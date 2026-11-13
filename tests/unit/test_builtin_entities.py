import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pytest

from offline_game import spy
from pyreborn import Client
from pyreborn.tiletypes import is_blocking

WALL = next(tile for tile in range(4096) if is_blocking(tile))


@pytest.fixture
def harness(make_game, monkeypatch):
    """A real offline game on an open board with the player at (4, 5);
    ``harness.sounds`` records the sound manager's ``play`` calls (the real
    one still runs)."""
    game = make_game(tiles=lambda tx, ty: 0)
    game.client.player.x, game.client.player.y = 4.0, 5.0
    game.active_bombs = []
    game.active_projectiles = []
    game.break_effects = []
    game.sound_calls = spy(monkeypatch, game.sound_mgr, 'play')
    return game


def test_remote_bomb_uses_wire_fuse(harness):
    h = harness
    bomb = h._add_remote_bomb(
        {'x': 4.0, 'y': 5.0, 'power': 2, 'timer_ms': 750}, now=10.0)
    assert bomb['time'] == 10.0
    assert bomb['fuse_time'] == 0.75


def test_removal_detonates_now_and_dedupes(harness):
    h = harness
    bomb = h._add_remote_bomb(
        {'x': 4.0, 'y': 5.0, 'power': 2, 'timer_ms': 3000}, now=10.0)
    h._detonate_bomb_at(4.0, 5.0, now=10.2)
    h._detonate_bomb_at(4.0, 5.0, now=10.3)
    assert bomb['exploded'] is True
    assert bomb['explosion_time'] == 10.2
    assert h.sound_calls == [(('bomb.wav',), {})]  # TServerLevel.cpp:1697
    assert len(h.active_bombs) == 1
    assert h._camera_shake_started > 0


def test_distant_explosion_does_not_shake(harness):
    h = harness
    assert h._start_camera_shake(20.0, 20.0, now=3.0) is False
    assert not hasattr(h, '_camera_shake_started')


def test_active_camera_shake_is_not_restarted(harness):
    h = harness
    assert h._start_camera_shake(4.0, 5.0, now=3.0) is True
    assert h._start_camera_shake(4.0, 5.0, now=3.2) is True
    assert h._camera_shake_started == 3.0


def test_arrow_stops_at_wall_then_spark_expires(harness, sim_time):
    h = harness
    h.client.tiles[1 * 64 + 2] = WALL
    h.active_projectiles.append({
        'x': 1.0, 'y': 1.0, 'dx': 8.0, 'dy': 0.0, 'time': 5.0,
        'direction': 3, 'gani': 'arrow', 'max_distance': 10.0,
        'start_x': 1.0, 'start_y': 1.0,
    })
    sim_time(5.0)
    h._update_and_render_projectiles(0.2)
    assert h.active_projectiles[0]['x'] >= 2.0
    assert h.active_projectiles[0]['hit_time'] == 5.0

    sim_time(5.13)
    h._update_and_render_projectiles(0.2)
    assert h.active_projectiles == []


def test_blast_uses_client_explosion_probes(harness, monkeypatch):
    """Bombs and script bursts share the headless client's bounded matcher."""
    h = harness
    calls = []

    def cut(x, y):
        calls.append((x, y))
        return {(11, 10)}
    monkeypatch.setattr(h.client, 'blast_board_at', cut)
    assert h._break_bushes_in_blast(10.0, 10.0, power=3) == {(11, 10)}
    assert calls == [(10.0, 10.0)]


def test_server_explosion_lasts_twelve_ticks(harness, monkeypatch):
    # TServerLevel.cpp:1606, TExplosion.cpp:101-102: counter 11..0 is drawn,
    # twelve ticks; the Client drops the cell on the twelfth tick after.
    h = harness
    clock = h.client.clock
    explosion = {'x': 4.0, 'y': 5.0, 'sprite_row': 4, 'time': 0.0,
                 'tick': clock.tick}
    h.client.active_explosions = [explosion]
    draws = []
    monkeypatch.setattr(h, '_render_world_object',
                        lambda *args, **kwargs: draws.append((args, kwargs)))
    for _ in range(11):
        clock.begin_tick()
        Client._expire_explosions(h.client)
    h._render_server_explosions()
    assert h.client.active_explosions == [explosion]
    assert len(draws) == 1
    clock.begin_tick()
    Client._expire_explosions(h.client)
    h._render_server_explosions()
    assert h.client.active_explosions == []
    assert len(draws) == 1
