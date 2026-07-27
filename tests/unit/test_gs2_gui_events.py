"""GS2 GUI event surface (2026-07-27 oracle-audit wave).

Covers, against the FourPlay decompilation (quattroplay/src, cited per
mechanism in the code under test):

- the multi-catcher dispatch registry (catchevent/ignoreevent, dotted
  handlers across every loaded VM, pending by-name registration);
- the canvas first-responder concept and onKeyDown/onKeyUp;
- script mouse events with the uniform 5-arg signature and click counting;
- GuiTextListCtrl onDblClick;
- onResize/onMove through the single resize choke point;
- onWake/onShow/onHide lifecycle events;
- GuiMLTextCtrl onURL (href retention + press/release-same-link).
"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pygame

import pyreborn.game.gs2_gui.manager as manager_module
from pyreborn.game.gs2_gui.keycodes import (
    full_modifier_key, torque_modifier, vk_from_pygame,
)
from pyreborn.gs2_client import ClientGS2

pygame.init()
pygame.font.init()


class _FakeFonts:
    def get(self, role):
        return pygame.font.Font(None, 16)


class _FakeVM:
    """Stands in for a GS2VM in rt2.vms: has_function/call over a plain
    name -> callable dict (the only surface fire_event touches)."""

    def __init__(self, fns=None):
        self.fns = {k.lower(): v for k, v in (fns or {}).items()}
        self.calls = []

    def has_function(self, name):
        return name.lower() in self.fns

    def call(self, name, *args):
        self.calls.append((name.lower(), args))
        fn = self.fns.get(name.lower())
        return fn(*args) if fn is not None else None


def _mousedown(pos, button=1):
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                              {"pos": pos, "button": button})


def _mouseup(pos, button=1):
    return pygame.event.Event(pygame.MOUSEBUTTONUP,
                              {"pos": pos, "button": button})


def _mousemove(pos, buttons=(0, 0, 0)):
    return pygame.event.Event(pygame.MOUSEMOTION,
                              {"pos": pos, "rel": (0, 0), "buttons": buttons})


def _keydown(key, unicode="", mod=0):
    return pygame.event.Event(pygame.KEYDOWN,
                              {"key": key, "unicode": unicode, "mod": mod})


def _keyup(key, mod=0):
    return pygame.event.Event(pygame.KEYUP, {"key": key, "mod": mod})


# =============================================================================
# 1. Dispatch infrastructure
# =============================================================================

class TestMultiCatcherDispatch:
    def setup_method(self):
        self.rt2 = ClientGS2()
        self.gui = self.rt2.gui
        self.host = self.rt2.host
        self.btn = self.gui.create_control("GuiButtonCtrl", "CatchBtn")
        self.gui.addcontrol(self.btn)

    def test_catchers_accumulate_across_scripts_with_source_prepended(self):
        """Distinct catcher scripts accumulate (TEventCatcherList.cpp:84-108
        delivers to EVERY registered catcher) and the named handler gets the
        source object as params[0] (TScriptSpace.cpp:794-812)."""
        got_a, got_b = [], []
        vm_a = _FakeVM({"onHandlerA": lambda *a: got_a.append(a)})
        vm_b = _FakeVM({"onHandlerB": lambda *a: got_b.append(a)})
        self.host.call_builtin(vm_a, "catchevent",
                               [self.btn, "onAction", "onHandlerA"])
        self.host.call_builtin(vm_b, "catchevent",
                               [self.btn, "onAction", "onHandlerB"])
        self.btn.fire_event("onaction", "payload")
        assert got_a == [(self.btn, "payload")]
        assert got_b == [(self.btn, "payload")]

    def test_same_catcher_reregistration_replaces_handler(self):
        """Re-registering the same (event, catcher) replaces the handler
        name instead of accumulating (TEventCatcherList.cpp:28-56)."""
        got = []
        vm = _FakeVM({"onOld": lambda *a: got.append("old"),
                      "onNew": lambda *a: got.append("new")})
        self.host.call_builtin(vm, "catchevent",
                               [self.btn, "onAction", "onOld"])
        self.host.call_builtin(vm, "catchevent",
                               [self.btn, "onAction", "onNew"])
        self.btn.fire_event("onaction")
        assert got == ["new"]

    def test_pending_registration_attaches_when_control_is_created(self):
        """catchevent on a not-yet-created control name registers pending
        and is adopted at construction (TScriptSpace.cpp:1662-1764)."""
        got = []
        vm = _FakeVM({"onLater": lambda *a: got.append(a)})
        self.host.call_builtin(vm, "catchevent",
                               ["FutureCtrl", "onSelect", "onLater"])
        ctrl = self.gui.create_control("GuiTextListCtrl", "FutureCtrl")
        self.gui.addcontrol(ctrl)
        ctrl.fire_event("onselect", 3.0, "row", 0.0)
        assert got == [(ctrl, 3.0, "row", 0.0)]

    def test_ignoreevent_reverses_registration(self):
        got = []
        vm = _FakeVM({"onGone": lambda *a: got.append(a)})
        self.host.call_builtin(vm, "catchevent",
                               [self.btn, "onAction", "onGone"])
        self.host.call_builtin(vm, "ignoreevent", [self.btn, "onAction"])
        self.btn.fire_event("onaction")
        assert got == []

    def test_dotted_handlers_run_in_every_loaded_vm(self):
        """`function CatchBtn.onAction()` in TWO weapons: the reference
        auto-registers every dotted function as an implicit catcher
        (TScript.cpp:1018-1073), so both run -- not just the owner VM's."""
        ran = []
        self.rt2.vms["weapon"]["w1"] = _FakeVM(
            {"catchbtn.onaction": lambda *a: ran.append(("w1", a))})
        self.rt2.vms["weapon"]["w2"] = _FakeVM(
            {"catchbtn.onaction": lambda *a: ran.append(("w2", a))})
        assert self.btn.fire_event("onaction", "t") is True
        assert ran == [("w1", ("t",)), ("w2", ("t",))]

    def test_member_closure_and_catchers_all_run_for_one_event(self):
        """The on<event>-variable fallback (TScriptSpace.cpp:424-443), the
        catchevent handler and the dotted function are separate catchers --
        all three run for one event."""
        ran = []
        self.btn.set("onaction", lambda *a: ran.append("member"))
        vm = _FakeVM({"onCaught": lambda *a: ran.append("catch"),
                      "catchbtn.onaction": lambda *a: ran.append("dotted")})
        self.rt2.vms["weapon"]["w"] = vm
        self.host.call_builtin(vm, "catchevent",
                               [self.btn, "onAction", "onCaught"])
        self.btn.fire_event("onaction")
        assert ran == ["member", "catch", "dotted"]

    def test_catchevent_follows_live_script_reload(self):
        """Registrations store the catcher's (kind, key) identity, not the
        VM object: after a live script update replaces the VM under the
        same key (ClientGS2.load_bytecode), the NEW VM's handler runs and
        nothing pins the old VM; a key that no longer resolves drops the
        registration."""
        got = []
        old_vm = _FakeVM({"onSwap": lambda *a: got.append("old")})
        old_vm._gs2_owner = ("weapon", "swapper")
        self.rt2.vms["weapon"]["swapper"] = old_vm
        self.host.call_builtin(old_vm, "catchevent",
                               [self.btn, "onAction", "onSwap"])
        # the entry holds the identity tuple -- the old VM is unreachable
        # from the registration
        assert self.btn._event_catchers["onaction"] == \
            [[("weapon", "swapper"), "onswap"]]
        new_vm = _FakeVM({"onSwap": lambda *a: got.append("new")})
        new_vm._gs2_owner = ("weapon", "swapper")
        self.rt2.vms["weapon"]["swapper"] = new_vm
        self.btn.fire_event("onaction")
        assert got == ["new"]
        del self.rt2.vms["weapon"]["swapper"]
        self.btn.fire_event("onaction")
        assert got == ["new"]
        assert self.btn._event_catchers["onaction"] == []

    def test_construction_stack_fallback_for_empty_target_name(self):
        """`thiso.catchevent(this.name, ...)` inside a construction block:
        this.name reads back empty, so the registration falls back to the
        control being constructed (the -Serverlist_Chat smilie wiring)."""
        got = []
        vm = _FakeVM({"onSmilieButton": lambda *a: got.append(a)})
        ctrl = self.gui.create_control("GuiButtonCtrl", None)
        self.host.call_builtin(vm, "catchevent",
                               ["", "onAction", "onSmilieButton"])
        self.gui.addcontrol(ctrl)
        ctrl.fire_event("onaction")
        assert got == [(ctrl,)]


# =============================================================================
# 2. First responder + keyboard
# =============================================================================

class TestFirstResponderKeyboard:
    def setup_method(self):
        self.rt2 = ClientGS2()
        self.gui = self.rt2.gui
        self.edit = self.gui.create_control("GuiTextEditCtrl", "KeyEdit")
        self.edit.x, self.edit.y = 10.0, 10.0
        self.edit.width, self.edit.height = 120.0, 20.0
        self.gui.addcontrol(self.edit)

    def test_click_makes_focusable_control_first_responder(self):
        events = []
        self.edit.set("onbecomefirstresponder", lambda: events.append("become"))
        self.gui.handle_event(_mousedown((15, 15)))
        assert self.gui._first_responder is self.edit
        assert events == ["become"]

    def test_makefirstresponder_fires_lose_then_become(self):
        """Focus change fires onLoseFirstResponder on the old control and
        onBecomeFirstResponder on the new (GuiCanvas.cpp:1411-1433,
        GuiControl.cpp:1107-1123, both no-args)."""
        other = self.gui.create_control("GuiTextEditCtrl", "KeyEdit2")
        self.gui.addcontrol(other)
        order = []
        self.edit.set("onlosefirstresponder", lambda: order.append("lose"))
        other.set("onbecomefirstresponder", lambda: order.append("become"))
        self.edit._m_makefirstresponder()
        other._m_makefirstresponder()
        assert order == ["lose", "become"]

    def test_keydown_script_event_precedes_builtin_and_never_consumes(self):
        """onKeyDown(keycode, keytext, repeatcount) fires on the first
        responder BEFORE the built-in key handling (GuiCanvas.cpp:958-966)
        -- the typed character still lands in the edit buffer."""
        got = []
        self.edit.set("onkeydown", lambda *a: got.append(a))
        self.gui.handle_event(_mousedown((15, 15)))
        self.gui.handle_event(_keydown(pygame.K_a, "A", pygame.KMOD_LSHIFT))
        assert got == [(0x41 + 0x100, "A", 1.0)]
        assert self.edit.text == "A"          # built-in still ran

    def test_keyup_script_event_fires_and_is_not_consumed(self):
        got = []
        self.edit.set("onkeyup", lambda *a: got.append(a))
        self.gui.handle_event(_mousedown((15, 15)))
        assert self.gui.handle_event(_keyup(pygame.K_a)) is False
        assert got == [(0x41, "", 1.0)]

    def test_no_first_responder_dispatches_to_graalcontrol_name(self):
        """With no first responder the canvas root's fixed name is the
        stand-in target -- Login's Tab-opens-chatbar handler is
        `GraalControl.onKeyDown(keycode, keytext)` testing keycode == 9
        (weapon-ServerListScreen.txt:2321-2327)."""
        got = []
        self.rt2.vms["weapon"]["w"] = _FakeVM(
            {"graalcontrol.onkeydown": lambda *a: got.append(a)})
        self.gui.set_first_responder(None)
        self.gui.handle_event(_keydown(pygame.K_TAB, "\t"))
        assert got == [(9.0, "\t", 1.0)]

    def test_click_on_empty_canvas_clears_first_responder(self):
        self.gui.handle_event(_mousedown((15, 15)))
        assert self.gui._first_responder is self.edit
        self.gui.handle_event(_mousedown((700, 500)))
        assert self.gui._first_responder is None

    def test_vk_mapping_spot_checks(self):
        assert vk_from_pygame(pygame.K_TAB) == 9
        assert vk_from_pygame(pygame.K_RETURN) == 13
        assert vk_from_pygame(pygame.K_ESCAPE) == 27
        assert vk_from_pygame(pygame.K_SPACE) == 32
        assert [vk_from_pygame(k) for k in
                (pygame.K_LEFT, pygame.K_UP, pygame.K_RIGHT, pygame.K_DOWN)] \
            == [37, 38, 39, 40]
        assert vk_from_pygame(pygame.K_F5) == 0x74
        assert vk_from_pygame(pygame.K_BACKSPACE) == 8
        assert vk_from_pygame(pygame.K_DELETE) == 46
        assert vk_from_pygame(pygame.K_PERIOD) == 0xBE
        assert vk_from_pygame(pygame.K_z) == 0x5A
        assert vk_from_pygame(pygame.K_9) == 0x39

    def test_modifier_key_suppresses_its_own_bit(self):
        """A held modifier adds its bit unless the key IS that modifier
        (GuiEvent::getFullModifierKey, GuiEvent.cpp:4-28)."""
        assert full_modifier_key(0x41, pygame.KMOD_LCTRL) == 0x241
        assert full_modifier_key(0xA0, pygame.KMOD_LSHIFT) == 0xA0
        assert full_modifier_key(0xA0, pygame.KMOD_LSHIFT | pygame.KMOD_LALT) \
            == 0x4A0
        assert torque_modifier(pygame.KMOD_LSHIFT | pygame.KMOD_RCTRL) == 0x09


# =============================================================================
# 3. Script mouse events
# =============================================================================

class TestMouseScriptEvents:
    def setup_method(self):
        self.rt2 = ClientGS2()
        self.gui = self.rt2.gui
        self.btn = self.gui.create_control("GuiButtonCtrl", "MouseBtn")
        self.btn.x, self.btn.y = 10.0, 10.0
        self.btn.width, self.btn.height = 80.0, 20.0
        self.gui.addcontrol(self.btn)
        self.now = [1000]

    def _patch_clock(self, monkeypatch):
        monkeypatch.setattr(manager_module, "_ticks", lambda: self.now[0])

    def test_uniform_five_arg_signature_in_canvas_pixels(self, monkeypatch):
        """(modifier, mousex, mousey, clickcount, deviceid) -- GLOBAL canvas
        pixels, deviceid 0 (GuiControl.cpp:2079-2082, asm-verified)."""
        self._patch_clock(monkeypatch)
        got = {}
        for name in ("onmousedown", "onmouseup", "onmousemove"):
            self.btn.set(name, lambda *a, _n=name: got.setdefault(_n, a))
        self.gui.handle_event(_mousedown((20, 15)))
        self.gui.handle_event(_mouseup((20, 15)))
        assert got["onmousedown"] == (0.0, 20.0, 15.0, 1.0, 0.0)
        assert got["onmouseup"] == (0.0, 20.0, 15.0, 1.0, 0.0)
        self.gui.handle_event(_mousemove((25, 12)))
        assert got["onmousemove"] == (0.0, 25.0, 12.0, 1.0, 0.0)

    def test_click_count_increments_within_500ms_and_resets_after(self, monkeypatch):
        self._patch_clock(monkeypatch)
        counts = []
        self.btn.set("onmousedown", lambda *a: counts.append(a[3]))
        self.gui.handle_event(_mousedown((20, 15)))
        self.gui.handle_event(_mouseup((20, 15)))
        self.now[0] += 400
        self.gui.handle_event(_mousedown((20, 15)))
        self.gui.handle_event(_mouseup((20, 15)))
        self.now[0] += 600                     # window expired
        self.gui.handle_event(_mousedown((20, 15)))
        assert counts == [1.0, 2.0, 1.0]

    def test_drag_goes_to_locked_control_even_outside_it(self, monkeypatch):
        """Mouse lock pins events to the pressed control; moves with the
        button held are onMouseDragged (GuiCanvas.cpp:1091-1096)."""
        self._patch_clock(monkeypatch)
        got = []
        self.btn.set("onmousedragged", lambda *a: got.append(a))
        self.gui.handle_event(_mousedown((20, 15)))
        self.gui.handle_event(_mousemove((300, 200), buttons=(1, 0, 0)))
        assert got == [(0.0, 300.0, 200.0, 1.0, 0.0)]
        self.gui.handle_event(_mouseup((300, 200)))
        # lock released: a later move is plain onmousemove elsewhere
        got.clear()
        self.gui.handle_event(_mousemove((300, 200)))
        assert got == []

    def test_right_mouse_events(self, monkeypatch):
        self._patch_clock(monkeypatch)
        got = []
        self.btn.set("onrightmousedown", lambda *a: got.append(("down", a[3])))
        self.btn.set("onrightmouseup", lambda *a: got.append(("up", a[3])))
        self.gui.handle_event(_mousedown((20, 15), button=3))
        self.gui.handle_event(_mouseup((20, 15), button=3))
        assert got == [("down", 1.0), ("up", 1.0)]

    def test_enter_and_leave_on_hover_change(self, monkeypatch):
        self._patch_clock(monkeypatch)
        got = []
        self.btn.set("onmouseenter", lambda *a: got.append("enter"))
        self.btn.set("onmouseleave", lambda *a: got.append("leave"))
        self.gui.handle_event(_mousemove((20, 15)))
        self.gui.handle_event(_mousemove((25, 15)))     # still inside: no repeat
        self.gui.handle_event(_mousemove((500, 400)))
        assert got == ["enter", "leave"]

    def test_wheel_events(self, monkeypatch):
        self._patch_clock(monkeypatch)
        got = []
        self.btn.set("onmousewheelup", lambda *a: got.append("up"))
        self.btn.set("onmousewheeldown", lambda *a: got.append("down"))
        self.gui.handle_event(_mousemove((20, 15)))
        self.gui.handle_event(pygame.event.Event(pygame.MOUSEWHEEL,
                                                 {"x": 0, "y": 1}))
        self.gui.handle_event(pygame.event.Event(pygame.MOUSEWHEEL,
                                                 {"x": 0, "y": -1}))
        assert got == ["up", "down"]

    def test_mousedown_handler_destroying_control_releases_capture(self, monkeypatch):
        """Destroy-in-handler: the capture state is armed BEFORE the fire,
        so destroy() -> _release_pointers_under clears it and the dead
        control receives no further script events."""
        self._patch_clock(monkeypatch)
        dragged = []
        self.btn.set("onmousedown", lambda *a: self.gui.destroy(self.btn))
        self.btn.set("onmousedragged", lambda *a: dragged.append(a))
        self.gui.handle_event(_mousedown((20, 15)))
        assert self.gui._mouse_lock is None
        self.gui.handle_event(_mousemove((30, 18), buttons=(1, 0, 0)))
        assert dragged == []

    def test_leave_handler_destroying_entered_control_suppresses_enter(self, monkeypatch):
        self._patch_clock(monkeypatch)
        other = self.gui.create_control("GuiButtonCtrl", "OtherBtn")
        other.x, other.y = 200.0, 10.0
        other.width, other.height = 80.0, 20.0
        self.gui.addcontrol(other)
        got = []
        other.set("onmouseenter", lambda *a: got.append("enter"))
        other.set("onmousemove", lambda *a: got.append("move"))
        self.btn.set("onmouseleave", lambda *a: self.gui.destroy(other))
        self.gui.handle_event(_mousemove((20, 15)))     # hover btn
        self.gui.handle_event(_mousemove((205, 15)))    # leave destroys other
        assert got == []
        assert self.gui._script_hover is None

    def test_script_events_fire_in_addition_to_builtin_handling(self, monkeypatch):
        """Scripts can't consume: the built-in click (onAction) still runs
        (GuiCanvas.cpp:494-516 -- script first, then the virtual chain)."""
        self._patch_clock(monkeypatch)
        order = []
        self.btn.set("onmousedown", lambda *a: order.append("script"))
        self.btn.set("onaction", lambda *a: order.append("action"))
        self.gui.handle_event(_mousedown((20, 15)))
        assert order == ["script", "action"]


# =============================================================================
# 4. GuiTextListCtrl onDblClick
# =============================================================================

class TestTextListDblClick:
    def setup_method(self):
        self.rt2 = ClientGS2()
        self.gui = self.rt2.gui
        self.lst = self.gui.create_control("GuiTextListCtrl", "DblList")
        self.lst.x, self.lst.y = 0.0, 0.0
        self.lst.width, self.lst.height = 100.0, 100.0
        self.gui.addcontrol(self.lst)
        self.lst._m_addrow(11, "First")
        self.lst._m_addrow(22, "Second")
        self.events = []
        self.lst.set("onselect", lambda *a: self.events.append(("sel", a)))
        self.lst.set("ondblclick", lambda *a: self.events.append(("dbl", a)))
        self.now = [1000]

    def test_even_click_on_selected_row_fires_ondblclick(self, monkeypatch):
        """Even click count on the already-selected cell activates it:
        onDblClick(id, text, row) (GuiArrayCtrl.cpp:477-508,
        GuiTextListCtrl.cpp:798-809); odd clicks select."""
        monkeypatch.setattr(manager_module, "_ticks", lambda: self.now[0])
        pos = (10, 5)                          # row 0 (ROW_H = 18)
        self.gui.handle_event(_mousedown(pos))
        self.gui.handle_event(_mouseup(pos))
        self.now[0] += 300
        self.gui.handle_event(_mousedown(pos))
        self.gui.handle_event(_mouseup(pos))
        assert self.events == [("sel", (11, "First", 0.0)),
                               ("dbl", (11, "First", 0.0))]
        # a third (odd) click selects again rather than activating
        self.now[0] += 300
        self.gui.handle_event(_mousedown(pos))
        assert self.events[-1] == ("sel", (11, "First", 0.0))

    def test_slow_second_click_only_selects(self, monkeypatch):
        monkeypatch.setattr(manager_module, "_ticks", lambda: self.now[0])
        pos = (10, 5)
        self.gui.handle_event(_mousedown(pos))
        self.now[0] += 800                     # outside the 500ms window
        self.gui.handle_event(_mousedown(pos))
        assert [tag for tag, _ in self.events] == ["sel", "sel"]


# =============================================================================
# 5. onResize / onMove
# =============================================================================

class TestResizeMoveEvents:
    def setup_method(self):
        self.rt2 = ClientGS2()
        self.gui = self.rt2.gui
        self.panel = self.gui.create_control("GuiControl", "SizePanel")
        self.panel.x, self.panel.y = 0.0, 0.0
        self.panel.width, self.panel.height = 200.0, 100.0
        self.gui.addcontrol(self.panel)
        self.events = []
        self.panel.set("onresize", lambda *a: self.events.append(("resize", a)))
        self.panel.set("onmove", lambda *a: self.events.append(("move", a)))

    def test_width_write_fires_onresize_with_new_extent(self):
        self.panel.set("width", 300)
        assert self.events == [("resize", (300.0, 100.0))]

    def test_same_value_write_is_the_setter_early_out(self):
        self.panel.set("width", 200)
        self.panel.set("extent", [200, 100])   # resize's own inequality guard
        assert self.events == []

    def test_position_write_fires_onmove(self):
        self.panel.set("x", 40)
        assert self.events == [("move", (40.0, 0.0))]

    def test_resize_method_fires_both_in_move_then_resize_order(self):
        """onMove at GuiControl.cpp:2609-2612 precedes onResize at
        :2615-2618 inside one resize() call."""
        self.panel._m_resize(10, 20, 250, 120)
        assert self.events == [("move", (10.0, 20.0)),
                               ("resize", (250.0, 120.0))]

    def test_child_cascade_fires_child_onresize(self):
        child = self.gui.create_control("GuiControl", "SizeChild")
        child.width, child.height = 200.0, 30.0
        child.set("horizsizing", "width")
        self.gui.addcontrol(child)
        self.gui.add_to(self.panel, child)
        got = []
        child.set("onresize", lambda *a: got.append(a))
        self.panel.set("width", 260)
        assert got == [(260.0, 30.0)]

    def test_self_resizing_handler_converges_by_fixed_point(self):
        """No re-entrancy flag exists: a handler resizing its own control
        converges because the second nested write assigns an equal value
        and the early-outs stop it (the Serverlist_Window.onResize shape)."""
        self.panel.set("onresize", lambda w, h: self.panel.set("width", 500))
        self.panel.set("width", 300)
        assert self.panel.width == 500.0

    def test_not_awake_control_fires_nothing(self):
        """Construction-time resizes are elided (see resize_control's
        documented synchronous-dispatch divergence)."""
        loose = self.gui.create_control("GuiControl", "UnattachedPanel")
        got = []
        loose.set("onresize", lambda *a: got.append(a))
        loose.set("width", 400)
        assert got == [] and loose.width == 400.0
        self.gui._construction_stack.clear()   # keep later tests clean

    def test_window_minimize_fires_onresize_before_onminimize(self):
        """Window chrome goes through resize() first, then fires its own
        event (GuiWindowCtrl.cpp:149-165)."""
        win = self.gui.create_control("GuiWindowCtrl", "MinWin")
        win.width, win.height = 300.0, 200.0
        self.gui.addcontrol(win)
        order = []
        win.set("onresize", lambda *a: order.append(("resize", a)))
        win.set("onminimize", lambda *a: order.append(("min", a)))
        win.minimize_window()
        assert order == [("resize", (300.0, 22.0)), ("min", ())]

    def test_parentless_unmanaged_maximize_fires_event_without_resizing(self):
        """maximizeWindow with no parent skips the resize but still fires
        onMaximize (GuiWindowCtrl.cpp:176-183). A root window's parent is
        the canvas in this model, so this state needs a manager-less
        control."""
        from pyreborn.game.gs2_gui import GuiWindowCtrl
        win = GuiWindowCtrl("Loose")
        win.width, win.height = 300.0, 200.0
        win._awake = True
        got = []
        win.set("onmaximize", lambda *a: got.append(a))
        win.maximize_window()
        assert got == [()]
        assert (win.width, win.height) == (300.0, 200.0)


# =============================================================================
# 6. onWake / onShow / onHide
# =============================================================================

class TestLifecycleEvents:
    def setup_method(self):
        self.rt2 = ClientGS2()
        self.gui = self.rt2.gui
        self.events = []

    def _tag(self, ctrl, *names):
        for name in names:
            ctrl.set(name, lambda *a, _n=name, _c=ctrl.ctrl_name:
                     self.events.append(f"{_c}.{_n}"))

    def test_addcontrol_wakes_children_before_self_then_shows_top_down(self):
        """awaken() is post-order (GuiControl.cpp:1815-1825); the attach
        root's onWake tail then fires onShow top-down (:1966-1967)."""
        parent = self.gui.create_control("GuiControl", "WakeParent")
        child = self.gui.create_control("GuiControl", "WakeChild")
        self._tag(parent, "onwake", "onshow")
        self._tag(child, "onwake", "onshow")
        self.gui.addcontrol(child)             # innermost-first (nested new)
        self.gui.addcontrol(parent)
        assert self.events == ["WakeChild.onwake", "WakeParent.onwake",
                               "WakeParent.onshow", "WakeChild.onshow"]

    def test_visible_true_does_not_fire_onwake(self):
        ctrl = self.gui.create_control("GuiControl", "NoWake")
        self.gui.addcontrol(ctrl)
        self._tag(ctrl, "onwake")
        ctrl.set("visible", False)
        self.events.clear()
        ctrl.set("visible", True)
        assert "NoWake.onwake" not in self.events

    def test_onshow_onhide_only_on_effective_visibility_change(self):
        """Toggling a control inside a hidden tree fires nothing; the
        visible flag is already updated when the handler runs
        (GuiControl.cpp:1288-1332)."""
        parent = self.gui.create_control("GuiControl", "VisParent")
        child = self.gui.create_control("GuiControl", "VisChild")
        self.gui.addcontrol(child)
        self.gui.addcontrol(parent)
        seen_flags = []
        child.set("onhide", lambda: seen_flags.append(child.visible))
        self._tag(parent, "onhide", "onshow")
        parent.set("visible", False)           # parent hides: child notified
        assert seen_flags == [True]            # child's OWN flag untouched
        self.events.clear()
        child.set("visible", False)            # inside a hidden tree: nothing
        child.set("visible", True)
        assert self.events == []
        parent.set("visible", True)            # top-down show pass
        assert self.events == ["VisParent.onshow"]

    def test_hidegui_and_showgui_route_the_events(self):
        win = self.gui.create_control("GuiWindowCtrl", "EventWin")
        self.gui.addcontrol(win)
        self._tag(win, "onshow", "onhide")
        self.rt2.host.call_builtin(None, "hidegui", [win])
        self.rt2.host.call_builtin(None, "showgui", [win])
        assert self.events == ["EventWin.onhide", "EventWin.onshow"]

    def test_window_close_fires_onhide_not_onsleep(self):
        """closeWindow with closequery unset is setVisible(false)
        (GuiWindowCtrl.cpp:144-146) -> onHide; script onSleep never fires
        from close/hide/destroy (its only emitters are the canvas content
        ops, GuiCanvas.cpp:1217-1226/:1472-1483)."""
        win = self.gui.create_control("GuiWindowCtrl", "CloseWin")
        self.gui.addcontrol(win)
        self._tag(win, "onhide", "onsleep")
        win.close_window()
        assert self.events == ["CloseWin.onhide"]

    def test_destroy_fires_onhide_bottom_up_and_never_onsleep(self):
        """Teardown sleep recurses children first, in reverse order
        (GuiControl.cpp:1828-1847), firing onHide per visible control."""
        parent = self.gui.create_control("GuiControl", "DoomParent")
        child = self.gui.create_control("GuiControl", "DoomChild")
        self.gui.addcontrol(child)
        self.gui.addcontrol(parent)
        self._tag(parent, "onhide", "onsleep")
        self._tag(child, "onhide", "onsleep")
        self.gui.destroy(parent)
        assert self.events == ["DoomChild.onhide", "DoomParent.onhide"]

    def test_hide_then_destroy_fires_onhide_once(self):
        win = self.gui.create_control("GuiWindowCtrl", "OnceWin")
        self.gui.addcontrol(win)
        self._tag(win, "onhide")
        self.gui.hide(win)
        self.gui.destroy(win)
        assert self.events == ["OnceWin.onhide"]

    def test_transient_root_show_divergence_is_pinned(self):
        """[PINNED DIVERGENCE] `HiddenParent.addcontrol(new ...)`: the
        nested new's auto-emitted bare addcontrol transiently ROOTS the
        child, firing onWake+onShow before add_to moves it under the hidden
        parent -- the reference attaches nothing until explicit placement
        and fires nothing until real effective visibility (so LTTP's
        LoadLevelWindow.onShow-constructs-controls pattern runs one build
        early here). Goes red if the transient awaken is ever deferred;
        re-judge against the Login fingerprint then (see the addcontrol
        comment in manager.py)."""
        parent = self.gui.create_control("GuiControl", "HiddenParent")
        self.gui.addcontrol(parent)
        parent.set("visible", False)
        child = self.gui.create_control("GuiControl", "MovedChild")
        self._tag(child, "onshow", "onhide")
        self.gui.addcontrol(child)          # transient root: early onShow
        self.gui.add_to(parent, child)      # now inside the hidden parent
        assert self.events == ["MovedChild.onshow"]
        self.events.clear()
        parent.set("visible", True)
        assert self.events == ["MovedChild.onshow"]   # second show, no hide

    def test_isfirstresponder_answers_from_the_first_responder_slot(self):
        """A focused BUTTON must report isFirstResponder() == 1 -- the
        answer keys on the same slot onBecome/onLoseFirstResponder fire
        from, not on the text-edit typing focus."""
        btn = self.gui.create_control("GuiButtonCtrl", "FRBtn")
        self.gui.addcontrol(btn)
        assert btn._m_isfirstresponder() == 0.0
        self.gui.focus(btn)
        assert btn._m_isfirstresponder() == 1.0
        assert self.gui._focus is None      # typing focus untouched

    def test_add_to_awake_parent_wakes_the_child(self):
        parent = self.gui.create_control("GuiControl", "LiveParent")
        self.gui.addcontrol(parent)
        child = self.gui.create_control("GuiControl", "LateChild")
        self._tag(child, "onwake", "onshow")
        self.gui.addcontrol(child)             # roots it: wakes once
        self.events.clear()
        late = self.gui.create_control("GuiControl", "LateChild2")
        self._tag(late, "onwake", "onshow")
        self.gui.addcontrol(late)
        self.events.clear()
        # already-awake reparent fires nothing new
        self.gui.add_to(parent, late)
        assert self.events == []


# =============================================================================
# 6b. Keyboard-capture handback (the Login Tab-toggle chain)
# =============================================================================

class TestKeyboardHandback:
    """Login's chat-bar toggle (weapon-Rescripted_Serverlist.txt:2649-2700):
    Tab on the canvas shows ChatBar + ChatBar.makeFirstResponder(true); Tab
    on ChatBar sets ChatBar.visible = false + GraalControl.
    makeFirstResponder(true). Both halves used to trap the keyboard: the
    engine-object makeFirstResponder fell into the inert catch-all (FR never
    returned to the canvas) and the visible=false script path released
    nothing (the invisible edit kept _focus, blocking held-key movement)."""

    def setup_method(self):
        self.rt2 = ClientGS2()
        self.gui = self.rt2.gui
        self.host = self.rt2.host
        self.chatbar = self.gui.create_control("GuiTextEditCtrl", "ChatBar")
        self.gui.addcontrol(self.chatbar)

    def test_visible_false_releases_first_responder_and_focus(self):
        lost = []
        self.chatbar.set("onlosefirstresponder", lambda: lost.append(True))
        self.gui.focus(self.chatbar)
        assert self.gui.keyboard_captured is True
        self.chatbar.set("visible", False)     # the script path, NOT hidegui
        assert self.gui.keyboard_captured is False
        assert self.gui._first_responder is None and self.gui._focus is None
        assert lost == [True]

    def test_engine_object_makefirstresponder_hands_fr_back_to_canvas(self):
        lost = []
        self.chatbar.set("onlosefirstresponder", lambda: lost.append(True))
        self.gui.focus(self.chatbar)
        graalcontrol = self.host.get_object("graalcontrol")
        self.host.call_builtin(None, "makefirstresponder", [1.0],
                               obj=graalcontrol)
        assert self.gui._first_responder is None and self.gui._focus is None
        assert lost == [True]

    def test_tab_toggle_round_trip(self):
        """Open (canvas Tab), Tab-close (visible=false + GraalControl
        handback), verify capture released, then Tab reaches the canvas
        handler again (reopen)."""
        opened = []
        vm = _FakeVM({"graalcontrol.onkeydown": lambda *a: opened.append(a)})
        self.rt2.vms["weapon"]["w"] = vm
        # boot state: an edit holds FR (Serverlist_ServerDirectConnect
        # pattern) -- the canvas fallback must NOT engage
        self.gui.focus(self.chatbar)
        self.gui.handle_event(_keydown(pygame.K_TAB, "\t"))
        assert opened == []
        # ChatBar.onKeyDown Tab-close: hideChatBar()
        self.chatbar.set("visible", False)
        graalcontrol = self.host.get_object("graalcontrol")
        self.host.call_builtin(None, "makefirstresponder", [1.0],
                               obj=graalcontrol)
        assert self.gui.keyboard_captured is False
        assert self.gui._first_responder is None
        # Tab now reaches GraalControl.onKeyDown (the reopen path)
        self.gui.handle_event(_keydown(pygame.K_TAB, "\t"))
        assert opened == [(9.0, "\t", 1.0)]


# =============================================================================
# 6c. Named `new` reuses the live object
# =============================================================================

class TestNamedReuse:
    def setup_method(self):
        self.rt2 = ClientGS2()
        self.gui = self.rt2.gui
        self.host = self.rt2.host

    def test_named_new_reuses_identity_members_and_catchers(self):
        """TScriptMachine::createObject (TScriptMachine.cpp:1135-1157):
        `new <Class>("Name")` with a live same-named engine object returns
        THAT object -- no reset; members, children and catchevent
        registrations survive. Login's onServerLogin re-runs
        initGraalControlSize() and used to mint a ghost ChatBar root."""
        first = self.gui.create_control("GuiTextEditCtrl", "ChatBar")
        self.gui.addcontrol(first)
        first.set("width", 500)
        got = []
        vm = _FakeVM({"onCaught": lambda *a: got.append(a)})
        self.host.call_builtin(vm, "catchevent",
                               [first, "onAction", "onCaught"])
        again = self.gui.create_control("GuiTextEditCtrl", "ChatBar")
        assert again is first
        self.gui.addcontrol(again)
        assert self.gui.roots.count(first) == 1        # no ghost root
        assert again.width == 500.0                    # no property reset
        again.fire_event("onaction")
        assert got == [(first,)]                       # catcher survived

    def test_named_new_inside_construction_reparents_the_reused_control(self):
        child = self.gui.create_control("GuiControl", "ReusedKid")
        self.gui.addcontrol(child)
        assert child in self.gui.roots
        parent = self.gui.create_control("GuiControl", "NewParent")
        reused = self.gui.create_control("GuiControl", "ReusedKid")
        assert reused is child
        self.gui.addcontrol(reused)
        self.gui.addcontrol(parent)
        assert child.parent is parent
        assert child not in self.gui.roots

    def test_fresh_name_still_constructs(self):
        a = self.gui.create_control("GuiButtonCtrl", "OnlyOnce")
        self.gui.addcontrol(a)
        b = self.gui.create_control("GuiButtonCtrl", "SomethingElse")
        self.gui.addcontrol(b)
        assert a is not b and len(self.gui.roots) == 2


# =============================================================================
# 6d. Start-button click fires script onAction alongside the menu toggle
# =============================================================================

def test_start_button_toggle_also_fires_script_onaction():
    """Serverlist_TaskButton_Start.onAction (weapon-Rescripted_Serverlist
    .txt:2884-2888) must fire even though the engine's start-menu toggle
    handles the click -- everything fires, engine handling can't consume
    events away from scripts."""
    rt2 = ClientGS2()
    gui = rt2.gui
    menu = gui.create_control("GuiStartMenuCtrl", "StartMenu")
    gui.addcontrol(menu)
    btn = gui.create_control("GuiButtonCtrl", "StartBtn")
    btn.x, btn.y, btn.width, btn.height = 0.0, 580.0, 80.0, 20.0
    btn.set("stylesection", "Taskbar.StartButton")
    gui.addcontrol(btn)
    fired = []
    btn.set("onaction", lambda *a: fired.append(True))
    assert menu.visible is False
    gui.handle_event(_mousedown((10, 590)))
    assert menu.visible is True                        # built-in toggle ran
    assert fired == [True]                             # script event too
    gui.handle_event(_mousedown((10, 590)))
    assert menu.visible is False
    assert fired == [True, True]


# =============================================================================
# 7. GuiMLTextCtrl onURL
# =============================================================================

class TestOnURL:
    def setup_method(self):
        self.rt2 = ClientGS2()
        self.gui = self.rt2.gui
        self.ml = self.gui.create_control("GuiMLTextCtrl", "UrlText")
        self.ml.x, self.ml.y = 10.0, 10.0
        self.ml.width, self.ml.height = 300.0, 60.0
        self.ml.set("text", '<a href="emailcheck">click here</a> plain tail')
        self.gui.addcontrol(self.ml)
        self.urls = []
        self.ml.set("onurl", lambda *a: self.urls.append(a))
        surf = pygame.Surface((400, 200))
        self.gui.render(surf, _FakeFonts(), sprite_mgr=None)
        assert self.ml._link_rects, "draw must have recorded link rects"

    def test_span_model_retains_href(self):
        from pyreborn.game.gs2_gui.mltext import parse_mltext
        paragraphs = parse_mltext('<a href="emailcheck">click here</a> x')
        segs = [s for _a, run in paragraphs for s in run]
        assert [s.href for s in segs if s.link] == ["emailcheck"]
        assert all(s.href is None for s in segs if not s.link)

    def test_press_and_release_on_link_fires_onurl(self):
        """Mouse-down arms the pressed link, release on the SAME link fires
        onURL(url) with the bare href passed through unresolved
        (GuiMLTextCtrl.cpp:939-957/:1157-1181, THTMLPage.cpp:278-287)."""
        pos = self.ml._link_rects[0][0].center
        self.gui.handle_event(_mousedown(pos))
        self.gui.handle_event(_mouseup(pos))
        assert self.urls == [("emailcheck",)]

    def test_release_off_the_link_fires_nothing(self):
        pos = self.ml._link_rects[0][0].center
        self.gui.handle_event(_mousedown(pos))
        self.gui.handle_event(_mouseup((self.ml._link_rects[0][0].right + 80,
                                        pos[1])))
        assert self.urls == []

    def test_press_off_link_release_on_link_fires_nothing(self):
        pos = self.ml._link_rects[0][0].center
        self.gui.handle_event(_mousedown((300, 15)))
        self.gui.handle_event(_mouseup(pos))
        assert self.urls == []
