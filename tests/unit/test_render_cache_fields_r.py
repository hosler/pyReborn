"""RenderCache group R (render.py): per-field invalidation.

``test_render_cache_derived.py`` proves dropping the cache changes no pixel.
These prove the other half: each cache is keyed, and a change in its key is
followed by the new content, never the stale entry.

Mutation check for each test (apply, see the named assertion fail, revert by
the inverse edit):

* zoom scene: in ``_render_scene_zoomed`` change
  ``cache_key = (sw, sh, self.camera.tile_size)`` to ``cache_key = (0,)``;
  ``test_zoom_scene_follows_zoom_and_resize`` fails its
  ``zoom_scene_surface.get_size()`` assertion after the zoom change.
* GUI camera: in ``_render_gui_band`` change
  ``key = (self.screen_w, self.screen_h, cam.tile_size)`` to ``key = (0,)``;
  ``test_gui_camera_follows_resize`` fails its ``seen[-1]`` size assertion.
* camera bounds: in ``_sync_camera`` change the ``bounds_key`` tuple to
  ``(self.client.current_level_name,)``;
  ``test_camera_bounds_follow_gmap_switch`` fails its ``_bounds`` assertion
  on the switch to a GMAP.
"""

import math
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from pyreborn.game.render_cache import RenderCache
from pyreborn.game.render import LEVEL_SIZE, gmap_extent


def _resize(game, size):
    game.viewport.handle_resize(*size)
    game.frames(1, events=[pygame.event.Event(
        pygame.VIDEORESIZE, size=size, w=size[0], h=size[1])])


def _digest(game):
    return (game.screen.get_size(), pygame.image.tobytes(game.screen, "RGB"))


def _fresh_digest(game):
    """The frame the game draws next when no cache entry exists."""
    game.render_cache = RenderCache()
    game.frames(1)
    return _digest(game)


def test_zoom_scene_follows_zoom_and_resize(make_game):
    game = make_game()
    game.camera.zoom = 2.0
    game.frames(2)
    cache = game.render_cache
    w, h = game.screen_w, game.screen_h
    assert cache.zoom_scene_surface.get_size() == (math.ceil(w / 2.0),
                                                   math.ceil(h / 2.0))
    first = cache.zoom_scene_surface

    game.camera.zoom = 4.0
    game.frames(2)
    assert cache.zoom_scene_surface.get_size() == (math.ceil(w / 4.0),
                                                   math.ceil(h / 4.0))
    assert cache.zoom_scene_surface is not first
    assert cache.zoom_scene_cam.screen_w == math.ceil(w / 4.0)
    live = _digest(game)
    assert live == _fresh_digest(game)

    _resize(game, (900, 700))
    game.frames(1)
    assert (game.screen_w, game.screen_h) != (w, h)
    cache = game.render_cache  # _fresh_digest swapped in a new one
    assert cache.zoom_scene_surface.get_size() == (
        math.ceil(game.screen_w / 4.0), math.ceil(game.screen_h / 4.0))
    assert _digest(game) == _fresh_digest(game)
    assert game.frame_errors == {}


def test_gui_camera_follows_resize(make_game):
    game = make_game()
    seen = []
    game._render_gui_layers = lambda: seen.append(
        (game.camera.screen_w, game.camera.screen_h))
    game.camera.zoom = 2.0
    game.frames(2)
    assert seen[-1] == (game.screen_w, game.screen_h)
    first = game.render_cache.gui_cam
    first.screen_size = (first.screen_w, first.screen_h)

    _resize(game, (900, 700))
    game.frames(1)
    assert (game.screen_w, game.screen_h) != first.screen_size
    assert seen[-1] == (game.screen_w, game.screen_h)
    assert game.render_cache.gui_cam is not first
    # The real camera is restored after the GUI band draws.
    assert game.camera is not game.render_cache.gui_cam
    assert game.frame_errors == {}


def test_camera_bounds_follow_gmap_switch(make_game):
    game = make_game()
    game.frames(2)
    assert game.camera._bounds == (0, 0, LEVEL_SIZE, LEVEL_SIZE)
    key = game.render_cache.camera_bounds_key
    assert key is not None

    # Same level name, only the GMAP size changes: the key alone must notice.
    game.client.gmap_width = game.client.gmap_height = 3
    game.client.gmap_grid[(0, 0)] = game.client.current_level_name
    assert game.client.in_gmap_segment
    game.frames(1)
    assert game.camera._bounds == (0, 0, *gmap_extent(3, 3))
    assert game.render_cache.camera_bounds_key != key

    game.client.gmap_width = game.client.gmap_height = 0
    game.client.gmap_grid.clear()
    game.frames(1)
    assert game.camera._bounds == (0, 0, LEVEL_SIZE, LEVEL_SIZE)
