from __future__ import annotations

from typing import Any, List, Optional, Tuple

import pygame

from reborn_protocol.gs2 import GS2Object, to_num, to_str

from .base import GuiControl, GuiListRow, _TreeNodeIcon
from .profiles import (
    GuiProfile, _MAX_PARENT_DEPTH, _draw_label, _fill_rect, _font, _profile_fields, _profile_from_fields, _readable_on, _shade,
)
from .base import _InertDrawable  # noqa: F401  - kept: original import block (star-import consumers rely on it)
from .profiles import _color, _draw_border  # noqa: F401  - kept: original import block (star-import consumers rely on it)
from reborn_protocol.gs2 import to_bool  # noqa: F401  - kept: original import block (star-import consumers rely on it)
from typing import Dict  # noqa: F401  - kept: original import block (star-import consumers rely on it)


class GuiDrawingPanel(GuiControl):
    """A script-driven canvas: `with (panel) { clearall(); drawline(...); }`.
    The draw calls are RECORDED (they are issued once, outside the render
    loop, and must persist across frames) and replayed every frame in the
    control's own coordinate space. Login's staff sprite-editor weapon
    draws its guidelines and sprite sheet this way."""

    CTRL_CLASS = "GuiDrawingPanel"
    _MAX_OPS = 4096          # a runaway script must not grow this forever

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.draw_ops: List[Tuple] = []
        #: saveimage() snapshots, name -> ops list (see _m_saveimage)
        self.saved_images: Dict[str, List[Tuple]] = {}

    #: the full registered method set (funcDefs, FourPlay quattroplay/src/
    #: gui/GuiDrawingPanelProperties.cpp:192-207); `clearall` resolves via
    #: GuiControl._METHOD_NAMES to the override below
    _METHOD_NAMES = GuiControl._METHOD_NAMES | frozenset(
        {"drawline", "drawimage", "drawimagestretched",
         "drawimagerectangle", "clearrectangle", "drawtext",
         "drawcurve", "drawobject", "saveimage", "saveimage2",
         "filterrectangle", "maskimage", "setdrawpalette"})
    #: registered properties (:183-190): partx/party/partw/parth and
    #: availablefilters are READ-ONLY (nullptr setters); enablecache is RW
    _TORQUE_PROPS = GuiControl._TORQUE_PROPS | frozenset({
        "partx", "party", "partw", "parth", "availablefilters",
        "enablecache"})

    def get(self, key: str) -> Any:
        k = key.lower()
        if k in ("partx", "party", "partw", "parth"):
            # RO ints (:28-46). Their backing fields' meaning is not
            # recovered from the transcription; 0 = the constructor state.
            return 0.0
        if k == "availablefilters":
            # 'o' RO (:48-51); the body forwards to a TDrawingPanel free
            # function that was not recovered -- type only, so an empty
            # array (an unanswered read would be Number 0.0, which
            # string-compares equal to everything)
            return []
        return super().get(k)

    def set(self, key: str, value: Any) -> None:
        k = key.lower()
        if k in ("partx", "party", "partw", "parth", "availablefilters"):
            return          # nullptr setters: read-only, write dropped
        super().set(k, value)

    def _record(self, op: Tuple) -> float:
        if len(self.draw_ops) < self._MAX_OPS:
            self.draw_ops.append(op)
        return 0.0

    def _m_clearall(self, *args) -> float:
        self.draw_ops.clear()
        return 0.0

    # Drawing methods unpack their script arguments into persistent operations.
    def _m_drawline(self, *args) -> float:
        values = [to_num(a) for a in args[:5]]
        while len(values) < 5:
            values.append(1.0)
        return self._record(("line", *values))

    def _m_clearrectangle(self, *args) -> float:
        """clearRectangle(x, y, w, h) (funcDefs `"iiii"`,
        GuiDrawingPanelProperties.cpp:194): erase a region of the canvas.
        Recorded as an op so replay order matches the call order."""
        values = [to_num(a) for a in args[:4]]
        while len(values) < 4:
            values.append(0.0)
        return self._record(("clear", *values))

    def _m_drawtext(self, *args) -> float:
        """drawText(x, y, text) (`"iis"`, :201). The pen font/colour come
        from the CONTROL's profile, not from any draw-state property
        (setGuiDrawingPanelProfile, :23-26)."""
        if len(args) < 3:
            return 0.0
        return self._record(("text", to_num(args[0]), to_num(args[1]),
                             to_str(args[2])))

    def _m_drawimage(self, *args) -> float:
        if len(args) < 3:
            return 0.0
        return self._record(("image", to_num(args[0]), to_num(args[1]),
                             to_str(args[2]), 0.0, 0.0))

    def _m_drawimagestretched(self, *args) -> float:
        """drawImageStretched(x, y, w, h, image, srcX, srcY, srcW, srcH):
        the image is the FIFTH argument and four source-rect arguments
        follow it (funcDefs `"iiiisiiii"`,
        quattroplay/src/gui/GuiDrawingPanelProperties.cpp:197, body
        :105-111). We used to read `(x, y, w, h, image)` and drop args 5-8,
        which is only invisible while a caller passes the whole image as
        the source rect."""
        if len(args) < 5:
            return 0.0
        source = tuple(to_num(a) for a in args[5:9]) if len(args) >= 9 else None
        return self._record(("imagestretched", to_num(args[0]),
                             to_num(args[1]), to_str(args[4]),
                             (to_num(args[2]), to_num(args[3])), source))

    def _m_drawimagerectangle(self, *args) -> float:
        """drawImageRectangle(x, y, image, partx, party, partw, parth):
        blit ONE sub-rectangle of a sheet (the sprite editor's sheet view
        and the chat window's smilie strip both slice art this way)."""
        if len(args) < 7:
            return 0.0
        return self._record(("imagepart", to_num(args[0]), to_num(args[1]),
                             to_str(args[2]),
                             tuple(to_num(a) for a in args[3:7])))

    def _m_drawcurve(self, *args) -> float:
        """drawCurve(x1, y1, x2, y2, x3, y3, width) (`"iiiiiif"`,
        GuiDrawingPanelProperties.cpp:195, body :83-97): a curve from p1 to
        p3 shaped by p2 -- the reference's invalidation rect spans p1..p3
        padded by width, so p1/p3 are the endpoints and p2 the control
        point. Pen colour comes from the control profile
        (setGuiDrawingPanelProfile, :14-26), same as drawline/drawtext."""
        if len(args) < 6:
            return 0.0
        values = [to_num(a) for a in args[:7]]
        if len(values) < 7:
            values.append(1.0)
        return self._record(("curve", *values))

    def _m_drawobject(self, *args) -> float:
        """drawObject(x, y, obj) (`"iio"`, :199): silently no-ops unless the
        object casts to a TLevelObject (:120-125). No script-built object
        ever passes that cast here, so it is faithfully a no-op."""
        return 0.0

    def _m_saveimage(self, *args) -> float:
        """saveImage(filename) (`"s"`, :202): the reference rewrites the
        path through TFileScripting::getScriptWriteBitmapFilename and DROPS
        the call outright when the sandbox returns empty (:152-157). This
        headless client never writes script-named files to disk at all; the
        gate is modelled as basename-only + image-extension, and a passing
        name snapshots the current op list (the one corpus caller is the
        staff sprite editor's temp_sprite.png hand-off,
        weapon-Staff_GraalShop.txt:946)."""
        name = to_str(args[0]) if args else ""
        name = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if not name or not name.endswith((".png", ".gif", ".jpg", ".jpeg",
                                          ".bmp", ".mng")):
            return 0.0          # sandbox gate: call dropped
        self.saved_images[name] = list(self.draw_ops)
        return 0.0

    #: saveImage2(filename, options) (`"si"`, :203): same gate, the int is
    #: forwarded to the encoder (:159-164) -- irrelevant to a snapshot
    _m_saveimage2 = _m_saveimage

    def _m_filterrectangle(self, *args) -> float:
        """filterRectangle(x, y, w, h, filter) -- the table declares a bool
        return (`:204`) but the transcribed body is void and discards
        filterRectangle_Impl's result (:166-170); no asm exists to
        arbitrate (static fn). Type recorded, no filter semantics asserted;
        answered so the call is not an unknown method."""
        return 0.0

    def _m_maskimage(self, *args) -> float:
        """maskImage(x, y, image, mode) (`"iiss"`, :205): forwards to
        TDrawingPanel::maskImage_Impl (:172-176), whose body was not
        recovered -- signature only, so a claimed no-op."""
        return 0.0

    def _m_setdrawpalette(self, *args) -> float:
        """setDrawPalette(palette, alpha) (`"si"`, :206) ->
        setDrawPaletteNamed (:178-181); palette resources are not modelled,
        the arguments are retained for reads."""
        if args:
            self._members["_drawpalette"] = (to_str(args[0]),
                                             to_num(args[1]) if len(args) > 1
                                             else 255.0)
        return 0.0

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        super()._draw_self(surf, fonts, sprite_mgr)
        prof = self.resolve_profile()
        r = self.rect()
        for op in self.draw_ops:
            if op[0] == "curve":
                _, x1, y1, x2, y2, x3, y3, thickness = op
                # quadratic bezier p1 -> p3 shaped by p2, flattened
                points = []
                for i in range(17):
                    t = i / 16.0
                    mt = 1.0 - t
                    points.append(
                        (r.x + mt * mt * x1 + 2 * mt * t * x2 + t * t * x3,
                         r.y + mt * mt * y1 + 2 * mt * t * y2 + t * t * y3))
                pygame.draw.lines(surf, prof.fg[:3], False,
                                  [(int(px), int(py)) for px, py in points],
                                  max(1, int(thickness)))
                continue
            if op[0] == "line":
                _, x1, y1, x2, y2, thickness = op
                pygame.draw.line(surf, prof.fg[:3],
                                 (r.x + int(x1), r.y + int(y1)),
                                 (r.x + int(x2), r.y + int(y2)),
                                 max(1, int(thickness)))
            elif op[0] == "clear":
                _, x, y, w, h = op
                _fill_rect(surf, prof.bg if prof.bg is not None else (0, 0, 0, 0),
                           pygame.Rect(r.x + int(x), r.y + int(y),
                                       max(0, int(w)), max(0, int(h))))
            elif op[0] == "text":
                if fonts is None:
                    continue
                _, x, y, text = op
                _draw_label(surf, _font(fonts, prof), text, prof.fg,
                            (r.x + int(x), r.y + int(y)), prof.text_shadow)
            elif op[0] in ("image", "imagepart", "imagestretched"):
                name = op[3]
                img = (sprite_mgr.load_sheet(name)
                       if (sprite_mgr is not None and name) else None)
                if img is None:
                    if name and self._manager is not None:
                        self._manager.request_image(name)
                    continue
                x, y = op[1], op[2]
                if op[0] == "imagepart":
                    px, py, pw, ph = op[4]
                    area = pygame.Rect(int(px), int(py), max(0, int(pw)),
                                       max(0, int(ph)))
                    surf.blit(img, (r.x + int(x), r.y + int(y)), area)
                    continue
                if op[0] == "imagestretched":
                    (w, h), source = op[4], op[5]
                    if source is not None:
                        area = pygame.Rect(int(source[0]), int(source[1]),
                                           max(0, int(source[2])),
                                           max(0, int(source[3])))
                        area = area.clip(img.get_rect())
                        if area.width <= 0 or area.height <= 0:
                            continue
                        img = img.subsurface(area)
                else:
                    w, h = op[4], op[5]
                if w > 0 and h > 0 and img.get_size() != (int(w), int(h)):
                    img = pygame.transform.smoothscale(img, (int(w), int(h)))
                surf.blit(img, (r.x + int(x), r.y + int(y)))


class GuiTextListCtrl(GuiControl):
    """Vertical list of addRow() rows; click selects a row and fires
    onSelect(entryid, entrytext, entryindex) -- same convention as
    GuiPopUpEditCtrl. Used all over the Login UI (GlobalChat_Channels,
    start-menu rows via the GuiStartMenuCtrl subclass).

    Rows are identified two independent ways and the reference is careful
    about which: an ID (whatever addRow's first argument was) and a ROW
    NUMBER (the array position). `getRowNumById` converts one to the other,
    `getEntryId` the other way, and a miss is -1 both directions
    (FourPlay quattroplay/src/gui/GuiTextListCtrl.cpp:664-676, :639-645).

    Selection is a LIST of cells, not one index: GuiArrayCtrl keeps every
    selected cell and `getSelectedCell()` is just the FIRST of them
    (src/gui/GuiArrayCtrl.cpp:378-385), which is why isRowSelected and the
    getSelected*s pair exist at all."""

    CTRL_CLASS = "GuiTextListCtrl"

    def pointer_down(self, manager, pos) -> bool:
        manager._set_focus(None)
        self.click_at(pos)
        return True
    ROW_H = 18

    #: sortorder/groupsortorder and sortmode are string ENUMS whose value is
    #: the name at the stored index (GuiTextListCtrlProperties.cpp:9-19,
    #: readers :113-115/:125-127/:135-137). Both default to index 0, so
    #: sortmode reads "" -- and being string-typed, an unanswered read would
    #: compare equal to every literal, so they answer even when unset.
    _SORT_ORDER_NAMES = ("sortascending", "sortdescending")
    _SORT_MODE_NAMES = ("", "sortbyvalue", "lexical", "sortbyextension")

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 160.0, 24.0
        #: selected ROW NUMBERS, in selection order; [0] is getSelectedCell()
        self.selected_rows: List[int] = []
        self.allow_multiple_selections = False

    @property
    def selected_index(self) -> int:
        """getSelectedCell().y -- the first selected row, -1 when none."""
        return self.selected_rows[0] if self.selected_rows else -1

    @selected_index.setter
    def selected_index(self, value) -> None:
        index = int(value)
        self.selected_rows = [index] if index >= 0 else []

    # -- row identity helpers ------------------------------------------------

    def _row_num_by_id(self, row_id) -> int:
        """findEntryById: array position of the row with that id, else -1."""
        wanted = to_str(row_id)
        for index, row in enumerate(self.list_rows):
            if to_str(row.get("id")) == wanted:
                return index
        return -1

    def _row_id(self, index: int) -> Any:
        """getEntryId: that row's id, -1 when the row number is out of
        range."""
        if 0 <= index < len(self.list_rows):
            return self.list_rows[index].get("id")
        return -1.0

    def _find_text(self, text: str) -> int:
        """findEntryByText: array position of the first row whose text matches
        exactly, else -1 (GuiTextListCtrl.cpp:747-758)."""
        for index, row in enumerate(self.list_rows):
            if to_str(row.get("text")) == text:
                return index
        return -1

    def _m_clearrows(self, *args) -> float:
        # clearRows() must also clear the SELECTION: Login rebuilds its tab
        # strips with clearRows + addRow + setSelectedById(sameid) on every
        # server click -- with the old index kept, re-selecting the same id
        # was treated as a no-op and onSelect (which shows the pane) never
        # fired, leaving every table panel hidden.
        self.selected_rows = []
        return super()._m_clearrows(*args)

    # -- counts and lookups --------------------------------------------------

    def _m_rowcount(self, *args) -> float:
        """rowCount() -> getNumEntries (GuiTextListCtrl.cpp:677-680). The
        single most-called list binding in the production corpus."""
        return float(len(self.list_rows))

    def _m_getrownumbyid(self, *args) -> float:
        return float(self._row_num_by_id(args[0]) if args else -1)

    def _m_findtextid(self, *args) -> Any:
        """findTextId(text) -> the matching row's ID, where findText gives its
        row NUMBER: the reference composes getEntryId(findEntryByText(...))
        (GuiTextListCtrlProperties.cpp:231-237)."""
        return self._row_id(self._find_text(to_str(args[0]) if args else ""))

    def _m_getrowatpoint(self, *args) -> float:
        """getRowAtPoint(x, y) -> the row number under a CANVAS-space point:
        getCellAt globalToLocalCoord()s its argument first
        (src/gui/GuiArrayCtrl.cpp:439-460)."""
        if len(args) < 2:
            return -1.0
        return float(self.row_at((to_num(args[0]), to_num(args[1]))))

    def _m_getrowidatpoint(self, *args) -> Any:
        if len(args) < 2:
            return -1.0
        return self._row_id(self.row_at((to_num(args[0]), to_num(args[1]))))

    # -- selection -----------------------------------------------------------

    def _m_isrowselected(self, *args) -> bool:
        return bool(args) and int(to_num(args[0])) in self.selected_rows

    def _m_isidselected(self, *args) -> bool:
        row = self._row_num_by_id(args[0]) if args else -1
        return row >= 0 and row in self.selected_rows

    def _m_getselectedid(self, *args) -> Any:
        """getSelectedId() -> the FIRST selected row's id, -1 when the
        selection is empty (GuiTextListCtrl.cpp:682-693)."""
        return self._row_id(self.selected_index)

    def _m_getselectedrows(self, *args) -> List[float]:
        """getSelectedRows() -> the selected ROW NUMBERS.

        The decompiled body looks like it returns ids and getSelectedIds
        looks like it double-converts (GuiTextListCtrlProperties.cpp:238-261),
        but the list it walks is GuiArrayCtrl's selected-CELL list, whose
        elements are TPoints -- every other user of that list casts them that
        way (insertEntry :561-566, removeEntryByIndex :880-893). So the field
        the decompiler printed as `entry->id` is the cell's y, i.e. the row
        number, and both names mean what they say."""
        return [float(row) for row in self.selected_rows]

    def _m_getselectedids(self, *args) -> List[Any]:
        return [self._row_id(row) for row in self.selected_rows]

    def _m_clearselection(self, *args) -> float:
        # setSelectedCell(TPoint(-1, -1)) (:204-207)
        self.selected_rows = []
        return 0.0

    def _m_setselectedbytext(self, *args) -> float:
        """setSelectedByText(text): select the row whose text matches, and do
        NOTHING when there is no match -- the reference gates on `row >= 0`
        (:378-383), so a miss leaves the previous selection intact."""
        row = self._find_text(to_str(args[0]) if args else "")
        if row >= 0:
            self.select_index(row)
        return 0.0

    def _m_setselectedbyids(self, *args) -> float:
        return self._select_many(args, by_id=True)

    def _m_setselectedrows(self, *args) -> float:
        return self._select_many(args, by_id=False)

    def _select_many(self, args, by_id: bool) -> float:
        """setSelectedByIds/setSelectedRows(csv): empty clears the selection,
        one token (or a single-selection control) is a plain select, and only
        a multi-selection control accumulates the rest
        (GuiTextListCtrlProperties.cpp:344-376)."""
        raw = to_str(args[0] if args else "")
        tokens = [t for t in raw.split(",") if t != ""]
        if not tokens:
            self.selected_rows = []
            return 0.0
        rows = [self._row_num_by_id(t) if by_id else int(to_num(t))
                for t in tokens]
        if len(tokens) == 1 or not self.allow_multiple_selections:
            self.select_index(rows[0])
            return 0.0
        self.selected_rows = []
        for row in rows:
            if 0 <= row < len(self.list_rows) \
                    and row not in self.selected_rows:
                self.selected_rows.append(row)
        return 0.0

    def _m_makevisible(self, *args) -> float:
        # scrollCellVisible; this client draws the whole list and lets the
        # enclosing GuiScrollCtrl clip, so there is no scroll to nudge.
        return 0.0

    def _m_makevisiblebyid(self, *args) -> float:
        return 0.0

    # -- row mutation --------------------------------------------------------

    def _m_insertrow(self, *args) -> Any:
        """insertRow(index, id, text): note the argument ORDER -- the binding
        is (index, id, text) and forwards to insertEntry(id, text, index)
        (GuiTextListCtrlProperties.cpp:281-289). An index past the end
        appends (GuiTextListCtrl.cpp:548-556)."""
        if len(args) < 3:
            return 0.0
        index = int(to_num(args[0]))
        row = GuiListRow(to_str(args[2]), args[1])
        if index < 0 or index > len(self.list_rows):
            self.list_rows.append(row)
        else:
            self.list_rows.insert(index, row)
            self.selected_rows = [r + 1 if index <= r else r
                                  for r in self.selected_rows]
        return row

    def _m_removerow(self, *args) -> float:
        if args:
            self._remove_row_num(int(to_num(args[0])))
        return 0.0

    def _m_removerowbyid(self, *args) -> float:
        if args:
            self._remove_row_num(self._row_num_by_id(args[0]))
        return 0.0

    def _remove_row_num(self, index: int) -> None:
        """removeEntryByIndex: drop the row, then drop its selected cell and
        shift every later one down (GuiTextListCtrl.cpp:868-894). Without the
        fix-up the selection would silently point at a different row."""
        if not 0 <= index < len(self.list_rows):
            return
        del self.list_rows[index]
        self.selected_rows = [r - 1 if r > index else r
                              for r in self.selected_rows if r != index]

    def _m_setrowbyid(self, *args) -> float:
        """setRowById(id, text): retext the row with that id -- and ADD it
        when no row has that id yet (GuiTextListCtrl.cpp:897-903 falls
        through to addEntry). Counter-intuitive but load-bearing: RC-style
        lists build themselves purely out of setRowById calls."""
        if len(args) < 2:
            return 0.0
        index = self._row_num_by_id(args[0])
        if index < 0:
            self.list_rows.append(GuiListRow(to_str(args[1]), args[0]))
        else:
            self.list_rows[index].set("text", to_str(args[1]))
        return 0.0

    def _m_setrowactivebyid(self, *args) -> float:
        if len(args) >= 2:
            index = self._row_num_by_id(args[0])
            if index >= 0:
                self.list_rows[index].set("active", to_num(args[1]))
        return 0.0

    def content_height(self) -> int:
        return len(self.list_rows) * self.ROW_H

    def row_at(self, pos) -> int:
        r = self.rect()
        if not r.collidepoint(pos) or not self.list_rows:
            return -1
        idx = int((pos[1] - r.y) // self.ROW_H)
        return idx if 0 <= idx < len(self.list_rows) else -1

    def click_at(self, pos) -> bool:
        return self.select_index(self.row_at(pos))

    def select_index(self, index: int) -> bool:
        if not 0 <= index < len(self.list_rows):
            return False
        row = self.list_rows[index]
        text = to_str(row.get("text"))
        if text == "-":
            return False                      # separator row
        self.selected_index = index
        self.fire_event("onselect", row.get("id"), text, float(index))
        return True

    def _m_setselectedrow(self, *args) -> float:
        """setSelectedRow(index) -- Login selects its default tab this way
        (Serverlist_DescriptionTab.setSelectedRow(0))."""
        if args:
            self.select_index(int(to_num(args[0])))
        return 0.0

    def _m_setselectedbyid(self, *args) -> float:
        """setSelectedById(id) -- select the row whose `id` member matches
        (Login: Serverlist_TablesTab.setSelectedById(0) right after
        addRow(0, ...))."""
        if args:
            index = self._row_num_by_id(args[0])
            if index >= 0:
                self.select_index(index)
        return 0.0

    def _m_getselectedrow(self, *args) -> Any:
        """getSelectedRow(): the selected ROW NUMBER, -1 when nothing is
        selected. It is bound straight to the `selectedrow` property reader
        (GuiTextListCtrlProperties.cpp:423 reuses
        propfun_guitextlistctrl_selectedrow_r, :156-159 = getSelectedCell().y)
        -- getSelectedId() is the one that hands back the id. This used to
        return the id, which made a script that fed it to setSelectedRow (a
        row NUMBER) select the wrong row whenever id != position."""
        return float(self.selected_index)

    def _m_getselectedtext(self, *args) -> str:
        if 0 <= self.selected_index < len(self.list_rows):
            return to_str(self.list_rows[self.selected_index].get("text"))
        return ""

    def _m_sortascending(self, *args) -> float:
        self.list_rows.sort(key=lambda row: to_str(row.get("text")).casefold())
        return 0.0

    def _m_sortdescending(self, *args) -> float:
        self.list_rows.sort(key=lambda row: to_str(row.get("text")).casefold(),
                            reverse=True)
        return 0.0

    def _m_findtext(self, *args) -> float:
        """findText(text) -> the matching row's INDEX, or -1.

        Reference: GuiTextListCtrlProperties.cpp:420 `{'i', "s"}` ->
        GuiTextListCtrl::findEntryByText (FourPlay quattroplay/src/gui/
        GuiTextListCtrl.cpp:747-758), a linear scan returning the array
        position. The sibling binding findTextId() is the one that maps that
        position to a row id -- so this must NOT return the id. Live site:
        GServer-v2/bin/servers/era/weapons/weaponSkyld%047RC.txt:915 uses it
        to find its "Admins"/"Players" group header and insert the row after
        it."""
        return float(self._find_text(to_str(args[0]) if args else ""))

    def get(self, key: str) -> Any:
        k = key.lower()
        # Properties the reference computes rather than stores
        # (GuiTextListCtrlProperties.cpp:407-411): `selectedrow` and
        # `selectedid` are the property spellings of the two getters above,
        # and `selected` is the selected ROW OBJECT (:150-153).
        if k == "allowmultipleselections":
            # GuiArrayCtrl's, inherited (src/gui/GuiArrayCtrlProperties.cpp:26)
            return 1.0 if self.allow_multiple_selections else 0.0
        if k == "selectedrow":
            return float(self.selected_index)
        if k == "selectedid":
            return self._row_id(self.selected_index)
        if k == "selected":
            index = self.selected_index
            return self.list_rows[index] if 0 <= index < len(self.list_rows) \
                else None
        # `k not in self._members`, not has(): GuiControl.has() claims the
        # whole Torque property vocabulary, so it cannot say whether a script
        # actually wrote this one.
        if k in ("sortorder", "groupsortorder", "sortmode") \
                and k not in self._members:
            return "" if k == "sortmode" else self._SORT_ORDER_NAMES[0]
        return super().get(key)

    def set(self, key: str, value: Any) -> None:
        k = key.lower()
        if k == "allowmultipleselections":
            self.allow_multiple_selections = bool(to_num(value))
            return
        if k == "selectedrow":
            self.select_index(int(to_num(value)))
            return
        if k == "selectedid":
            self._m_setselectedbyid(value)
            return
        if k in ("sortorder", "groupsortorder", "sortmode"):
            # The writers only accept a member of the enum, by name or by
            # index, and ignore anything else (:117-122, parseEnumValue
            # :27-39). Store the NAME so the reader round-trips.
            names = (self._SORT_MODE_NAMES if k == "sortmode"
                     else self._SORT_ORDER_NAMES)
            text = to_str(value)
            for index, name in enumerate(names):
                if text == name or text == str(index):
                    super().set(k, name)
                    return
            return
        super().set(key, value)

    _METHOD_NAMES = GuiControl._METHOD_NAMES | frozenset(
        {"setselectedrow", "setselectedbyid", "getselectedrow",
         "getselectedtext", "sortascending", "sortdescending", "findtext",
         # the row API proper -- every one of these was a 0.0 before
         "rowcount", "isrowselected", "isidselected", "getrownumbyid",
         "getselectedid", "getselectedids", "getselectedrows",
         "setselectedbytext", "setselectedbyids", "setselectedrows",
         "clearselection", "findtextid", "getrowatpoint", "getrowidatpoint",
         "insertrow", "removerow", "removerowbyid", "setrowbyid",
         "setrowactivebyid", "makevisible", "makevisiblebyid"})

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        # keep our height in sync with content so ancestor GuiScrollCtrl
        # clipping/scrolling covers every row
        self.height = max(self.height, float(self.content_height()))
        prof = self.resolve_profile()
        r = self.rect()
        _fill_rect(surf, prof.bg, r)
        if fonts is None:
            return
        font = _font(fonts, prof)
        for index, row in enumerate(self.list_rows):
            rr = pygame.Rect(r.x, r.y + index * self.ROW_H, r.width, self.ROW_H)
            text = to_str(row.get("text"))
            if text == "-":
                pygame.draw.line(surf, prof.border[:3],
                                 (rr.x + 4, rr.centery), (rr.right - 4, rr.centery))
                continue
            fg = prof.fg
            if index in self.selected_rows:   # every selected cell, not [0]
                _fill_rect(surf, prof.title_bg, rr)
                fg = _readable_on(prof.title_bg, prof.bg, prof.fg)
            _draw_label(surf, font, text, fg,
                        (rr.x + 4, rr.centery - font.get_height() // 2),
                        prof.text_shadow and index != self.selected_index)


class GuiTabCtrl(GuiControl):
    """Horizontal tab strip over addRow() rows. Selecting fires
    onDeselect(oldid, oldtext, oldindex) then onSelect(newid, newtext,
    newindex) -- exactly the pair Login's Serverlist_DescriptionTab /
    Serverlist_TablesTab / GlobalChat_ChatTab handlers expect (they hide
    the old tab's panel and show the new one's)."""

    CTRL_CLASS = "GuiTabCtrl"

    def pointer_down(self, manager, pos) -> bool:
        manager._set_focus(None)
        self.click_at(pos)
        return True
    _METHOD_NAMES = GuiControl._METHOD_NAMES | frozenset(
        {"setselectedrow", "setselectedbyid"})

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 200.0, 22.0
        self.selected_index = -1

    def _m_clearrows(self, *args) -> float:
        # same reset-selection-on-clearRows contract as GuiTextListCtrl
        # (Login re-selects the same row id after every rebuild)
        self.selected_index = -1
        return super()._m_clearrows(*args)

    def tab_width(self) -> float:
        w = to_num(self._members.get("tabwidth", 0))
        if w > 0:
            return w
        return self.width / max(1, len(self.list_rows))

    def tab_at(self, pos) -> int:
        r = self.rect()
        if not r.collidepoint(pos) or not self.list_rows:
            return -1
        idx = int((pos[0] - r.x) // max(1.0, self.tab_width()))
        return idx if 0 <= idx < len(self.list_rows) else -1

    def click_at(self, pos) -> bool:
        return self.select_index(self.tab_at(pos))

    def select_index(self, index: int) -> bool:
        if not 0 <= index < len(self.list_rows) or index == self.selected_index:
            return False
        old = self.selected_index
        self.selected_index = index
        if 0 <= old < len(self.list_rows):
            row = self.list_rows[old]
            self.fire_event("ondeselect", row.get("id"),
                            to_str(row.get("text")), float(old))
        row = self.list_rows[index]
        self.fire_event("onselect", row.get("id"),
                        to_str(row.get("text")), float(index))
        return True

    def _m_setselectedrow(self, *args) -> float:
        if args:
            self.select_index(int(to_num(args[0])))
        return 0.0

    def _m_setselectedbyid(self, *args) -> float:
        if args:
            wanted = to_str(args[0])
            for index, row in enumerate(self.list_rows):
                if to_str(row.get("id")) == wanted:
                    self.select_index(index)
                    break
        return 0.0

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        prof = self.resolve_profile()
        r = self.rect()
        tw = int(max(1.0, self.tab_width()))
        base = prof.bg if prof.bg is not None else (24, 48, 112, 224)
        skin = self._skin(prof, sprite_mgr)
        # guiblue_tab.png: 9-patch group 0 = the (taller) selected tab,
        # group 1 = the shorter unselected tab, then arrow rows.
        for index, row in enumerate(self.list_rows):
            selected = index == self.selected_index
            rr = pygame.Rect(r.x + index * tw, r.y, tw, r.height)
            if not selected:
                rr = pygame.Rect(rr.x, rr.y + 3, rr.width, rr.height - 3)
            drew = False
            if skin is not None:
                drew = skin.draw_nine(surf, rr, 0 if selected else 3,
                                      int(255 * prof.transparency))
                if not drew and not selected:
                    drew = skin.draw_nine(surf, rr, 0,
                                          int(255 * prof.transparency))
            if not drew:
                fill = prof.title_bg if selected else _shade(base, 1.2)
                _fill_rect(surf, fill, rr)
                pygame.draw.rect(surf, prof.border[:3], rr, 1)
            if fonts is not None:
                font = _font(fonts, prof)
                text = to_str(row.get("text"))
                tw_px = font.size(text)[0]
                _draw_label(surf, font, text, prof.fg,
                            (rr.centerx - tw_px // 2,
                             rr.centery - font.get_height() // 2),
                            prof.text_shadow)


class GuiTreeNode(GS2Object):
    """One GuiTreeViewCtrl entry (folder or leaf). Script-visible members:
    `text` (leaf text may carry TAB-separated columns, e.g.
    "Zelda: A Link to the Past\\t63" from Login's server list), `id`,
    `sortgroup`, `sortvalue`, `icon`, and a `select()` method."""

    def __init__(self, tree: "GuiTreeViewCtrl", text: str,
                 parent_node: Optional["GuiTreeNode"] = None):
        super().__init__(name="treenode")
        self.tree = tree
        self.text = text
        self.parent_node = parent_node
        self.child_nodes: List["GuiTreeNode"] = []
        self.icon_image = ""

    @property
    def is_folder(self) -> bool:
        return bool(self.child_nodes)

    def columns(self) -> List[str]:
        return self.text.split("\t")

    def path(self) -> str:
        parts, node = [], self
        for _ in range(_MAX_PARENT_DEPTH):
            if node is None:
                break
            parts.append(node.columns()[0])
            node = node.parent_node
        return "/".join(reversed(parts))

    def level(self) -> float:
        """Torque tree depth, 1-based (a root node is level 1). Login gates
        its connect handler on it -- `if (node == null || node.level <= 1)
        return;` skips the CATEGORY folder rows -- so an unanswered read
        (0) made every row look like a folder and swallowed the connect."""
        depth, node = 0, self
        for _ in range(_MAX_PARENT_DEPTH):
            if node is None:
                break
            depth += 1
            node = node.parent_node
        return float(depth)

    def profile_ref(self) -> Any:
        """This node's own `profile` override, if the script set one.
        Login's serverlist restyles its category folders with
        `node.profile = IRC_TreeViewProfile2;` (a different fill), which the
        renderer used to ignore -- every row drew in the tree's profile."""
        return self._members.get("profile")

    def add_node(self, *args) -> "GuiTreeNode":
        child = GuiTreeNode(self.tree, to_str(args[0]) if args else "", self)
        self.child_nodes.append(child)
        return child

    def get(self, key: str) -> Any:
        k = key.lower()
        if k == "text":
            return self.text
        if k == "level" and k not in self._members:
            return self.level()
        if k == "id" and k not in self._members:
            # A node the script never gave an id reads -1 (the invalid-item
            # sentinel), NOT unset/0. Evidence: Login's serverlist boots via
            # `Serverlist_ServerList.nodes[0].select()` and its onSelect
            # gates `node.id >= 0` -> server pane vs showLoginInfo(); the
            # auto-selected first node is the category folder for the "U "
            # servers, which the live script's FOUR-entry category table
            # (no 5th name -- string absent from the live bytecode) never
            # names or ids. The real client boots into the login-info panes,
            # so that untouched node's id must compare < 0; with unset->0 we
            # boot into a serverless "Map" pane instead (a 0x0 bitmap hole
            # for art no server serves, plus per-tick updateServerMapIcons).
            # Category folders the script DOES id get -1 assigned anyway
            # (weapon -Rescripted/Serverlist: `node.id = -1;`).
            return -1.0
        if k == "select" and not super().has(k):
            return lambda *a: self.tree.select_node(self)
        if k == "addnode" and not super().has(k):
            # parentNode.addNode(text) -> the new CHILD node (Staff's
            # GUIExplorer walks the control tree building one node per
            # control this way)
            return self.add_node
        if k == "icon" and k not in self._members:
            v = self._members[k] = _TreeNodeIcon(self)
            return v
        return super().get(k)

    def set(self, key: str, value: Any) -> None:
        if key.lower() == "text":
            self.text = to_str(value)
            return
        super().set(key, value)

    def has(self, key: str) -> bool:
        return True


class GuiTreeViewCtrl(GuiControl):
    """Hierarchical list built with addNodeByPath("Folder/Leaf", "/") --
    the control the Login server list actually lives in
    (Serverlist_ServerList: category folders containing one row per
    server, icon + name + player count, sorted by player count within
    category). Selection fires onSelect(node, path, dot); a double-click
    fires onDblClick(node, path, dot), which on Login connects to the
    server (checkServerConnect -> serverwarp)."""

    CTRL_CLASS = "GuiTreeViewCtrl"

    def pointer_down(self, manager, pos) -> bool:
        manager._set_focus(None)
        node = self.node_at(pos)
        if node is not None:
            now = pygame.time.get_ticks()
            last_t, last_node = manager._last_tree_click
            manager._last_tree_click = (now, node)
            if node is last_node and now - last_t <= 400:
                # second click of a double-click: onDblClick (Login:
                # connect to the clicked server)
                self.select_node(node, event="ondblclick")
            else:
                self.select_node(node)
        return True
    _METHOD_NAMES = GuiControl._METHOD_NAMES | frozenset({
        "clearnodes", "addnodebypath", "getnode", "getselectednode",
        "setselectedbyid", "addnode",
    })

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 200.0, 120.0
        self.root_nodes: List[GuiTreeNode] = []
        self.selected_node: Optional[GuiTreeNode] = None

    # -- script surface ---------------------------------------------------

    def get(self, key: str) -> Any:
        if key.lower() == "nodes" and "nodes" not in self._members:
            return self.flat_nodes()
        return super().get(key)

    def _m_clearnodes(self, *args) -> float:
        self.root_nodes.clear()
        self.selected_node = None
        return 0.0

    #: clearAll() on a tree empties its NODES, not the base class's row model
    _m_clearall = _m_clearnodes

    def _m_addnode(self, *args) -> GuiTreeNode:
        """addNode(text) on the CONTROL: append a root node. (Staff's
        GUIExplorer builds its object tree with parentNode.addNode(...) --
        see GuiTreeNode's own addnode for the per-node form.)"""
        node = GuiTreeNode(self, to_str(args[0]) if args else "", None)
        self.root_nodes.append(node)
        return node

    def _m_addnodebypath(self, *args) -> Optional[GuiTreeNode]:
        if not args:
            return None
        path = to_str(args[0])
        sep = to_str(args[1]) if len(args) > 1 else "/"
        parts = path.split(sep) if sep else [path]
        parent: Optional[GuiTreeNode] = None
        siblings = self.root_nodes
        node: Optional[GuiTreeNode] = None
        for depth, part in enumerate(parts):
            last = depth == len(parts) - 1
            node = None if last else next(
                (n for n in siblings if n.columns()[0] == part), None)
            if node is None:
                node = GuiTreeNode(self, part, parent)
                siblings.append(node)
            parent, siblings = node, node.child_nodes
        return node

    def _m_getnode(self, *args) -> Optional[GuiTreeNode]:
        name = to_str(args[0]) if args else ""
        for node in self.flat_nodes():
            if node.columns()[0] == name:
                return node
        return None

    def _m_getselectednode(self, *args) -> Optional[GuiTreeNode]:
        return self.selected_node

    def _m_setselectedbyid(self, *args) -> float:
        """setSelectedById(id): select the node whose `id` member matches
        (Login's tree keeps its serverlist row index there)."""
        if args:
            wanted = to_str(args[0])
            for node in self.flat_nodes():
                if to_str(node.get("id")) == wanted:
                    self.select_node(node)
                    break
        return 0.0

    def _m_sort(self, *args) -> float:
        """Folders by their `sortgroup` ascending, leaves inside each folder
        by `sortvalue` (player count) descending -- the tree's construction
        fields on Login (sortmode="value", sortorder="descending",
        groupsortorder="ascending")."""
        self.root_nodes.sort(key=lambda n: to_num(n.get("sortgroup") or 0))
        for folder in self.root_nodes:
            folder.child_nodes.sort(
                key=lambda n: to_num(n.get("sortvalue") or 0), reverse=True)
        return 0.0

    # -- model ------------------------------------------------------------

    def flat_nodes(self) -> List[GuiTreeNode]:
        out: List[GuiTreeNode] = []
        def visit(nodes):
            for n in nodes:
                out.append(n)
                visit(n.child_nodes)
        visit(self.root_nodes)
        return out

    def select_node(self, node: Optional[GuiTreeNode], event: str = "onselect") -> None:
        self.selected_node = node
        if node is not None:
            self.fire_event(event, node, node.path(), 0.0)

    # -- render / hit-test ------------------------------------------------

    def row_height(self) -> int:
        return max(20, int(self.icon_h) + 4) if self.icon_h else 20

    def display_nodes(self) -> List[GuiTreeNode]:
        """flat_nodes minus category folders with an EMPTY label. The live
        Login lister has no name for its hidden-servers category (the wire
        rows arrive as "/Name\\t0"), which produced a blank folder row; the
        official client shows no such row, so it is dropped from display
        (children keep their indent) while staying script-visible in
        flat_nodes/`nodes`."""
        return [n for n in self.flat_nodes()
                if n.columns()[0] or not n.is_folder]

    def node_at(self, pos) -> Optional[GuiTreeNode]:
        r = self.rect()
        if not r.collidepoint(pos):
            return None
        nodes = self.display_nodes()
        idx = int((pos[1] - r.y) // self.row_height())
        return nodes[idx] if 0 <= idx < len(nodes) else None

    def column_offsets(self) -> List[float]:
        """Column x offsets: setColumnOffset calls override the `columns`
        construction field ({0, 230} on Login's server list)."""
        offsets = dict(self._members.get("_column_offsets") or {})
        cols = self._members.get("columns")
        if isinstance(cols, (list, tuple)):
            for i, v in enumerate(cols):
                offsets.setdefault(i, to_num(v))
        out = [v for _i, v in sorted(offsets.items())]
        return out or [0.0]

    def node_profile(self, node: GuiTreeNode, default: GuiProfile) -> GuiProfile:
        """The effective style for ONE row: a node's own `profile` override
        resolved through the same inheritance chain controls use, else the
        tree's profile. Login styles its category folders with
        IRC_TreeViewProfile2 (opaque, its own fill/font colour) while the
        server rows keep IRC_TreeViewProfile."""
        ref = node.profile_ref()
        if not ref:
            return default
        return _profile_from_fields(_profile_fields(ref, self._manager, set()))

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        nodes = self.display_nodes()
        row_h = self.row_height()
        self.height = max(self.height, float(len(nodes) * row_h))
        tree_prof = self.resolve_profile()
        r = self.rect()
        _fill_rect(surf, tree_prof.bg, r)
        if fonts is None:
            return
        icon_w = int(self.icon_w) or 16
        icon_h = int(self.icon_h) or 16
        col_offsets = self.column_offsets()
        for index, node in enumerate(nodes):
            prof = self.node_profile(node, tree_prof)
            font = _font(fonts, prof)
            rr = pygame.Rect(r.x, r.y + index * row_h, r.width, row_h)
            indent = 0 if node.parent_node is None else 16
            fg = prof.fg
            if prof is not tree_prof and prof.opaque:
                # a per-node profile paints its own row background (the
                # folder-row banding the reference client shows)
                _fill_rect(surf, prof.bg, rr)
            if node is self.selected_node:
                _fill_rect(surf, prof.title_bg, rr)
                fg = _readable_on(prof.title_bg, prof.bg, prof.fg)
            cols = node.columns()
            tx = rr.x + 4 + indent
            if node.is_folder:
                icon = None
                if node.icon_image and sprite_mgr is not None:
                    icon = sprite_mgr.load_sheet(node.icon_image)
                    if icon is None and self._manager is not None:
                        self._manager.request_image(node.icon_image)
                if icon is not None:
                    ih = min(row_h - 2, icon.get_height())
                    iw = max(1, icon.get_width() * ih // max(1, icon.get_height()))
                    if icon.get_size() != (iw, ih):
                        icon = pygame.transform.smoothscale(icon, (iw, ih))
                    surf.blit(icon, (tx, rr.centery - ih // 2))
                    tx += iw + 4
                else:
                    # open-folder disclosure triangle fallback
                    cy = rr.centery
                    pygame.draw.polygon(
                        surf, fg,
                        [(tx, cy - 3), (tx + 8, cy - 3), (tx + 4, cy + 4)])
                    tx += 14
            elif node.icon_image and sprite_mgr is not None:
                img = sprite_mgr.load_sheet(node.icon_image)
                if img is None and self._manager is not None:
                    self._manager.request_image(node.icon_image)
                if img is not None:
                    if img.get_size() != (icon_w, icon_h):
                        img = pygame.transform.smoothscale(img, (icon_w, icon_h))
                    surf.blit(img, (tx, rr.centery - icon_h // 2))
                tx += icon_w + 4
            _draw_label(surf, font, cols[0], fg,
                        (tx, rr.centery - font.get_height() // 2),
                        prof.text_shadow and node is not self.selected_node)
            # extra columns at the profile's column offsets (player count)
            for ci in range(1, len(cols)):
                if not cols[ci]:
                    continue
                if ci < len(col_offsets) and col_offsets[ci] > 0:
                    cx = rr.x + int(col_offsets[ci])
                else:
                    cx = rr.right - font.size(cols[ci])[0] - 8
                cx = min(cx, rr.right - font.size(cols[ci])[0] - 4)
                _draw_label(surf, font, cols[ci], fg,
                            (cx, rr.centery - font.get_height() // 2),
                            prof.text_shadow and node is not self.selected_node)


class GuiTaskbar(GuiControl):
    """The Login taskbar strip: a plain container bar; its buttons are
    ordinary GuiButtonCtrl children (the start button opens the
    GuiStartMenuCtrl -- engine behavior, provided by GS2GuiManager's
    click routing)."""

    CTRL_CLASS = "GuiTaskbar"

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 640.0, 30.0

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        prof = self.resolve_profile()
        r = self.rect()
        skin = self._skin(prof, sprite_mgr)
        # IRC_TaskBarProfile: bitmap = guiblue_button.png (the bar is one
        # stretched button-face 9-patch, the classic look)
        if skin is not None and skin.draw_nine(surf, r, 0,
                                               int(255 * prof.transparency)):
            return
        _fill_rect(surf, prof.bg if prof.bg is not None else prof.title_bg, r)
        pygame.draw.rect(surf, prof.border[:3], r, 1)


class GuiStartMenuCtrl(GuiTextListCtrl):
    """The taskbar's start menu: hidden until the start button toggles it
    (see GS2GuiManager), then a vertical menu of addRow() entries whose
    selection fires onSelect(selid, seltext, selindex) and closes the menu
    -- Login's Serverlist_Taskbar_Menu opens Global Chat, the log window,
    the playerlist etc. from exactly that handler."""

    CTRL_CLASS = "GuiStartMenuCtrl"
    ROW_H = 22

    def __init__(self, ctor_arg: Any = None):
        super().__init__(ctor_arg)
        self.width, self.height = 190.0, 24.0
        self.visible = False        # engine shows it on start-button click

    _METHOD_NAMES = GuiTextListCtrl._METHOD_NAMES | frozenset({"open"})

    def select_index(self, index: int) -> bool:
        picked = super().select_index(index)
        if picked and self._manager is not None:
            self._manager.hide(self)
        return picked

    def _m_open(self, *args) -> float:
        """open(x, y): show the menu with its BOTTOM-left at the given
        canvas point -- Login opens it from the start button's own
        localToGlobalCoord({0, 0}), i.e. the button's top-left corner, and
        the reference menu grows upwards from there."""
        self.height = float(max(self.content_height(), self.ROW_H))
        x, y = self._coord_arg(args)
        self.x, self.y = x, y - self.height
        if self._manager is not None:
            self._manager.show(self)
        else:
            self.visible = True
        return 0.0

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        self.height = float(max(self.content_height(), self.ROW_H))
        prof = self.resolve_profile()
        r = self.rect()
        _fill_rect(surf, prof.bg if prof.bg is not None else (16, 32, 96, 240), r)
        pygame.draw.rect(surf, prof.border[:3], r, 1)
        super()._draw_self(surf, fonts, sprite_mgr)
