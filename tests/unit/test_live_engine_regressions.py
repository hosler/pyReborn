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


def test_nearest_players_reads_wire_records():
    client = SimpleNamespace(players={
        2: {"x": 8, "y": 6, "account": "far", "nickname": "Far"},
        1: {"x": 2, "y": 1, "account": "near", "nickname": "Near"},
    })
    nearest = ClientGS2(client).nearest_players(0, 0)
    assert [p.get("id") for p in nearest] == [1, 2]
    assert nearest[0].get("account") == "near"
