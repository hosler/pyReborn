"""Headless checks for the equipped-weapon slot and modal map helpers."""

import os
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

from offline_game import key_event, spy
from pyreborn.game.minimap import aspect_fit, map_entity_positions
from pyreborn.inventory_ui import HeartDisplay, resolve_weapon_indicator


pygame.init()
pygame.display.set_mode((1, 1))


class _Sheets:
    def __init__(self):
        self.loaded = []

    def load_sheet(self, image):
        self.loaded.append(image)
        return pygame.Surface((24, 12)) if image == "bow.png" else None


def test_weapon_indicator_uses_filtered_equipped_entry_and_shared_image_loader():
    sheets = _Sheets()
    weapons = {
        "-internal": {"image": "hidden.png"},
        "Bomb": {"image": ""},
        "Bow": {"image": "bow.png"},
    }

    name, image, surface = resolve_weapon_indicator(weapons, 1, sheets)

    assert (name, image) == ("Bow", "bow.png")
    assert surface.get_size() == (24, 12)
    assert sheets.loaded == ["bow.png"]


def test_weapon_indicator_falls_back_to_name_when_image_is_unavailable():
    name, image, surface = resolve_weapon_indicator(
        {"Lantern": {"image": "missing.png"}}, 0, _Sheets())
    assert (name, image, surface) == ("Lantern", "missing.png", None)


def test_map_aspect_fit_never_stretches():
    assert aspect_fit((400, 200), (600, 600)) == (600, 300)
    assert aspect_fit((200, 400), (600, 300)) == (150, 300)


def test_hearts_wrap_after_ten_and_half_heart_fills_left_side_only():
    target = pygame.Surface((300, 100), pygame.SRCALPHA)
    hearts = HeartDisplay(0, 0)
    hearts.render(target, 10.5, 12)

    assert hearts._cache.get_height() == 36
    second_row_y = HeartDisplay.HEART_SIZE + HeartDisplay.HEART_SPACING
    half = hearts._cache.subsurface((0, second_row_y, 16, 16))
    assert half.get_at((3, 5)) != half.get_at((13, 5))


def test_world_entity_dots_use_each_players_segment():
    client = SimpleNamespace(
        x=96, y=32, gmap_width=3, gmap_height=2,
        current_level_name="middle",
        gmap_grid={(0, 0): "left", (1, 0): "middle", (2, 0): "right"},
        players={7: {"x": 32, "y": 16, "level": "right"}},
    )
    dots = list(map_entity_positions(client))
    assert dots[0][:2] == (0.5, 0.25)
    assert dots[1][:2] == (160 / 192, 16 / 128)
    assert dots[1][2] == (255, 255, 255)


@pytest.mark.parametrize("close_key", [pygame.K_m, pygame.K_ESCAPE])
def test_open_map_dispatch_swallows_keys_and_m_or_escape_close(make_game, monkeypatch, close_key):
    game = make_game()
    game.frames(1)
    game.big_map_visible = True
    pressed = spy(monkeypatch, game, "_handle_key_press")

    game.frames(1, events=[key_event(pygame.K_a, "a"), key_event(close_key)])

    assert game.big_map_visible is False
    assert pressed == []
    assert game._gs1_keypress_queue == []
