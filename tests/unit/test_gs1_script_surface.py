"""Client-side GS1 script-surface gaps: carry flags, setletters, players[i]
members, take, toinventory, takeplayerhorse, timershow, shootfireblast and
shootnuke.

Each command is checked against what the reference client does
(Preagonal/FourPlay/quattroplay/src, citations in the handlers). Fragments
marked "corpus" are lines copied from the workspace's real server content.
"""

import math
import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pytest

from pyreborn.clock import Clock
from pyreborn import Client, npc_flags
from pyreborn.game.callbacks.gs1_callbacks import wire_gs1_callbacks
from pyreborn.gs1_client import ClientGS1
from pyreborn.npc_script_display import take_display, timer_text
from pyreborn.packets import PacketID

from .test_gs1_npc_host_gaps import _client, _this


def _engine(scripts, level="room0.nw"):
    """Like test_gs1_npc_host_gaps._engine, but NPCs get a 2x2 image footprint
    and the recorder is returned so wire output can be asserted."""
    c = _client(level)
    for npc_id, src in scripts.items():
        c.npcs[npc_id] = {"x": 10.0, "y": 10.0, "image": "-", "script": src,
                          "_level": level}
    gs1 = ClientGS1(c)
    for npc_id, src in scripts.items():
        gs1.load_script("npc_%d" % npc_id, src, npc_id=npc_id, x=10.0, y=10.0)
    return c, gs1


def _run(gs1, npc_id, event="playerenters"):
    gs1.trigger_npc_event(npc_id, event)


def _game(**client_attrs):
    """A stand-in GameClient: enough surface for wire_gs1_callbacks and the
    callbacks under test."""
    client = SimpleNamespace(player=SimpleNamespace(id=1, account="a"),
                             clock=Clock(), **client_attrs)
    game = SimpleNamespace(
        gs1=ClientGS1(None), client=client, clock=client.clock, player_anim=SimpleNamespace(),
        active_bombs=[], thrown_objects=[], other_thrown_objects=[],
        active_projectiles=[])
    wire_gs1_callbacks(game)
    return game


# -- canbe* / cannotbe* -------------------------------------------------------

def test_canbe_commands_set_their_own_blockflag_bit():
    c, gs1 = _engine({5: "if (playerenters) { canbecarried; canbepulled; canbepushed; }"})
    _run(gs1, 5)
    npc = c.npcs[5]
    assert npc["blockflags"] == 0x02 | 0x04 | 0x08
    assert npc_flags.can_be_carried(npc) and npc_flags.can_be_pulled(npc)
    assert npc_flags.can_be_pushed(npc)


def test_cannotbe_commands_clear_only_their_bit():
    c, gs1 = _engine({5: "if (playerenters) { cannotbecarried; cannotbepushed; }"})
    c.npcs[5]["blockflags"] = 0x0F          # no-block + all three, as the wire sends
    _run(gs1, 5)
    assert c.npcs[5]["blockflags"] == 0x01 | 0x04
    assert not npc_flags.can_be_carried(c.npcs[5])
    assert npc_flags.can_be_pulled(c.npcs[5])


def test_wire_blockflags_byte_round_trips_through_the_same_key():
    c, gs1 = _engine({5: "if (playerenters) { canbepushed; }"})
    c.npcs[5].update(blockflags=0x02)       # PLO_NPCPROPS BLOCKFLAGS
    _run(gs1, 5)
    assert c.npcs[5]["blockflags"] == 0x0A


def test_corpus_geovanie_snack_fragment_marks_the_npc_carryable():
    # corpus: Preagonal/graal-gta/world/geovanie-snack.nw:119 `canbecarried;`
    c, gs1 = _engine({5: "canbecarried;\nif (playerenters) { this.ran = 1; }"})
    _run(gs1, 5)
    # a bare top-level statement runs on the first event the NPC sees
    assert npc_flags.can_be_carried(c.npcs[5])
    assert _this(gs1, 5)["ran"] == 1.0


def test_canbe_commands_in_a_weapon_script_do_nothing_and_do_not_raise():
    c, gs1 = _engine({})
    gs1.load_weapon("-probe", "if (created) { canbecarried; this.ok = 1; }")
    gs1.trigger_event("created", name="weapon_-probe")


# -- carryobject / throwcarry -------------------------------------------------

def test_carryobject_gives_a_character_npc_the_carry_sprite_and_gani():
    from pyreborn.throwing import carry_code
    c, gs1 = _engine({5: "if (playerenters) { showcharacter; carryobject vase; }"})
    _run(gs1, 5)
    assert c.npcs[5]["carry_sprite"] == carry_code(0x109)      # vase
    assert c.npcs[5]["gani"].split(",")[0] == "carrystill"


def test_carryobject_table_matches_the_reference_names():
    from pyreborn.gs1_client.objects import _CARRY_NAMES, _CARRY_SPRITES
    # TInitStatics.cpp:1139-1140 / :1179
    assert _CARRY_NAMES[:5] == ("bush", "sign", "vase", "stone", "blackstone")
    assert dict(zip(_CARRY_NAMES, _CARRY_SPRITES))["hotjoltbomb"] == 0x15c
    assert dict(zip(_CARRY_NAMES, _CARRY_SPRITES))["none"] == -1


def test_carryobject_ignores_plain_image_npcs_and_unknown_names():
    c, gs1 = _engine({5: "if (playerenters) { carryobject bush; }",
                      6: "if (playerenters) { showcharacter; carryobject lamp; }"})
    _run(gs1, 5)
    _run(gs1, 6)
    assert "carry_sprite" not in c.npcs[5]
    assert "carry_sprite" not in c.npcs[6]


def test_throwcarry_launches_the_object_and_returns_the_npc_to_idle():
    thrown = []
    c, gs1 = _engine({5: "if (playerenters) { showcharacter; carryobject stone; }"
                         " if (timeout) { throwcarry; }"})
    gs1.on_throwcarry = lambda npc, code: thrown.append((npc["carry_sprite"], code))
    _run(gs1, 5)
    carried = c.npcs[5]["carry_sprite"]
    _run(gs1, 5, "timeout")
    assert [t[1] for t in thrown] == [carried]
    assert c.npcs[5]["carry_sprite"] == -1
    assert c.npcs[5]["gani"].split(",")[0] == "idle"


def test_throwcarry_needs_a_carry_gani():
    thrown = []
    c, gs1 = _engine({5: "if (playerenters) { showcharacter; carryobject stone; setcharani idle,; }"
                         " if (timeout) { throwcarry; }"})
    gs1.on_throwcarry = lambda npc, code: thrown.append(code)
    _run(gs1, 5)
    _run(gs1, 5, "timeout")
    assert thrown == []                      # TServerNPCProperties.cpp:979-981


def test_throwcarry_callback_spawns_an_arc_one_tick_short():
    from pyreborn.throwing import THROW_TICKS, carry_code
    game = _game()
    npc = {"x": 10.0, "y": 20.0, "direction": 3}
    game.gs1.on_throwcarry(npc, carry_code(0x109))
    assert not game.thrown_objects and len(game.other_thrown_objects) == 1
    obj = game.other_thrown_objects[0]
    assert obj["landing_tick"] == THROW_TICKS - 1
    assert obj["dx"] == 1 and obj["type"] == "vase"
    assert obj["x"] == pytest.approx(10.0 + 0.5 + 1.0)        # flyd[3].x == 1


def test_throwcarry_of_a_bomb_leaves_a_ticking_bomb_in_flight():
    from pyreborn.throwing import carry_code
    game = _game()
    game.gs1.on_throwcarry({"x": 1.0, "y": 1.0, "direction": 2}, carry_code(0x41))
    bomb = game.active_bombs[0]
    assert bomb["in_flight"] and bomb["fuse_time"] == 3.0      # 0x3c ticks
    assert game.thrown_objects[0]["bomb"] is bomb


# -- takeplayercarry ----------------------------------------------------------

def _carrying_client():
    from pyreborn.throwing import carry_code
    c = _client()
    c.player.pickup_object("bush", (1, 2, 3, 4), (5.0, 5.0))
    c.player.action_mode = 4
    return c, ClientGS1(c)


def test_takeplayercarry_deletes_the_carried_object_without_throwing():
    c, gs1 = _carrying_client()
    gs1.load_weapon("-t", "if (created) { takeplayercarry; }")
    assert c.player.is_carrying()
    gs1.trigger_event("created", name="weapon_-t")
    assert not c.player.is_carrying()
    assert c.player.carry_sprite == -1 and c.player.action_mode == 0
    assert c.player.animation == "idle"
    # published as "nothing carried" on the wire
    props = [d for pid, d in c._protocol.sent if pid == int(PacketID.PLI_PLAYERPROPS)]
    assert props


def test_takeplayercarry_leaves_hiding_and_drops_a_carried_bomb():
    from pyreborn.hiding import HIDDEN_ACTION_MODE
    c, gs1 = _carrying_client()
    c.player.action_mode = HIDDEN_ACTION_MODE
    bomb = {"x": 1.0, "y": 1.0}
    c.player.carried_bomb = bomb
    gs1.load_weapon("-t", "if (created) { takeplayercarry; }")
    gs1.trigger_event("created", name="weapon_-t")
    assert c.player.action_mode == 0 and bomb["discarded"] is True
    assert c.player.carried_bomb is None


# -- setletters ---------------------------------------------------------------

def test_setletters_selects_the_sign_font_sheet():
    # corpus: Preagonal/graal-gta/world/sardontoweroutsil.nw:83 `setletters grayletters.png;`
    c, gs1 = _engine({5: "if (playerenters) { setbackpal grayscale.png; "
                         "setletters grayletters.png; }"})
    assert gs1.letters_image == "letters.png"       # TPlayer.cpp:792 default
    _run(gs1, 5)
    assert gs1.letters_image == "grayletters.png"


# -- players[i] ---------------------------------------------------------------

def _roster():
    c = _client()
    p = c.player
    p.id, p.account, p.nickname = 3, "me", "Me"
    p.hearts, p.max_hearts, p.ap, p.mp = 2.5, 4.0, 60, 7
    p.direction, p.rupees, p.arrows, p.bombs = 1, 99, 12, 5
    p.glove_power, p.sword_power, p.shield_power, p.bomb_power = 2, 3, 1, 2
    p.head_image = "head007.png"
    c.players[9] = {"id": 9, "account": "other", "nickname": "Oth", "x": 4.0,
                    "y": 5.0, "direction": 3, "ap": 80, "mp": 1,
                    "sword_power": 2, "shield_power": 1, "level": "room0.nw"}
    return c


def test_players_index_exposes_the_documented_members_for_self():
    c = _roster()
    gs1 = ClientGS1(c)
    c.npcs[5] = {"x": 1.0, "y": 1.0, "image": "-"}
    src = ("if (playerenters) { this.h = players[0].hearts; this.i = players[0].id;"
           " this.a = players[0].ap; this.d = players[0].dir;"
           " this.f = players[0].fullhearts; this.r = players[0].rupees;"
           " this.sw = players[0].swordpower; this.gp = players[0].glovepower;"
           " this.dt = players[0].darts; this.b = players[0].bombs;"
           " this.hs = players[0].headset; this.hp = players[0].hp; }")
    gs1.load_script("npc_5", src, npc_id=5)
    _run(gs1, 5)
    got = _this(gs1, 5)
    assert (got["h"], got["i"], got["a"], got["d"], got["f"], got["r"]) == (
        2.5, 3.0, 60.0, 1.0, 4.0, 99.0)
    assert (got["sw"], got["gp"], got["dt"], got["b"], got["hs"], got["hp"]) == (
        3.0, 2.0, 12.0, 5.0, 7.0, 2.5)


def test_players_index_exposes_the_members_the_wire_gives_for_others():
    c = _roster()
    gs1 = ClientGS1(c)
    c.npcs[5] = {"x": 1.0, "y": 1.0, "image": "-"}
    src = ("if (playerenters) { this.i = players[1].id; this.d = players[1].dir;"
           " this.a = players[1].ap; this.x = players[1].x;"
           " this.sw = players[1].swordpower; this.h = players[1].hearts;"
           " this.n = players[2].id; }")
    gs1.load_script("npc_5", src, npc_id=5)
    _run(gs1, 5)
    got = _this(gs1, 5)
    assert (got["i"], got["d"], got["a"], got["x"], got["sw"]) == (9.0, 3.0, 80.0, 4.0, 2.0)
    assert got["h"] == 0.0 and got["n"] == 0.0         # unsent / out of range
    # string members read back as strings (GS1 `=` only assigns numbers)
    ctx = SimpleNamespace(this_obj=c.npcs[5])
    assert gs1._host.get_builtin("players.nick", [1], ctx) == "Oth"
    assert gs1._host.get_builtin("players.account", [1], ctx) == "other"


def test_corpus_player_loop_reads_x_y_id_hearts():
    # corpus shape (Preagonal/graal-gta/world/): `for (i=0;i<playerscount;i++) if (players[i].hearts ...`
    c = _roster()
    gs1 = ClientGS1(c)
    c.npcs[5] = {"x": 1.0, "y": 1.0, "image": "-"}
    gs1.load_script("npc_5", "if (playerenters) { for (i=0;i<playerscount;i++) "
                    "{ this.sum += players[i].id; this.hp += players[i].hearts; } }", npc_id=5)
    _run(gs1, 5)
    assert _this(gs1, 5)["sum"] == 12.0 and _this(gs1, 5)["hp"] == 2.5


# -- take ---------------------------------------------------------------------

def _take_client(items):
    c = _client()
    c.items = {"room0.nw": dict(items)}
    return c


def test_take_absorbs_a_matching_item_in_reach_and_tells_the_server():
    # corpus: Preagonal/graal-gta/world/nightlord_house2.nw (bed.png) `if (playerlaysitem) { take greenrupee; ... }`
    c = _take_client({(12.0, 11.0): "greenrupee", (40.0, 40.0): "greenrupee"})
    c.npcs[5] = {"x": 10.0, "y": 10.0, "image": "-",
                 "script": "", "_level": "room0.nw"}
    gs1 = ClientGS1(c)
    gs1.load_script("npc_5", "if (playerlaysitem) {\n  take greenrupee;\n"
                    "  take bluerupee;\n  take redrupee;\n  take goldrupee;}", npc_id=5)
    _run(gs1, 5, "playerlaysitem")
    assert (12.0, 11.0) not in c.items["room0.nw"]
    assert (40.0, 40.0) in c.items["room0.nw"]                 # out of reach: 10 tiles
    deletes = [d for pid, d in c._protocol.sent if pid == int(PacketID.PLI_ITEMDEL)]
    assert deletes == [bytes([12 * 2 + 32, 11 * 2 + 32])]
    assert not [1 for pid, _ in c._protocol.sent if pid == int(PacketID.PLI_ITEMTAKE)]
    assert c.npcs[5]["rupees"] == 1.0                           # takeItem(0): +1


def test_take_only_matches_the_named_kind_and_counts_per_kind():
    c = _take_client({(11.0, 10.0): "goldrupee", (11.0, 12.0): "bluerupee"})
    c.npcs[5] = {"x": 10.0, "y": 10.0, "image": "-", "_level": "room0.nw"}
    gs1 = ClientGS1(c)
    gs1.load_script("npc_5", "if (playerenters) { take bluerupee; take goldrupee; "
                    "take redrupee; }", npc_id=5)
    _run(gs1, 5)
    assert c.items["room0.nw"] == {}
    assert c.npcs[5]["rupees"] == 105.0                        # +5 and +100


def test_take_effects_follow_takeitem():
    c = _take_client({(10.0, 11.0): "sword", (10.0, 12.0): "glove2", (10.0, 13.0): "darts"})
    c.npcs[5] = {"x": 10.0, "y": 10.0, "image": "-"}
    gs1 = ClientGS1(c)
    gs1.load_script("npc_5", "if (playerenters) { take sword; take glove2; take darts; }", npc_id=5)
    _run(gs1, 5)
    npc = c.npcs[5]
    assert (npc["sword_power"], npc["glove_power"], npc["arrows"]) == (1, 2, 5.0)


def test_take_ignores_unknown_items_and_an_empty_floor():
    c = _take_client({})
    c.npcs[5] = {"x": 10.0, "y": 10.0, "image": "-"}
    gs1 = ClientGS1(c)
    gs1.load_script("npc_5", "if (playerenters) { take mushroom; take heart; }", npc_id=5)
    _run(gs1, 5)
    assert "take_item" not in c.npcs[5]
    assert not [1 for pid, _ in c._protocol.sent if pid == int(PacketID.PLI_ITEMDEL)]


def test_take_display_lasts_twenty_ticks_and_shows_totals_for_stat_items():
    npc = {"take_item": 0, "take_until": 100.0 + 1.0, "take_value": 7.0}
    assert take_display(npc, now=100.5) == (136, "7")           # green rupee sprite
    assert take_display(npc, now=101.0) is None
    heart = {"take_item": 5, "take_until": 5.0, "take_value": 0.00001}
    assert take_display(heart, now=1.0)[1] == "0"
    glove = {"take_item": 6, "take_until": 5.0}
    assert take_display(glove, now=1.0) == (145, None)


# -- toinventory ---------------------------------------------------------------

def test_toinventory_sets_the_flag_and_files_the_npc():
    # corpus: Preagonal/graal-gta/world/swordpalacebossdead.nw:82
    c, gs1 = _engine({5: "if (playertouchsme) {toinventory GotBlackRupee;}\n"
                         "if (timeout) { if (GotBlackRupee) this.has = 1; }"})
    _run(gs1, 5, "playertouchsme")
    _run(gs1, 5, "timeout")
    assert _this(gs1, 5).get("has") == 1.0
    assert c.npcs[5]["inventory_flag"] == "GotBlackRupee"


# -- takeplayerhorse -----------------------------------------------------------

def test_takeplayerhorse_dismounts_and_reports_it():
    c = _client()
    c.player.horse_image = "horse.png"
    gs1 = ClientGS1(c)
    gs1.load_weapon("-h", "if (created) { takeplayerhorse; this.on = playeronhorse; }")
    gs1.trigger_event("created", name="weapon_-h")
    assert c.player.horse_image == ""
    props = [d for pid, d in c._protocol.sent if pid == int(PacketID.PLI_PLAYERPROPS)]
    assert props and props[-1][0] == 21 + 32                    # HORSEGIF, empty


def test_takeplayerhorse_on_foot_sends_nothing():
    c = _client()
    gs1 = ClientGS1(c)
    gs1.load_weapon("-h", "if (created) { takeplayerhorse; }")
    gs1.trigger_event("created", name="weapon_-h")
    assert not c._protocol.sent


# -- timershow -----------------------------------------------------------------

def test_timershow_shows_the_floored_remaining_timeout():
    c, gs1 = _engine({5: "if (playerenters) { timershow; timeout = 3.2; }"})
    _run(gs1, 5)
    npc = c.npcs[5]
    assert npc["timershow"] is True
    assert timer_text(npc) == "3"
    npc["_timeout"] = 0.99995
    assert timer_text(npc) == "1"       # floor(t + 0.0001)
    npc["_timeout"] = None
    assert timer_text(npc) is None


def test_timershow_is_cleared_by_message_by_timeout_zero_and_by_expiry():
    c, gs1 = _engine({
        5: "if (playerenters) { timershow; timeout = 2; } if (timeout) { this.fired = 1; }",
        6: "if (playerenters) { timershow; timeout = 2; message hi; }",
        7: "if (playerenters) { timershow; timeout = 2; timeout = 0; }",
    })
    for npc_id in (5, 6, 7):
        _run(gs1, npc_id)
    assert not c.npcs[6].get("timershow")
    assert not c.npcs[7].get("timershow")
    assert c.npcs[5]["timershow"] is True
    gs1.process_timeouts(2.5)
    assert not c.npcs[5].get("timershow") and _this(gs1, 5)["fired"] == 1.0


# -- shootfireblast / shootnuke -------------------------------------------------

def _fired(script, direction_npc=None):
    c, gs1 = _engine({5: script})
    shots = []
    gs1.on_flying = lambda *a: shots.append(a)
    if direction_npc:
        c.npcs[5].update(direction_npc)
    _run(gs1, 5)
    return shots


def test_shootfireblast_and_shootnuke_launch_power_two_and_three():
    shots = _fired("if (playerenters) { shootfireblast 2; shootnuke 0; }")
    assert [(s[2], s[3]) for s in shots] == [(2, 2), (0, 3)]


def test_flying_object_starts_where_the_reference_puts_it():
    # image NPC at (10,10); no known size -> 0x0, so only the fixed offsets act
    shots = _fired("if (playerenters) { shootfireblast 1; shootfireblast 3; shootnuke 2; }")
    (lx, ly, *_), (rx, ry, *_), (dx, dy, *_) = shots
    # left/right: x -= 0.9375, y -= 0.3125 (TServerNPCProperties.cpp:121-130)
    assert (lx, ly) == (10.0 - 0.9375, 10.0 - 0.3125)
    assert (rx, ry) == (10.0 - 0.9375, 10.0 - 0.3125)
    # down: x -= 0.3125, y -= 0.9375
    assert (dx, dy) == (10.0 - 0.3125, 10.0 - 0.9375)


def test_character_npc_flying_start_uses_its_two_tile_box():
    shots = _fired("if (playerenters) { showcharacter; shootnuke 3; }")
    x, y, direction, power = shots[0]
    # right: x += width (2.0), y += height / 2 (1.0)
    assert (x, y) == (10.0 - 0.9375 + 2.0, 10.0 - 0.3125 + 1.0)
    assert direction == 3 and power == 3


def test_direction_names_and_wrapping():
    shots = _fired("if (playerenters) { shootnuke up; shootnuke -1; shootnuke 6; }")
    assert [s[2] for s in shots] == [0, 3, 2]


def test_flying_callback_spawns_a_projectile_at_arrow_speed():
    game = _game(ARROW_SPEED=20.0, ARROW_MAX_DISTANCE=128.0)
    game.gs1.on_flying(4.0, 5.0, 3, 2)
    proj = game.active_projectiles[0]
    assert (proj["dx"], proj["dy"], proj["gani"]) == (20.0, 0, "fireblast")


# -- review regressions ----------------------------------------------------------

@pytest.mark.parametrize("name, power", [("bomb", 1), ("hotbomb", 1),
                                         ("superbomb", 2), ("joltbomb", 3),
                                         ("hotjoltbomb", 3)])
def test_script_throwcarry_bomb_power_follows_the_carried_sprite(name, power):
    # TServerNPCProperties.cpp:985-1017
    c, gs1 = _engine({5: "if (playerenters) { showcharacter; carryobject %s; "
                         "throwcarry; }" % name})
    game = _game()
    game.gs1 = gs1
    wire_gs1_callbacks(game)
    _run(gs1, 5)
    assert [b["power"] for b in game.active_bombs] == [power]


def _gmap(c, segment=(1, 0)):
    c.gmap_width = 2
    c.gmap_grid = {segment: "room0.nw"}
    c.player.x, c.player.y = 64.0 * segment[0] + 5.0, 5.0


def test_take_uses_world_coordinates_on_a_gmap():
    # an NPC one segment away (local x 10, world x 74) is 64 tiles from the
    # item the player's own segment holds at local (10, 10)
    c, gs1 = _engine({5: "if (playerenters) { take greenrupee; }"})
    c.items = {"room0.nw": {(10.0, 10.0): "greenrupee"}}
    _gmap(c, (0, 0))
    c.npcs[5].update(world_x=74.0, world_y=10.0)
    _run(gs1, 5)
    assert c.items["room0.nw"] == {(10.0, 10.0): "greenrupee"}
    assert not c._protocol.sent


def test_take_on_a_gmap_matches_an_npc_in_the_same_segment():
    c, gs1 = _engine({5: "if (playerenters) { take greenrupee; }"})
    c.items = {"room0.nw": {(10.0, 10.0): "greenrupee"}}
    _gmap(c, (1, 0))                       # item's world x = 74
    c.npcs[5].update(world_x=74.0, world_y=10.0)
    _run(gs1, 5)
    assert c.items["room0.nw"] == {}
    sent = [d for pid, d in c._protocol.sent if pid == int(PacketID.PLI_ITEMDEL)]
    assert sent == [bytes([10 * 2 + 32, 10 * 2 + 32])]      # level-local on the wire


def test_takeplayercarry_with_nothing_carried_sends_nothing():
    c = _client()
    gs1 = ClientGS1(c)
    gs1.load_weapon("-h", "if (created) { for (i=0;i<1000;i++) { takeplayercarry; } }")
    gs1.trigger_event("created", name="weapon_-h")
    assert c._protocol.sent == []


def test_takeplayercarry_publishes_once_then_goes_quiet():
    c, gs1 = _carrying_client()
    gs1.load_weapon("-h", "if (created) { for (i=0;i<1000;i++) { takeplayercarry; } }")
    gs1.trigger_event("created", name="weapon_-h")
    # one carry-sprite -1 publish; the player is already idle, so no gani
    # packet, and the 999 later calls find nothing to take
    assert [pid for pid, _ in c._protocol.sent] == [int(PacketID.PLI_PLAYERPROPS)]


def test_takeplayerhorse_loop_dismounts_once():
    c = _client()
    c.player.horse_image = "h.png"
    gs1 = ClientGS1(c)
    gs1.load_weapon("-h", "if (created) { for (i=0;i<1000;i++) { takeplayerhorse; } }")
    gs1.trigger_event("created", name="weapon_-h")
    assert len(c._protocol.sent) == 1


def test_script_spawn_caps_stop_a_runaway_loop_across_events():
    from pyreborn.game.callbacks.gs1_callbacks import MAX_SCRIPT_OBJECTS
    game = _game(ARROW_SPEED=20.0, ARROW_MAX_DISTANCE=128.0)
    for _ in range(MAX_SCRIPT_OBJECTS * 2):
        game.gs1.on_flying(1.0, 1.0, 0, 2)
    assert len(game.active_projectiles) == MAX_SCRIPT_OBJECTS


def test_players_loop_over_a_big_roster_is_fast_and_sees_changes_between_events():
    c, gs1 = _engine({5: "if (playerenters) { this.s = 0; for (i=0;i<playerscount;i++) "
                         "{ this.s = this.s + players[i].x + players[i].hearts; } }"})
    for i in range(2, 400):
        c.players[i] = {"x": 3.0, "y": 4.0, "account": "a%d" % i,
                        "nickname": "n", "head_image": "head12.png"}
    def drain():
        _run(gs1, 5)
        while any(co["remaining"] <= 0 for co in gs1._coros):   # preempted slices
            gs1.process_coroutines(0.0)

    start = time.perf_counter()
    drain()
    assert time.perf_counter() - start < 0.5
    assert _this(gs1, 5)["s"] == pytest.approx(398 * 3.0 + c.player.x + c.player.hearts)
    # the cache lives for one slice: a roster change is seen by the next event
    c.players[2]["x"] = 10.0
    drain()
    assert _this(gs1, 5)["s"] == pytest.approx(397 * 3.0 + 10.0 + c.player.x + c.player.hearts)


def test_local_player_record_is_live_within_a_slice():
    c, gs1 = _engine({5: "if (playerenters) { playerhearts = 1; this.h = players[0].hearts; }"})
    c.player.hearts = 3.0
    c.player.max_hearts = 3.0
    _run(gs1, 5)
    assert _this(gs1, 5)["h"] == 1.0
