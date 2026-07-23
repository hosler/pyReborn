"""Headless rendering tests for the Q inventory overlay."""

import os
import sys
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

import pygame

from pyreborn.inventory_ui import InventoryUI
from pyreborn.sprites import PLAYER_EQUIPMENT_PREVIEW_RECTS


pygame.init()
pygame.display.set_mode((1, 1))


class _RecordingSpriteManager:
    def __init__(self):
        self.crops = []

    def get_sprite(self, image, x, y, width, height):
        self.crops.append((image, x, y, width, height))
        crop = pygame.Surface((width, height), pygame.SRCALPHA)
        crop.fill((220, 30, 40, 255))
        return crop

    def load_sheet(self, image):
        return None


def _player(**overrides):
    values = dict(
        hearts=3.0, max_hearts=5.0, rupees=12, arrows=4, bombs=7,
        sword_power=2, shield_power=3, glove_power=1,
        sword_image="equipped_sword.png", shield_image="equipped_shield.png",
        head_image="equipped_head.png", body_image="equipped_body.png",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_public_render_crops_each_equipment_sheet_before_scaling():
    screen = pygame.Surface((640, 560), pygame.SRCALPHA)
    manager = _RecordingSpriteManager()
    ui = InventoryUI(screen, manager)
    ui.show()

    ui.render(_player())

    expected_equipment = [
        ("equipped_sword.png", 32, 0, 32, 32),
        ("equipped_shield.png", 0, 0, 19, 20),
        ("equipped_body.png", *PLAYER_EQUIPMENT_PREVIEW_RECTS['body']),
        ("equipped_head.png", *PLAYER_EQUIPMENT_PREVIEW_RECTS['head']),
    ]
    assert manager.crops == expected_equipment
    assert all((crop[3], crop[4]) != (128, 704) for crop in manager.crops)


def test_power_convention_resolves_missing_sword_and_shield_names():
    screen = pygame.Surface((640, 560), pygame.SRCALPHA)
    manager = _RecordingSpriteManager()
    ui = InventoryUI(screen, manager)
    ui.show()

    ui.render(_player(sword_image="", shield_image=""))

    assert manager.crops[0][0] == "sword2.png"
    assert manager.crops[1][0] == "shield3.png"


def test_panel_background_and_footer_are_inside_overlay():
    screen = pygame.Surface((640, 560), pygame.SRCALPHA)
    ui = InventoryUI(screen)
    ui.show()
    ui.render(_player())

    # Translucent plate (exact color/alpha now comes from pyreborn.game.theme).
    assert 0 < ui.BG_COLOR[3] < 255
    footer_y = ui.ui_height - ui.PADDING - ui.font_small.get_height()
    footer_band = pygame.Rect(0, footer_y, ui.ui_width, ui.font_small.get_height())
    assert ui.overlay.subsurface(footer_band).get_bounding_rect().width > 0
    # Nothing is drawn by the inventory below its now-extended panel.
    assert screen.get_at((ui.ui_x + ui.ui_width // 2,
                          ui.ui_y + ui.ui_height + 1))[3] == 0


def test_granted_name_only_weapon_is_visible_and_system_weapon_is_hidden():
    screen = pygame.Surface((640, 560), pygame.SRCALPHA)
    ui = InventoryUI(screen)
    ui.show()
    weapons = {
        "Beer": {"name": "Beer", "image": ""},
        "-validation": {"name": "-validation", "image": ""},
    }

    ui.render(_player(), weapons)

    assert [name for name, _ in ui._visible_weapon_entries(weapons)] == ["Beer"]
    assert any(key[1] == "Beer" for key in ui._text_cache)
    assert not any("validation" in key[1] for key in ui._text_cache)


def test_grid_population_preserves_live_acquisition_order_and_hides_system_weapons():
    ui = InventoryUI(pygame.Surface((640, 560), pygame.SRCALPHA))
    weapons = {
        "Bow": {"image": "wbow1.png"},
        "-arenaSYS": {"image": ""},
        "Bomb": {"image": "wbomb.png"},
    }

    assert [name for name, _ in ui._visible_weapon_entries(weapons)] == ["Bow", "Bomb"]


def test_selector_moves_by_grid_and_stops_at_partial_row_bounds():
    ui = InventoryUI(pygame.Surface((640, 560), pygame.SRCALPHA))
    weapons = {f"Weapon {i}": {} for i in range(7)}

    assert ui.move_selector(1, 0, weapons) == 1
    assert ui.move_selector(0, 1, weapons) == 6
    assert ui.move_selector(1, 0, weapons) == 6
    assert ui.move_selector(0, 1, weapons) == 6
    assert ui.move_selector(-1, 0, weapons) == 5
    assert ui.move_selector(0, -1, weapons) == 0


def test_enter_equips_cursor_for_the_d_key_weapon_lookup():
    ui = InventoryUI(pygame.Surface((640, 560), pygame.SRCALPHA))
    weapons = {"Bow": {}, "Bomb": {}}
    ui.cursor_weapon_idx = 1

    assert ui.handle_key(pygame.K_RETURN, weapons)
    assert ui.selected_weapon_idx == 1
    # ActionsMixin._use_weapon calls this exact lookup for D.
    assert ui.get_selected_weapon(weapons) == "Bomb"


def test_imageless_weapon_renders_initials_letter_tile():
    screen = pygame.Surface((640, 560), pygame.SRCALPHA)
    ui = InventoryUI(screen, _RecordingSpriteManager())
    ui.show()
    ui.render(_player(), {"Magic Wand": {"image": ""}})

    assert any(key[1] == "MA" for key in ui._text_cache)
