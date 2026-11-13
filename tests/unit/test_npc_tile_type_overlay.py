"""A setshape2 array is a per-cell TILE TYPE table, not a blocking mask.

`TServerNPC::getTileType` indexes the array by the offset from the NPC's
origin and returns the cell verbatim
(Preagonal/FourPlay/quattroplay/src/TServerNPC.cpp:2016-2040).
`TServerLevel::getTileType` asks the level's NPCs BEFORE the board and lets any
answer above 1 override it (TServerLevel.cpp:688-708, searching via
getNPCTileType at :536-561).

We used to keep only the single value 22 (blocking), which is all the Bomber
arena's falling choc blocks needed. Everything else was dropped — including the
32 cells of type 3 (CHAIR) that classic Bomber's player-base room controller
paints over the whole 64x64 room with `setshape2 64,64,obj`. Live on
bomber.eevul.net that room's chair cells sit on board tiles of type 0, so the
board can never say "chair" and walking onto your own furniture did nothing.
"""

import pytest

from pyreborn.npc_handler import NPCHandler, NPCShape
from pyreborn.tiletypes import TileType


@pytest.fixture
def engine(make_game):
    """``engine(level="room0.nw", board_tile=0, **knobs)``: (client, GS1
    engine, game) of a real offline game on a board of ``board_tile``."""
    def build(level="room0.nw", board_tile=0, **knobs):
        game = make_game(level=level, tiles=lambda tx, ty: board_tile, **knobs)
        return game.client, game.gs1, game
    return build


def _shape(gs1, client, npc_id, x, y, w, h, cells):
    """Run one NPC's `setshape2 w,h,{cells}` at (x, y)."""
    npc = client.npcs.setdefault(npc_id, {"x": float(x), "y": float(y),
                                          "script": ";"})
    npc["x"], npc["y"] = float(x), float(y)
    gs1.load_script("npc_%d" % npc_id, ";", npc_id=npc_id, x=x, y=y)
    gs1._update_shape_blocks(npc_id, npc, w, h, list(cells))


# -- the overlay itself ------------------------------------------------------

def test_a_chair_cell_is_published_as_a_tile_type(engine):
    c, gs1, game = engine()
    _shape(gs1, c, 91, 10, 5, 2, 2, [0, 0, 3, 3])
    # Row-major from the NPC's origin: the 3s are the second row.
    assert gs1.npc_tile_type(10, 6) == TileType.CHAIR
    assert gs1.npc_tile_type(11, 6) == TileType.CHAIR
    assert gs1.npc_tile_type(10, 5) == 0
    # A fractional coordinate floors into its cell (the player's feet point
    # is never tile-aligned).
    assert gs1.npc_tile_type(10.75, 6.25) == TileType.CHAIR


def test_cells_at_or_below_one_do_not_override_the_board(engine):
    # TServerLevel.cpp:694-696 takes the NPC answer only when it is > 1; the
    # room controller also parks private markers (-1..-9) in the same array.
    c, gs1, game = engine()
    _shape(gs1, c, 91, 0, 0, 3, 1, [0, 1, -7])
    assert [gs1.npc_tile_type(x, 0) for x in (0, 1, 2)] == [0, 1, -7]


def test_blocking_cells_still_reach_the_onwall_probe(engine):
    # The pre-existing behaviour this generalises: 22 keeps blocking.
    c, gs1, game = engine()
    _shape(gs1, c, 91, 4, 4, 2, 1, [22, 0])
    assert (4, 4) in gs1._shape_blocks and (5, 4) not in gs1._shape_blocks
    assert gs1.is_wall(4, 4) is True
    assert gs1.npc_tile_type(4, 4) == TileType.BLOCKING


def test_rerunning_setshape2_replaces_the_npcs_own_cells(engine):
    c, gs1, game = engine()
    _shape(gs1, c, 91, 10, 5, 2, 2, [0, 0, 3, 3])
    _shape(gs1, c, 91, 10, 5, 2, 2, [0, 0, 0, 0])
    assert gs1.npc_tile_type(10, 6) == 0
    assert gs1._shape_types == {}


def test_a_despawned_npc_leaves_another_npcs_overlapping_cell_intact(engine):
    # Bomber's room0 has TWO 64x64 shape NPCs blanketing the same room.
    c, gs1, game = engine()
    _shape(gs1, c, 90, 0, 0, 1, 1, [22])
    _shape(gs1, c, 91, 0, 0, 1, 1, [3])
    gs1.forget_npc(91)
    assert gs1.npc_tile_type(0, 0) == TileType.BLOCKING
    gs1.forget_npc(90)
    assert gs1.npc_tile_type(0, 0) == 0


def test_clear_drops_the_overlay(engine):
    c, gs1, game = engine()
    _shape(gs1, c, 91, 10, 5, 2, 2, [0, 0, 3, 3])
    gs1.clear()
    assert gs1.npc_tile_type(10, 6) == 0


# -- what the player actually feels ------------------------------------------

def _sitting_harness(engine, chair_cells):
    c, gs1, game = engine()
    if chair_cells:
        w = 2
        _shape(gs1, c, 91, chair_cells[0][0], chair_cells[0][1], w, 1,
               [TileType.CHAIR] * w)
    return c, gs1, game


def test_walking_onto_an_npc_chair_seats_the_player(engine):
    # The live failure: the board says type 0 everywhere, only the NPC's
    # setshape2 array says chair.
    c, gs1, game = _sitting_harness(engine, [(20, 30)])
    assert game._tile_type(game._get_tile_at(20.5, 30.5)) == 0
    c.player.x = 20.5 - game.PLAYER_GROUND_DX
    c.player.y = 30.5 - game.PLAYER_GROUND_DY
    game._update_sitting_state()
    assert c.player.is_sitting is True


def test_leaving_the_npc_chair_stands_the_player_up(engine):
    c, gs1, game = _sitting_harness(engine, [(20, 30)])
    c.player.x = 20.5 - game.PLAYER_GROUND_DX
    c.player.y = 30.5 - game.PLAYER_GROUND_DY
    game._update_sitting_state()
    assert c.player.is_sitting is True
    c.player.x += 4.0
    game._update_sitting_state()
    assert c.player.is_sitting is False


def test_the_sit_band_matches_the_official_ground_point(engine):
    """A Bomber furniture chair is TWO tiles tall, and the sit test samples
    ONE point. Sampling it at PLAYER_STAND_Y (2.5) instead of the official
    (x+1.5, y+2.0) — `TPlayer::testSittingSleeping`,
    Preagonal/FourPlay/quattroplay/src/TPlayer.cpp:5925-5927 — shifted the
    seatable band half a tile up the screen: measured live on
    bomber.eevul.net 2026-07-26, a chair on rows 27-28 seated the player over
    y 24.50..26.375 instead of 25.00..26.875, so the bottom half-tile of every
    chair refused to seat him."""
    c, gs1, game = engine()
    _shape(gs1, c, 91, 27, 27, 1, 2, [TileType.CHAIR, TileType.CHAIR])

    def sits(py):
        c.player.x = 27.5 - game.PLAYER_GROUND_DX
        c.player.y = py
        c.player.is_sitting = False
        game._update_sitting_state()
        return bool(c.player.is_sitting)

    # floor(y + 2.0) in {27, 28}  ->  y in [25.0, 27.0)
    assert sits(24.875) is False
    assert sits(25.0) is True
    assert sits(26.0) is True
    assert sits(26.875) is True          # the half-tile the old point lost
    assert sits(27.0) is False


def test_no_npc_overlay_means_the_board_still_decides(engine):
    c, gs1, game = _sitting_harness(engine, [])
    c.player.x, c.player.y = 20.0, 30.0
    game._update_sitting_state()
    assert c.player.is_sitting is False




@pytest.mark.parametrize("ttype", [0, 1, 2, 3, 4, 11, 12, 19, 20, 21, 22, 23])
def test_touch_and_blocking_have_separate_thresholds(ttype, engine):
    c, gs1, game = engine()
    _shape(gs1, c, 1, 10.25, 5.5, 1, 1, [ttype])
    shape = NPCShape(10.25, 5.5, 1, 1, [ttype])
    assert shape.is_point_inside(10.5, 5.75) == (ttype >= 2)
    assert shape.get_touchable_tiles() == ([(0, 0)] if ttype >= 2 else [])
    assert gs1.npc_blocks_at(10.5, 5.75) == (ttype >= 20)
    assert game._is_blocked_at(10.5, 5.75) == (ttype >= 20)
    handler = NPCHandler(c)
    handler.gs1 = gs1
    handler.update_npcs()
    assert handler.npc_shapes[1].is_point_inside(10.5, 5.75) == (ttype >= 2)


def test_overlay_uses_live_fractional_world_position_and_array(engine):
    c, gs1, game = engine()
    _shape(gs1, c, 1, 1, 2, 2, 1, [3, 22])
    npc = c.npcs[1]
    npc.update(world_x=65.5, world_y=130.25)
    assert gs1.tile_type_at(65.25, 130.5) == 0
    assert gs1.tile_type_at(66.25, 130.5) == 3
    assert game._effective_tile_type(66.25, 130.5) == 3
    assert not gs1.npc_blocks_at(66.25, 130.5)
    assert gs1.npc_blocks_at(66.5, 130.5)
    npc['world_x'] += 0.5
    assert not gs1.npc_blocks_at(66.5, 130.5)
    gs1.shapes[1][2][0] = 12
    assert gs1.tile_type_at(66.5, 130.5) == 12
    assert gs1.is_water_at(66.5, 130.5)


@pytest.mark.parametrize("first", [1, -7, 3, 22])
def test_first_nonzero_overlay_wins_even_when_it_does_not_override_board(first, engine):
    c, gs1, game = engine(board_tile=61)
    _shape(gs1, c, 1, 0, 0, 1, 1, [first])
    _shape(gs1, c, 2, 0, 0, 1, 1, [12])
    assert gs1.npc_tile_type(0, 0) == first
    expected = first if first > 1 else 22
    assert gs1.tile_type_at(0, 0) == expected
    assert game._effective_tile_type(0, 0) == expected


def test_shape1_blocks_without_publishing_a_shape2_type(engine):
    c, gs1, game = engine()
    c.npcs[1] = {"x": 0, "y": 0, "script": ";"}
    gs1.load_script("npc_1", "if (created) setshape 1,16,16;", npc_id=1)
    gs1.trigger_npc_event(1, "created")
    assert gs1.npc_blocks_at(.5, .5)
    assert gs1.tile_type_at(.5, .5) == 0


@pytest.mark.parametrize("ttype", [8, 9, 11, 12])
def test_gs1_and_gs2_water_and_tiletype_forward_live_overlays(ttype, engine):
    c, gs1, game = engine()
    _shape(gs1, c, 1, 10.5, 5.5, 1, 1, [ttype])
    gs1.load_weapon("probe", "if (timeout) { this.t = tiletype(10.75,5.75); this.w = onwater(10.75,5.75); }")
    gs1.trigger_event("timeout", "weapon_probe")
    scope = gs1._progs["weapon_probe"]["scopes"]["this"]
    assert scope['t'] == ttype
    assert bool(scope['w']) == (ttype in (11, 12))
    rt2 = game.gs2
    assert rt2.host.call_builtin(None, "tiletype", [10.75, 5.75]) == ttype
    assert bool(rt2.host.call_builtin(None, "onwater", [10.75, 5.75])) == (ttype in (11, 12))
    c.level_state.tiletypes.set_waterheight(0.3)
    assert gs1.is_water_at(0, 0)
    assert bool(rt2.host.call_builtin(None, "onwater", [0, 0]))


@pytest.mark.parametrize("source,expected", [
    ('setshape2 3,1,{22,"abc",""};', [22, 0, 0]),
    ('setshape2 3,1,{"2.9tail","-0.2","19.9"};', [2, -1, 19]),
    ('tokenize 22 abc 0; setshape2 3,1,{#t(0),#t(1),#t(2)};', [22, 0, 0]),
])
def test_string_shape_cells_agree_in_runtime_and_per_move_touch(source, expected, engine):
    c, gs1, game = engine()
    c.npcs[1] = {"x": 10.0, "y": 5.0, "script": ";"}
    gs1.load_script("npc_1", "if (created) { " + source + " }", npc_id=1)
    gs1.trigger_npc_event(1, "created")
    handler = NPCHandler(c)
    handler.gs1 = gs1
    handler.update_npcs()
    shape = handler.npc_shapes[1]
    assert shape.solid_flags == expected
    assert shape.get_touchable_tiles() == [(i, 0) for i, t in enumerate(expected) if t >= 2]
    for i, ttype in enumerate(expected):
        px, py = 10.25 + i, 5.25
        assert gs1._shape_type_at(1, c.npcs[1], px, py) == ttype
        assert shape.is_point_inside(px, py) == (ttype >= 2)
        assert handler.check_touch(px - 3.0, py - 1.55, 3) == ([1] if ttype >= 2 else [])


@pytest.mark.parametrize("height,water", [(-1, False), (0, False), (0.299, False),
                                        (0.3, True), (12.5, True)])
def test_waterheight_default_and_gs1_setter_follow_assembly_threshold(height, water, engine):
    c, gs1, game = engine()
    assert c.level_state.tiletypes.waterheight == 0.0
    assert not gs1.is_water_at(0, 0)
    gs1.load_weapon("plane", f"if (timeout) {{ waterheight = {height}; this.h = waterheight; }}")
    gs1.trigger_event("timeout", "weapon_plane")
    assert c.level_state.tiletypes.waterheight == height
    assert gs1._progs['weapon_plane']['scopes']['this']['h'] == height
    assert gs1.is_water_at(0, 0) == water
    assert bool(game.gs2.host.call_builtin(None, 'onwater', [0, 0])) == water
    _shape(gs1, c, 1, 10, 5, 1, 1, [11])
    assert gs1.is_water_at(10, 5)  # A disabled plane never disables tile water.


@pytest.mark.parametrize('ttype', [0, 3, 4, 5, 20, 21, 22, 23])
def test_upper_board_layers_block_in_game_and_both_script_engines(ttype, monkeypatch, engine):
    from pyreborn import tiletypes as tt
    c, gs1, game = engine()
    if ttype == 23:
        # The shipped table has no 23; exercise the enum's reference threshold
        # in memory without changing either .dat fixture.
        monkeypatch.setattr(tt, 'TILE_TYPES_NW', tt.TILE_TYPES_NW[:-1] + bytes([23]))
    tile_id = next(i for i, value in enumerate(tt.TILE_TYPES_NW) if value == ttype)
    c.level_state.tiletypes.register_tiledef('', 1)
    raw = bytearray(8192)
    offset = (5 * 64 + 10) * 2
    raw[offset:offset + 2] = tile_id.to_bytes(2, 'little')
    c.board_layers = {2: bytes(raw)}
    c._board_layers_level_name = c._current_level_name
    expected = ttype >= 20 or ttype == 4
    assert gs1.is_wall(10.5, 5.5) == expected
    assert game._is_blocked_at(10.5, 5.5) == expected
    rt2 = game.gs2
    assert bool(rt2.host.call_builtin(None, 'onwall', [10.5, 5.5])) == expected
    c._board_layers_level_name = 'neighbor.nw'
    assert not gs1.is_wall(10.5, 5.5)
    assert not game._is_blocked_at(10.5, 5.5)


def test_layer_misses_are_skipped_and_no_tile_types_disables_layer_walls(engine):
    c, gs1, game = engine()
    c._board_layers_level_name = c._current_level_name
    c.board_layers = {1: b'\xff\xff' * 4096, 2: b'\x3d\x00' * 4096}
    assert gs1.is_wall(0, 0)
    c.level_state.tiletypes.register_tiledef('', 5)
    assert not gs1.is_wall(0, 0)
    assert not game._is_blocked_at(0, 0)


def test_headless_gmap_probe_uses_target_segments_board_and_tiledefs(engine):
    c, gs1, game = engine(board_tile=4, gmap=True, gmap_segment=(0, 0))
    c.level_state.tiletypes.register_tiledef('fixture_b', 1)
    assert gs1.tile_type_at(0, 0) == 22
    assert gs1.tile_type_at(64, 0) == 0
    assert gs1.is_wall(0, 0)
    assert not gs1.is_wall(64, 0)
