from __future__ import annotations

from typing import Any, List, Tuple

import pygame

from reborn_protocol.gs2 import to_num, to_str

from .base import GuiControl
from .profiles import _fill_rect, _font, _profile_fields, _profile_from_fields, _shade
from .profiles import _draw_border, _draw_label  # noqa: F401  - kept: original import block (star-import consumers rely on it)
from reborn_protocol.gs2 import to_bool  # noqa: F401  - kept: original import block (star-import consumers rely on it)
from typing import Dict, Optional  # noqa: F401  - kept: original import block (star-import consumers rely on it)


class GuiPopUpEditCtrl(GuiControl):
    """Single-selection combo box with a manager-rendered popup list."""

    CTRL_CLASS = "GuiPopUpEditCtrl"

    def pointer_down(self, manager, pos) -> bool:
        manager._set_focus(None)
        manager._set_pressed(self)
        manager._open_popup_for(self)
        return True
    # getSelectedRow/getSelectedText also reach this control by METHOD form
    # (call_builtin's obj branch), but with-scope bare calls only consult
    # get(), so they must be declared here too.
    _METHOD_NAMES = GuiControl._METHOD_NAMES | frozenset(
        {"getselectedrow", "getselectedtext", "setselectedrow",
         "setselectedbyid", "getrowtext", "clear",
         "setselected", "findtext", "rowcount", "setselectedbytext"})

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 150.0, 22.0
        self.rows: List[Tuple[Any, str]] = []
        self.selected_row = -1
        self.popup_open = False
        self.hover_row = -1

    def add_row(self, row_id: Any, text: Any) -> float:
        self.rows.append((row_id, to_str(text)))
        return float(len(self.rows) - 1)

    # popup rows are (id, text) pairs with their own draw path -- keep the
    # base class's generic list-row methods from shadowing them
    def _m_addrow(self, *args):
        return self.add_row(args[0] if args else None,
                            args[1] if len(args) > 1 else "")

    def _m_clearrows(self, *args):
        return self.clear_rows()

    def clear_rows(self) -> float:
        self.rows.clear()
        self.selected_row = -1
        self.text = ""
        self.popup_open = False
        self.hover_row = -1
        return 0.0

    def get_selected_row(self) -> Any:
        if 0 <= self.selected_row < len(self.rows):
            return self.rows[self.selected_row][0]
        return -1.0

    def _m_getselectedrow(self, *args) -> Any:
        return self.get_selected_row()

    def _m_clear(self, *args) -> float:
        return self.clear_rows()

    def _m_getselectedtext(self, *args) -> str:
        """getSelectedText(): the selected row's LABEL (Login's staff
        sprite-editor weapon reads its batch-mode combo that way)."""
        if 0 <= self.selected_row < len(self.rows):
            return self.rows[self.selected_row][1]
        return ""

    def _m_getrowtext(self, *args) -> str:
        return self.get_row_text(args[0] if args else None)

    def _m_setselectedrow(self, *args) -> float:
        if args:
            self.select_row(int(to_num(args[0])))
        return 0.0

    def _m_setselectedbyid(self, *args) -> float:
        if args:
            wanted = to_str(args[0])
            for index, (row_id, _text) in enumerate(self.rows):
                if to_str(row_id) == wanted:
                    self.select_row(index)
                    break
        return 0.0

    #: setSelected(id) is the reference spelling of setSelectedById: the
    #: engine's GuiPopUpMenuCtrl::setSelected resolves its argument with
    #: findEntryById, NOT as a row index (FourPlay quattroplay/src/gui/
    #: GuiPopUpMenuCtrl.cpp:316-327; binding GuiPopUpMenuCtrlProperties.cpp:74
    #: `{"setselected", false, 'v', "i"}`). Live sites construct the combo and
    #: call it in the same with-block
    #: (GServer-v2/bin/servers/era/weapons/weaponGraalNet.txt:106,
    #: GServer-v2/bin/servers/era/scripts/pdamod_browser.txt:60), where row ids
    #: and indices happen to coincide.
    _m_setselected = _m_setselectedbyid

    def _m_rowcount(self, *args) -> float:
        """rowCount(): the popup has its OWN binding for this
        (GuiPopUpMenuCtrlProperties.cpp:73), separate from the text list's --
        the popup's chain is GuiPopUpMenuCtrl -> GuiTextCtrl, so it inherits
        nothing from GuiTextListCtrl."""
        return float(len(self.rows))

    def _m_setselectedbytext(self, *args) -> float:
        """setSelectedByText(text) (:75). Same no-match-is-a-no-op rule the
        text list's version has."""
        row = self._m_findtext(*args)
        if row >= 0:
            self.select_row(int(row))
        return 0.0

    def _m_findtext(self, *args) -> float:
        """findText(text) -> the matching row's INDEX, or -1.

        Reference: GuiPopUpMenuCtrlProperties.cpp:69 `{'i', "s"}` ->
        GuiTextListCtrl::findEntryByText, which returns the ARRAY POSITION
        (FourPlay quattroplay/src/gui/GuiTextListCtrl.cpp:747-758) -- not the
        row id, and -1 when nothing matches."""
        wanted = to_str(args[0]) if args else ""
        for index, (_row_id, text) in enumerate(self.rows):
            if to_str(text) == wanted:
                return float(index)
        return -1.0

    def get_row_text(self, row_id: Any) -> str:
        for item_id, text in self.rows:
            if item_id == row_id or to_str(item_id) == to_str(row_id):
                return text
        return ""

    def select_row(self, index: int) -> bool:
        if not 0 <= index < len(self.rows) or index == self.selected_row:
            return False
        self.selected_row = index
        row_id, self.text = self.rows[index]
        # (entryid, entrytext, entryindex) per the reference convention --
        # member closures that only declare (id, text) simply never bind the
        # extra index argument.
        self.fire_event("onselect", row_id, self.text, float(index))
        self.fire_action()
        return True

    def popup_rect(self) -> pygame.Rect:
        r = self.rect()
        return pygame.Rect(r.x, r.bottom, r.width, int(self.height) * len(self.rows))

    def popup_row_at(self, pos) -> int:
        pr = self.popup_rect()
        if not pr.collidepoint(pos) or not self.rows:
            return -1
        return min(len(self.rows) - 1,
                   (pos[1] - pr.y) // max(1, int(self.height)))

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        prof = self.resolve_profile()
        r = self.rect()
        fill = prof.bg if prof.bg is not None else prof.title_bg
        if self.pressed:
            fill = _shade(fill, 0.75)
        elif self.hovered:
            fill = _shade(fill, 1.2)
        _fill_rect(surf, fill, r)
        pygame.draw.rect(surf, prof.border[:3], r, 1)
        arrow_w = min(r.height, 20)
        arrow = pygame.Rect(r.right - arrow_w, r.y, arrow_w, r.height)
        pygame.draw.line(surf, prof.border[:3], arrow.topleft, arrow.bottomleft, 1)
        cx, cy = arrow.center
        pygame.draw.polygon(surf, prof.fg,
                            [(cx - 4, cy - 2), (cx + 4, cy - 2), (cx, cy + 3)])
        if self.text and fonts is not None:
            label = _font(fonts, prof).render(self.text, True, prof.fg)
            surf.blit(label, (r.x + 4, r.centery - label.get_height() // 2))

    def _row_profile(self):
        """The profile styling popup ROWS. One profile for everything here;
        GuiContextMenuCtrl overrides -- its rows belong to the embedded text
        list, styled by `textprofile`."""
        return self.resolve_profile()

    def draw_popup(self, surf, fonts) -> None:
        if not self.popup_open or not self.rows:
            return
        prof = self.resolve_profile()
        row_prof = self._row_profile()
        pr = self.popup_rect()
        row_h = max(1, int(self.height))
        _fill_rect(surf, prof.bg if prof.bg is not None else (16, 32, 96, 240), pr)
        for index, (_row_id, text) in enumerate(self.rows):
            rr = pygame.Rect(pr.x, pr.y + index * row_h, pr.width, row_h)
            if index == self.hover_row:
                _fill_rect(surf, _shade(prof.title_bg, 1.2), rr)
            if fonts is not None:
                label = _font(fonts, row_prof).render(text, True, row_prof.fg)
                surf.blit(label, (rr.x + 4, rr.centery - label.get_height() // 2))
        pygame.draw.rect(surf, prof.border[:3], pr, 1)


class GuiPopUpMenuCtrl(GuiPopUpEditCtrl):
    """The non-editable spelling of the same combo box. Login's staff
    sprite-editor weapon builds every one of its selectors as
    GuiPopUpMenuCtrl and then calls getSelectedRow()/getSelectedText() on
    them."""

    CTRL_CLASS = "GuiPopUpMenuCtrl"


class GuiFrameSetCtrl(GuiControl):
    """A splitter: divides its own client area into `rowcount` x
    `columncount` cells and gives each child ONE cell, in the order the
    children were added (row-major).

    Divider positions come from setRowOffset(i, y) / setColumnOffset(i, x);
    dividers 0 and `count` are implicit (0 and the frameset's own extent),
    and a divider nobody set falls back to an even split. The Global Chat
    window is one row by two columns with `setColumnOffset(1, 150)` over a
    600x400 client area (Preagonal/gbf/bytecode/login/
    _Serverlist_Chat.gs2bc.gs2:570-616), i.e. a 150-wide channel list beside
    a 450-wide chat panel.

    Sizing HAS to happen when a child is added, not at render time: the
    scripts build a cell's contents in a following `with (<cell>) {...}`
    block that reads `<cell>.clientwidth`/`.clientheight` to size them
    (:617-660).
    """

    CTRL_CLASS = "GuiFrameSetCtrl"

    def _cell_bounds(self, count: int, span: float, key: str) -> List[float]:
        """The `count`+1 divider positions along one axis."""
        count = max(1, count)
        given = self._members.get(key) or {}
        out = [0.0]
        for i in range(1, count):
            v = given.get(i)
            out.append(to_num(v) if v is not None else span * i / count)
        out.append(span)
        # dividers must stay ordered and inside the frame
        for i in range(1, len(out)):
            out[i] = max(out[i - 1], min(out[i], span))
        return out

    def relayout(self) -> None:
        rows = max(1, int(to_num(self._members.get("rowcount") or 1)))
        cols = max(1, int(to_num(self._members.get("columncount") or 1)))
        ys = self._cell_bounds(rows, float(self.client_height()), "_row_offsets")
        xs = self._cell_bounds(cols, float(self.client_width()), "_column_offsets")
        for index, child in enumerate(self.children):
            if child.is_profile:
                continue
            r, c = divmod(index, cols)
            if r >= rows:
                break               # more children than cells: leave as-is
            child.x, child.y = xs[c], ys[r]
            child.width = max(0.0, xs[c + 1] - xs[c])
            child.height = max(0.0, ys[r + 1] - ys[r])

    def add_child(self, child: "GuiControl") -> bool:
        added = super().add_child(child)
        if added:
            self.relayout()
        return added

    def set(self, key: str, value: Any) -> None:
        super().set(key, value)
        if key.lower() in ("rowcount", "columncount", "extent", "clientextent",
                           "width", "height"):
            self.relayout()

    def _m_setcolumnoffset(self, *args) -> float:
        rv = super()._m_setcolumnoffset(*args)
        self.relayout()
        return rv

    def _m_setrowoffset(self, *args) -> float:
        rv = super()._m_setrowoffset(*args)
        self.relayout()
        return rv


class GuiStretchCtrl(GuiControl):
    """A container whose `clientwidth`/`clientheight`/`clientextent` mean
    something DIFFERENT from every other control's: this class redeclares
    all three (FourPlay quattroplay/src/gui/GuiStretchCtrlProperties.cpp:
    46-48, bodies :6-43) against its own virtual content size `m_size`,
    where GuiControl's versions derive the client area from the outer
    bounds. Child replaces parent, so on a stretch control the write does
    NOT resize the outer bounds.

    The reference additionally calls resizeChildren(old, new) on each such
    write; that body was not read, so no child rescaling is modelled here.
    """

    CTRL_CLASS = "GuiStretchCtrl"

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.client_size = (self.width, self.height)

    def client_width(self) -> float:
        return float(self.client_size[0])

    def client_height(self) -> float:
        return float(self.client_size[1])

    def set(self, key: str, value: Any) -> None:
        k = key.lower()
        if k in ("clientextent", "clientwidth", "clientheight"):
            if k == "clientwidth":
                pair = (to_num(value), self.client_size[1])
            elif k == "clientheight":
                pair = (self.client_size[0], to_num(value))
            else:
                pair = self._num_pair(value)
            if pair is not None:
                self.client_size = (to_num(pair[0]), to_num(pair[1]))
            return
        super().set(k, value)


class GuiContextMenuCtrl(GuiPopUpEditCtrl):
    """A right-click menu: a row list that is HIDDEN until openAtMouse().

    `m_visible = false` in the constructor (FourPlay quattroplay/src/gui/
    GuiContextMenuCtrl.cpp:35-46, GuiContextMenuCtrl::initObject).

    The reference's parent is GuiControl, not a popup, but it reaches the
    text list's whole surface by delegation -- addPropertyObject(m_textListCtrl)
    at GuiContextMenuCtrl.cpp:158 -- which is what deriving from
    GuiPopUpEditCtrl approximates here.

    Profile ALIASING (GuiContextMenuCtrlProperties.cpp:155-161): `profile`
    and `scrollprofile` are ONE slot -- pointer-identical accessors styling
    the embedded SCROLL control -- so `.profile` on a context menu styles
    the frame, and row/text styling needs `textprofile` (the embedded text
    list's, :44-64). This redeclaration REPLACES GuiControl's `profile`.

    Not modelled: `width`'s asymmetric READ (the reference reads the text
    list's extent but writes the scroll control's, :66-84, so write->read
    does not round-trip there; one control here, so ours does), and the
    RO `rows` forward of the text list's rows var (:106-114; 0 corpus
    reads)."""

    CTRL_CLASS = "GuiContextMenuCtrl"
    _TORQUE_PROPS = GuiPopUpEditCtrl._TORQUE_PROPS | frozenset(
        {"maxpopupheight", "scrollprofile"})
    _METHOD_NAMES = GuiPopUpEditCtrl._METHOD_NAMES | frozenset(
        {"close", "isopen", "open"})

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.visible = False
        self.width, self.height = 120.0, 22.0

    def get(self, key: str) -> Any:
        k = key.lower()
        if k == "scrollprofile":
            return super().get("profile")
        return super().get(k)

    def set(self, key: str, value: Any) -> None:
        k = key.lower()
        if k == "scrollprofile":
            super().set("profile", value)
            return
        if k == "width":
            # the width setter clamps to >= 1 before resizing the scroll
            # control (GuiContextMenuCtrlProperties.cpp:74-78)
            super().set("width", max(1.0, to_num(value)))
            return
        super().set(k, value)

    def _row_profile(self):
        """Rows belong to the embedded text list: `textprofile` styles them
        (GuiContextMenuCtrlProperties.cpp:44-64); without one they fall back
        to the frame profile."""
        ref = self._members.get("textprofile")
        if ref is None:
            return self.resolve_profile()
        return _profile_from_fields(_profile_fields(ref, self._manager, set()))

    def _m_isopen(self, *args) -> float:
        return 1.0 if self.visible else 0.0

    def _m_close(self, *args) -> float:
        return self._m_hide()

    def _m_open(self, *args) -> float:
        """open(x, y) (:126-138). The reference additionally reparents the
        popup to the moused control's context-menu parent; that is not
        modelled -- it opens in place."""
        if len(args) >= 2:
            self.x, self.y = to_num(args[0]), to_num(args[1])
        return self._m_showtop()

