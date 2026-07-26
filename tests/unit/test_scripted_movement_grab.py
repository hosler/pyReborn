"""Regression tests: A = grab/interact under scripted movement, and the sign
popup radius under script-quantized movement.

Bomber v6 (disabledefmovement via -Test/Movement) exposed two dead sign paths,
live-verified on bomber.home.eevul.net:14915 (bomblobby.nw streams 3 real
PLO_LEVELSIGN signs, so the DATA was always there):

1. input.py's scripted-movement branch returned right after
   _scripted_movement_touch, so the one-shot A dispatch (_try_grab: sign read
   -> dialogue box, chests, doors, pickups) was unreachable — pressing A on a
   level sign did nothing. disabledefmovement only disables default MOVEMENT;
   grab stays a built-in.

2. _check_and_render_signs' proximity popup used a 2.0-tile feet-to-sign-
   centre radius, exactly reachable when the built-in _move() clamps flush —
   but the v6 movement script steps in 0.3-tile quanta and rests up to 0.29
   short of flush, putting the feet sample at up to ~2.3 (live-measured 2.2).
   Radius is now 2.35 (next tile row is a full 3.0 away, so no walkway
   false-positives).
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pygame

pygame.init()
pygame.display.set_mode((64, 64))  # _feed_gs1_input reads the mouse

from pygame.locals import K_a, K_UP

from pyreborn.game.dialogue import format_sign_text
from pyreborn.game.input import InputMixin
from pyreborn.game.render_objects import LevelObjectsRenderMixin


class FakeKeys:
    """pygame.key.get_pressed() stand-in: index with K_* constants."""

    def __init__(self, *held):
        self._held = set(held)

    def __getitem__(self, key):
        return key in self._held

    def __len__(self):
        return 512


class _FakePlayer:
    hearts = 3.0
    direction = 0
    x = 0.0
    y = 0.0


class _FakeClient:
    input_frozen = False
    _local_level_transition = ''

    def __init__(self):
        self.player = _FakePlayer()
        self.x = 0.0
        self.y = 0.0
        self.npcs = {}


class _FakeGS1:
    """Just what _feed_gs1_input/_handle_input touch."""

    default_movement = False

    def __init__(self):
        self.keys_dir = set()
        self.keys_raw = set()


class _FakeUI:
    visible = False


class _FakeViewport:
    """Native (canvas == window) viewport: _feed_gs1_input maps the mouse
    through window_to_virtual before handing it to the GS1 engine."""

    @staticmethod
    def window_to_virtual(wx, wy):
        return (float(wx), float(wy))


class _InputHarness(InputMixin):
    """Minimal GameClient stand-in driving the REAL _handle_input through its
    scripted-movement branch, with spies on the two dispatch targets."""

    def __init__(self):
        self.client = _FakeClient()
        self.gs1 = _FakeGS1()
        self.screen = pygame.Surface((640, 480))
        self.viewport = _FakeViewport()
        self.typing = False
        self.dialogue_text = None
        self.inventory_ui = _FakeUI()
        self.show_player_list = False
        self.show_server_list = False
        self.pm_target_id = None
        self.key_just_pressed = {}
        self.last_action_time = 0.0
        self.action_delay = 0.3
        self._gs1_keypress_queue = []
        self._vk_cache = {}
        self._frozen_until = 0.0
        self.is_moving = False
        self.grab_calls = 0
        self.touch_calls = 0

    # overlay/settings guards
    def _ensure_settings_ui(self):
        return _FakeUI()

    def _gs2_gui_captures_keys(self):
        return False

    # spies for the two scripted-branch dispatch targets
    def _scripted_movement_touch(self, keys):
        self.touch_calls += 1

    def _try_grab(self):
        self.grab_calls += 1


def _run_input(harness, keys, now=100.0):
    orig = pygame.key.get_pressed
    pygame.key.get_pressed = lambda: keys
    try:
        harness._handle_input(now)
    finally:
        pygame.key.get_pressed = orig


class TestScriptedMovementGrab:
    def test_fresh_a_press_dispatches_try_grab(self):
        h = _InputHarness()
        h.key_just_pressed[K_a] = True  # _handle_events saw KEYDOWN
        _run_input(h, FakeKeys(K_a))
        assert h.grab_calls == 1
        assert h.touch_calls == 1  # NPC-touch probe still runs

    def test_walk_into_and_press_dispatches_with_arrow_held(self):
        # The classic sign gesture: UP held into the sign, then press A.
        h = _InputHarness()
        h.key_just_pressed[K_a] = True
        _run_input(h, FakeKeys(K_a, K_UP))
        assert h.grab_calls == 1

    def test_held_a_without_fresh_press_does_not_refire(self):
        h = _InputHarness()
        # A is held but was pressed in some earlier frame (no just-pressed).
        _run_input(h, FakeKeys(K_a))
        assert h.grab_calls == 0

    def test_action_delay_cooldown_respected(self):
        h = _InputHarness()
        h.key_just_pressed[K_a] = True
        h.last_action_time = 100.0 - 0.1  # 0.1s ago < action_delay 0.3
        _run_input(h, FakeKeys(K_a), now=100.0)
        assert h.grab_calls == 0

    def test_dismissing_keystroke_does_not_reopen_sign(self):
        # Pressing A on the dialog's LAST page dismisses it in
        # _handle_events; that same keystroke must NOT count as a fresh
        # press for _try_grab in the same frame's _handle_input, or the
        # dialog instantly re-opens under a player still standing at the
        # sign (live: page-0 wrap-around forever, dialog undismissable).
        from pyreborn.game.dialogue import DialoguePager

        h = _InputHarness()
        h.settings_ui = _FakeUI()
        h.dialogue_text = "last page"
        h.dialogue_classic_font = False
        h.dialogue_pager = DialoguePager()
        h.dialogue_pager.replace("last page", lambda s: len(s), 100)

        # Real ActionsMixin dismissal semantics, minimal stand-ins.
        def _advance():
            if not h.dialogue_pager.advance():
                h.dialogue_text = None
        h._advance_dialogue = _advance

        pygame.event.clear()
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=K_a,
                                             unicode=""))
        h._handle_events()
        assert h.dialogue_text is None          # dialog closed
        assert K_a not in h.key_just_pressed    # keystroke consumed

        _run_input(h, FakeKeys(K_a))            # same frame: A still held
        assert h.grab_calls == 0                # no instant re-open

    def test_default_movement_path_unchanged(self):
        # Sanity: with default movement ON the scripted branch (and its
        # touch probe) must not run; A goes through the classic dispatch.
        h = _InputHarness()
        h.gs1.default_movement = True

        # The default path needs a few more collaborators; stub just enough.
        h.grab_state = None
        h._clear_grab_state = lambda: None
        h._update_grab_pull_state = lambda dx, dy: None
        h.key_just_pressed[K_a] = True
        _run_input(h, FakeKeys(K_a))
        assert h.touch_calls == 0
        assert h.grab_calls == 1


class _PopupHarness(LevelObjectsRenderMixin):
    def __init__(self, client):
        self.client = client
        self.popup_texts = []

    def _render_sign_popup(self, text):
        self.popup_texts.append(text)


def _popup_client(player_x, player_y):
    c = _FakeClient()
    c._current_level_name = "bomblobby.nw"
    c.gmap_grid = {}
    c.in_gmap_segment = False
    # sign tile at (20, 40) — the v6 piano-instructions sign
    c.signs = {"bomblobby.nw": {(20, 40): "Piano Playing Instructions"}}
    c.player.x = player_x
    c.player.y = player_y
    return c


class TestSignPopupScriptQuantizedRadius:
    def test_scripted_flush_rest_position_triggers_popup(self):
        # Scripted movement rests at y=40.2 below the sign (0.3-tile step
        # stops short of flush y=40.0): feet sample (x+1.5, y+2.5) =
        # (20.3, 42.7), 2.2 tiles from the sign centre (20.5, 40.5).
        h = _PopupHarness(_popup_client(18.8, 40.2))
        h._check_and_render_signs()
        assert h.popup_texts == ["Piano Playing Instructions"]

    def test_exact_flush_still_triggers(self):
        # Built-in movement clamps flush at y=40.0: feet distance exactly 2.0.
        h = _PopupHarness(_popup_client(18.8, 40.0))
        h._check_and_render_signs()
        assert h.popup_texts == ["Piano Playing Instructions"]

    def test_one_row_back_does_not_trigger(self):
        # A player one walkway row further (feet distance 3.0+) must not pop.
        h = _PopupHarness(_popup_client(18.8, 41.0))
        h._check_and_render_signs()
        assert h.popup_texts == []

    def test_popup_suppressed_while_dialogue_open(self):
        # The A-read dialogue box supersedes the proximity popup — both at
        # once double-displayed the same sign (live on bomber v6).
        h = _PopupHarness(_popup_client(18.8, 40.2))
        h.dialogue_text = "Piano Playing Instructions"
        h._check_and_render_signs()
        assert h.popup_texts == []


class TestFormatSignText:
    """Sign-code escape translation (semantics from GServer LevelSign.cpp)."""

    def test_chr_escape_is_raw_ascii(self):
        # encodeSignCode writes unknown chars as #K(<ascii code>).
        assert format_sign_text("eye#K(95)bomber#K(95)poni.png") == \
            "eye_bomber_poni.png"
        assert format_sign_text("#K(43)5 Win / #K(43)1 Lose") == \
            "+5 Win / +1 Lose"
        assert format_sign_text("#K(91)Enter#K(93)") == "[Enter]"

    def test_key_escape_uses_binding_names(self):
        # #k(n) = name of the key bound to control function n.
        assert format_sign_text("Press #k(4) to place a bomb.") == \
            "Press D to place a bomb."
        assert format_sign_text("Use #k(6) to cancel.") == "Use A to cancel."

    def test_button_symbols_become_names(self):
        assert format_sign_text("#u #u #d #d #l #r #l #r B A") == \
            "Up Up Down Down Left Right Left Right B A"

    def test_inline_images_are_dropped(self):
        got = format_sign_text(
            "#i(eye#K(95)bomber#K(95)poni.png,32,0,32,32)Fire - blast.")
        assert got == "Fire - blast."

    def test_leading_empty_image_line_collapses(self):
        # The v6 piano sign opens with a bare "#i()" line.
        got = format_sign_text("#i()\n    Piano Playing Instructions\n")
        assert got == "    Piano Playing Instructions"

    def test_interior_blank_lines_survive(self):
        assert format_sign_text("a\n \nb") == "a\n \nb"
