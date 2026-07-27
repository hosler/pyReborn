from __future__ import annotations

from typing import Any, Tuple

import pygame

from reborn_protocol.gs2 import to_bool, to_num, to_str

from .base import GuiControl
from .profiles import _draw_border, _draw_label, _fill_rect, _font, _shade
from .skins import _Skin  # noqa: F401  - kept: original import block (star-import consumers rely on it)
from typing import Dict, List, Optional  # noqa: F401  - kept: original import block (star-import consumers rely on it)


class GuiWindowCtrl(GuiControl):
    """Frame + title bar + draggable (drag handled by GS2GuiManager).

    TITLE_H is 22 per the Login scripts' own layout math: every panel is
    placed at y = -22 relative to the client area precisely to overlay the
    title bar (Serverlist_DescriptionPanel/TablesPanel), so a different
    title height shifts the whole pane contents."""

    CTRL_CLASS = "GuiWindowCtrl"
    TITLE_H = 22

    def child_state_offset(self) -> Tuple[float, float]:
        if to_bool(self._members.get("clientrelative", 0)):
            return 0.0, float(self.TITLE_H)
        return 0.0, 0.0

    def ancestor_window(self):
        return self

    def pointer_down(self, manager, pos) -> bool:
        close, minimize, maximize = self._screen_button_rects()
        if self.canclose and close.collidepoint(pos):
            self.close_button_pressed = True
            manager._window_button_press = self
            manager._set_focus(None)
            return True
        if self.canminimize and minimize.collidepoint(pos):
            self.minimize_button_pressed = True
            manager._window_button_press = self
            manager._set_focus(None)
            return True
        if self.canmaximize and maximize.collidepoint(pos):
            self.maximize_button_pressed = True
            manager._window_button_press = self
            manager._set_focus(None)
            return True
        if self.canmove and self.titlebar_rect().collidepoint(pos):
            r = self.rect()
            manager._drag = (self, pos[0] - r.x, pos[1] - r.y)
            manager._set_focus(None)
            return True
        return False

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 240.0, 160.0
        self.canclose = True
        self.canminimize = True
        self.canmaximize = True
        self.canmove = True
        self.closequery = False
        self.destroyonhide = False
        self.close_button_pressed = False
        self.minimize_button_pressed = False
        self.maximize_button_pressed = False
        self.minimized = False
        self.maximized = False
        self.standard_bounds = pygame.Rect(0, 0, 100, 200)

    _TORQUE_PROPS = GuiControl._TORQUE_PROPS | frozenset(
        {"maximized", "minimized"})
    _METHOD_NAMES = GuiControl._METHOD_NAMES | frozenset(
        {"close", "minimize", "maximize", "restore"})

    def get(self, key: str) -> Any:
        k = key.lower()
        if k in ("canclose", "canminimize", "canmaximize", "canmove",
                 "closequery", "destroyonhide", "maximized", "minimized"):
            return 1.0 if getattr(self, k) else 0.0
        return super().get(k)

    def set(self, key: str, value: Any) -> None:
        k = key.lower()
        if k in ("maximized", "minimized"):
            # These setters are TOGGLES, not idempotent state writes: a
            # truthy write calls maximizeWindow()/minimizeWindow(), and
            # those RESTORE when the window is already in that state; a
            # falsy write restores only if it IS in that state (FourPlay
            # quattroplay/src/gui/GuiWindowCtrlProperties.cpp:137-156,
            # GuiWindowCtrl.cpp:151-155, :169-173).
            if to_bool(value):
                if k == "maximized":
                    self.maximize_window()
                else:
                    self.minimize_window()
            elif getattr(self, k):
                self.restore_window()
            return
        if k in ("canclose", "canminimize", "canmaximize", "canmove",
                 "closequery", "destroyonhide"):
            setattr(self, k, to_bool(value))
            return
        super().set(k, value)

    def _m_close(self, *args) -> float:
        """close(): note it does NOT consult `canclose`, which only gates
        the title-bar button (GuiWindowCtrlProperties.cpp:181-184 vs
        GuiWindowCtrl.cpp:253-258)."""
        self.close_window()
        return 0.0

    def _m_minimize(self, *args) -> float:
        self.minimize_window()
        return 0.0

    def _m_maximize(self, *args) -> float:
        self.maximize_window()
        return 0.0

    def _m_restore(self, *args) -> float:
        self.restore_window()
        return 0.0

    def button_rects(self) -> Tuple[pygame.Rect, pygame.Rect, pygame.Rect]:
        x = int(self.width) - 18
        close = pygame.Rect(x, 3, 16, 16) if self.canclose else pygame.Rect(0, 0, 0, 0)
        if self.canclose:
            x -= 18
        maximize = (pygame.Rect(x, 3, 16, 16) if self.canmaximize
                    else pygame.Rect(0, 0, 0, 0))
        if self.canmaximize:
            x -= 18
        minimize = (pygame.Rect(x, 3, 16, 16) if self.canminimize
                    else pygame.Rect(0, 0, 0, 0))
        return close, minimize, maximize

    def _screen_button_rects(self) -> Tuple[pygame.Rect, pygame.Rect, pygame.Rect]:
        r = self.rect()
        return tuple(button.move(r.x, r.y) for button in self.button_rects())

    def close_window(self) -> None:
        if self.closequery:
            self.fire_event("onclosequery")
            return
        if self._manager is not None:
            self._manager.hide(self)
            if self.destroyonhide:
                self._manager.destroy(self)
        else:
            self.visible = False

    def minimize_window(self) -> None:
        """Min/max/restore all resize through the choke point, so onResize
        fires BEFORE the window event (GuiWindowCtrl.cpp:149-199: each calls
        resize() and then invokes its own event)."""
        if self.minimized:
            self.restore_window()
            return
        self.standard_bounds = pygame.Rect(
            int(self.x), int(self.y), int(self.width), int(self.height))
        self.minimized = True
        self.resize_control(self.x, self.y, self.width, float(self.TITLE_H))
        self.fire_event("onminimize")

    def maximize_window(self) -> None:
        if self.maximized:
            self.restore_window()
            return
        self.standard_bounds = pygame.Rect(
            int(self.x), int(self.y), int(self.width), int(self.height))
        self.maximized = True
        if self.parent is not None:
            self.resize_control(0.0, 0.0, self.parent.width,
                                self.parent.height)
        elif self._manager is not None:
            # a root's Torque parent is the canvas (GuiControl.get("parent")),
            # so this IS the engine's parent-sized maximize for our roots
            canvas = self._manager.canvas_object()
            self.resize_control(0.0, 0.0, to_num(canvas.get("width")),
                                to_num(canvas.get("height")))
        # a genuinely parentless window skips the resize but still fires the
        # event (GuiWindowCtrl.cpp:176-183)
        self.fire_event("onmaximize")

    def restore_window(self) -> None:
        changed = self.minimized or self.maximized
        self.minimized = self.maximized = False
        if changed:
            bounds = self.standard_bounds
            self.resize_control(float(bounds.x), float(bounds.y),
                                float(bounds.width), float(bounds.height))
        self.fire_event("onrestore")

    def titlebar_rect(self) -> pygame.Rect:
        r = self.rect()
        return pygame.Rect(r.x, r.y, r.width, min(self.TITLE_H, r.height))

    def client_inset(self) -> Tuple[float, float]:
        # the client area children are laid out in starts below the title bar
        return 0.0, float(self.TITLE_H)

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        prof = self.resolve_profile()
        r = self.rect()
        tb = self.titlebar_rect()
        skin = self._skin(prof, sprite_mgr)
        alpha = int(255 * prof.transparency)
        drew_frame = False
        if skin is not None and skin.looks_like_window_sheet():
            # client area first: the full window sheet carries a tiled
            # background cell (guiblue_window.png -- IRC_WindowRedProfile's
            # red fillcolor is never seen in the official look); the
            # *_noback sheets have none, there the translucent blue
            # fillcolor IS the background. Then the sliced title bar +
            # frame art on top.
            client = pygame.Rect(r.x, r.y + tb.height, r.width,
                                 max(0, r.height - tb.height))
            if not skin.draw_window_background(surf, client, alpha):
                _fill_rect(surf, prof.bg, client)
            drew_frame = skin.draw_window_frame(surf, r, alpha)
        if not drew_frame:
            _fill_rect(surf, prof.bg, r)
            _draw_border(surf, r, prof, skin)
            _fill_rect(surf, prof.title_bg, tb)
        if self.text and fonts is not None:
            font = _font(fonts, prof)
            label_w = font.size(self.text)[0]
            if prof.align == "right":
                lx = tb.right - label_w - 8
            elif prof.align == "center":
                lx = tb.centerx - label_w // 2
            else:
                lx = tb.x + 8
            label_h = font.get_height()
            _draw_label(surf, font, self.text, prof.title_fg,
                        (lx, tb.y + (tb.height - label_h) // 2),
                        prof.text_shadow or drew_frame)
        close, minimize, maximize = self._screen_button_rects()
        glyph = prof.title_fg
        if self.canclose:
            pygame.draw.line(surf, glyph, (close.x + 4, close.y + 4),
                             (close.right - 5, close.bottom - 5), 2)
            pygame.draw.line(surf, glyph, (close.right - 5, close.y + 4),
                             (close.x + 4, close.bottom - 5), 2)
        if self.canminimize:
            pygame.draw.line(surf, glyph, (minimize.x + 3, minimize.bottom - 4),
                             (minimize.right - 4, minimize.bottom - 4), 2)
        if self.canmaximize:
            pygame.draw.rect(surf, glyph, maximize.inflate(-6, -6), 1)


class GuiButtonBaseCtrl(GuiControl):
    """Shared button surface: `text`, `checked`, `groupnum`, `buttontype`
    (FourPlay quattroplay/src/gui/GuiButtonBaseCtrlProperties.cpp:68-105).
    Every button-ish control -- plain, bitmap, checkbox, radio -- inherits
    it; `GuiCheckBoxCtrlProperties.cpp` and `GuiRadioCtrlProperties.cpp`
    register nothing of their own, so this table IS their whole
    button-specific surface.

    What the control DOES is driven by `buttontype`, not by the class: a
    checkbox with `buttontype = "RadioButton"` is a working radio and a
    radio with `"PushButton"` stops being one (GuiButtonBaseCtrl::onAction,
    :59-94). The class only picks the default -- PushButton here,
    ToggleButton on a checkbox (GuiCheckBoxCtrl.cpp:25-35), RadioButton on
    a radio (GuiRadioCtrl.cpp:18-24)."""

    CTRL_CLASS = "GuiButtonBaseCtrl"
    can_key_focus = True         # GuiButtonBaseCtrl.cpp:104-117

    def pointer_down(self, manager, pos) -> bool:
        manager._set_focus(None)
        manager._set_pressed(self)
        manager._activate_button(self)
        return True
    #: byte-exact; the setter loops these three with TString's memcmp `==`
    #: and, on no match, leaves the old value and reports nothing
    #: (GuiButtonBaseCtrlProperties.cpp:16-26)
    BUTTON_TYPES = ("PushButton", "ToggleButton", "RadioButton")
    DEFAULT_BUTTON_TYPE = 0
    _TORQUE_PROPS = GuiControl._TORQUE_PROPS | frozenset(
        {"checked", "groupnum", "buttontype"})

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.checked = False
        self.button_type = self.DEFAULT_BUTTON_TYPE
        #: radio-group id; default -1 (GuiButtonBaseCtrl.cpp:33)
        self.groupnum = -1

    def get(self, key: str) -> Any:
        k = key.lower()
        if k == "checked":
            return 1.0 if self.checked else 0.0
        if k == "groupnum":
            return float(self.groupnum)
        if k == "buttontype":
            return self.BUTTON_TYPES[self.button_type]
        return super().get(k)

    def set(self, key: str, value: Any) -> None:
        k = key.lower()
        if k == "checked":
            # setChecked() only stores and repaints (GuiButtonBaseCtrl.cpp:
            # 42-46) -- radio-group exclusivity lives in onAction(), so a
            # SCRIPT write leaves every sibling checked. Login clears them by
            # hand for exactly that reason (graal-loginserver/weapons/
            # weapon-Rescripted_IRC_Login2.txt:48-49).
            self.checked = to_bool(value)
            return
        if k == "groupnum":
            self.groupnum = int(to_num(value))
            return
        if k == "buttontype":
            name = to_str(value)
            if name in self.BUTTON_TYPES:
                self.button_type = self.BUTTON_TYPES.index(name)
            return
        super().set(k, value)

    def is_active(self) -> bool:
        return to_bool(self._members.get("active", 1))

    def on_action(self) -> bool:
        """The engine's onAction(): the activation path a click/Enter/hotkey
        takes (GuiButtonBaseCtrl.cpp:59-94). Inactive controls do nothing at
        all; a ToggleButton flips `checked`; a RadioButton checks itself and
        clears the same-`groupnum` RadioButton siblings among its parent's
        direct children."""
        if not self.is_active():
            return False
        if self.button_type == 1:
            self.checked = not self.checked
        elif self.button_type == 2:
            self.checked = True
            siblings = (self.parent.children if self.parent is not None
                        else (self._manager.roots if self._manager else []))
            for sib in siblings:
                if (sib is not self and isinstance(sib, GuiButtonBaseCtrl)
                        and sib.button_type == 2
                        and sib.groupnum == self.groupnum):
                    sib.checked = False
        return self.fire_action()


class GuiButtonCtrl(GuiButtonBaseCtrl):
    """Rect + text (aligned per profile) + optional icon; onAction fires on
    click (GS2GuiManager). Skin sheets (guiblue_button.png) carry four
    9-patch state groups in order normal/hilight/pressed/inactive."""

    CTRL_CLASS = "GuiButtonCtrl"

    def pointer_down(self, manager, pos) -> bool:
        manager._set_focus(None)
        manager._set_pressed(self)
        if not manager._toggle_start_menu(self):
            manager._activate_button(self)
        return True

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 100.0, 24.0

    def _label_text(self) -> str:
        if self.text:
            return self.text
        # The taskbar start button has no script-side text -- the official
        # client paints it from the window-style skin. Use the start menu's
        # own title as the label so it isn't an anonymous slab.
        if (to_str(self._members.get("stylesection", "")).lower()
                == "taskbar.startbutton" and self._manager is not None):
            from .collection_controls import GuiStartMenuCtrl
            menu = next((c for c in self._manager.roots
                         if isinstance(c, GuiStartMenuCtrl)), None)
            if menu is not None and menu.text:
                return menu.text
            return "Start"
        return ""

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        prof = self.resolve_profile()
        r = self.rect()
        skin = self._skin(prof, sprite_mgr)
        state_row = 6 if self.pressed else (3 if self.hovered else 0)
        drew = False
        if skin is not None:
            drew = skin.draw_nine(surf, r, state_row,
                                  int(255 * prof.transparency))
            if not drew and state_row:
                drew = skin.draw_nine(surf, r, 0,
                                      int(255 * prof.transparency))
        if not drew:
            fill = prof.bg if prof.bg is not None else prof.title_bg
            if self.pressed:
                fill = _shade(fill, 0.75)
            elif self.hovered:
                fill = _shade(fill, 1.2)
            _fill_rect(surf, fill, r, border_radius=4)
            _draw_border(surf, r, prof, skin, border_radius=4)
        # optional icon (icon.drawimagestretched from the construction
        # block -- the taskbar's server buttons)
        tx = r.x + 8
        if self.icon_image and sprite_mgr is not None:
            img = sprite_mgr.load_sheet(self.icon_image)
            if img is None and self._manager is not None:
                self._manager.request_image(self.icon_image)
            if img is not None:
                iw = int(self.icon_w) or 24
                ih = int(self.icon_h) or 24
                if img.get_size() != (iw, ih):
                    img = pygame.transform.smoothscale(img, (iw, ih))
                surf.blit(img, (tx, r.centery - ih // 2))
                tx += iw + 4
        text = self._label_text()
        if text and fonts is not None:
            font = _font(fonts, prof)
            tw = font.size(text)[0]
            if prof.align == "left":
                lx = tx
            elif prof.align == "right":
                lx = r.right - tw - 8
            else:
                lx = max(tx, r.centerx - tw // 2)
            _draw_label(surf, font, text, prof.fg,
                        (lx, r.centery - font.get_height() // 2),
                        prof.text_shadow)


class GuiTextCtrl(GuiControl):
    """A plain (non-interactive) text label.

    `maxchars` caps the text and defaults to **255**
    (GuiTextCtrl::initObject, FourPlay quattroplay/src/gui/GuiTextCtrl.cpp:27),
    and the cap is applied by `setText` itself -- `subString(0, maxchars)`
    at :181 -- so it truncates every write, script-assigned or typed, on
    labels and on the edit controls below alike. `maxchars <= 0` disables
    it."""

    CTRL_CLASS = "GuiTextCtrl"
    _TORQUE_PROPS = GuiControl._TORQUE_PROPS | frozenset({"maxchars"})
    maxchars = 255
    _text = ""

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 100.0, 16.0

    @property
    def text(self) -> str:
        return self._text

    @text.setter
    def text(self, value: Any) -> None:
        """GuiTextCtrl::setText (quattroplay/src/gui/GuiTextCtrl.cpp:
        170-199): unchanged text EARLY-OUTS with no event (:172-176), the
        clip applies (:181), then `onTextChanged` fires ON THE CONTROL with
        one string param = the CLIPPED text (:190-193). setText is virtual,
        so the same applies to every write path on the edit subclasses --
        script `.text =`, settext(), and typed input alike. Live handlers:
        Login's Serverlist_EventOptions_Teams.onTextChanged(newtext) and
        ~15 catchevent routes in the staff sprite editor."""
        value = to_str(value)
        if 0 < self.maxchars < len(value):
            value = value[:self.maxchars]
        if value == self._text:
            return
        self._text = value
        self.fire_event("ontextchanged", value)

    def get(self, key: str) -> Any:
        if key.lower() == "maxchars":
            return float(self.maxchars)
        return super().get(key)

    def set(self, key: str, value: Any) -> None:
        if key.lower() == "maxchars":
            self.maxchars = int(to_num(value))
            return
        super().set(key, value)

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        if not self.text or fonts is None:
            return
        prof = self.resolve_profile()
        r = self.rect()
        font = _font(fonts, prof)
        tw = font.size(self.text)[0]
        if prof.align == "right":
            lx = r.right - tw
        elif prof.align == "center":
            lx = r.centerx - tw // 2
        else:
            lx = r.x
        _draw_label(surf, font, self.text, prof.fg, (lx, r.y),
                    prof.text_shadow)
