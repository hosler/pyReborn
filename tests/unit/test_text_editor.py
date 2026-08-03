"""Headless coverage for the reusable multiline editor."""

import os
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

from pyreborn.game.assets import FontManager
from pyreborn.game.text_editor import TextBuffer, TextEditor


def _key(key, unicode="", mod=0):
    return SimpleNamespace(key=key, unicode=unicode, mod=mod)


def test_insert_newline_backspace_and_forward_delete():
    buffer = TextBuffer()
    buffer.insert("abc")
    buffer.newline()
    buffer.insert("def")
    assert buffer.text == "abc\ndef"
    buffer.backspace()
    assert buffer.text == "abc\nde"
    buffer.home()
    buffer.backspace()
    assert buffer.text == "abcde"
    buffer.cursor = (0, 2)
    buffer.delete_forward()
    assert buffer.text == "abde"


def test_navigation_home_end_page_and_words_at_extremes():
    buffer = TextBuffer("one two\nthree\nfour\nfive")
    buffer.cursor = (0, 7)
    buffer.word_left()
    assert buffer.cursor == (0, 4)
    buffer.word_right()
    assert buffer.cursor == (0, 7)
    buffer.right()
    assert buffer.cursor == (1, 0)
    buffer.end()
    assert buffer.cursor == (1, 5)
    buffer.home()
    buffer.up()
    buffer.left()
    assert buffer.cursor == (0, 0)
    buffer.page_down(2)
    assert buffer.cursor == (2, 0)
    buffer.page_up(99)
    assert buffer.cursor == (0, 0)


def test_undo_redo_coalesces_consecutive_typing():
    buffer = TextBuffer()
    for character in "hello":
        buffer.insert(character)
    buffer.undo()
    assert buffer.text == ""
    buffer.redo()
    assert buffer.text == "hello"
    buffer.newline()
    buffer.insert("x")
    buffer.undo()
    assert buffer.text == "hello\n"
    buffer.undo()
    assert buffer.text == "hello"


def test_new_edit_clears_redo_and_dirty_tracks_loaded_text():
    buffer = TextBuffer("base")
    assert not buffer.dirty
    buffer.insert("x")
    assert buffer.dirty
    buffer.undo()
    assert not buffer.dirty
    buffer.insert("y")
    buffer.redo()
    assert buffer.text == "ybase"
    buffer.load("fresh")
    assert buffer.text == "fresh"
    assert not buffer.dirty
    assert buffer.cursor == (0, 0)


def test_editor_handles_keys_and_viewport_follows_cursor():
    editor = TextEditor(TextBuffer("0\n1\n2\n3\n4"), visible_lines=2)
    editor.buffer.cursor = (0, 0)
    for _ in range(4):
        editor.handle_key(_key(pygame.K_DOWN))
    assert editor.top_row == 3
    editor.handle_key(_key(pygame.K_HOME))
    editor.handle_key(_key(ord("x"), "x"))
    assert editor.buffer.lines[4] == "x4"
    editor.handle_key(_key(pygame.K_z, mod=pygame.KMOD_CTRL))
    assert editor.buffer.lines[4] == "4"


@pytest.mark.parametrize("text,cursor,rect", [
    ("", (0, 0), (0, 0, 200, 80)),
    ("a", (0, 0), (0, 0, 200, 80)),
    ("a", (0, 1), (0, 0, 200, 80)),
    ("long line " * 100, (0, 1000), (0, 0, 200, 80)),
    ("a\nb\nc", (2, 1), (0, 0, 1, 1)),
    ("", (0, 0), (0, 0, 0, 0)),
])
def test_draw_smoke_for_empty_extreme_and_tiny_rects(text, cursor, rect):
    pygame.init()
    pygame.display.set_mode((1, 1))
    surface = pygame.Surface((240, 100))
    buffer = TextBuffer(text)
    buffer.cursor = cursor
    TextEditor(buffer, visible_lines=3).draw(surface, rect, FontManager())
    pygame.quit()
