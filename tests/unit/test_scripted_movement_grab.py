"""Regression tests: A = grab/interact under scripted movement, and the sign
popup radius under script-quantized movement.

Bomber v6 (disabledefmovement via -Test/Movement) exposed two dead sign paths,
live-verified on bomber.home.eevul.net:14915 (bomblobby.nw streams 3 real
PLO_LEVELSIGN signs, so the DATA was always there):

1. input.py's scripted-movement branch returned right after
   _scripted_movement_touch, so the one-shot A dispatch (_try_grab: sign read
   -> dialogue box, chests, doors, pickups) was unreachable — pressing A on a
   level sign did nothing. disabledefmovement only disables default MOVEMENT.
   grab stays a built-in.

2. _check_and_render_signs' proximity popup used a 2.0-tile feet-to-sign-
   centre radius, exactly reachable when the built-in _move() clamps flush —
   but the v6 movement script steps in 0.3-tile quanta and rests up to 0.29
   short of flush, putting the feet sample at up to ~2.3 (live-measured 2.2).
   Radius is now 2.35 (next tile row is a full 3.0 away, so no walkway
   false-positives).
"""

import pygame
import pytest

pygame.init()
pygame.display.set_mode((64, 64))  # _feed_gs1_input reads the mouse

from pygame.locals import K_a, K_UP

from offline_game import spy
from pyreborn.game.dialogue import format_sign_text


class FakeKeys:
    """pygame.key.get_pressed() stand-in: index with K_* constants."""

    def __init__(self, *held):
        self._held = set(held)

    def __getitem__(self, key):
        return key in self._held

    def __len__(self):
        return 512


@pytest.fixture
def input_game(make_game, monkeypatch):
    """A real offline game with script-driven movement driving the REAL
    _handle_input through its scripted-movement branch, with call-through
    spies on the two dispatch targets (``grab_calls`` / ``touch_calls``)."""
    h = make_game()
    h.frames(1)
    h.gs1.default_movement = False
    h.key_just_pressed = {}
    h.last_action_time = 0.0
    h.action_delay = 0.3
    h.grab_calls = spy(monkeypatch, h, '_try_grab')
    h.touch_calls = spy(monkeypatch, h, '_scripted_movement_touch')
    return h


def _run_input(harness, keys, now=100.0):
    orig = pygame.key.get_pressed
    pygame.key.get_pressed = lambda: keys
    try:
        harness._handle_input(now)
    finally:
        pygame.key.get_pressed = orig


class TestScriptedMovementGrab:
    def test_fresh_a_press_dispatches_try_grab(self, input_game):
        h = input_game
        h.key_just_pressed[K_a] = True  # _handle_events saw KEYDOWN
        _run_input(h, FakeKeys(K_a))
        assert len(h.grab_calls) == 1
        assert len(h.touch_calls) == 1  # NPC-touch probe still runs

    def test_walk_into_and_press_dispatches_with_arrow_held(self, input_game):
        # The classic sign gesture: UP held into the sign, then press A.
        h = input_game
        h.key_just_pressed[K_a] = True
        _run_input(h, FakeKeys(K_a, K_UP))
        assert len(h.grab_calls) == 1

    def test_held_a_without_fresh_press_does_not_refire(self, input_game):
        h = input_game
        # A is held but was pressed in some earlier frame (no just-pressed).
        _run_input(h, FakeKeys(K_a))
        assert h.grab_calls == []

    def test_action_delay_cooldown_respected(self, input_game):
        h = input_game
        h.key_just_pressed[K_a] = True
        h.last_action_time = 100.0 - 0.1  # 0.1s ago < action_delay 0.3
        _run_input(h, FakeKeys(K_a), now=100.0)
        assert h.grab_calls == []

    def test_dismissing_keystroke_does_not_reopen_sign(self, input_game):
        # Pressing A on the dialog's LAST page dismisses it in
        # _handle_events; that same keystroke must NOT count as a fresh
        # press for _try_grab in the same frame's _handle_input, or the
        # dialog instantly re-opens under a player still standing at the
        # sign (live: page-0 wrap-around forever, dialog undismissable).
        h = input_game
        h._show_dialogue("last page")
        assert h.dialogue_text

        pygame.event.clear()
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=K_a,
                                             unicode=""))
        h._handle_events()
        assert h.dialogue_text is None          # dialog closed
        assert K_a not in h.key_just_pressed    # keystroke consumed

        _run_input(h, FakeKeys(K_a))            # same frame: A still held
        assert h.grab_calls == []               # no instant re-open

    def test_default_movement_path_unchanged(self, input_game):
        # Sanity: with default movement ON the scripted branch (and its
        # touch probe) must not run; A goes through the classic dispatch.
        h = input_game
        h.gs1.default_movement = True
        h.key_just_pressed[K_a] = True
        _run_input(h, FakeKeys(K_a))
        assert h.touch_calls == []
        assert len(h.grab_calls) == 1


@pytest.fixture
def popup_game(make_game, monkeypatch):
    """``popup_game(x, y)``: a real game standing at (x, y) below the sign at
    tile (20, 40) (the v6 piano-instructions sign); ``popup_texts`` records
    the popups (the sign popup draw itself is stubbed)."""
    def build(player_x, player_y):
        h = make_game(signs=[(20, 40, "Piano Playing Instructions")])
        h.client.player.x = player_x
        h.client.player.y = player_y
        h.popup_texts = []
        monkeypatch.setattr(h, '_render_sign_popup', h.popup_texts.append)
        return h
    return build


SIGN_TEXT = "Piano Playing Instructions\n"   # the server ends a sign with a newline


class TestSignPopupScriptQuantizedRadius:
    def test_scripted_flush_rest_position_triggers_popup(self, popup_game):
        # Scripted movement rests at y=40.2 below the sign (0.3-tile step
        # stops short of flush y=40.0): feet sample (x+1.5, y+2.5) =
        # (20.3, 42.7), 2.2 tiles from the sign centre (20.5, 40.5).
        h = popup_game(18.8, 40.2)
        h._check_and_render_signs()
        assert h.popup_texts == [SIGN_TEXT]

    def test_exact_flush_still_triggers(self, popup_game):
        # Built-in movement clamps flush at y=40.0: feet distance exactly 2.0.
        h = popup_game(18.8, 40.0)
        h._check_and_render_signs()
        assert h.popup_texts == [SIGN_TEXT]

    def test_one_row_back_does_not_trigger(self, popup_game):
        # A player one walkway row further (feet distance 3.0+) must not pop.
        h = popup_game(18.8, 41.0)
        h._check_and_render_signs()
        assert h.popup_texts == []

    def test_popup_suppressed_while_dialogue_open(self, popup_game):
        # The A-read dialogue box supersedes the proximity popup — both at
        # once double-displayed the same sign (live on bomber v6).
        h = popup_game(18.8, 40.2)
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

    def test_inline_images_emit_tokens_with_part_specs(self):
        got = format_sign_text(
            "#i(eye#K(95)bomber#K(95)poni.png,32,0,32,32)Fire - blast.")
        token, image = next(iter(got.images.items()))
        assert got == token + "Fire - blast."
        assert len(token) == 1 and 0xE000 <= ord(token) <= 0xF8FF
        assert image.name == "eye_bomber_poni.png"
        assert image.part == (32, 0, 32, 32)

    def test_plain_images_keep_order_and_touching_text(self):
        got = format_sign_text("left#i(first.png)#i(second.png)right")
        tokens = list(got.images)
        assert got == "left" + ''.join(tokens) + "right"
        assert len(set(tokens)) == 2
        assert [(image.name, image.part) for image in got.images.values()] == [
            ("first.png", None), ("second.png", None)]

    def test_image_csv_trims_name_and_invalid_numbers_become_zero(self):
        got = format_sign_text('#i( "icon,one.png" , bad, -2, 12, nope, extra)')
        image = next(iter(got.images.values()))
        assert image.name == "icon,one.png"
        assert image.part == (0, -2, 12, 0)

    def test_image_csv_without_full_rect_uses_full_image(self):
        got = format_sign_text("#i( icon.png , 3, 4, 5)")
        image = next(iter(got.images.values()))
        assert image.name == "icon.png"
        assert image.part is None

    def test_malformed_image_markers_drop_only_marker(self):
        got = format_sign_text("a#ib #i(no close #i")
        assert got == "ab (no close "
        assert got.images == {}

    def test_image_only_boundary_lines_survive(self):
        got = format_sign_text("\n #i()\n    Piano Playing Instructions\n#i(icon.png)\n ")
        tokens = list(got.images)
        assert got == " " + tokens[0] + "\n    Piano Playing Instructions\n" + tokens[1]
        assert got.images[tokens[0]].name == ""

    def test_image_name_with_nested_brackets(self):
        got = format_sign_text("#i(icon(1).png)end")
        token, image = next(iter(got.images.items()))
        assert got == token + "end"
        assert image.name == "icon(1).png"

    def test_literal_private_use_character_is_not_an_image(self):
        got = format_sign_text("\ue000#i(icon.png)")
        token = next(iter(got.images))
        assert token != '\ue000'
        assert list(got.segments(got)) == ['\ue000', got.images[token]]

    def test_empty_boundary_lines_are_trimmed(self):
        assert format_sign_text("\n \nInstructions\n \n") == "Instructions"

    def test_interior_blank_lines_survive(self):
        assert format_sign_text("a\n \nb") == "a\n \nb"
