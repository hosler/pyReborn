import math

import pytest

from offline_game import GMAP_SEGMENTS, spy
from pyreborn.jumping import (
    JUMP_DELTA_X_SIDE, JUMP_DELTA_Y_DOWN, JUMP_DELTA_Y_SIDE,
    JUMP_DELTA_Y_UP, JUMP_LANDING_OFFSET, JumpState,
)
from pyreborn.tiletypes import TILE_TYPES

LEDGE = next(i for i, kind in enumerate(TILE_TYPES) if kind == 21)
WALL = next(i for i, kind in enumerate(TILE_TYPES) if kind == 22)


@pytest.fixture
def new_game(make_game, monkeypatch):
    """``new_game(**knobs)``: a real offline game on an open board at
    (20, 20). ``game.sound_calls`` / ``game.anim_calls`` record what the
    sound manager and the player's animation state were asked (call-through);
    ``sounds(game)`` and ``animations(game)`` read them."""
    def build(**knobs):
        knobs.setdefault("player_xy", (20.0, 20.0))
        knobs.setdefault("tiles", lambda tx, ty: 0)
        game = make_game(**knobs)
        game.sound_calls = spy(monkeypatch, game.sound_mgr, "play")
        game.anim_calls = spy(monkeypatch, game.player_anim, "set_animation")
        game.current_anim_name = 'idle'
        return game
    return build


def sounds(game):
    return [args[0] for args, _ in game.sound_calls]


def animations(game):
    return [args for args, _ in game.anim_calls]


def set_tile(game, x, y, tile):
    if game.client.in_gmap_segment:
        name = game.client.gmap_grid[(math.floor(x / 64), math.floor(y / 64))]
        game.client.levels[name][math.floor(x) % 64 + (math.floor(y) % 64) * 64] = tile
    else:
        game.client.tiles[math.floor(x) + math.floor(y) * 64] = tile


def plant_ledge(game, direction):
    dx, dy = ((0, -1), (-1, 0), (0, 1), (1, 0))[direction]
    set_tile(game, game.client.x + 1.5 + dx * 1.5,
             game.client.y + 2 + dy * 1.5, LEDGE)


def test_jump_tables_match_oracle():
    assert JUMP_DELTA_Y_UP == (-0.2, 0.2, 0.5, 1.5, 2.8, 4, 5.4, 7)
    assert JUMP_DELTA_Y_SIDE == (-0.2, -0.5, 0, 0.5, 1.1, 1.7, 2.3, 3)
    assert JUMP_DELTA_X_SIDE == (1, 2, 3, 3.8, 4.5, 5.2, 5.8, 6.5)
    assert JUMP_DELTA_Y_DOWN == (1.5, 2.7, 3.8, 4.5, 5, 5.2, 5.2, 5)
    assert JUMP_LANDING_OFFSET == ((0, -5), (-6.5, 3), (0, 7), (6.5, 3))


@pytest.mark.parametrize('direction,path', [
    (0, [(0, -d) for d in (1.5, 2.7, 3.8, 4.5, 5, 5.2, 5.2, 5)]),
    (1, [(-x, y) for x, y in zip((1, 2, 3, 3.8, 4.5, 5.2, 5.8, 6.5),
                                  (-0.2, -0.5, 0, 0.5, 1.1, 1.7, 2.3, 3))]),
    (2, [(0, d) for d in (-0.2, 0.2, 0.5, 1.5, 2.8, 4, 5.4, 7)]),
    (3, list(zip((1, 2, 3, 3.8, 4.5, 5.2, 5.8, 6.5),
                  (-0.2, -0.5, 0, 0.5, 1.1, 1.7, 2.3, 3))))])
def test_arc_positions_per_tick(direction, path):
    state = JumpState(20, 30, direction)
    seen = []
    for tick in range(8):
        done = state.advance(0.05, lambda x, y: seen.append((x - 20, y - 30)))
        assert seen[-1] == pytest.approx(path[tick])
        assert done == (tick == 7)


@pytest.mark.parametrize('direction', range(4))
def test_ledge_starts_and_lands_at_oracle_offset(direction, new_game):
    game = new_game()
    plant_ledge(game, direction)
    assert game._try_start_ledge_jump(direction)
    assert game.client.player.action_mode == 2
    assert sounds(game) == ['jump.wav']
    for _ in range(8):
        game._advance_ledge_jump(0.05)
    dx, dy = JUMP_LANDING_OFFSET[direction]
    assert (game.client.x, game.client.y) == pytest.approx((20 + dx, 20 + dy))
    assert game.client.player.action_mode == 0
    assert game._ledge_jump is None


@pytest.mark.parametrize('direction', range(4))
def test_blocked_landing_keeps_ledge_a_wall(direction, new_game):
    game = new_game()
    plant_ledge(game, direction)
    dx, dy = JUMP_LANDING_OFFSET[direction]
    set_tile(game, 21.5 + dx, 22 + dy, WALL)
    assert not game._try_start_ledge_jump(direction)
    assert game._is_blocked_at(21.5 + (0, -1.5, 0, 1.5)[direction],
                               22 + (-1.5, 0, 1.5, 0)[direction])
    assert sounds(game) == []


@pytest.mark.parametrize('kind', [0, 3, 4, 6, 11, 20, 22])
def test_other_tile_types_never_start_jump(kind, new_game):
    game = new_game()
    tile = next(i for i, value in enumerate(TILE_TYPES) if value == kind)
    set_tile(game, 21.5, 23.5, tile)
    assert not game._try_start_ledge_jump(2)
    assert (game.client.x, game.client.y) == (20, 20)


def test_landing_player_blocks_jump(new_game):
    game = new_game()
    plant_ledge(game, 3)
    game.client.players[99] = {'x': 27, 'y': 24}
    assert not game._try_start_ledge_jump(3)


def test_missing_gani_does_not_prevent_motion_or_change_pose(new_game):
    game = new_game()
    game.current_anim_name = 'walk'
    plant_ledge(game, 2)
    assert game._try_start_ledge_jump(2)
    assert animations(game) == []
    assert game.current_anim_name == 'walk'
    game._advance_ledge_jump(0.4)
    assert (game.client.x, game.client.y) == (20, 27)
    assert game.current_anim_name == 'idle'


def test_available_jump_gani_is_played(new_game, monkeypatch):
    game = new_game()
    real_parse = game.gani_parser.parse
    # A jump gani exists: answer it with a real (looping) gani's data.
    monkeypatch.setattr(game.gani_parser, 'parse',
                        lambda name: real_parse('walk' if name == 'jump' else name))
    plant_ledge(game, 2)
    game._try_start_ledge_jump(2)
    assert animations(game) == [('jump', 2)]
    assert game.client.player.animation == 'jump'


def test_motion_ignores_intermediate_walls_after_landing_check(new_game):
    game = new_game()
    plant_ledge(game, 3)
    assert game._try_start_ledge_jump(3)
    game._is_blocked_at = lambda x, y: pytest.fail('arc must ignore collision')
    game._advance_ledge_jump(0.4)
    assert (game.client.x, game.client.y) == (26.5, 23)


def test_jump_starts_from_held_movement_after_eighteen_ticks(sim_time, monkeypatch, new_game):
    game = new_game()
    plant_ledge(game, 2)
    sim_time(lambda: 100.0)
    game._move(0, 1)
    assert getattr(game, '_ledge_jump', None) is None
    sim_time(lambda: 100.89)
    game._move(0, 1)
    assert getattr(game, '_ledge_jump', None) is None
    sim_time(lambda: 100.91)
    game._move(0, 1)
    assert game._ledge_jump is not None
    assert (game.client.x, game.client.y) == (20, 20)


def test_jump_ignores_input_until_landing(new_game):
    game = new_game()
    plant_ledge(game, 2)
    game._try_start_ledge_jump(2)
    game._move(-1, 0)
    assert game.client.player.direction == 2
    game._advance_ledge_jump(0.4)
    assert (game.client.x, game.client.y) == (20, 27)


def test_hurt_interrupts_jump(new_game):
    game = new_game()
    plant_ledge(game, 2)
    game._try_start_ledge_jump(2)
    game.client.respond_to_hurt(0.5)
    game._advance_ledge_jump(0.4)
    assert game._ledge_jump is None
    assert game.client.player.action_mode == 3


def test_gmap_probes_and_arc_cross_seam(new_game):
    game = new_game(gmap=True, gmap_segment=(0, 0))
    c = game.client
    c.player.x, c.player.y = 61, 20.0
    plant_ledge(game, 3)  # Probe is in the next segment, at world x=64.
    assert game._try_start_ledge_jump(3)
    game._advance_ledge_jump(0.4)
    assert (c.x, c.y) == (67.5, 23)
    assert c._current_level_name == GMAP_SEGMENTS[1]


def test_landing_off_standalone_board_is_blocked(new_game):
    game = new_game()
    game.client.player.x = 59
    plant_ledge(game, 3)
    assert not game._try_start_ledge_jump(3)


def test_composed_game_renders_missing_gani_jump_through_landing(new_game):
    game = new_game()
    plant_ledge(game, 3)
    assert game._try_start_ledge_jump(3)
    for _ in range(8):
        game._update_animations(0.05)
        game._render()
    assert (game.client.x, game.client.y) == (26.5, 23)
    assert game.current_anim_name == 'idle'
