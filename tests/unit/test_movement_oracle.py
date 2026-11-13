from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import Mock

import pygame
import pytest
from reborn_protocol import PLSTATUS

from offline_game import GMAP_SEGMENTS, spy
from pyreborn.npc_handler import NPCHandler, NPCShape, TOUCH_OFFSETS
from pyreborn.tiletypes import TileType, is_blocking, type_is_blocking


WALL = next(tile for tile in range(4096) if is_blocking(tile))
LEVEL = 'fixture.nw'
SIGN = 'read me\n'   # the server ends every sign line with a newline


@pytest.fixture
def new_game(make_game, monkeypatch):
    """``new_game(**knobs)``: a real offline game on an open board at
    (20, 20). Call-through spies on the helpers the movement tests read:
    ``game.spies['dir' | 'npc' | 'push' | 'dialogue']``."""
    def build(**knobs):
        knobs.setdefault("player_xy", (20.0, 20.0))
        knobs.setdefault("tiles", lambda tx, ty: 0)
        game = make_game(**knobs)
        # Corner assist has its own tests (test_corner_assist.py); the
        # oracle boundaries here are the plain two-axis moves.
        monkeypatch.setattr(game, '_corner_assist_offset', lambda *args: None)
        game.spies = {
            'dir': spy(monkeypatch, game.player_anim, 'set_direction'),
            'npc': spy(monkeypatch, game.npc_handler, 'process_movement'),
            'push': spy(monkeypatch, game, '_update_push_hold'),
            'dialogue': spy(monkeypatch, game, '_show_dialogue'),
        }
        return game
    return build


@pytest.mark.parametrize('dx,dy,facing', [(-1, -1, 1), (1, -1, 3),
                                         (-1, 1, 2), (1, 1, 3)])
def test_axes_move_independently_in_direction_order(dx, dy, facing, new_game):
    game = new_game()
    game._move(dx, dy)
    assert (game.client.x, game.client.y) == (20 + dx * .25, 20 + dy * .25)
    assert game.client.player.direction == facing
    assert game.spies['dir'][-1] == ((facing,), {})
    calls = game.spies['npc']
    assert len(calls) == 2
    assert calls[-1][0][2] == facing


def test_blocked_last_axis_still_wins_facing_and_other_axis_moves(new_game):
    game = new_game()
    # The right P2 enters (22,20); the down pair remains clear.
    game.client.player.x = 19.75
    game.client.tiles[20 * 64 + 22] = WALL
    game._move(1, 1)
    assert (game.client.x, game.client.y) == (19.75, 20.25)
    assert game.client.player.direction == 3
    assert game.spies['push'][-1][0] == (1, 0)


def test_blocked_first_axis_does_not_prevent_second_axis(new_game):
    game = new_game()
    game.client.tiles[20 * 64 + 22] = WALL
    game._move(1, -1)
    assert (game.client.x, game.client.y) == (20.25, 20)
    assert game.client.player.direction == 3


def test_all_held_keys_are_dispatched_including_opposites(new_game, monkeypatch):
    game = new_game()
    moves = spy(monkeypatch, game, '_move')
    game.key_just_pressed = {}
    game.push.grab = None
    game.current_anim_name = 'idle'
    game.walk_speed, game._frame_dt, game._move_accum = 10, .05, 0
    keys = defaultdict(bool, {key: True for key in
                             (pygame.K_UP, pygame.K_LEFT, pygame.K_DOWN, pygame.K_RIGHT)})
    monkeypatch.setattr(pygame.key, 'get_pressed', lambda: keys)
    game._handle_input(10)
    assert [args for args, _ in moves] == [
        (0, -1), (-1, 0), (0, 1), (1, 0)] * 2
    assert game._move_accum == 0


@pytest.mark.parametrize('x,y,blocked', [(30.5, 31, True), (32.999, 32.999, True),
                                        (32.75, 32, True), (33, 32, False),
                                        (30.499, 32, False), (32, 30.999, False),
                                        (32, 33, False)])
def test_remote_player_half_open_bounds(x, y, blocked, new_game):
    game = new_game()
    game.client.players[7] = {'x': 30, 'y': 30}
    assert game._is_blocked_at(x, y) is blocked


@pytest.mark.parametrize('props', [{'status': PLSTATUS.DEAD}, {'status': PLSTATUS.HIDDEN},
                                   {'isblocking': False}])
def test_nonblocking_dead_hidden_players_are_skipped(props, new_game):
    game = new_game()
    game.client.players[7] = dict(x=30, y=30, **props)
    assert not game._is_blocked_at(31, 32)


@pytest.mark.parametrize('script_flag', [False, True])
def test_no_pk_disables_player_blocking(script_flag, new_game):
    game = new_game()
    game.client.players[7] = {'x': 30, 'y': 30}
    if script_flag:
        game.client.gs2_host = SimpleNamespace(level_object={'isnopkzone': True})
    else:
        game.client.level_nopk = True
    assert not game._is_blocked_at(31, 32)


def test_player_world_coordinates_and_neighbor_level(new_game):
    game = new_game(gmap=True)
    c = game.client
    c.players[7] = {'x': 5, 'y': 30, 'level': GMAP_SEGMENTS[1]}
    assert game._is_blocked_at(70, 32)
    assert not game._is_blocked_at(6, 32)
    c.players[7].update(world_x=80, world_y=30)
    assert game._is_blocked_at(81, 32)
    assert not game._is_blocked_at(70, 32)


@pytest.mark.parametrize('source', ['wire', 'local'])
@pytest.mark.parametrize('x,y,blocked', [(30.25, 30, True), (32.999, 31.999, True),
                                        (30.249, 31, False), (33, 31, False),
                                        (31, 29.999, False), (31, 32, False)])
def test_active_bomb_bounds(source, x, y, blocked, new_game):
    game = new_game()
    if source == 'wire':
        game.client.bombs[LEVEL] = {0: {'x': 30, 'y': 30}}
    else:
        game.active_bombs = [{'x': 30, 'y': 30, 'exploded': False}]
    assert game._is_blocked_at(x, y) is blocked


def test_exploded_bomb_stops_blocking(new_game):
    game = new_game()
    game.active_bombs = [{'x': 30, 'y': 30, 'exploded': True}]
    assert not game._is_blocked_at(31, 31)


def test_type_five_is_passable_but_upper_bed_and_walls_block(new_game):
    assert not type_is_blocking(TileType.BED_LOWER)
    assert type_is_blocking(TileType.BED_UPPER)
    assert all(type_is_blocking(t) for t in range(20, 27))
    game = new_game()
    game._tile_type = lambda tile: TileType.BED_LOWER
    assert not game._is_blocked_at(31, 31)


@pytest.mark.parametrize('direction', range(4))
def test_npc_touch_uses_only_the_two_facing_probes(direction, make_client):
    handler = NPCHandler(make_client())
    # A footprint solely under the old centre probe must not trigger touch.
    handler.npc_shapes[1] = NPCShape(x=11.4, y=12.4, width=.2, height=.2)
    assert handler.check_touch(10, 10, direction) == []
    for ox, oy in TOUCH_OFFSETS[direction]:
        handler.npc_shapes[2] = NPCShape(x=10 + ox - .01, y=10 + oy - .01,
                                       width=.02, height=.02)
        assert handler.check_touch(10, 10, direction) == [2]


@pytest.fixture
def sign_game(new_game):
    """A real game with a sign at (21, 20) whose tile blocks, facing up."""
    game = new_game(signs=[(21, 20, 'read me')])
    game.client.tiles[20 * 64 + 21] = WALL
    game.client.player.direction = 0
    return game


def test_walk_up_sign_opens_once_until_contact_is_left(sign_game):
    game = sign_game
    dialogue = game.spies['dialogue']
    game._move(0, -1)
    game._move(0, -1)
    assert dialogue == [((SIGN,), {'classic_font': True})]
    assert (game.client.x, game.client.y) == (20, 20)
    game._move(0, 1)
    game.client.player.y = 20
    game._move(0, -1)
    assert len(dialogue) == 2


@pytest.mark.parametrize('x,y,inside', [(19.5, 19.5, True), (21.5, 20.5, True),
                                       (19.499, 20, False), (21.501, 20, False),
                                       (20, 19.499, False), (20, 20.501, False)])
def test_sign_probe_box_has_inclusive_upper_bounds(x, y, inside, sign_game, monkeypatch):
    game = sign_game
    game.client.player.x, game.client.player.y = x, y
    blocked = Mock(return_value=True)
    monkeypatch.setattr(game, '_is_blocked_at', blocked)
    assert (game._check_sign_nearby() == SIGN) is inside
    if inside:
        blocked.assert_called_with(x + 1.5, y + .5, check_players=False)


@pytest.mark.parametrize('direction', [1, 2, 3])
def test_sign_requires_facing_up(direction, sign_game):
    game = sign_game
    game.client.player.direction = direction
    assert game._check_sign_nearby() is None


def test_sign_requires_wall_and_a_uses_same_contact_latch(sign_game):
    game = sign_game
    game.client.tiles[20 * 64 + 21] = 0
    assert game._check_sign_nearby() is None
    game.client.tiles[20 * 64 + 21] = WALL
    assert game._check_sign_nearby() == SIGN
    game._move(0, -1)
    assert game.spies['dialogue'] == []


def test_links_keep_oracle_inclusive_bound(new_game):
    game = new_game()
    c = game.client
    c.player.x, c.player.y, c.player.direction = 20.5, 20, 3
    link = dict(x=22, y=21, width=1, height=1, dest_level='inside.nw')
    c.links[LEVEL] = [link]
    assert c.check_link_collision() is link
    c.player.x += 1
    assert c.check_link_collision() is None


@pytest.mark.parametrize('direction,offset', [(0, (1.5, 1)), (1, (.5, 2)),
                                              (2, (1.5, 3)), (3, (2.5, 2))])
def test_link_uses_one_continuous_directional_probe(direction, offset, new_game):
    game = new_game()
    c = game.client
    c.player.direction = direction
    dx, dy = offset
    link = dict(x=22, y=22, width=1, height=1, dest_level='inside.nw')
    c.links[LEVEL] = [link]
    c.player.x, c.player.y = 22 - dx, 22 - dy
    assert c.check_link_collision() is link
    c.player.x += 1
    assert c.check_link_collision() is link
    c.player.x += .001
    assert c.check_link_collision() is None


def test_bomb_box_crosses_segment_boundary_and_explosion_overrides_wire_copy(new_game):
    game = new_game(gmap=True)
    c = game.client
    c.bombs[c.current_level_name] = {0: {'x': 62, 'y': 30}}
    assert game._is_blocked_at(64.5, 31)
    game.active_bombs = [{'x': 62, 'y': 30, 'exploded': True}]
    assert not game._is_blocked_at(64.5, 31)
