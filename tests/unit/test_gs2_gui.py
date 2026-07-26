"""GS2 GUI-controls layer (game/gs2_gui.py + gs2_client.py's showgui wiring).

Two layers of coverage:

1. Direct-host-call tests build the control tree the same way the real GS2
   compiler's bytecode drives it (see game/gs2_gui.py's module docstring for
   the traced opcode sequence) but call GS2ClientHost.create_object() /
   .call_builtin() directly instead of hand-assembling that bytecode -- this
   repo's hand-assembler helper (see test_gs2_client.py) only covers simple
   op sequences, not the ~20-instruction nested with-block/lambda dance a
   real `new GuiWindowCtrl(...) { new GuiButtonCtrl(...) {...} }` compiles
   to. These are the primary, always-run tests.
2. One end-to-end test compiles an actual .gs2 script with the real
   GServer-v2 compiler (gs2test, shared with reborn-protocol's test suite)
   and drives it through ClientGS2.load_bytecode() -- proving the traced
   compiler behavior this module's design relies on. Skipped if the gs2test
   binary isn't built (same skip convention as
   reborn-protocol/tests/test_gs2_compiler.py).
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pygame
import pytest

from reborn_protocol.gs2 import GS2VM
from pyreborn.gs2_client import ClientGS2
from pyreborn.game.gs2_gui import (
    GS2GuiManager, GuiBitmapCtrl, GuiButtonCtrl, GuiCheckBoxCtrl,
    GuiPopUpEditCtrl, GuiRadioCtrl, GuiShowImgCtrl, GuiTextCtrl,
    GuiTextEditCtrl, GuiWindowCtrl,
)

pygame.init()
pygame.font.init()


class _FakeFonts:
    """Minimal stand-in for game/assets.py's FontManager: role -> Font."""

    def get(self, role):
        return pygame.font.Font(None, 16)


# =============================================================================
# Direct-host-call tests: exercise GS2ClientHost.create_object/call_builtin
# exactly as the VM's OP_NEW_OBJECT/OP_CALL would invoke them.
# =============================================================================

def _click_events(pos):
    return (pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": pos, "button": 1}),
            pygame.event.Event(pygame.MOUSEBUTTONUP, {"pos": pos, "button": 1}))


def _mousedown(pos):
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": pos, "button": 1})


def _mouseup(pos):
    return pygame.event.Event(pygame.MOUSEBUTTONUP, {"pos": pos, "button": 1})


def _mousemove(pos):
    return pygame.event.Event(pygame.MOUSEMOTION, {"pos": pos, "rel": (0, 0), "buttons": (0, 0, 0)})


class _FakeSpriteMgr:
    """Minimal stand-in for SpriteManager: name -> Surface (or None)."""

    def __init__(self, sheets=None):
        self.sheets = sheets or {}

    def load_sheet(self, name):
        return self.sheets.get(name)


class TestDirectHostConstruction:
    """Builds trees the way GS2CompilerVisitor's StatementNewNode bytecode
    does: create_object() -> field sets -> addcontrol() -- see gs2_gui.py's
    module docstring point 1."""

    def setup_method(self):
        self.rt2 = ClientGS2()
        assert self.rt2.gui is not None, "pygame is installed; gui manager must exist"
        self.host = self.rt2.host

    def test_gui_classname_routes_to_control(self):
        obj = self.host.create_object("GuiButtonCtrl", "mybutton")
        assert isinstance(obj, GuiButtonCtrl)
        assert obj.ctrl_name == "mybutton"

    def test_non_gui_classname_unaffected(self):
        from reborn_protocol.gs2 import GS2Object
        obj = self.host.create_object("TStaticVar", None)
        assert type(obj) is GS2Object
        assert not isinstance(obj, GuiButtonCtrl)

    def test_addcontrol_attaches_to_root(self):
        ctrl = self.host.create_object("GuiButtonCtrl", "btn1")
        ctrl.set("text", "Click me")
        self.host.call_builtin(None, "addcontrol", [ctrl])
        assert self.rt2.gui.roots == [ctrl]
        assert ctrl.parent is None

    def test_nested_new_infers_parent_from_call_order(self):
        """window -> button, text (children created+addcontrol'd before the
        window's own addcontrol -- innermost-first, per the traced compiler
        order)."""
        win = self.host.create_object("GuiWindowCtrl", None)
        win.set("text", "Shop")
        btn = self.host.create_object("GuiButtonCtrl", None)
        btn.set("text", "Buy")
        self.host.call_builtin(None, "addcontrol", [btn])   # child finishes first
        lbl = self.host.create_object("GuiTextCtrl", None)
        lbl.set("text", "Welcome")
        self.host.call_builtin(None, "addcontrol", [lbl])
        self.host.call_builtin(None, "addcontrol", [win])   # parent finishes last

        assert self.rt2.gui.roots == [win]
        assert win.children == [btn, lbl]
        assert btn.parent is win
        assert lbl.parent is win

    def test_sibling_new_statements_dont_interfere(self):
        a = self.host.create_object("GuiButtonCtrl", None)
        self.host.call_builtin(None, "addcontrol", [a])
        b = self.host.create_object("GuiButtonCtrl", None)
        self.host.call_builtin(None, "addcontrol", [b])
        assert self.rt2.gui.roots == [a, b]
        assert a.children == [] and b.children == []

    def test_manual_expression_form_addcontrol(self):
        """temp.ctrl = new GuiButtonCtrl("x"); addcontrol(temp.ctrl);"""
        ctrl = self.host.create_object("GuiButtonCtrl", "manual")
        self.host.call_builtin(None, "addcontrol", [ctrl])
        assert self.rt2.gui.roots == [ctrl]

    def test_destroy_removes_from_tree_and_registry(self):
        ctrl = self.host.create_object("GuiButtonCtrl", "doomed")
        self.host.call_builtin(None, "addcontrol", [ctrl])
        self.host.call_builtin(None, "destroy", [ctrl])
        assert ctrl not in self.rt2.gui.roots
        assert self.rt2.gui._resolve("doomed") is None

    def test_destroy_object_method_form(self):
        ctrl = self.host.create_object("GuiButtonCtrl", "doomed2")
        self.host.call_builtin(None, "addcontrol", [ctrl])
        # ctrl.destroy() -- obj is not None
        self.host.call_builtin(None, "destroy", [], obj=ctrl)
        assert ctrl not in self.rt2.gui.roots

    def test_addcontrol_on_non_control_is_a_noop(self):
        self.host.call_builtin(None, "addcontrol", ["not a control"])
        assert self.rt2.gui.roots == []


# =============================================================================
# Visibility (showgui/hidegui)
# =============================================================================

class TestVisibility:
    def setup_method(self):
        self.rt2 = ClientGS2()
        self.host = self.rt2.host
        self.win = self.host.create_object("GuiWindowCtrl", "mainwindow")
        self.host.call_builtin(None, "addcontrol", [self.win])

    def test_hidden_by_default_is_false_until_hidden(self):
        assert self.win.visible is True

    def test_hidegui_by_object(self):
        self.host.call_builtin(None, "hidegui", [self.win])
        assert self.win.visible is False

    def test_showgui_by_name_string(self):
        self.host.call_builtin(None, "hidegui", [self.win])
        self.host.call_builtin(None, "showgui", ["mainwindow"])
        assert self.win.visible is True

    def test_hidegui_by_name_string(self):
        self.host.call_builtin(None, "hidegui", ["mainwindow"])
        assert self.win.visible is False

    def test_showgui_unknown_name_does_not_raise(self):
        self.host.call_builtin(None, "showgui", ["no-such-window"])  # just must not raise


# =============================================================================
# Hit-testing / event dispatch
# =============================================================================

class TestEventDispatch:
    def setup_method(self):
        self.rt2 = ClientGS2()
        self.gui = self.rt2.gui
        self.clicked = []

        self.btn = GuiButtonCtrl("btn")
        self.btn.x, self.btn.y, self.btn.width, self.btn.height = 10, 10, 80, 20
        self.btn.set("onaction", lambda: self.clicked.append("btn"))
        self.gui.addcontrol(self.btn)

    def test_mousedown_on_button_fires_onaction(self):
        down, _up = _click_events((20, 15))
        consumed = self.gui.handle_event(down)
        assert consumed is True
        assert self.clicked == ["btn"]

    def test_mousedown_off_button_does_not_fire(self):
        down, _up = _click_events((500, 500))
        consumed = self.gui.handle_event(down)
        assert consumed is False
        assert self.clicked == []

    def test_checkbox_toggles_and_fires(self):
        cb = GuiCheckBoxCtrl("cb")
        cb.x, cb.y, cb.width, cb.height = 200, 10, 16, 16
        fired = []
        cb.set("onaction", lambda: fired.append(cb.checked))
        self.gui.addcontrol(cb)

        down, _up = _click_events((205, 15))
        self.gui.handle_event(down)
        assert cb.checked is True
        assert fired == [True]


class TestWindowTitleButtons:
    def setup_method(self):
        self.rt2 = ClientGS2()
        self.gui = self.rt2.gui
        self.window = GuiWindowCtrl("window")
        self.window.x, self.window.y = 20, 30
        self.window.width, self.window.height = 350, 160
        self.gui.addcontrol(self.window)

    def test_button_geometry(self):
        close, minimize, maximize = self.window.button_rects()
        assert close == pygame.Rect(332, 3, 16, 16)
        assert maximize == pygame.Rect(314, 3, 16, 16)
        assert minimize == pygame.Rect(296, 3, 16, 16)

        self.window.set("canmaximize", False)
        close, minimize, maximize = self.window.button_rects()
        assert close == pygame.Rect(332, 3, 16, 16)
        assert minimize == pygame.Rect(314, 3, 16, 16)
        assert maximize == pygame.Rect(0, 0, 0, 0)

    def test_close_query_dispatches_and_stays_visible(self):
        calls = []
        self.window.set("closequery", True)
        self.window.set("onclosequery", lambda: calls.append("close"))
        pos = (self.window.x + 336, self.window.y + 7)
        self.gui.handle_event(_mousedown(pos))
        self.gui.handle_event(_mouseup(pos))
        assert calls == ["close"]
        assert self.window.visible is True

    @pytest.mark.parametrize("destroy_on_hide", [False, True])
    def test_close_hides_and_optionally_destroys(self, destroy_on_hide):
        self.window.set("destroyonhide", destroy_on_hide)
        pos = (self.window.x + 336, self.window.y + 7)
        self.gui.handle_event(_mousedown(pos))
        self.gui.handle_event(_mouseup(pos))
        assert self.window.visible is False
        assert (self.window not in self.gui.roots) is destroy_on_hide

    def test_release_outside_close_does_nothing(self):
        pos = (self.window.x + 336, self.window.y + 7)
        self.gui.handle_event(_mousedown(pos))
        self.gui.handle_event(_mouseup((self.window.x + 200, self.window.y + 10)))
        assert self.window.visible is True

    def test_close_press_does_not_start_drag(self):
        pos = (self.window.x + 336, self.window.y + 7)
        assert self.gui.handle_event(_mousedown(pos)) is True
        assert self.window.close_button_pressed is True
        assert self.gui._drag is None


class TestZOrder:
    """Two overlapping windows: the topmost (last shown / brought-to-front)
    must receive the click, not the one drawn under it."""

    def setup_method(self):
        self.rt2 = ClientGS2()
        self.gui = self.rt2.gui

        self.back = GuiWindowCtrl("back")
        self.back.x, self.back.y, self.back.width, self.back.height = 0, 0, 200, 150
        self.gui.addcontrol(self.back)

        self.front = GuiWindowCtrl("front")
        self.front.x, self.front.y, self.front.width, self.front.height = 20, 20, 200, 150
        self.gui.addcontrol(self.front)

    def test_topmost_window_hit_in_overlap_region(self):
        # (50, 50) is inside both windows' rects; "front" was added later
        # (topmost by list order -- see GS2GuiManager.bring_to_front).
        hit = self.gui.hit_test((50, 50))
        assert hit is self.front

    def test_click_brings_window_to_front(self):
        # click "back" in its non-overlapping region -> it becomes topmost
        down, _up = _click_events((5, 5))
        self.gui.handle_event(down)
        assert self.gui.roots[-1] is self.back
        hit = self.gui.hit_test((50, 50))     # now inside the overlap again
        assert hit is self.back


# =============================================================================
# Text entry
# =============================================================================

class TestTextEdit:
    def setup_method(self):
        self.rt2 = ClientGS2()
        self.gui = self.rt2.gui
        self.edit = GuiTextEditCtrl("field")
        self.edit.x, self.edit.y, self.edit.width, self.edit.height = 10, 10, 120, 20
        self.gui.addcontrol(self.edit)

    def test_click_focuses(self):
        down, _up = _click_events((15, 15))
        self.gui.handle_event(down)
        assert self.edit.focused is True

    def test_typed_characters_append_to_text(self):
        down, _up = _click_events((15, 15))
        self.gui.handle_event(down)
        for ch in "hi":
            evt = pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_a, "unicode": ch, "mod": 0})
            self.gui.handle_event(evt)
        assert self.edit.text == "hi"

    def test_backspace(self):
        self.edit.text = "abc"
        down, _up = _click_events((15, 15))
        self.gui.handle_event(down)
        evt = pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_BACKSPACE, "unicode": "", "mod": 0})
        self.gui.handle_event(evt)
        assert self.edit.text == "ab"

    def test_enter_fires_onaction(self):
        fired = []
        # text-field onAction receives (text) per the reference convention
        self.edit.set("onaction", lambda *_text: fired.append(True))
        down, _up = _click_events((15, 15))
        self.gui.handle_event(down)
        evt = pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_RETURN, "unicode": "\r", "mod": 0})
        self.gui.handle_event(evt)
        assert fired == [True]

    def test_escape_hides_topmost_window(self):
        win = GuiWindowCtrl("w")
        self.gui.addcontrol(win)
        assert win.visible is True
        evt = pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_ESCAPE, "unicode": "", "mod": 0})
        consumed = self.gui.handle_event(evt)
        assert consumed is True
        assert win.visible is False


# =============================================================================
# Render smoke: draw() must not raise on a populated tree, no fonts/sprites.
# =============================================================================

def test_render_smoke_does_not_raise():
    rt2 = ClientGS2()
    gui = rt2.gui
    win = GuiWindowCtrl("w")
    win.set("text", "Shop")
    btn = GuiButtonCtrl(None)
    btn.set("text", "Buy")
    gui.addcontrol(btn)
    gui.addcontrol(win)  # not actually nested here, both are roots -- fine for a smoke test
    surf = pygame.Surface((320, 240))
    gui.render(surf, _FakeFonts(), sprite_mgr=None)
    gui.render(surf, fonts=None, sprite_mgr=None)  # fonts=None path must also survive


def test_headless_without_pygame_gui_is_none(monkeypatch):
    """gs2_client.py must degrade gracefully (gui=None, no crash) when the
    GS2GuiManager import fails -- the game_tester headless path."""
    import pyreborn.gs2_client as gs2_client_mod
    monkeypatch.setattr(gs2_client_mod, "GS2GuiManager", None)
    rt2 = ClientGS2()
    assert rt2.gui is None
    # builtins must no-op, not raise, with gui unavailable
    obj = rt2.host.create_object("GuiButtonCtrl", "x")
    assert obj.name == "GuiButtonCtrl"
    rt2.host.call_builtin(None, "addcontrol", [obj])
    rt2.host.call_builtin(None, "showgui", [obj])


# =============================================================================
# End-to-end: real GS2 compiler -> ClientGS2.load_bytecode()
# =============================================================================

def _find_gs2test():
    candidates = [
        os.environ.get("GS2TEST_BIN"),
        str(Path(__file__).parent / "../../../reborn-protocol/tests/tools/gs2test"),
        shutil.which("gs2test"),
    ]
    for c in candidates:
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return str(c)
    return None


GS2TEST = _find_gs2test()

_GUI_SCRIPT = """
function onCreated() {
  new GuiWindowCtrl(temp.win) {
    x = 5;
    y = 5;
    width = 200;
    height = 150;
    text = "Shop";

    new GuiButtonCtrl(temp.btn1) {
      x = 10;
      y = 10;
      text = "Buy";
      onAction = function() {
        this.clicked = 1;
      };
    }

    new GuiTextCtrl(temp.lbl) {
      x = 10;
      y = 40;
      text = "Welcome";
    }
  }
  showgui(temp.win);
}
"""


@pytest.mark.skipif(GS2TEST is None, reason="gs2test compiler binary not built "
                    "(see reborn-protocol/tests/tools/build_gs2test.sh)")
def test_real_compiler_end_to_end():
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "gui.gs2"
        out = Path(tmp) / "gui.gs2bc"
        src.write_text(_GUI_SCRIPT)
        result = subprocess.run([GS2TEST, str(src), "-o", str(out)],
                                capture_output=True, text=True, timeout=30)
        assert out.exists(), f"gs2test failed to produce bytecode: {result.stdout} {result.stderr}"
        blob = out.read_bytes()

    rt2 = ClientGS2()
    vm = rt2.load_bytecode("npc", 1, blob)
    assert vm is not None

    assert len(rt2.gui.roots) == 1
    win = rt2.gui.roots[0]
    assert isinstance(win, GuiWindowCtrl)
    assert win.text == "Shop"
    assert win.visible is True                       # showgui() ran
    assert {c.text for c in win.children} == {"Buy", "Welcome"}

    btn = next(c for c in win.children if c.text == "Buy")
    assert isinstance(btn, GuiButtonCtrl)
    assert btn.fire_action() is True
    assert vm.this.get("clicked") == 1.0


class TestReviewRegressions:
    """Regressions from the adversarial review of the initial GUI layer."""

    def setup_method(self):
        self.rt2 = ClientGS2()
        self.gui = self.rt2.gui
        self.host = self.rt2.host

    def _window_with_focused_edit(self):
        win = self.host.create_object("GuiWindowCtrl", "dlg")
        win.x, win.y, win.width, win.height = 0, 0, 200, 100
        edit = self.host.create_object("GuiTextEditCtrl", "dlgfield")
        edit.x, edit.y, edit.width, edit.height = 10, 40, 120, 20
        self.host.call_builtin(None, "addcontrol", [edit])
        self.host.call_builtin(None, "addcontrol", [win])
        down, _ = _click_events((15, 45))
        self.gui.handle_event(down)
        assert self.gui.keyboard_captured is True
        return win, edit

    def test_hide_container_releases_descendant_focus(self):
        win, _edit = self._window_with_focused_edit()
        self.gui.hide(win)
        assert self.gui.keyboard_captured is False

    def test_destroy_container_releases_descendant_focus(self):
        win, _edit = self._window_with_focused_edit()
        self.gui.destroy(win)
        assert self.gui.keyboard_captured is False

    def test_hide_unrelated_control_keeps_focus(self):
        _win, edit = self._window_with_focused_edit()
        other = self.host.create_object("GuiWindowCtrl", "other")
        self.host.call_builtin(None, "addcontrol", [other])
        self.gui.hide(other)
        assert self.gui.keyboard_captured is True
        assert edit.focused is True

    def test_aborted_construction_does_not_poison_later_new(self):
        # Simulate a script whose VM aborted mid-`new`: create_object ran,
        # the auto-emitted addcontrol never did.
        self.host.create_object("GuiWindowCtrl", "deadwindow")
        # Boundary (render/handle_event) reaps the leak...
        surf = pygame.Surface((320, 240))
        self.gui.render(surf, _FakeFonts())
        assert self.gui._construction_stack == []
        # ...so an unrelated later `new` lands in roots, not under the corpse.
        btn = self.host.create_object("GuiButtonCtrl", "laterbtn")
        self.host.call_builtin(None, "addcontrol", [btn])
        assert btn in self.gui.roots
        assert btn.parent is None

    def test_addcontrol_pops_by_identity_after_partial_abort(self):
        # Parent's addcontrol fires even though an aborted child above it on
        # the construction stack never saw its own addcontrol.
        win = self.host.create_object("GuiWindowCtrl", "w2")
        self.host.create_object("GuiTextCtrl", "orphanlabel")  # aborted child
        self.host.call_builtin(None, "addcontrol", [win])
        assert self.gui._construction_stack == []
        assert win in self.gui.roots

    def test_mutual_addcontainer_refuses_parent_cycle(self):
        first = self.host.create_object("GuiWindowCtrl", "first")
        second = self.host.create_object("GuiWindowCtrl", "second")
        self.host.call_builtin(None, "addcontrol", [first])
        self.host.call_builtin(None, "addcontrol", [second])
        self.gui.add_to(first, second)
        self.gui.add_to(second, first)
        assert second.parent is first
        assert first.parent is None
        assert first not in second.children
        assert first in self.gui.roots

    def test_corrupt_parent_walks_stop_at_step_bound(self, monkeypatch):
        import pyreborn.game.gs2_gui as gui_module

        monkeypatch.setattr(gui_module, "_MAX_PARENT_DEPTH", 3)
        first = self.host.create_object("GuiTextEditCtrl", "first-edit")
        second = self.host.create_object("GuiTextEditCtrl", "second-edit")
        unrelated = self.host.create_object("GuiWindowCtrl", "unrelated")
        first.parent = second
        second.parent = first
        self.gui._focus = first
        self.gui.destroy(unrelated)
        self.gui.render(pygame.Surface((32, 32)), _FakeFonts())
        assert self.gui._focus is first


# =============================================================================
# Radio-group mutual exclusion
# =============================================================================

class TestRadioGroup:
    """Radios that share an immediate parent container mutually exclude on
    click -- see GS2GuiManager._select_radio."""

    def setup_method(self):
        self.rt2 = ClientGS2()
        self.gui = self.rt2.gui
        self.fired = []

        self.win = GuiWindowCtrl("win")
        self.win.x, self.win.y, self.win.width, self.win.height = 0, 0, 200, 150
        self.gui.addcontrol(self.win)

        self.r1 = self._make_radio("r1", 10, 30)
        self.r2 = self._make_radio("r2", 10, 50)
        self.r3 = self._make_radio("r3", 10, 70)

        # A sibling radio group under a *different* parent must not be
        # affected by clicks in the first group.
        self.other_win = GuiWindowCtrl("otherwin")
        self.other_win.x, self.other_win.y = 300, 300
        self.other_win.width, self.other_win.height = 200, 150
        self.gui.addcontrol(self.other_win)
        self.outside = GuiRadioCtrl("outside")
        self.outside.x, self.outside.y, self.outside.width, self.outside.height = 310, 330, 16, 16
        self.outside.checked = True
        self.other_win.add_child(self.outside)

    def _make_radio(self, name, x, y):
        r = GuiRadioCtrl(name)
        r.x, r.y, r.width, r.height = x, y, 16, 16
        r.set("onaction", lambda n=name: self.fired.append(n))
        self.win.add_child(r)
        return r

    def _click(self, radio):
        self.gui.handle_event(_mousedown((radio.x + 5, radio.y + 5)))
        self.gui.handle_event(_mouseup((radio.x + 5, radio.y + 5)))

    def test_click_checks_radio_and_fires_onaction(self):
        self._click(self.r1)
        assert self.r1.checked is True
        assert self.fired == ["r1"]

    def test_click_unchecks_sibling_radios(self):
        self._click(self.r1)
        self._click(self.r2)
        assert self.r1.checked is False
        assert self.r2.checked is True
        assert self.r3.checked is False
        assert self.fired == ["r1", "r2"]

    def test_reclicking_checked_radio_is_a_noop(self):
        self._click(self.r1)
        self._click(self.r1)
        assert self.r1.checked is True
        # onAction only fires on an actual selection change.
        assert self.fired == ["r1"]

    def test_other_parent_group_unaffected(self):
        self._click(self.r1)
        assert self.outside.checked is True
        assert "outside" not in self.fired


# =============================================================================
# Popup selection control
# =============================================================================

class TestPopUpEdit:
    def setup_method(self):
        self.rt2 = ClientGS2()
        self.gui = self.rt2.gui
        self.popup = GuiPopUpEditCtrl("choices")
        self.popup.x, self.popup.y = 10, 10
        self.popup.width, self.popup.height = 120, 20
        self.gui.addcontrol(self.popup)
        self.popup.add_row(10, "First")
        self.popup.add_row(20, "Second")
        self.selected = []
        self.actions = []
        # reference convention passes (entryid, entrytext, entryindex);
        # GS2 closures that declare fewer params just ignore the extras
        self.popup.set("onselect", lambda row_id, text, *_index:
                       self.selected.append((row_id, text)))
        self.popup.set("onaction", lambda: self.actions.append(self.popup.text))

    def _open(self):
        self.gui.handle_event(_mousedown((15, 15)))
        self.gui.handle_event(_mouseup((15, 15)))
        assert self.popup.popup_open is True

    def _choose(self, index):
        row_y = int(self.popup.y + self.popup.height * (index + 1) + 5)
        self.gui.handle_event(_mousedown((15, row_y)))
        self.gui.handle_event(_mouseup((15, row_y)))

    def test_add_select_and_callbacks_once_per_change(self):
        assert self.popup.get_row_text(20) == "Second"
        self._open()
        self._choose(1)
        assert self.popup.get_selected_row() == 20
        assert self.popup.text == "Second"
        assert self.selected == [(20, "Second")]
        assert self.actions == ["Second"]
        assert self.popup.popup_open is False

    def test_reselecting_same_row_fires_nothing(self):
        self._open()
        self._choose(0)
        self._open()
        self._choose(0)
        assert self.selected == [(10, "First")]
        assert self.actions == ["First"]

    def test_outside_click_closes_and_is_consumed(self):
        under = GuiButtonCtrl("under")
        under.x, under.y, under.width, under.height = 200, 10, 80, 20
        fired = []
        under.set("onaction", lambda: fired.append(True))
        self.gui.addcontrol(under)
        self._open()
        assert self.gui.handle_event(_mousedown((205, 15))) is True
        assert self.popup.popup_open is False
        assert fired == []
        assert self.popup.get_selected_row() == -1.0

    def test_escape_closes_without_hiding_window_or_selecting(self):
        self._open()
        event = pygame.event.Event(
            pygame.KEYDOWN, {"key": pygame.K_ESCAPE, "unicode": "", "mod": 0})
        assert self.gui.handle_event(event) is True
        assert self.popup.popup_open is False
        assert self.popup.get_selected_row() == -1.0

    @pytest.mark.parametrize("operation", ["hide", "destroy"])
    def test_close_releases_pointer_state(self, operation):
        win = GuiWindowCtrl("container")
        win.x, win.y, win.width, win.height = 0, 0, 160, 120
        self.gui.roots.remove(self.popup)
        win.add_child(self.popup)
        self.gui.addcontrol(win)
        self._open()
        self.gui.handle_event(_mousemove((15, 35)))
        assert self.gui._open_popup is self.popup
        assert self.gui._hover is self.popup
        getattr(self.gui, operation)(win)
        assert self.gui._open_popup is None
        assert self.gui._hover is None
        assert self.gui._pressed is None
        assert self.popup.popup_open is False

    def test_script_facing_object_methods(self):
        host = self.rt2.host
        extra = GuiPopUpEditCtrl("extra")
        assert host.call_builtin(None, "addrow", [7, "Seven"], obj=extra) == 0.0
        assert host.call_builtin(None, "add", [8, "Eight"], obj=extra) == 1.0
        assert host.call_builtin(None, "getrowtext", [8], obj=extra) == "Eight"
        assert host.call_builtin(None, "getselectedrow", [], obj=extra) == -1.0
        host.call_builtin(None, "clear", [], obj=extra)
        assert extra.rows == []
        assert extra.text == ""


# =============================================================================
# GuiShowImgCtrl rendering (shares GuiBitmapCtrl's load/scale path)
# =============================================================================

class TestShowImgRendering:
    def setup_method(self):
        self.rt2 = ClientGS2()
        self.gui = self.rt2.gui

    def test_bitmap_and_image_property_aliases(self):
        img = GuiShowImgCtrl("pic")
        img.set("bitmap", "shop.png")
        assert img.get("bitmap") == "shop.png"
        assert img.get("image") == "shop.png"
        img.set("image", "other.png")
        assert img.get("bitmap") == "other.png"

    def test_renders_loaded_sprite_stretched_to_rect(self):
        img = GuiShowImgCtrl("pic")
        img.x, img.y, img.width, img.height = 5, 5, 40, 20
        img.set("bitmap", "shop.png")
        self.gui.addcontrol(img)

        sheet = pygame.Surface((16, 16))
        sheet.fill((10, 20, 30))
        sprite_mgr = _FakeSpriteMgr({"shop.png": sheet})

        surf = pygame.Surface((320, 240))
        self.gui.render(surf, fonts=None, sprite_mgr=sprite_mgr)

        assert img._scaled_surf is not None
        assert img._scaled_surf.get_size() == (40, 20)
        # A pixel inside the control's rect now carries the sheet's color
        # (proves the blit actually landed at the control's rect, not (0,0)).
        assert surf.get_at((10, 10))[:3] == (10, 20, 30)

    def test_missing_bitmap_falls_back_to_placeholder_box_no_raise(self):
        img = GuiShowImgCtrl("pic")
        img.x, img.y, img.width, img.height = 5, 5, 40, 20
        self.gui.addcontrol(img)
        surf = pygame.Surface((320, 240))
        self.gui.render(surf, fonts=None, sprite_mgr=_FakeSpriteMgr())  # must not raise

    def test_shares_bitmapctrl_class(self):
        assert issubclass(GuiShowImgCtrl, GuiBitmapCtrl)


# =============================================================================
# Hover / pressed visual state
# =============================================================================

class TestHoverPressedState:
    def setup_method(self):
        self.rt2 = ClientGS2()
        self.gui = self.rt2.gui
        self.btn = GuiButtonCtrl("btn")
        self.btn.x, self.btn.y, self.btn.width, self.btn.height = 10, 10, 80, 20
        self.gui.addcontrol(self.btn)

    def test_mouse_move_over_button_sets_hovered(self):
        self.gui.handle_event(_mousemove((20, 15)))
        assert self.btn.hovered is True

    def test_mouse_move_away_clears_hovered(self):
        self.gui.handle_event(_mousemove((20, 15)))
        self.gui.handle_event(_mousemove((500, 500)))
        assert self.btn.hovered is False

    def test_mouse_down_sets_pressed_mouse_up_clears_it(self):
        self.gui.handle_event(_mousedown((20, 15)))
        assert self.btn.pressed is True
        self.gui.handle_event(_mouseup((20, 15)))
        assert self.btn.pressed is False

    def test_hide_button_releases_hover_and_pressed(self):
        self.gui.handle_event(_mousemove((20, 15)))
        self.gui.handle_event(_mousedown((20, 15)))
        assert self.btn.hovered is True and self.btn.pressed is True
        self.gui.hide(self.btn)
        assert self.btn.hovered is False
        assert self.btn.pressed is False

    def test_checkbox_hover_tracked_too(self):
        cb = GuiCheckBoxCtrl("cb")
        cb.x, cb.y, cb.width, cb.height = 200, 10, 16, 16
        self.gui.addcontrol(cb)
        self.gui.handle_event(_mousemove((205, 15)))
        assert cb.hovered is True
        assert self.btn.hovered is False   # mutually exclusive, single hover slot

    def test_render_with_hover_and_pressed_does_not_raise(self):
        self.gui.handle_event(_mousemove((20, 15)))
        self.gui.handle_event(_mousedown((20, 15)))
        surf = pygame.Surface((320, 240))
        self.gui.render(surf, _FakeFonts(), sprite_mgr=None)


# =============================================================================
# Profile resolution (styled rendering) -- regression for the 07-24 "flat
# serverlist" round: script-defined profiles must actually style controls.
# =============================================================================

class TestProfileResolution:
    def setup_method(self):
        self.rt2 = ClientGS2()
        self.host = self.rt2.host
        self.gui = self.rt2.gui

    def _new(self, classname, name, fields=None):
        obj = self.host.create_object(classname, name)
        for k, v in (fields or {}).items():
            obj.set(k, v)
        self.host.call_builtin(None, "addcontrol", [name])
        return obj

    def test_derived_profile_classname_routes_to_profile_not_gs2object(self):
        # `new IRC_WindowProfile("IRC_WindowLeftProfile")`: classname does
        # NOT start with "gui" -- previously fell to a plain GS2Object
        # (unregistered; its auto-addcontrol then warned "non-control value")
        from pyreborn.game.gs2_gui import GuiControlProfile
        base = self._new("GuiBlueTransWindowProfile", "IRC_WindowProfile",
                         {"fontsize": 24, "align": "right"})
        derived = self._new("IRC_WindowProfile", "IRC_WindowLeftProfile",
                            {"align": "left"})
        assert isinstance(base, GuiControlProfile)
        assert isinstance(derived, GuiControlProfile)
        assert self.gui._named["irc_windowleftprofile"] is derived
        assert derived.parent_profile_name == "irc_windowprofile"
        assert self.gui.roots == []          # profiles never render

    def test_construction_fields_land_on_profile(self):
        # the VM's with-scope assignment is existence-gated on has(); a
        # profile must claim every field name or its members stay empty
        prof = self._new("GuiBlueTransWindowProfile", "IRC_WindowProfile")
        assert prof.has("fillcolor") and prof.has("anyfieldatall")
        prof.set("fillcolor", [224, 0, 0, 192])
        assert prof.get("fillcolor") == [224, 0, 0, 192]

    def test_chain_merges_child_over_parent_down_to_builtin(self):
        self._new("GuiBlueTransWindowProfile", "IRC_WindowProfile",
                  {"fontsize": 24, "align": "right"})
        self._new("IRC_WindowProfile", "IRC_WindowRedProfile",
                  {"fillcolor": [224, 0, 0, 192]})
        win = GuiWindowCtrl("W")
        win._manager = self.gui
        win.set("profile", "IRC_WindowRedProfile")
        prof = win.resolve_profile()
        assert prof.bg == (224, 0, 0, 192)          # own field
        assert prof.font_size == 24                 # inherited from parent
        assert prof.align == "right"
        # builtin root (GuiBlueTransWindowProfile) supplies the text color
        assert prof.fg == (255, 255, 255)

    def test_profile_object_assignment_resolves(self):
        # `profile = IRC_ScrollProfile;` assigns the OBJECT; stringifying it
        # took the repr and every such control fell back to the default
        prof_obj = self._new("GuiBlueTransScrollProfile", "IRC_ScrollProfile",
                             {"fillcolor": [1, 2, 3, 200], "border": 0})
        ctrl = GuiTextCtrl("T")
        ctrl._manager = self.gui
        ctrl.set("profile", prof_obj)
        assert ctrl.profile_obj is prof_obj
        resolved = ctrl.resolve_profile()
        assert resolved.bg == (1, 2, 3, 200)
        assert resolved.border_style == 0           # border = 0 -> borderless

    def test_builtin_profile_vivifies_on_bare_reference(self):
        # `profile = GuiDefaultProfile;` -- engine builtin, never
        # script-defined; get_object must resolve it to a profile object
        obj = self.host.get_object("guidefaultprofile")
        from pyreborn.game.gs2_gui import GuiControlProfile
        assert isinstance(obj, GuiControlProfile)
        assert self.host.get_object("guidefaultprofile") is obj   # cached
        # late restyle via `with (GuiDefaultProfile) { fillcolor = ...; }`
        obj.set("fillcolor", [9, 9, 9, 255])
        ctrl = GuiTextCtrl("T2")
        ctrl._manager = self.gui
        ctrl.set("profile", obj)
        assert ctrl.resolve_profile().bg == (9, 9, 9, 255)

    def test_unknown_profile_name_falls_back_to_default(self):
        from pyreborn.game.gs2_gui import _DEFAULT_GUIPROFILE
        ctrl = GuiTextCtrl("T3")
        ctrl._manager = self.gui
        ctrl.set("profile", "NoSuchProfile")
        assert ctrl.resolve_profile() is _DEFAULT_GUIPROFILE
        ctrl.set("profile", "")
        assert ctrl.resolve_profile() is _DEFAULT_GUIPROFILE

    def test_styled_render_smoke_with_alpha(self):
        self._new("GuiBlueTransWindowProfile", "IRC_WindowProfile",
                  {"fillcolor": [96, 144, 208, 240]})
        win = self.host.create_object("GuiWindowCtrl", "Win")
        win.set("profile", "IRC_WindowProfile")
        win.set("text", "Styled")
        self.host.call_builtin(None, "addcontrol", ["Win"])
        surf = pygame.Surface((320, 240))
        self.gui.render(surf, _FakeFonts(), sprite_mgr=None)


class TestNewControlMethods:
    def setup_method(self):
        self.rt2 = ClientGS2()
        self.gui = self.rt2.gui

    def test_clearcontrols_removes_all_children(self):
        panel = self.gui.create_control("GuiControl", "Panel")
        child = self.gui.create_control("GuiButtonCtrl", "Child")
        self.gui.addcontrol(child)          # innermost-first (nested new)
        self.gui.addcontrol(panel)
        assert child in panel.children
        panel._m_clearcontrols()
        assert panel.children == [] and child.parent is None

    def test_isactuallyvisible_walks_ancestors(self):
        panel = self.gui.create_control("GuiControl", "P2")
        child = self.gui.create_control("GuiBitmapCtrl", "C2")
        self.gui.addcontrol(child)          # innermost-first (nested new)
        self.gui.addcontrol(panel)
        assert child._m_isactuallyvisible() == 1.0
        panel.visible = False
        assert child._m_isactuallyvisible() == 0.0
        assert child.visible                      # own flag untouched

    def test_setselectedbyid_on_tab_and_list(self):
        from pyreborn.game.gs2_gui import GuiTabCtrl, GuiTextListCtrl
        tab = GuiTabCtrl("Tabs")
        tab._m_addrow(5, "Map")
        tab._m_addrow(7, "News")
        tab._m_setselectedbyid(7)
        assert tab.selected_index == 1
        lst = GuiTextListCtrl("List")
        lst._m_addrow(11, "Global Chat")
        lst._m_addrow(12, "Trade")
        lst._m_setselectedbyid(11)
        assert lst.selected_index == 0

    def test_setselectedbyid_on_treeview(self):
        from pyreborn.game.gs2_gui import GuiTreeViewCtrl
        tree = GuiTreeViewCtrl("Tree")
        node = tree._m_addnodebypath("Classic/Zelda", "/")
        node.set("id", 3)
        tree._m_setselectedbyid(3)
        assert tree.selected_node is node


# =============================================================================
# 2026-07-24 visual-fidelity round (live Login server): canvas sizing,
# skin bitmap arrays, serverlist tree columns, tab re-selection, mini-HTML.
# =============================================================================

class TestLoginVisualFidelity:
    def setup_method(self):
        self.rt2 = ClientGS2()
        self.gui = self.rt2.gui

    # -- serverlist tree ---------------------------------------------------

    def test_tree_column_offsets_from_columns_field(self):
        from pyreborn.game.gs2_gui import GuiTreeViewCtrl
        tree = GuiTreeViewCtrl("SL")
        tree.set("columns", [0, 230])           # Login's construction field
        assert tree.column_offsets() == [0.0, 230.0]
        # setColumnOffset(index, offset) -- Torque's argument order, and the
        # one both live call sites use (setColumnOffset(1, 150) on Global
        # Chat's 600-wide two-column frame set, Preagonal/gbf/bytecode/login/
        # _Serverlist_Chat.gs2bc.gs2:578). This assertion previously had the
        # arguments the other way round; nothing in the corpus called it that
        # way, so the mistake never showed up live.
        tree._m_setcolumnoffset(1, 200)         # setColumnOffset overrides
        assert tree.column_offsets() == [0.0, 200.0]

    def test_tree_count_column_parsed_from_tab_separated_text(self):
        from pyreborn.game.gs2_gui import GuiTreeViewCtrl
        tree = GuiTreeViewCtrl("SL")
        node = tree._m_addnodebypath("Classics/Zelda: A Link to the Past\t63", "/")
        assert node.columns() == ["Zelda: A Link to the Past", "63"]

    def test_tree_hides_empty_label_category_rows(self):
        from pyreborn.game.gs2_gui import GuiTreeViewCtrl
        tree = GuiTreeViewCtrl("SL")
        tree.set("height", 200)
        # the live Login lister has no name for its hidden category: rows
        # arrive as "/Name\t0" and used to render a blank folder row
        tree._m_addnodebypath("Classics/Zelda\t0", "/")
        tree._m_addnodebypath("/Login\t0", "/")
        flat = tree.flat_nodes()
        shown = tree.display_nodes()
        assert len(flat) == 4                    # both folders script-visible
        assert len(shown) == 3                   # blank folder not displayed
        assert all(n.columns()[0] or not n.is_folder for n in shown)
        # node_at indexes DISPLAY rows, not flat rows
        r = tree.rect()
        rh = tree.row_height()
        assert tree.node_at((r.x + 5, r.y + 2 * rh + 2)) is shown[2]

    # -- tab strips --------------------------------------------------------

    def test_clearrows_resets_selection_so_reselect_fires(self):
        from pyreborn.game.gs2_gui import GuiTabCtrl
        tab = GuiTabCtrl("TablesTab")
        fired = []
        tab.set("onselect", lambda *a: fired.append(a))
        tab._m_addrow(0, "Map")
        tab._m_setselectedbyid(0)
        assert len(fired) == 1
        # Login rebuilds the strip on every server click with the SAME id;
        # the pane-show handler must fire again
        tab._m_clearrows()
        assert tab.selected_index == -1
        tab._m_addrow(0, "Map")
        tab._m_setselectedbyid(0)
        assert len(fired) == 2

    # -- canvas sizing (Torque horizSizing/vertSizing) ---------------------

    def test_canvas_resize_propagates_torque_sizing(self):
        panel = self.gui.create_control("GuiControl", "Panel")
        panel.x, panel.y, panel.width, panel.height = 0, 0, 800, 600
        panel.set("horizsizing", "width")
        panel.set("vertsizing", "height")
        child = self.gui.create_control("GuiControl", "Child")
        child.x, child.y, child.width, child.height = 0, 0, 800, 30
        child.set("horizsizing", "width")
        child.set("vertsizing", "top")
        self.gui.addcontrol(child)
        self.gui.addcontrol(panel)
        bar = self.gui.create_control("GuiControl", "Bar")
        bar.x, bar.y, bar.width, bar.height = 0, 570, 800, 30
        bar.set("horizsizing", "width")
        bar.set("vertsizing", "top")
        self.gui.addcontrol(bar)
        self.gui.on_canvas_resize(800, 600)          # baseline
        self.gui.on_canvas_resize(1280, 778)
        assert (panel.width, panel.height) == (1280, 778)
        assert (child.width, child.y) == (1280, 178)  # width follows, top-anchored to bottom
        assert (bar.width, bar.y) == (1280, 748)      # taskbar re-docks to the bottom
        # anchored default ("right"/"bottom") controls do not move
        static = self.gui.create_control("GuiControl", "S")
        static.x, static.y, static.width, static.height = 10, 10, 50, 20
        self.gui.addcontrol(static)
        self.gui.on_canvas_resize(1400, 800)
        assert (static.x, static.y, static.width, static.height) == (10, 10, 50, 20)

    def test_render_tracks_surface_size(self):
        panel = self.gui.create_control("GuiControl", "P")
        panel.x, panel.y, panel.width, panel.height = 0, 0, 800, 600
        panel.set("horizsizing", "width")
        panel.set("vertsizing", "height")
        self.gui.addcontrol(panel)
        self.gui.render(pygame.Surface((800, 600)))
        assert self.gui.canvas_size == (800, 600)
        self.gui.render(pygame.Surface((1000, 700)))
        assert (panel.width, panel.height) == (1000, 700)

    def test_root_parent_reads_resolve_to_canvas(self):
        # updateChatBarSize: ChatBar.parent.clientwidth on a ROOT control
        # (its Torque parent is the canvas) -- None here sized the chat bar
        # to zero width
        ctrl = self.gui.create_control("GuiTextEditCtrl", "ChatBar")
        self.gui.addcontrol(ctrl)
        self.gui.render(pygame.Surface((1280, 778)))
        parent = ctrl.get("parent")
        assert parent is not None
        assert parent.get("clientwidth") == 1280.0
        assert parent.get("clientheight") == 778.0

    # -- plain containers (opaque gate) ------------------------------------

    def test_plain_container_fills_only_when_opaque(self):
        surf = pygame.Surface((60, 40))
        surf.fill((0, 0, 0))
        panel = self.gui.create_control("GuiControl", "Plain")
        panel.x, panel.y, panel.width, panel.height = 0, 0, 60, 40
        panel.set("profile", "GuiDefaultProfile")
        self.gui.addcontrol(panel)
        self.gui.render(surf)
        assert surf.get_at((30, 20))[:3] == (0, 0, 0)   # untouched
        panel.set("opaque", True)                        # profile-object path
        prof = self.gui.profile_by_name("GuiDefaultProfile")
        prof.set("opaque", 1)
        self.gui.render(surf)
        assert surf.get_at((30, 20))[:3] != (0, 0, 0)

    def test_window_title_height_matches_login_panel_math(self):
        from pyreborn.game.gs2_gui import GuiWindowCtrl
        win = self.gui.create_control("GuiWindowCtrl", "W")
        win.x, win.y = 100, 50
        win.set("clientrelative", 1)
        panel = self.gui.create_control("GuiControl", "WPanel")
        panel.x, panel.y = 0, -22                       # Login's overlay math
        self.gui.addcontrol(panel)
        self.gui.addcontrol(win)
        assert GuiWindowCtrl.TITLE_H == 22
        assert panel.rect().y == win.rect().y           # lands on the window top

    # -- skin art ----------------------------------------------------------

    def test_bitmap_array_split_matches_torque_layout(self):
        from pyreborn.game.gs2_gui import _split_bitmap_array
        sep = (255, 0, 0)
        sheet = pygame.Surface((10, 9))
        sheet.fill(sep)
        fill = (16, 49, 123)
        for rect in [(0, 1, 3, 2), (4, 1, 2, 2), (7, 1, 3, 2),
                     (0, 4, 3, 2), (4, 4, 2, 2), (7, 4, 3, 2),
                     (0, 7, 3, 2), (4, 7, 2, 2), (7, 7, 3, 2)]:
            sheet.fill(fill, rect)
        rows = _split_bitmap_array(sheet)
        assert [len(r) for r in rows] == [3, 3, 3]
        assert rows[0][0] == pygame.Rect(0, 1, 3, 2)
        assert rows[2][2] == pygame.Rect(7, 7, 3, 2)

    def test_skin_fetches_missing_art_once_via_file_request(self):
        from types import SimpleNamespace
        requested = []
        rt2 = ClientGS2(SimpleNamespace(
            player=SimpleNamespace(x=0, y=0), players={},
            request_file=lambda name: requested.append(name)))
        mgr = rt2.gui
        sprite_mgr = _FakeSpriteMgr({})
        assert mgr.skin("guiblue_button.png", sprite_mgr) is None
        assert mgr.skin("guiblue_button.png", sprite_mgr) is None
        assert requested == ["guiblue_button.png"]

    def test_skin_reslices_when_sprite_cache_replaces_surface(self):
        mgr = self.gui
        sheet1 = pygame.Surface((10, 9))
        sheet1.fill((255, 0, 0))
        sheet1.fill((1, 2, 3), (0, 1, 3, 2))
        sprites = _FakeSpriteMgr({"art.png": sheet1})
        skin1 = mgr.skin("art.png", sprites)
        assert skin1 is not None and mgr.skin("art.png", sprites) is skin1
        sheet2 = pygame.Surface((10, 9))
        sheet2.fill((255, 0, 0))
        sheet2.fill((1, 2, 3), (0, 1, 3, 2))
        sprites.sheets["art.png"] = sheet2              # download landed
        skin2 = mgr.skin("art.png", sprites)
        assert skin2 is not skin1 and skin2.source is sheet2

    # -- mini-HTML (GuiMLTextCtrl) -----------------------------------------

    def test_parse_mltext_strips_tags_and_honors_breaks(self):
        from pyreborn.game.gs2_gui import parse_mltext
        paras = parse_mltext(
            "<font size=4><b><i>Account:</i></b></font> hosler<br>"
            "<h1><center>OpenGraal</center></h1>"
            "<center>All your base are belong to us!</center><br>")
        texts = ["".join(seg.text for seg in segs) for _a, segs in paras]
        assert texts[0] == "Account: hosler"
        assert any("OpenGraal" in t for t in texts)
        # markup never leaks into rendered text
        assert not any("<" in t for t in texts)
        # heading is bold + enlarged + centered
        for align, segs in paras:
            for seg in segs:
                if seg.text == "OpenGraal":
                    assert seg.bold and seg.size and align == "center"
        # first line's Account: run is bold-italic at font size 4 -> 15px
        first = paras[0][1][0]
        assert first.bold and first.italic and first.size == 15

    def test_parse_mltext_links_and_entities(self):
        from pyreborn.game.gs2_gui import parse_mltext
        paras = parse_mltext('A &amp; B <a href=x>Choose one</a>&nbsp;!')
        segs = paras[0][1]
        joined = "".join(s.text for s in segs)
        assert "A & B" in joined and "Choose one" in joined and "!" in joined
        assert any(s.link for s in segs)

    def test_parse_mltext_ignorelinebreaks(self):
        from pyreborn.game.gs2_gui import parse_mltext
        paras = parse_mltext("<ignorelinebreaks>line one\nline two<br>next")
        texts = ["".join(seg.text for seg in segs) for _a, segs in paras]
        assert texts[0].startswith("line one") and "line two" in texts[0]
        assert len(texts) == 2                            # only the <br> broke

    def test_mltext_autogrows_height_for_scroll_clipping(self):
        from pyreborn.game.gs2_gui import GuiMLTextCtrl
        ml = GuiMLTextCtrl("News")
        ml.width, ml.height = 200.0, 14.0                 # Login's seed height
        ml.set("text", "word " * 60)
        surf = pygame.Surface((400, 400))
        ml.draw(surf, _FakeFonts(), None)
        assert ml.height > 14.0

    # -- taskbar start button ----------------------------------------------

    def test_start_button_labels_from_start_menu(self):
        btn = self.gui.create_control("GuiButtonCtrl", "StartBtn")
        btn.set("stylesection", "Taskbar.StartButton")
        self.gui.addcontrol(btn)
        menu = self.gui.create_control("GuiStartMenuCtrl", "Menu")
        menu.set("text", "Graal")
        self.gui.addcontrol(menu)
        assert btn._label_text() == "Graal"

    def test_scroll_content_height_and_wheel_clamp(self):
        from pyreborn.game.gs2_gui import GuiScrollCtrl
        scroll = self.gui.create_control("GuiScrollCtrl", "Scr")
        scroll.x, scroll.y, scroll.width, scroll.height = 0, 0, 100, 100
        inner = self.gui.create_control("GuiControl", "Inner")
        inner.x, inner.y, inner.width, inner.height = 0, 0, 80, 400
        self.gui.addcontrol(inner)
        self.gui.addcontrol(scroll)
        assert scroll.content_height() == 400
        assert scroll.max_scroll_y() == 300
        wheel = pygame.event.Event(pygame.MOUSEWHEEL,
                                   {"y": -100, "pos": (50, 50)})
        assert self.gui.handle_event(wheel)
        assert scroll.scroll_y == 300.0                  # clamped to content

    # -- frame sets (Global Chat) ------------------------------------------

    def test_frame_set_lays_children_out_in_row_major_cells(self):
        """Global Chat's splitter: one row, two columns, divider at x=150 in
        a 600x400 client area (Preagonal/gbf/bytecode/login/
        _Serverlist_Chat.gs2bc.gs2:566,570-616). Unimplemented, both cells kept
        their constructor defaults stacked at (0,0), which squashed the chat
        pane into a ~150px strip."""
        frames = self.gui.create_control("GuiFrameSetCtrl", "GlobalChat_Frames")
        frames.set("extent", [600, 400])
        frames.set("rowcount", 1)
        frames.set("columncount", 2)
        frames._m_setcolumnoffset(1, 150)
        left = self.gui.create_control("GuiScrollCtrl", "Channels")
        self.gui.addcontrol(left)
        right = self.gui.create_control("GuiControl", "ChatPanel")
        self.gui.addcontrol(right)
        self.gui.addcontrol(frames)

        assert (left.x, left.y, left.width, left.height) == (0, 0, 150, 400)
        assert (right.x, right.y, right.width, right.height) == (150, 0, 450, 400)
        # the pane the placeholder text lives in must be the WIDE one
        assert right.get("clientwidth") == 450.0

    def test_frame_set_splits_rows_and_falls_back_to_an_even_split(self):
        """setRowOffset(1, 140) over a two-row 412x280 frame set is Login's
        PM window (Preagonal/gbf/bytecode/login/_Playerlist.gs2bc.gs2:
        2517-2519). A divider nobody set splits evenly."""
        frames = self.gui.create_control("GuiFrameSetCtrl", "PMFrames")
        frames.set("extent", [412, 280])
        frames.set("rowcount", 2)
        frames.set("columncount", 1)
        frames._m_setrowoffset(1, 140)
        top = self.gui.create_control("GuiControl", "Top")
        self.gui.addcontrol(top)
        bottom = self.gui.create_control("GuiControl", "Bottom")
        self.gui.addcontrol(bottom)
        self.gui.addcontrol(frames)
        assert (top.y, top.height) == (0, 140)
        assert (bottom.y, bottom.height) == (140, 140)

        even = self.gui.create_control("GuiFrameSetCtrl", "Even")
        even.set("extent", [400, 100])
        even.set("rowcount", 1)
        even.set("columncount", 4)
        cells = []
        for index in range(4):
            cell = self.gui.create_control("GuiControl", f"Cell{index}")
            self.gui.addcontrol(cell)
            cells.append(cell)
        self.gui.addcontrol(even)
        assert [c.x for c in cells] == [0, 100, 200, 300]
        assert [c.width for c in cells] == [100, 100, 100, 100]

    def test_client_extent_write_resizes_the_outer_window(self):
        """`extent = (bounds.extent - m_size) + clientExtent`
        (propfun_guicontrol_clientextent_w, FourPlay quattroplay/src/gui/
        GuiControlProperties.cpp:115-122), and the reader hands back the
        CLIENT size. Treating clientextent as the outer extent gave Global
        Chat a 600x400 window with a 600x378 client area, so its bottom row
        hung 22px out through the frame."""
        from pyreborn.game.gs2_gui import GuiWindowCtrl
        win = self.gui.create_control("GuiWindowCtrl", "Win")
        win.set("clientextent", [600, 400])
        assert (win.width, win.height) == (600, 400 + GuiWindowCtrl.TITLE_H)
        assert win.get("clientextent") == [600.0, 400.0]
        assert win.get("clientheight") == 400.0

        # a plain control has no chrome, so it is a plain extent write
        panel = self.gui.create_control("GuiControl", "Panel")
        panel.set("clientextent", [300, 120])
        assert (panel.width, panel.height) == (300, 120)
        assert panel.get("clientextent") == [300.0, 120.0]

        # clientheight/clientwidth writes go the same way
        win2 = self.gui.create_control("GuiWindowCtrl", "Win2")
        win2.set("clientwidth", 280)
        win2.set("clientheight", 90)
        assert (win2.width, win2.height) == (280, 90 + GuiWindowCtrl.TITLE_H)

    def test_context_menu_starts_hidden(self):
        """GuiContextMenuCtrl::initObject sets m_visible = false (FourPlay
        quattroplay/src/gui/GuiContextMenuCtrl.cpp:35-46). As an unknown
        class it fell back to a VISIBLE generic control, so Global Chat's
        channel menu drew as a stray filled rectangle at the canvas origin,
        over the top of the server-list window."""
        from pyreborn.game.gs2_gui import GuiContextMenuCtrl
        menu = self.gui.create_control("GuiContextMenuCtrl",
                                       "GlobalChat_ChannelMenu")
        assert isinstance(menu, GuiContextMenuCtrl)
        assert menu.visible is False

    def test_login_control_classes_are_all_known(self):
        """Every control class the Login corpus constructs must resolve to a
        real class -- an unknown one silently becomes a generic, always
        visible, never-laid-out GuiControl."""
        from pyreborn.game.gs2_gui import _CONTROL_CLASSES
        for name in ("GuiFrameSetCtrl", "GuiContextMenuCtrl", "GuiTreeViewCtrl",
                     "GuiTextListCtrl", "GuiTabCtrl", "GuiWindowCtrl",
                     "GuiMLTextCtrl", "GuiScrollCtrl"):
            assert name.lower() in _CONTROL_CLASSES, name

    def test_center_sizing_only_applies_on_a_canvas_resize(self):
        """Not a bug -- pinned because it looked like one.

        Global Chat is built with horizSizing/vertSizing = "center" and no
        x/y, so it starts at the origin and is only centred when the canvas
        resizes. That is what the reference does too: setting horizsizing
        just records the mode (propfun_guicontrol_horizsizing_w, FourPlay
        quattroplay/src/gui/GuiControlProperties.cpp:342-352) and neither
        GuiControl::addObject nor showtop() repositions anything
        (GuiControl.cpp:2244-2276 and :2224-2233).
        """
        gui = self.gui
        gui.canvas_size = (800, 600)
        win = gui.create_control("GuiWindowCtrl", "GlobalChat_Window")
        win.set("horizsizing", "center")
        win.set("vertsizing", "center")
        win.set("clientextent", [600, 400])
        gui.addcontrol(win)
        assert (win.x, win.y) == (0.0, 0.0)
        gui.on_canvas_resize(1262, 594)
        assert win.x == (1262 - 600) / 2
        assert win.y == (594 - 422) / 2


# =============================================================================
# Control tables: the names the construction-block existence gate needs
# =============================================================================

def _construction_write(ctrl, name, value):
    """A bare `name = value;` inside a `new <Class>(...) { ... }` block.

    The VM resolves such an assignment against the with-target's has() and,
    when the name is not claimed, writes a TEMP instead
    (reborn_protocol/gs2/vm.py:572-578) -- so an unclaimed name is a write
    that never reaches the control. Returns whether it landed."""
    if not ctrl.has(name.lower()):
        return False
    ctrl.set(name.lower(), value)
    return True


class TestClaimedPropertyNames:
    def setup_method(self):
        self.gui = ClientGS2().gui

    def test_bitmap_button_claims_its_three_faces(self):
        """Login's 2001-style buttons set all three in their construction
        blocks (graal-loginserver/weapons/
        weapon-Rescripted_IRC_Login2001.txt:324-326); unclaimed, they
        rendered with no face at all."""
        btn = self.gui.create_control("GuiBitmapButtonCtrl", "LoginButton")
        faces = (("normalbitmap", "gui2001_button.png"),
                 ("mouseoverbitmap", "gui2001_button_over.png"),
                 ("pressedbitmap", "gui2001_button_pressed.png"))
        for name, value in faces:
            assert _construction_write(btn, name, value), name
            assert btn.get(name) == value
        assert btn.face() == "gui2001_button.png"
        btn.hovered = True
        assert btn.face() == "gui2001_button_over.png"
        btn.pressed = True
        assert btn.face() == "gui2001_button_pressed.png"
        # an unset slot falls back to the normal face
        btn.set("pressedbitmap", "")
        assert btn.face() == "gui2001_button.png"
        # setBitmap(name, slot) is the two-argument form on this class
        btn.get("setbitmap")("other.png", 2)
        assert btn.get("pressedbitmap") == "other.png"

    def test_text_edit_claims_password(self):
        """16 corpus files write it, 8 inside a construction block."""
        edit = self.gui.create_control("GuiTextEditCtrl", "PassEdit")
        assert _construction_write(edit, "password", True)
        assert edit.get("password") == 1.0
        for name in ("inputtype", "showcursor", "deniedsound"):
            assert edit.has(name), name

    def test_button_family_claims_checked_groupnum_buttontype(self):
        """All three live on GuiButtonBaseCtrl, so they are reachable on a
        plain button and a bitmap button too, not just on the checkbox
        (GuiButtonBaseCtrlProperties.cpp:68-105)."""
        for classname in ("GuiButtonCtrl", "GuiBitmapButtonCtrl",
                          "GuiCheckBoxCtrl", "GuiRadioCtrl"):
            ctrl = self.gui.create_control(classname, classname)
            assert _construction_write(ctrl, "groupnum", 1), classname
            assert ctrl.get("groupnum") == 1.0
            assert _construction_write(ctrl, "checked", True), classname
            assert ctrl.get("checked") == 1.0
            assert _construction_write(ctrl, "buttontype", "RadioButton")
            assert ctrl.get("buttontype") == "RadioButton"

    def test_button_defaults_match_the_class(self):
        assert self.gui.create_control("GuiButtonCtrl", "b").get(
            "buttontype") == "PushButton"
        assert self.gui.create_control("GuiCheckBoxCtrl", "c").get(
            "buttontype") == "ToggleButton"
        assert self.gui.create_control("GuiRadioCtrl", "r").get(
            "buttontype") == "RadioButton"
        # groupnum defaults to -1 (GuiButtonBaseCtrl.cpp:33)
        assert self.gui.create_control("GuiRadioCtrl", "r2").get(
            "groupnum") == -1.0

    def test_buttontype_write_is_case_sensitive_and_silently_rejected(self):
        btn = self.gui.create_control("GuiCheckBoxCtrl", "cb")
        btn.set("buttontype", "pushbutton")          # wrong case -> no-op
        assert btn.get("buttontype") == "ToggleButton"
        btn.set("buttontype", "PushButton")
        assert btn.get("buttontype") == "PushButton"

    def test_mltext_claims_its_whole_table(self):
        """All thirteen are written bare in construction blocks -- wordwrap
        in 7 files, htmlcompatibility in 5, maxchars in 4."""
        ml = self.gui.create_control("GuiMLTextCtrl", "Serverlist_EventNews")
        for name in ("allowedtags", "alpha", "cursorposition", "deniedsound",
                     "disallowedtags", "htmllinks", "htmlcompatibility",
                     "maxchars", "parsetags", "plaintext", "text", "urlbase",
                     "wordwrap"):
            assert ml.has(name), name
        assert _construction_write(ml, "urlbase", "http://example.com/")
        assert ml.get("urlbase") == "http://example.com/"
        assert _construction_write(ml, "wordwrap", False)
        assert ml.word_wrap() is False

    def test_scroll_claims_childmargin_and_the_rest_of_its_table(self):
        scroll = self.gui.create_control("GuiScrollCtrl", "Scroll")
        for name in ("childmargin", "constantthumbheight", "hscrollbar",
                     "scrollpos", "tile", "vscrollbar", "wheelscrolllines",
                     "willfirstrespond"):
            assert scroll.has(name), name
        # both spellings the corpus uses for a point-valued field
        assert _construction_write(scroll, "childmargin", "0 0")
        assert scroll.get("childmargin") == "0 0"
        assert _construction_write(scroll, "childmargin", [10, 10])
        assert scroll.get("childmargin") == [10, 10]

    def test_scrollbar_mode_write_is_case_sensitive(self):
        scroll = self.gui.create_control("GuiScrollCtrl", "Scroll")
        scroll.set("vscrollbar", "alwaysOff")
        scroll.set("vscrollbar", "ALWAYSON")         # not byte-exact -> no-op
        assert scroll.get("vscrollbar") == "alwaysOff"
        # wheelscrolllines ignores non-positive values (:103-112)
        scroll.set("wheelscrolllines", 4)
        scroll.set("wheelscrolllines", 0)
        assert scroll.get("wheelscrolllines") == 4

    def test_bitmap_ctrl_claims_tile_with_wrap_as_its_alias(self):
        """12 corpus files set `tile`; `wrap` is the same field under a
        second name (GuiBitmapCtrlProperties.cpp:95-112)."""
        bmp = self.gui.create_control("GuiBitmapCtrl", "Back")
        assert _construction_write(bmp, "tile", True)
        assert bmp.tile is True and bmp.get("wrap") == 1.0
        bmp.set("wrap", 0)
        assert bmp.tile is False and bmp.get("tile") == 0.0
        for name in ("bitmaprectangle", "fullbitmap"):
            assert bmp.has(name), name

    def test_tiled_bitmap_repeats_instead_of_stretching(self):
        bmp = self.gui.create_control("GuiBitmapCtrl", "Back")
        bmp.x, bmp.y, bmp.width, bmp.height = 0, 0, 32, 32
        bmp.set("bitmap", "cell.png")
        bmp.set("tile", True)
        cell = pygame.Surface((16, 16))
        cell.fill((0, 0, 0))
        cell.fill((0, 255, 0), pygame.Rect(0, 0, 4, 4))
        surf = pygame.Surface((32, 32))
        bmp.draw(surf, _FakeFonts(), _FakeSpriteMgr({"cell.png": cell}))
        # the marker corner repeats at every 16px step
        assert surf.get_at((1, 1))[:3] == (0, 255, 0)
        assert surf.get_at((17, 17))[:3] == (0, 255, 0)
        assert surf.get_at((10, 10))[:3] == (0, 0, 0)


class TestButtonActivation:
    """Which control does what is driven by `buttontype`, and the
    radio-group sweep lives in onAction() -- never in a `checked` write
    (GuiButtonBaseCtrl.cpp:42-46 vs :59-94)."""

    def setup_method(self):
        self.gui = ClientGS2().gui
        self.panel = self.gui.create_control("GuiControl", "Panel")
        self.gui.addcontrol(self.panel)

    def _radio(self, name, groupnum):
        radio = self.gui.create_control("GuiRadioCtrl", name)
        self.gui.addcontrol(radio)
        self.gui.add_to(self.panel, radio)
        radio.set("groupnum", groupnum)
        return radio

    def test_script_checked_write_leaves_siblings_checked(self):
        """`StartMemberCheck.checked = true;` does NOT clear the sibling --
        Login clears it by hand on the next line (graal-loginserver/weapons/
        weapon-Rescripted_IRC_Login2.txt:48-49)."""
        a, b = self._radio("A", 1), self._radio("B", 1)
        a.set("checked", True)
        b.set("checked", True)
        assert a.checked is True and b.checked is True

    def test_activation_clears_only_same_groupnum_radios(self):
        a, b = self._radio("A", 1), self._radio("B", 1)
        other = self._radio("Other", 2)
        a.on_action()
        other.on_action()
        b.on_action()
        assert b.checked is True
        assert a.checked is False
        # a different groupnum is a different group and must survive
        assert other.checked is True

    def test_buttontype_not_class_decides_the_behaviour(self):
        """A checkbox with buttontype = "RadioButton" is a working radio,
        and a radio with "PushButton" stops being one."""
        cb = self.gui.create_control("GuiCheckBoxCtrl", "CB")
        self.gui.addcontrol(cb)
        self.gui.add_to(self.panel, cb)
        cb.set("buttontype", "RadioButton")
        cb.set("groupnum", 3)
        radio = self._radio("R", 3)
        radio.on_action()
        cb.on_action()
        assert cb.checked is True and radio.checked is False

        plain = self._radio("Plain", 3)
        plain.set("buttontype", "PushButton")
        plain.on_action()
        assert plain.checked is False and cb.checked is True

    def test_toggle_button_flips_on_every_activation(self):
        cb = self.gui.create_control("GuiCheckBoxCtrl", "CB")
        self.gui.addcontrol(cb)
        cb.on_action()
        assert cb.checked is True
        cb.on_action()
        assert cb.checked is False

    def test_inactive_control_does_not_activate(self):
        """onAction() returns early when `active` is false (:61-62); an
        UNSET active is true (GuiControl.cpp:3172)."""
        fired = []
        cb = self.gui.create_control("GuiCheckBoxCtrl", "CB")
        cb.set("onaction", lambda: fired.append(1))
        assert cb.is_active() is True
        cb.set("active", False)
        cb.on_action()
        assert cb.checked is False and fired == []


class TestBorderStyle:
    """`border` selects a border RENDERER, it is not a pixel width
    (TGUIRender::renderBorder, FourPlay quattroplay/src/TGUIRender.cpp:
    59-153); the width is the separate `borderthickness`."""

    def setup_method(self):
        self.rt2 = ClientGS2()
        self.gui = self.rt2.gui
        self.host = self.rt2.host

    def _profile(self, name, fields):
        prof = self.host.create_object("GuiControlProfile", name)
        for key, value in fields.items():
            prof.set(key, value)
        self.gui.addcontrol(prof)
        return prof

    def _resolved(self, fields):
        ctrl = self.gui.create_control("GuiControl", "C")
        ctrl.set("profile", self._profile("P" + str(len(fields)), fields))
        return ctrl.resolve_profile()

    def test_border_5_is_the_skinned_style_not_a_3px_rectangle(self):
        """Ten corpus assignments use the skinned value 5; clamped to 0..3
        it drew a solid 3px frame."""
        prof = self._resolved({"border": 5, "borderthickness": 2})
        assert prof.border_style == 5
        assert prof.border_thickness == 2

    def test_border_style_0_draws_nothing(self):
        from pyreborn.game.gs2_gui import _draw_border
        prof = self._resolved({"border": 0, "bordercolor": [255, 0, 0]})
        surf = pygame.Surface((20, 20))
        surf.fill((0, 0, 0))
        _draw_border(surf, pygame.Rect(0, 0, 20, 20), prof)
        assert surf.get_at((0, 0))[:3] == (0, 0, 0)

    def test_border_style_1_is_a_flat_one_pixel_bordercolor_rect(self):
        from pyreborn.game.gs2_gui import _draw_border
        prof = self._resolved({"border": 1, "bordercolor": [255, 0, 0]})
        surf = pygame.Surface((20, 20))
        surf.fill((0, 0, 0))
        _draw_border(surf, pygame.Rect(0, 0, 20, 20), prof)
        assert surf.get_at((0, 0))[:3] == (255, 0, 0)
        assert surf.get_at((1, 1))[:3] == (0, 0, 0)      # one pixel only

    def test_border_style_2_bevels_with_bordercolorna_and_black(self):
        from pyreborn.game.gs2_gui import _draw_border
        prof = self._resolved({"border": 2, "bordercolor": [255, 0, 0],
                               "bordercolorna": [0, 255, 0]})
        surf = pygame.Surface((20, 20))
        surf.fill((0, 0, 0))
        _draw_border(surf, pygame.Rect(0, 0, 20, 20), prof)
        # outer ring: bordercolorna on top/left, bevel dark on bottom/right
        assert surf.get_at((5, 0))[:3] == (0, 255, 0)
        assert surf.get_at((0, 5))[:3] == (0, 255, 0)
        # inner ring: the reverse (TGUIRender.cpp:65-90)
        assert surf.get_at((5, 18))[:3] == (0, 255, 0)
        assert surf.get_at((18, 5))[:3] == (0, 255, 0)

    def test_justify_is_the_same_slot_as_align(self):
        """`justify` and `align` share getter and setter pointers
        (GuiControlProfileProperties.cpp:550 vs :582) and the live Login
        content spells it `justify` (5 files, 23 assignments)."""
        assert self._resolved({"justify": "center"}).align == "center"
        # last write wins, whichever name it used
        prof = self.host.create_object("GuiControlProfile", "PJ")
        prof.set("align", "right")
        prof.set("justify", "center")
        self.gui.addcontrol(prof)
        ctrl = self.gui.create_control("GuiControl", "CJ")
        ctrl.set("profile", prof)
        assert ctrl.resolve_profile().align == "center"

    def test_align_write_is_case_sensitive_and_keeps_the_inherited_value(self):
        base = self._profile("BaseAlign", {"align": "center"})
        child = self.host.create_object("GuiControlProfile", "ChildAlign")
        child.parent_profile_name = "basealign"
        child.set("justify", "RIGHT")            # not byte-exact -> no-op
        self.gui.addcontrol(child)
        ctrl = self.gui.create_control("GuiControl", "CA")
        ctrl.set("profile", child)
        assert base is not None
        assert ctrl.resolve_profile().align == "center"


class TestTextTruncation:
    """maxchars defaults to 255 and setText applies it, so it truncates
    every write on labels and edit fields alike (GuiTextCtrl.cpp:27, :181)."""

    def setup_method(self):
        self.gui = ClientGS2().gui

    def test_label_text_is_truncated_at_the_default_255(self):
        label = self.gui.create_control("GuiTextCtrl", "L")
        assert label.get("maxchars") == 255.0
        label.set("text", "x" * 300)
        assert len(label.get("text")) == 255

    def test_edit_field_inherits_the_cap_from_guitextctrl(self):
        edit = self.gui.create_control("GuiTextEditCtrl", "E")
        edit.set("maxchars", 5)
        edit.get("settext")("abcdefgh")
        assert edit.get("text") == "abcde"
        # typing stops at the same cap
        assert edit.max_len == 5

    def test_a_non_positive_maxchars_disables_the_cap(self):
        label = self.gui.create_control("GuiTextCtrl", "L")
        label.set("maxchars", 0)
        label.set("text", "y" * 400)
        assert len(label.get("text")) == 400


class TestScrollBehaviour:
    def setup_method(self):
        self.gui = ClientGS2().gui
        self.scroll = self.gui.create_control("GuiScrollCtrl", "S")
        self.gui.addcontrol(self.scroll)
        self.scroll.width, self.scroll.height = 100.0, 50.0
        self.events = []
        self.scroll.set("onscrolled", lambda *a: self.events.append(
            (a, self.scroll.get("scrollpos"))))

    def _child(self, w=80.0, h=250.0):
        child = self.gui.create_control("GuiControl", "Inner")
        self.gui.addcontrol(child)
        self.gui.add_to(self.scroll, child)
        child.width, child.height = w, h
        return child

    def test_a_childless_scroll_control_cannot_be_scrolled(self):
        """`if (m_controls->mArraySize <= 0) return;` -- not even to 0
        (GuiScrollCtrl.cpp:911)."""
        self.scroll.get("scrollto")(0, 40)
        assert self.scroll.scroll_y == 0.0
        assert self.events == []

    def test_onscrolled_fires_before_the_position_is_stored(self):
        """The handler is invoked with (newX, newY, dx, dy) and only THEN
        are the fields written, so a handler reading .scrollpos sees the
        pre-scroll value (GuiScrollCtrl.cpp:930-939)."""
        self._child()
        self.scroll.get("scrollto")(0, 40)
        assert self.scroll.scroll_y == 40.0
        assert len(self.events) == 1
        args, seen = self.events[0]
        assert args == (0.0, 40.0, 0.0, 40.0)
        assert seen == [0.0, 0.0]

    def test_scrollpos_writes_go_through_scrollto(self):
        self._child()
        self.scroll.set("scrollpos", [0, 500])
        assert self.scroll.get("scrollpos") == [0.0, 200.0]   # clamped
        assert len(self.events) == 1

    def test_an_unchanged_position_fires_nothing(self):
        self._child()
        self.scroll.get("scrollto")(0, 40)
        self.scroll.get("scrollto")(0, 40)
        assert len(self.events) == 1

    def test_scrolltotop_and_bottom_reset_the_horizontal_scroll(self):
        self._child(w=400.0)
        self.scroll.get("scrollto")(120, 10)
        assert self.scroll.scroll_x == 120.0
        self.scroll.get("scrolltobottom")()
        assert (self.scroll.scroll_x, self.scroll.scroll_y) == (0.0, 200.0)
        self.scroll.get("scrollto")(120, 10)
        self.scroll.get("scrolltotop")()
        assert (self.scroll.scroll_x, self.scroll.scroll_y) == (0.0, 0.0)


class TestMLTextReflow:
    def setup_method(self):
        self.gui = ClientGS2().gui

    def test_reflow_resizes_and_fires_onreflow(self):
        """reflow() is not a pure layout pass: it resizes to the page's
        extents and fires onReflow(width, height)
        (GuiMLTextCtrl::reflowResize, quattroplay/src/gui/GuiMLTextCtrl.cpp:
        1609-1648)."""
        ml = self.gui.create_control("GuiMLTextCtrl", "Log")
        self.gui.addcontrol(ml)
        ml.x, ml.y, ml.width, ml.height = 0, 0, 200, 10
        ml.set("text", "one two three four five six seven eight nine ten")
        fired = []
        ml.set("onreflow", lambda w, h: fired.append((w, h)))
        surf = pygame.Surface((300, 300))
        ml.draw(surf, _FakeFonts(), None)
        ml.get("reflow")()
        assert fired and fired[0] == (ml.width, ml.height)
        assert ml.height > 10


class TestDrawingPanelOps:
    def setup_method(self):
        self.gui = ClientGS2().gui
        self.panel = self.gui.create_control("GuiDrawingPanel", "P")
        self.panel.width, self.panel.height = 64.0, 64.0

    def test_drawimagestretched_keeps_its_source_rectangle(self):
        """Signature is `iiiisiiii` = (x, y, w, h, image, srcX, srcY, srcW,
        srcH) (GuiDrawingPanelProperties.cpp:197); args 5-8 used to be
        dropped, which only stayed invisible while every live caller passed
        the whole image as its source rect."""
        self.panel.get("drawimagestretched")(0, 0, 32, 32, "sheet.png",
                                             16, 0, 16, 16)
        assert self.panel.draw_ops == [
            ("imagestretched", 0.0, 0.0, "sheet.png", (32.0, 32.0),
             (16.0, 0.0, 16.0, 16.0))]
        sheet = pygame.Surface((32, 16))
        sheet.fill((255, 0, 0))
        sheet.fill((0, 0, 255), pygame.Rect(16, 0, 16, 16))
        surf = pygame.Surface((64, 64))
        self.panel.draw(surf, _FakeFonts(), _FakeSpriteMgr({"sheet.png": sheet}))
        # the BLUE half is what was asked for, scaled up to 32x32
        assert surf.get_at((4, 4))[:3] == (0, 0, 255)
        assert surf.get_at((30, 30))[:3] == (0, 0, 255)

    def test_drawrect_is_not_a_reference_method(self):
        """No `drawrect` entry exists in GuiDrawingPanelProperties::funcDefs
        (:192-207) and no corpus script calls one -- it was ours."""
        from pyreborn.game.gs2_gui import GuiDrawingPanel
        assert "drawrect" not in GuiDrawingPanel._METHOD_NAMES

    def test_checkbox_has_no_value_alias(self):
        """`value` is registered nowhere under src/gui and no corpus script
        uses it."""
        cb = self.gui.create_control("GuiCheckBoxCtrl", "CB")
        assert not cb.has("value")


def test_stretch_control_client_size_is_its_own_field():
    """GuiStretchCtrl redeclares clientextent/clientwidth/clientheight
    against its virtual content size, so the write does NOT resize the outer
    bounds the way GuiControl's versions do
    (GuiStretchCtrlProperties.cpp:46-48)."""
    from pyreborn.game.gs2_gui import GuiStretchCtrl
    gui = ClientGS2().gui
    stretch = gui.create_control("GuiStretchCtrl", "Stretch")
    assert isinstance(stretch, GuiStretchCtrl)
    stretch.set("extent", [200, 100])
    stretch.set("clientwidth", 600)
    stretch.set("clientheight", 400)
    assert (stretch.width, stretch.height) == (200, 100)
    assert stretch.get("clientextent") == [600.0, 400.0]


def test_password_field_masks_its_text():
    """`password = true;` in a GuiTextEditCtrl construction block (8 corpus
    files) used to be dropped by the existence gate, so Login's password
    fields echoed the characters. The flag is derived from `inputtype`, and
    clearing it writes "default" rather than restoring the old type
    (GuiTextEditCtrl.cpp:308-316)."""
    gui = ClientGS2().gui
    edit = gui.create_control("GuiTextEditCtrl", "PassEdit")
    edit.set("inputtype", "email")
    assert edit.get("password") == 0.0
    edit.set("password", True)
    assert edit.get("inputtype") == "password" and edit.is_password()
    edit.text = "hunter2"
    surf = pygame.Surface((200, 40))
    edit.x, edit.y, edit.width, edit.height = 0, 0, 150, 22
    edit.draw(surf, _FakeFonts(), None)
    assert edit.text == "hunter2"            # only the rendering is masked
    edit.set("password", False)
    assert edit.get("inputtype") == "default"


def test_window_maximized_is_a_toggle_and_the_methods_are_callable():
    """`maximized = true;` twice UNmaximizes: the setter calls
    maximizeWindow(), which restores when already maximized (FourPlay
    quattroplay/src/gui/GuiWindowCtrlProperties.cpp:137-156,
    GuiWindowCtrl.cpp:169-173). Two corpus files write it, and the write was
    dropped entirely before -- the name was not claimed."""
    gui = ClientGS2().gui
    win = gui.create_control("GuiWindowCtrl", "W")
    gui.addcontrol(win)
    win.x, win.y, win.width, win.height = 20, 30, 200, 150
    assert win.has("maximized")
    win.set("maximized", True)
    assert win.get("maximized") == 1.0 and (win.x, win.y) == (0.0, 0.0)
    win.set("maximized", True)
    assert win.get("maximized") == 0.0 and (win.x, win.y) == (20.0, 30.0)
    # the four window methods are script-callable
    win.get("maximize")()
    assert win.get("maximized") == 1.0
    win.get("restore")()
    assert win.get("maximized") == 0.0 and (win.width, win.height) == (200, 150)
    win.get("close")()
    assert win.visible is False


def test_context_menu_open_close_and_isopen():
    """`isopen` has two corpus call sites (GuiContextMenuCtrlProperties.cpp:
    164-169)."""
    gui = ClientGS2().gui
    menu = gui.create_control("GuiContextMenuCtrl", "Menu")
    gui.addcontrol(menu)
    assert menu.get("isopen")() == 0.0
    menu.get("open")(40, 60)
    assert menu.get("isopen")() == 1.0 and (menu.x, menu.y) == (40.0, 60.0)
    menu.get("close")()
    assert menu.get("isopen")() == 0.0
    assert menu.has("maxpopupheight")


def test_ontextchanged_fires_on_change_with_the_clipped_text():
    """GuiTextCtrl::setText (GuiTextCtrl.cpp:170-199): unchanged text
    early-outs with no event (:172-176), the maxchars clip applies first
    (:181), then onTextChanged fires on the control with the CLIPPED text
    (:190-193)."""
    gui = ClientGS2().gui
    label = gui.create_control("GuiTextCtrl", "Lbl")
    gui.addcontrol(label)
    seen = []
    label.set("ontextchanged", lambda *a: seen.append(a))
    label.set("maxchars", 5)
    label.set("text", "abcdefgh")
    assert seen == [("abcde",)]          # clipped BEFORE the event
    label.set("text", "abcdefgh")        # clips to the same text: early-out
    assert len(seen) == 1
    label.get("settext")("xy")           # the settext method routes the same
    assert seen[-1] == ("xy",)
    # the member write itself must be claimed (construction-block closures)
    assert label.has("ontextchanged")


def test_text_property_write_clears_the_selection_but_settext_does_not():
    """C7: the `text` PROPERTY setter zeroes both selection anchors, the
    inherited settext() method does not (GuiTextEditCtrlProperties.cpp:31-36
    vs GuiTextCtrlProperties.cpp:30-33)."""
    gui = ClientGS2().gui
    edit = gui.create_control("GuiTextEditCtrl", "Edit")
    gui.addcontrol(edit)
    edit.set("text", "hello world")
    edit.get("setselection")(0, 5)
    assert edit.selection == (0, 5)
    edit.get("settext")("hello there")
    assert edit.selection == (0, 5)      # method: selection intact
    edit.set("text", "replaced")
    assert edit.selection == (0, 0)      # property: anchors zeroed


def test_useownprofile_copies_and_isolates_the_profile():
    """`useownprofile = true` allocates a PRIVATE copyFrom'd profile
    (GuiControl::setUseOwnProfile, GuiControl.cpp:1746-1806), the getter is
    `ownProfile != nullptr` (GuiControlProperties.cpp:559-561), and the
    profile getter prefers it (:411-418) -- so `profile.<field> = ...` after
    it styles only this control. 3 mobile-corpus scripts rely on this."""
    gui = ClientGS2().gui
    prof = gui.create_control("GuiControlProfile", "SharedProf")
    prof.set("fontcolor", [1, 2, 3])
    gui.addcontrol(prof)
    a = gui.create_control("GuiButtonCtrl", "OwnProfA")
    gui.addcontrol(a)
    b = gui.create_control("GuiButtonCtrl", "OwnProfB")
    gui.addcontrol(b)
    a.set("profile", prof)
    b.set("profile", prof)
    assert a.get("useownprofile") == 0.0
    a.set("useownprofile", 1)
    assert a.get("useownprofile") == 1.0
    own = a.get("profile")
    assert own is not prof and own.get("fontcolor") == [1, 2, 3]
    own.set("fontcolor", [9, 9, 9])      # the corpus `profile.fontColor =` shape
    assert prof.get("fontcolor") == [1, 2, 3]     # shared profile untouched
    assert b.get("profile") is prof               # sibling unaffected
    assert a.resolve_profile().fg == (9, 9, 9)
    a.set("useownprofile", 0)                     # destroys the copy, reverts
    assert a.get("profile") is prof
    # assigning a profile also drops an active own copy (setProfile,
    # GuiControl.cpp:1706-1709)
    a.set("useownprofile", 1)
    a.set("profile", prof)
    assert a.get("useownprofile") == 0.0


def test_copyfrom_copies_profiles_but_noops_on_controls():
    """The TGraalVar::copyFrom gate (TGraalVar.cpp:2208-2214): every
    Gui*Ctrl is engine-owned and silently no-ops; GuiControlProfile is the
    one GUI class whose table opts in (GuiControlProfileProperties.cpp:618)."""
    gui = ClientGS2().gui
    src = gui.create_control("GuiControlProfile", "SrcProf")
    src.set("fillcolor", [1, 2, 3, 4])
    gui.addcontrol(src)
    dst = gui.create_control("GuiControlProfile", "DstProf")
    gui.addcontrol(dst)
    dst.copy_from(src)
    assert dst._members.get("fillcolor") == [1, 2, 3, 4]
    assert dst._members["fillcolor"] is not src._members["fillcolor"]  # cloned
    ctrl = gui.create_control("GuiButtonCtrl", "CopyBtn")
    gui.addcontrol(ctrl)
    ctrl.copy_from(src)
    assert "fillcolor" not in ctrl._members       # silent no-op


def test_context_menu_profile_is_the_scroll_slot_and_textprofile_styles_rows():
    """`profile` and `scrollprofile` are pointer-identical accessors -- one
    slot, styling the frame -- while `textprofile` styles the rows
    (GuiContextMenuCtrlProperties.cpp:155-161, :44-64); the width setter
    clamps to >= 1 (:74-78)."""
    gui = ClientGS2().gui
    frame_prof = gui.create_control("GuiControlProfile", "CtxFrameProf")
    frame_prof.set("fontcolor", [10, 20, 30])
    gui.addcontrol(frame_prof)
    text_prof = gui.create_control("GuiControlProfile", "CtxTextProf")
    text_prof.set("fontcolor", [200, 100, 50])
    gui.addcontrol(text_prof)
    menu = gui.create_control("GuiContextMenuCtrl", "AliasMenu")
    gui.addcontrol(menu)
    menu.set("scrollprofile", frame_prof)
    assert menu.get("profile") is frame_prof       # one slot, both names
    menu.set("profile", text_prof)
    assert menu.get("scrollprofile") is text_prof
    menu.set("profile", frame_prof)
    menu.set("textprofile", text_prof)
    assert menu._row_profile().fg == (200, 100, 50)
    assert menu.resolve_profile().fg == (10, 20, 30)
    menu.set("width", -5)
    assert menu.width == 1.0


def test_drawing_panel_full_method_table_and_ro_props():
    """The 7 methods and 6 properties beyond the draw-op set already
    modelled (funcDefs/propDefs, GuiDrawingPanelProperties.cpp:183-207):
    drawcurve records, saveimage honours the sandbox gate (:152-157),
    the unrecovered-body entries answer typed no-ops, and the four RO
    part* fields drop writes."""
    gui = ClientGS2().gui
    panel = gui.create_control("GuiDrawingPanel", "CurvePanel")
    gui.addcontrol(panel)
    panel.get("drawcurve")(0, 0, 10, 0, 10, 10, 2)
    assert panel.draw_ops[-1][0] == "curve"
    panel.get("saveimage")("../../evil/path")       # gate: dropped
    assert panel.saved_images == {}
    panel.get("saveimage")("art/temp_sprite.png")   # basename + snapshot
    assert "temp_sprite.png" in panel.saved_images
    assert panel.get("drawobject")(0, 0, None) == 0.0
    assert panel.get("filterrectangle")(0, 0, 4, 4, "blur") == 0.0
    assert panel.get("maskimage")(0, 0, "a.png", "mode") == 0.0
    assert panel.get("setdrawpalette")("pal", 128) == 0.0
    assert panel.get("partx") == 0.0
    assert panel.get("availablefilters") == []      # typed, not Number 0.0
    panel.set("partx", 9)
    assert panel.get("partx") == 0.0                # nullptr setter
    panel.set("enablecache", 1)
    assert panel.has("enablecache")


def test_mobile_login_construction_props_are_claimed():
    """weapon-Mobile_Login writes these bare in construction blocks; an
    unclaimed name silently falls through to temps (GuiControlProperties.cpp
    :660 clipchildren, :662 cliptobounds, :696 useownprofile)."""
    gui = ClientGS2().gui
    ctrl = gui.create_control("GuiControl", "GR_LoginScreen")
    gui.addcontrol(ctrl)
    for name in ("useownprofile", "clipchildren", "cliptobounds"):
        assert ctrl.has(name), name


def test_canvas_resize_fires_graalcontrol_onresize_but_not_per_control():
    """Login hangs its chat-bar resize off the canvas's fixed name
    (`function GraalControl.onResize(newwidth, newheight)`,
    weapon-Rescripted_Serverlist.txt:2634) -- dispatched across the weapon
    VMs on canvas resize. Per-control onResize is deliberately NOT fired
    from the sizing sweep: the reference fires it from EVERY resize
    (GuiControl.cpp:2615-2618) including script writes, and firing Login's
    mutually-resizing Serverlist_*Window handlers from only one path
    live-collapsed Serverlist_Map (see _apply_sizing's comment)."""
    rt = ClientGS2()
    gui = rt.gui
    calls = []

    class _VM:
        def has_function(self, n):
            return n == "graalcontrol.onresize"

        def call(self, n, *a):
            calls.append((n, a))

    rt.vms["weapon"]["w"] = _VM()
    win = gui.create_control("GuiWindowCtrl", "ResizeWin")
    gui.addcontrol(win)
    win.set("horizsizing", "width")
    seen = []
    win.set("onresize", lambda *a: seen.append(a))
    gui.canvas_size = (800, 600)
    gui.on_canvas_resize(1000, 600)
    assert calls == [("graalcontrol.onresize", (1000.0, 600.0))]
    assert seen == []
