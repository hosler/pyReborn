"""NPC, level, and weapon client-script surfaces verified in wave 5."""

from types import SimpleNamespace

from reborn_protocol.gs2 import GS2Object

from pyreborn.gs1_client import ClientGS1
from pyreborn.gs2_client import ClientGS2, _NpcThisObject
from pyreborn.player import Player


def runtime(**overrides):
    values = dict(player=Player(), players={}, npcs={}, weapons={},
                  board_layers={}, gmap_grid={}, gmap_width=0, gmap_height=0,
                  _current_level_name="room.nw", signs={}, items={}, bombs={})
    values.update(overrides)
    client = SimpleNamespace(**values)
    return ClientGS2(client, ClientGS1(client))


def call(rt, name, args=(), obj=None):
    return rt.host.call_builtin(None, name, list(args), obj=obj)


def npc_object(rt, npc_id):
    obj = _NpcThisObject(rt, ("npc", npc_id))
    rt.vms["npc"][npc_id] = SimpleNamespace(this=obj)
    return obj


def test_npcsindex_and_npc_constructor_properties_use_live_store():
    rt = runtime(npcs={20: {"x": 2, "y": 3}, 10: {"x": 8, "y": 9}})
    first, second = npc_object(rt, 20), npc_object(rt, 10)
    assert first.get("npcsindex") == 0.0
    assert second.get("npcsindex") == 1.0
    assert first.get("actionplayer") == -2.0
    assert first.get("isblocking") == 1.0
    assert first.get("isblockingprojectiles") == 1.0
    assert first.get("save") == [0.0] * 10
    assert not any(first.get(name) for name in (
        "peltwithnpc", "peltwithbush", "peltwithsign", "peltwithvase",
        "peltwithstone", "peltwithblackstone"))


def test_npc_blocking_properties_bridge_real_collision_state():
    rt = runtime(npcs={4: {"x": 1, "y": 1}})
    npc = npc_object(rt, 4)
    npc.set("isblocking", 0)
    npc.set("isblockingprojectiles", 0)
    assert rt.client.npcs[4]["dontblock"] is True
    assert rt.client.npcs[4]["blocks_projectiles"] is False
    assert npc.get("isblocking") == npc.get("isblockingprojectiles") == 0.0


def test_findareanpcs_uses_world_positions_and_half_open_rectangle():
    rt = runtime(npcs={
        1: {"x": 1, "y": 1, "world_x": 65, "world_y": 2},
        2: {"x": 3, "y": 4, "world_x": 69.9, "world_y": 5.9},
        3: {"x": 6, "y": 4, "world_x": 70, "world_y": 4},
    })
    wanted = [npc_object(rt, npc_id) for npc_id in rt.client.npcs]
    found = call(rt, "findareanpcs", [65, 2, 5, 4], rt.level_object)
    assert found == wanted[:2]


def test_getmappartfile_uses_floor_segment_math_including_negative_coords():
    grid = {(-2, -1): "negative.nw", (1, 2): "positive.nw"}
    rt = runtime(gmap_grid=grid, gmap_width=4, gmap_height=4)
    assert call(rt, "getmappartfile", [-64.01, -0.01], rt.level_object) == \
        "negative.nw"
    assert call(rt, "getmappartfile", [64, 128], rt.level_object) == \
        "positive.nw"
    assert call(rt, "getmappartfile", [0, 0], rt.level_object) == ""


def test_level_flags_alias_and_reference_defaults():
    rt = runtime()
    level = rt.level_object
    assert level.get("preloadleveldefaulttile") == 0.0
    assert level.get("isnopkzone") == level.get("nopkzone") == 0.0
    assert level.get("issparringzone") == 0.0
    level.set("nopkzone", 1)
    assert level.get("isnopkzone") == level.get("nopkzone") == 1.0
    level.set("issparringzone", 1)
    assert level.get("issparringzone") == 0.0


def test_putbomb2_reuses_putbomb_placement_without_consuming_ammo():
    calls = []
    rt = runtime()
    rt.client.put_bomb = lambda x, y, power, consume_ammo: calls.append(
        (x, y, power, consume_ammo))
    call(rt, "putbomb2", [3, 12.5, 9.0, "custom.png"], rt.level_object)
    assert calls == [(12.5, 9.0, 3, False)]


def test_isweapon_distinguishes_weapon_npc_and_plain_objects():
    rt = runtime(npcs={7: {}})
    from pyreborn.gs2_client.objects_player import _ThisObject
    weapon_this = _ThisObject(rt, ("weapon", "bow"))
    npc_this = npc_object(rt, 7)
    assert weapon_this.get("isweapon") == 1.0
    assert npc_this.get("isweapon") == 0.0
    assert GS2Object().get("isweapon") is None
