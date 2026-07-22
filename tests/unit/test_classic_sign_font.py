"""Headless checks for the classic sign/dialogue font."""
import os
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from pyreborn.game import assets
from pyreborn.game.assets import FontManager
from pyreborn.game.hud import HUD
from pyreborn.game.render_objects import LevelObjectsRenderMixin


def setup_module():
    pygame.init()


def test_classic_font_loads_from_assets_path():
    fonts = FontManager()
    font = fonts.classic()

    assert assets.CLASSIC_FONT_PATH.is_file()
    assert font is fonts.classic()
    assert font.render("Classic sign", True, "black").get_width() > 0


def test_classic_font_falls_back_when_asset_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(assets, "CLASSIC_FONT_PATH", tmp_path / "missing.ttf")
    fonts = FontManager()

    font = fonts.classic()

    assert font is fonts.at(assets.CLASSIC_FONT_SIZE)
    assert font is fonts.classic()
    assert font.render("fallback", True, "black").get_width() > 0


def test_sign_popup_render_smoke_with_classic_font():
    game = SimpleNamespace(
        screen=pygame.Surface((640, 480)), screen_w=640, screen_h=480,
        fonts=FontManager(),
    )
    game.hud = HUD.__new__(HUD)
    game.hud.game = game
    game._render_sign_popup = LevelObjectsRenderMixin._render_sign_popup.__get__(game)

    game._render_sign_popup("Chunky sign lettering\nfits inside the popup")

    assert game.screen.get_bounding_rect().width > 0
