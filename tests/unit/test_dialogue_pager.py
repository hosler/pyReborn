"""Headless checks for dialogue wrapping, paging, and wire line breaks."""

from types import SimpleNamespace

from pyreborn.game.dialogue import DialoguePager, format_sign_text, wrap_dialogue
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


def test_sign_wrap_measures_images_as_part_of_touching_words():
    text = format_sign_text("a pre#i(icon.png)post z")
    token = next(iter(text.images))
    sprites = SimpleNamespace(load_sheet=lambda name: SimpleNamespace(get_width=lambda: 8))
    measure = lambda line: text.measure(line, len, sprites)

    assert measure("pre" + token + "post") == 15
    assert wrap_dialogue(text, measure, 15) == ["a", "pre" + token + "post", "z"]
    assert wrap_dialogue(token + "ab", measure, 4) == [token, "ab"]


def test_sign_image_measure_uses_part_width_and_zero_for_missing_images():
    text = format_sign_text("#i(part.png,0,0,12,20)#i(missing.png,0,0,99,99)")
    calls = []

    def get_sprite(name, *part):
        calls.append((name, part))
        return SimpleNamespace(get_width=lambda: 5) if name == "part.png" else None

    assert text.measure(text, len, SimpleNamespace(get_sprite=get_sprite)) == 12
    assert calls == [("part.png", (0, 0, 12, 20)), ("missing.png", (0, 0, 99, 99))]


def test_sign_missing_full_image_has_zero_width():
    text = format_sign_text("a#i(missing.png)b")
    assert text.measure(text, len, SimpleNamespace(load_sheet=lambda name: None)) == 2


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
