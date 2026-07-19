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
    GS2GuiManager, GuiButtonCtrl, GuiCheckBoxCtrl, GuiTextCtrl,
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
        self.edit.set("onaction", lambda: fired.append(True))
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
