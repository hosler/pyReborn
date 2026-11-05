import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from types import SimpleNamespace

import pygame

from pyreborn.game.render_effects import EffectsRenderMixin
from pyreborn.game.constants import BOMB_FUSE_TIME, EXPLOSION_DURATION
from pyreborn.tiletypes import TileType


class _Camera:
    def world_to_screen(self, x, y):
        return x * 16, y * 16


class _Sound:
    def __init__(self):
        self.played = []

    def play(self, name):
        self.played.append(name)


class _Harness(EffectsRenderMixin):
    def __init__(self):
        pygame.init()
        self.screen = pygame.Surface((320, 240))
        self.camera = _Camera()
        self.sound_mgr = _Sound()
        self.active_bombs = []
        self.active_projectiles = []
        self.break_effects = []
        self.bomb_fuse_time = BOMB_FUSE_TIME
        self.explosion_duration = EXPLOSION_DURATION
        self.world_surface = object()
        self.board = {}
        self.sent = {}                # tiles the blast pushed over the wire
        self.client = SimpleNamespace(
            player=SimpleNamespace(x=4.0, y=5.0),
            get_current_level_from_position=lambda: "test.nw",
            modify_board=self._modify_board,
            _cut_bushes_at_explosion=lambda x, y: set(),
        )

    def _get_tile_at(self, x, y):
        return self.board.get((int(x), int(y)), 0)

    def _tile_type(self, tile_id):
        return 0

    def _is_tile_blocking(self, tile_id):
        return tile_id == 99

    def _level_tiles_at(self, x, y):
        return "test.nw", []        # non-empty level name; sends go to the wire

    def _modify_board(self, x, y, w, h, tiles):
        self.sent[(x, y)] = tiles[0]
        self.board[(x, y)] = tiles[0]
        return True

    def _spawn_hit_break_effect(self, x, y):
        self.break_effects.append((x, y))

    def _render_projectile_marker(self, *args):
        pass


def test_remote_bomb_uses_wire_fuse():
    h = _Harness()
    bomb = h._add_remote_bomb(
        {'x': 4.0, 'y': 5.0, 'power': 2, 'timer_ms': 750}, now=10.0)
    assert bomb['time'] == 10.0
    assert bomb['fuse_time'] == 0.75


def test_removal_detonates_now_and_dedupes():
    h = _Harness()
    bomb = h._add_remote_bomb(
        {'x': 4.0, 'y': 5.0, 'power': 2, 'timer_ms': 3000}, now=10.0)
    h._detonate_bomb_at(4.0, 5.0, now=10.2)
    h._detonate_bomb_at(4.0, 5.0, now=10.3)
    assert bomb['exploded'] is True
    assert bomb['explosion_time'] == 10.2
    assert h.sound_mgr.played == ['explode.wav']
    assert len(h.active_bombs) == 1
    assert h._camera_shake_started > 0


def test_distant_explosion_does_not_shake():
    h = _Harness()
    assert h._start_camera_shake(20.0, 20.0, now=3.0) is False
    assert not hasattr(h, '_camera_shake_started')


def test_active_camera_shake_is_not_restarted():
    h = _Harness()
    assert h._start_camera_shake(4.0, 5.0, now=3.0) is True
    assert h._start_camera_shake(4.0, 5.0, now=3.2) is True
    assert h._camera_shake_started == 3.0


def test_arrow_stops_at_wall_then_spark_expires(monkeypatch):
    h = _Harness()
    h.board[(2, 1)] = 99
    h.active_projectiles.append({
        'x': 1.0, 'y': 1.0, 'dx': 8.0, 'dy': 0.0, 'time': 5.0,
        'direction': 3, 'gani': 'arrow', 'max_distance': 10.0,
        'start_x': 1.0, 'start_y': 1.0,
    })
    monkeypatch.setattr('pyreborn.game.render_effects.time.time', lambda: 5.0)
    h._update_and_render_projectiles(0.2)
    assert h.active_projectiles[0]['x'] >= 2.0
    assert h.active_projectiles[0]['hit_time'] == 5.0

    monkeypatch.setattr('pyreborn.game.render_effects.time.time', lambda: 5.13)
    h._update_and_render_projectiles(0.2)
    assert h.active_projectiles == []


def test_blast_uses_client_explosion_probes():
    """Bombs and script bursts share the headless client's bounded matcher."""
    h = _Harness()
    calls = []
    def cut(x, y):
        calls.append((x, y))
        return {(11, 10)}
    h.client._cut_bushes_at_explosion = cut
    assert h._break_bushes_in_blast(10.0, 10.0, power=3) == {(11, 10)}
    assert calls == [(10.0, 10.0)]


def test_server_explosion_lasts_twelve_ticks(monkeypatch):
    h = _Harness()
    explosion = {'x': 4.0, 'y': 5.0, 'time': 0.0}
    h.client.active_explosions = [explosion]
    draws = []
    h._render_world_object = lambda *args: draws.append(args)
    monkeypatch.setattr('pyreborn.game.render_effects.time.time', lambda: 0.55)
    h._render_server_explosions()
    assert h.client.active_explosions == [explosion]
    assert len(draws) == 1
    monkeypatch.setattr('pyreborn.game.render_effects.time.time', lambda: EXPLOSION_DURATION)
    h._render_server_explosions()
    assert h.client.active_explosions == []
    assert len(draws) == 1
