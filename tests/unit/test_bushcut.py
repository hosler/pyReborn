"""Classic bush tables, bounded matching, and sword/explosion integration."""

from types import SimpleNamespace  # only for the GS1 runtime stand-in below

import pytest

from pyreborn.bushcut import BUSH_OBJECTS, BUSH_PROBE, BUSH_REPLACE, bush_probe, find_bush_block
from pyreborn.handlers.combat import handle_explosion
from pyreborn.liftobjects import LIFT_OBJECTS, LIFT_REPLACE
from pyreborn.packets import PacketID
from pyreborn import tiletypes


def plant(board, x=10, y=10, index=0):
    for dx in range(2):
        for dy in range(2):
            board[x + dx + (y + dy) * 64] = BUSH_OBJECTS[index][dx * 2 + dy]


LEVEL = 'fixture.nw'


@pytest.fixture
def new_client(make_client):
    """``new_client(**knobs)``: a real offline Client on an empty board with the
    player at (9, 6) facing down holding a sword. ``c.modifications`` records
    every ``modify_board`` call (the real one still runs), ``c.effects`` every
    ``on_bush_cut`` event and ``c.sent`` every packet the client sent."""
    def build(**knobs):
        knobs.setdefault('tiles', lambda tx, ty: 0)
        c = make_client(**knobs)
        c.player.x, c.player.y = 9.0, 6.0
        c.player.direction = 2
        c.player.sword_power = 1
        c.modifications = []
        c.effects = []
        c.on_bush_cut = lambda *args: c.effects.append(args)
        real = c.modify_board

        def modify_board(*args):
            c.modifications.append(args)
            return real(*args)
        c.modify_board = modify_board
        c.sent = c._protocol.sent
        return c
    return build


def test_tables_match_official_client():
    # TInitStatics.cpp:1502-1509, column-major.
    assert BUSH_OBJECTS == ((0x2, 0x12, 0x3, 0x13), (0x1a4, 0x1b4, 0x1a5, 0x1b5))
    assert BUSH_REPLACE == ((0x2a5, 0x2b5, 0x2a6, 0x2b6),
                            (0x2a7, 0x2b7, 0x2a8, 0x2b8))
    assert BUSH_OBJECTS[0] is LIFT_OBJECTS[0]
    assert BUSH_REPLACE[0] is LIFT_REPLACE[0]
    assert BUSH_PROBE == ((1.5, 0), (-0.5, 2), (1.5, 4), (3.5, 2))


@pytest.mark.parametrize('direction,expected', [(0, (9, 6)), (1, (7, 8)),
                                                (2, (9, 10)), (3, (11, 8))])
def test_probe_by_direction(direction, expected):
    assert bush_probe(8.0, 6.0, direction) == expected


def test_probe_floors_negative_values():
    assert bush_probe(-0.25, -0.75, 1) == (-1, 1)


def test_probe_uses_epsilon_not_half_tile():
    # DOUBLE_00402440 = 0.0001 (TInitStatics.cpp:1266): 8.5 + 1.5 stays on tile 10.
    assert bush_probe(8.5, 6.0, 0) == (10, 6)
    assert bush_probe(8.4998, 6.0, 0) == (9, 6)


# Flush = player box edge touching the 2x2 bush; a full tile gap is not cut.

POSITIONS = {0: (8.0, 6.0), 1: (12.0, 6.0), 2: (8.0, 2.0), 3: (4.0, 6.0)}


@pytest.mark.parametrize('direction', [0, 1, 2, 3])
def test_flush_bush_cut_from_all_four_sides(direction, new_client):
    # Bush touching the player's box on the facing side.
    start = {0: (8, 5), 1: (10, 7), 2: (8, 5), 3: (6, 7)}[direction]
    c = new_client()
    plant(c.tiles, *start)
    c.player.x, c.player.y = POSITIONS[direction]
    c.player.direction = direction
    assert c.sword_attack(direction)
    assert len(c.modifications) == 1
    assert c.modifications[0][:2] == start


@pytest.mark.parametrize('direction', [0, 1, 2, 3])
def test_bush_one_tile_away_is_not_cut(direction, new_client):
    start = {0: (8, 3), 1: (8, 7), 2: (8, 7), 3: (8, 7)}[direction]
    c = new_client()
    plant(c.tiles, *start)
    c.player.x, c.player.y = POSITIONS[direction]
    c.player.direction = direction
    c.sword_attack(direction)
    assert c.modifications == []


@pytest.mark.parametrize('index', [0, 1])
@pytest.mark.parametrize('dx,dy', [(0, 0), (0, 1), (1, 0), (1, 1)])
def test_find_and_replace_from_every_quadrant(index, dx, dy, new_client):
    c = new_client()
    plant(c.tiles, index=index)
    assert find_bush_block(c.get_tile, 10 + dx, 10 + dy) == (10, 10, index)
    assert c._cut_bush_at(10 + dx, 10 + dy) == (10, 10)
    tl, bl, tr, br = BUSH_REPLACE[index]
    assert c.modifications == [(10, 10, 2, 2, [tl, tr, bl, br])]
    assert [c.get_tile(x, y) for x, y in ((10, 10), (10, 11), (11, 10), (11, 11))] == list(BUSH_REPLACE[index])
    assert c.effects == [(10, 10, index)]
    assert c._cut_bush_at(10, 10) is None


@pytest.mark.parametrize('bad_corner', [0, 1, 2, 3])
def test_partial_or_mismatched_block_is_not_cut(bad_corner, new_client):
    c = new_client()
    plant(c.tiles)
    dx, dy = divmod(bad_corner, 2)
    c.tiles[10 + dx + (10 + dy) * 64] = 0
    for x in (10, 11):
        for y in (10, 11):
            assert c._cut_bush_at(x, y) is None
    assert c.modifications == []


@pytest.mark.parametrize('x,y', [(-1, 10), (64, 10), (10, -1), (10, 64),
                                (0, 0), (63, 63), (0, 63), (63, 0)])
def test_matching_never_reads_outside_board(x, y):
    def read(tx, ty):
        assert 0 <= tx < 64 and 0 <= ty < 64
        return BUSH_OBJECTS[0][3]
    assert find_bush_block(read, x, y) is None


@pytest.mark.parametrize('x,y', [(0, 0), (62, 62), (0, 62), (62, 0)])
def test_complete_blocks_at_board_edges(x, y, new_client):
    c = new_client()
    plant(c.tiles, x, y)
    assert find_bush_block(c.get_tile, x + 1, y + 1) == (x, y, 0)


@pytest.mark.parametrize('index', [0, 1])
def test_sword_cuts_and_sends_one_board_modify(index, new_client):
    c = new_client()
    plant(c.tiles, index=index)
    assert c.sword_attack()
    tl, bl, tr, br = BUSH_REPLACE[index]
    assert c.modifications == [(10, 10, 2, 2, [tl, tr, bl, br])]
    assert sum(pid == PacketID.PLI_BOARDMODIFY for pid, _ in c.sent) == 1


def test_zero_sword_power_does_not_cut(new_client):
    c = new_client()
    plant(c.tiles)
    c.player.sword_power = 0
    c.sword_attack()
    assert c.modifications == c.effects == []
    assert c.get_tile(10, 10) == BUSH_OBJECTS[0][0]


@pytest.mark.parametrize('action', [10, 13])
def test_blocked_action_mode_does_not_cut(action, new_client):
    c = new_client()
    plant(c.tiles)
    c.player.action_mode = action
    c.sword_attack()
    assert c.modifications == []


@pytest.mark.parametrize('animation', ['dead', 'spin'])
def test_blocked_animation_does_not_cut(animation, new_client):
    c = new_client()
    plant(c.tiles)
    c.player.animation = animation
    c.sword_attack()
    assert c.modifications == []


@pytest.mark.parametrize('tile_type', [4, 11, 12, 20, 22])
def test_can_lay_item_wall_and_water_gate(tile_type, new_client):
    c = new_client()
    c.player.x = 8.0
    plant(c.tiles)
    c.tiles[9 + 10 * 64] = next(i for i, t in enumerate(tiletypes.TILE_TYPES) if t == tile_type)
    assert not c._can_lay_item(2)


@pytest.mark.parametrize('obstacle', ['npc', 'chest', 'bomb'])
def test_can_lay_item_entity_gate(obstacle, new_client):
    c = new_client()
    c.player.x = 8.0
    plant(c.tiles)
    if obstacle == 'npc':
        c.gs1_host = SimpleNamespace(rt=SimpleNamespace(npc_blocks_at=lambda x, y: True))
    elif obstacle == 'chest':
        c.chests[LEVEL] = {(9, 10): False}
    else:
        c.bombs[LEVEL] = {0: {'x': 9, 'y': 10}}
    assert not c._can_lay_item(2)


@pytest.mark.parametrize('overlay,can_cut', [(6, True), (11, False), (12, False)])
def test_can_lay_item_water_uses_npc_tile_overlay(overlay, can_cut, new_client):
    c = new_client()
    c.player.x = 8.0
    plant(c.tiles)
    c.tiles[9 + 10 * 64] = next(i for i, t in enumerate(tiletypes.TILE_TYPES) if t == 11)
    c.gs1_host = SimpleNamespace(rt=SimpleNamespace(
        npc_blocks_at=lambda x, y: False, npc_tile_type=lambda x, y: overlay))
    assert c._can_lay_item(2) == can_cut


def test_bush_cut_ignores_can_lay_item_gate(new_client):
    # Deliberate deviation: the type-20 bush tile ahead would fail canLayItem.
    c = new_client()
    plant(c.tiles)
    c.tiles[10 + 10 * 64] = BUSH_OBJECTS[0][0]
    assert not c._can_lay_item(2)
    c.sword_attack()
    assert len(c.modifications) == 1


def test_missing_action_level_does_not_cut(new_client):
    c = new_client()
    plant(c.tiles)
    c._current_level_name = ''
    c.sword_attack()
    assert c.modifications == []


@pytest.fixture
def gmap_client(new_client):
    def build():
        # Standing in segment (1, 1) of the fixture gmap (world origin 64, 64).
        c = new_client(gmap=True, gmap_segment=(1, 1))
        c.player.x, c.player.y = 9.0 + 64, 6.0 + 64
        board = c.levels[c.current_level_name]
        # An adjacent preload must not replace the standing segment's board.
        c._pending_level_name = c._tiles_level_name = 'neighbor.nw'
        c.tiles = [0] * 4096
        return c, board
    return build


def test_gmap_uses_standing_board_local_probe_and_world_effect_origin(gmap_client):
    c, board = gmap_client()
    plant(board)
    c.sword_attack()
    assert c.modifications == [(10, 10, 2, 2, [0x2a5, 0x2a6, 0x2b5, 0x2b6])]
    assert c.effects == [(74, 74, 0)]
    assert board[10 + 10 * 64] == 0x2a5
    assert c.tiles == [0] * 4096


@pytest.mark.parametrize('index', [0, 1])
def test_server_explosion_cuts_once_and_preserves_outside_bush(index, new_client):
    c = new_client()
    plant(c.tiles, index=index)
    plant(c.tiles, x=15)
    handle_explosion(c, bytes((32, 32, 33, 52, 52, 35)))  # owner 0, radius 1, (10,10), type 3
    assert len(c.modifications) == 1
    assert c.effects == [(10, 10, index)]
    assert c.get_tile(15, 10) == BUSH_OBJECTS[0][0]


@pytest.mark.parametrize('tiles_type', [1, 2, 5])
def test_explosions_only_cut_classic_tiles(tiles_type, monkeypatch, new_client):
    c = new_client()
    plant(c.tiles)
    c.level_state.tiletypes.register_tiledef('', tiles_type)
    handle_explosion(c, bytes((32, 32, 33, 52, 52, 33)))
    assert c.modifications == c.effects == []


def test_server_explosion_local_position_on_gmap(gmap_client):
    c, board = gmap_client()
    plant(board)
    handle_explosion(c, bytes((32, 32, 33, 52, 52, 33)))
    assert c.effects == [(74, 74, 0)]
    assert (c.active_explosions[0]['x'], c.active_explosions[0]['y']) == (74, 74)


def test_explosion_does_not_wrap_at_level_edge(new_client):
    c = new_client()
    plant(c.tiles, x=0)
    assert c._cut_bushes_at_explosion(63, 10) == set()
    assert c.modifications == []
