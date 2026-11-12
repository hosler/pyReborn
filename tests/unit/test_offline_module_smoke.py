"""Smoke coverage for the pygame modules the render tests reach least:
pygame_screens, game/minimap, game/render_text, game/render_layers,
game/viewport, game/ui, game/editor/{palette,overlay} and gs2_gui/skins.

Everything runs in SDL dummy mode with the real fonts. The game-bound ones go
through the make_game fixture (tests/offline_game.py)."""

import pygame
import pytest
from pygame.locals import (
    K_BACKSPACE, K_DOWN, K_ESCAPE, K_RETURN, K_TAB, K_UP)

from offline_game import (
    GANI_NPC, NAMED_NPC, frame_differs, key_event, surface_is_flat)
from pyreborn import pygame_screens
from pyreborn.game import minimap, theme, ui
from pyreborn.game.assets import FontManager
from pyreborn.game.editor.palette import (
    MAX_TILE_ID, SHEET_COLS, SHEET_ROWS, TilePalette, tile_id_at)
from pyreborn.game.gs2_gui.skins import _Skin, _split_bitmap_array
from pyreborn.game.viewport import Viewport
from pyreborn.listserver import ServerEntry
from pyreborn.packets import PacketID
from pyreborn.prefs import Prefs


def _servers(n):
    return [ServerEntry(name="Server %d" % i, type_prefix=("P ", "H ", "3 ",
                                                           "U ", "")[i % 5],
                        language="English", description="d" * (i * 7),
                        url="", version="6.037", player_count=i,
                        ip="10.0.0.%d" % (i + 1), port=14900 + i)
            for i in range(n)]


@pytest.fixture(autouse=True)
def _private_prefs(monkeypatch, tmp_path):
    """The screens write the window size to prefs on the way out; keep that
    out of the session-wide prefs that later GameClients read."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))


def _post(*events):
    pygame.event.clear()
    for ev in events:
        pygame.event.post(ev)


# -- pygame_screens ----------------------------------------------------------

def test_login_screen_submits_typed_credentials():
    screen = pygame_screens.LoginScreen(
        prefs=Prefs.load(), fields={"username": "", "password": ""})
    _post(*[key_event(ord(c), c) for c in "abc"], key_event(K_TAB),
          *[key_event(ord(c), c) for c in "pw"], key_event(K_RETURN))
    result = screen.run()
    assert result is not None
    assert result["username"] == "abc" and result["password"] == "pw"


def test_login_screen_requires_both_fields_and_escape_cancels():
    screen = pygame_screens.LoginScreen(prefs=Prefs.load(),
                                        fields={"username": "", "password": ""})
    _post(key_event(K_RETURN), key_event(K_ESCAPE))
    assert screen.run() is None
    assert "required" in screen.error.text


def test_login_screen_mode_toggle_and_resize_and_reopen_with_error():
    screen = pygame_screens.LoginScreen(
        prefs=Prefs.load(), error="Bad password",
        fields={"username": "u", "password": "p", "host": "h", "port": 15000,
                "use_listserver": False, "listserver_host": "ls"})
    screen.build()
    assert screen.host_in.visible and not screen.ls_in.visible
    screen._toggle_mode()
    assert screen.ls_in.visible and not screen.host_in.visible
    for size in ((800, 600), (1600, 900), (640, 480)):
        screen.viewport.handle_resize(*size)
        screen.ui.update((10, 10))
        screen.canvas.fill(pygame_screens.BG)
        screen.ui.draw(screen.canvas)
        screen.viewport.present()
    assert drew_canvas(screen.canvas)
    screen._submit()
    assert screen._done and screen._result["host"] == "h"
    assert screen._result["port"] == 15000


def drew_canvas(surface):
    return not surface_is_flat(surface)


def test_server_select_screen_scroll_choose_and_remember():
    servers = _servers(14)
    screen = pygame_screens.ServerSelectScreen(servers, "tester",
                                               prefs=Prefs.load())
    _post(*[key_event(K_DOWN)] * 9, key_event(K_UP),
          pygame.event.Event(pygame.MOUSEWHEEL, y=-1, x=0),
          pygame.event.Event(pygame.MOUSEWHEEL, y=1, x=0),
          pygame.event.Event(pygame.VIDEORESIZE, size=(900, 700), w=900, h=700),
          key_event(K_RETURN))
    chosen = screen.run()
    assert chosen is not None and chosen.player_count in range(14)
    assert screen.prefs.last_server is not None
    screen.canvas.fill(pygame_screens.BG)
    screen.ui.draw(screen.canvas)
    assert drew_canvas(screen.canvas)


@pytest.mark.parametrize("count", [0, 1, 40])
def test_server_select_screen_list_sizes(count):
    screen = pygame_screens.ServerSelectScreen(_servers(count), "tester",
                                               prefs=Prefs.load())
    screen.build()
    for size in ((700, 500), (1400, 1000)):
        screen.viewport.handle_resize(*size)
    screen.on_scroll(-3)
    screen.on_key(key_event(K_DOWN))
    screen.ui.draw(screen.canvas)
    _post(key_event(K_ESCAPE))
    assert screen.run() is None


def test_show_loading_screen_draws():
    pygame_screens.show_loading_screen("Loading the world", size=(400, 300))
    surface = pygame.display.get_surface()
    assert surface.get_size() == (400, 300)
    assert drew_canvas(surface)


# -- game/ui: widget toolkit ---------------------------------------------------

def test_ui_widgets_layout_draw_and_handle_events():
    pygame.init()
    fonts = FontManager()
    mgr = ui.UIManager(fonts, 640, 480)
    clicked = []
    entered = []
    user = ui.TextInput(w=200, placeholder="user", max_len=5,
                        on_enter=lambda: entered.append(1))
    secret = ui.TextInput(w=200, placeholder="pw", password=True)
    button = ui.Button("Go", w=120, h=30, on_click=lambda: clicked.append(1))
    panel = ui.Panel(w=300, h=300, anchor=ui.CENTER, bg=theme.PANEL_BG,
                     border=theme.PANEL_BORDER, radius=10, vstack=True,
                     padding=12, spacing=6)
    panel.add(ui.Label("Title", role="title"), user, secret, button,
              ui.Image(pygame.Surface((10, 10))))
    mgr.root.add(panel)
    mgr.layout()
    user.focused = True
    for ch in "abcdefg":                       # max_len 5 clips it
        mgr.handle_event(key_event(ord(ch), ch))
    assert user.text == "abcde"
    mgr.handle_event(key_event(K_BACKSPACE))
    assert user.text == "abcd"
    mgr.handle_event(key_event(K_RETURN))
    assert entered
    mgr.focus_next()
    secret.text = "hunter2"
    assert secret.display_text != "hunter2"
    center = button.rect.center if hasattr(button, "rect") else (320, 240)
    mgr.update(center)
    mgr.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                        pos=center, button=1))
    mgr.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP,
                                        pos=center, button=1))
    surf = pygame.Surface((640, 480))
    surf.fill((0, 0, 0))
    mgr.draw(surf)
    assert drew_canvas(surf)
    mgr.resize(900, 700)
    mgr.draw(pygame.Surface((900, 700)))
    panel.clear()
    mgr.layout()


# -- game/viewport ---------------------------------------------------------------

def test_viewport_scaled_and_native_modes():
    scaled = Viewport(320, 240, window_w=640, window_h=480, caption="t")
    assert scaled.window_to_virtual(320, 240) == (160.0, 120.0)
    scaled.canvas.fill((200, 10, 10))
    scaled.present()
    seen = []
    scaled.on_resize = lambda w, h: seen.append((w, h))
    scaled.handle_resize(800, 400)       # wider than the aspect: letterbox
    assert scaled._dest_rect.width < 800
    assert scaled.window_to_virtual(400, 200) == pytest.approx((160.0, 120.0), abs=0.5)
    scaled.present()
    assert scaled.mouse_pos() is not None
    native = Viewport(320, 240, window_w=500, window_h=300, native=True,
                      on_resize=lambda w, h: seen.append((w, h)))
    assert native.window_to_virtual(7, 9) == (7.0, 9.0)
    native.handle_resize(640, 480)
    assert seen[-1] == (640, 480)
    native.present()


# -- game/minimap --------------------------------------------------------------

def test_aspect_fit():
    assert minimap.aspect_fit((100, 50), (200, 200)) == (200, 100)
    assert minimap.aspect_fit((0, 0), (200, 200)) == (1, 1)
    assert minimap.aspect_fit((10, 400), (100, 100)) == (2, 100)


def test_map_entity_positions_on_a_gmap_and_a_single_level(make_game):
    game = make_game(gmap=True, gmap_segment=(1, 1), player_xy=(32.0, 32.0),
                     players=[{"id": 5, "x": 16.0, "y": 16.0}])
    points = list(minimap.map_entity_positions(game.client))
    assert points[0][:2] == (0.75, 0.75) and points[0][2] == (255, 0, 0)
    assert len(points) == 2 and points[1][2] == (255, 255, 255)
    single = make_game(players=[{"id": 5, "x": 16.0, "y": 48.0}])
    points = list(minimap.map_entity_positions(single.client))
    assert points[1][:2] == (0.25, 0.75)


@pytest.mark.parametrize("size", [4096, 16384, 100, 37])
def test_minimap_raw_data_builds_a_surface_or_refuses(make_game, size):
    game = make_game(gmap=True)
    data = bytes(((i * 7) % 40) + 1 for i in range(size))
    game.feed(PacketID.PLO_MINIMAP, data)
    game.frames(3)
    if size in (4096, 16384, 100):
        assert game.minimap_surface is not None
        assert game.minimap_surface.get_size() == game.minimap_size
    else:
        assert game.minimap_surface is None
    game.big_map_visible = True
    game.frames(2)
    assert game.frame_errors == {}


def test_bigmap_and_minimap_images_load_from_the_sheet(make_game):
    """The server's `bigmap`/`minimap` options arrive in the login frame;
    both maps load their image from the content tier."""
    game = make_game(gmap=True, server_options={
        "bigmap": "pics1.png,fixture.txt,0,0",
        "minimap": "pics1.png,fixture.txt,0,0"})
    game.frames(1, events=[key_event(pygame.K_m, "m")])
    game.frames(2)
    assert game.frame_errors == {}
    assert game.bigmap_surface.get_size() == (2048, 512)
    assert game.minimap_surface.get_size() == game.minimap_size


# -- game/render_text -------------------------------------------------------------

def test_nameplates_stagger_and_text_caches(make_game):
    game = make_game()
    frame = game._frame_context()
    first = game._place_nameplate(100.0, 100.0, (60, 12), frame)
    second = game._place_nameplate(100.0, 100.0, (60, 12), frame)
    far = game._place_nameplate(400.0, 300.0, (60, 12), frame)
    assert first == (100, 100) and second[1] > first[1] and far == (400, 300)
    font = game.font_small
    a = game._render_text_cached(font, "hello", (1, 2, 3))
    assert game._render_text_cached(font, "hello", (1, 2, 3)) is a
    b = game._render_text_outlined_cached(font, "hello", (255, 255, 255))
    assert game._render_text_outlined_cached(font, "hello", (255, 255, 255)) is b
    assert b.get_width() >= a.get_width()


@pytest.mark.parametrize("text", [
    "hi", "a much longer message that has to wrap onto several lines of "
    "speech bubble text before the third line cuts it off entirely", "   ", ""])
def test_speech_bubbles(make_game, text):
    game = make_game()
    assert game._wrapped_lines(text) == game._wrapped_lines(text)
    assert len(game._wrapped_lines(text)) <= 3
    game.screen.fill((0, 0, 0))
    game._render_speech_bubble(200.0, 200.0, text)
    assert surface_is_flat(game.screen) != bool(text.strip())


# -- game/render_layers -------------------------------------------------------------

LAYER_SCRIPT = (
    "if (created) {\n"
    " showimg 1,pics1.png,100,100;\n changeimgvis 1,4;\n"
    " showtext 2,40,60,Arial,b,Hello layer;\n changeimgvis 2,4;\n"
    " showimg 3,pics1.png,20,20;\n changeimgvis 3,1;\n"
    " showimg 6,pics1.png,30,30;\n changeimgvis 6,0;\n"
    " showimg 7,pics1.png,30,30;\n changeimgvis 7,2;\n"
    " this.poly={10,10,60,10,35,50}; showpoly 4,this.poly;\n"
    " changeimgvis 4,4;\n"
    " showani 5,50,50,0,idle;\n changeimgvis 5,4;\n"
    " setcoloreffect 1,0,0,0.5;\n drawaslight;\n}\n")


LAYER_NPC = {"id": 110, "x": 30.0, "y": 28.0, "image": "pics1.png",
             "imagepart": (0, 0, 32, 32), "script": LAYER_SCRIPT}


def test_scripted_layers_render_every_kind(make_game):
    game = make_game(npcs=[LAYER_NPC, GANI_NPC])
    plain = make_game(npcs=[dict(LAYER_NPC, script=""), GANI_NPC])
    game.frames(6)
    plain.frames(6)
    assert game.frame_errors == {}
    layers = game.client.npcs[110]["imgs"]
    assert {1, 2, 3, 4, 5}.issubset(layers), sorted(layers)
    assert frame_differs(game, plain)


def test_scripted_layers_survive_a_resize_and_leave_with_their_level(
        make_game):
    """After a resize and a warp away, the NPC's layers (GUI band included)
    are gone: the frame is the one a game that never saw the NPC draws."""
    knobs = {"extra_levels": {"elsewhere.nw": None}}
    game = make_game(npcs=[LAYER_NPC], **knobs)
    never = make_game(**knobs)

    async def warp(world):
        await world.me.warp("elsewhere.nw", 30.0, 30.0)
    for g in (game, never):
        g.frames(2)
        g.viewport.handle_resize(1000, 700)
        g.frames(2)
        g.server.run(warp)
        g.frames(3)
    assert game.frame_errors == {}
    assert game.client.current_level_name == "elsewhere.nw"
    assert not frame_differs(game, never)


# -- game/editor/palette + overlay ----------------------------------------------------

def test_tile_id_mapping_is_a_bijection_over_the_sheet():
    ids = {tile_id_at(c, r) for c in range(SHEET_COLS) for r in range(SHEET_ROWS)}
    assert ids == set(range(MAX_TILE_ID + 1))


def test_palette_geometry_zoom_scroll_pick_and_draw(make_game):
    game = make_game()
    palette = TilePalette(game)
    rect = palette.rect()
    assert rect.width > 0 and rect.height > 0
    assert palette.tile_at_pos((-5, -5)) is None
    inside = palette.tile_at_pos((palette._grid_rect().x + 3,
                                  palette._grid_rect().y + 3))
    assert inside == tile_id_at(0, 0)
    for delta in (1, 1, 1, -1, -5, 9):
        palette.zoom_by(delta)
        assert palette.step >= 1
    palette.scroll_by(500, 500)
    palette.scroll_by(-9999, -9999)
    assert (palette.scroll_x, palette.scroll_y) == (0, 0)
    surf = pygame.Surface((game.screen_w, game.screen_h))
    surf.fill((0, 0, 0))
    palette.draw(surf, selected=5)
    assert drew_canvas(surf)


def test_editor_overlay_draws_every_tool_and_object_kind(make_game):
    game = make_game(
        chests=[(10, 10, False)], signs=[(5, 5, "sign")],
        links=["elsewhere.nw 60 30 2 4 2 30"], npcs=[NAMED_NPC])
    game.frames(1, events=[key_event(pygame.K_F11)])
    assert game.level_editor.enabled
    for key in ("1", "2", "3", "4", "5", "o", "g", "[", "]", "p", "p"):
        game.frames(1, events=[key_event(ord(key), key)])
    game.level_editor.state.selection = (4, 4, 6, 6)
    for button_pos in ((300, 240), (310, 250)):
        game.frames(1, events=[
            pygame.event.Event(pygame.MOUSEMOTION, pos=button_pos,
                               rel=(1, 1), buttons=(1, 0, 0)),
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button_pos,
                               button=1),
            pygame.event.Event(pygame.MOUSEBUTTONUP, pos=button_pos,
                               button=1)])
    game.frames(3)
    assert game.frame_errors == {}
    surf = game.screen.copy()
    surf.fill((0, 0, 0))
    game.editor_overlay.draw(surf)
    assert drew_canvas(surf)
    game.frames(1, events=[key_event(pygame.K_F11)])
    assert not game.level_editor.enabled


def test_editor_overlay_on_a_gmap_segment(make_game):
    game = make_game(gmap=True, gmap_segment=(1, 0))
    game.frames(1, events=[key_event(pygame.K_F11)])
    game.frames(4)
    assert game.level_editor.enabled and game.frame_errors == {}


# -- gs2_gui/skins ---------------------------------------------------------------------

def _nine_patch_sheet():
    """Three states of a 3x3 9-patch, split by 1px separator lines in the
    colour of pixel (0, 0), the Torque bitmap-array layout."""
    sep = (255, 0, 255)
    cell, gap = 8, 1
    sheet = pygame.Surface((3 * (cell + gap), 9 * (cell + gap) + gap))
    sheet.fill(sep)
    for row in range(9):
        for col in range(3):
            pygame.draw.rect(sheet, (20 + row * 20, 60 + col * 40, 200),
                             (col * (cell + gap), gap + row * (cell + gap),
                              cell, cell))
    return sheet


def test_bitmap_array_split_finds_rows_and_cells():
    rows = _split_bitmap_array(_nine_patch_sheet())
    assert len(rows) == 9 and all(len(r) == 3 for r in rows)
    assert _split_bitmap_array(pygame.Surface((0, 0))) == []


def test_skin_cells_nine_patch_and_scaling():
    skin = _Skin("guiblue_button.png", _nine_patch_sheet())
    assert skin.cell(0, 0) is not None and skin.cell(99, 0) is None
    surf = pygame.Surface((120, 60))
    surf.fill((0, 0, 0))
    assert skin.draw_nine(surf, pygame.Rect(5, 5, 100, 40), 0)
    assert skin.draw_nine(surf, pygame.Rect(5, 5, 6, 4), 3, alpha=100)
    assert not skin.draw_nine(surf, pygame.Rect(0, 0, 10, 10), 7)
    skin.blit_scaled(surf, None, pygame.Rect(0, 0, 4, 4))
    skin.blit_scaled(surf, skin.cell(0, 0), pygame.Rect(0, 0, 0, 4))
    assert drew_canvas(surf)


def test_skin_window_frame_and_background():
    plain = _Skin("small.png", _nine_patch_sheet())
    surf = pygame.Surface((200, 160))
    assert not plain.looks_like_window_sheet()
    assert not plain.draw_window_frame(surf, pygame.Rect(0, 0, 100, 80))
    assert not plain.draw_window_background(surf, pygame.Rect(0, 0, 100, 80))
    sheet = pygame.Surface((64, 152))
    sheet.fill((10, 120, 200))
    window = _Skin("guiblue_window.png", sheet)
    assert window.looks_like_window_sheet() and window.has_window_background()
    assert window.draw_window_background(surf, pygame.Rect(10, 10, 90, 70),
                                         alpha=128)
    assert window.draw_window_frame(surf, pygame.Rect(10, 10, 120, 100))
    assert window.draw_window_frame(surf, pygame.Rect(0, 0, 40, 20))
    noback = _Skin("guiblue_window_noback.png", pygame.Surface((64, 135)))
    assert noback.looks_like_window_sheet() and not noback.has_window_background()


def test_gs2_window_with_a_skin_through_the_frame(make_game):
    game = make_game()
    gui = game.gs2.gui
    win = gui.create_control("GuiWindowCtrl", "SkinWin")
    win.width, win.height = 320.0, 200.0
    gui.addcontrol(win)
    button = gui.create_control("GuiButtonCtrl", "SkinButton")
    gui.add_to(win, button)
    plain = make_game()
    game.frames(3)
    plain.frames(3)
    assert game.frame_errors == {}
    assert frame_differs(game, plain)
