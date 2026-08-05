from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pygame

from pyreborn.game.gs2_gui import GuiTextEditCtrl


@dataclass(frozen=True)
class InputResult:
    success: bool
    reason: str = ""
    point: tuple[int, int] | None = None


class InputDriver:
    """Synthetic physical input, always routed through manager.handle_event."""

    def __init__(self, manager: Any):
        self.manager = manager

    def _point(self, control: Any) -> tuple[int, int] | None:
        rect = control.rect()
        if rect.width <= 0 or rect.height <= 0:
            return None
        xs = (rect.centerx, rect.left + 2, rect.right - 2,
              rect.left + rect.width // 4, rect.left + 3 * rect.width // 4)
        ys = (rect.centery, rect.top + 2, rect.bottom - 2,
              rect.top + rect.height // 4, rect.top + 3 * rect.height // 4)
        for y in ys:
            for x in xs:
                point = (int(x), int(y))
                if self.manager.hit_test(point) is control:
                    return point
        return None

    def click_control(self, control: Any, button: int = 1,
                      click_count: int = 1) -> InputResult:
        point = self._point(control)
        if point is None:
            return InputResult(False, "occluded/unhittable")
        for _ in range(max(1, click_count)):
            self.manager.click_point(point, button)
        return InputResult(True, point=point)

    def click_point(self, canvas_pos, button: int = 1) -> InputResult:
        hit = self.manager.hit_test(canvas_pos)
        if hit is None and getattr(self.manager, "_open_popup", None) is None:
            return InputResult(False, "unhittable")
        self.manager.click_point(canvas_pos, button)
        return InputResult(True, point=tuple(map(int, canvas_pos)))

    def select_row(self, control: Any, row_index: int,
                   double: bool = False) -> InputResult:
        rect = control.rect()
        point = (int(rect.left + min(6, max(1, rect.width - 1))),
                 int(rect.top + row_index * control.ROW_H + control.ROW_H / 2))
        if self.manager.hit_test(point) is not control:
            return InputResult(False, "occluded/unhittable", point)
        self.manager.click_point(point)
        if double:
            self.manager.click_point(point)
        return InputResult(True, point=point)

    def select_tab(self, control: Any, row_index: int) -> InputResult:
        rect = control.rect()
        point = (int(rect.left + (row_index + .5) * control.tab_width()),
                 int(rect.centery))
        return self.click_point(point)

    def select_popup_row(self, control: Any, row_index: int) -> InputResult:
        if getattr(self.manager, "_open_popup", None) is not control:
            opened = self.click_control(control)
            if not opened.success:
                return opened
        rect = control.popup_rect()
        point = (int(rect.left + max(1, rect.width // 2)),
                 int(rect.top + (row_index + .5) * max(1, int(control.height))))
        return self.click_point(point)

    def focus_control(self, control: Any) -> InputResult:
        return self.click_control(control)

    def type_text(self, control: Any, text: str,
                  submit: bool = False) -> InputResult:
        if not isinstance(control, GuiTextEditCtrl):
            return InputResult(False, "not a text edit")
        if control.is_password():
            return InputResult(False, "password field")
        focused = self.focus_control(control)
        if not focused.success:
            return focused
        for char in text:
            self.manager.press_key(ord(char.lower()) if char else 0, char, 0)
        if submit:
            self.manager.press_key(pygame.K_RETURN)
        return InputResult(True, point=focused.point)

    def press_key(self, key, unicode: str = "", modifiers: int = 0) -> InputResult:
        return InputResult(bool(self.manager.press_key(key, unicode, modifiers)))

    def press_tab(self, reverse: bool = False) -> InputResult:
        return InputResult(bool(self.manager.press_tab(reverse)))
