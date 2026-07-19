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

    expected = [
        ("equipped_sword.png", *PLAYER_EQUIPMENT_PREVIEW_RECTS['sword']),
        ("equipped_shield.png", *PLAYER_EQUIPMENT_PREVIEW_RECTS['shield']),
        ("equipped_head.png", *PLAYER_EQUIPMENT_PREVIEW_RECTS['head']),
        ("equipped_body.png", *PLAYER_EQUIPMENT_PREVIEW_RECTS['body']),
    ]
    assert manager.crops == expected
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

    assert ui.BG_COLOR[3] == 220
    footer_y = ui.ui_height - ui.PADDING - ui.font_small.get_height()
    footer_band = pygame.Rect(0, footer_y, ui.ui_width, ui.font_small.get_height())
    assert ui.overlay.subsurface(footer_band).get_bounding_rect().width > 0
    # Nothing is drawn by the inventory below its now-extended panel.
    assert screen.get_at((ui.ui_x + ui.ui_width // 2,
                          ui.ui_y + ui.ui_height + 1))[3] == 0
