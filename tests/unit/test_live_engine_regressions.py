from types import SimpleNamespace

from reborn_protocol.gs1.runtime import UNSET
from reborn_protocol.gs2 import gs2_eq

from pyreborn.client import Client
from pyreborn.gs1_client import ClientGS1
from pyreborn.gs2_client import ClientGS2
from pyreborn.packets import parse_npc_props, parse_player_props


def test_bare_players_tiles_and_value_builtins():
    client = Client("localhost", 14900)
    client.player.account = "local"
    client.player.nickname = "Local"
    client.player.x, client.player.y = 4, 5
    client.player.direction = 3
    client.players = {
        7: {"account": "other", "nickname": "Other", "chat": "hi",
            "x": 8, "y": 9},
    }
    client.tiles = list(range(4096))
    gs1 = ClientGS1(client)
    rt = ClientGS2(client, gs1)

    players = rt.host.get_object("players")
    assert [p.get("account") for p in players] == ["local", "other"]
    assert rt.host.get_object("playerscount") == 2
    assert rt.host.get_object("playerx") == 4
    assert rt.host.get_object("playerdir") == 3
    tiles = rt.host.get_object("tiles")
    assert tiles[3][2] == float(2 * 64 + 3)
    assert rt.tiles_view() is tiles
    client.tiles = [1] * 4096
    assert rt.tiles_view() is not tiles
    assert rt.host.get_object("missing_value") is None
    assert gs1._host.get_builtin(
        "missing_value", [], rt._gs1_ctx(None)) is UNSET


def test_npc_colors_width_retry_keeps_following_property_aligned():
    data = bytes([32, 32, 33, 51, 33, 34, 35, 36, 37, 52, 35]) + b"abc"
    diagnostics = {}
    props = parse_npc_props(data, 8, diagnostics)
    assert props["colors"] == [1, 2, 3, 4, 5]
    assert props["nickname"] == "abc"
    assert diagnostics["width_fallbacks"] == 1


def test_npc_entry_events_repeat_in_order_per_visit():
    client = SimpleNamespace(_current_level_name="room.nw",
                             npcs={4: {"_level": "room.nw"}})
    rt = ClientGS2(client)
    seen = []
    vm = SimpleNamespace(
        has_function=lambda name: name in ("onCreated", "onPlayerEnters"))
    rt.vms["npc"][4] = vm
    rt._run = lambda unused, event, *args: seen.append(event)
    rt.pump_level_events()
    rt.pump_level_events()
    rt.begin_level_visit()
    rt.pump_level_events()
    assert seen == [
        "onCreated", "onPlayerEnters", "onCreated", "onPlayerEnters"]


def test_local_player_id_and_level_object_forms():
    props = parse_player_props(bytes([46, 32, 41]))
    client = Client("localhost", 14900)
    client.player.update_from_props(props)
    client.player.level = "room.nw"
    level = ClientGS2(client).player_object.get("level")
    assert client.player.id == 9
    assert ClientGS2(client).player_object.get("id") == 9
    assert level.get("name") == "room.nw"
    assert gs2_eq(level, "room.nw")


def test_runtime_npc_effect_commands_store_values():
    client = Client("localhost", 14900)
    client.npcs[5] = {}
    gs1 = ClientGS1(client)
    ctx = SimpleNamespace(this_obj=client.npcs[5])
    gs1._host.call_command("setzoomeffect", [2.5], ctx)
    gs1._host.call_command("seteffectmode", [2], ctx)
    gs1._host.call_command("setcoloreffect", [1, .5, .25, .75], ctx)
    assert client.npcs[5]["zoom_effect"] == 2.5
    assert client.npcs[5]["effect_mode"] == 2
    assert client.npcs[5]["coloreffect"] == (1, .5, .25, .75)


def test_server_replica_prefers_prefixed_then_bare_flags():
    rt = ClientGS2()
    rt.gs1 = SimpleNamespace(_shared={"server": {
        "serverr.lobby": "replica", "bombrush": "bare"}})
    scope = rt.flag_scope_object("serverr")
    assert scope.get("lobby") == "replica"
    assert scope.get("bombrush") == "bare"
    assert scope.has("lobby") and scope.has("bombrush")


def test_nearest_player_indices_read_wire_records():
    """getnearestplayers() ranks the DICT-shaped wire records too (they are
    what parse_other_player stores), and answers players[] indices --
    players[0] is always us, so the remotes here are 1 and 2 in insertion
    order and rank 2, 1 by distance from (0, 0)."""
    client = SimpleNamespace(player=SimpleNamespace(x=40, y=40), x=40, y=40,
                             players={
                                 2: {"x": 8, "y": 6, "account": "far"},
                                 1: {"x": 2, "y": 1, "account": "near"},
                             })
    rt = ClientGS2(client)
    assert rt.nearest_player_indices(0, 0) == [2.0, 1.0, 0.0]
    assert rt.player_positions() == [(40, 40), (8, 6), (2, 1)]


def test_serverlist_string_globals_answer_as_strings_not_unset():
    """2026-07-25 outage: the Login server list came up EMPTY.

    `serverstartconnect` was unanswered, so it resolved to the lattice's
    NUMBER 0.0 -- and the official number/string rule is
    compareNumberValues(0.0, strtofloat(s)) (TScriptMachine::compare,
    Preagonal/FourPlay/quattroplay/src/TScriptMachine.cpp:1463), where
    strtofloat of a non-numeric string is 0.0. So an unset global compared
    EQUAL TO EVERY WORD. initServerlist() hit
    `if (serverstartconnect == "skills")`
    (Preagonal/graal-loginserver/weapons/weapon-Rescripted_Serverlist.txt:85),
    rewrote it to "login3", fell into the `!= ""` arm at :106 and ran
    `Serverlist_Panel.visible = false; serverwarp("login3");` with
    donormallogin = false -- so sendServerListRequest() at :121 never ran.

    The reference allocates all four TServerList globals as TStrings up front
    (TInitStatics.cpp:4928-4937), so an untouched one is the EMPTY STRING and
    is compared with strcasecmp.
    """
    client = Client("localhost", 14900)
    gs1 = ClientGS1(client)
    rt = ClientGS2(client, gs1)

    for name in ("serverstartconnect", "serverstartparams", "serveraddr"):
        value = rt.host.get_object(name)
        assert value == "", (name, value)
        assert isinstance(value, str), name
        # the branches initServerlist() actually takes
        for word in ("skills", "playerworlds", "zone", "kingdoms"):
            assert not gs2_eq(value, word), f"{name} == {word!r}"
        # ...while the guard the script relies on still holds
        assert gs2_eq(value, "")


def test_unset_global_does_not_equal_words_under_faithful_strtofloat():
    """An unanswered name resolves to Number 0.0, and official strtofloat of
    a string strtod can't parse is -1.0 (TInitStatics.cpp:4377-4380) — so
    0.0 == "word" is FALSE. Host seeding (T1) remains correct fidelity
    because the reference seeds these globals, but the old "an unanswered
    name equals every word" mechanism was a misreading and is gone.
    """
    assert not gs2_eq(None, "skills")
    assert not gs2_eq(None, "anything at all")
    assert gs2_eq(None, "")  # "" -> 0.0, matches an unanswered name
    assert not gs2_eq("", "skills")
