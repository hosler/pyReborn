"""Explosion cells, exact board patterns, packet expansion, and sprite depth."""

import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

import pygame
import pytest

from offline_game import spy
from pyreborn import tiletypes
from pyreborn.bushcut import BUSH_OBJECTS, BUSH_REPLACE
from pyreborn.explosions import (
    ARM_SPRITE_ROWS, ARM_STEP, BUSH_LEAPS, CENTER_ROW, EXPLOSION_SPRITES,
    EXPLOSION_TICKS, MAX_RADIUS, BlastBlock, ExplosionCell, board_blocks_at,
    bomb_crosses, cross_cells, explosion_damage, explosion_sound,
    explosion_sprite, hits_player, knockback, order_point_y,
)
from pyreborn.game.frame_context import FrameContext
from pyreborn.game.render_effects import EffectsRenderMixin
from pyreborn.handlers.combat import handle_explosion
from pyreborn.liftobjects import LIFT_OBJECTS, LIFT_REPLACE
from .test_bushcut import gmap_client, new_client  # noqa: F401


def plant(board, x, y, pattern):
    for dx in range(2):
        for dy in range(2):
            board[x + dx + (y + dy) * 64] = pattern[dx * 2 + dy]


def test_radius_two_cells_in_oracle_order():
    # TServerLevel.cpp:73-84,1620-1641: centre, up, left, down, right.
    assert cross_cells(10, 20, 2) == [
        ExplosionCell(10, 20, 4),
        ExplosionCell(10, 18, 1), ExplosionCell(10, 16, 0),
        ExplosionCell(8, 20, 3), ExplosionCell(6, 20, 2),
        ExplosionCell(10, 22, 5), ExplosionCell(10, 24, 6),
        ExplosionCell(12, 20, 7), ExplosionCell(14, 20, 8),
    ]
    assert ARM_SPRITE_ROWS == ((6, 1, 0), (8, 3, 2), (0, 5, 6), (2, 7, 8))
    assert ARM_STEP == ((0, -2), (-2, 0), (0, 2), (2, 0))
    assert CENTER_ROW == 4


def test_radius_cap_and_zero_radius_tip_objects():
    # TServerLevel.cpp:1616-1641: cap at 15; tips are outside the distance loop.
    assert MAX_RADIUS == 15
    assert cross_cells(0, 0, 200) == cross_cells(0, 0, 15)
    assert len(cross_cells(0, 0, 15)) == 61
    assert [c.sprite_row for c in cross_cells(0, 0, 0)] == [4, 0, 2, 6, 8]


def test_superbomb_cross_order_and_cell_count():
    # TServerLevel.cpp:1712-1724: retain overlaps as separate objects.
    crosses = bomb_crosses(10, 20, 2)
    assert crosses == [(8, 18, 2), (12, 18, 2), (8, 22, 2),
                       (12, 22, 2), (10, 20, 4)]
    assert sum(len(cross_cells(*cross)) for cross in crosses) == 53
    assert bomb_crosses(10, 20, 1) == bomb_crosses(10, 20, 3) == [(10, 20, 2)]


@pytest.mark.parametrize('kind,sound,damage', [
    (1, 'bomb.wav', .5), (2, 'bomb.wav', .5), (3, 'thunder.wav', 1.0),
])
def test_sounds_and_damage(kind, sound, damage):
    # TServerLevel.cpp:1697; TExplosion.cpp:86.
    assert explosion_sound(kind) == sound
    assert explosion_damage(kind) == damage


@pytest.mark.parametrize('dx,dy', [(-1, -1), (-1, 1), (1, -1), (1, 1), (0, 0)])
def test_hits_player_inclusive_edges(dx, dy):
    # TExplosion.cpp:54-72: compare the cell centre to player+(1.5,2).
    assert hits_player(10, 20, 9.5 + dx, 19 + dy)
    assert not hits_player(10, 20, 10.5001, 19)
    assert not hits_player(10, 20, 9.5, 20.0001)


def test_knockback_all_five_direction_slots():
    # TInitStatics.cpp:1159; TInput.cpp:13; TExplosion.cpp:89-90.
    assert [knockback(row) for row in range(5)] == [
        (0, -1), (-1, 0), (0, 1), (1, 0), (0, -1)]


def test_sprites_and_order_point():
    # TServerLevel.cpp:60-70,1606-1607; TExplosion.cpp:24-30.
    assert [explosion_sprite(row) for row in range(9)] == [
        0x116, 0x11a, 0x12a, 0x12b, 0x11e, 0x122, 0x126, 0x12c, 0x12d]
    assert all(len(row) == 4 for row in EXPLOSION_SPRITES)
    assert EXPLOSION_TICKS == 11
    assert order_point_y(10, .5, 11) == pytest.approx(14.7)
    assert order_point_y(10, .5, 0) == 12.5
    assert BUSH_LEAPS == (1, 0, 3, 2, 2, 2, 0, 2)  # TServerLevel.cpp:56


@pytest.mark.parametrize('pattern,replacement,leap,bush', [
    (BUSH_OBJECTS[0], BUSH_REPLACE[0], 0, 0),
    (BUSH_OBJECTS[1], BUSH_REPLACE[1], 1, 1),
    (LIFT_OBJECTS[1], LIFT_REPLACE[1], 3, None),
    (LIFT_OBJECTS[2], LIFT_REPLACE[2], None, None),
    (LIFT_OBJECTS[3], LIFT_REPLACE[3], None, None),
    (LIFT_OBJECTS[4], LIFT_REPLACE[4], None, None),
])
def test_classic_blocks_once_without_mutating_board(pattern, replacement, leap, bush):
    # TServerLevel.cpp:1547-1590: bush row wins over lift row 0; only lift 0/1 leap.
    board = [0] * 4096
    plant(board, 10, 20, pattern)
    before = board[:]
    assert board_blocks_at(lambda x, y: board[x + y * 64], 0, 10, 20) == [
        BlastBlock(10, 20, replacement, leap, bush)]
    assert board == before


@pytest.mark.parametrize('corner', range(4))
def test_partial_pattern_is_not_a_block(corner):
    # TServerLevel.cpp:218-227: all four tiles must match.
    board = [0] * 4096
    plant(board, 10, 20, BUSH_OBJECTS[0])
    dx, dy = divmod(corner, 2)
    board[10 + dx + (20 + dy) * 64] = 0
    assert board_blocks_at(lambda x, y: board[x + y * 64], 0, 10, 20) == []


@pytest.mark.parametrize('style', [1, 2])
@pytest.mark.parametrize('low', [0, 2, 4, 6, 8, 10, 12, 14])
def test_new_world_formula_and_excluded_pair(style, low):
    # TServerLevel.cpp:1514-1540; buildArray layout TServerLevel.cpp:1486-1488.
    board = [0] * 4096
    pattern = tuple(low + tile for tile in (0x1a0, 0x1b0, 0x1a1, 0x1b1))
    plant(board, 10, 20, pattern)
    blocks = board_blocks_at(lambda x, y: board[x + y * 64], style, 10, 20)
    if low == 10:
        assert blocks == []
    else:
        assert blocks == [BlastBlock(
            10, 20, tuple(low + tile for tile in (0x1c0, 0x1d0, 0x1c1, 0x1d1)),
            BUSH_LEAPS[low // 2])]


def test_probe_cast_truncation_and_level_bounds():
    # TServerLevel.cpp:1505-1508: truncate before checking the unsigned result.
    board = [0] * 4096
    plant(board, 0, 0, BUSH_OBJECTS[0])
    def read(x, y):
        assert 0 <= x < 64 and 0 <= y < 64
        return board[x + y * 64]
    assert len(board_blocks_at(read, 0, -.75, -.75)) == 1
    for x, y in ((-4, 0), (64, 0), (0, -4), (0, 64)):
        assert board_blocks_at(read, 0, x, y) == []


@pytest.mark.parametrize('gmap', [False, True])
def test_packet_expands_cells_and_blasts_arm(gmap, monkeypatch, new_client, gmap_client):
    # TServerLevel.cpp:1624-1641: the arm cells also run putExplosion's probes.
    client, board = gmap_client() if gmap else (new_client(), None)
    board = client.tiles if board is None else board
    plant(board, 14, 10, BUSH_OBJECTS[0])
    client.on_explosion = Mock()
    client.on_leaps = Mock()
    hearts = client.player.hearts
    handle_explosion(client, bytes((32, 32, 34, 52, 52, 35)))  # owner 0,radius=2,x=10,y=10,type=3
    ox, oy = (64, 64) if gmap else (0, 0)
    cells = cross_cells(ox + 10, oy + 10, 2)
    assert [(e['x'], e['y'], e['sprite_row']) for e in client.active_explosions] == [
        (c.x, c.y, c.sprite_row) for c in cells]
    assert all(e['type'] == 3 and e['order_offset'] == 0 for e in client.active_explosions)
    assert len({e['time'] for e in client.active_explosions}) == 1
    assert client.modifications == [(14, 10, 2, 2, [0x2a5, 0x2a6, 0x2b5, 0x2b6])]
    client.on_explosion.assert_called_once_with(ox + 10, oy + 10, 2, 3)
    client.on_leaps.assert_called_once_with(0, ox + 14, oy + 10)
    # TExplosion.cpp:48-96: the standing player is inside an arm cell, so the
    # client hurts itself (type 3 = one heart), once, with no hurt packet.
    assert client.player.hearts == hearts - 1.0


@pytest.mark.parametrize('gmap', [False, True])
def test_stone_patch_notifies_board_renderer_without_debris(gmap, monkeypatch, new_client, gmap_client):
    # TServerLevel.cpp:1582-1586: stones still change tiles but do not spawn leaps.
    client, board = gmap_client() if gmap else (new_client(), None)
    board = client.tiles if board is None else board
    client.on_board_modify = Mock()
    client.on_leaps = Mock()
    plant(board, 10, 10, LIFT_OBJECTS[3])
    ox, oy = (64, 64) if gmap else (0, 0)
    assert client._blast_board_at(ox + 10, oy + 10) == {(ox + 10, oy + 10)}
    client.on_leaps.assert_not_called()
    assert client.effects == []
    info = {
        'x': 10, 'y': 10, 'width': 2, 'height': 2,
        'tiles': [0x72a, 0x72b, 0x73a, 0x73b]}
    if gmap:
        info.update(map_x=1, map_y=1)
    client.on_board_modify.assert_called_once_with(info)


@pytest.fixture
def cell_game(make_game, monkeypatch):
    """A real offline game on an empty board whose art lookup answers nothing
    (the vector fallback draws), with a unit camera (16 px per tile), the
    burst drawing and camera shake stubbed and the sound manager spied
    (``game.sound_calls``)."""
    game = make_game(tiles=lambda tx, ty: 0)
    monkeypatch.setattr(game.camera, 'world_to_screen', lambda x, y: (x * 16, y * 16))
    monkeypatch.setattr(game.sprite_mgr, 'get_sprite', lambda *args, **kw: None)
    game.sound_calls = spy(monkeypatch, game.sound_mgr, 'play')
    game._start_camera_shake = Mock()
    game._render_explosion_burst = Mock()
    return game


def test_callback_wiring_spawns_one_bush_leap_and_invalidates_surface(cell_game):
    # TServerLevel.cpp:1558-1561,2850-2867: one patch and one leap per block.
    game = cell_game
    game._request_asset = Mock()
    game._spawn_leaf_particles = Mock()
    game._spawn_leaps = Mock()
    game._patch_world_surface_for_modify = Mock()
    game.world_surface = object()
    plant(game.client.tiles, 10, 10, BUSH_OBJECTS[0])
    game.client._blast_board_at(10, 10)
    game._spawn_leaf_particles.assert_called_once_with(10, 10)
    game._spawn_leaps.assert_called_once_with(0, 10, 10)
    assert game.world_surface is None


@pytest.mark.parametrize('kind,sound,count', [(1, 'bomb.wav', 9),
                                            (2, 'bomb.wav', 53),
                                            (3, 'thunder.wav', 9)])
def test_detonation_sounds_and_all_cells(cell_game, kind, sound, count):
    # TServerLevel.cpp:1697,1710-1724: bomb type owns sound and cross geometry.
    game = cell_game
    game.client._blast_board_at = Mock()
    bomb = {'x': 10, 'y': 10, 'power': kind}
    assert game._detonate_bomb(bomb, now=100)
    assert not game._detonate_bomb(bomb, now=101)
    assert game.sound_calls == [((sound,), {})]
    assert len(bomb['cells']) == count
    assert game.client._blast_board_at.call_count == count


def test_cell_fallback_and_exact_depth_without_sheet(cell_game):
    # TExplosion.cpp:24-46: top-left draw; timeLeft contributes to sort Y.
    game = cell_game
    frame = FrameContext(in_frame=True)
    game._render_explosion_cell(frame, 3, 4, 4, .1, .5)
    game._render_explosion_burst.assert_not_called()
    assert len(frame.world_draws) == 1
    draw, depth = frame.world_draws[0]
    assert depth == pytest.approx(order_point_y(4, .5, 9))
    draw()
    game._render_explosion_burst.assert_called_once_with(48, 64, .1, 16, 212)


def test_cell_sprite_uses_top_left_and_no_fallback(cell_game, monkeypatch):
    # TServerLevel.cpp:1607; TExplosion.cpp:42-45.
    game = cell_game
    sprite = pygame.Surface((4, 4))
    sprite.fill((250, 10, 20))
    monkeypatch.setattr(game.sprite_mgr, 'get_sprite', lambda *args, **kw: sprite)
    game._render_explosion_cell(None, 3, 4, 4, 0, 0)
    assert game.screen.get_at((48, 64))[:3] == (250, 10, 20)
    game._render_explosion_burst.assert_not_called()


def test_legacy_remote_cross_expands_on_render(cell_game):
    # TServerLevel.cpp:1614-1641: legacy cross entries use the same cell order.
    game = cell_game
    game.client.active_explosions = [{'x': 3, 'y': 4, 'radius': 2, 'time': 100,
                                      'tick': game.client.clock.tick}]
    game._render_explosion_cell = Mock()
    game.client.clock.begin_tick()
    game._render_server_explosions()
    assert game._render_explosion_cell.call_count == 9


def test_legacy_bomb_computes_cells_lazily_on_render(cell_game):
    # TServerLevel.cpp:1710-1724: type 2 expands into all five crosses; the
    # burst lasts twelve ticks (TServerLevel.cpp:1606, TExplosion.cpp:101-102).
    game = cell_game
    clock = game.client.clock
    bomb = {'x': 3, 'y': 4, 'time': 97, 'explosion_time': 100,
            'explosion_tick': clock.tick, 'exploded': True, 'power': 2}
    game.active_bombs = [bomb]
    game.bomb_fuse_time = 3
    game.explosion_duration = .6
    game._render_explosion_cell = Mock()
    clock.begin_tick()
    game._advance_bombs()
    game._render_bombs()
    assert len(bomb['cells']) == 53
    assert game._render_explosion_cell.call_count == 53
    for _ in range(10):                 # ticks 2..11 of the burst
        clock.begin_tick()
        game._advance_bombs()
    assert game.active_bombs == [bomb]
    clock.begin_tick()                  # tick 12: gone
    game._advance_bombs()
    assert game.active_bombs == []
