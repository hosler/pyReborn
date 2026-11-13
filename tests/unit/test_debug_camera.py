"""Camera invariants around startup, debug mode, and stitched world views."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from offline_game import GMAP_SEGMENTS, key_event, spy
from pyreborn.game.camera import Camera2D


def test_camera_transform_is_current_on_first_use_after_setup_sequence():
    camera = Camera2D(1, 1)
    camera.resize(800, 600)
    camera.zoom = 1.5
    camera.set_center(70.0, 40.0)

    assert camera.world_to_screen(70.0, 40.0) == (400.0, 300.0)
    assert camera.scale == 24.0
    assert camera.visible_tile_range() == (53, 27, 87, 53)


def test_debug_toggle_round_trips_camera_state(make_game):
    game = make_game()
    game.camera.zoom = 1.75
    game.camera.set_center(80.25, 50.5)
    before = (game.camera.center, game.camera.zoom, game.camera.origin)
    event = key_event(pygame.K_F1)
    assert not game.debug_mode

    game._handle_key_press(event)
    assert game.debug_mode
    assert (game.camera.center, game.camera.zoom, game.camera.origin) == before

    game._handle_key_press(event)
    assert not game.debug_mode
    assert (game.camera.center, game.camera.zoom, game.camera.origin) == before


def test_debug_zoom_uses_composition_camera_and_culls_adjacent_segments(
        make_game, monkeypatch):
    game = make_game(gmap=True, gmap_segment=(0, 0))
    game.camera.zoom = 2.0
    game.camera.set_center(64.0, 32.0)
    game.debug_mode = True
    segments = []
    real_blit = game._blit_segment

    def blit_segment(level_name, grid_ox, grid_oy):
        segments.append((level_name, grid_ox, grid_oy,
                         game.camera.visible_tile_range()))
        return real_blit(level_name, grid_ox, grid_oy)
    monkeypatch.setattr(game, "_blit_segment", blit_segment)
    real_camera = game.camera

    game._render_scene_zoomed(real_camera.zoom)

    assert game.camera is real_camera
    assert [entry[0] for entry in segments] == list(GMAP_SEGMENTS[:2])
    assert {entry[3] for entry in segments} == {
        real_camera.visible_tile_range()
    }


def test_debug_overlay_uses_collision_tile_type_helper(make_game, monkeypatch):
    game = make_game()
    game.debug_mode = True
    calls = spy(monkeypatch, game, "_tile_type")

    game._render_debug_overlay()

    assert calls
