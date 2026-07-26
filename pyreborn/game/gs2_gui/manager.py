from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pygame

from reborn_protocol.gs2 import GS2Object, to_num, to_str

from .base import GuiControl
from .collection_controls import GuiStartMenuCtrl, GuiTreeNode
from .factory import make_control
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

    def create_control(self, classname: str, ctor_arg: Any) -> GuiControl:
        ctrl = make_control(classname, ctor_arg)
        ctrl._manager = self
        if ctrl.ctrl_name:
            self._named[ctrl.ctrl_name.lower()] = ctrl
        if ctrl.is_profile:
            # named registration only -- never in the construction stack or
            # the render tree (its auto-emitted addcontrol no-ops below)
            return ctrl
        if self._construction_stack:
            self._construction_stack[-1].add_child(ctrl)
        self._construction_stack.append(ctrl)
        return ctrl

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
        if ctrl.parent is not None:
            ctrl.parent.remove_child(ctrl)
        elif ctrl in self.roots:
            self.roots.remove(ctrl)
        if ctrl.ctrl_name and self._named.get(ctrl.ctrl_name.lower()) is ctrl:
            del self._named[ctrl.ctrl_name.lower()]
        self._release_pointers_under(ctrl)

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
        ctrl.visible = True
        self.bring_to_front(ctrl)

    def hide(self, target: Any) -> None:
        ctrl = self._resolve(target)
        if ctrl is None:
            _log_once(("hide", to_str(target)),
                      "GS2 GUI: hidegui() target not found: %r", target)
            return
        ctrl.visible = False
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
                child.visible = False
                self._release_pointers_under(child)

    def focus(self, target: Any) -> None:
        ctrl = self._resolve(target)
        self._set_focus(ctrl if isinstance(ctrl, GuiTextEditCtrl) else None)

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

    @staticmethod
    def _apply_sizing(ctrl: GuiControl, old_w: float, old_h: float,
                      new_w: float, new_h: float) -> None:
        """Torque GuiControl::parentResized: adjust one control for its
        parent's extent change, then recurse with this control's own
        old/new extent. Defaults ("right"/"bottom") anchor to the top-left
        and change nothing."""
        dx, dy = new_w - old_w, new_h - old_h
        if not dx and not dy:
            return
        old_cw, old_ch = ctrl.width, ctrl.height
        h = to_str(ctrl._members.get("horizsizing", "")).lower() or "right"
        v = to_str(ctrl._members.get("vertsizing", "")).lower() or "bottom"
        if h == "width":
            ctrl.width = max(0.0, ctrl.width + dx)
        elif h == "left":
            ctrl.x += dx
        elif h == "center":
            ctrl.x = (new_w - ctrl.width) / 2.0
        elif h == "relative" and old_w > 0:
            scale = new_w / old_w
            ctrl.x *= scale
            ctrl.width *= scale
        if v == "height":
            ctrl.height = max(0.0, ctrl.height + dy)
        elif v == "top":
            ctrl.y += dy
        elif v == "center":
            ctrl.y = (new_h - ctrl.height) / 2.0
        elif v == "relative" and old_h > 0:
            scale = new_h / old_h
            ctrl.y *= scale
            ctrl.height *= scale
        if (ctrl.width, ctrl.height) != (old_cw, old_ch):
            for child in ctrl.children:
                GS2GuiManager._apply_sizing(child, old_cw, old_ch,
                                            ctrl.width, ctrl.height)
            # NOT fired here: the reference fires onResize("ii", w, h) from
            # GuiControl::resize on EVERY extent change (GuiControl.cpp:
            # 2615-2618) -- i.e. script width/height writes included, a full
            # event-feedback layout loop. Login's Serverlist_*Window.onResize
            # handlers resize EACH OTHER and call updateServerMapIcons();
            # firing them only from this sweep (a state the reference never
            # sees) live-collapsed Serverlist_Map to zero area and nearly
            # doubled the host-call volume on 2026-07-26. All-or-nothing:
            # until every resize path dispatches (with the changed-extent
            # early-outs doing the convergence), fire none of them.

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
        for root in self.roots:
            self._apply_sizing(root, float(old[0]), float(old[1]),
                               float(new_w), float(new_h))
        # The canvas root control resizes too: scripts hang dotted handlers
        # off its fixed names -- `function GraalControl.onResize(newwidth,
        # newheight)` in Login's Rescripted_Serverlist relayouts the whole
        # serverlist UI (weapon-Rescripted_Serverlist.txt:2634, GraalControl3D
        # :2735). There is no control object by that name here, so dispatch
        # the dotted functions across the loaded weapon VMs directly.
        vms = getattr(self.rt2, "vms", None)
        weapon_vms = vms.get("weapon", {}) if isinstance(vms, dict) else {}
        for vm in list(weapon_vms.values()):
            for fname in ("graalcontrol.onresize", "graalcontrol3d.onresize"):
                try:
                    if vm.has_function(fname):
                        vm.call(fname, float(new_w), float(new_h))
                except Exception:
                    logger.exception("GS2 GUI: %s raised on canvas resize", fname)

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
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            return self._on_mouse_down(event.pos)
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            return self._on_mouse_up(event.pos)
        if event.type == pygame.MOUSEMOTION:
            return self._on_mouse_move(event.pos)
        if event.type == pygame.MOUSEWHEEL:
            return self._on_wheel(event)
        if event.type == pygame.KEYDOWN:
            return self._on_keydown(event)
        return False

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
            return False

        window = hit.ancestor_window()
        if window is None:
            window = self._ancestor_window(hit)
        if window is not None:
            self.bring_to_front(window)

        if hit.pointer_down(self, pos):
            return True
        self._set_focus(None)
        return True

    def _toggle_start_menu(self, btn: GuiButtonCtrl) -> bool:
        """Engine behavior with no script-side handler: a taskbar button
        styled as the start button (`stylesection = "Taskbar.StartButton"`,
        Login's Serverlist_TaskButton_Start) toggles the GuiStartMenuCtrl,
        anchored just above it."""
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
        # moving just the window moves its whole subtree
        win.x = pos[0] - off_x
        win.y = pos[1] - off_y
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
