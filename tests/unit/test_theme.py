"""Headless checks for the shared UI theme (pyreborn/game/theme.py)."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from pyreborn.game import theme


pygame.init()
pygame.display.set_mode((1, 1))


def test_palette_entries_are_rgb_tuples():
    for name in ("NIGHT", "SURFACE", "FOREST", "MOSS", "EMERALD", "MINT",
                 "TEXT", "TEXT_DIM", "TEXT_FAINT", "ERROR", "WARN", "INFO"):
        color = getattr(theme, name)
        assert len(color) == 3
        assert all(0 <= c <= 255 for c in color)


def test_plate_rgba_appends_alpha():
    assert theme.plate_rgba(90) == (*theme.PLATE, 90)


def test_emblem_loads_keys_out_navy_field_and_scales_integer():
    logo = theme.emblem(1)
    assert logo is not None
    # The baked-in navy field must be keyed out so the mandala can sit on any
    # panel: every corner of the cropped art is fully transparent...
    w, h = logo.get_size()
    assert logo.get_at((0, 0)).a == 0
    # ...while the leaf art itself is opaque green.
    center = logo.get_at((w // 2, h // 2))
    assert center.a == 255
    assert center.g > center.r and center.g > center.b

    doubled = theme.emblem(2)
    assert doubled.get_size() == (w * 2, h * 2)


def test_emblem_alpha_variant_does_not_mutate_cache():
    faded = theme.emblem(1, alpha=40)
    assert faded.get_alpha() == 40
    assert theme.emblem(1).get_alpha() in (None, 255)


def test_draw_panel_paints_bg_and_border_inside_rect():
    surf = pygame.Surface((60, 40))
    surf.fill((0, 0, 0))
    theme.draw_panel(surf, pygame.Rect(10, 5, 40, 30))
    # border pixel (edge midpoint) picks up the overlay border green
    edge = surf.get_at((30, 5))
    assert edge.g > edge.r
    # interior gets the translucent navy fill (no longer pure black)
    inside = surf.get_at((30, 20))
    assert (inside.r, inside.g, inside.b) != (0, 0, 0)


def test_focus_glow_is_cached_per_size():
    surf = pygame.Surface((100, 50), pygame.SRCALPHA)
    rect = pygame.Rect(20, 10, 60, 30)
    theme.focus_glow(surf, rect)
    theme.focus_glow(surf, rect)
    key = (rect.size, theme.MINT, 6, 3)
    assert key in theme._GLOW_CACHE
