from __future__ import annotations

from typing import Any, List, Optional, TYPE_CHECKING, Tuple

import pygame

from reborn_protocol.gs2 import GS2Object, to_bool, to_num, to_str

from .profiles import (
    GuiProfile, _DEFAULT_GUIPROFILE, _DEFAULT_PROFILE_NAME, _MAX_PARENT_DEPTH, _draw_border, _draw_label, _fill_rect, _font, _profile_fields, _profile_from_fields, logger,
)
from .profiles import _color, _readable_on  # noqa: F401  - kept: original import block (star-import consumers rely on it)
from typing import Dict  # noqa: F401  - kept: original import block (star-import consumers rely on it)

if TYPE_CHECKING:  # annotation-only; real imports would cycle
    from .profiles import GuiControlProfile
    from .skins import _Skin
    from .collection_controls import GuiTreeNode


class _InertDrawable(GS2Object):
    """Stand-in for an engine drawing surface (`ctrl.icon` / `row.icon`):
    scripts call clearAll()/drawImage()/drawImageRectangle() on it
    (-Serverlist_Chat smilie buttons and channel-menu rows); those are
    engine-canvas calls with no headless equivalent, so every unknown
    member resolves to a no-op callable -- keeping the whole chain on the
    object-exists path instead of logging unknown-method."""

    def get(self, key: str) -> Any:
        v = super().get(key)
        return v if v is not None else (lambda *a: 0.0)

    def has(self, key: str) -> bool:
        return True


class GuiListRow(GS2Object):
    """One addRow() result: text/id members plus an inert `icon` drawing
    surface (scripts do `with (row) { icon.clearAll(); ... }`)."""

    def __init__(self, text: str, row_id: Any):
        super().__init__(name="row")
        self.set("text", text)
        self.set("id", row_id)

    def get(self, key: str) -> Any:
        k = key.lower()
        v = super().get(k)
        if v is None and k not in self._members:
            v = self._members[k] = _InertDrawable(name=f"row.{k}")
        return v

    def has(self, key: str) -> bool:
        # claim everything: `icon` (and friends) must resolve through the
        # with-scope lookup inside `with (row) {...}` blocks
        return True


class GuiControl(GS2Object):
    """Base GS2 GUI control: a script-visible GS2Object (property get/set
    from bytecode) that doubles as a render/hit-test tree node.

    `x`/`y`/`width`/`height`/`text`/`visible`/`profile` are real Python
    attributes (fast, and readable from Python without going through
    GS2Object's dict); any other property a script sets (including
    `onaction`, which ends up holding a Python callable -- see module
    docstring point 2) falls through to the generic member dict.

    Control METHODS (showTop/addRow/...) are exposed as bound callables via
    get(): the VM calls `obj.m(...)` through LValue.get, and -- crucially --
    bare calls inside `with (ctrl) { setIconSize(16,16); }` resolve through
    the VM's with-scope lookup, which only consults `wobj.get(name)`; the
    host's call_builtin never sees the with target, so method names MUST be
    answered here (Login's -Serverlist_Chat builds its whole chat window in
    that style)."""

    CTRL_CLASS = "GuiControl"
    #: profile-definition objects (GuiControlProfile) set this True and are
    #: kept out of the render/hit-test tree by the manager
    is_profile = False

    _NUM_ATTRS = ("x", "y", "width", "height")
    _STR_ATTRS = {"text": "text", "name": "ctrl_name"}
    _EVENT_MEMBERS = {"onaction", "onselect", "ontextchanged"}
    # Registered Torque property surface. The official runtime's with-scope
    # assignment is EXISTENCE-GATED (verified against the reversed
    # interpreter): a construction-block field like `canmove = true;` only
    # lands on the control because the control CLAIMS the name -- so has()
    # must claim every registered property, or those writes fall through to
    # temps/this. Core GuiControl fields plus every field the live Login
    # server's -Serverlist_Chat construction blocks assign.
    _TORQUE_PROPS = frozenset({
        "position", "extent", "minextent", "clientrelative", "clientextent",
        "horizsizing", "vertsizing", "docking", "style", "active", "modal",
        "helptag", "tooltip", "canmove", "canresize", "closequery",
        "destroyonhide",
        "isexternal", "bordercolor", "columncount", "sortorder", "sortmode",
        "groupsortorder", "textprofile", "hscrollbar", "vscrollbar",
        "willfirstrespond", "historysize", "tabcomplete",
        # Login -Rescripted/Serverlist construction fields (taskbar buttons,
        # tree view, tabs) -- existence-gating means unclaimed names fall
        # through to temps, so each must be listed to land on the control.
        "clientwidth", "clientheight", "stylesection", "boxwidth",
        "statuswidth", "fitparentwidth", "columns", "clipcolumntext",
        "wrapcolumntext", "firstlinevisible", "tabwidth", "leveling",
        "canminimize", "canmaximize", "canclose", "tile", "hint",
        # registered on GuiControl in the reference table -- the mobile Login
        # corpus writes all three in construction blocks, where an unclaimed
        # name silently falls through to temps (FourPlay quattroplay/src/gui/
        # GuiControlProperties.cpp:660 clipchildren, :662 cliptobounds,
        # :696 useownprofile)
        "useownprofile", "clipchildren", "cliptobounds",
    })
    _METHOD_NAMES = frozenset({
        "showtop", "show", "hide", "makefirstresponder",
        "seticonsize", "clearrows", "addrow", "sort", "setcolumnoffset",
        "setrowoffset", "resize",
        "pushtoback", "clearcontrols", "isactuallyvisible",
        "isfirstresponder", "bringtofront", "settext", "gettext",
        "setlines", "getlines", "clearall",
        "globaltolocalcoord", "localtoglobalcoord",
        "addtext", "scrolltobottom", "openatmouse",
        # isEmpty() has no entry in
        # the reference client's binding tables (FourPlay quattroplay/src/gui
        # has none) -- it is a Torque control method the live Login corpus
        # calls on its password field, `if (!PassEdit.isEmpty()) doLogin();`
        # (graal-loginserver weapon-Rescripted_IRC_Login2001.txt:64,
        # weapon-LoginScreen.txt:77). Answering it as "the edit buffer is
        # empty" is both the plain reading and the only one consistent with
        # this client's credential policy: pyReborn never lets a script fill
        # or read a password field, so the field IS empty and the
        # auto-login branch correctly does not fire. Unanswered it returned
        # 0.0, i.e. "not empty", which would have taken that branch.
        "isempty",
    })

    def __init__(self, ctor_arg: Any = None):
        super().__init__(name=self.CTRL_CLASS)
        self.ctrl_name: str = ctor_arg if isinstance(ctor_arg, str) else ""
        self.x = 0.0
        self.y = 0.0
        self.width = 100.0
        self.height = 24.0
        self.text = ""
        self.visible = True
        self.profile_name = _DEFAULT_PROFILE_NAME
        #: `profile = IRC_ScrollProfile;` assigns the registered profile
        #: OBJECT (Torque semantics); kept alongside the name so late field
        #: writes (`with (IRC_ScrollProfile) {...}` after control creation)
        #: are seen at draw time
        self.profile_obj: Optional["GuiControlProfile"] = None
        #: `useownprofile = true` gives the control a PRIVATE copy of its
        #: current profile so later `profile.<field> = ...` writes style only
        #: this control (GuiControl::setUseOwnProfile, FourPlay quattroplay/
        #: src/gui/GuiControl.cpp:1746-1806: allocates an anonymous
        #: GuiControlProfile, copyFrom(current), and makes it the effective
        #: profile; false destroys it and reverts). The mobile Login corpus
        #: writes it in 3 scripts' construction blocks.
        self.own_profile: Optional["GuiControlProfile"] = None
        self.parent: Optional["GuiControl"] = None
        self.children: List["GuiControl"] = []
        # Render-only mouse state, maintained by GS2GuiManager the same way
        # it maintains GuiTextEditCtrl.focused -- not script-visible (not
        # routed through get()/set()).
        self.hovered = False
        self.pressed = False
        # back-reference stamped by GS2GuiManager.create_control -- lets
        # bound methods (showTop) reach z-order/focus state
        self._manager = None
        # The GS2VM whose script constructed this control (stamped at its
        # addcontrol; see GS2GuiManager.addcontrol). Live Login's
        # -Serverlist_Chat wires most control events NOT as member closures
        # but as dotted same-script FUNCTIONS ("GlobalChat_ChatField.
        # onAction", "GlobalChat_ChatTab.onSelect", ... -- all registered in
        # vm.functions under the dotted name); fire_event falls back to
        # those, which a member-only lookup left permanently dead.
        self._owner_vm = None
        # generic list-row model (GuiTextListCtrl/GuiContextMenuCtrl style;
        # distinct from GuiPopUpEditCtrl's own `rows`)
        self.list_rows: List[GuiListRow] = []
        self.icon_w = 0.0
        self.icon_h = 0.0
        # last image painted onto this control's `icon` drawing surface
        # (icon.drawimage/drawimagestretched in construction blocks --
        # taskbar buttons); rendered by GuiButtonCtrl
        self.icon_image = ""

    # -- GS2Object property bridge ------------------------------------------

    def get(self, key: str) -> Any:
        k = key.lower()
        if k in self._NUM_ATTRS:
            return float(getattr(self, k))
        if k == "visible":
            return 1.0 if self.visible else 0.0
        if k == "profile":
            # The reference getter returns the OWN profile first, else the
            # referenced profile OBJECT (GuiControlProperties.cpp:411-418) --
            # so `profile.border = 1` after `useownprofile = true` writes the
            # private copy. A name with no registered object falls back to
            # the name string (our pre-object behaviour).
            if self.own_profile is not None:
                return self.own_profile
            if self.profile_obj is not None:
                return self.profile_obj
            if self._manager is not None:
                prof = self._manager.profile_by_name(self.profile_name)
                if prof is not None:
                    return prof
            return self.profile_name
        if k == "useownprofile":
            # derived read: `ownProfile != nullptr`
            # (GuiControlProperties.cpp:559-561)
            return 1.0 if self.own_profile is not None else 0.0
        if k in self._STR_ATTRS:
            return getattr(self, self._STR_ATTRS[k])
        # Torque client-area geometry READS: Login's -Rescripted/Serverlist
        # sizes nearly every child off its parent (`width =
        # Serverlist_Window.clientwidth`, `extent = Serverlist_Panel.extent`,
        # right-aligned taskbar buttons at `clientwidth - width - 25`).
        # These reads previously fell through to the empty member dict ->
        # None -> 0, collapsing the whole layout to zero/negative sizes.
        # These three are DERIVED, never stored: the reference readers hand
        # back m_size (the client size) unconditionally, and the writers
        # resize the outer bounds to suit -- see set() below.
        if k == "clientwidth":
            return float(self.client_width())
        if k == "clientheight":
            return float(self.client_height())
        if k == "clientextent":
            return [float(self.client_width()), float(self.client_height())]
        if k == "extent" and k not in self._members:
            return [float(self.width), float(self.height)]
        if k == "parent" and k not in self._members:
            if self.parent is not None:
                return self.parent
            # a root control's Torque parent is the canvas itself --
            # updateChatBarSize does `ChatBar.parent.clientwidth` on a
            # control added straight to GraalControl; None here read as 0
            # and sized the chat bar to nothing
            return (self._manager.canvas_object()
                    if self._manager is not None else None)
        if k in self._METHOD_NAMES and not super().has(k):
            return getattr(self, "_m_" + k)
        if k == "icon" and k not in self._members:
            # engine drawing surface (`with (button) { icon.drawimage(...) }`)
            # -- records the painted image name into self.icon_image so the
            # renderer can show it (same recorder tree nodes use)
            v = self._members[k] = _TreeNodeIcon(self)
            return v
        return super().get(k)

    # -- script-callable methods -----------------------------------------

    def _m_showtop(self, *args) -> float:
        """showTop(): make visible and raise to the top of the sibling
        z-order (-Serverlist_Chat openChat: GlobalChat_Window.showtop())."""
        if self._manager is not None:
            self._manager.show(self)
        else:
            self.visible = True
        return 0.0

    _m_show = _m_showtop

    def _m_isempty(self, *args) -> bool:
        """isEmpty(): True when this control holds no text. See the
        _METHOD_NAMES note for why the polarity matters on Login."""
        return not to_str(self.text)

    def _m_hide(self, *args) -> float:
        if self._manager is not None:
            self._manager.hide(self)
        else:
            self.visible = False
        return 0.0

    def _m_makefirstresponder(self, *args) -> float:
        if self._manager is not None:
            self._manager.focus(self if not args or to_bool(args[0]) else None)
        return 0.0

    def _m_isfirstresponder(self, *args) -> float:
        """isFirstResponder(): does this control hold keyboard focus?
        Login's staff sprite-editor weapon gates its whole key handler on it
        (`if (<zoom edit>.isFirstResponder()) return;`), so a missing answer
        read 0 and the editor swallowed every keystroke."""
        return 1.0 if (self._manager is not None
                       and self._manager._focus is self) else 0.0

    def _m_bringtofront(self, *args) -> float:
        """bringToFront(): raise to the top of the sibling z-order WITHOUT
        touching visibility (showTop does both). Called bare inside
        construction blocks (`with (window) { ...; bringtofront(); }`)."""
        if self._manager is not None:
            self._manager.bring_to_front(self)
        return 0.0

    def _m_settext(self, *args) -> float:
        self.text = to_str(args[0]) if args else ""
        return 0.0

    def _m_gettext(self, *args) -> str:
        return self.text

    def _m_setlines(self, *args) -> float:
        lines = args[0] if args else []
        if not isinstance(lines, (list, tuple)):
            lines = [lines]
        self.text = "\n".join(to_str(line) for line in lines)
        return 0.0

    def _m_getlines(self, *args) -> List[str]:
        return self.text.split("\n") if self.text else []

    def _m_addtext(self, *args) -> float:
        """addText(text, [scrollToBottom]): append to a log/chat pane
        (`addtext(msg SPC ... NL "", true)` in Login's F2 log window). The
        optional second argument asks the engine to follow the tail, which
        is scrollToBottom()'s job."""
        self.text += to_str(args[0]) if args else ""
        if len(args) > 1 and to_bool(args[1]):
            self._m_scrolltobottom()
        return 0.0

    def _m_openatmouse(self, *args) -> float:
        """openAtMouse(): show this control with its top-left at the
        pointer -- a context menu (the live -ShopGlobal opens its item menu
        this way). The manager records the pointer in the same
        virtual-canvas space control x/y live in, so no remapping is
        needed; with no pointer seen yet the control opens where it is."""
        if self._manager is not None:
            pos = self._manager.last_mouse
            if pos is not None:
                self.x, self.y = float(pos[0]), float(pos[1])
            self._manager.show(self)
        else:
            self.visible = True
        return 0.0

    def _m_scrolltobottom(self, *args) -> float:
        """scrollToBottom(): pin the enclosing scroll view to its end --
        what a chat/log pane does after every appended line."""
        node: Optional["GuiControl"] = self
        for _ in range(_MAX_PARENT_DEPTH):
            if node is None:
                return 0.0
            scroll = node.scroll_container()
            if scroll is not None:
                scroll.scroll_y = scroll.max_scroll_y()
                return 0.0
            node = node.parent
        return 0.0

    def _m_clearall(self, *args) -> float:
        """clearAll(): the engine's "empty this control" verb. On a plain
        control that is its row model (the tree/list subclasses override)."""
        return self._m_clearrows()

    def _m_globaltolocalcoord(self, *args) -> List[float]:
        """globalToLocalCoord({x, y}): canvas coordinates -> this control's
        own coordinate space. Login's staff sprite-editor weapon maps every
        mouse position through it before hit-testing its sprite canvas."""
        x, y = self._coord_arg(args)
        ox, oy = self.effective_offset()
        return [x - (self.x + ox), y - (self.y + oy)]

    def _m_localtoglobalcoord(self, *args) -> List[float]:
        """localToGlobalCoord({x, y}): the inverse -- Login anchors its start
        menu with Serverlist_TaskButton_Start.localtoglobalcoord({0, 0})."""
        x, y = self._coord_arg(args)
        ox, oy = self.effective_offset()
        return [x + self.x + ox, y + self.y + oy]

    @staticmethod
    def _coord_arg(args) -> Tuple[float, float]:
        if len(args) >= 2:
            return to_num(args[0]), to_num(args[1])
        pair = GuiControl._num_pair(args[0]) if args else None
        return pair if pair is not None else (0.0, 0.0)

    def _m_resize(self, *args) -> float:
        """resize(x, y, w, h): position AND extent in one call, on every
        control (FourPlay quattroplay/src/gui/GuiControlProperties.cpp:883,
        body :806-811 -> GuiControl::resize(point, extent)). Login's
        -ScriptedRC GUI editor and the serverlist relayouters use it instead
        of four separate property writes."""
        if len(args) >= 4:
            self.x, self.y = to_num(args[0]), to_num(args[1])
            self.width, self.height = to_num(args[2]), to_num(args[3])
        return 0.0

    def _m_seticonsize(self, *args) -> float:
        if len(args) >= 2:
            self.icon_w, self.icon_h = to_num(args[0]), to_num(args[1])
        return 0.0

    def _m_setcolumnoffset(self, *args) -> float:
        """setColumnOffset(index, offset): the x of column divider `index`.

        Torque's argument order, and the one both live call sites use --
        `setColumnOffset(1, 150)` on a 600-wide two-column frameset
        (Preagonal/gbf/bytecode/login/_Serverlist_Chat.gs2bc.gs2:578, the
        Global Chat window) and `setColumnOffset(1, 210)` on a two-column
        one (_IRC_InstallerGUI.gs2bc.gs2:90). Read the other way round those
        would be "column 150 at offset 1" and "column 210 at offset 1",
        which is nonsense; read this way they are the divider positions the
        layouts obviously want.
        """
        offsets = self._members.setdefault("_column_offsets", {})
        if len(args) >= 2:
            offsets[int(to_num(args[0]))] = to_num(args[1])
        elif args:
            offsets[0] = to_num(args[0])
        return 0.0

    def _m_setrowoffset(self, *args) -> float:
        """setRowOffset(index, offset): the y of row divider `index`.
        Same convention as setColumnOffset; Login's Playerlist splits its PM
        window with `setrowoffset(1, 140)` over a 280-tall 1- or 2-row frameset
        (Preagonal/gbf/bytecode/login/_Playerlist.gs2bc.gs2:2517-2519)."""
        offsets = self._members.setdefault("_row_offsets", {})
        if len(args) >= 2:
            offsets[int(to_num(args[0]))] = to_num(args[1])
        elif args:
            offsets[0] = to_num(args[0])
        return 0.0

    def _m_clearrows(self, *args) -> float:
        self.list_rows.clear()
        return 0.0

    def _m_addrow(self, *args) -> GuiListRow:
        """addRow(id, text) -> row object (scripts then `with (row) {...}`
        to decorate its icon). Argument order is the Torque one, same as
        GuiPopUpEditCtrl's: every Login call site passes the id first
        (`addRow(11, "Global Chat")`, `addRow(0, "Map")`)."""
        row = GuiListRow(to_str(args[1]) if len(args) > 1 else "",
                         args[0] if args else len(self.list_rows))
        self.list_rows.append(row)
        return row

    def _m_sort(self, *args) -> float:
        self.list_rows.sort(key=lambda row: to_str(row.get("text")).casefold())
        return 0.0

    def _m_pushtoback(self, *args) -> float:
        """pushToBack(): send to the back of the sibling z-order (Login's
        Serverlist_MainPanel_Back background bitmap)."""
        siblings = (self.parent.children if self.parent is not None
                    else (self._manager.roots if self._manager else None))
        if siblings and self in siblings:
            siblings.remove(self)
            siblings.insert(0, self)
        return 0.0

    def _m_clearcontrols(self, *args) -> float:
        """clearControls(): remove every child (Login rebuilds its
        Serverlist_TablesPanel0 contents this way on each tab switch).
        Children stay in the name registry -- the rebuild recreates them
        under the same names, which overwrites the entries."""
        for child in list(self.children):
            if self._manager is not None:
                self._manager._release_pointers_under(child)
            self.remove_child(child)
        return 0.0

    def _m_isactuallyvisible(self, *args) -> float:
        """isActuallyVisible(): visible AND every ancestor visible (the
        Torque canvas walk; Login gates its server-map icon refresh on it)."""
        node: Optional["GuiControl"] = self
        visited = set()
        for _ in range(_MAX_PARENT_DEPTH):
            if node is None:
                return 1.0
            if not node.visible or id(node) in visited:
                return 0.0
            visited.add(id(node))
            node = node.parent
        return 0.0

    # -- client-area geometry --------------------------------------------

    def client_inset(self) -> Tuple[float, float]:
        """(outer - client) for this control class: the non-client chrome.
        Zero for a plain control, the title bar for a window."""
        return 0.0, 0.0

    def client_width(self) -> float:
        return max(0.0, self.width - self.client_inset()[0])

    def client_height(self) -> float:
        return max(0.0, self.height - self.client_inset()[1])

    @staticmethod
    def _num_pair(value) -> Optional[Tuple[float, float]]:
        """A Torque two-component field value: {a, b} array or "a b" string."""
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return to_num(value[0]), to_num(value[1])
        parts = to_str(value).replace(",", " ").split()
        if len(parts) >= 2:
            try:
                return float(parts[0]), float(parts[1])
            except ValueError:
                return None
        return None

    def set(self, key: str, value: Any) -> None:
        k = key.lower()
        if k in self._NUM_ATTRS:
            setattr(self, k, to_num(value))
            return
        if k == "visible":
            self.visible = to_bool(value)
            return
        if k == "profile":
            # accept a profile OBJECT (`profile = IRC_ScrollProfile;` -- the
            # bare reference resolves to the registered GuiControlProfile) or
            # a name string; stringifying the object took its repr and every
            # such control fell back to the default flat style
            from .profiles import GuiControlProfile
            # assigning a profile DROPS an active own-profile copy
            # (GuiControl::setProfile, GuiControl.cpp:1688-1710: the branch
            # holding a tooltip/own profile destroys it and nulls the slot)
            self.own_profile = None
            if isinstance(value, GuiControlProfile):
                self.profile_obj = value
                self.profile_name = value.ctrl_name or value.name or ""
            else:
                self.profile_obj = None
                self.profile_name = to_str(value)
            return
        if k == "useownprofile":
            self._set_use_own_profile(to_bool(value))
            return
        if k in self._STR_ATTRS:
            setattr(self, self._STR_ATTRS[k], to_str(value))
            return
        if k in ("clientextent", "clientwidth", "clientheight"):
            # Torque client-area WRITES resize the OUTER bounds so that the
            # CLIENT area ends up the requested size -- the reference is
            #   extent = (bounds.extent - m_size) + clientExtent
            # (propfun_guicontrol_clientextent_w / _clientheight_w, FourPlay
            # quattroplay/src/gui/GuiControlProperties.cpp:115-133). On a
            # plain GuiControl the chrome is 0 and this is a plain extent
            # write; on a GuiWindowCtrl it is the title bar.
            pair = self._num_pair(value)
            if k == "clientwidth":
                pair = (to_num(value), self.client_height())
            elif k == "clientheight":
                pair = (self.client_width(), to_num(value))
            if pair is not None:
                inset = self.client_inset()
                self.width, self.height = pair[0] + inset[0], pair[1] + inset[1]
            return
        if k in ("position", "extent"):
            pair = self._num_pair(value)
            if pair is not None:
                if k == "position":
                    self.x, self.y = pair
                else:
                    self.width, self.height = pair
        super().set(k, value)

    def has(self, key: str) -> bool:
        k = key.lower()
        return (k in self._NUM_ATTRS or k == "visible" or k == "icon"
                or k == "profile"
                or k in self._STR_ATTRS or k in self._EVENT_MEMBERS
                or k in self._TORQUE_PROPS or super().has(k))

    def _set_use_own_profile(self, on: bool) -> None:
        """GuiControl::setUseOwnProfile (FourPlay quattroplay/src/gui/
        GuiControl.cpp:1746-1806): true allocates an anonymous
        GuiControlProfile, copyFrom(current profile), and makes it this
        control's effective profile (idempotent while one exists); false
        destroys it and reverts to the referenced profile."""
        from .profiles import GuiControlProfile
        if not on:
            self.own_profile = None
            return
        if self.own_profile is not None:
            return
        own = GuiControlProfile("")
        own._manager = self._manager
        source = self.profile_obj
        if source is None and self._manager is not None:
            source = self._manager.profile_by_name(self.profile_name)
        if source is not None:
            own.copy_from(source)
        else:
            # unresolvable reference: root the copy's chain at the name so
            # the style still resolves at draw time
            own.parent_profile_name = (self.profile_name or "").lower()
        self.own_profile = own

    def copy_from(self, source: Any) -> None:
        """`someControl.copyfrom(x)` is a SILENT NO-OP in the reference:
        TGraalVar::copyFrom early-returns for engine-owned objects whose
        class table does not opt in (src/TGraalVar.cpp:2208-2214; every
        Gui*Ctrl initObject sets the engine-owned flag and only
        GuiControlProfile's table sets the opt-in bool,
        gui/GuiControlProfileProperties.cpp:618 -- which re-overrides this)."""
        return

    def resolve_profile(self) -> GuiProfile:
        """This control's effective style: the referenced profile's
        inheritance chain merged over builtin field data (see the module's
        Profiles section). Recomputed per draw -- profiles are tiny dicts
        and scripts mutate them after creation (`with (IRC_...Profile)`).
        An own-profile copy (useownprofile) takes precedence, same as the
        reference's effective-profile slot."""
        ref: Any = self.own_profile
        if ref is None:
            ref = self.profile_obj if self.profile_obj is not None \
                else self.profile_name
        mgr = self._manager
        if not ref:
            return _DEFAULT_GUIPROFILE
        return _profile_from_fields(_profile_fields(ref, mgr, set()))

    # -- tree -----------------------------------------------------------

    def add_child(self, child: "GuiControl") -> bool:
        node: Optional["GuiControl"] = self
        visited = set()
        for _ in range(_MAX_PARENT_DEPTH):
            if node is None:
                break
            if node is child or id(node) in visited:
                return False
            visited.add(id(node))
            node = node.parent
        else:
            return False
        if child.parent is not None:
            child.parent.remove_child(child)
        child.parent = self
        self.children.append(child)
        return True

    def remove_child(self, child: "GuiControl") -> None:
        if child in self.children:
            self.children.remove(child)
        if child.parent is self:
            child.parent = None

    def effective_offset(self) -> Tuple[float, float]:
        """Extra (dx, dy) from ancestor state: parent origins (control x/y
        are PARENT-RELATIVE, Torque semantics -- Login's -Rescripted/
        Serverlist places windows at x=280 whose children sit at x=0, and
        window children at y=-22 relative to the client area to overlay the
        title bar; treating x/y as canvas-absolute clumped every nested
        control at the top-left corner) plus ancestor GuiScrollCtrl scroll
        state, composed across nesting. A GuiWindowCtrl parent whose script
        set `clientrelative = true` additionally offsets its children by its
        title-bar height (their coordinates are relative to the client area
        below the title bar; Login's panels use y = -22 to overlay it)."""
        ox = oy = 0.0
        p = self.parent
        visited = set()
        for _ in range(_MAX_PARENT_DEPTH):
            if p is None or id(p) in visited:
                break
            visited.add(id(p))
            ox += p.x
            oy += p.y
            dx, dy = p.child_state_offset()
            ox += dx
            oy += dy
            p = p.parent
        return ox, oy

    def child_state_offset(self) -> Tuple[float, float]:
        return 0.0, 0.0

    def scroll_container(self):
        return None

    def ancestor_window(self):
        return None

    def pointer_down(self, manager, pos) -> bool:
        return False

    def rect(self) -> pygame.Rect:
        ox, oy = self.effective_offset()
        return pygame.Rect(int(self.x + ox), int(self.y + oy),
                           max(0, int(self.width)), max(0, int(self.height)))

    def fire_event(self, event: str, *args) -> bool:
        """Dispatch a control event: a script-assigned member handler first
        (`onAction = function(){...}` -> a bound vm.call closure, or a
        catchevent binding), then the dotted same-script function the live
        servers actually use ("GlobalChat_ChatField.onAction" et al, keyed
        f"{name}.{event}" in the owning VM's function table). Returns True
        if a handler ran. Handler argument conventions (disasm-verified on
        Login's -Serverlist_Chat; params list reversed = call order):
        onAction(text) for a text field, onSelect(entryid, entrytext,
        entryindex), onDblClick(selectedid, selectedtext, selectedrow)."""
        event = event.lower()
        handler = self.get(event)
        if callable(handler):
            try:
                handler(*args)
            except Exception:
                logger.exception("GS2 GUI: %s handler for %s raised",
                                 event, self.ctrl_name or self.CTRL_CLASS)
            return True
        vm = self._owner_vm
        if vm is not None and self.ctrl_name:
            fname = f"{self.ctrl_name}.{event}".lower()
            try:
                if vm.has_function(fname):
                    vm.call(fname, *args)
                    return True
            except Exception:
                logger.exception("GS2 GUI: %s handler for %s raised",
                                 event, self.ctrl_name)
                return True
        return False

    def fire_action(self, *args) -> bool:
        """fire_event("onaction") -- kept as the manager/host entry point."""
        return self.fire_event("onaction", *args)

    # -- render (subclasses override _draw_self) -------------------------

    def draw(self, surf: pygame.Surface, fonts, sprite_mgr=None) -> None:
        self._draw_self(surf, fonts, sprite_mgr)

    def _skin(self, prof: GuiProfile, sprite_mgr) -> Optional["_Skin"]:
        if self._manager is None:
            return None
        return self._manager.skin(prof.bitmap, sprite_mgr)

    def _draw_self(self, surf, fonts, sprite_mgr) -> None:
        # Plain container semantics (Torque GuiControl): draw NOTHING unless
        # the profile is explicitly `opaque` -- containers used to stack
        # translucent fills over the whole canvas, which is why the login
        # screen's background looked layered navy instead of the level.
        prof = self.resolve_profile()
        r = self.rect()
        if prof.opaque:
            skin = self._skin(prof, sprite_mgr)
            if skin is None or not skin.draw_nine(
                    surf, r, 0, int(255 * prof.transparency)):
                _fill_rect(surf, prof.bg if prof.bg is not None
                           else prof.title_bg, r)
                _draw_border(surf, r, prof, skin)
        if self.text and fonts is not None:
            _draw_label(surf, _font(fonts, prof), self.text, prof.fg,
                        (r.x + 4, r.y + 4), prof.text_shadow)


class _TreeNodeIcon(GS2Object):
    """A tree node's `icon` drawing surface: records the image filename the
    script paints (`node.icon.drawimage(0, 0, "graalicon_big.png")`) so the
    tree renderer can blit it; every other member is a no-op callable (same
    contract as _InertDrawable)."""

    def __init__(self, node: "GuiTreeNode"):
        super().__init__(name="node.icon")
        self._node = node

    def get(self, key: str) -> Any:
        k = key.lower()
        if k in ("drawimage", "drawimagestretched"):
            def _draw(*args, _node=self._node, _k=k):
                # drawimage(x, y, image) / drawimagestretched(x,y,w,h, image, ...)
                idx = 2 if _k == "drawimage" else 4
                if len(args) > idx:
                    _node.icon_image = to_str(args[idx])
                return 0.0
            return _draw
        if k in ("clearall", "clear"):
            def _clear(*args, _node=self._node):
                _node.icon_image = ""
                return 0.0
            return _clear
        v = super().get(k)
        return v if v is not None else (lambda *a: 0.0)

    def has(self, key: str) -> bool:
        return True
