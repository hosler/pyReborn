"""Offline render coverage over the make_game() fixture (tests/offline_game.py).

Every scene below is asserted through a content probe: the scene is built
twice on the same fixture clock, once with the thing under test and once
without, and the probe region of the two finished frames must differ. An
overlay's region is its own rect (worked out from its layout constants, not
by asking the overlay), and the area outside it must not change, except where
the overlay legitimately dims or decorates the screen (``Scene.outside``).
A render pass that stops drawing therefore fails its scene, and
``test_probe_goes_blind_without_its_pass`` proves that for every pass in
PASS_SCENES by replacing the pass with a no-op and requiring its check to
fail. Where, what and in which order things are drawn is pinned by the colour
checks in test_offline_positions.py, and
``test_position_checks_fail_under_behavioural_mutation`` proves those by
breaking the renderer on purpose. Every step is strict, so a raising pass
fails the test as well.
"""

import re
import textwrap
from dataclasses import dataclass, field
from itertools import zip_longest
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pygame
import pytest
from pygame.locals import (
    K_DOWN, K_ESCAPE, K_F1, K_F7, K_F8, K_F9, K_F10, K_F11, K_F12, K_RETURN,
    K_UP, K_a, K_e, K_h, K_m, K_q, K_y)

import offline_expect as ex
import offline_game
from frame_baseline import capture
from offline_game import (
    GANI_NPC, GMAP_NAME, GMAP_SEGMENTS, IMAGE_NPC, NAMED_NPC, _gchar, changed_outside, changed_pixels, key_event, region_differs,
    world_rect)
from offline_checks import POSITION_CHECKS
from pyreborn.game.editor.overlay import EditorOverlay
from pyreborn.game.editor.palette import TilePalette
from pyreborn.game.camera import Camera2D
from pyreborn.sprites import SpriteManager, TilesetManager
from pyreborn.inventory_ui import HeartDisplay, InventoryUI
from pyreborn.packets import PacketID
from pyreborn.pygame_game import GameClient
from pyreborn.game.dev_ui import DevOverlay
from pyreborn.game import theme
from pyreborn.game.hud import HUD
from pyreborn.game.rc_ui import RCOverlay
from pygserver.protocol.packets import (
    build_explosion, build_say2)


def _flat(tile):
    return lambda tx, ty: tile


def _npc(npc_id, x, y, script, image="pics1.png"):
    return {"id": npc_id, "x": x, "y": y, "image": image, "script": script}


def _keys(*keys):
    return [[key_event(k, chr(k) if 32 <= k < 127 else "")] for k in keys]


def _open_chest(x, y):
    """Our client opens a chest; pygserver's own PLI_OPENCHEST handler
    answers (opened chest + the item)."""
    async def run(world):
        await world.me._dispatch_packet(PacketID.PLI_OPENCHEST,
                                        _gchar(x) + _gchar(y))
    return lambda game: game.server.run(run)


def _send(raw):
    return lambda game: game.server.send(raw)


@dataclass
class Scene:
    """``knobs`` build the subject; ``baseline`` (default: no knobs) builds
    the frame it is compared with. ``common`` goes to both. ``act`` runs on
    the subject after its first frame; ``inputs`` are per-frame event lists
    for the subject, starting with the second frame, and ``baseline_inputs``
    the same for the baseline. ``region`` is a world rect ``(x, y, w, h)``, a
    screen ``pygame.Rect``, a ``fn(game) -> Rect`` for an overlay whose rect
    follows from the game's own state, or None (whole frame).

    ``outside`` says what the area outside ``region`` may do:
    ``"same"`` nothing (apart from the rects ``allow(game)`` lists),
    ``"dim"`` it is the baseline's pixels under the theme's shade (the overlay
    dims everything behind it), ``""`` unchecked. ``verify(subject,
    baseline)`` adds colour assertions."""
    knobs: Dict[str, Any] = field(default_factory=dict)
    baseline: Dict[str, Any] = field(default_factory=dict)
    common: Dict[str, Any] = field(default_factory=dict)
    act: Optional[Callable] = None
    inputs: List[list] = field(default_factory=list)
    baseline_inputs: List[list] = field(default_factory=list)
    region: Any = None
    frames: int = 6
    minimum: int = 4
    outside: str = ""
    allow: Optional[Callable] = None
    verify: Optional[Callable] = None


def run_scene(make_game, scene: Scene):
    """Run the subject and the baseline, capturing the subject's frames for
    the frame baseline tool at the first frame, after every input, and in the
    middle and at the end of the run."""
    subject = make_game(**scene.common, **scene.knobs)
    baseline = make_game(**scene.common, **scene.baseline)
    for game in (subject, baseline):
        game.frames(1)
    capture(subject, "first")
    if scene.act is not None:
        scene.act(subject)
    pairs = list(zip_longest(scene.inputs, scene.baseline_inputs))
    for n, (events, base_events) in enumerate(pairs, 1):
        subject.frames(1, events=events)
        baseline.frames(1, events=base_events)
        capture(subject, f"input{n}")
    subject.frames(max(1, scene.frames - 1))
    baseline.frames(max(1, scene.frames - 1))
    capture(subject, "mid")
    subject.frames(1)
    baseline.frames(1)
    capture(subject, "end")
    assert subject.frame_errors == {} and baseline.frame_errors == {}
    return subject, baseline


def scene_region(scene: Scene, subject):
    return scene.region(subject) if callable(scene.region) else scene.region


def probe(make_game, scene: Scene) -> bool:
    subject, baseline = run_scene(make_game, scene)
    region = scene_region(scene, subject)
    if isinstance(region, pygame.Rect):
        return region_differs(subject, baseline, screen=region,
                              minimum=scene.minimum)
    return region_differs(subject, baseline, world=region,
                          minimum=scene.minimum)


def check_scene(make_game, name: str) -> None:
    """The scene's region differs, nothing outside it changes the way it must
    not, and its colour assertions hold. Raises AssertionError otherwise."""
    scene = SCENES[name]
    subject, baseline = run_scene(make_game, scene)
    region = scene_region(scene, subject)
    if isinstance(region, pygame.Rect):
        differs = region_differs(subject, baseline, screen=region,
                                 minimum=scene.minimum)
    else:
        differs = region_differs(subject, baseline, world=region,
                                 minimum=scene.minimum)
    assert differs, (f"{name}: the probe region is identical with and "
                     f"without the content")
    if scene.outside:
        assert isinstance(region, pygame.Rect), "outside needs a screen rect"
        keep = [region] + (scene.allow(subject) if scene.allow else [])
        if scene.outside == "same":
            n = changed_outside(subject, baseline, keep)
            assert n == 0, (f"{name}: {n} pixels changed outside the "
                            f"overlay's own rect {region}")
        elif scene.outside == "dim":
            shade = pygame.Surface(baseline.last_frame.get_size(),
                                   pygame.SRCALPHA)
            shade.fill(theme.SHADE)
            expected = baseline.last_frame.copy()
            expected.blit(shade, (0, 0))
            holder = type("Frame", (), {"last_frame": expected})
            n = changed_outside(subject, holder, keep)
            assert n == 0, (f"{name}: {n} pixels outside {region} are not the "
                            f"baseline under the theme's shade")
    if scene.verify:
        scene.verify(subject, baseline)


# -- the rect each overlay draws into, from its layout constants --------------

def _centred(game, w, h):
    sw, sh = game.screen.get_size()
    return pygame.Rect((sw - w) // 2, (sh - h) // 2, w, h)


def list_overlay_rect(rows):
    """hud._draw_list_overlay: 360 px wide, 14 px padding, a 30 px title, 22
    px rows (one "(none)" row when empty), a 24 px footer; centred."""
    def rect(game):
        n = rows(game) if callable(rows) else rows
        return _centred(game, 360, 14 * 2 + 30 + 22 * max(1, n) + 24)
    return rect


def dialogue_rect(game):
    """hud._draw_dialogue: 400 px (or the canvas minus 40) wide, 20 px plus a
    line per visible text line tall (60 at least), bottom-anchored. A sign's
    text is set in the classic font, other speech in the small one."""
    sw, sh = game.screen.get_size()
    font = (game.fonts.classic() if game.dialogue_classic_font
            else game.font_small)
    lines = len(game.dialogue_pager.visible_lines)
    h = max(60, lines * font.get_linesize() + 20)
    w = min(sw - 40, 400)
    return pygame.Rect((sw - w) // 2, min(sh - 150, sh - h - 10), w, h)


SERVER_MOVE_TEXT = ("This server wants to move you to Other (10.9.9.9:14999). "
                    "Connect?")


def warp_prompt_rect(game):
    """hud._draw_server_warp_prompt: 380 wide; the request wrapped at 44 plus
    four fixed lines of 20 px, a 30 px title, a 76 px input area."""
    lines = len(textwrap.wrap(SERVER_MOVE_TEXT, 44)) + 4
    return _centred(game, 380, 14 * 2 + 30 + 20 * lines + 76)


def rc_panel_rect(game):
    sw, sh = game.screen.get_size()
    return _centred(game, min(720, max(320, sw - 20)),
                    min(500, max(240, sh - 20)))


def dev_panel_rect(game):
    sw, sh = game.screen.get_size()
    return pygame.Rect(24, 24, max(320, sw - 48), max(240, sh - 48))


def editor_toolbar_rect(game):
    """editor/overlay._draw_toolbar: at (8, 8), 860 wide at most, 12 px plus
    three rows of the chat font's height + 8, one more while a status line
    ("edit mode on") is showing."""
    sw, _ = game.screen.get_size()
    font = game.fonts.get("chat")
    rows = 3 + (1 if game.level_editor.state.status else 0)
    return pygame.Rect(8, 8, min(sw - 16, 860), 12 + rows * (font.get_height() + 8))


def palette_rect(game):
    """editor/palette.rect: the tileset at 2x, pinned to the window bottom."""
    sw, sh = game.screen.get_size()
    w = min(sw - 20, 128 * 16 * 2 + 16)
    h = min(max(120, sh // 3), 32 * 16 * 2 + 16 + 20)
    return pygame.Rect((sw - w) // 2, sh - h - 10, w, h)


def editor_decorations(game):
    """What edit mode draws over the level besides its toolbar: the tile grid
    (one pixel column and row per tile boundary) and the one-tile brush
    cursor under the mouse."""
    sw, sh = game.screen.get_size()
    origin = ex.level_origin(game, (game.client.x, game.client.y))
    lines = [pygame.Rect(int(origin[0] + i * 16), 0, 1, sh) for i in range(65)]
    lines += [pygame.Rect(0, int(origin[1] + i * 16), sw, 1) for i in range(65)]
    mx, my = game.viewport.mouse_pos()
    col, row = (mx - origin[0]) // 16, (my - origin[1]) // 16
    lines.append(pygame.Rect(int(origin[0] + col * 16),
                             int(origin[1] + row * 16), 16, 16))
    return lines


def debug_readout_rect(game):
    """_render_debug_hud's first left-column line, with its backing plate."""
    x, y = game.client.x, game.client.y
    text = f"{game.client.current_level_name}  ({x:.1f}, {y:.1f})"
    w, h = game.font.size(text)
    return pygame.Rect(10 - 5, 64 - 2, w + 10, h + 4)


def big_map_rect(game):
    """hud._draw_big_map: the map image, fitted into the canvas minus 80 px
    and centred, in a 3 px frame."""
    source = (game.bigmap_surface or game._minimap_native_surface
              or game.minimap_surface)
    sw, sh = game.screen.get_size()
    iw, ih = source.get_size()
    scale = min((sw - 80) / iw, (sh - 80) / ih)
    w, h = round(iw * scale), round(ih * scale)
    return pygame.Rect((sw - w) // 2 - 3, (sh - h) // 2 - 3, w + 6, h + 6)


def _verify_palette(subject, baseline):
    """Palette cells sit on a 32 px pitch (16 px tiles at 2x), 8 px in from the
    panel; the cell at sheet column c, row r shows that cell's colour."""
    rect = palette_rect(subject)
    for col, row in ((0, 0), (5, 2), (20, 3), (28, 1)):
        x = rect.x + 8 + col * 32 + 16
        y = rect.y + 8 + row * 32 + 16
        ex.expect_pixel(subject.last_frame, (x, y),
                        offline_game.cell_color("dustynewpics1.png", col, row),
                        f"palette cell ({col},{row})")


def _verify_big_map(subject, baseline):
    rect = big_map_rect(subject)
    # the 3 px frame is drawn in the theme's colour around the image
    ex.expect_pixel(subject.last_frame, (rect.centerx, rect.y + 1),
                    theme.EMERALD_DEEP, "big map frame, top edge")
    ex.expect_pixel(subject.last_frame, (rect.x + 1, rect.centery),
                    theme.EMERALD_DEEP, "big map frame, left edge")


#: A gmap whose server sets the `bigmap` and `minimap` options (four
#: tokens, the only form the login sends).
MAPS = {"gmap": True,
        "server_options": {"bigmap": "pics1.png,fixture.txt,0,0",
                           "minimap": "pics1.png,fixture.txt,0,0"}}

#: The frame minus the top-right "H: Help" hint, which the inventory, the
#: help overlay and chat typing all hide (so it differs without their draw).
BELOW_HINT = pygame.Rect(0, 30, 4096, 4096)
BOTTOM_STRIP = pygame.Rect(0, 680, 4096, 40)

LAYER_IMG = "showimg 1,pics1.png,600,500;\n changeimgpart 1,0,0,32,32;\n"

SCENES: Dict[str, Scene] = {
    # -- populations ---------------------------------------------------------
    "other_player_chat": Scene(
        knobs={"players": [{"id": 6, "x": 40.0, "y": 22.0,
                            "nickname": "Cy", "curchat": "hi there"}]},
        baseline={"players": [{"id": 6, "x": 40.0, "y": 22.0,
                               "nickname": "Cy"}]},
        region=(38, 19, 6, 3)),
    "chest": Scene(knobs={"chests": [(20, 38, False)]}, region=(20, 38, 2, 2)),
    "item": Scene(knobs={"items": [(26.0, 40.0, 0)]}, region=(26, 40, 1, 1)),
    "baddy": Scene(knobs={"baddies": [{"x": 40.0, "y": 40.0, "type": 1}]},
                   region=(40, 40, 3, 3)),
    "bomb": Scene(knobs={"bombs": [(36.0, 36.0)]}, region=(35, 35, 2, 2),
                  frames=3),
    "arrow": Scene(knobs={"arrows": [(40.0, 26.0, 1)]},
                   region=(30, 25, 12, 3), frames=3),
    "flying": Scene(knobs={"flying": [(40.0, 34.0, 1, 2)]},
                    region=(30, 32, 12, 5), frames=3),
    "sign_popup": Scene(knobs={"signs": [(31, 32, "hello sign")]}),
    "dead": Scene(knobs={"hearts": 0}, region=(48, 44, 3, 3), frames=30),
    # The server only lets a chest open from within three tiles of it.
    "chest_reveal": Scene(knobs={"chests": [(27, 31, False)]},
                          baseline={"chests": [(27, 31, True)]},
                          act=_open_chest(27, 31),
                          region=(27.5, 30, 1, 1), frames=3),
    "explosion": Scene(act=_send(build_explosion(0, 44, 18, 2, 1)),
                       region=(42, 16, 5, 5), frames=3),
    "tint": Scene(knobs={"npcs": [_npc(120, 44, 30, "seteffect 0,0,1,0.5;")]},
                  region=(48, 14, 2, 2)),
    "light": Scene(knobs={"npcs": [dict(
        _npc(121, 44, 34, "if (playerenters) {drawaslight;}"),
        imagepart=(0, 0, 32, 32))]}, region=(44, 34, 2, 2)),
    "npc_layer_over": Scene(
        knobs={"npcs": [_npc(122, 44, 40, "if (created) {\n"
                             " showimg 1,pics1.png,46,42;\n"
                             " changeimgpart 1,0,0,32,32;\n"
                             " changeimgvis 1,2;\n}\n", image="-")]},
        region=(46, 42, 2, 2)),
    "gui_showimg": Scene(
        knobs={"npcs": [_npc(123, 44, 30, "if (created) {\n " + LAYER_IMG
                             + " changeimgvis 1,4;\n}\n", image="-")]},
        region=pygame.Rect(600, 500, 32, 32)),
    "gui_showtext": Scene(
        knobs={"npcs": [_npc(124, 44, 30, "if (created) {\n"
                             " showtext 2,600,400,Arial,b,Hello layer;\n"
                             " changeimgvis 2,4;\n}\n", image="-")]},
        region=pygame.Rect(590, 390, 200, 40)),
    "gui_showpoly": Scene(
        knobs={"npcs": [_npc(125, 44, 30, "if (created) {\n"
                             " this.poly={600,200,660,200,630,250};\n"
                             " showpoly 4,this.poly;\n"
                             " changeimgvis 4,4;\n}\n", image="-")]},
        region=pygame.Rect(600, 200, 60, 50)),
    "gui_showani": Scene(
        knobs={"npcs": [_npc(126, 44, 30, "if (created) {\n"
                             " showani 5,600,300,0,idle;\n"
                             " changeimgvis 5,4;\n}\n", image="-")]},
        region=pygame.Rect(580, 280, 80, 80)),
    "gmap_neighbour": Scene(
        common={"gmap": True, "player_xy": (56.0, 30.0)},
        baseline={"extra_levels": {GMAP_SEGMENTS[1]: _flat(3)}},
        region=(66, 28, 3, 3)),
    "gmap_npc": Scene(common={"gmap": True},
                      knobs={"npcs": [NAMED_NPC]}, region=(28, 34, 2, 2)),
    "gmap_other_segment": Scene(
        common={"gmap": True, "gmap_segment": (1, 1)},
        baseline={"extra_levels": {GMAP_SEGMENTS[3]: _flat(3)}},
        region=(64 + 40, 64 + 12, 3, 3)),
    # -- overlays ---------------------------------------------------------------
    "hud": Scene(knobs={"me": {"rupees": 123}},
                 region=pygame.Rect(0, 0, 240, 90)),
    # Typing also hides the corner "H: Help" hint; the entry line is the
    # bottom strip.
    "chat_input": Scene(inputs=_keys(K_RETURN, K_h, K_e, K_y),
                        region=BOTTOM_STRIP),
    "dialogue": Scene(act=_send(build_say2(
        "A sign says something long enough to wrap across more than one line "
        "of the dialogue box so the pager has pages to turn.")),
        region=dialogue_rect, outside="same"),
    # The corner map shows by default (prefs); the server's option is what
    # gives it an image.
    "minimap": Scene(common={"gmap": True},
                     knobs={"server_options": MAPS["server_options"]},
                     region=pygame.Rect(880, 0, 144, 130)),
    # The big map dims the whole screen behind its image.
    "big_map": Scene(common=MAPS, inputs=_keys(K_m), region=big_map_rect,
                     outside="dim", verify=_verify_big_map),
    "inventory": Scene(inputs=_keys(K_q), region=BELOW_HINT),
    "settings": Scene(inputs=_keys(K_F9), outside="same",
                      region=list_overlay_rect(lambda g: len(g.settings_ui.rows()))),
    "player_list": Scene(common={"players": [
        {"id": 5, "x": 20.0, "y": 20.0, "nickname": "Bob"}]},
        inputs=_keys(K_F7), region=list_overlay_rect(1), outside="same"),
    "pm": Scene(common={"players": [
        {"id": 5, "x": 20.0, "y": 20.0, "nickname": "Bob"}]},
        inputs=_keys(K_F7, K_RETURN), region=list_overlay_rect(1),
        outside="same"),
    "server_list": Scene(inputs=_keys(K_F8), region=list_overlay_rect(0),
                         outside="same"),
    "server_warp_prompt": Scene(act=lambda g: g.feed(
        PacketID.PLO_SERVERWARP, b'"Other","Other","10.9.9.9","14999"'),
        region=warp_prompt_rect, outside="same"),
    "help": Scene(inputs=_keys(K_h), region=BELOW_HINT),
    "rc_panel": Scene(inputs=_keys(K_F10), region=rc_panel_rect,
                      outside="same"),
    "dev_panel": Scene(inputs=_keys(K_F12), region=dev_panel_rect,
                       outside="same"),
    # Edit mode draws the toolbar and a one-pixel grid over the level.
    "editor": Scene(inputs=_keys(K_F11), region=editor_toolbar_rect,
                    outside="same", allow=editor_decorations),
    # The palette is compared with edit mode itself, so only the palette
    # (and its cells' colours) may differ.
    "editor_palette": Scene(inputs=[[key_event(K_F11)],
                                    [key_event(pygame.K_p, "p")]],
                            baseline_inputs=[[key_event(K_F11)]],
                            region=palette_rect, outside="same",
                            verify=_verify_palette),
    # F1 tints every visible tile (asserted by the debug_overlay position
    # check), so nothing "outside" stays put; this is the first readout line.
    "debug": Scene(inputs=_keys(K_F1), region=debug_readout_rect),
}


@pytest.mark.parametrize("name", sorted(SCENES))
def test_scene_draws_its_content(make_game, name):
    check_scene(make_game, name)


#: Every check the self-check below can point a render pass at: the scenes
#: above and the colour checks of test_offline_positions.py.
CHECKS: Dict[str, Callable] = {
    **{name: (lambda make_game, name=name: check_scene(make_game, name))
       for name in SCENES},
    **POSITION_CHECKS,
}


# -- the probes are not blind ---------------------------------------------------

#: Every render pass the frame relies on: (owner class, method, the scene
#: whose probe must go blind when that method draws nothing).
PASS_SCENES = [
    (GameClient, "_render_world", "tiles"),
    (GameClient, "_render_player", "own_player_position"),
    (GameClient, "_render_npc", "npc_positions"),
    (GameClient, "_render_animated_entity", "npc_positions"),
    (GameClient, "_render_other_player", "other_player_position"),
    (GameClient, "_render_debug_overlay", "debug_overlay"),
    (HeartDisplay, "render", "hearts"),
    (EditorOverlay, "draw", "editor"),
    (TilePalette, "draw", "editor_palette"),
    (GameClient, "_render_bombs", "bomb"),
    (GameClient, "_render_screen_tint", "tint"),
    (GameClient, "_render_deferred_lights", "light"),
    (GameClient, "_render_gui_layers_inner", "gui_showimg"),
    (GameClient, "_render_server_explosions", "explosion"),
    (GameClient, "_render_combat_presentation", "dead"),
    (GameClient, "_render_chest_reveals", "chest_reveal"),
    (GameClient, "_render_npc_layers", "npc_layer_over"),
    (GameClient, "_render_showimg_rec", "gui_showimg"),
    (GameClient, "_render_showtext_rec", "gui_showtext"),
    (GameClient, "_render_showpoly_rec", "gui_showpoly"),
    (GameClient, "_render_showani_rec", "gui_showani"),
    (GameClient, "_render_sign_popup", "sign_popup"),
    # _render_chests/_render_items are harness entry points the frame never
    # calls; the frame draws chests and items through these two.
    (GameClient, "_draw_chest_entity", "chest"),
    (GameClient, "_draw_item_entity", "item"),
    (HUD, "draw", "hud"),
    (HUD, "_draw_chat", "chat_input"),
    (HUD, "_draw_dialogue", "dialogue"),
    (HUD, "_draw_minimap", "minimap"),
    (HUD, "_draw_big_map", "big_map"),
    (HUD, "_draw_player_list", "player_list"),
    (HUD, "_draw_server_list", "server_list"),
    (HUD, "_draw_server_warp_prompt", "server_warp_prompt"),
    (HUD, "_draw_settings", "settings"),
    (HUD, "_draw_help_overlay", "help"),
    (RCOverlay, "draw", "rc_panel"),
    (DevOverlay, "draw", "dev_panel"),
    (InventoryUI, "render", "inventory"),
]


@pytest.mark.parametrize("owner,method,scene", PASS_SCENES,
                         ids=[f"{o.__name__}.{m}" for o, m, _ in PASS_SCENES])
def test_probe_goes_blind_without_its_pass(make_game, monkeypatch, owner,
                                           method, scene):
    original = getattr(owner, method)
    assert callable(original)

    def noop(*args, **kwargs):
        return None
    monkeypatch.setattr(owner, method, noop)
    # The entity pass dispatches through a kind -> function table built at
    # class creation, so a renderer is replaced there too.
    table = getattr(owner, "_ENTITY_RENDERERS", {})
    for kind, render in list(table.items()):
        if render is original:
            monkeypatch.setitem(table, kind, noop)
    with pytest.raises(AssertionError):
        CHECKS[scene](make_game)
    # (a check that fails for an unrelated reason would pass the line above,
    # so the unmutated check must pass: test_scene_draws_its_content and
    # test_position run it)


# -- the position checks are not blind either ---------------------------------

def _mutate_npc_blit(mp):
    original = GameClient._render_npc
    mp.setattr(GameClient, "_render_npc",
               lambda self, x, y, *rest, **kw: original(self, x + 16, y,
                                                        *rest, **kw))


def _mutate_other_player_blit(mp):
    original = GameClient._render_other_player
    mp.setattr(GameClient, "_render_other_player",
               lambda self, x, y, *rest, **kw: original(self, x + 16, y,
                                                        *rest, **kw))


def _mutate_camera(mp):
    original = Camera2D.world_to_screen
    mp.setattr(Camera2D, "world_to_screen",
               lambda self, wx, wy: tuple(
                   v + 16 for v in original(self, wx, wy)))


def _mutate_tile_id(mp):
    original = TilesetManager.get_tile
    mp.setattr(TilesetManager, "get_tile",
               lambda self, tile_id, tileset=None: original(
                   self, tile_id + 1, tileset))


def _mutate_sprite_rect(mp):
    plain, recoloured = (SpriteManager.get_sprite,
                         SpriteManager.get_sprite_recolored)
    mp.setattr(SpriteManager, "get_sprite",
               lambda self, sheet, x, y, w, h: plain(self, sheet, x + 8, y, w, h))
    mp.setattr(SpriteManager, "get_sprite_recolored",
               lambda self, sheet, colors, x, y, w, h: recoloured(
                   self, sheet, colors, x + 8, y, w, h))


def _mutate_nameplate_text(mp):
    original = GameClient._render_text_outlined_cached
    mp.setattr(GameClient, "_render_text_outlined_cached",
               lambda self, font, text, color, *rest: original(
                   self, font, text + "!", color, *rest))


def _mutate_npc_plate_centre(mp):
    """The old rule: a character NPC's plate centred at x + 16, not x + 24."""
    original = GameClient._draw_nameplate
    mp.setattr(GameClient, "_draw_nameplate",
               lambda self, text, color, centre_x, top_y, frame: original(
                   self, text, color,
                   centre_x - 8 if text == "Offline Guard" else centre_x,
                   top_y, frame))


def _mutate_nameplate_y(mp):
    """A plate 8 px too low (the old 48 px rule was 8 px off for others)."""
    original = GameClient._nameplate_top
    mp.setattr(GameClient, "_nameplate_top",
               lambda self, y, horse=False, own=False: original(
                   self, y, horse, own) + 8)


def _mutate_hearts(mp):
    original = HeartDisplay.render
    mp.setattr(HeartDisplay, "render",
               lambda self, screen, current, maximum: original(
                   self, screen, current - 1, maximum))


def _mutate_depth_sort(mp):
    mp.setattr(GameClient, "_depth_sort_key",
               staticmethod(lambda world_y, height: -(world_y + height)))


def _mutate_debug_overlay(mp):
    mp.setattr(GameClient, "_render_debug_overlay", lambda self: None)


#: mutation name -> (how to break the renderer, the position checks that must
#: each fail under it). The table in the commit message / CLAUDE.md lists
#: which assertion catches each.
MUTATIONS = {
    "npc blit +16 px": (_mutate_npc_blit, ["npc_positions"]),
    "other-player blit +16 px": (_mutate_other_player_blit,
                                 ["other_player_position", "sprite_cells"]),
    "camera world_to_screen +16 px": (_mutate_camera,
                                      ["tiles", "camera", "own_player_position"]),
    "tile id +1": (_mutate_tile_id, ["tiles", "camera"]),
    "sprite sub-rect x+8": (_mutate_sprite_rect,
                            ["own_player_position", "sprite_cells",
                             "npc_positions"]),
    "nameplate text altered": (_mutate_nameplate_text, ["nameplates"]),
    "NPC plate centred at +16": (_mutate_npc_plate_centre, ["nameplates"]),
    "nameplate 8 px low": (_mutate_nameplate_y, ["nameplates"]),
    "HeartDisplay count -1": (_mutate_hearts, ["hearts"]),
    "negated _depth_sort_key": (_mutate_depth_sort, ["z_order"]),
    "no-op _render_debug_overlay": (_mutate_debug_overlay, ["debug_overlay"]),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_position_checks_fail_under_behavioural_mutation(
        make_game, monkeypatch, name):
    """Break the renderer in a way that still draws something, and require
    every listed colour check to fail. A check that passes under its own
    mutation does not pin what it claims to."""
    mutate, checks = MUTATIONS[name]
    mutate(monkeypatch)
    survivors = []
    for check in checks:
        try:
            POSITION_CHECKS[check](make_game)
        except AssertionError:
            continue
        survivors.append(check)
    assert not survivors, f"mutation {name!r} survives {survivors}"


def test_death_overlay_is_drawn_after_the_delay(make_game, monkeypatch):
    """The death overlay sits on top of a full-screen fade, so no
    with/without pair isolates it; this re-renders the same frame with only
    the overlay suppressed, and goes blind when the overlay is a no-op."""
    game = make_game(hearts=0)
    game.frames(30)                       # 0.5 s, past DEATH_OVERLAY_DELAY
    assert offline_game.pass_contributes(game, game.hud, "draw_death_overlay")
    monkeypatch.setattr(HUD, "draw_death_overlay", lambda *a, **k: None)
    assert not offline_game.pass_contributes(game, game.hud,
                                             "draw_death_overlay")


# -- what reaches the stores ---------------------------------------------------------

def test_population_reaches_the_client_stores(make_game):
    """The stores a frame draws from are filled by the real handlers from
    what pygserver sent."""
    game = make_game(npcs=[IMAGE_NPC, NAMED_NPC], chests=[(10, 10, False)],
                     items=[(14.0, 14.0, 0)], signs=[(5, 5, "hello")],
                     players=[{"id": 5, "x": 20.0, "y": 20.0,
                               "nickname": "Bob"}],
                     baddies=[{"x": 40.0, "y": 40.0}],
                     bombs=[(31.0, 31.0)], arrows=[(32.0, 33.0, 1)])
    c = game.client
    assert {101, 103} <= set(c.npcs)
    assert c.npcs[103]["nickname"] == "Offline Guard"
    assert c.chests["fixture.nw"][(10, 10)] is False
    assert c.items["fixture.nw"][(14.0, 14.0)] == "greenrupee"
    assert c.signs["fixture.nw"][(5, 5)].strip() == "hello"
    assert c.players[5]["x"] == 20.0
    assert [b["x"] for b in c.baddies["fixture.nw"].values()] == [40.0]
    assert c.bombs["fixture.nw"] and c.arrows
    assert (c.x, c.y) == (30.0, 30.0)
    assert len(c.tiles) == 4096


def test_gmap_fixture_builds_the_grid_and_world_position(make_game):
    game = make_game(gmap=True, gmap_segment=(1, 0), player_xy=(10.0, 12.0))
    c = game.client
    assert c.gmap_width == 2 and c.gmap_height == 2
    assert c.gmap_name == GMAP_NAME
    assert [c.gmap_grid[cell] for cell in ((0, 0), (1, 0), (0, 1), (1, 1))] \
        == list(GMAP_SEGMENTS)
    assert c._current_level_name == GMAP_SEGMENTS[1]
    assert (c.x, c.y) == (64 + 10.0, 12.0)
    for name in GMAP_SEGMENTS:
        assert len(c.levels[name]) == 4096


# -- the overlays take keys -----------------------------------------------------------

OVERLAY_KEYS = [key_event(K_DOWN), key_event(K_UP), key_event(K_a, "a"),
                key_event(pygame.K_TAB), key_event(K_RETURN),
                key_event(pygame.K_BACKSPACE)]
OVERLAYS = ("chat_input", "dialogue", "minimap", "big_map", "inventory",
            "settings", "player_list", "pm", "server_list",
            "server_warp_prompt", "help", "rc_panel", "dev_panel", "editor",
            "editor_palette", "debug")


@pytest.mark.parametrize("name", OVERLAYS)
def test_overlay_accepts_keys(make_game, name):
    scene = SCENES[name]
    game = make_game(**scene.common, **scene.knobs)
    game.frames(1)
    if scene.act is not None:
        scene.act(game)
    for events in scene.inputs:
        game.frames(1, events=events)
    for ev in OVERLAY_KEYS:
        game.frames(1, events=[ev])
    game.frames(2)
    assert game.frame_errors == {}


@pytest.mark.parametrize("key,flag", [
    (K_q, lambda g: g.inventory_ui.visible),
    (K_F7, lambda g: g.show_player_list),
    (K_F8, lambda g: g.show_server_list),
    (K_F9, lambda g: g.settings_ui.visible),
    (K_F10, lambda g: g.rc_ui.visible),
    (K_F11, lambda g: g.level_editor.enabled),
    (K_F12, lambda g: g.dev_ui.visible),
    (K_h, lambda g: g.show_help),
    (K_m, lambda g: g.big_map_visible),
])
def test_overlay_hotkey_opens_and_escape_restores_the_frame(
        make_game, key, flag):
    """Open with the hotkey, close with the hotkey and Escape: the frame is
    the one a game that never opened anything draws."""
    game = make_game(gmap=True)
    untouched = make_game(gmap=True)
    game.frames(1, events=[key_event(key)])
    untouched.frames(1)
    assert flag(game)
    game.frames(3)
    untouched.frames(3)
    game.frames(1, events=[key_event(key), key_event(K_ESCAPE)])
    untouched.frames(1)
    game.running = True
    game.frames(2)
    untouched.frames(2)
    assert not flag(game)
    assert game.frame_errors == {}
    assert not region_differs(game, untouched)


# -- level change, gmap crossing --------------------------------------------------------

def test_level_change_mid_run(make_game):
    game = make_game(npcs=[IMAGE_NPC], chests=[(10, 10, False)],
                     items=[(14.0, 14.0, 0)],
                     extra_levels={"other.nw": _flat(3)})
    game.frames(3)
    capture(game, "before")
    c = game.client
    before = game.last_frame

    async def warp(world, level, x, y):
        await world.me.warp(level, x, y)
    game.server.run(lambda w: warp(w, "other.nw", 20.0, 20.0))
    game.frames(5)
    capture(game, "other")
    assert c._current_level_name == "other.nw"
    assert c.tiles[0] == 3
    assert 101 not in {n for n, v in c.npcs.items()
                       if v.get("_level") == "other.nw"}
    assert game.frame_errors == {}
    assert (pygame.image.tobytes(game.last_frame, "RGB")
            != pygame.image.tobytes(before, "RGB"))
    # And back.
    game.server.run(lambda w: warp(w, "fixture.nw", 30.0, 30.0))
    game.frames(5)
    capture(game, "back")
    assert c._current_level_name == "fixture.nw"
    assert game.frame_errors == {}


def test_gmap_segment_crossing_mid_run(make_game):
    game = make_game(gmap=True, player_xy=(62.0, 30.0),
                     npcs=[NAMED_NPC], bombs=[(31.0, 31.0)])
    c = game.client
    game.frames(3)
    capture(game, "start")
    assert c._current_level_name == GMAP_SEGMENTS[0]
    # Walk east across the seam through the client's own move path.
    for step in range(12):
        c.move(1, 0, step=0.5)
        game.frames(1)
        if step in (3, 11):
            capture(game, f"step{step + 1}")
    assert c.x > 64
    assert c._current_level_name == GMAP_SEGMENTS[1]
    game.frames(5)
    capture(game, "crossed")
    assert game.frame_errors == {}
    # What the server says about the crossing: let it handle what the client
    # sent while walking, then confirm with its own warp.
    game.server.pump()
    game.frames(5)
    assert c._current_level_name == GMAP_SEGMENTS[1]
    assert game.frame_errors == {}


def test_gmap_walk_across_every_seam(make_game):
    """A loop through all four segments: every seam is crossed, and the walk
    ends where it started (no seam swallowed or doubled a step)."""
    game = make_game(gmap=True, player_xy=(30.0, 62.0))
    c = game.client
    seen = set()
    for leg, (dx, dy) in enumerate(((0, 1), (1, 0), (0, -1), (-1, 0))):
        for step in range(140):
            c.move(dx, dy, step=0.5)
            game.frames(1)
            seen.add(c._current_level_name)
            if step in (69, 139):
                capture(game, f"leg{leg}/step{step + 1}")
    assert game.frame_errors == {}
    assert seen == set(GMAP_SEGMENTS)
    assert (c.x, c.y) == (30.0, 62.0)
    assert c._current_level_name == GMAP_SEGMENTS[0]


# -- death and respawn ---------------------------------------------------------------------

def test_death_then_respawn(make_game):
    from pygserver.protocol.constants import PLPROP
    game = make_game(npcs=[NAMED_NPC], hearts=3.0)
    game.frames(3)
    capture(game, "alive")
    c = game.client

    async def set_hearts(world, hearts):
        world.me.hearts = hearts
        await world.me.send_props({PLPROP.CURPOWER: int(hearts * 2)})
    game.server.run(lambda w: set_hearts(w, 0))
    assert c.player.hearts == 0
    game.frames(30)                     # past the death status delay
    capture(game, "dead")
    assert game._death_started is not None
    assert game.current_anim_name == "dead"
    game.server.run(lambda w: set_hearts(w, 3))
    game.frames(10)
    capture(game, "respawned")
    assert c.player.hearts > 0
    assert game._death_started is None
    assert game.frame_errors == {}


def test_death_then_revive_on_input(make_game):
    game = make_game(hearts=0.0)
    game.frames(5)
    # REVIVAL_INPUT_DELAY has to pass, then a held key revives.
    held = {k: True for k in (pygame.K_UP,)}

    class Keys:
        def __getitem__(self, key):
            return held.get(key, False)

        def __len__(self):
            return 512

    real = pygame.key.get_pressed
    pygame.key.get_pressed = lambda: Keys()
    try:
        game.frames(240)
    finally:
        pygame.key.get_pressed = real
    assert game.client.player.hearts > 0
    assert game.frame_errors == {}


# -- window resize ----------------------------------------------------------------------------

@pytest.mark.parametrize("size", [(800, 600), (1280, 720), (640, 480),
                                  (1920, 1080), (200, 150)])
def test_window_resize(make_game, size):
    game = make_game(npcs=[NAMED_NPC], players=[
        {"id": 5, "x": 20.0, "y": 20.0, "nickname": "Bob"}])
    game.frames(2)
    game.viewport.handle_resize(*size)
    game.frames(1, events=[pygame.event.Event(pygame.VIDEORESIZE,
                                              size=size, w=size[0], h=size[1])])
    game.frames(4)
    capture(game, "resized")
    assert game.frame_errors == {}
    assert game.screen.get_size() == game.viewport.canvas.get_size() == size
    # The player is still drawn at the centre of the new canvas.
    rect = world_rect(game, game.client.x, game.client.y, 3, 3)
    assert rect.width > 0 and rect.collidepoint(size[0] // 2, size[1] // 2)


def test_window_resize_with_overlays_open(make_game):
    game = make_game(gmap=True)
    game.frames(1, events=[key_event(K_F9)])
    game.frames(1, events=[key_event(K_F7)])
    for size in ((900, 700), (500, 400), (1100, 800)):
        game.viewport.handle_resize(*size)
        game.frames(3)
        assert game.screen.get_size() == size
    assert game.frame_errors == {}
    # The open settings panel owns the keys, so F7 does not open the list.
    assert game.settings_ui.visible and not game.show_player_list


# -- the fixture itself ---------------------------------------------------------------------

def test_a_raising_render_pass_fails_the_test(make_game):
    game = make_game()

    def boom(*args, **kwargs):
        raise RuntimeError("render pass blew up")

    game._render_player = boom
    with pytest.raises(RuntimeError, match="blew up"):
        game.frames(1)


def test_a_raising_render_pass_is_counted_in_production_mode(make_game):
    game = make_game()
    game._render_player = lambda *a, **k: 1 / 0
    game.step(1 / 60, strict=False)
    assert game.frame_errors, "frame_errors is the signal the tests assert on"


def test_make_client_has_no_game_and_the_same_world(make_client):
    client = make_client(npcs=[IMAGE_NPC], chests=[(10, 10, False)],
                         gmap=True, gmap_segment=(0, 1))
    assert client._current_level_name == GMAP_SEGMENTS[2]
    assert 101 in client.npcs and client.chests[GMAP_SEGMENTS[2]][(10, 10)] is False
    assert not hasattr(client, "screen")


def test_two_builds_of_one_scene_draw_identical_frames(make_game):
    """The clock, random and assets are pinned: the same knobs give the same
    pixels, which is what makes every with/without probe above exact."""
    knobs = {"npcs": [IMAGE_NPC, GANI_NPC, NAMED_NPC],
             "players": [{"id": 5, "x": 20.0, "y": 20.0, "nickname": "Bob"}],
             "bombs": [(36.0, 36.0)], "flying": [(40.0, 34.0, 1, 2)],
             "baddies": [{"x": 40.0, "y": 40.0, "type": 1}]}
    a, b = make_game(**knobs), make_game(**knobs)
    a.frames(20)
    b.frames(20)
    assert changed_pixels(a, b) == 0


def test_one_failing_shutdown_does_not_leave_other_servers_open():
    """The teardown loop closes every game's server even when one game's
    shutdown (or server.close) raises, and still reports the first failure."""
    class Game:
        def __init__(self, fail_shutdown=False, fail_close=False):
            self.fail_shutdown, self.fail_close = fail_shutdown, fail_close
            self.shut = self.closed = False
            self.server = self

        def shutdown(self, remember_window=True):
            self.shut = True
            if self.fail_shutdown:
                raise RuntimeError("shutdown failed")

        def close(self):
            self.closed = True
            if self.fail_close:
                raise OSError("close failed")

    real_quit = pygame.quit
    games = [Game(fail_shutdown=True), Game(fail_close=True), Game(), Game()]
    with pytest.raises(RuntimeError, match="shutdown failed"):
        offline_game.shutdown_games(games)
    assert all(g.shut and g.closed for g in games)
    assert pygame.quit is real_quit


def test_a_game_whose_start_raises_is_registered_for_teardown(
        _offline_env, tmp_path, monkeypatch):
    """make_game passes ``register``: the game is handed over before start()
    runs, so a start() that raises still leaves it in the teardown list."""
    registered = []
    monkeypatch.setattr(GameClient, "start", lambda self: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        offline_game.build_game(root=tmp_path / "w", register=registered.append)
    assert len(registered) == 1
    game = registered[0]
    real_quit, pygame.quit = pygame.quit, lambda: None
    try:
        game.shutdown(remember_window=False)
    finally:
        pygame.quit = real_quit
        game.server.close()


def _prop_ids(table, data, pos=0):
    from reborn_protocol.props import payload_len
    ids = []
    while pos < len(data):
        prop_id = data[pos] - 32
        ids.append(prop_id)
        pos += 1 + payload_len(table[prop_id], data, pos + 1, 5)
    return ids


def test_an_item_present_before_login_is_not_sent_on_entry(make_client):
    """The reference server never sends a level's ground items to a player
    who enters (GServer-v2 Level.cpp:2430 is the only level-item send, at
    creation). The item exists in the in-process world BEFORE the login, so
    the recorded entry stream must hold no PLO_ITEMADD and the client no item.

    Falsifiable: if pygserver restored `ItemManager.send_level_items`
    (pygserver/items.py, the per-item build_item_add loop on level entry) the
    stream would carry the packet and both assertions fail. The `items=` knob
    cannot test that, because it creates its item after login."""
    client = make_client(preplaced_items=[(14.0, 14.0, 0)])
    held = []

    async def server_items(world):
        held.extend(world.server.item_manager.get_items_on_level(
            world.me.level.name))
    client.server.run(server_items)
    assert len(held) == 1                                 # it is in the world
    ids = [packet_id for packet_id, _ in client._protocol.received]
    assert PacketID.PLO_LEVELNAME in ids                  # we did enter
    assert PacketID.PLO_ITEMADD not in ids
    assert not any(client.items.values())


def test_fixture_stream_is_what_pygserver_sends(make_client):
    """The packets reach the client in pygserver's own order and shapes,
    because pygserver produced them: the gmap entry order (warp, level send,
    mod time, NPC delta, and no item on entry), our login props
    (no position, the gear in its biased form), other players' X2/Y2 with
    the gmap and its grid cell, and the NPC position/sprite props."""
    from reborn_protocol.props import NPC_PROPS, PLAYER_PROPS
    client = make_client(gmap=True, gmap_segment=(1, 0), npcs=[NAMED_NPC],
                         players=[{"id": 5, "x": 20.0, "y": 20.0,
                                   "nickname": "Bob"}],
                         signs=[(5, 5, "hi")], items=[(14.0, 14.0, 0)])
    stream = client._protocol.received
    ids = [packet_id for packet_id, _ in stream]
    names = [(packet_id, data) for packet_id, data in stream
             if packet_id == PacketID.PLO_LEVELNAME]
    seg = GMAP_SEGMENTS[1].encode()
    entry = ids.index(PacketID.PLO_LEVELNAME)
    assert names[0][1] == seg
    # A login is a server warp: PLAYERWARP2 first, then the full level send
    # (server-spec.md 1.7: LEVELNAME(sub), the empty LEVELBOARD of a first
    # load, the board, signs, LEVELMODTIME, LEVELNAME(gmap)), then the delta
    # block (NPCs between SETACTIVELEVELs, then the player exchange).
    assert ids[entry:entry + 4] == [
        PacketID.PLO_LEVELNAME, PacketID.PLO_LEVELBOARD,
        PacketID.PLO_RAWDATA, PacketID.PLO_BOARDPACKET]
    warp = ids.index(PacketID.PLO_PLAYERWARP2)
    gmap_name = next(i for i, (pid, data) in enumerate(stream)
                     if pid == PacketID.PLO_LEVELNAME and data == GMAP_NAME.encode())
    sign = ids.index(PacketID.PLO_LEVELSIGN)
    modtime = ids.index(PacketID.PLO_LEVELMODTIME)
    npc = ids.index(PacketID.PLO_NPCPROPS)
    assert warp < entry < ids.index(PacketID.PLO_BOARDPACKET) < sign
    assert sign < modtime < gmap_name < npc
    # The server sends no ground item to a player who enters: the add packet
    # comes when the item is created, after the whole entry (GServer-v2
    # Level.cpp:2430 is the only level-item send).
    assert ids.count(PacketID.PLO_ITEMADD) == 1
    assert ids.index(PacketID.PLO_ITEMADD) > max(
        i for i, pid in enumerate(ids[:-1]) if pid == PacketID.PLO_OTHERPLPROPS)

    own = [data for pid, data in stream if pid == PacketID.PLO_PLAYERPROPS][0]
    own_ids = set(_prop_ids(PLAYER_PROPS, own))
    p = {name: _player_prop_id(name) for name in (
        "X", "Y", "X2", "Y2", "GANI", "CURLEVEL", "SWORDPOWER", "SHIELDPOWER",
        "GMAPLEVELX", "GMAPLEVELY")}
    assert not own_ids & {p["X"], p["Y"], p["X2"], p["Y2"], p["GANI"],
                          p["CURLEVEL"]}
    assert {p["SWORDPOWER"], p["SHIELDPOWER"]} <= own_ids
    sword_at = own.index(bytes([32 + p["SWORDPOWER"]]))
    assert own[sword_at + 1] - 32 >= 30          # power + 30, then the image

    other = [data for pid, data in stream if pid == PacketID.PLO_OTHERPLPROPS][0]
    other_ids = set(_prop_ids(PLAYER_PROPS, other, pos=2))
    assert {p["X2"], p["Y2"], p["GMAPLEVELX"], p["GMAPLEVELY"],
            p["CURLEVEL"], p["SWORDPOWER"], p["SHIELDPOWER"]} <= other_ids
    assert not other_ids & {p["X"], p["Y"]}
    assert GMAP_NAME.encode() in other

    npc = [data for pid, data in stream if pid == PacketID.PLO_NPCPROPS][0]
    npc_ids = set(_prop_ids(NPC_PROPS, npc, pos=3))
    want = {d.id for d in NPC_PROPS.values()
            if d.name in ("IMAGE", "X", "Y", "X2", "Y2", "SPRITE",
                          "GLOVEPOWER")}
    assert want <= npc_ids


def _player_prop_id(name):
    from reborn_protocol.props import PLAYER_PROPS
    return next(d.id for d in PLAYER_PROPS.values() if d.name == name)


def test_no_from_time_import_escapes_the_fixture_clock():
    """The fixture clock patches the ``time`` module, so a ``from time import
    time`` binding in the client would read the wall clock."""
    root = Path(__file__).resolve().parents[2] / "pyreborn"
    pattern = re.compile(r"^\s*from\s+time\s+import\s", re.M)
    offenders = [str(p.relative_to(root)) for p in root.rglob("*.py")
                 if pattern.search(p.read_text(encoding="utf-8",
                                                errors="replace"))]
    assert offenders == []


def test_scene_assets_are_synthetic(make_game):
    """Bodies, heads and NPC images come from the fixture's generated
    content tier, never from the developer's machine or the gitignored
    bundled art."""
    game = make_game(npcs=[IMAGE_NPC])
    content = Path(__import__("os").environ["PYREBORN_CONTENT_DIR"])
    for name in ("body.png", "head0.png", "pics1.png", "dustynewpics1.png"):
        assert game.sprite_mgr.find_file(name).parent == content
    assert game.gani_parser.find_file("idle").parent == content / "ganis"
    bundled = game.sprite_mgr.search_paths[-1]
    assert sorted(p.name for p in bundled.iterdir()) == sorted(
        offline_game.TRACKED_BUNDLED)
