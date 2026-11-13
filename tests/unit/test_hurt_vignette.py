"""The hurt vignette is painted at whatever size the window has.

``_render_combat_presentation`` caches the vignette surface per screen size.
Readiness must follow that surface: a window resize builds a new surface, and
it must come out painted, not blank.
"""

import pygame

from offline_game import _frame


def _hit(game):
    """Take a hit, then draw one frame inside the flash."""
    assert game.client.respond_to_hurt(0.5)
    game.client.on_hurt(99, 0.5, 0, 0, 0)
    game.frames(1)


def _edge_pixels(game):
    """The corner pixels, where the vignette is strongest."""
    frame = _frame(game)
    w, h = frame.get_size()
    return [tuple(frame.get_at(p))[:3]
            for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]


def _vignette_shows(game, before):
    """Every corner is redder after the hit than in ``before``."""
    return all(a[0] > b[0] and a[1] <= b[1] + 1
               for a, b in zip(_edge_pixels(game), before))


def test_vignette_is_painted_before_and_after_a_resize(make_game, sim_time):
    # Mutation: restore the once-only flag (paint only while
    # render_cache.hurt_vignette_ready is False, set True after the first
    # paint, never reset on a new surface) -> fails "after resize".
    now = [100.0]
    sim_time(lambda: now[0])
    game = make_game()
    game.frames(2)
    before = _edge_pixels(game)
    _hit(game)
    assert _vignette_shows(game, before), "at the original size"

    size = (900, 700)
    game.viewport.handle_resize(*size)
    game.frames(1, events=[pygame.event.Event(
        pygame.VIDEORESIZE, size=size, w=size[0], h=size[1])])
    # Let the first flash expire, then take a second hit at the new size.
    now[0] += 10.0
    game.frames(60)
    assert game.screen.get_size() == size
    before = _edge_pixels(game)
    _hit(game)
    assert _vignette_shows(game, before), "after resize"
