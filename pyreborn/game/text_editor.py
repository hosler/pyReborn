"""Reusable multiline text model and pygame editor view."""

from __future__ import annotations

from typing import List, Optional, Tuple

import pygame

from . import theme


class TextBuffer:
    """Pure multiline text storage with cursor movement and edit history."""

    def __init__(self, text: str = ""):
        self.lines: List[str] = [""]
        self.row = 0
        self.col = 0
        self._loaded_text = ""
        self._undo: List[Tuple[str, int, int]] = []
        self._redo: List[Tuple[str, int, int]] = []
        self._typing = False
        self.load(text)

    @property
    def cursor(self) -> Tuple[int, int]:
        return self.row, self.col

    @cursor.setter
    def cursor(self, value: Tuple[int, int]) -> None:
        self.row, self.col = value
        self._clamp()
        self._typing = False

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def dirty(self) -> bool:
        return self.text != self._loaded_text

    def load(self, text: str) -> None:
        self.lines = text.split("\n") or [""]
        self.row = self.col = 0
        self._loaded_text = text
        self._undo.clear()
        self._redo.clear()
        self._typing = False

    def _state(self) -> Tuple[str, int, int]:
        return self.text, self.row, self.col

    def _restore(self, state: Tuple[str, int, int]) -> None:
        text, self.row, self.col = state
        self.lines = text.split("\n") or [""]
        self._clamp()

    def _record(self, typing: bool = False) -> None:
        if not (typing and self._typing):
            self._undo.append(self._state())
        self._redo.clear()
        self._typing = typing

    def _clamp(self) -> None:
        if not self.lines:
            self.lines = [""]
        self.row = max(0, min(self.row, len(self.lines) - 1))
        self.col = max(0, min(self.col, len(self.lines[self.row])))

    def insert(self, text: str) -> None:
        if not text:
            return
        if "\n" in text:
            for index, part in enumerate(text.split("\n")):
                if index:
                    self.newline()
                self.insert(part)
            return
        self._record(typing=True)
        line = self.lines[self.row]
        self.lines[self.row] = line[:self.col] + text + line[self.col:]
        self.col += len(text)

    def newline(self) -> None:
        self._record()
        line = self.lines[self.row]
        self.lines[self.row] = line[:self.col]
        self.lines.insert(self.row + 1, line[self.col:])
        self.row += 1
        self.col = 0

    def backspace(self) -> None:
        if self.row == 0 and self.col == 0:
            self._typing = False
            return
        self._record()
        if self.col:
            line = self.lines[self.row]
            self.lines[self.row] = line[:self.col - 1] + line[self.col:]
            self.col -= 1
        else:
            previous = self.lines[self.row - 1]
            self.col = len(previous)
            self.lines[self.row - 1] = previous + self.lines.pop(self.row)
            self.row -= 1

    def delete_forward(self) -> None:
        line = self.lines[self.row]
        if self.col == len(line) and self.row == len(self.lines) - 1:
            self._typing = False
            return
        self._record()
        if self.col < len(line):
            self.lines[self.row] = line[:self.col] + line[self.col + 1:]
        else:
            self.lines[self.row] += self.lines.pop(self.row + 1)

    delete = delete_forward

    def undo(self) -> None:
        if not self._undo:
            return
        self._redo.append(self._state())
        self._restore(self._undo.pop())
        self._typing = False

    def redo(self) -> None:
        if not self._redo:
            return
        self._undo.append(self._state())
        self._restore(self._redo.pop())
        self._typing = False

    def left(self) -> None:
        if self.col:
            self.col -= 1
        elif self.row:
            self.row -= 1
            self.col = len(self.lines[self.row])
        self._typing = False

    def right(self) -> None:
        if self.col < len(self.lines[self.row]):
            self.col += 1
        elif self.row < len(self.lines) - 1:
            self.row += 1
            self.col = 0
        self._typing = False

    def up(self) -> None:
        self.row = max(0, self.row - 1)
        self.col = min(self.col, len(self.lines[self.row]))
        self._typing = False

    def down(self) -> None:
        self.row = min(len(self.lines) - 1, self.row + 1)
        self.col = min(self.col, len(self.lines[self.row]))
        self._typing = False

    def home(self) -> None:
        self.col = 0
        self._typing = False

    def end(self) -> None:
        self.col = len(self.lines[self.row])
        self._typing = False

    def page_up(self, rows: int = 10) -> None:
        self.row = max(0, self.row - max(1, rows))
        self.col = min(self.col, len(self.lines[self.row]))
        self._typing = False

    def page_down(self, rows: int = 10) -> None:
        self.row = min(len(self.lines) - 1, self.row + max(1, rows))
        self.col = min(self.col, len(self.lines[self.row]))
        self._typing = False

    def word_left(self) -> None:
        if self.col == 0:
            self.left()
            return
        line = self.lines[self.row]
        while self.col and line[self.col - 1].isspace():
            self.col -= 1
        while self.col and not line[self.col - 1].isspace():
            self.col -= 1
        self._typing = False

    def word_right(self) -> None:
        line = self.lines[self.row]
        if self.col == len(line):
            self.right()
            return
        while self.col < len(line) and not line[self.col].isspace():
            self.col += 1
        while self.col < len(line) and line[self.col].isspace():
            self.col += 1
        self._typing = False


class TextEditor:
    """Pygame viewport and keyboard handling over a :class:`TextBuffer`."""

    def __init__(self, buffer: Optional[TextBuffer] = None, visible_lines: int = 20):
        self.buffer = buffer or TextBuffer()
        self.visible_lines = max(1, visible_lines)
        self.top_row = 0
        self.horizontal_offset = 0

    def _follow_cursor(self, columns: Optional[int] = None) -> None:
        row, col = self.buffer.cursor
        if row < self.top_row:
            self.top_row = row
        elif row >= self.top_row + self.visible_lines:
            self.top_row = row - self.visible_lines + 1
        self.top_row = max(0, self.top_row)
        if columns is not None:
            columns = max(1, columns)
            if col < self.horizontal_offset:
                self.horizontal_offset = col
            elif col >= self.horizontal_offset + columns:
                self.horizontal_offset = col - columns + 1

    def handle_key(self, event) -> bool:
        key = event.key
        mod = getattr(event, "mod", 0)
        ctrl = bool(mod & pygame.KMOD_CTRL)
        if ctrl and key == pygame.K_z:
            self.buffer.undo()
        elif ctrl and key == pygame.K_y:
            self.buffer.redo()
        elif key == pygame.K_BACKSPACE:
            self.buffer.backspace()
        elif key == pygame.K_DELETE:
            self.buffer.delete_forward()
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.buffer.newline()
        elif key == pygame.K_LEFT:
            self.buffer.word_left() if ctrl else self.buffer.left()
        elif key == pygame.K_RIGHT:
            self.buffer.word_right() if ctrl else self.buffer.right()
        elif key == pygame.K_UP:
            self.buffer.up()
        elif key == pygame.K_DOWN:
            self.buffer.down()
        elif key == pygame.K_HOME:
            self.buffer.home()
        elif key == pygame.K_END:
            self.buffer.end()
        elif key == pygame.K_PAGEUP:
            self.buffer.page_up(self.visible_lines)
        elif key == pygame.K_PAGEDOWN:
            self.buffer.page_down(self.visible_lines)
        elif not ctrl and getattr(event, "unicode", "") and \
                event.unicode not in ("\r", "\n", "\x00"):
            self.buffer.insert(event.unicode)
        else:
            return False
        self._follow_cursor()
        return True

    @staticmethod
    def _font(fonts):
        if hasattr(fonts, "get"):
            return fonts.get("small")
        if isinstance(fonts, dict):
            return fonts.get("small") or next(iter(fonts.values()))
        return fonts

    def draw(self, surface, rect, fonts) -> None:
        rect = pygame.Rect(rect).clip(surface.get_rect())
        if rect.w <= 0 or rect.h <= 0:
            return
        font = self._font(fonts)
        line_height = max(1, font.get_linesize())
        visible = max(0, rect.h // line_height)
        self.visible_lines = max(1, visible)
        number_width = font.size(str(max(1, len(self.buffer.lines))))[0] + 12
        columns = max(1, (rect.w - number_width) // max(1, font.size("M")[0]))
        self._follow_cursor(columns)
        pygame.draw.rect(surface, theme.INPUT_BG, rect)
        pygame.draw.line(surface, theme.INPUT_BORDER,
                         (rect.x + number_width, rect.y),
                         (rect.x + number_width, rect.bottom))
        if visible == 0:
            return
        old_clip = surface.get_clip()
        surface.set_clip(rect)
        end = min(len(self.buffer.lines), self.top_row + visible)
        for screen_row, row in enumerate(range(self.top_row, end)):
            y = rect.y + screen_row * line_height
            number = font.render(str(row + 1), True, theme.TEXT_FAINT)
            surface.blit(number, (rect.x + number_width - number.get_width() - 6, y))
            text = self.buffer.lines[row][self.horizontal_offset:]
            surface.blit(font.render(text, True, theme.TEXT),
                         (rect.x + number_width + 4, y))
        cursor_row = self.buffer.row - self.top_row
        if 0 <= cursor_row < visible:
            prefix = self.buffer.lines[self.buffer.row][
                self.horizontal_offset:self.buffer.col]
            x = rect.x + number_width + 4 + font.size(prefix)[0]
            y = rect.y + cursor_row * line_height
            pygame.draw.line(surface, theme.MINT, (x, y),
                             (x, min(rect.bottom - 1, y + line_height - 1)))
        surface.set_clip(old_clip)
