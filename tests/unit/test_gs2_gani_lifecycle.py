"""Scripted animation lifecycle coverage for the client GS2 host."""

from types import SimpleNamespace

import pytest

from reborn_protocol.gs2 import FunctionEntry, GS2Container, Op
from pyreborn.gs2_client import ClientGS2, _csv_flatten


def _client(players=None, npcs=None):
    requests = []
    client = SimpleNamespace(
        player=SimpleNamespace(id=1, x=30.0, y=31.0, direction=2,
                               animation="idle", account="local"),
        players=players or {}, npcs=npcs or {}, x=30.0, y=31.0,
        weapons={}, connected=True, _authenticated=True, _in_update=False,
        _current_level_name="room.nw", gs2_host=None,
    )
    client.request_gani_bytecode = (
        lambda name, checksum=0: requests.append((name, checksum)) or True)
    return client, requests


def _events(*names):
    code = bytes([Op.OP_RET]) * (len(names) + 1)
    return GS2Container(
        functions=[FunctionEntry(name, index + 1)
                   for index, name in enumerate(names)],
        code=code,
    )


def _timeout_counter():
    strings = ["hit"]
    code = bytes([
        Op.OP_RET,
        Op.OP_THIS,
        Op.OP_TYPE_VAR, 0xF0, 0,
        Op.OP_MEMBER_ACCESS,
        Op.OP_INC,
        Op.OP_RET,
    ])
    return GS2Container(
        functions=[FunctionEntry("onTimeout", 1)],
        strings=strings,
        code=code,
    )


def test_attach_requests_code_and_fires_entry_with_params():
    client, requests = _client()
    rt2 = ClientGS2(client)
    seen = []
    original = rt2._run
    rt2._run = lambda vm, event, *args: seen.append((event, args))
    rt2.load_bytecode("gani", "glow",
                      _events("onCreated", "onPlayerEnters"))

    rt2.note_gani(("local", 1), "glow,red,large")

    assert requests == [("glow", 0)]
    assert seen == [("onCreated", ()), ("onPlayerEnters", ("red", "large"))]
    rt2._run = original


def test_refused_pre_auth_gani_request_is_retried_by_sync():
    client, requests = _client()
    client._authenticated = False
    client.request_gani_bytecode = lambda *args: False
    rt2 = ClientGS2(client)
    client.player.animation = "login"
    rt2.note_gani(("local", 1), "login")
    assert "login" not in rt2._requested_ganis

    client._authenticated = True
    client.request_gani_bytecode = (
        lambda name, checksum=0: requests.append((name, checksum)) or True)
    rt2.sync_gani_wearers()

    assert requests == [("login", 0)]
    assert "login" in rt2._requested_ganis


def test_trigger_csv_quotes_outbound_and_unquotes_inbound_tolerantly():
    assert _csv_flatten(["a,b", 'a"b', r"a\b"]) == [
        '"a,b"', '"a""b"', r'"a\\b"',
    ]
    client, _ = _client()
    rt2 = ClientGS2(client)
    seen = []
    rt2.trigger_event = lambda event, *args: seen.append((event, args))

    rt2.handle_triggeraction(r'event,"a,b","a""b","a\\b"')
    rt2.handle_triggeraction('"broken,raw')

    assert seen[0] == ("onActionevent", ("a,b", 'a"b', r"a\b"))
    assert seen[1] == ('onAction"broken', ("raw",))


def test_lighting_global_reads_through_after_script_write_and_renderer_toggle():
    client, _ = _client()
    rt2 = ClientGS2(client)
    rt2.game_shell = SimpleNamespace(_day_night_enabled=False)

    rt2.globals_store["lighteffectsenabled"] = 1
    assert rt2.game_shell._day_night_enabled is True
    rt2.game_shell._day_night_enabled = False
    assert rt2.globals_store["lighteffectsenabled"] == 0.0
    assert "lighteffectsenabled" not in dict(rt2.globals_store)


def test_late_code_arrival_attaches_and_refires_entry_on_reload():
    client, _ = _client()
    rt2 = ClientGS2(client)
    seen = []
    rt2._run = lambda vm, event, *args: seen.append((event, args))

    rt2.note_gani(("local", 1), "glow,first")
    assert seen == []
    rt2.load_bytecode("gani", "glow", _events("onPlayerEnters"))
    rt2.load_bytecode("gani", "glow", _events("onPlayerEnters"))

    assert seen == [
        ("onPlayerEnters", ("first",)),
        ("onPlayerEnters", ("first",)),
    ]


def test_current_params_are_supplied_to_events_without_explicit_args():
    client, _ = _client()
    rt2 = ClientGS2(client)
    rt2.load_bytecode("gani", "glow", _events("onTimeout"))
    rt2.note_gani(("local", 1), "glow,old")
    vm = rt2.vms["gani"][("local", 1)]
    seen = []
    vm.iter_call = lambda event, *args: seen.append((event, args)) or iter(())

    rt2._gani_worn[("local", 1)] = ("glow", ["new", "value"])
    rt2._run(vm, "onTimeout")

    assert seen == [("onTimeout", ("new", "value"))]


def test_each_wearer_has_an_independent_hidden_object():
    players = {
        2: {"ani": "glow", "x": 4.0, "y": 5.0, "direction": 1},
        3: {"ani": "glow", "x": 8.0, "y": 9.0, "direction": 3},
    }
    client, _ = _client(players=players)
    rt2 = ClientGS2(client)
    rt2.load_bytecode("gani", "glow", GS2Container())
    rt2.sync_gani_wearers()

    first = rt2.vms["gani"][("player", 2)]
    second = rt2.vms["gani"][("player", 3)]
    first.this.set("private", 7)

    assert first is not second
    assert first.this is not second.this
    assert second.this.get("private") is None


def test_animation_change_clears_layers_and_cancels_timer():
    client, _ = _client()
    gs1 = SimpleNamespace(_weapon_imgs={})
    rt2 = ClientGS2(client, gs1=gs1)
    rt2.load_bytecode("gani", "glow", GS2Container())
    rt2.note_gani(("local", 1), "glow")
    vm = rt2.vms["gani"][("local", 1)]
    key = rt2._timeout_key(vm)
    layer_key = f"gs2_gani_{key[1]}"
    gs1._weapon_imgs[layer_key] = {1: {"image": "light.png"}}
    rt2._timeouts[key] = 1.0

    rt2.note_gani(("local", 1), "idle")

    assert layer_key not in gs1._weapon_imgs
    assert key not in rt2._timeouts
    assert ("local", 1) not in rt2.vms["gani"]


def test_hidden_object_state_is_pruned_on_detach_and_id_reuse():
    client, _ = _client()
    rt2 = ClientGS2(client)
    rt2.load_bytecode("gani", "first", GS2Container())
    rt2.load_bytecode("gani", "second", GS2Container())
    rt2.note_gani(("local", 1), "first")
    original = rt2.vms["gani"][("local", 1)].this
    original.set("kept", 4)

    rt2.note_gani(("local", 1), "idle")
    rt2.note_gani(("local", 1), "second")

    reused = rt2.vms["gani"][("local", 1)].this
    assert reused is not original
    assert reused.get("kept") is None
    assert (("local", 1), "first") not in rt2._gani_created


def test_remote_id_reuse_gets_fresh_this_and_created_event():
    players = {
        2: {"account": "first", "ani": "glow", "x": 4.0, "y": 5.0},
    }
    client, _ = _client(players=players)
    rt2 = ClientGS2(client)
    seen = []
    original_run = rt2._run
    rt2._run = lambda vm, event, *args: seen.append(event)
    rt2.load_bytecode("gani", "glow", _events("onCreated"))
    rt2.sync_gani_wearers()
    first_this = rt2.vms["gani"][("player", 2)].this
    first_this.set("old", 1)

    players[2] = {"account": "second", "ani": "glow", "x": 8.0, "y": 9.0}
    rt2.sync_gani_wearers()
    second_this = rt2.vms["gani"][("player", 2)].this

    assert second_this is not first_this
    assert second_this.get("old") is None
    assert seen.count("onCreated") == 2
    rt2._run = original_run


def test_timeout_uses_existing_timer_pump():
    client, _ = _client()
    rt2 = ClientGS2(client)
    rt2.load_bytecode("gani", "glow", _timeout_counter())
    client.player.animation = "glow"
    rt2.note_gani(("local", 1), "glow")
    vm = rt2.vms["gani"][("local", 1)]
    rt2._timeouts[rt2._timeout_key(vm)] = 0.01

    rt2.process_timeouts(0.02)

    assert vm.this.get("hit") == pytest.approx(1.0)


def test_hidden_object_position_mirrors_wearer_before_each_event():
    players = {
        2: {"ani": "glow", "x": 4.0, "y": 5.0, "direction": 1},
    }
    client, _ = _client(players=players)
    rt2 = ClientGS2(client)
    rt2.load_bytecode("gani", "glow", _events("onTimeout"))
    rt2.sync_gani_wearers()
    vm = rt2.vms["gani"][("player", 2)]
    vm.this.set("x", 99)
    players[2].update(x=12.0, y=14.0, direction=3)

    rt2._run(vm, "onTimeout")

    assert vm.this.get("x") == pytest.approx(12.0)
    assert vm.this.get("y") == pytest.approx(14.0)
    assert vm.this.get("dir") == pytest.approx(3.0)


def test_remote_player_and_npc_player_objects_refresh_from_live_wearer():
    players = {2: {"ani": "glow", "x": 4.0, "y": 5.0, "direction": 1}}
    npcs = {8: {"gani": "glow", "x": 6.0, "y": 7.0, "direction": 2}}
    client, _ = _client(players=players, npcs=npcs)
    rt2 = ClientGS2(client)
    rt2.load_bytecode("gani", "glow", _events("onTimeout"))
    rt2.sync_gani_wearers()
    player_vm = rt2.vms["gani"][("player", 2)]
    npc_vm = rt2.vms["gani"][("npc", 8)]
    players[2].update(x=14.0, direction=3)
    npcs[8].update(x=16.0, direction=0)

    rt2._run(player_vm, "onTimeout")
    rt2._run(npc_vm, "onTimeout")

    assert player_vm._gs2_player.get("x") == pytest.approx(14.0)
    assert player_vm._gs2_player.get("dir") == pytest.approx(3.0)
    assert npc_vm._gs2_player.get("x") == pytest.approx(16.0)
    assert npc_vm._gs2_player is not rt2.player_object


def test_timeout_handler_freeing_another_vm_does_not_crash_the_step():
    """A fired onTimeout may tear down another armed VM mid-step (a script
    changing the player's gani makes _free_gani_vm pop that VM's _timeouts
    entry from under the snapshot the step iterates). The stale key must be
    skipped, not raise KeyError -- live crash on the Zelda server,
    2026-08-05, key ('gani', ('local', 0))."""
    client, _ = _client()
    rt2 = ClientGS2(client)
    rt2.load_bytecode("weapon", "a", _events("onTimeout"))
    rt2.load_bytecode("weapon", "b", _events("onTimeout"))
    rt2._timeouts[("weapon", "a")] = 0.005
    rt2._timeouts[("weapon", "b")] = 0.005
    fired = []

    def run(vm, event, *args):
        fired.append(event)
        for key in list(rt2._timeouts):    # the teardown-during-step
            rt2._timeouts.pop(key, None)

    rt2._run = run
    rt2._process_timeout_step(0.01)

    assert fired == ["onTimeout"]
