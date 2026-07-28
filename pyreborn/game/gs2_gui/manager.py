from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pygame

from reborn_protocol.gs2 import GS2Object, to_num, to_str

from .base import DOUBLE_CLICK_MS, GuiControl, _same_catcher, catcher_identity
from .collection_controls import GuiStartMenuCtrl, GuiTreeNode
from .factory import make_control
from .keycodes import full_modifier_key, torque_modifier, vk_from_pygame
from .profiles import (
    GuiControlProfile, _BUILTIN_PROFILE_FIELDS, _MAX_PARENT_DEPTH, _log_once, logger,
)
from .skins import _Skin
from .text_controls import GuiScrollCtrl, GuiTextEditCtrl
from .basic_controls import GuiButtonBaseCtrl, GuiButtonCtrl, GuiWindowCtrl
from .popup_controls import GuiPopUpEditCtrl
from .profiles import _DEFAULT_PROFILE_NAME  # noqa: F401  - kept: original import block (star-import consumers rely on it)
from reborn_protocol.gs2 import to_bool  # noqa: F401  - kept: original import block (star-import consumers rely on it)


# =============================================================================
# Manager
# =============================================================================

def _ticks() -> int:
    """Monotonic ms clock for click counting (tests monkeypatch this)."""
    return pygame.time.get_ticks()


class GS2GuiManager:
    """Root of the GS2 GUI control tree.

    Construction (`create_control`/`addcontrol`) is driven purely by call
    order -- see module docstring point 1 for why that's sufficient to infer
    parent/child nesting without addcontrol() ever naming a parent.
    `rt2` (the owning ClientGS2) is unused today but kept for parity with the
    rest of gs2_client.py's host objects and in case a future control type
    needs client/file access (e.g. downloading a not-yet-cached bitmap)."""

    def __init__(self, rt2=None):
        self.rt2 = rt2
        self.roots: List[GuiControl] = []
        self._named: Dict[str, GuiControl] = {}
        self._construction_stack: List[GuiControl] = []
        self._focus: Optional[GuiTextEditCtrl] = None
        self._drag: Optional[Tuple[GuiWindowCtrl, float, float]] = None
        self._window_button_press: Optional[GuiWindowCtrl] = None
        # Render-only mouse state for hover/pressed visuals (button + check-
        # box/radio) -- maintained the same way as `_focus`, via mouse
        # events already flowing through handle_event() (see input.py's
        # _gs2_gui_event, which remaps every MOUSEMOTION into virtual-canvas
        # coordinates before forwarding it here).
        self._hover: Optional[GuiControl] = None
        self._pressed: Optional[GuiControl] = None
        self._open_popup: Optional[GuiPopUpEditCtrl] = None
        # (ticks, node) of the last tree-view row click, for double-click
        # detection (onDblClick = connect on the Login server list)
        self._last_tree_click: Tuple[int, Optional[GuiTreeNode]] = (0, None)
        # canvas first responder: the control keyboard script events go to
        # (distinct from _focus, which is the text-edit TYPING slot -- a
        # button can be first responder without capturing gameplay keys)
        self._first_responder: Optional[GuiControl] = None
        # script mouse-event state: hover control for onMouseEnter/Leave,
        # the mouse-locked control (receives everything until release), and
        # the click counter (same button within DOUBLE_CLICK_MS increments)
        self._script_hover: Optional[GuiControl] = None
        self._mouse_lock: Optional[GuiControl] = None
        self._lock_button = 0
        self._click_count = 0
        self._click_ticks = 0
        self._click_button = 0
        # control the current built-in press started on (pointer_up routing)
        self._press_target: Optional[GuiControl] = None
        # catchevent registrations for control names that don't exist yet:
        # name -> event -> [[catcher_vm, handler_name], ...]; adopted by
        # create_control (TScriptSpace.cpp:1662-1764's pending TEventObject)
        self._pending_catchers: Dict[str, Dict[str, List[list]]] = {}
        # skin-art cache (profile bitmap sheets, sliced) + one-shot file
        # requests for art the sprite manager doesn't have yet
        self._skins: Dict[str, _Skin] = {}
        self._requested_images: set = set()
        # last pointer position seen by handle_event, already in the
        # virtual-canvas space control x/y live in (see handle_event's
        # docstring) -- what openAtMouse() anchors to
        self.last_mouse: Optional[Tuple[int, int]] = None
        # canvas size the control tree was last laid out for; render()
        # compares against the live surface and propagates Torque-sizing
        # deltas on change (window resizes)
        self.canvas_size: Optional[Tuple[int, int]] = None
        # GuiCanvas cursor visibility (cursorOn/cursorOff/isCursorOn --
        # FourPlay quattroplay/src/gui/GuiCanvas.cpp:48-63, bindings :82-84).
        # The canvas starts with the pointer shown, which is also pygame's
        # default, so cursorOn() -- the only one of the three any corpus
        # actually calls -- is a confirmation rather than a change.
        self.cursor_on = True

    def set_cursor_on(self, on: bool) -> None:
        """cursorOn()/cursorOff(): show or hide the mouse pointer over the
        canvas. Login's serverlist calls cursorOn() when it takes over the
        screen (graal-loginserver weapon-Rescripted_Serverlist.txt:379)."""
        self.cursor_on = bool(on)
        try:
            pygame.mouse.set_visible(self.cursor_on)
        except Exception:      # no display yet / headless SDL driver
            pass

    @property
    def keyboard_captured(self) -> bool:
        """True while a text-edit control holds keyboard focus, so gameplay
        held-key movement must not run alongside typing."""
        return self._focus is not None

    # -- construction --------------------------------------------------------

    def register_native_control(self, classname: str, name: str) -> GuiControl:
        """Register a client-owned control without attaching it to the canvas."""
        existing = self._named.get(name.lower())
        if existing is not None:
            return existing
        ctrl = make_control(classname, name)
        ctrl._manager = self
        self._named[name.lower()] = ctrl
        return ctrl

    def create_control(self, classname: str, ctor_arg: Any) -> GuiControl:
        # Named `new` REUSES a live same-named engine object: the reference
        # looks the name up in universe->vars and returns the EXISTING
        # object -- identity, members, children and catchevent registrations
        # all survive and NO reset happens (the construction block's writes
        # simply re-apply); only a PLAIN script variable holding the name is
        # replaced by a fresh engine object, and the requested class is not
        # even consulted on reuse (TScriptMachine::createObject,
        # TScriptMachine.cpp:1135-1157). Login's onServerLogin re-runs
        # initGraalControlSize(); without reuse each run minted a ghost
        # ChatBar+toggle root that kept rendering while script writes only
        # reached the newest copy -- a successful hide looked inert.
        if isinstance(ctor_arg, str) and ctor_arg:
            existing = self._named.get(ctor_arg.lower())
            if isinstance(existing, GuiControl):
                if not existing.is_profile:
                    if self._construction_stack:
                        if (self._construction_stack[-1].add_child(existing)
                                and existing in self.roots):
                            self.roots.remove(existing)
                    self._construction_stack.append(existing)
                self._adopt_plain_global(existing)
                return existing
        ctrl = make_control(classname, ctor_arg)
        ctrl._manager = self
        if ctrl.ctrl_name:
            self._named[ctrl.ctrl_name.lower()] = ctrl
            self._adopt_plain_global(ctrl)
            # adopt catchevent registrations made before this control existed
            pending = self._pending_catchers.pop(ctrl.ctrl_name.lower(), None)
            if pending:
                for event, entries in pending.items():
                    for vm, handler in entries:
                        ctrl.add_event_catcher(event, vm, handler)
        if ctrl.is_profile:
            # named registration only -- never in the construction stack or
            # the render tree (its auto-emitted addcontrol no-ops below)
            return ctrl
        if self._construction_stack:
            self._construction_stack[-1].add_child(ctrl)
        self._construction_stack.append(ctrl)
        return ctrl

    def _adopt_plain_global(self, ctrl: GuiControl) -> None:
        """The reference's createObject REPLACES a plain script variable
        already holding the new object's name: the variable is removed from
        universe vars, the fresh engine object adopts its members
        (copyVarsFrom) and takes over the binding (TScriptMachine.cpp:
        1135-1157) -- engine objects are never replaced (that is the reuse
        path above). Without this, Login's Options tab fires onSelect
        during construction, whose `Opt*Pane2D.visible` writes vivify plain
        globals BEFORE the panes exist; those then shadow the real controls
        in every later name lookup, and the pane with-blocks leak their
        geometry onto the enclosing window (76px-tall Options)."""
        store = getattr(self.rt2, "globals_store", None)
        if store is None or not ctrl.ctrl_name:
            return
        key = ctrl.ctrl_name.lower()
        prev = store.get(key)
        if prev is None or prev is ctrl:
            return
        if isinstance(prev, GuiControl) or type(prev) is not GS2Object:
            # a non-plain-object global (another engine object, a scalar):
            # the engine only replaces plain VARIABLES; scalars are Var-type
            # too and get deleted with the binding
            if not isinstance(prev, GS2Object):
                store[key] = ctrl
            return
        for member, value in list(prev._members.items()):
            ctrl.set(member, value)
        store[key] = ctrl

    def addcontrol(self, ctrl: Any, owner_vm: Any = None) -> None:
        if isinstance(ctrl, str):
            # the inline-new compile shape (`Name = new ("Class") {...}`,
            # see Login's -Serverlist_Chat addChatWindowControls) passes the
            # control's NAME string to its auto-emitted addcontrol
            ctrl = self._named.get(ctrl.lower(), ctrl)
        if not isinstance(ctrl, GuiControl):
            _log_once(("addcontrol", type(ctrl).__name__),
                      "GS2 GUI: addcontrol() called on a non-control value (%r)", ctrl)
            return
        ctrl._manager = self
        if owner_vm is not None and ctrl._owner_vm is None:
            # every new-statement emits addcontrol from the constructing
            # script's VM, so this stamps the whole tree -- fire_event's
            # dotted-handler fallback resolves against it
            ctrl._owner_vm = owner_vm
        if ctrl.is_profile:
            return
        # Pop by identity, not just the top: if a script aborted mid-`new`
        # (VM error/op budget), descendants above ctrl never saw their
        # auto-emitted addcontrol. They're already parented under ctrl, so
        # dropping them from the stack is safe.
        if ctrl in self._construction_stack:
            idx = self._construction_stack.index(ctrl)
            del self._construction_stack[idx:]
        if ctrl.parent is None and ctrl not in self.roots:
            self.roots.append(ctrl)
        # attach into the live tree wakes the subtree (addObject into an
        # awake parent / canvas attach, GuiControl.cpp:2260-2261); a nested
        # child under a still-under-construction parent waits for the
        # outermost addcontrol.
        # PINNED DIVERGENCE: a parentless finished construction roots and
        # wakes IMMEDIATELY, so `HiddenParent.addcontrol(new ...)` sees one
        # transient-root onShow before add_to reparents it under the hidden
        # parent (the reference attaches nothing until explicit placement,
        # firing nothing until real effective visibility). Deferring the
        # awaken to a post-call flush would shift EVERY onWake/onShow on
        # live Login relative to same-call script code under this model's
        # synchronous dispatch -- judged too risky; pinned by
        # test_transient_root_show_divergence_is_pinned.
        if not ctrl._awake and (ctrl.parent is None
                                or ctrl.parent._awake):
            ctrl.awaken()

    def _reap_construction_leak(self) -> None:
        """Valid construction is synchronous within one VM execution, so the
        stack must be empty whenever render()/handle_event() run. Residue
        means a script aborted mid-`new` (error cap / op budget) and its
        auto-emitted addcontrol never fired — without this reset every later
        `new` from ANY script would silently parent under the dead control.
        Per the C# client's semantics the un-added outermost control never
        reaches the canvas, so it is simply dropped."""
        if self._construction_stack:
            _log_once(("construction_leak", self._construction_stack[0].name),
                      "GS2 GUI: script aborted mid-construction; dropping %d "
                      "unfinished control(s)", len(self._construction_stack))
            self._construction_stack.clear()

    def destroy(self, target: Any) -> None:
        ctrl = self._resolve(target)
        if ctrl is None:
            return
        # capture the ancestor chain's visibility BEFORE detaching: the
        # teardown onHide pass needs to know whether this subtree was
        # actually on screen
        ancestors_visible = (ctrl.parent.effectively_visible()
                             if ctrl.parent is not None else True)
        if ctrl.parent is not None:
            ctrl.parent.remove_child(ctrl)
        elif ctrl in self.roots:
            self.roots.remove(ctrl)
        if ctrl.ctrl_name and self._named.get(ctrl.ctrl_name.lower()) is ctrl:
            del self._named[ctrl.ctrl_name.lower()]
        self._release_pointers_under(ctrl)
        ctrl.sleep_subtree(ancestors_visible)

    def _release_pointers_under(self, ctrl: GuiControl) -> None:
        """Drop keyboard focus / an active drag / hover / pressed state held
        by ctrl OR any of its descendants. Scripts close whole windows
        (hidegui/destroy on the container), so an exact-identity check would
        leave a vanished text edit holding focus — and keyboard_captured
        would block player movement with nothing visible on screen. Same
        reasoning applies to a vanished button being left permanently
        "hovered"/"pressed"."""
        if self._focus is not None and self._is_or_descends(self._focus, ctrl):
            self._set_focus(None)
        if self._drag is not None and self._is_or_descends(self._drag[0], ctrl):
            self._drag = None
        if (self._window_button_press is not None
                and self._is_or_descends(self._window_button_press, ctrl)):
            self._window_button_press.close_button_pressed = False
            self._window_button_press.minimize_button_pressed = False
            self._window_button_press.maximize_button_pressed = False
            self._window_button_press = None
        if self._hover is not None and self._is_or_descends(self._hover, ctrl):
            self._set_hover(None)
        if self._pressed is not None and self._is_or_descends(self._pressed, ctrl):
            self._set_pressed(None)
        if (self._first_responder is not None
                and self._is_or_descends(self._first_responder, ctrl)):
            self.set_first_responder(None)
        if (self._script_hover is not None
                and self._is_or_descends(self._script_hover, ctrl)):
            self._script_hover = None
        if (self._mouse_lock is not None
                and self._is_or_descends(self._mouse_lock, ctrl)):
            self._mouse_lock = None
        if (self._press_target is not None
                and self._is_or_descends(self._press_target, ctrl)):
            self._press_target = None
        if (self._open_popup is not None and
                self._is_or_descends(self._open_popup, ctrl)):
            self._close_popup()

    @staticmethod
    def _is_or_descends(node: GuiControl, ancestor: GuiControl) -> bool:
        visited = set()
        for _ in range(_MAX_PARENT_DEPTH):
            if node is None or id(node) in visited:
                return False
            visited.add(id(node))
            if node is ancestor:
                return True
            node = node.parent
        return False

    def _resolve(self, target: Any) -> Optional[GuiControl]:
        if isinstance(target, GuiControl):
            return target
        if isinstance(target, str):
            return self._named.get(target.lower())
        return None

    def profile_by_name(self, name: str) -> Optional["GuiControlProfile"]:
        """The registered profile object for `name`, auto-vivifying
        engine-builtin profiles (GuiBlueTransWindowProfile,
        GuiDefaultProfile, ...) on first reference: the official client
        defines those natively, so both `profile = GuiBlueTransWindowProfile;`
        (bare object reference) and `with (GuiDefaultProfile) {...}`
        restyles must resolve to a live object even though no script ever
        declares one. The vivified object is seeded with the builtin field
        data, so later script writes overlay it like any derived profile."""
        key = (name or "").lower()
        obj = self._named.get(key)
        if isinstance(obj, GuiControlProfile):
            return obj
        if obj is not None:
            return None       # a real control owns this name; don't shadow
        fields = _BUILTIN_PROFILE_FIELDS.get(key)
        if fields is None:
            return None
        prof = GuiControlProfile(name)
        prof.name = name
        prof._manager = self
        prof._members.update(fields)
        self._named[key] = prof
        return prof

    # -- visibility -----------------------------------------------------

    def show(self, target: Any) -> None:
        ctrl = self._resolve(target)
        if ctrl is None:
            _log_once(("show", to_str(target)),
                      "GS2 GUI: showgui() target not found: %r", target)
            return
        ctrl.set_visible(True)
        self.bring_to_front(ctrl)

    def hide(self, target: Any) -> None:
        ctrl = self._resolve(target)
        if ctrl is None:
            _log_once(("hide", to_str(target)),
                      "GS2 GUI: hidegui() target not found: %r", target)
            return
        ctrl.set_visible(False)
        self._release_pointers_under(ctrl)

    def bring_to_front(self, ctrl: GuiControl) -> None:
        siblings = ctrl.parent.children if ctrl.parent is not None else self.roots
        if ctrl in siblings:
            siblings.remove(ctrl)
            siblings.append(ctrl)          # z-order = list order, last = topmost

    def add_to(self, parent: Any, child: Any) -> None:
        parent_ctrl, child_ctrl = self._resolve(parent), self._resolve(child)
        if (parent_ctrl is not None and child_ctrl is not None
                and not child_ctrl.is_profile):
            if parent_ctrl.add_child(child_ctrl) and child_ctrl in self.roots:
                self.roots.remove(child_ctrl)
            if parent_ctrl._awake and not child_ctrl._awake:
                child_ctrl.awaken()      # addcontrol into an awake parent

    def get_child(self, parent: Any, child: Any) -> Any:
        parent_ctrl = self._resolve(parent)
        if parent_ctrl is None:
            return 0.0
        if isinstance(child, str):
            wanted = child.casefold()
            for item in parent_ctrl.children:
                if item.ctrl_name.casefold() == wanted:
                    return item
        else:
            index = int(to_num(child))
            if 0 <= index < len(parent_ctrl.children):
                return parent_ctrl.children[index]
        return 0.0

    def hide_children(self, parent: Any) -> None:
        ctrl = self._resolve(parent)
        if ctrl is not None:
            for child in ctrl.children:
                child.set_visible(False)
                self._release_pointers_under(child)

    def focus(self, target: Any) -> None:
        ctrl = self._resolve(target)
        self.set_first_responder(ctrl if isinstance(ctrl, GuiControl)
                                 and not ctrl.is_profile else None)
        self._set_focus(ctrl if isinstance(ctrl, GuiTextEditCtrl) else None)

    def set_first_responder(self, ctrl: Optional[GuiControl]) -> None:
        """GuiCanvas::setFirstResponder (GuiCanvas.cpp:1411-1433): on change,
        `onFirstResponderChanges(new)` on the universe object (routed
        through the runtime's weapon/NPC event dispatch -- -Playerlist's
        search overlay dismisses itself on it, B/_Playerlist.gs2bc.gs2:
        2906-2922), then onLoseFirstResponder on the old control and
        onBecomeFirstResponder on the new."""
        if ctrl is self._first_responder:
            return
        old, self._first_responder = self._first_responder, ctrl
        trigger = getattr(self.rt2, "trigger_event", None)
        if trigger is not None:
            trigger("onFirstResponderChanges", ctrl)
        if old is not None:
            old.fire_event("onlosefirstresponder")
        if ctrl is not None:
            ctrl.fire_event("onbecomefirstresponder")

    # -- catchevent plumbing ---------------------------------------------

    def register_catchevent(self, target: Any, event: str, vm,
                            handler: str) -> bool:
        """Attach a catcher to a control, by object or by name; an unknown
        NAME registers pending and is adopted when the control is created
        (TScriptSpace::catchEvent, TScriptSpace.cpp:1662-1764). Returns
        False only for an unresolvable non-string target."""
        event = event.lower()
        if isinstance(target, GuiControl):
            target.add_event_catcher(event, vm, handler)
            return True
        if isinstance(target, str) and target:
            ctrl = self._named.get(target.lower())
            if isinstance(ctrl, GuiControl):
                ctrl.add_event_catcher(event, vm, handler)
                return True
            ident = catcher_identity(vm)
            entries = self._pending_catchers.setdefault(
                target.lower(), {}).setdefault(event, [])
            for entry in entries:
                if _same_catcher(entry[0], ident):
                    entry[1] = handler
                    return True
            entries.append([ident, handler])
            return True
        return False

    def unregister_catchevent(self, target: Any, event: str, vm) -> None:
        event = event.lower()
        if isinstance(target, GuiControl):
            target.remove_event_catcher(event, vm)
            return
        if isinstance(target, str) and target:
            ctrl = self._named.get(target.lower())
            if isinstance(ctrl, GuiControl):
                ctrl.remove_event_catcher(event, vm)
                return
            entries = self._pending_catchers.get(target.lower(), {}).get(event)
            if entries:
                ident = catcher_identity(vm)
                entries[:] = [e for e in entries
                              if not _same_catcher(e[0], ident)]

    def _resolve_catcher_vm(self, ident) -> Any:
        """See GuiControl._resolve_catcher_vm -- the (kind, key) identities
        resolve against the runtime's live VM table."""
        if not isinstance(ident, tuple):
            return ident
        vms = getattr(self.rt2, "vms", None)
        if isinstance(vms, dict) and len(ident) == 2:
            return vms.get(ident[0], {}).get(ident[1])
        return None

    def _all_vms(self) -> list:
        seen = set()
        out = []
        vms = getattr(self.rt2, "vms", None)
        if isinstance(vms, dict):
            for kind in ("weapon", "npc"):
                for vm in list(vms.get(kind, {}).values()):
                    if id(vm) not in seen:
                        seen.add(id(vm))
                        out.append(vm)
        return out

    def fire_unbound_event(self, name: str, event: str, *args) -> bool:
        """Dispatch an event addressed to a control NAME with no live object
        behind it -- the canvas root's fixed names (GraalControl /
        GraalControl3D, which scripts hang dotted handlers and catchevents
        off even though no such control exists in this model). A real
        control by that name gets normal fire_event; otherwise pending
        catchers and the dotted functions across every loaded VM run, with
        the NAME standing in for the source-object prepend."""
        key = name.lower()
        ctrl = self._named.get(key)
        if isinstance(ctrl, GuiControl) and not ctrl.is_profile:
            return ctrl.fire_event(event, *args)
        event = event.lower()
        handled = False
        entries = self._pending_catchers.get(key, {}).get(event)
        for entry in list(entries or ()):
            ident, handler = entry
            if not handler:
                continue
            vm = self._resolve_catcher_vm(ident)
            if vm is None:
                if entry in entries:
                    entries.remove(entry)
                continue
            try:
                vm.call(handler, name, *args)
            except Exception:
                logger.exception("GS2 GUI: %s catcher %s for %s raised",
                                 event, handler, name)
            handled = True
        fname = f"{key}.{event}"
        for vm in self._all_vms():
            try:
                if vm.has_function(fname):
                    vm.call(fname, *args)
                    handled = True
            except Exception:
                logger.exception("GS2 GUI: %s raised", fname)
                handled = True
        return handled

    # -- skin art / downloads --------------------------------------------

    def request_image(self, name: str) -> None:
        """Ask the server for a GUI image once (skin sheets, tree icons,
        bitmap controls) via the client's normal file-request path; the
        game's on_file callback drops it into the sprite cache."""
        key = to_str(name).lower()
        if not key or key in self._requested_images:
            return
        self._requested_images.add(key)
        client = getattr(self.rt2, "client", None)
        request = getattr(client, "request_file", None)
        if request is None:
            return
        try:
            request(name)
        except Exception:
            logger.exception("GS2 GUI: request_file(%r) failed", name)

    def skin(self, name: str, sprite_mgr) -> Optional[_Skin]:
        """The sliced skin sheet for a profile's bitmap field, fetching the
        file on first miss. Cache entries pin their source surface and are
        re-sliced when the sprite cache replaces it (download landing)."""
        if not name or sprite_mgr is None:
            return None
        key = name.lower()
        sheet = sprite_mgr.load_sheet(name)
        if sheet is None:
            self.request_image(name)
            return None
        entry = self._skins.get(key)
        if entry is not None and entry.source is sheet:
            return entry
        try:
            entry = _Skin(name, sheet)
        except Exception:
            logger.exception("GS2 GUI: skin slice failed for %r", name)
            return None
        self._skins[key] = entry
        return entry

    # -- canvas resize (Torque horizSizing/vertSizing) -------------------
    # The per-control sizing cascade lives on GuiControl.on_parent_resized /
    # resize_control now, so canvas resizes dispatch onResize/onMove through
    # the same choke point every other resize path uses.

    def canvas_object(self) -> GS2Object:
        """Live-geometry stand-in for the canvas, handed out as root
        controls' `parent` (Torque semantics)."""
        obj = getattr(self, "_canvas_obj", None)
        if obj is None:
            obj = self._canvas_obj = GS2Object(name="canvas")
        if self.canvas_size is not None:
            w, h = float(self.canvas_size[0]), float(self.canvas_size[1])
        else:
            gs1 = getattr(self.rt2, "gs1", None)
            w = float(getattr(gs1, "screen_w", 800) or 800)
            h = float(getattr(gs1, "screen_h", 600) or 600)
        obj._members.update({
            "width": w, "height": h, "clientwidth": w, "clientheight": h,
            "extent": [w, h], "clientextent": [w, h],
        })
        return obj

    def on_canvas_resize(self, new_w: int, new_h: int) -> None:
        old = self.canvas_size
        self.canvas_size = (new_w, new_h)
        if old is None or old == (new_w, new_h):
            return
        for root in list(self.roots):
            root.on_parent_resized(float(old[0]), float(old[1]),
                                   float(new_w), float(new_h))
        # The canvas root control resizes too: scripts hang dotted handlers
        # off its fixed names -- `function GraalControl.onResize(newwidth,
        # newheight)` in Login's Rescripted_Serverlist relayouts the whole
        # serverlist UI (weapon-Rescripted_Serverlist.txt:2634, GraalControl3D
        # :2735). There is no control object by those names here, so they go
        # through the unbound-name dispatch (dotted functions + pending
        # catchevents across the loaded VMs).
        for cname in ("graalcontrol", "graalcontrol3d"):
            self.fire_unbound_event(cname, "onresize",
                                    float(new_w), float(new_h))

    # -- render ---------------------------------------------------------

    def render(self, surf: pygame.Surface, fonts=None, sprite_mgr=None) -> None:
        self._reap_construction_leak()
        self._close_invalid_popup()
        self.on_canvas_resize(*surf.get_size())
        for root in self.roots:
            self._draw_node(root, surf, fonts, sprite_mgr, None)
        if self._open_popup is not None:
            surf.set_clip(None)
            self._open_popup.draw_popup(surf, fonts)
        surf.set_clip(None)

    def _draw_node(self, node: GuiControl, surf, fonts, sprite_mgr, clip) -> None:
        if not node.visible:
            return
        surf.set_clip(clip)
        node.draw(surf, fonts, sprite_mgr)
        child_clip = clip
        if node.scroll_container() is not None:
            r = node.rect()
            child_clip = r if clip is None else clip.clip(r)
        for c in node.children:
            self._draw_node(c, surf, fonts, sprite_mgr, child_clip)

    # -- hit-testing ------------------------------------------------------

    def hit_test(self, pos: Tuple[int, int]) -> Optional[GuiControl]:
        for root in reversed(self.roots):          # topmost root first
            hit = self._hit_test(root, pos)
            if hit is not None:
                return hit
        return None

    def _hit_test(self, node: GuiControl, pos) -> Optional[GuiControl]:
        if not node.visible or not node.rect().collidepoint(pos):
            return None
        for c in reversed(node.children):           # topmost child first
            hit = self._hit_test(c, pos)
            if hit is not None:
                return hit
        return node

    def _ancestor_window(self, ctrl: GuiControl) -> Optional[GuiWindowCtrl]:
        p = ctrl.parent
        visited = set()
        for _ in range(_MAX_PARENT_DEPTH):
            if p is None or id(p) in visited:
                return None
            visited.add(id(p))
            window = p.ancestor_window()
            if window is not None:
                return window
            p = p.parent
        return None

    def _topmost_window(self) -> Optional[GuiWindowCtrl]:
        for root in reversed(self.roots):
            window = root.ancestor_window()
            if window is not None and root.visible:
                return window
        return None

    def _set_focus(self, ctrl: Optional[GuiTextEditCtrl]) -> None:
        if self._focus is ctrl:
            return
        if self._focus is not None:
            self._focus.focused = False
        self._focus = ctrl
        if ctrl is not None:
            ctrl.focused = True

    def _set_hover(self, ctrl: Optional[GuiControl]) -> None:
        if self._hover is ctrl:
            return
        if self._hover is not None:
            self._hover.hovered = False
        self._hover = ctrl
        if ctrl is not None:
            ctrl.hovered = True

    def _set_pressed(self, ctrl: Optional[GuiControl]) -> None:
        if self._pressed is ctrl:
            return
        if self._pressed is not None:
            self._pressed.pressed = False
        self._pressed = ctrl
        if ctrl is not None:
            ctrl.pressed = True

    def _close_popup(self) -> None:
        if self._open_popup is None:
            return
        self._open_popup.popup_open = False
        self._open_popup.hover_row = -1
        self._open_popup = None
        self._set_hover(None)
        self._set_pressed(None)

    def _open_popup_for(self, ctrl: GuiPopUpEditCtrl) -> None:
        if self._open_popup is not ctrl:
            self._close_popup()
        self._open_popup = ctrl
        ctrl.popup_open = True

    def _close_invalid_popup(self) -> None:
        popup = self._open_popup
        if popup is None:
            return
        node: Optional[GuiControl] = popup
        visited = set()
        for _ in range(_MAX_PARENT_DEPTH):
            if node is None:
                break
            if id(node) in visited:
                self._close_popup()
                return
            visited.add(id(node))
            if not node.visible:
                self._close_popup()
                return
            node = node.parent
        else:
            self._close_popup()
            return
        if popup.parent is None and popup not in self.roots:
            self._close_popup()

    def _activate_button(self, btn: "GuiButtonBaseCtrl") -> None:
        """User activation: the engine's onAction(), which owns the toggle
        flip and the radio-group sweep (see GuiButtonBaseCtrl.on_action).
        One deliberate divergence: re-clicking an already-checked radio is a
        no-op here, where the reference re-fires onAction."""
        if btn.button_type == 2 and btn.checked:
            return
        btn.on_action()

    def _shift(self, ctrl: GuiControl, dx: float, dy: float) -> None:
        ctrl.x += dx
        ctrl.y += dy
        for c in ctrl.children:
            self._shift(c, dx, dy)

    # -- events -----------------------------------------------------------

    def handle_event(self, event) -> bool:
        """True = consumed. Assumes `event.pos` is already in the same
        virtual-canvas coordinate space the control tree's x/y live in
        (the pygame_screens.py convention: the caller remaps window coords
        via viewport.window_to_virtual() before calling in)."""
        self._reap_construction_leak()
        self._close_invalid_popup()
        pos = getattr(event, "pos", None)
        if pos is not None:
            self.last_mouse = (int(pos[0]), int(pos[1]))
        # Script events first, before any built-in handling, and they can
        # never consume the event -- consumption is decided exclusively by
        # the built-in chain (GuiCanvas.cpp:494-516 for mouse, :958-966 for
        # keys; handler return values are discarded by the dispatcher).
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP,
                          pygame.MOUSEMOTION, pygame.MOUSEWHEEL):
            self._fire_pointer_scripts(event)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            return self._on_mouse_down(event.pos)
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            return self._on_mouse_up(event.pos)
        if event.type == pygame.MOUSEMOTION:
            return self._on_mouse_move(event.pos)
        if event.type == pygame.MOUSEWHEEL:
            return self._on_wheel(event)
        if event.type == pygame.KEYDOWN:
            self._fire_key_script(event, "onkeydown")
            consumed = self._on_keydown(event)
            if not consumed:
                self._fire_universe_key(event)
            return consumed
        if event.type == pygame.KEYUP:
            self._fire_key_script(event, "onkeyup")
            return False
        return False

    # -- script input events ----------------------------------------------

    def _mouse_args(self, pos) -> tuple:
        """The uniform 5-arg mouse signature (modifier, mousex, mousey,
        clickcount, deviceid) in GLOBAL canvas pixels, deviceid 0
        (GuiControl::sendMouseEvent, GuiControl.cpp:2079-2082,
        asm-verified)."""
        try:
            mods = pygame.key.get_mods()
        except Exception:                      # no keyboard subsystem
            mods = 0
        return (float(torque_modifier(mods)), float(pos[0]), float(pos[1]),
                float(self._click_count), 0.0)

    def _fire_pointer_scripts(self, event) -> None:
        """Script mouse events (GuiCanvas::rootMouseEvent, GuiCanvas.cpp:
        419-517): the mouse-locked control receives everything until
        release, otherwise the hover control from the hit test; moves with
        the locking button held are onMouseDragged; hover changes fire
        onMouseEnter/onMouseLeave (GuiCanvas.cpp:519-531). Skipped while
        the popup overlay is open (a transient engine surface with no
        script identity)."""
        if self._open_popup is not None:
            return
        if event.type == pygame.MOUSEWHEEL:
            pos = self.last_mouse or (0, 0)
            target = self._mouse_lock or self.hit_test(pos)
            if target is not None and event.y:
                target.fire_event(
                    "onmousewheelup" if event.y > 0 else "onmousewheeldown",
                    *self._mouse_args(pos))
            return
        pos = event.pos
        if event.type == pygame.MOUSEBUTTONDOWN and event.button in (1, 3):
            now = _ticks()
            if (event.button == self._click_button
                    and now - self._click_ticks <= DOUBLE_CLICK_MS):
                self._click_count += 1
            else:
                self._click_count = 1
                self._click_button = event.button
            self._click_ticks = now
            target = self._mouse_lock or self.hit_test(pos)
            if target is not None:
                # arm the lock BEFORE firing: a handler that destroys the
                # control runs destroy() -> _release_pointers_under, which
                # clears the lock -- arming after the fire would re-pin the
                # dead control until button release
                self._mouse_lock = target      # buttons lock down -> up
                self._lock_button = event.button
                target.fire_event(
                    "onmousedown" if event.button == 1 else "onrightmousedown",
                    *self._mouse_args(pos))
            return
        if event.type == pygame.MOUSEBUTTONUP and event.button in (1, 3):
            target = self._mouse_lock or self.hit_test(pos)
            if target is not None:
                target.fire_event(
                    "onmouseup" if event.button == 1 else "onrightmouseup",
                    *self._mouse_args(pos))
            if self._mouse_lock is not None and event.button == self._lock_button:
                self._mouse_lock = None
            return
        if event.type == pygame.MOUSEMOTION:
            buttons = getattr(event, "buttons", (0, 0, 0))
            if self._mouse_lock is not None and (buttons[0] or buttons[2]):
                self._mouse_lock.fire_event(
                    "onmousedragged" if self._lock_button == 1
                    else "onrightmousedragged", *self._mouse_args(pos))
                return
            hit = self.hit_test(pos)
            old = self._script_hover
            entered = hit is not old
            if entered:
                # arm before firing (same destroy-in-handler reasoning as
                # the lock above): if the leave handler destroys the entered
                # control, _release_pointers_under clears _script_hover and
                # the enter/move fires below are skipped
                self._script_hover = hit
                if old is not None:
                    old.fire_event("onmouseleave", *self._mouse_args(pos))
            if entered and hit is not None and self._script_hover is hit:
                hit.fire_event("onmouseenter", *self._mouse_args(pos))
            if hit is not None and self._script_hover is hit:
                hit.fire_event("onmousemove", *self._mouse_args(pos))

    def _fire_key_script(self, event, name: str) -> None:
        """onKeyDown/onKeyUp(keycode, keytext, repeatcount) on the first
        responder only, before built-in key handling (GuiCanvas.cpp:
        882-1011, script event at :958-965). With no first responder the
        canvas root ("GraalControl") is the stand-in target, same as the
        onresize dispatch -- Login's Tab-opens-chatbar handler lives there."""
        vk = vk_from_pygame(event.key)
        if not vk:
            return
        keycode = float(full_modifier_key(vk, getattr(event, "mod", 0)))
        text = getattr(event, "unicode", "") or ""
        fr = self._first_responder
        if fr is not None:
            fr.fire_event(name, keycode, text, 1.0)
        else:
            self.fire_unbound_event("graalcontrol", name, keycode, text, 1.0)

    def _fire_universe_key(self, event) -> None:
        """Universe onControlKeyDown(keycode, keytext, scancode, window) for
        a key no GUI control consumed -- the F2/F7 window togglers'
        engine-side feed (official handlers: B/_F2LogWindow.gs2bc.gs2:
        240-257, B/_Playerlist.gs2bc.gs2:685-702, both disasm-corrected:
        `keycode==113/118 || (window=="<own window>" && keycode==27)`).

        The reference fires it from the OS-window key pump with the
        detached window's name, `""` for the main window (TWindow.cpp:
        339-348 fires the literal ""; the name-passing arm is inferred from
        the scripts' window== branches). This client renders everything
        internally, so window is ALWAYS "" here -- which keeps the Esc arms
        correctly dead and the F-key arms live. Also fires the GS1-style
        raw-keyboard onKeyPressed(keycode, keytext, scancode) the
        -Rescripted/-F2LogWindow shim's F4/F6 extras hang off
        (weapon-Rescripted_-F2LogWindow.txt:114-135)."""
        rt2 = self.rt2
        trigger = getattr(rt2, "trigger_event", None)
        if trigger is None:
            return
        vk = vk_from_pygame(event.key)
        if not vk:
            return
        keycode = float(full_modifier_key(vk, getattr(event, "mod", 0)))
        text = getattr(event, "unicode", "") or ""
        scancode = float(getattr(event, "scancode", 0) or 0)
        trigger("onControlKeyDown", keycode, text, scancode, "")
        trigger("onKeyPressed", keycode, text, scancode)

    def _on_mouse_down(self, pos) -> bool:
        if self._open_popup is not None:
            popup = self._open_popup
            row = popup.popup_row_at(pos)
            if row >= 0:
                self._set_pressed(popup)
                popup.select_row(row)
                self._close_popup()
                return True
            self._close_popup()
            return True
        hit = self.hit_test(pos)
        if hit is None:
            self._set_focus(None)
            self.set_first_responder(None)     # click-through to the canvas
            return False

        window = hit.ancestor_window()
        if window is None:
            window = self._ancestor_window(hit)
        if window is not None:
            self.bring_to_front(window)

        self._press_target = hit
        if hit.can_key_focus:
            self.set_first_responder(hit)
        if hit.pointer_down(self, pos):
            return True
        self._set_focus(None)
        return True

    def _toggle_start_menu(self, btn: GuiButtonCtrl) -> bool:
        """Built-in behavior of a taskbar button styled as the start button
        (`stylesection = "Taskbar.StartButton"`, Login's
        Serverlist_TaskButton_Start): toggle the GuiStartMenuCtrl, anchored
        just above it. Runs IN ADDITION to the script onAction dispatch
        (see GuiButtonCtrl.pointer_down) -- engine handling never consumes
        events away from scripts."""
        if to_str(btn._members.get("stylesection", "")).lower() != \
                "taskbar.startbutton":
            return False
        menu = next((c for c in reversed(self.roots)
                     if isinstance(c, GuiStartMenuCtrl)), None)
        if menu is None:
            return False
        if menu.visible:
            self.hide(menu)
            return True
        br = btn.rect()
        menu.height = float(max(menu.content_height(), menu.ROW_H))
        menu.x = float(br.x)
        menu.y = float(br.y - menu.height)
        self.show(menu)
        return True

    def _on_mouse_up(self, pos) -> bool:
        self._set_pressed(None)
        press, self._press_target = self._press_target, None
        if press is not None:
            press.pointer_up(self, pos)
        pressed_window = self._window_button_press
        self._window_button_press = None
        if pressed_window is not None:
            close_pressed = pressed_window.close_button_pressed
            minimize_pressed = pressed_window.minimize_button_pressed
            maximize_pressed = pressed_window.maximize_button_pressed
            pressed_window.close_button_pressed = False
            pressed_window.minimize_button_pressed = False
            pressed_window.maximize_button_pressed = False
            close, minimize, maximize = pressed_window._screen_button_rects()
            if close_pressed and pressed_window.canclose and close.collidepoint(pos):
                pressed_window.close_window()
            elif (minimize_pressed and pressed_window.canminimize
                  and minimize.collidepoint(pos)):
                pressed_window.minimize_window()
            elif (maximize_pressed and pressed_window.canmaximize
                  and maximize.collidepoint(pos)):
                pressed_window.maximize_window()
            return True
        if self._drag is not None:
            self._drag = None
            return True
        return self.hit_test(pos) is not None

    def _on_mouse_move(self, pos) -> bool:
        if self._open_popup is not None:
            popup = self._open_popup
            popup.hover_row = popup.popup_row_at(pos)
            self._set_hover(popup if (popup.hover_row >= 0 or
                                      popup.rect().collidepoint(pos)) else None)
            return True
        hit = self.hit_test(pos)
        self._set_hover(hit if isinstance(
            hit, (GuiButtonBaseCtrl, GuiPopUpEditCtrl)) else None)
        if self._drag is None:
            return False
        win, off_x, off_y = self._drag
        # children's x/y are parent-relative (see effective_offset), so
        # moving just the window moves its whole subtree; routed through the
        # choke point so the drag fires onMove
        win.resize_control(pos[0] - off_x, pos[1] - off_y,
                           win.width, win.height)
        return True

    def _on_wheel(self, event) -> bool:
        pos = getattr(event, "pos", None) or pygame.mouse.get_pos()
        node = self.hit_test(pos)
        visited = set()
        for _ in range(_MAX_PARENT_DEPTH):
            if node is None or isinstance(node, GuiScrollCtrl):
                break
            if id(node) in visited:
                node = None
                break
            visited.add(id(node))
            node = node.parent
        else:
            node = None
        if node is None:
            return False
        node.scroll_y = max(0.0, min(node.scroll_y - event.y * 20.0,
                                     node.max_scroll_y()))
        return True

    def _on_keydown(self, event) -> bool:
        if event.key == pygame.K_ESCAPE:
            if self._open_popup is not None:
                self._close_popup()
                return True
            top = self._topmost_window()
            if top is not None:
                self.hide(top)
                return True
            return False
        if self._focus is None:
            return False
        if event.key == pygame.K_RETURN:
            # onAction(text) -- the reference passes the field's text (the
            # Login chat field's dotted handler declares a `text` param and
            # sends exactly that string)
            self._focus.fire_action(self._focus.text)
            return True
        if event.key == pygame.K_BACKSPACE:
            # a pending setSelection() range is deleted whole, exactly as
            # the reference client does for a select-all-then-edit
            if not self._focus.take_selection():
                self._focus.text = self._focus.text[:-1]
            return True
        if event.unicode and event.unicode.isprintable():
            self._focus.take_selection()
            if len(self._focus.text) < self._focus.max_len:
                self._focus.text += event.unicode
        return True
