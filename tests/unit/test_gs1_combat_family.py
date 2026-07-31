"""Client-side scripted combat family (GTA corpus wave): hurt / hitplayer /
hitcompu / hitnpc / hitobjects, putbomb / putexplosion(2) / explodebomb /
removebomb / removeexplo, lay / lay2, setbackpal, and the bombs[] / explos[] /
compus[] script arrays.

Oracle notes (grep-verified):
- wire ops: PLI_BOMBADD/BOMBDEL/EXPLOSION/ITEMADD/HURTPLAYER/BADDYHURT/
  HITOBJECTS readers in GServer-v2 PlayerClientPackets.cpp (msgPLI_BOMBADD
  :215-242, msgPLI_EXPLOSION :840-861, msgPLI_ITEMADD :345-349,
  msgPLI_HURTPLAYER :819-838).
- damage units are HALF-hearts, floored (GS1Commands.cpp fn_hurt :1423-1442,
fn_hitplayer :1396-1419, fn_hitnpc :1327-1368). GTA heals through negative
  amounts (`hurt -3` fountains), clamped to max hearts.
- players[0] is the LOCAL player. FourPlay's hitplayer applies the local
  branch directly (Preagonal/FourPlay/quattroplay/src/TInitStatics.cpp
  :3447-3464) and reports remote hits over the wire.
- explosion hitbox is a BOX with an INCLUSIVE boundary and damage is
  power*2 half-hearts (pygserver gs1/commands/combat.py _explode /
  _explosion_targets, pinned there by tests/test_gs1_audience.py).
- setbackpal swaps the tileset's 256-color palette for the named file's
  (scripting-gs1-commands.md:1715). The pal files are tiny indexed PNGs.
"""

import os
import sys

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

from pyreborn import Client
from pyreborn.gs1_client import ClientGS1
from pyreborn.packets import (
    PacketID, build_attack_player, build_baddy_hurt, build_bomb_add,
    build_bomb_del, build_explosion_add, build_hit_objects, build_item_add)


class _SentRecorder:
    connected = True

    def __init__(self):
        self.sent = []

    def send_packet(self, packet_id, data=b""):
        self.sent.append((int(packet_id), bytes(data)))
        return True


def _fake_connected_client():
    c = Client("localhost", 14900)
    c._authenticated = True
    c._protocol = _SentRecorder()
    return c


def _npc_gs1(client, npc_id, script, x=30.0, y=30.0):
    client.npcs.setdefault(npc_id, {"x": x, "y": y, "script": script})
    gs1 = ClientGS1(client)
    gs1.load_script(f"npc_{npc_id}", script, npc_id=npc_id, x=x, y=y)
    return gs1


def _sent(client, pli):
    return [d for (pid, d) in client._protocol.sent if pid == int(pli)]


# -- wire builders ----------------------------------------------------------

def test_build_explosion_add_wire_bytes():
    # {GUChar radius}{GUChar x*2}{GUChar y*2}{GUChar power}
    assert build_explosion_add(2, 30.5, 12, 3) == bytes(
        [2 + 32, 61 + 32, 24 + 32, 3 + 32])


def test_build_item_add_wire_bytes():
    # {GUChar x*2}{GUChar y*2}{GUChar item_id}
    assert build_item_add(30, 31.5, 5) == bytes([60 + 32, 63 + 32, 5 + 32])


# -- hurt -------------------------------------------------------------------

def test_hurt_takes_halfhearts_and_reports_props():
    client = _fake_connected_client()
    client.player.hearts = 3.0
    gs1 = _npc_gs1(client, 5, "if (playertouchsme) { hurt 1; }")
    gs1.trigger_npc_event(5, "playertouchsme")
    assert client.player.hearts == 2.5
    # respond_to_hurt sent the CURPOWER/gani props report
    assert _sent(client, PacketID.PLI_PLAYERPROPS)


def test_hurt_floors_fractional_halfhearts():
    client = _fake_connected_client()
    client.player.hearts = 3.0
    gs1 = _npc_gs1(client, 5, "if (playertouchsme) { hurt 1.9; }")
    gs1.trigger_npc_event(5, "playertouchsme")
    assert client.player.hearts == 2.5


def test_hurt_clamps_at_zero():
    client = _fake_connected_client()
    client.player.hearts = 0.5
    gs1 = _npc_gs1(client, 5, "if (playertouchsme) { hurt 99; }")
    gs1.trigger_npc_event(5, "playertouchsme")
    assert client.player.hearts == 0.0


def test_hurt_negative_heals_clamped_to_max():
    # GTA's healing fountains do `hurt -3` (uwwatershrine & co).
    client = _fake_connected_client()
    client.player.hearts = 2.0
    client.player.max_hearts = 3.0
    gs1 = _npc_gs1(client, 5, "if (playertouchsme) { hurt -9; }")
    gs1.trigger_npc_event(5, "playertouchsme")
    assert client.player.hearts == 3.0
    assert _sent(client, PacketID.PLI_PLAYERPROPS)   # bare CURPOWER report


def test_hurt_fires_on_hurt_presentation_callback():
    client = _fake_connected_client()
    seen = []
    client.on_hurt = lambda *a: seen.append(a)
    gs1 = _npc_gs1(client, 5, "if (playertouchsme) { hurt 2; }")
    gs1.trigger_npc_event(5, "playertouchsme")
    assert seen and seen[0][1] == 1.0    # damage in hearts


# -- hitplayer --------------------------------------------------------------

def test_hitplayer_index_zero_is_local_player():
    client = _fake_connected_client()
    client.player.hearts = 3.0
    gs1 = _npc_gs1(client, 5, "if (playertouchsme) { hitplayer 0,2,x,y; }")
    gs1.trigger_npc_event(5, "playertouchsme")
    assert client.player.hearts == 2.0
    assert not _sent(client, PacketID.PLI_HURTPLAYER)   # local, no relay


def test_hitplayer_remote_index_relays_pli_hurtplayer():
    client = _fake_connected_client()
    client.players[77] = {"x": 33.0, "y": 30.0, "account": "other"}
    gs1 = _npc_gs1(client, 5, "if (playertouchsme) { hitplayer 1,2,30,30; }",
                   x=30.0, y=30.0)
    gs1.trigger_npc_event(5, "playertouchsme")
    # push dir = normalized(target - from) = (+1, 0); knockback = dir*2
    assert _sent(client, PacketID.PLI_HURTPLAYER) == [
        build_attack_player(77, 2, 0, 1.0)]
    assert client.player.hearts == 3.0   # local player untouched


def test_hitplayer_out_of_range_index_is_noop():
    client = _fake_connected_client()
    gs1 = _npc_gs1(client, 5, "if (playertouchsme) { hitplayer 4,2,30,30; }")
    gs1.trigger_npc_event(5, "playertouchsme")
    assert not _sent(client, PacketID.PLI_HURTPLAYER)


# -- hitcompu ---------------------------------------------------------------

def test_hitcompu_as_leader_applies_and_broadcasts():
    client = _fake_connected_client()
    client.is_leader = True
    client.baddies[0] = {"x": 20.0, "y": 20.0, "power": 4, "image": "baddy.png"}
    gs1 = _npc_gs1(client, 5,
                   "if (playertouchsme) { hitcompu 0,3,21,20; }")
    gs1.trigger_npc_event(5, "playertouchsme")
    assert client.baddies[0]["power"] == 1     # 3 half-hearts of baddy power
    assert _sent(client, PacketID.PLI_BADDYPROPS)


def test_hitcompu_as_non_leader_sends_baddyhurt():
    client = _fake_connected_client()
    client.is_leader = False
    client.baddies[0] = {"x": 22.0, "y": 20.0, "power": 4}
    gs1 = _npc_gs1(client, 5,
                   "if (playertouchsme) { hitcompu 0,2,20,20; }")
    gs1.trigger_npc_event(5, "playertouchsme")
    # dir = normalized((22,20)-(20,20)) = (1, 0); damage 2 halfhearts = 1 heart
    assert _sent(client, PacketID.PLI_BADDYHURT) == [
        build_baddy_hurt(0, 1.0, 1.0, 0.0)]


# -- hitnpc -----------------------------------------------------------------

def test_hitnpc_fires_washit_and_decrements_power():
    client = _fake_connected_client()
    gs1 = _npc_gs1(client, 5,
                   "if (washit) { this.gothit = 1; }", x=20.0, y=20.0)
    client.npcs[5]["power"] = 6
    striker = ("if (playertouchsme) { hitnpc 0,2,18,20; }")
    client.npcs[9] = {"x": 30.0, "y": 30.0, "script": striker}
    gs1.load_script("npc_9", striker, npc_id=9, x=30.0, y=30.0)
    gs1.trigger_npc_event(9, "playertouchsme")
    assert client.npcs[5]["power"] == 4
    assert gs1._progs["npc_5"]["scopes"]["this"].get("gothit") == 1


def test_hitnpc_sets_hurt_gani_only_for_character_npcs():
    client = _fake_connected_client()
    striker = "if (playertouchsme) { hitnpc 0,1,0,0; }"
    gs1 = _npc_gs1(client, 5, striker, x=20.0, y=20.0)
    client.npcs[5]["gani"] = "idle"
    # lower id sorts first -> npcs[0] is npc 3
    client.npcs[3] = {"x": 10.0, "y": 10.0, "script": ""}
    gs1.trigger_npc_event(5, "playertouchsme")
    assert "gani" not in client.npcs[3]       # image NPC: no hurt pose
    client.npcs.pop(3)
    gs1.trigger_npc_event(5, "playertouchsme")
    assert client.npcs[5]["gani"] == "hurt"   # character NPC


# -- hitobjects wire half ---------------------------------------------------

def test_hitobjects_sends_wire_probe_and_hits_local_baddies():
    client = _fake_connected_client()
    client.is_leader = False
    client.baddies[0] = {"x": 25.0, "y": 25.0, "power": 3}
    gs1 = _npc_gs1(client, 5,
                   "if (playertouchsme) { hitobjects 1,25,25; }")
    gs1.trigger_npc_event(5, "playertouchsme")
    assert _sent(client, PacketID.PLI_HITOBJECTS) == [
        build_hit_objects(1, 25, 25)]
    assert _sent(client, PacketID.PLI_BADDYHURT)


# -- putbomb ----------------------------------------------------------------

def test_putbomb_sends_wire_and_spawns_via_callback():
    client = _fake_connected_client()
    client.player.bombs = 0            # scripted bombs are ammo-free
    spawned = []
    gs1 = _npc_gs1(client, 5, "if (playertouchsme) { putbomb 1,20,20; }")
    gs1.on_putbomb = lambda *a: spawned.append(a)
    gs1.trigger_npc_event(5, "playertouchsme")
    assert _sent(client, PacketID.PLI_BOMBADD) == [
        build_bomb_add(20, 20, 1, 3050)]
    assert spawned == [(1, 20.0, 20.0, 3.0)]
    assert client.player.bombs == 0    # no ammo touched, no BOMBSCOUNT report


def test_putbomb_on_water_splashes_instead():
    client = _fake_connected_client()
    leaps = []
    spawned = []
    gs1 = _npc_gs1(client, 5, "if (playertouchsme) { putbomb 1,20,20; }")
    gs1.on_putbomb = lambda *a: spawned.append(a)
    gs1.on_putleaps = lambda *a: leaps.append(a)
    gs1.is_water_at = lambda x, y: True
    gs1.trigger_npc_event(5, "playertouchsme")
    assert leaps == [(5, 20.0, 20.0)]  # type 5 = water splash
    assert not spawned
    # the server is still informed (reference behavior)
    assert _sent(client, PacketID.PLI_BOMBADD)


# -- bombs[] / explodebomb / removebomb -------------------------------------

def _with_bombs(gs1, bombs):
    gs1.bombs_source = lambda: bombs
    return bombs


def test_bombs_array_reads():
    client = _fake_connected_client()
    gs1 = _npc_gs1(client, 5, """if (playertouchsme) {
  this.n = bombscount;
  this.px = bombs[1].x;
  this.pw = bombs[1].power;
}""")
    _with_bombs(gs1, [
        {"x": 10.0, "y": 11.0, "power": 1, "time": 0, "fuse_time": 3.0},
        {"x": 20.5, "y": 21.0, "power": 3, "time": 0, "fuse_time": 3.0},
    ])
    gs1.trigger_npc_event(5, "playertouchsme")
    this = gs1._progs["npc_5"]["scopes"]["this"]
    assert this.get("n") == 2.0
    assert this.get("px") == 20.5
    assert this.get("pw") == 3.0


def test_removebomb_removes_silently_and_sends_bombdel():
    client = _fake_connected_client()
    gs1 = _npc_gs1(client, 5, "if (playertouchsme) { removebomb 0; }")
    bombs = _with_bombs(gs1, [
        {"x": 10.0, "y": 11.0, "power": 1, "time": 0, "fuse_time": 3.0}])
    removed = []
    gs1.on_removebomb = lambda bomb, explode: removed.append((bomb, explode))
    gs1.trigger_npc_event(5, "playertouchsme")
    assert _sent(client, PacketID.PLI_BOMBDEL) == [build_bomb_del(10, 11)]
    assert removed == [(bombs[0], False)]


def test_explodebomb_bursts_now():
    client = _fake_connected_client()
    gs1 = _npc_gs1(client, 5, "if (playertouchsme) { explodebomb 0; }")
    bombs = _with_bombs(gs1, [
        {"x": 10.0, "y": 11.0, "power": 1, "time": 0, "fuse_time": 3.0}])
    removed = []
    gs1.on_removebomb = lambda bomb, explode: removed.append((bomb, explode))
    gs1.trigger_npc_event(5, "playertouchsme")
    assert removed == [(bombs[0], True)]
    assert _sent(client, PacketID.PLI_BOMBDEL)


def test_exploded_bombs_leave_the_script_array():
    client = _fake_connected_client()
    gs1 = ClientGS1(client)
    gs1.bombs_source = lambda: [
        {"x": 1, "y": 1, "power": 1, "exploded": True},
        {"x": 2, "y": 2, "power": 2},
    ]
    assert gs1._host._bomb_list() == [{"x": 2, "y": 2, "power": 2}]


# -- putexplosion / putexplosion2 / removeexplo / explos[] ------------------

def test_putexplosion_wire_and_visual():
    client = _fake_connected_client()
    client.player.x = 50.0
    client.player.y = 50.0
    gs1 = _npc_gs1(client, 5, "if (playertouchsme) { putexplosion 1,20,20; }")
    gs1.trigger_npc_event(5, "playertouchsme")
    assert _sent(client, PacketID.PLI_EXPLOSION) == [
        build_explosion_add(1, 20, 20, 1)]
    assert len(client.active_explosions) == 1
    exp = client.active_explosions[0]
    assert (exp["x"], exp["y"], exp["radius"], exp["power"]) == (20, 20, 1, 1)


def test_putexplosion2_arg_order_is_power_radius_x_y():
    # GTA's standard trap: `putexplosion2 3,2, x, y` (132 uses)
    client = _fake_connected_client()
    gs1 = _npc_gs1(client, 5,
                   "if (playertouchsme) { putexplosion2 3,2,20,20; }")
    gs1.trigger_npc_event(5, "playertouchsme")
    assert _sent(client, PacketID.PLI_EXPLOSION) == [
        build_explosion_add(2, 20, 20, 3)]


def test_putexplosion_damages_local_player_box_inclusive():
    client = _fake_connected_client()
    # exactly radius away on one axis: INCLUSIVE boundary -> hit
    client.player.hearts = 3.0
    client.player.x = 22.0
    client.player.y = 20.0
    gs1 = _npc_gs1(client, 5,
                   "if (playertouchsme) { putexplosion2 1,2,20,20; }")
    gs1.trigger_npc_event(5, "playertouchsme")
    assert client.player.hearts == 2.0     # power 1 = 2 half-hearts = 1 heart


def test_putexplosion_misses_outside_radius():
    client = _fake_connected_client()
    client.player.hearts = 3.0
    client.player.x = 23.5
    client.player.y = 20.0
    gs1 = _npc_gs1(client, 5,
                   "if (playertouchsme) { putexplosion2 1,2,20,20; }")
    gs1.trigger_npc_event(5, "playertouchsme")
    assert client.player.hearts == 3.0


def test_putexplosion_fires_washit_on_covered_npcs():
    client = _fake_connected_client()
    gs1 = _npc_gs1(client, 5, "if (washit) { this.boomed = 1; }",
                   x=21.0, y=21.0)
    trap = "if (playertouchsme) { putexplosion2 1,2,20,20; }"
    client.npcs[9] = {"x": 40.0, "y": 40.0, "script": trap}
    gs1.load_script("npc_9", trap, npc_id=9, x=40.0, y=40.0)
    gs1.trigger_npc_event(9, "playertouchsme")
    assert gs1._progs["npc_5"]["scopes"]["this"].get("boomed") == 1


def test_explos_array_reads_and_removeexplo():
    client = _fake_connected_client()
    gs1 = _npc_gs1(client, 5, """if (playertouchsme) {
  this.n = exploscount;
  this.pw = explos[0].power;
  removeexplo 0;
}""")
    client.active_explosions.append(
        {"x": 5.0, "y": 6.0, "radius": 2, "power": 3, "time": 0})
    gs1.trigger_npc_event(5, "playertouchsme")
    this = gs1._progs["npc_5"]["scopes"]["this"]
    assert this.get("n") == 1.0
    assert this.get("pw") == 3.0
    assert client.active_explosions == []


# -- compus[] reads ---------------------------------------------------------

def test_compus_array_reads():
    client = _fake_connected_client()
    client.baddies[0] = {"x": 8.0, "y": 53.5, "power": 2, "mode": 1,
                         "type": 3, "direction": 2}
    client.baddies[1] = {"x": 9.0, "y": 10.0, "power": 4, "mode": 0}
    gs1 = _npc_gs1(client, 5, """if (playertouchsme) {
  this.n = compuscount;
  this.y0 = compus[0].y;
  this.m0 = compus[0].mode;
  this.d0 = compus[0].dir;
  this.p1 = compus[1].power;
}""")
    gs1.trigger_npc_event(5, "playertouchsme")
    this = gs1._progs["npc_5"]["scopes"]["this"]
    assert this.get("n") == 2.0
    assert this.get("y0") == 53.5
    assert this.get("m0") == 1.0
    assert this.get("d0") == 2.0
    assert this.get("p1") == 4.0


# -- lay / lay2 -------------------------------------------------------------

def test_lay_drops_item_at_npc_feet():
    client = _fake_connected_client()
    gs1 = _npc_gs1(client, 5, "if (playertouchsme) { lay bombs; }",
                   x=12.0, y=14.0)
    gs1.trigger_npc_event(5, "playertouchsme")
    # bombs = LevelItemType 3 (scripting-gs1-variables.md "Item names")
    assert _sent(client, PacketID.PLI_ITEMADD) == [build_item_add(12, 14, 3)]
    assert client.items_in_level(client._current_level_name)[(12.0, 14.0)] == "bombs"


def test_lay2_drops_item_at_position():
    client = _fake_connected_client()
    gs1 = _npc_gs1(client, 5, "if (playertouchsme) { lay2 heart,30,31; }")
    gs1.trigger_npc_event(5, "playertouchsme")
    assert _sent(client, PacketID.PLI_ITEMADD) == [build_item_add(30, 31, 5)]
    assert client.items_in_level(client._current_level_name)[(30.0, 31.0)] == "heart"


def test_lay_unknown_item_is_noop():
    client = _fake_connected_client()
    gs1 = _npc_gs1(client, 5, "if (playertouchsme) { lay nosuchthing; }")
    gs1.trigger_npc_event(5, "playertouchsme")
    assert not _sent(client, PacketID.PLI_ITEMADD)
    assert client.items == {}


# -- setbackpal -------------------------------------------------------------

def test_setbackpal_fires_callback_with_trimmed_name():
    client = _fake_connected_client()
    pals = []
    gs1 = _npc_gs1(client, 5,
                   "if (playerenters) { setbackpal underwaterpal.png; }")
    gs1.on_setbackpal = pals.append
    gs1.trigger_npc_event(5, "playerenters")
    assert pals == ["underwaterpal.png"]


def test_setbackpal_without_callback_is_silent():
    client = _fake_connected_client()
    gs1 = _npc_gs1(client, 5,
                   "if (playerenters) { setbackpal grayscale.png; this.ok = 1; }")
    gs1.trigger_npc_event(5, "playerenters")
    assert gs1._progs["npc_5"]["scopes"]["this"].get("ok") == 1


def test_tileset_backpal_swaps_palette():
    import pygame
    pygame.init()
    from pyreborn.sprites import SpriteManager, TilesetManager
    sm = SpriteManager(search_paths=[])
    # a 2048-wide sheet isn't needed: tile 0 reads pixels (0,0)-(15,15)
    sheet = pygame.Surface((32, 32), depth=8)
    sheet.set_palette([(0, 0, 0)] * 256)
    sheet.set_palette_at(1, (10, 20, 30))
    sheet.fill((10, 20, 30))        # every pixel = index 1
    pal = pygame.Surface((4, 4), depth=8)
    palette = [(0, 0, 0)] * 256
    palette[1] = (200, 100, 50)     # index 1 remapped
    pal.set_palette(palette)
    sm.sheet_cache["base.png"] = sheet
    sm._raw8_cache["base.png"] = sheet
    sm.sheet_cache["swap.png"] = pal
    sm._raw8_cache["swap.png"] = pal
    tm = TilesetManager(sm)
    tm.default_tileset = "base.png"
    before = tm.get_tile(0).get_at((0, 0))[:3]
    assert before == (10, 20, 30)
    assert tm.set_backpal("swap.png") is True
    after = tm.get_tile(0).get_at((0, 0))[:3]
    assert after == (200, 100, 50)
    # re-issuing the same pal is a no-op; clearing restores stock
    assert tm.set_backpal("swap.png") is False
    assert tm.set_backpal("") is True
    assert tm.get_tile(0).get_at((0, 0))[:3] == (10, 20, 30)
