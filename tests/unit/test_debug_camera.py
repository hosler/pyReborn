"""Camera invariants around startup, debug mode, and stitched world views."""

import os
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from pyreborn.game.camera import Camera2D
from pyreborn.game.input import InputMixin
from pyreborn.game.render import RenderMixin
from pyreborn.game.render_world import WorldRenderMixin


def test_camera_transform_is_current_on_first_use_after_setup_sequence():
    camera = Camera2D(1, 1)
    camera.resize(800, 600)
    camera.zoom = 1.5
    camera.set_center(70.0, 40.0)

    assert camera.world_to_screen(70.0, 40.0) == (400.0, 300.0)
    assert camera.scale == 24.0
    assert camera.visible_tile_range() == (53, 27, 87, 53)


class _InputHarness(InputMixin):
    def __init__(self):
        self.debug_mode = False
        self.camera = Camera2D(800, 600)
        self.camera.zoom = 1.75
        self.camera.set_center(80.25, 50.5)


def test_debug_toggle_round_trips_camera_state():
    game = _InputHarness()
    before = (game.camera.center, game.camera.zoom, game.camera.origin)
    event = SimpleNamespace(key=pygame.K_F1)

    game._handle_key_press(event)
    assert game.debug_mode
    assert (game.camera.center, game.camera.zoom, game.camera.origin) == before

    game._handle_key_press(event)
    assert not game.debug_mode
    assert (game.camera.center, game.camera.zoom, game.camera.origin) == before


class _DebugRenderHarness(RenderMixin, WorldRenderMixin):
    def __init__(self):
        pygame.init()
        self.screen = pygame.Surface((800, 600))
        self.camera = Camera2D(800, 600)
        self.camera.zoom = 2.0
        self.camera.set_center(64.0, 32.0)
        self.debug_mode = True
        self.segments = []
        levels = {"left.nw": [1] * 4096, "right.nw": [1] * 4096}
        self.client = SimpleNamespace(
            _current_level_name="left.nw", _tiles_level_name="left.nw",
            levels=levels, tiles=levels["left.nw"],
            gmap_grid={(0, 0): "left.nw", (1, 0): "right.nw"},
        )
        self.world_surface = True
        self._shimmer_step_this_frame = 0
        self._shimmer_draw_this_frame = False

    @property
    def screen_w(self):
        return self.screen.get_width()

    @property
    def screen_h(self):
        return self.screen.get_height()

    def _apply_pending_full_invalidate(self):
        pass

    def _shimmer_ramp_step(self):
        return 0

    def _blit_segment(self, level_name, grid_ox, grid_oy):
        self.segments.append((level_name, grid_ox, grid_oy,
                              self.camera.visible_tile_range()))

    def _render_scene(self):
        self._render_world()


def test_debug_zoom_uses_composition_camera_and_culls_adjacent_segments():
    game = _DebugRenderHarness()
    real_camera = game.camera

    game._render_scene_zoomed(real_camera.zoom)

    assert game.camera is real_camera
    assert [entry[0] for entry in game.segments] == ["left.nw", "right.nw"]
    assert {entry[3] for entry in game.segments} == {
        real_camera.visible_tile_range()
    }


class _DebugOverlayCamera:
    def visible_tile_range(self):
        return (0, 0, 1, 1)

    def world_to_screen(self, x, y):
        return (x * 16, y * 16)


class _DebugOverlayHarness(RenderMixin):
    def __init__(self):
        self.screen = pygame.Surface((16, 16))
        self.camera = _DebugOverlayCamera()
        self.client = SimpleNamespace(player=SimpleNamespace(glove_power=0))
        self.tile_type_calls = []

    @property
    def screen_w(self):
        return self.screen.get_width()

    @property
    def screen_h(self):
        return self.screen.get_height()

    def _get_tile_at(self, x, y):
        return 1

    def _tile_type(self, tile_id):
        self.tile_type_calls.append(tile_id)
        return 22


def test_debug_overlay_uses_collision_tile_type_helper():
    game = _DebugOverlayHarness()

    game._render_debug_overlay()

    assert game.tile_type_calls
