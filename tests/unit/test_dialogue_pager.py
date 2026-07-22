"""Headless checks for dialogue wrapping, paging, and wire line breaks."""

from pyreborn.game.dialogue import DialoguePager, wrap_dialogue
from pyreborn.packets import parse_rpg_window, parse_say2


def _measure(text):
    return len(text)


def test_wrap_retains_explicit_newlines_and_empty_lines():
    assert wrap_dialogue("first line\n\nsecond line", _measure, 40) == [
        "first line", "", "second line"]


def test_wrap_uses_supplied_render_measurement():
    widths = {"wide": 8, "wide i": 10, "i": 1}
    assert wrap_dialogue("wide i", lambda text: widths.get(text, len(text)), 8) == [
        "wide", "i"]


def test_pager_splits_advances_and_closes_on_final_page():
    pager = DialoguePager(page_size=2)
    pager.replace("one\ntwo\nthree\nfour", _measure, 40)
    assert pager.visible_lines == ["one", "two"]
    assert pager.advance() is True
    assert pager.visible_lines == ["three", "four"]
    assert pager.advance() is False


def test_replace_resets_page_position():
    pager = DialoguePager(page_size=2)
    pager.replace("one\ntwo\nthree", _measure, 40)
    pager.advance()
    pager.replace("new first\nnew second", _measure, 40)
    assert pager.offset == 0
    assert pager.visible_lines == ["new first", "new second"]


def test_scroll_clamps_to_available_lines():
    pager = DialoguePager(page_size=2)
    pager.replace("one\ntwo\nthree\nfour", _measure, 40)
    pager.scroll(1)
    assert pager.visible_lines == ["two", "three"]
    pager.scroll(20)
    assert pager.visible_lines == ["three", "four"]
    pager.scroll(-20)
    assert pager.offset == 0


def test_window_packet_line_conventions_are_preserved():
    assert parse_rpg_window(b'"first, still first",second,""') == [
        "first, still first", "second", ""]
    assert parse_say2(b"first#b#bthird") == "first\n\nthird"
