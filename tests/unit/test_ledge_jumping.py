"""Official canJump/animateJumping coordinates and game integration."""

import math
from types import SimpleNamespace

import pytest

from pyreborn import Client
from pyreborn.game.actions import ActionsMixin
from pyreborn.game.collision import CollisionMixin
from pyreborn.jumping import (
    JUMP_DELTA_X_SIDE, JUMP_DELTA_Y_DOWN, JUMP_DELTA_Y_SIDE,
    JUMP_DELTA_Y_UP, JUMP_LANDING_OFFSET, JumpState,
)
from pyreborn.tiletypes import TILE_TYPES

LEDGE = next(i for i, kind in enumerate(TILE_TYPES) if kind == 21)
WALL = next(i for i, kind in enumerate(TILE_TYPES) if kind == 22)


class Game(ActionsMixin, CollisionMixin):
    def __init__(self):
        self.client = Client('localhost', 14900)
        self.client._authenticated = True
        self.sent = []
        self.client._protocol = SimpleNamespace(connected=True,
            send_packet=lambda p, d=b'': self.sent.append((p, d)) or True)
        self.client._current_level_name = self.client._tiles_level_name = 'jump.nw'
        self.client.tiles = [0] * 4096
        self.client.levels['jump.nw'] = self.client.tiles
        self.client.player.x = self.client.player.y = 20.0
        self.animations, self.sounds = [], []
        self.player_anim = SimpleNamespace(
            set_direction=lambda d: None,
            set_animation=lambda *a, **kw: self.animations.append(a))
        self.sound_mgr = SimpleNamespace(play=self.sounds.append)
        self.gani_parser = SimpleNamespace(parse=lambda name: None)
        self.current_anim_name = 'idle'
        self._push_hold_dir = None
        self._push_hold_start = 0
        self.is_pushing = False
        self.is_moving = False
        self._find_chest_in_front = lambda: None
        self._update_swimming_state = lambda: None
        self._try_link_warp = lambda: None
        self.npc_handler = SimpleNamespace(process_movement=lambda *a: None)

    def set_tile(self, x, y, tile):
        if self.client.in_gmap_segment:
            name = self.client.gmap_grid[(math.floor(x / 64), math.floor(y / 64))]
            self.client.levels[name][math.floor(x) % 64 + (math.floor(y) % 64) * 64] = tile
        else:
            self.client.tiles[math.floor(x) + math.floor(y) * 64] = tile

    def plant_ledge(self, direction):
        dx, dy = ((0, -1), (-1, 0), (0, 1), (1, 0))[direction]
        self.set_tile(self.client.x + 1.5 + dx * 1.5,
                      self.client.y + 2 + dy * 1.5, LEDGE)


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
def test_ledge_starts_and_lands_at_oracle_offset(direction):
    game = Game()
    game.plant_ledge(direction)
    assert game._try_start_ledge_jump(direction)
    assert game.client.player.action_mode == 2
    assert game.sounds == ['jump.wav']
    for _ in range(8):
        game._advance_ledge_jump(0.05)
    dx, dy = JUMP_LANDING_OFFSET[direction]
    assert (game.client.x, game.client.y) == pytest.approx((20 + dx, 20 + dy))
    assert game.client.player.action_mode == 0
    assert game._ledge_jump is None


@pytest.mark.parametrize('direction', range(4))
def test_blocked_landing_keeps_ledge_a_wall(direction):
    game = Game()
    game.plant_ledge(direction)
    dx, dy = JUMP_LANDING_OFFSET[direction]
    game.set_tile(21.5 + dx, 22 + dy, WALL)
    assert not game._try_start_ledge_jump(direction)
    assert game._is_blocked_at(21.5 + (0, -1.5, 0, 1.5)[direction],
                               22 + (-1.5, 0, 1.5, 0)[direction])
    assert game.sounds == []


@pytest.mark.parametrize('kind', [0, 3, 4, 6, 11, 20, 22])
def test_other_tile_types_never_start_jump(kind):
    game = Game()
    tile = next(i for i, value in enumerate(TILE_TYPES) if value == kind)
    game.set_tile(21.5, 23.5, tile)
    assert not game._try_start_ledge_jump(2)
    assert (game.client.x, game.client.y) == (20, 20)


def test_landing_player_blocks_jump():
    game = Game()
    game.plant_ledge(3)
    game.client.players[99] = {'x': 27, 'y': 24}
    assert not game._try_start_ledge_jump(3)


def test_missing_gani_does_not_prevent_motion_or_change_pose():
    game = Game()
    game.current_anim_name = 'walk'
    game.plant_ledge(2)
    assert game._try_start_ledge_jump(2)
    assert game.animations == []
    assert game.current_anim_name == 'walk'
    game._advance_ledge_jump(0.4)
    assert (game.client.x, game.client.y) == (20, 27)
    assert game.current_anim_name == 'idle'


def test_available_jump_gani_is_played():
    game = Game()
    game.gani_parser.parse = lambda name: object()
    game.plant_ledge(2)
    game._try_start_ledge_jump(2)
    assert game.animations == [('jump', 2)]
    assert game.client.player.animation == 'jump'


def test_motion_ignores_intermediate_walls_after_landing_check():
    game = Game()
    game.plant_ledge(3)
    assert game._try_start_ledge_jump(3)
    game._is_blocked_at = lambda x, y: pytest.fail('arc must ignore collision')
    game._advance_ledge_jump(0.4)
    assert (game.client.x, game.client.y) == (26.5, 23)


def test_jump_starts_from_held_movement_after_eighteen_ticks(sim_time, monkeypatch):
    game = Game()
    game.plant_ledge(2)
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


def test_jump_ignores_input_until_landing():
    game = Game()
    game.plant_ledge(2)
    game._try_start_ledge_jump(2)
    game._move(-1, 0)
    assert game.client.player.direction == 2
    game._advance_ledge_jump(0.4)
    assert (game.client.x, game.client.y) == (20, 27)


def test_hurt_interrupts_jump():
    game = Game()
    game.plant_ledge(2)
    game._try_start_ledge_jump(2)
    game.client.respond_to_hurt(0.5)
    game._advance_ledge_jump(0.4)
    assert game._ledge_jump is None
    assert game.client.player.action_mode == 3


def test_gmap_probes_and_arc_cross_seam():
    game = Game()
    c = game.client
    c.gmap_width, c.gmap_height = 2, 1
    c.gmap_grid.update({(0, 0): 'jump.nw', (1, 0): 'next.nw'})
    c.levels['next.nw'] = [0] * 4096
    c.player.x = 61
    game.plant_ledge(3)  # Probe is in the next segment, at world x=64.
    assert game._try_start_ledge_jump(3)
    game._advance_ledge_jump(0.4)
    assert (c.x, c.y) == (67.5, 23)
    assert c._current_level_name == 'next.nw'


def test_landing_off_standalone_board_is_blocked():
    game = Game()
    game.client.player.x = 59
    game.plant_ledge(3)
    assert not game._try_start_ledge_jump(3)


def test_composed_game_renders_missing_gani_jump_through_landing():
    from pyreborn.pygame_game import GameClient
    harness = Game()
    harness.plant_ledge(3)
    game = GameClient(harness.client)
    assert game._try_start_ledge_jump(3)
    for _ in range(8):
        game._update_animations(0.05)
        game._render()
    assert (game.client.x, game.client.y) == (26.5, 23)
    assert game.current_anim_name == 'idle'
