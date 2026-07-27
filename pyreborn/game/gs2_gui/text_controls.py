from __future__ import annotations

from typing import Any, List, Optional, Tuple

import pygame

from reborn_protocol.gs2 import to_bool, to_num, to_str

from .base import GuiControl
from .basic_controls import GuiTextCtrl
from .mltext import _MLSegment, parse_mltext
from .profiles import _BLUE_FILL, _draw_border, _draw_label, _fill_rect, _font, logger
from .skins import _Skin  # noqa: F401  - kept: original import block (star-import consumers rely on it)
from typing import Dict  # noqa: F401  - kept: original import block (star-import consumers rely on it)


class GuiMLTextCtrl(GuiControl):
    """Multi-line Torque-ML text: minimal markup handling (see
    parse_mltext) with word-wrap and inline bold/italic/size/color runs.
    Height auto-grows to the laid-out content (Torque MLText autosizes;
    the script-set height of 10-14px is just a seed) so an enclosing
    GuiScrollCtrl clips/scrolls it instead of the text vanishing."""

    CTRL_CLASS = "GuiMLTextCtrl"
    #: reflow() is registered on the ML-text control, NOT on GuiTextListCtrl
    #: (quattroplay/src/gui/GuiMLTextCtrlProperties.cpp:334, body :233-236).
    #: The live callers are the RC log windows, which append lines and then
    #: reflow before scrolling to the bottom.
    _METHOD_NAMES = GuiControl._METHOD_NAMES | frozenset({"reflow"})
    #: the rest of the own table (GuiMLTextCtrlProperties.cpp:305-319; `text`
    #: comes from the base) -- all of these are written bare in construction
    #: blocks, which the VM's existence gate drops unless the name is claimed
    _TORQUE_PROPS = GuiControl._TORQUE_PROPS | frozenset({
        "allowedtags", "alpha", "cursorposition", "deniedsound",
        "disallowedtags", "htmllinks", "htmlcompatibility", "maxchars",
        "parsetags", "plaintext", "urlbase", "wordwrap",
    })

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 160.0, 80.0
        self._ml_cache_key = None
        self._ml_paragraphs = None
        #: (width, height) of the last laid-out content -- reflow() reports
        #: the page extents and it can only measure them at paint time
        self._content_extent: Optional[Tuple[float, float]] = None
        #: [(canvas-space Rect, href)] recorded at draw time, and the href
        #: pressed by the last mouse-down -- the onURL press/release pair
        #: (GuiMLTextCtrl.cpp:939-957 press, :1157-1181 release-on-same-link)
        self._link_rects: List[Tuple[pygame.Rect, str]] = []
        self._pressed_link: Optional[str] = None

    def _link_at(self, pos) -> Optional[str]:
        for rect, href in self._link_rects:
            if rect.collidepoint(pos):
                return href
        return None

    def pointer_down(self, manager, pos) -> bool:
        self._pressed_link = self._link_at(pos)
        return self._pressed_link is not None

    def pointer_up(self, manager, pos) -> None:
        pressed, self._pressed_link = self._pressed_link, None
        if pressed is not None and self._link_at(pos) == pressed:
            # bare tokens pass through unresolved -- with no page base URL
            # getAbsoluteLinkURL is the identity (THTMLPage.cpp:278-287;
            # Login compares `url == "emailcheck"`)
            self.fire_event("onurl", pressed)

    def word_wrap(self) -> bool:
        return to_bool(self._members.get("wordwrap", 1))

    def _m_reflow(self, *args) -> float:
        """reflow(): re-lay-out, RESIZE to the page's extents and fire
        `onReflow(width, height)` -- it is not a pure layout pass
        (GuiMLTextCtrl::reflowResize, quattroplay/src/gui/GuiMLTextCtrl.cpp:
        1609-1648: height from the page's max height, width from its max
        width + 1 when word-wrap is off, then resize(), then the event).
        Our layout is lazy and keyed on self.text, so this also drops the
        cache -- a script that mutated markup state without changing the
        text would otherwise keep the stale paragraph list."""
        self._ml_cache_key = None
        if self._content_extent is not None:
            content_w, content_h = self._content_extent
            self.height = content_h
            if not self.word_wrap():
                self.width = content_w + 1.0
        self.fire_event("onreflow", float(self.width), float(self.height))
        return 0.0

    def _paragraphs(self):
        if self._ml_cache_key != self.text:
            self._ml_cache_key = self.text
            try:
                self._ml_paragraphs = parse_mltext(self.text)
            except Exception:
                logger.exception("GS2 GUI: mltext parse failed")
                self._ml_paragraphs = [("left", [_MLSegment(
                    self.text, False, False, None, None, False)])]
        return self._ml_paragraphs

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        if not self.text or fonts is None:
            return
        prof = self.resolve_profile()
        r = self.rect()
        base_font = _font(fonts, prof)
        # `wordwrap = false` lets a line run past the control's width; the
        # reference's reflowResize then widens the control to fit it
        max_w = max(20, r.width) if self.word_wrap() else 0
        y = r.y
        widest = 0
        self._link_rects = []
        at = getattr(fonts, "at", None)

        def seg_font(seg):
            if at is None:
                return base_font
            size = seg.size if seg.size else prof.font_size
            try:
                return at(size, seg.bold or prof.font_bold, seg.italic)
            except TypeError:       # older fonts objects: at(size, bold)
                return at(size, seg.bold or prof.font_bold)

        for align, segments in self._paragraphs():
            # split segments into word chunks that carry their style
            words: List[Tuple[str, Any]] = []
            for seg in segments:
                for piece in seg.text.split(" "):
                    if piece:
                        words.append((piece, seg))
            if not words:
                y += base_font.get_height()
                continue
            # greedy wrap
            lines: List[List[Tuple[str, Any]]] = [[]]
            line_w = 0
            for word, seg in words:
                font = seg_font(seg)
                w = font.size(word + " ")[0]
                if lines[-1] and max_w and line_w + w > max_w:
                    lines.append([])
                    line_w = 0
                lines[-1].append((word, seg))
                line_w += w
            for line in lines:
                line_h = max(seg_font(seg).get_height()
                             for _w, seg in line)
                total_w = sum(seg_font(seg).size(word + " ")[0]
                              for word, seg in line)
                widest = max(widest, total_w)
                if align == "center":
                    x = r.x + max(0, (r.width - total_w) // 2)
                elif align == "right":
                    x = r.x + max(0, r.width - total_w)
                else:
                    x = r.x
                for word, seg in line:
                    font = seg_font(seg)
                    color = seg.color if seg.color is not None else prof.fg
                    label = _draw_label(
                        surf, font, word, color,
                        (x, y + line_h - font.get_height()),
                        prof.text_shadow)
                    if seg.link:
                        pygame.draw.line(
                            surf, color, (x, y + line_h - 2),
                            (x + label.get_width(), y + line_h - 2))
                    if seg.href:
                        self._link_rects.append((pygame.Rect(
                            int(x), int(y), label.get_width(),
                            max(line_h, font.get_height())), seg.href))
                    x += font.size(word + " ")[0]
                y += line_h
        # autosize so ancestor scroll controls know the content extent
        self._content_extent = (float(widest), float(y - r.y))
        self.height = max(self.height, float(y - r.y))


class GuiScrollCtrl(GuiControl):
    """Clips its children to its own rect and offsets them by
    scroll_x/scroll_y (adjusted by mouse wheel -- GS2GuiManager). Draws a
    skinned vertical scrollbar (guiblue_scroll.png: row0 = up/down arrow
    states, rows1-4 = thumb top/mid/bottom + track) when the content
    overflows and the profile's vscrollbar mode allows it."""

    CTRL_CLASS = "GuiScrollCtrl"

    def child_state_offset(self) -> Tuple[float, float]:
        return -self.scroll_x, -self.scroll_y

    def scroll_container(self):
        return self
    SCROLLBAR_W = 17
    #: byte-exact values `hscrollbar`/`vscrollbar` accept; anything else is a
    #: silent no-op that leaves the mode alone (writeScrollbarMode, FourPlay
    #: quattroplay/src/gui/GuiScrollCtrlProperties.cpp:23-34)
    SCROLLBAR_MODES = ("alwaysOn", "alwaysOff", "dynamic")

    _TORQUE_PROPS = GuiControl._TORQUE_PROPS | frozenset({
        "childmargin", "constantthumbheight", "scrollpos", "wheelscrolllines",
    })

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 160.0, 120.0
        self.scroll_x = 0.0
        self.scroll_y = 0.0

    _METHOD_NAMES = GuiControl._METHOD_NAMES | frozenset(
        {"scrolldelta", "scrollto", "scrolltotop"})

    def get(self, key: str) -> Any:
        if key.lower() == "scrollpos":
            return [float(self.scroll_x), float(self.scroll_y)]
        return super().get(key)

    def set(self, key: str, value: Any) -> None:
        k = key.lower()
        if k == "scrollpos":
            # the setter IS scrollTo(x, y) (GuiScrollCtrlProperties.cpp:71-80)
            pair = self._num_pair(value)
            if pair is not None:
                self.scroll_to(*pair)
            return
        if k in ("hscrollbar", "vscrollbar"):
            if to_str(value) not in self.SCROLLBAR_MODES:
                return
        elif k == "wheelscrolllines" and to_num(value) <= 0:
            return
        super().set(k, value)

    def content_height(self) -> float:
        bottom = 0.0
        for c in self.children:
            if c.visible:
                bottom = max(bottom, c.y + c.height)
        return bottom

    def content_width(self) -> float:
        right = 0.0
        for c in self.children:
            if c.visible:
                right = max(right, c.x + c.width)
        return right

    def max_scroll_y(self) -> float:
        return max(0.0, self.content_height() - self.height)

    def max_scroll_x(self) -> float:
        return max(0.0, self.content_width() - self.width)

    def scroll_to(self, x: float, y: float) -> None:
        """scrollTo(x, y), with the reference's three surprises: a control
        with NO children cannot be scrolled at all (not even to 0), the
        clamped position is compared against the old one, and `onScrolled`
        is invoked with (newX, newY, dx, dy) BEFORE the new position is
        stored -- so a handler reading `.scrollpos` sees the pre-scroll
        value (quattroplay/src/gui/GuiScrollCtrl.cpp:909-943)."""
        if not self.children:
            return
        new_x = max(0.0, min(to_num(x), self.max_scroll_x()))
        new_y = max(0.0, min(to_num(y), self.max_scroll_y()))
        old_x, old_y = self.scroll_x, self.scroll_y
        if new_x == old_x and new_y == old_y:
            return
        self.fire_event("onscrolled", new_x, new_y, new_x - old_x,
                        new_y - old_y)
        self.scroll_x, self.scroll_y = new_x, new_y

    def _m_scrollto(self, *args) -> float:
        x, y = self._coord_arg(args)
        self.scroll_to(x, y)
        return 0.0

    def _m_scrolldelta(self, *args) -> float:
        """scrollDelta(dx, dy): scroll BY the given amount (Login Mobile's
        gui_scroll class drives its touch-drag scrolling through it)."""
        dx, dy = self._coord_arg(args)
        self.scroll_to(self.scroll_x + dx, self.scroll_y + dy)
        return 0.0

    def _m_scrolltotop(self, *args) -> float:
        """scrollToTop(): scrollTo(0, 0) -- it resets the HORIZONTAL scroll
        too (GuiScrollCtrlProperties.cpp:144-147)."""
        self.scroll_to(0.0, 0.0)
        return 0.0

    def _m_scrolltobottom(self, *args) -> float:
        """scrollToBottom(): scrollTo(0, INT_MAX), i.e. x is reset (:139-142)."""
        self.scroll_to(0.0, self.max_scroll_y())
        return 0.0

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        prof = self.resolve_profile()
        r = self.rect()
        skin = self._skin(prof, sprite_mgr)
        _fill_rect(surf, prof.bg, r)
        _draw_border(surf, r, prof, skin)
        # vertical scrollbar on overflow
        vmode = to_str(self._members.get("vscrollbar", "dynamic")).lower()
        max_scroll = self.max_scroll_y()
        if vmode == "alwaysoff" or max_scroll <= 0 or r.height < 40:
            return
        self.scroll_y = max(0.0, min(self.scroll_y, max_scroll))
        bw = self.SCROLLBAR_W
        bar = pygame.Rect(r.right - bw, r.y, bw, r.height)
        track = pygame.Rect(bar.x, bar.y + bw, bw, max(0, bar.height - 2 * bw))
        frac = r.height / max(1.0, self.content_height())
        thumb_h = max(20, int(track.height * frac))
        thumb_y = track.y + int((track.height - thumb_h) *
                                (self.scroll_y / max_scroll))
        skin = self._skin(prof, sprite_mgr)
        if skin is not None and len(skin.rows) >= 5 and len(skin.rows[0]) >= 5:
            alpha = int(255 * prof.transparency)
            skin.blit_scaled(surf, skin.rows[0][1],
                             pygame.Rect(bar.x, bar.y, bw, bw), alpha)
            skin.blit_scaled(surf, skin.rows[0][4],
                             pygame.Rect(bar.x, bar.bottom - bw, bw, bw), alpha)
            if len(skin.rows[4]) >= 2:
                skin.blit_scaled(surf, skin.rows[4][1], track, alpha)
            cap = min(6, thumb_h // 3)
            if len(skin.rows[1]) >= 2 and len(skin.rows[2]) >= 2 \
                    and len(skin.rows[3]) >= 2:
                skin.blit_scaled(surf, skin.rows[1][1],
                                 pygame.Rect(bar.x, thumb_y, bw, cap), alpha)
                skin.blit_scaled(surf, skin.rows[2][1],
                                 pygame.Rect(bar.x, thumb_y + cap, bw,
                                             thumb_h - 2 * cap), alpha)
                skin.blit_scaled(surf, skin.rows[3][1],
                                 pygame.Rect(bar.x, thumb_y + thumb_h - cap,
                                             bw, cap), alpha)
            return
        # solid fallback
        _fill_rect(surf, (16, 32, 80, 200), bar)
        _fill_rect(surf, _BLUE_FILL,
                   pygame.Rect(bar.x + 2, thumb_y, bw - 4, thumb_h),
                   border_radius=4)


class GuiTextEditCtrl(GuiTextCtrl):
    """Single-line editable text field. Enter fires onAction (GS2GuiManager
    routes focus + key/Enter handling; `.text` is the live edit buffer).

    Chain is GuiTextEditCtrl -> GuiTextCtrl (quattroplay/src/gui/
    GuiTextEditCtrlProperties.cpp:57), which is where `maxchars` and its
    truncation come from."""

    CTRL_CLASS = "GuiTextEditCtrl"
    can_key_focus = True

    def pointer_down(self, manager, pos) -> bool:
        manager._set_focus(self)
        return True
    _METHOD_NAMES = GuiControl._METHOD_NAMES | frozenset(
        {"setselection", "getselection"})
    _TORQUE_PROPS = GuiTextCtrl._TORQUE_PROPS | frozenset({
        "password", "inputtype", "showcursor", "deniedsound",
    })

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 150.0, 22.0
        self.focused = False
        #: [start, end] character range, empty when start == end. Login's
        #: chat bar recalls a message and then selects all of it
        #: (`ChatBar.setSelection(0, ChatBar.text.length())`) precisely so
        #: the next keystroke REPLACES it -- see take_selection().
        self.selection: Tuple[int, int] = (0, 0)

    @property
    def max_len(self) -> int:
        """Typing cap: `maxchars`, since every text change routes through
        the truncating GuiTextCtrl::setText (GuiTextEditCtrl::setText ->
        setTextKeepCursor, quattroplay/src/gui/GuiTextEditCtrl.cpp:
        1072-1079)."""
        return self.maxchars if self.maxchars > 0 else 1 << 30

    def get(self, key: str) -> Any:
        k = key.lower()
        if k == "password":
            return 1.0 if self.is_password() else 0.0
        if k == "inputtype":
            return to_str(self._members.get("inputtype", "default"))
        return super().get(k)

    def set(self, key: str, value: Any) -> None:
        k = key.lower()
        if k == "password":
            # `password` and `inputtype` are the same storage under two
            # names, and clearing it writes "default" rather than restoring
            # the previous type (setPasswordText, GuiTextEditCtrl.cpp:
            # 308-316; getPasswordText is `m_inputType == "password"`)
            super().set("inputtype", "password" if to_bool(value) else "default")
            return
        if k == "text":
            # the `text` PROPERTY setter additionally zeroes both selection
            # anchors; the inherited settext() method does not
            # (GuiTextEditCtrlProperties.cpp:31-36 vs
            # GuiTextCtrlProperties.cpp:30-33)
            super().set(k, value)
            self.selection = (0, 0)
            return
        super().set(k, value)

    def is_password(self) -> bool:
        return to_str(self._members.get("inputtype", "default")) == "password"

    def _m_setselection(self, *args) -> float:
        """setSelection(start, end): start clamps up to 0 and end down to
        the text length, and an INVERTED range zeroes BOTH ends rather than
        swapping them -- `setSelection(5, 2)` selects nothing
        (GuiTextEditCtrl::setSelection, quattroplay/src/gui/
        GuiTextEditCtrl.cpp:205-225)."""
        start = int(to_num(args[0])) if args else 0
        end = int(to_num(args[1])) if len(args) > 1 else start
        start = max(0, start)
        end = min(end, len(self.text))
        if end < start:
            start = end = 0
        self.selection = (start, end)
        return 0.0

    def _m_getselection(self, *args) -> List[float]:
        return [float(self.selection[0]), float(self.selection[1])]

    def take_selection(self) -> bool:
        """Consume a pending selection by deleting the selected characters.
        Returns whether anything was removed (the caller then inserts)."""
        start, end = self.selection
        self.selection = (0, 0)
        if start >= end or end > len(self.text):
            return False
        self.text = self.text[:start] + self.text[end:]
        return True

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        prof = self.resolve_profile()
        r = self.rect()
        skin = self._skin(prof, sprite_mgr)
        if skin is None or not skin.draw_nine(surf, r, 0,
                                              int(255 * prof.transparency)):
            _fill_rect(surf, prof.bg if prof.bg is not None
                       else prof.title_bg, r)
            pygame.draw.rect(surf,
                             (150, 190, 255) if self.focused else prof.border,
                             r, 2 if self.focused else 1)
        elif self.focused:
            pygame.draw.rect(surf, (150, 190, 255), r, 1)
        if fonts is None:
            return
        font = _font(fonts, prof)
        shown = "*" * len(self.text) if self.is_password() else self.text
        label = font.render(shown, True, prof.fg)
        surf.blit(label, (r.x + 4, r.centery - label.get_height() // 2))
        if self.focused and (pygame.time.get_ticks() // 500) % 2 == 0:
            cx = r.x + 4 + font.size(shown)[0]
            pygame.draw.line(surf, prof.fg, (cx, r.y + 3), (cx, r.bottom - 3), 1)


class GuiAccountPasswordCtrl(GuiTextEditCtrl):
    """The Login screen's password field (gr_LoginScreen_PassEdit). Same
    edit control, rendered masked -- the reference client never echoes the
    characters, and neither should a client whose credential surface is
    deliberately inert (see GS2ClientHost.stubbed).

    Masking is a RENDER-TIME substitution only (is_password() drives the
    base _draw_self), never a write through the text setter: setText fires
    onTextChanged, so masking by assignment would fire two script events
    per rendered frame -- the second carrying the real password."""

    CTRL_CLASS = "GuiAccountPasswordCtrl"

    def is_password(self) -> bool:
        return True


class GuiMLTextEditCtrl(GuiMLTextCtrl):
    """Editable multi-line text pane (Staff's script editor). Rendered with
    GuiMLTextCtrl's markup pipeline; setLines/getLines (GuiControl) are the
    surface the scripts actually drive it through, and focus/typing route
    through GS2GuiManager exactly as for GuiTextEditCtrl."""

    CTRL_CLASS = "GuiMLTextEditCtrl"
    can_key_focus = True

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.focused = False
        self.max_len = 65536


class GuiSliderCtrl(GuiControl):
    """Horizontal value slider (Login's Options sound/volume rows). Absent
    from the FourPlay build (mobile), so the surface is the Torque standard:
    `range` = "min max", `ticks`, `value`; dragging/clicking sets value and
    fires onAction."""

    CTRL_CLASS = "GuiSliderCtrl"
    _TORQUE_PROPS = GuiControl._TORQUE_PROPS | frozenset(
        {"range", "ticks", "value"})

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 120.0, 20.0
        self.value = 0.0

    def slider_range(self) -> Tuple[float, float]:
        pair = self._num_pair(self._members.get("range", "0 1"))
        return pair if pair is not None else (0.0, 1.0)

    def get(self, key: str) -> Any:
        if key.lower() == "value":
            return float(self.value)
        return super().get(key)

    def set(self, key: str, value: Any) -> None:
        if key.lower() == "value":
            lo, hi = self.slider_range()
            self.value = max(min(lo, hi), min(max(lo, hi), to_num(value)))
            return
        super().set(key, value)

    def pointer_down(self, manager, pos) -> bool:
        manager._set_focus(None)
        r = self.rect()
        if r.width > 8:
            lo, hi = self.slider_range()
            frac = min(1.0, max(0.0, (pos[0] - r.x - 4) / (r.width - 8)))
            self.set("value", lo + frac * (hi - lo))
            self.fire_action()
        return True

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        prof = self.resolve_profile()
        r = self.rect()
        track = pygame.Rect(r.x + 4, r.centery - 2, max(1, r.width - 8), 4)
        _fill_rect(surf, prof.bg if prof.bg is not None else _BLUE_FILL, track)
        pygame.draw.rect(surf, prof.border[:3], track, 1)
        lo, hi = self.slider_range()
        span = (hi - lo) or 1.0
        frac = min(1.0, max(0.0, (self.value - lo) / span))
        tx = track.x + int(frac * track.width)
        thumb = pygame.Rect(tx - 4, r.centery - 7, 8, 14)
        _fill_rect(surf, prof.title_bg, thumb)
        pygame.draw.rect(surf, prof.border[:3], thumb, 1)


class GuiTextEditSliderCtrl(GuiTextEditCtrl):
    """Numeric edit with spinner semantics (Torque standard; not in the
    FourPlay build). Rendered as the edit; `range`/`increment`/`format`
    are claimed so construction writes land."""

    CTRL_CLASS = "GuiTextEditSliderCtrl"
    _TORQUE_PROPS = GuiTextEditCtrl._TORQUE_PROPS | frozenset(
        {"range", "increment", "format"})


class GuiProgressCtrl(GuiControl):
    """Horizontal progress bar. `progress` is 0..1 (Login's IRC_Installer
    drives three of them off the update-package byte counts); the label, if
    any, is a child GuiTextCtrl, so this control only paints the bar."""

    CTRL_CLASS = "GuiProgressCtrl"
    _TORQUE_PROPS = GuiControl._TORQUE_PROPS | frozenset({"progress"})

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 150.0, 20.0
        self.progress = 0.0

    def get(self, key: str) -> Any:
        if key.lower() == "progress":
            return float(self.progress)
        return super().get(key)

    def set(self, key: str, value: Any) -> None:
        if key.lower() == "progress":
            self.progress = max(0.0, min(1.0, to_num(value)))
            return
        super().set(key, value)

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        prof = self.resolve_profile()
        r = self.rect()
        _fill_rect(surf, prof.bg if prof.bg is not None else prof.title_bg, r)
        filled = int(r.width * self.progress)
        if filled > 0:
            _fill_rect(surf, prof.title_bg,
                       pygame.Rect(r.x, r.y, filled, r.height))
        pygame.draw.rect(surf, prof.border[:3], r, 1)

