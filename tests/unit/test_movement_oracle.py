"""Movement and contact boundaries checked against the official client."""

from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import Mock

import pygame
import pytest
from reborn_protocol import PLSTATUS

from pyreborn import Client
from pyreborn.game.actions import ActionsMixin
from pyreborn.game.collision import CollisionMixin
from pyreborn.game.input import InputMixin
from pyreborn.game.render_objects import LevelObjectsRenderMixin
from pyreborn.npc_handler import NPCHandler, NPCShape, TOUCH_OFFSETS
from pyreborn.tiletypes import TileType, is_blocking, type_is_blocking


WALL = next(tile for tile in range(4096) if is_blocking(tile))


class Game(ActionsMixin, CollisionMixin, LevelObjectsRenderMixin):
    def __init__(self):
        self.client = Client('localhost', 14900)
        self.client._authenticated = True
        self.client._protocol = SimpleNamespace(connected=True, send_packet=Mock(return_value=True))
        self.client._current_level_name = 'test.nw'
        self.client.tiles = [0] * 4096
        self.client.levels['test.nw'] = self.client.tiles
        self.client.player.x = self.client.player.y = 20.0
        self.sound_mgr = Mock()
        self.player_anim = Mock()
        self.npc_handler = Mock()
        self.current_anim_name = 'idle'
        self.is_swimming = False
        self._find_chest_in_front = lambda: None
        self._try_link_warp = Mock()
        self._update_swimming_state = Mock()
        self._update_push_hold = Mock()
        self._clear_push_hold = Mock()
        self._corner_assist_offset = lambda *args: None
        self._show_dialogue = Mock()


@pytest.mark.parametrize('dx,dy,facing', [(-1, -1, 1), (1, -1, 3),
                                         (-1, 1, 2), (1, 1, 3)])
def test_axes_move_independently_in_direction_order(dx, dy, facing):
    game = Game()
    game._move(dx, dy)
    assert (game.client.x, game.client.y) == (20 + dx * .25, 20 + dy * .25)
    assert game.client.player.direction == facing
    game.player_anim.set_direction.assert_called_with(facing)
    calls = game.npc_handler.process_movement.call_args_list
    assert len(calls) == 2
    assert calls[-1].args[2] == facing


def test_blocked_last_axis_still_wins_facing_and_other_axis_moves():
    game = Game()
    # The right P2 enters (22,20); the down pair remains clear.
    game.client.player.x = 19.75
    game.client.tiles[20 * 64 + 22] = WALL
    game._move(1, 1)
    assert (game.client.x, game.client.y) == (19.75, 20.25)
    assert game.client.player.direction == 3
    assert game._update_push_hold.call_args.args == (1, 0)


def test_blocked_first_axis_does_not_prevent_second_axis():
    game = Game()
    game.client.tiles[20 * 64 + 22] = WALL
    game._move(1, -1)
    assert (game.client.x, game.client.y) == (20.25, 20)
    assert game.client.player.direction == 3


def test_all_held_keys_are_dispatched_including_opposites(monkeypatch):
    class InputGame(Game, InputMixin):
        pass
    game = InputGame()
    for attr in ('typing', 'show_player_list', 'show_server_list', 'is_swimming'):
        setattr(game, attr, False)
    game.dialogue_text = game.pm_target_id = None
    game.inventory_ui = SimpleNamespace(visible=False)
    game._ensure_settings_ui = lambda: SimpleNamespace(visible=False)
    game._admin_overlay_captures_keys = game._gs2_gui_captures_keys = lambda: False
    game._feed_gs1_input = game._fire_gs1_keypress_queue = Mock()
    game._auto_pickup_items = game._clear_grab_state = Mock()
    game.gs1 = SimpleNamespace(default_movement=True)
    game._move = Mock()
    game.key_just_pressed = {}
    game.grab_state = None
    game.current_anim_name = 'idle'
    game.walk_speed, game._frame_dt, game._move_accum = 10, .05, 0
    keys = defaultdict(bool, {key: True for key in
                             (pygame.K_UP, pygame.K_LEFT, pygame.K_DOWN, pygame.K_RIGHT)})
    monkeypatch.setattr(pygame.key, 'get_pressed', lambda: keys)
    game._handle_input(10)
    assert [call.args for call in game._move.call_args_list] == [
        (0, -1), (-1, 0), (0, 1), (1, 0)] * 2
    assert game._move_accum == 0


@pytest.mark.parametrize('x,y,blocked', [(30.5, 31, True), (32.999, 32.999, True),
                                        (32.75, 32, True), (33, 32, False),
                                        (30.499, 32, False), (32, 30.999, False),
                                        (32, 33, False)])
def test_remote_player_half_open_bounds(x, y, blocked):
    game = Game()
    game.client.players[7] = {'x': 30, 'y': 30}
    assert game._is_blocked_at(x, y) is blocked


@pytest.mark.parametrize('props', [{'status': PLSTATUS.DEAD}, {'status': PLSTATUS.HIDDEN},
                                   {'isblocking': False}])
def test_nonblocking_dead_hidden_players_are_skipped(props):
    game = Game()
    game.client.players[7] = dict(x=30, y=30, **props)
    assert not game._is_blocked_at(31, 32)


@pytest.mark.parametrize('script_flag', [False, True])
def test_no_pk_disables_player_blocking(script_flag):
    game = Game()
    game.client.players[7] = {'x': 30, 'y': 30}
    if script_flag:
        game.client.gs2_host = SimpleNamespace(level_object={'isnopkzone': True})
    else:
        game.client.level_nopk = True
    assert not game._is_blocked_at(31, 32)


def test_player_world_coordinates_and_neighbor_level():
    game = Game()
    c = game.client
    c.gmap_width, c.gmap_height = 2, 1
    c.gmap_grid = {(0, 0): 'test.nw', (1, 0): 'east.nw'}
    c.levels['east.nw'] = [0] * 4096
    c.players[7] = {'x': 5, 'y': 30, 'level': 'east.nw'}
    assert game._is_blocked_at(70, 32)
    assert not game._is_blocked_at(6, 32)
    c.players[7].update(world_x=80, world_y=30)
    assert game._is_blocked_at(81, 32)
    assert not game._is_blocked_at(70, 32)


@pytest.mark.parametrize('source', ['wire', 'local'])
@pytest.mark.parametrize('x,y,blocked', [(30.25, 30, True), (32.999, 31.999, True),
                                        (30.249, 31, False), (33, 31, False),
                                        (31, 29.999, False), (31, 32, False)])
def test_active_bomb_bounds(source, x, y, blocked):
    game = Game()
    if source == 'wire':
        game.client.bombs['test.nw'] = {0: {'x': 30, 'y': 30}}
    else:
        game.active_bombs = [{'x': 30, 'y': 30, 'exploded': False}]
    assert game._is_blocked_at(x, y) is blocked


def test_exploded_bomb_stops_blocking():
    game = Game()
    game.active_bombs = [{'x': 30, 'y': 30, 'exploded': True}]
    assert not game._is_blocked_at(31, 31)


def test_type_five_is_passable_but_upper_bed_and_walls_block():
    assert not type_is_blocking(TileType.BED_LOWER)
    assert type_is_blocking(TileType.BED_UPPER)
    assert all(type_is_blocking(t) for t in range(20, 27))
    game = Game()
    game._tile_type = lambda tile: TileType.BED_LOWER
    assert not game._is_blocked_at(31, 31)


@pytest.mark.parametrize('direction', range(4))
def test_npc_touch_uses_only_the_two_facing_probes(direction):
    handler = NPCHandler(SimpleNamespace(npcs={}))
    # A footprint solely under the old centre probe must not trigger touch.
    handler.npc_shapes[1] = NPCShape(x=11.4, y=12.4, width=.2, height=.2)
    assert handler.check_touch(10, 10, direction) == []
    for ox, oy in TOUCH_OFFSETS[direction]:
        handler.npc_shapes[2] = NPCShape(x=10 + ox - .01, y=10 + oy - .01,
                                       width=.02, height=.02)
        assert handler.check_touch(10, 10, direction) == [2]


def sign_game():
    game = Game()
    game.client.signs['test.nw'] = {(21, 20): 'read me'}
    game.client.tiles[20 * 64 + 21] = WALL
    game.client.player.direction = 0
    return game


def test_walk_up_sign_opens_once_until_contact_is_left():
    game = sign_game()
    game._move(0, -1)
    game._move(0, -1)
    game._show_dialogue.assert_called_once_with('read me', classic_font=True)
    assert (game.client.x, game.client.y) == (20, 20)
    game._move(0, 1)
    game.client.player.y = 20
    game._move(0, -1)
    assert game._show_dialogue.call_count == 2


@pytest.mark.parametrize('x,y,inside', [(19.5, 19.5, True), (21.5, 20.5, True),
                                       (19.499, 20, False), (21.501, 20, False),
                                       (20, 19.499, False), (20, 20.501, False)])
def test_sign_probe_box_has_inclusive_upper_bounds(x, y, inside):
    game = sign_game()
    game.client.player.x, game.client.player.y = x, y
    game._is_blocked_at = Mock(return_value=True)
    assert (game._check_sign_nearby() == 'read me') is inside
    if inside:
        game._is_blocked_at.assert_called_with(x + 1.5, y + .5, check_players=False)


@pytest.mark.parametrize('direction', [1, 2, 3])
def test_sign_requires_facing_up(direction):
    game = sign_game()
    game.client.player.direction = direction
    assert game._check_sign_nearby() is None


def test_sign_requires_wall_and_a_uses_same_contact_latch():
    game = sign_game()
    game.client.tiles[20 * 64 + 21] = 0
    assert game._check_sign_nearby() is None
    game.client.tiles[20 * 64 + 21] = WALL
    assert game._check_sign_nearby() == 'read me'
    game._move(0, -1)
    game._show_dialogue.assert_not_called()


def test_links_keep_oracle_inclusive_bound():
    game = Game()
    c = game.client
    c.player.x, c.player.y, c.player.direction = 20.5, 20, 3
    link = dict(x=22, y=21, width=1, height=1, dest_level='inside.nw')
    c.links['test.nw'] = [link]
    assert c.check_link_collision() is link
    c.player.x += 1
    assert c.check_link_collision() is None


@pytest.mark.parametrize('direction,offset', [(0, (1.5, 1)), (1, (.5, 2)),
                                              (2, (1.5, 3)), (3, (2.5, 2))])
def test_link_uses_one_continuous_directional_probe(direction, offset):
    game = Game()
    c = game.client
    c.player.direction = direction
    dx, dy = offset
    link = dict(x=22, y=22, width=1, height=1, dest_level='inside.nw')
    c.links['test.nw'] = [link]
    c.player.x, c.player.y = 22 - dx, 22 - dy
    assert c.check_link_collision() is link
    c.player.x += 1
    assert c.check_link_collision() is link
    c.player.x += .001
    assert c.check_link_collision() is None


def test_bomb_box_crosses_segment_boundary_and_explosion_overrides_wire_copy():
    game = Game()
    c = game.client
    c.gmap_width, c.gmap_height = 2, 1
    c.gmap_grid = {(0, 0): 'test.nw', (1, 0): 'east.nw'}
    c.levels['east.nw'] = [0] * 4096
    c.bombs['test.nw'] = {0: {'x': 62, 'y': 30}}
    assert game._is_blocked_at(64.5, 31)
    game.active_bombs = [{'x': 62, 'y': 30, 'exploded': True}]
    assert not game._is_blocked_at(64.5, 31)
