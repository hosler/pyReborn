"""Characterization of the pygame client's input routing over its overlays.

For every overlay alone, and for every pair of overlays open together, each
event of a representative set (Escape, Return, letters, arrows, every F-key
the client binds, the overlays' own toggle keys, mouse clicks inside and
outside the centred panels, wheel and motion) is fed through the real
``GameClient._handle_events`` of an offline game (tests/offline_game.py).
The outcome records which handler took the event, the resulting open/closed
state of every overlay, whether held-key movement is gated afterwards, and the
gameplay state an event can change (quit request, just-pressed keys, the GS1
keypress queue, ...).

The table was recorded from the routing as it stood before the overlay stack
(game/overlays.py) replaced the hand-kept chains, and the routing must keep
producing it. Record it again only for a deliberate routing change, with
``PYREBORN_RECORD_OVERLAY_ROUTING=1``, and say in the commit which cases moved
and why.

The rest of the file covers the stack itself and the keymap (game/keymap.py).
Draw order is the reverse of input priority: the pixel tests open two
overlays that overlap and compare the finished frame with one composed by
hand (the lower overlay's frame, then the upper overlay's own draw call on top
of it). Translucent panels composite differently in the other order, and each
test also proves that the other order gives a different frame, so a probe that
cannot tell the two apart fails instead of passing vacuously.
"""

import json
import os
import time
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest
from pygame.locals import (
    K_0, K_BACKSPACE, K_DOWN, K_ESCAPE, K_F1, K_F2, K_F7, K_F8, K_F9, K_F10,
    K_F11, K_F12, K_LEFT, K_PAGEDOWN, K_PAGEUP, K_RETURN, K_RIGHT, K_SPACE,
    K_TAB, K_UP, K_a, K_d, K_h, K_m, K_n, K_p, K_q, K_s, K_x)
from reborn_protocol import PLSTATUS

from offline_game import _running, changed_pixels, key_event
from pyreborn.game import input as input_module
from pyreborn.game import keymap, overlays
from pyreborn.game.hud import HUD

SNAPSHOT = Path(__file__).resolve().parents[1] / "fixtures" / "overlay_routing.json"
RECORD = os.environ.get("PYREBORN_RECORD_OVERLAY_ROUTING") == "1"

PM_PEER = {"id": 5, "x": 20.0, "y": 20.0, "nickname": "Bob"}
DIALOGUE = ("A sign says something long enough to wrap across more than one "
            "line of the dialogue box so the pager has pages to turn, and "
            "then some more words so there is a second page to scroll to, "
            "and a third line after that for good measure.")


# -- opening each overlay --------------------------------------------------------

def _gs2_window(game):
    """A GS2 window holding a text edit, built once per game; the opener
    shows it and clicks the edit so it holds keyboard focus."""
    made = getattr(game, "_routing_gs2", None)
    if made is None:
        host = game.gs2.host
        win = host.create_object("GuiWindowCtrl", "routing_dlg")
        win.x, win.y, win.width, win.height = 0, 0, 200, 100
        edit = host.create_object("GuiTextEditCtrl", "routing_field")
        edit.x, edit.y, edit.width, edit.height = 10, 40, 120, 20
        host.call_builtin(None, "addcontrol", [edit])
        host.call_builtin(None, "addcontrol", [win])
        made = game._routing_gs2 = (win, edit)
    return made


def _open_gs2(game):
    win, edit = _gs2_window(game)
    gui = game.gs2.gui
    gui.show(win)
    edit.text = ""
    pos = (int(win.x) + 15, int(win.y) + 45)     # inside the edit
    gui.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                        pos=pos, button=1))
    gui.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP,
                                        pos=pos, button=1))
    assert gui.keyboard_captured


def _open_server_warp(game):
    # Armed: opened longer ago than SERVER_WARP_ARM_SECONDS, so typed keys
    # land in the prompt's field.
    game.server_warp_prompt = {
        "name": "Other", "host": "10.9.9.9", "port": 14999, "in_list": False,
        "opened_at": game.clock.frame_now() - 10.0, "typed": "",
    }


def _open_editor(game):
    game.level_editor.state.enabled = True


OPENERS = {
    "server_warp": _open_server_warp,
    "gs2_gui": _open_gs2,
    "rc": lambda g: setattr(g.rc_ui, "visible", True),
    "dev": lambda g: setattr(g.dev_ui, "visible", True),
    "editor": _open_editor,
    "pm": lambda g: setattr(g, "pm_target_id", PM_PEER["id"]),
    "player_list": lambda g: setattr(g, "show_player_list", True),
    "server_list": lambda g: setattr(g, "show_server_list", True),
    "settings": lambda g: setattr(g.settings_ui, "visible", True),
    "big_map": lambda g: setattr(g, "big_map_visible", True),
    "chat": lambda g: setattr(g, "typing", True),
    "dialogue": lambda g: g._show_dialogue(DIALOGUE),
    "inventory": lambda g: setattr(g.inventory_ui, "visible", True),
    "help": lambda g: setattr(g, "show_help", True),
    "debug": lambda g: setattr(g, "debug_mode", True),
}


def _state(game):
    """Every overlay's open/closed state plus the gameplay state an event can
    change: (the set of flags that are on, the non-default extras)."""
    gui = game.gs2.gui
    win, _edit = _gs2_window(game)
    editor = game.level_editor.state
    flags = {
        "server_warp": game.server_warp_prompt is not None,
        "gs2_gui": bool(win.visible),
        "gs2_focus": gui.keyboard_captured,
        "rc": game.rc_ui.visible,
        "dev": game.dev_ui.visible,
        "editor": editor.enabled,
        "palette": editor.palette_visible,
        "pm": game.pm_target_id is not None,
        "player_list": game.show_player_list,
        "server_list": game.show_server_list,
        "settings": game.settings_ui.visible,
        "big_map": game.big_map_visible,
        "chat": game.typing,
        "dialogue": game.dialogue_text is not None,
        "inventory": game.inventory_ui.visible,
        "help": game.show_help,
        "debug": game.debug_mode,
        "noclip": game.noclip,
        "paused": bool(game.client.player.status & PLSTATUS.PAUSED),
        "quit": not game.running,
        "switch": game.switch_server is not None,
    }
    extra = {
        "chat": repr(game.chat_input) if game.chat_input else "",
        "pm": repr(game.pm_input) if game.pm_input else "",
        "typed": repr((game.server_warp_prompt or {}).get("typed", "")),
        "scroll": str(game.chat_scroll) if game.chat_scroll else "",
        "zoom": f"{game.camera.zoom:.3f}" if game.camera.zoom != 1.0 else "",
        "jp": ",".join(str(k) for k in sorted(game.key_just_pressed)),
        "gs1q": ",".join(str(k) for k, _ in game._gs1_keypress_queue),
    }
    if extra["typed"] == "''":
        extra["typed"] = ""
    return ({k for k, v in flags.items() if v},
            "|".join(f"{k}={v}" for k, v in extra.items() if v))


# -- the events ------------------------------------------------------------------

def _click(pos):
    return [pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1),
            pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=1)]


def _centre(game):
    w, h = game.screen.get_size()
    return (w // 2, h // 2)


EVENTS = {
    **{name: (lambda game, k=k, u=u: [key_event(k, u)]) for name, k, u in (
        ("Escape", K_ESCAPE, "\x1b"), ("Return", K_RETURN, "\r"),
        ("a", K_a, "a"), ("s", K_s, "s"), ("d", K_d, "d"), ("q", K_q, "q"),
        ("m", K_m, "m"), ("h", K_h, "h"), ("n", K_n, "n"), ("x", K_x, "x"),
        ("p", K_p, "p"), ("0", K_0, "0"), ("Space", K_SPACE, " "),
        ("Up", K_UP, ""), ("Down", K_DOWN, ""), ("Left", K_LEFT, ""),
        ("Right", K_RIGHT, ""), ("Tab", K_TAB, "\t"),
        ("Backspace", K_BACKSPACE, "\b"), ("PageUp", K_PAGEUP, ""),
        ("PageDown", K_PAGEDOWN, ""),
        ("F1", K_F1, ""), ("F2", K_F2, ""), ("F7", K_F7, ""),
        ("F8", K_F8, ""), ("F9", K_F9, ""), ("F10", K_F10, ""),
        ("F11", K_F11, ""), ("F12", K_F12, ""))},
    "click_centre": lambda game: _click(_centre(game)),
    "click_corner": lambda game: _click((4, 4)),
    "wheel": lambda game: [pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1,
                                              flipped=False)],
    "motion": lambda game: [pygame.event.Event(
        pygame.MOUSEMOTION, pos=_centre(game), rel=(1, 1), buttons=(0, 0, 0))],
}


# -- one case ----------------------------------------------------------------------

class _Reached(Exception):
    """Raised by the stand-in _feed_gs1_input: held keys reached gameplay."""


def _wrap(calls, owner, name, label, only_true=False):
    original = getattr(owner, name)

    def wrapper(*args, **kwargs):
        result = original(*args, **kwargs)
        if not only_true or result:
            calls.append(label)
        return result
    setattr(owner, name, wrapper)


def _reset(game, calls):
    """Close everything and put the gameplay state back, then wrap every
    handler the routing can hand an event to so the case can see who took it."""
    from pyreborn.game.dev_ui import DevOverlay
    from pyreborn.game.editor import EditorOverlay, LevelEditor, TilePalette
    from pyreborn.game.rc_ui import RCOverlay

    for name in ("_handle_server_warp_key", "_gs2_gui_event",
                 "_handle_pm_input", "_handle_player_list_key",
                 "_handle_server_list_key", "_handle_chat_input",
                 "_advance_dialogue", "_handle_key_press",
                 "_feed_gs1_input"):
        vars(game).pop(name, None)

    game.running = True
    game.switch_server = None
    game.server_warp_prompt = None
    game.rc_ui = RCOverlay(game)
    game.dev_ui = DevOverlay(game)
    game.level_editor = LevelEditor(game)
    game.tile_palette = TilePalette(game)
    game.editor_overlay = EditorOverlay(game, game.level_editor)
    game.pm_target_id = None
    game.pm_input = ""
    game.show_player_list = False
    game.player_list_sel = 0
    game.show_server_list = False
    game.server_list_sel = 0
    game.servers = [SimpleNamespace(name="Other", display_name="Other",
                                    ip="10.9.9.9", port=14999,
                                    player_count=1)]
    game.settings_ui.visible = False
    game.settings_ui.selected = 0
    game.big_map_visible = False
    game.typing = False
    game.chat_input = ""
    game._dismiss_dialogue()
    game.inventory_ui.visible = False
    game.inventory_ui.selected_weapon_idx = 0
    game.show_help = False
    game.debug_mode = False
    game.noclip = False
    game.chat_scroll = 0
    game._chat_scroll_baseline = 0
    game.camera.zoom = 1.0
    game.client.player.status &= ~PLSTATUS.PAUSED
    game.key_just_pressed.clear()
    game._gs1_keypress_queue.clear()
    game._level_transition_input_frozen = False
    if getattr(game.client, "local_level_transition", ""):
        game.client.release_local_transition()
    win, _edit = _gs2_window(game)
    game.gs2.gui.hide(win)
    game._frozen_until = 0.0

    _wrap(calls, game, "_handle_server_warp_key", "server_warp")
    _wrap(calls, game, "_gs2_gui_event", "gs2_gui", only_true=True)
    _wrap(calls, game.rc_ui, "handle_key", "rc")
    _wrap(calls, game.dev_ui, "handle_key", "dev")
    _wrap(calls, game.level_editor, "handle_key", "editor_key", only_true=True)
    _wrap(calls, game.level_editor, "handle_mouse", "editor_mouse",
          only_true=True)
    _wrap(calls, game, "_handle_pm_input", "pm")
    _wrap(calls, game, "_handle_player_list_key", "player_list")
    _wrap(calls, game, "_handle_server_list_key", "server_list")
    _wrap(calls, game.settings_ui, "handle_key", "settings")
    _wrap(calls, game, "_handle_chat_input", "chat")
    _wrap(calls, game, "_advance_dialogue", "dialogue_advance")
    _wrap(calls, game.dialogue_pager, "scroll", "dialogue_scroll")
    _wrap(calls, game.inventory_ui, "handle_key", "inventory_key")
    _wrap(calls, game.inventory_ui, "handle_mouse_motion", "inventory_motion")
    _wrap(calls, game.inventory_ui, "handle_click", "inventory_click")
    _wrap(calls, game, "_handle_key_press", "gameplay")
    _wrap(calls, game.camera, "zoom_by", "zoom")

    def feed(keys):
        raise _Reached
    game._feed_gs1_input = feed


def _unwrap(game):
    for owner, names in (
            (game.settings_ui, ("handle_key",)),
            (game.dialogue_pager, ("scroll",)),
            (game.inventory_ui, ("handle_key", "handle_mouse_motion",
                                 "handle_click")),
            (game.camera, ("zoom_by",))):
        for name in names:
            vars(owner).pop(name, None)


def run_case(game, opened, event_name):
    calls = []
    with _running(game):
        _reset(game, calls)
        for name in opened:
            OPENERS[name](game)
        before, _ = _state(game)
        pygame.event.clear()
        for event in EVENTS[event_name](game):
            pygame.event.post(event)
        try:
            game._handle_events()
        finally:
            _unwrap(game)
        after, extra = _state(game)
        try:
            game._handle_input(game.clock.sim_now())
            gated = True
        except _Reached:
            gated = False
    delta = ",".join([f"+{k}" for k in sorted(after - before)]
                     + [f"-{k}" for k in sorted(before - after)])
    return f"{'>'.join(calls) or '-'}|gated={gated}|{delta}|{extra}"


def scenarios():
    names = list(OPENERS)
    yield ()
    for name in names:
        yield (name,)
    for pair in combinations(names, 2):
        yield pair


def characterize(game):
    out = {}
    for opened in scenarios():
        for event_name in EVENTS:
            key = f"{'+'.join(opened) or 'none'}/{event_name}"
            out[key] = run_case(game, opened, event_name)
    return out


def _compact(table):
    outcomes = sorted(set(table.values()))
    index = {o: i for i, o in enumerate(outcomes)}
    return {"outcomes": outcomes,
            "cases": {k: index[v] for k, v in sorted(table.items())}}


def _expand(data):
    return {k: data["outcomes"][i] for k, i in data["cases"].items()}


def test_input_routing_matches_the_recorded_table(make_game):
    game = make_game(players=[PM_PEER])
    game.frames(1)
    table = characterize(game)
    assert game.frame_errors == {}
    if RECORD:
        SNAPSHOT.write_text(json.dumps(_compact(table), indent=0,
                                       sort_keys=True) + "\n")
        pytest.skip(f"recorded {len(table)} cases into {SNAPSHOT}")
    expected = _expand(json.loads(SNAPSHOT.read_text()))
    assert set(table) == set(expected), "the case list changed"
    moved = {k: (expected[k], table[k]) for k in table
             if table[k] != expected[k]}
    assert not moved, (
        f"{len(moved)} routing cases changed; first few:\n" + "\n".join(
            f"{k}\n  was {a}\n  now {b}" for k, (a, b) in
            sorted(moved.items())[:8]))


def test_every_overlay_is_characterized_alone_and_in_pairs():
    cases = list(scenarios())
    n = len(OPENERS)
    assert len(cases) == 1 + n + n * (n - 1) // 2


# -- the list itself -------------------------------------------------------------

#: Input priority, topmost first, as the hand-written chain in
#: game/input.py had it before the stack (plus where the passive layers sit
#: in the draw order).
EXPECTED_ORDER = [
    "server_warp", "gs2_gui", "debug_hud", "hud_notice", "rc_tools",
    "dev_tools", "level_editor", "pm", "player_list", "server_list",
    "settings", "big_map", "level_editor_pointer", "help", "chat",
    "dialogue", "inventory",
]


def test_the_stack_order(make_game):
    game = make_game()
    assert [o.name for o in game.overlays] == EXPECTED_ORDER


@pytest.mark.parametrize("opener", [pygame.K_RETURN, pygame.K_q])
def test_a_key_an_overlay_consumes_is_never_latched_for_gameplay(
        make_game, opener):
    """Chat and the inventory take the keys typed into them: none of them
    is latched for the next tick (only the opener reached gameplay, and the
    overlay opening dropped it)."""
    game = make_game()
    game.frames(1, events=[key_event(opener)])
    assert game._overlays_capture_keys()
    game.frames(1, dt=0.0, events=[key_event(pygame.K_SPACE, " "),
                                   key_event(pygame.K_a, "a"),
                                   key_event(pygame.K_RIGHT)])
    assert game.key_just_pressed == {}


def test_hud_draws_the_stack_bottom_up(make_game, monkeypatch):
    game = make_game()
    game.frames(1)
    drawn = []
    for o in game.overlays:
        monkeypatch.setattr(o, "draw", lambda surf, n=o.name: drawn.append(n))
    with _running(game):
        game.hud.draw()
    assert drawn == list(reversed(EXPECTED_ORDER))


def test_death_presentation_hides_the_hud_entries_only(make_game, monkeypatch):
    game = make_game(hearts=0)
    game.frames(30)
    assert game.combat_presentation.death_started is not None
    drawn = []
    for o in game.overlays:
        monkeypatch.setattr(o, "draw", lambda surf, n=o.name: drawn.append(n))
    with _running(game):
        game.hud.draw()
    assert drawn == ["inventory", "debug_hud", "gs2_gui"]


def test_movement_gate_and_named_close_read_the_stack(make_game):
    game = make_game()
    game.frames(1)
    assert not game._overlays_capture_keys()
    game.show_player_list = True
    game.settings_ui.visible = True
    assert game._overlays_capture_keys()
    game._close_overlays("player_list", "settings")
    assert not game.show_player_list and not game.settings_ui.visible
    # Edit mode and the help overlay never gate movement.
    game.level_editor.state.enabled = True
    game.show_help = True
    assert not game._overlays_capture_keys()


# -- draw order with two overlays open ---------------------------------------------

def _open(game, names):
    with _running(game):
        for name in names:
            OPENERS[name](game)


def _centre_gs2_window(game):
    """Move the routing test's GS2 window over the centred panels; it stays
    hidden until its opener shows it."""
    win, _edit = _gs2_window(game)
    sw, sh = game.screen.get_size()
    win.x, win.y, win.width, win.height = sw // 2 - 150, sh // 2 - 100, 300, 200
    game.gs2.gui.hide(win)


def _setup(name):
    return {"gs2_gui": _centre_gs2_window}.get(name, lambda game: None)


#: (lower, upper, draw the upper overlay onto a surface, draw the lower one).
#: `upper` takes the keys first, so it must be drawn on top.
PAIRS = {
    "rc panel over inventory": (
        "inventory", "rc",
        lambda g, s: g.rc_ui.draw(s),
        lambda g, s: _inventory_onto(g, s)),
    "server-warp prompt over GS2 window": (
        "gs2_gui", "server_warp",
        lambda g, s: g.hud._draw_server_warp_prompt(s),
        lambda g, s: g.gs2.gui.render(s, g.fonts, g.sprite_mgr)),
    "player list over settings": (
        "settings", "player_list",
        lambda g, s: g.hud._draw_player_list(s),
        lambda g, s: g.hud._draw_settings(s)),
    "dialogue over inventory": (
        "inventory", "dialogue",
        lambda g, s: g.hud._draw_dialogue(s),
        lambda g, s: _inventory_onto(g, s)),
}


def _inventory_onto(game, surf):
    ui = game.inventory_ui
    screen, ui.screen = ui.screen, surf
    try:
        ui.render(game.client.player, game.client.weapons)
    finally:
        ui.screen = screen


def _frame_with(make_game, names, setup):
    game = make_game(players=[PM_PEER])
    game.frames(1)
    setup(game)
    _open(game, names)
    game.frames(2)
    return game


def _holder(surface):
    return SimpleNamespace(last_frame=surface)


@pytest.mark.parametrize("pair", sorted(PAIRS))
def test_the_overlay_that_takes_keys_first_is_drawn_on_top(make_game, pair):
    lower, upper, draw_upper, draw_lower = PAIRS[pair]
    setup = lambda g: (_setup(lower)(g), _setup(upper)(g))
    both = _frame_with(make_game, [lower, upper], setup)
    assert both.overlay(routing_name(lower)).visible
    assert both.overlay(routing_name(upper)).visible

    # the lower overlay alone, with the upper one's draw on top
    only_lower = _frame_with(make_game, [lower], setup)
    expected = only_lower.last_frame.copy()
    with _running(only_lower):
        _open(only_lower, [upper])
        draw_upper(only_lower, expected)

    # the upper overlay alone, with the lower one's draw on top: the old,
    # reversed order
    only_upper = _frame_with(make_game, [upper], setup)
    reversed_order = only_upper.last_frame.copy()
    with _running(only_upper):
        _open(only_upper, [lower])
        draw_lower(only_upper, reversed_order)

    assert changed_pixels(_holder(expected), _holder(reversed_order)) > 0, \
        "the two orders draw the same frame: this pair cannot show the order"
    assert changed_pixels(both, _holder(expected)) == 0, (
        f"{pair}: the frame with both open is not the {upper} overlay drawn "
        f"over the {lower} one")


def routing_name(opener):
    return {"rc": "rc_tools", "dev": "dev_tools"}.get(opener, opener)


# -- the routing snapshot is not blind --------------------------------------------

def _swapped(first, second):
    order = list(overlays.OVERLAY_TYPES)
    i, j = order.index(first), order.index(second)
    order[i], order[j] = order[j], order[i]
    return lambda game: [kind(game) for kind in order]


@pytest.mark.parametrize("first,second", [
    (overlays.RCTools, overlays.DevTools),
    (overlays.BigMap, overlays.LevelEditorPointer),
    (overlays.ChatInput, overlays.Dialogue),
    (overlays.ServerWarpPrompt, overlays.GS2Gui),
], ids=lambda kind: kind.name)
def test_routing_table_catches_a_reordered_stack(make_game, monkeypatch,
                                                  first, second):
    monkeypatch.setattr(input_module, "build_overlays", _swapped(first, second))
    game = make_game(players=[PM_PEER])
    game.frames(1)
    table = characterize(game)
    expected = _expand(json.loads(SNAPSHOT.read_text()))
    assert any(table[k] != expected[k] for k in table)


# -- the keymap --------------------------------------------------------------------

#: The help overlay as it was written out by hand before the keymap.
OLD_HELP_LINES = [
    ("Arrow Keys", "Move"),
    ("A", "Grab / Pick up / Throw"),
    ("S or Space", "Swing sword"),
    ("D", "Use weapon"),
    ("Q", "Inventory"),
    ("Wheel / 0", "Zoom / reset"),
    ("M", "Open map"),
    ("N", "Noclip (walk through walls)"),
    ("Enter", "Chat"),
    ("F1", "Debug / tile editor"),
    ("F2", "Unstick: warp to (30,30)"),
    ("F7", "Player list / PM"),
    ("F8", "Server list"),
    ("F9", "Settings"),
    ("F10", "RC tools (staff)"),
    ("F11", "Level edit mode (staff)"),
    ("F12", "Dev playground (staff)"),
    ("PageUp/Down", "Scroll chat log"),
    ("H", "Close this help"),
]


def test_help_lines_are_generated_with_the_old_wording():
    assert HUD.HELP_LINES == OLD_HELP_LINES
    assert keymap.help_lines() == OLD_HELP_LINES


#: GS1 keydown(i) index -> the keys that held it before the keymap.
OLD_GS1_KEYDOWN = {0: (K_UP,), 1: (K_LEFT,), 2: (K_DOWN,), 3: (K_RIGHT,),
                   4: (K_d,), 5: (K_s, K_SPACE), 6: (K_a,), 7: (K_m,),
                   8: (K_TAB,), 9: (K_q,)}


@pytest.mark.parametrize("key", sorted({k for keys in OLD_GS1_KEYDOWN.values()
                                        for k in keys} | {K_p, K_RETURN}))
def test_gs1_keydown_indices_unchanged(key):
    pressed = defaultdict(bool, {key: True})
    expected = {i for i, keys in OLD_GS1_KEYDOWN.items() if key in keys}
    assert keymap.gs1_keydown_indices(pressed) == expected


def test_press_actions_cover_the_old_press_keys():
    old = {K_p: "pause", K_ESCAPE: "back", K_RETURN: "chat", K_q: "inventory",
           K_0: "zoom_reset", K_F1: "debug", K_F2: "unstick",
           K_F7: "player_list", K_F8: "server_list", K_F9: "settings",
           K_F10: "rc_tools", K_F11: "level_editor", K_F12: "dev_tools",
           K_PAGEUP: "chat_scroll_back", K_PAGEDOWN: "chat_scroll_forward",
           K_h: "help", K_m: "map", K_n: "noclip"}
    for key, action in old.items():
        assert keymap.press_action(key) == action
    for key in (K_a, K_s, K_d, K_SPACE, K_UP, K_TAB):
        assert keymap.press_action(key) is None


def test_revive_and_dialogue_key_sets_unchanged():
    assert set(keymap.keys_for(*keymap.REVIVE_ACTIONS)) == {
        K_UP, K_LEFT, K_DOWN, K_RIGHT, K_a, K_s, K_d, K_SPACE}
    assert set(keymap.keys_for(*keymap.DIALOGUE_PASSTHROUGH)) == {
        K_F1, K_F2, K_F7, K_F8, K_F9, K_F10, K_F11, K_F12}
    assert keymap.keys_for("grab", "sword") == (K_a, K_s, K_SPACE)
