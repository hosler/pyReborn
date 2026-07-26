from __future__ import annotations

from typing import Any, Optional, Tuple

import pygame

from reborn_protocol.gs2 import to_bool, to_num, to_str

from .base import GuiControl
from .basic_controls import GuiButtonBaseCtrl, GuiButtonCtrl
from .profiles import _draw_label, _font, _shade
from .profiles import _fill_rect  # noqa: F401  - kept: original import block (star-import consumers rely on it)
from .skins import _Skin  # noqa: F401  - kept: original import block (star-import consumers rely on it)
from typing import List  # noqa: F401  - kept: original import block (star-import consumers rely on it)


class GuiCheckBoxCtrl(GuiButtonBaseCtrl):
    """Rendered as a small box with a checked state. Registers nothing of
    its own (GuiCheckBoxCtrlProperties.cpp:3-6 is a bare constructor) --
    the whole surface is GuiButtonBaseCtrl's; it only defaults `buttontype`
    to ToggleButton (GuiCheckBoxCtrl.cpp:25-35)."""

    CTRL_CLASS = "GuiCheckBoxCtrl"
    DEFAULT_BUTTON_TYPE = 1

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 16.0, 16.0

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        prof = self.resolve_profile()
        r = self.rect()
        box = pygame.Rect(r.x, r.y, min(r.width, r.height) or 16, min(r.width, r.height) or 16)
        base = (prof.bg if prof.bg is not None else prof.title_bg)[:3]
        bg = _shade(base, 0.75) if self.pressed else base
        border = (150, 190, 255) if self.hovered else prof.border
        pygame.draw.rect(surf, bg, box)
        pygame.draw.rect(surf, border, box, 1)
        if self.checked:
            pygame.draw.line(surf, prof.fg, box.topleft, box.bottomright, 2)
            pygame.draw.line(surf, prof.fg, box.bottomleft, box.topright, 2)
        if self.text and fonts is not None:
            label = _font(fonts, prof).render(self.text, True, prof.fg)
            surf.blit(label, (box.right + 6, box.y + (box.height - label.get_height()) // 2))


class GuiRadioCtrl(GuiCheckBoxCtrl):
    """Same as GuiCheckBoxCtrl visually (a filled circle instead of a box);
    it only defaults `buttontype` to RadioButton (GuiRadioCtrl.cpp:18-24).
    Mutual exclusion runs on activation and is scoped by `groupnum` -- see
    GuiButtonBaseCtrl.on_action()."""

    CTRL_CLASS = "GuiRadioCtrl"
    DEFAULT_BUTTON_TYPE = 2

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        prof = self.resolve_profile()
        r = self.rect()
        d = min(r.width, r.height) or 16
        center = (r.x + d // 2, r.y + d // 2)
        base = (prof.bg if prof.bg is not None else prof.title_bg)[:3]
        bg = _shade(base, 0.75) if self.pressed else base
        border = (150, 190, 255) if self.hovered else prof.border
        pygame.draw.circle(surf, bg, center, d // 2)
        pygame.draw.circle(surf, border[:3], center, d // 2, 1)
        if self.checked:
            pygame.draw.circle(surf, prof.fg, center, max(1, d // 4))
        if self.text and fonts is not None:
            label = _font(fonts, prof).render(self.text, True, prof.fg)
            surf.blit(label, (r.x + d + 6, r.y + (d - label.get_height()) // 2))


class GuiBitmapCtrl(GuiControl):
    """Renders an image (by filename, resolved via the game's SpriteManager)
    stretched to fit the control's rect, or TILED when `tile` is set.

    `wrap` is an alias of `tile` -- one field, two names, identical accessor
    pointers (FourPlay quattroplay/src/gui/GuiBitmapCtrlProperties.cpp:95-112).
    `image` is ours, not the reference's: no such property exists on this
    class."""

    CTRL_CLASS = "GuiBitmapCtrl"
    _TORQUE_PROPS = GuiControl._TORQUE_PROPS | frozenset(
        {"bitmap", "image", "bitmaprectangle", "fullbitmap", "tile", "wrap"})
    _METHOD_NAMES = GuiControl._METHOD_NAMES | frozenset({"setbitmap"})

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.bitmap = ""
        self.tile = False
        self._scaled_cache: Optional[Tuple[str, Tuple[int, int]]] = None
        self._scaled_surf: Optional[pygame.Surface] = None

    def get(self, key: str) -> Any:
        k = key.lower()
        if k in ("bitmap", "image"):
            return self.bitmap
        if k in ("tile", "wrap"):
            return 1.0 if self.tile else 0.0
        return super().get(k)

    def set(self, key: str, value: Any) -> None:
        k = key.lower()
        if k in ("bitmap", "image"):
            self.bitmap = to_str(value)
            return
        if k in ("tile", "wrap"):
            self.tile = to_bool(value)
            return
        super().set(k, value)

    def _m_setbitmap(self, *args) -> float:
        """setBitmap(name): identical to writing `bitmap`
        (GuiBitmapCtrlProperties.cpp:52-55)."""
        self.bitmap = to_str(args[0]) if args else ""
        return 0.0

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        r = self.rect()
        img = sprite_mgr.load_sheet(self.bitmap) if (sprite_mgr and self.bitmap) else None
        if img is not None:
            if self.tile:
                prev = surf.get_clip()
                surf.set_clip(r if prev is None else r.clip(prev))
                iw, ih = img.get_size()
                for ty in range(r.y, r.bottom, max(1, ih)):
                    for tx in range(r.x, r.right, max(1, iw)):
                        surf.blit(img, (tx, ty))
                surf.set_clip(prev)
                return
            key = (self.bitmap, r.size)
            if self._scaled_cache != key:
                self._scaled_surf = (img if img.get_size() == r.size
                                     else pygame.transform.smoothscale(img, r.size))
                self._scaled_cache = key
            surf.blit(self._scaled_surf, r.topleft)
            return
        # not cached yet: fetch via the normal file-request path and draw
        # nothing meanwhile (the official client draws no placeholder --
        # scripts probe getimgwidth() themselves)
        if self.bitmap and self._manager is not None:
            self._manager.request_image(self.bitmap)


class GuiShowImgCtrl(GuiBitmapCtrl):
    """Same image control as GuiBitmapCtrl (filename via the `bitmap`/`image`
    property, resolved through the game's SpriteManager and stretched to
    fit, cached by (bitmap-name, rect-size) -- see GuiBitmapCtrl). Some GS2
    scripts spell this control's class name one way, some the other; the
    C# client renders both identically, so this subclass only changes
    CTRL_CLASS and reuses GuiBitmapCtrl's get/set/_draw_self as-is."""

    CTRL_CLASS = "GuiShowImgCtrl"


class GuiBitmapButtonCtrl(GuiButtonCtrl):
    """A button whose face is a bitmap (Login's 2001-style buttons and
    Mobile's on-screen keys). Clicking behaves exactly like GuiButtonCtrl --
    only the face differs.

    Three separate faces, one per mouse state, are what the reference
    registers: `normalbitmap` / `mouseoverbitmap` / `pressedbitmap`, all
    routed through setBitmap(name, slot) with slots 0/1/2 (FourPlay
    quattroplay/src/gui/GuiBitmapButtonCtrlProperties.cpp:5-33, table
    :40-67). `bitmap`/`image` are ours and stand in for the normal face --
    the class has no property of either name."""

    CTRL_CLASS = "GuiBitmapButtonCtrl"
    _BITMAP_SLOTS = ("normalbitmap", "mouseoverbitmap", "pressedbitmap")
    _TORQUE_PROPS = GuiButtonCtrl._TORQUE_PROPS | frozenset(
        ("bitmap", "image") + _BITMAP_SLOTS)
    _METHOD_NAMES = GuiButtonCtrl._METHOD_NAMES | frozenset({"setbitmap"})

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.bitmaps = ["", "", ""]

    @property
    def bitmap(self) -> str:
        return self.bitmaps[0]

    @bitmap.setter
    def bitmap(self, value: Any) -> None:
        self.bitmaps[0] = to_str(value)

    def face(self) -> str:
        """The bitmap for the current mouse state, falling back to the
        normal face (an unset hover/press slot is not a blank button)."""
        slot = 2 if self.pressed else (1 if self.hovered else 0)
        return self.bitmaps[slot] or self.bitmaps[0]

    def get(self, key: str) -> Any:
        k = key.lower()
        if k in ("bitmap", "image"):
            return self.bitmaps[0]
        if k in self._BITMAP_SLOTS:
            return self.bitmaps[self._BITMAP_SLOTS.index(k)]
        return super().get(k)

    def set(self, key: str, value: Any) -> None:
        k = key.lower()
        if k in ("bitmap", "image"):
            self.bitmaps[0] = to_str(value)
            return
        if k in self._BITMAP_SLOTS:
            self.bitmaps[self._BITMAP_SLOTS.index(k)] = to_str(value)
            return
        super().set(k, value)

    def _m_setbitmap(self, *args) -> float:
        """setBitmap(name, slot) -- note the two-argument signature, unlike
        GuiBitmapCtrl's one-argument one (funcDefs `"si"`, :70-80)."""
        if len(args) >= 2:
            slot = int(to_num(args[1]))
            if 0 <= slot < len(self.bitmaps):
                self.bitmaps[slot] = to_str(args[0])
        return 0.0

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        r = self.rect()
        name = self.face()
        img = (sprite_mgr.load_sheet(name)
               if (sprite_mgr is not None and name) else None)
        if img is None:
            if name and self._manager is not None:
                self._manager.request_image(name)
            super()._draw_self(surf, fonts, sprite_mgr)
            return
        if img.get_size() != r.size:
            img = pygame.transform.smoothscale(img, r.size)
        surf.blit(img, r.topleft)
        if self.text and fonts is not None:
            prof = self.resolve_profile()
            font = _font(fonts, prof)
            width = font.size(self.text)[0]
            _draw_label(surf, font, self.text, prof.fg,
                        (r.centerx - width // 2,
                         r.centery - font.get_height() // 2),
                        prof.text_shadow)

