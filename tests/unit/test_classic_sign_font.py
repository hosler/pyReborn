"""Headless checks for the classic sign/dialogue font."""
import os
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from pyreborn.game import assets
from pyreborn.game.actions import ActionsMixin
from pyreborn.game.assets import FontManager
from pyreborn.game.dialogue import DialoguePager
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
        fonts=FontManager(), sprite_mgr=None,
    )
    game.hud = HUD.__new__(HUD)
    game.hud.game = game
    game._render_sign_popup = LevelObjectsRenderMixin._render_sign_popup.__get__(game)

    game._render_sign_popup("Chunky sign lettering\nfits inside the popup")

    assert game.screen.get_bounding_rect().width > 0


class _DialogueFont:
    def __init__(self):
        self.rendered = []

    def get_linesize(self):
        return 10

    def size(self, text):
        return len(text) * 4, 10

    def render(self, text, antialias, color):
        self.rendered.append(text)
        surface = pygame.Surface(self.size(text), pygame.SRCALPHA)
        surface.fill(color)
        return surface


def test_classic_dialogue_inline_image_render_smoke():
    font = _DialogueFont()
    full = pygame.Surface((12, 50), pygame.SRCALPHA)
    full.fill((255, 0, 0))
    part = pygame.Surface((7, 20), pygame.SRCALPHA)
    part.fill((0, 255, 0))
    loads = []

    def load_sheet(name):
        loads.append(name)
        return full if name == "full.png" else None

    def get_sprite(name, *rect):
        loads.append((name, rect))
        return part if name == "part.png" else None

    game = SimpleNamespace(
        screen_w=640, screen_h=480, fonts=SimpleNamespace(classic=lambda: font),
        font_small=font, dialogue_pager=DialoguePager(),
        sprite_mgr=SimpleNamespace(load_sheet=load_sheet, get_sprite=get_sprite),
    )
    ActionsMixin._show_dialogue(
        game, "A#i(full.png)B#i(part.png,1,2,9,20)C#i(missing.png)D\nnext",
        classic_font=True)
    hud = HUD.__new__(HUD)
    hud.game = game
    screen = pygame.Surface((640, 480), pygame.SRCALPHA)

    hud._draw_dialogue(screen)

    assert font.rendered == ["A", "B", "C", "D", "next"]
    assert screen.get_at((134, 340))[:3] == (255, 0, 0)
    assert screen.get_at((134, 389))[:3] == (255, 0, 0)
    assert screen.get_at((150, 340))[:3] == (0, 255, 0)
    assert screen.get_at((158, 340)) != screen.get_at((159, 340))
    assert screen.get_at((159, 340)) == screen.get_at((163, 340))
    assert screen.get_at((130, 390)) == screen.get_at((130, 340))
    assert screen.get_at((120, 409)).a > 0
    assert screen.get_at((120, 410)).a == 0
    assert ("part.png", (1, 2, 9, 20)) in loads
    assert "full.png" in loads and "missing.png" in loads


def test_nonclassic_dialogue_keeps_image_syntax_as_text():
    font = _DialogueFont()
    game = SimpleNamespace(screen_w=640, screen_h=480, font_small=font,
                           dialogue_pager=DialoguePager(), sprite_mgr=None)
    ActionsMixin._show_dialogue(game, "plain #i(icon.png)")
    hud = HUD.__new__(HUD)
    hud.game = game

    hud._draw_dialogue(pygame.Surface((640, 480), pygame.SRCALPHA))

    assert game.dialogue_text == "plain #i(icon.png)"
    assert font.rendered == ["plain #i(icon.png)"]


def test_missing_sign_image_is_requested_and_rewraps_on_arrival():
    font = _DialogueFont()
    sheets = {}
    requested = []
    game = SimpleNamespace(
        screen_w=640, screen_h=480, fonts=SimpleNamespace(classic=lambda: font),
        font_small=font, dialogue_pager=DialoguePager(page_size=1),
        sprite_mgr=SimpleNamespace(load_sheet=sheets.get,
                                   get_sprite=lambda *a: None),
        _request_asset=requested.append,
    )
    game._show_dialogue = lambda text, classic_font=False: \
        ActionsMixin._show_dialogue(game, text, classic_font)
    # 90 + 90 chars of text at 4 px = 360 px per word pair: fits the 360 px
    # box only while the image still measures 0 px.
    game._show_dialogue("a" * 45 + "#i(late.png)" + "b" * 45, classic_font=True)
    assert requested == ["late.png"]
    assert len(game.dialogue_pager.lines) == 1

    sheets["late.png"] = pygame.Surface((40, 10))
    ActionsMixin._rewrap_sign_dialogue(game, "other.png")
    assert len(game.dialogue_pager.lines) == 1
    ActionsMixin._rewrap_sign_dialogue(game, "late.png")
    assert len(game.dialogue_pager.lines) == 2
    assert isinstance(game.dialogue_text, str) and game.dialogue_text.images
