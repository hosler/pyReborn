"""Host-surface gaps closed from the 2026-07-24 Login weapon corpus.

Evidence: every checked-in Login weapon (GServer-v2's GS2 compiler test
scripts, advanced/loginserver/*.gs2) compiled with gs2test and run event by
event against a real GS2ClientHost. The unanswered calls, by frequency:
gettextheight (732), getSelectedRow on a GuiPopUpMenuCtrl (45),
isFirstResponder (44), drawLine (40), md5 (25), the update-package counters
(41 across four names), the credential/URL/platform families, and per-node
tree-view styling.

Everything here is either REAL behaviour or an explicitly policy-inert stub
(the stub set itself is pinned in test_gs2_client_gap_surface.py).
"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

from types import SimpleNamespace

import pygame

from reborn_protocol.gs2 import GS2Object
import pyreborn.gs2_client as gs2_client_module
from pyreborn.gs2_client import ClientGS2, _ThisObject
from pyreborn.game.gs2_gui import (
    GuiAccountPasswordCtrl, GuiBitmapButtonCtrl, GuiControl, GuiDrawingPanel,
    GuiMLTextEditCtrl, GuiPopUpMenuCtrl, GuiProgressCtrl, GuiStartMenuCtrl,
    GuiTextListCtrl, GuiTreeViewCtrl, control_method_names, make_control,
)

pygame.init()
pygame.font.init()


class _FakeFonts:
    def get(self, role):
        return pygame.font.Font(None, 16)


def call(rt, name, args=(), obj=None, vm=None):
    return rt.host.call_builtin(vm, name, list(args), obj=obj)


def test_gettextheight_is_positive_and_scales_with_zoom():
    """ServerListScreen sizes labels with
    `extent = { w, gettextheight(scale, "friz", "b") }` -- 732 calls in one
    corpus pass. A zero answer collapsed those controls to no height."""
    rt = ClientGS2()
    single = call(rt, "gettextheight", [1, "friz", "b"])
    double = call(rt, "gettextheight", [2, "friz", ""])
    assert single > 0 and double > single


def test_gettextheight_uses_the_game_shell_font_metrics_when_present():
    rt = ClientGS2()
    font = pygame.font.Font(None, 24)
    rt.game_shell = SimpleNamespace(
        _showtext_font=lambda name, size, bold: font)
    assert call(rt, "gettextheight", [1, "friz", "b"]) == float(font.get_height())


def test_md5_matches_the_reference_digest():
    rt = ClientGS2()
    assert call(rt, "md5", ["abc"]) == "900150983cd24fb0d6963f7d28e17f72"
    assert call(rt, "md5", []) == "d41d8cd98f00b204e9800998ecf8427e"


def test_path_helpers_split_both_separators():
    rt = ClientGS2()
    for path in ("levels/sprites/icon.png", "levels\\sprites\\icon.png"):
        assert call(rt, "extractfilename", [path]) == "icon.png"
        assert call(rt, "extractfilebase", [path]) == "icon"
        assert call(rt, "extractfileext", [path]) == ".png"
    assert call(rt, "extractfilebase", ["readme"]) == "readme"
    assert call(rt, "extractfileext", ["readme"]) == ""


def test_fileexists_only_sees_content_this_client_holds():
    """Never a local-filesystem probe -- a server script must not be able to
    enumerate the user's disk."""
    rt = ClientGS2(SimpleNamespace(_received_files={"Icon.PNG": b"x"}))
    assert call(rt, "fileexists", ["icon.png"]) == 1.0
    assert call(rt, "fileexists", ["/etc/passwd"]) == 0.0
    assert call(rt, "fileexists", [""]) == 0.0


def test_fileexists_falls_back_to_the_sprite_cache():
    rt = ClientGS2(SimpleNamespace(_received_files={}))
    rt.game_shell = SimpleNamespace(sprite_mgr=SimpleNamespace(
        load_sheet=lambda name: object() if name == "skin.png" else None))
    assert call(rt, "fileexists", ["skin.png"]) == 1.0
    assert call(rt, "fileexists", ["missing.png"]) == 0.0


def test_pushdialog_and_popdialog_raise_and_hide_a_control():
    rt = ClientGS2()
    back = rt.gui.create_control("GuiControl", "back")
    rt.gui.addcontrol(back)
    dialog = rt.gui.create_control("GuiWindowCtrl", "dialog")
    rt.gui.addcontrol(dialog)
    dialog.visible = False
    call(rt, "pushdialog", ["dialog"])
    assert dialog.visible and rt.gui.roots[-1] is dialog
    call(rt, "popdialog", ["dialog"])
    assert not dialog.visible


def test_bringtofront_global_form_reorders_without_showing():
    rt = ClientGS2()
    first = rt.gui.create_control("GuiWindowCtrl", "first")
    rt.gui.addcontrol(first)
    second = rt.gui.create_control("GuiWindowCtrl", "second")
    rt.gui.addcontrol(second)
    first.visible = False
    call(rt, "bringtofront", ["first"])
    assert rt.gui.roots[-1] is first and first.visible is False


def test_isfullscreenmode_reports_the_real_window_state():
    rt = ClientGS2()
    assert call(rt, "isfullscreenmode") == 0.0
    rt.game_shell = SimpleNamespace(fullscreen=True)
    assert call(rt, "isfullscreenmode") == 1.0


def test_native_platform_queries_answer_inert_without_warning():
    """Login Mobile's -Adventure/-Mobile/Serverlist call these every session;
    they stay out of `stubbed` because server_crawl's KNOWN_UNSUPPORTED_CALLS
    is the registry that classifies them."""
    rt = ClientGS2()
    for name in ("getgamesubversion", "getpremiumoption", "fileupdate"):
        assert call(rt, name) == 0.0


def test_getplatform_answers_a_string_not_the_inert_zero():
    """getplatform() must NOT share the 0.0 group above: content compares it
    against platform tokens, and 0 == any non-numeric string under the
    machine's compare rules, so an inert 0.0 matched "android" (and every
    other token) and sent Login Mobile's -Adventure down the handset branch.
    Same value player.platform reports (reference TInitStatics.cpp:2796 and
    TPlayer.cpp:663 both read TIdentification::platformname)."""
    rt = ClientGS2()
    assert call(rt, "getplatform") == gs2_client_module.PLATFORM_NAME
    assert isinstance(call(rt, "getplatform"), str)
    # never a token that would impersonate a client we are not
    assert call(rt, "getplatform") not in (
        "android", "iphone", "bada", "flash", "linuxstream")


def test_string_case_methods_are_answered_by_the_host():
    """`.lower()`/`.upper()` are the string methods the compiler does not
    lower to an opcode (Login's staff sprite editor keys its default
    map on them)."""
    rt = ClientGS2()
    assert call(rt, "lower", obj="MiXeD") == "mixed"
    assert call(rt, "upper", obj="MiXeD") == "MIXED"


def test_method_call_on_a_weapon_name_string_runs_that_weapon(monkeypatch):
    """`("-Serverlist_Options").showOptions()` -- the reference engine's
    weapon-as-object form, which Login uses for -ScriptedRC and friends."""
    rt = ClientGS2()
    called = []
    vm = SimpleNamespace(
        name="weapon:-Serverlist_Options",
        has_function=lambda n: n == "showoptions",
        call=lambda n, *a: called.append((n, a)) or 7.0)
    rt.vms["weapon"]["-serverlist_options"] = vm
    assert call(rt, "showoptions", ["Help"], obj="-Serverlist_Options") == 7.0
    assert called == [("showoptions", ("Help",))]


def test_unloaded_weapon_name_falls_through_to_the_policy_stub():
    rt = ClientGS2()
    assert call(rt, "showoptions", [], obj="-Serverlist_Options") == 0.0


def test_foreign_this_object_exposes_the_scripts_public_functions():
    """`Gs2Utils = this;` in -ReShared's onCreated makes that weapon's
    this-object the shared utility API every other Login weapon calls
    (Gs2Utils.replaceAll / .destroyObject). Those reads land on a FOREIGN
    script's this-object, which the shared VM does not resolve for us --
    dropping this bridge cost 14 "unknown method replaceall()" per live
    Login Mobile session."""
    rt = ClientGS2()
    vm = _fake_vm(rt, key="-reshared", functions={"replaceall"})
    vm.script_function = (
        lambda n, _vm=vm: (lambda *a: _vm.call(n, *a))
        if _vm.has_function(n) else None)
    utils = _ThisObject(rt, ("weapon", "-reshared"), name="this")
    handler = utils.get("replaceAll")
    assert callable(handler)
    handler("a-b", "-", "+")
    assert vm.calls == [("replaceall", ("a-b", "-", "+"))]
    assert utils.get("nosuchfunction") is None


def test_dynamic_var_methods_walk_and_clear_object_members():
    rt = ClientGS2()
    cache = GS2Object(name="spritecache")
    cache.set("one", 1)
    cache.set("two", 2)
    cache._members["_private"] = 3      # engine bookkeeping stays hidden
    assert sorted(call(rt, "getdynamicvarnames", obj=cache)) == ["one", "two"]
    assert sorted(call(rt, "getvarnames", obj=cache)) == ["one", "two"]
    call(rt, "clearvars", obj=cache)
    assert cache.get("one") is None and cache._members == {"_private": 3}


def test_list_sortascending_and_sortdescending():
    """The shared VM implements sortbyvalue but not these two."""
    rt = ClientGS2()
    values = ["b", "C", "a"]
    assert call(rt, "sortascending", obj=values) == ["a", "b", "C"]
    assert call(rt, "sortdescending", obj=values) == ["C", "b", "a"]


#: every live scheduleevent call site spells it `this.scheduleevent(...)`,
#: so the host sees it as an object method on the script's own `this`
_THIS = GS2Object(name="this")


def _fake_vm(rt, key="w", functions=()):
    """A weapon VM stand-in whose iter_call records the fired event.

    ClientGS2._run drives handlers through vm.iter_call (the coroutine
    entry point), so the stub yields nothing and simply records."""
    vm = SimpleNamespace(
        name=f"weapon:{key}", _gs2_owner=("weapon", key),
        _gs2_kind="weapon", _gs2_key=key, functions=set(functions),
        has_function=lambda n, _f=set(functions): n.lower() in _f, calls=[])

    def iter_call(name, *args, _vm=vm):
        _vm.calls.append((name.lower(), args))
        return iter(())

    vm.iter_call = iter_call
    vm.call = lambda n, *a, _vm=vm: _vm.calls.append((n.lower(), a))
    rt.vms["weapon"][key] = vm
    return vm


def test_scheduleevent_fires_once_after_the_delay():
    rt = ClientGS2()
    vm = _fake_vm(rt, functions={"turnoffborder"})
    call(rt, "scheduleevent", [0.1, "TurnOffBorder", "arg"], obj=_THIS, vm=vm)
    rt.process_timeouts(0.05)
    assert vm.calls == []
    rt.process_timeouts(0.1)
    assert vm.calls == [("turnoffborder", ("arg",))]
    rt.process_timeouts(1.0)
    assert len(vm.calls) == 1          # one-shot, never re-arms


def test_cancelevents_drops_pending_arms_by_name():
    rt = ClientGS2()
    vm = _fake_vm(rt, functions={"a", "b"})
    call(rt, "scheduleevent", [0.1, "A"], obj=_THIS, vm=vm)
    call(rt, "scheduleevent", [0.1, "B"], obj=_THIS, vm=vm)
    call(rt, "cancelevents", ["A"], obj=_THIS, vm=vm)
    rt.process_timeouts(0.2)
    assert [name for name, _ in vm.calls] == ["b"]
    call(rt, "scheduleevent", [0.1, "A"], obj=_THIS, vm=vm)
    call(rt, "cancelevents", [], obj=_THIS, vm=vm)
    rt.process_timeouts(0.2)
    assert len(vm.calls) == 1


def test_scheduleevent_queue_is_capped():
    import pyreborn.gs2_client as mod
    rt = ClientGS2()
    vm = _fake_vm(rt, functions={"x"})
    for _ in range(mod.SCHEDULED_EVENT_CAP + 20):
        call(rt, "scheduleevent", [5, "X"], obj=_THIS, vm=vm)
    assert len(rt._scheduled) == mod.SCHEDULED_EVENT_CAP


def test_isfirstresponder_tracks_keyboard_focus():
    rt = ClientGS2()
    edit = rt.gui.create_control("GuiTextEditCtrl", "edit")
    rt.gui.addcontrol(edit)
    assert edit.get("isfirstresponder")() == 0.0
    rt.gui.focus(edit)
    assert edit.get("isfirstresponder")() == 1.0


def test_bringtofront_method_form_keeps_visibility():
    rt = ClientGS2()
    first = rt.gui.create_control("GuiWindowCtrl", "first")
    rt.gui.addcontrol(first)
    second = rt.gui.create_control("GuiWindowCtrl", "second")
    rt.gui.addcontrol(second)
    first.visible = False
    first.get("bringtofront")()
    assert rt.gui.roots[-1] is first and first.visible is False


def test_settext_setlines_and_getlines_round_trip():
    ctrl = GuiControl("c")
    ctrl.get("settext")("hello")
    assert ctrl.text == "hello" and ctrl.get("gettext")() == "hello"
    ctrl.get("setlines")(["a", "b"])
    assert ctrl.get("getlines")() == ["a", "b"]


def test_coordinate_transforms_are_inverses_through_the_parent_chain():
    rt = ClientGS2()
    parent = rt.gui.create_control("GuiControl", "parent")
    rt.gui.addcontrol(parent)
    child = rt.gui.create_control("GuiControl", "child")
    rt.gui.addcontrol(child)
    rt.gui.add_to(parent, child)
    parent.x, parent.y = 100.0, 40.0
    child.x, child.y = 10.0, 5.0
    assert child.get("localtoglobalcoord")([0, 0]) == [110.0, 45.0]
    assert child.get("globaltolocalcoord")([110, 45]) == [0.0, 0.0]
    assert child.get("localtoglobalcoord")(0, 0) == [110.0, 45.0]


def test_clearall_empties_rows_lists_and_tree_nodes():
    rt = ClientGS2()
    lst = GuiTextListCtrl("list")
    lst.get("addrow")(1, "one")
    lst.get("clearall")()
    assert lst.list_rows == []
    tree = rt.gui.create_control("GuiTreeViewCtrl", "tree")
    tree.get("addnodebypath")("Cat/Server", "/")
    tree.get("clearall")()
    assert tree.root_nodes == []


def test_text_list_selection_accessors():
    """getSelectedRow is the ROW NUMBER, getSelectedId the id.

    This used to assert getSelectedRow() == 12, the row's ID. The oracle
    disagrees: the binding reuses propfun_guitextlistctrl_selectedrow_r
    (FourPlay quattroplay/src/gui/GuiTextListCtrlProperties.cpp:423, body
    :156-159 = getSelectedCell().y), and the table carries a SEPARATE
    getselectedid entry (:421) for the id. With ids that are not their own
    row numbers -- exactly the case here -- feeding getSelectedRow() back
    into setSelectedRow(), which takes a row number, selected the wrong row.
    """
    lst = GuiTextListCtrl("list")
    lst.get("addrow")(11, "Global Chat")
    lst.get("addrow")(12, "Log")
    assert lst.get("getselectedrow")() == -1.0
    assert lst.get("getselectedid")() == -1.0
    lst.get("setselectedrow")(1)
    assert lst.get("getselectedrow")() == 1.0
    assert lst.get("getselectedid")() == 12
    assert lst.get("getselectedtext")() == "Log"


def test_popup_menu_ctrl_is_a_real_combo_box():
    """GuiPopUpMenuCtrl used to be an unknown class -> generic GuiControl,
    which answered neither getSelectedRow nor getSelectedText (45 misses)."""
    ctrl = make_control("GuiPopUpMenuCtrl", "Sprite_Direction_Popup")
    assert isinstance(ctrl, GuiPopUpMenuCtrl)
    ctrl.get("addrow")(3, "down")
    ctrl.get("addrow")(4, "left")
    ctrl.get("setselectedrow")(1)
    assert ctrl.get("getselectedrow")() == 4
    assert ctrl.get("getselectedtext")() == "left"
    ctrl.get("clearrows")()
    assert ctrl.get("getselectedrow")() == -1.0


def test_start_menu_open_anchors_above_the_given_point():
    rt = ClientGS2()
    menu = rt.gui.create_control("GuiStartMenuCtrl", "menu")
    rt.gui.addcontrol(menu)
    assert isinstance(menu, GuiStartMenuCtrl) and menu.visible is False
    menu.get("addrow")(0, "Global Chat")
    menu.get("addrow")(1, "Log")
    menu.get("open")([40, 300])
    assert menu.visible and menu.x == 40.0
    assert menu.y == 300.0 - menu.height


def test_login_corpus_control_classes_resolve_to_real_types():
    for classname, cls in (
            ("GuiAccountPasswordCtrl", GuiAccountPasswordCtrl),
            ("GuiMLTextEditCtrl", GuiMLTextEditCtrl),
            ("GuiProgressCtrl", GuiProgressCtrl),
            ("GuiBitmapButtonCtrl", GuiBitmapButtonCtrl),
            ("GuiPopUpMenuCtrl", GuiPopUpMenuCtrl),
            ("GuiDrawingPanel", GuiDrawingPanel)):
        ctrl = make_control(classname, "x")
        assert isinstance(ctrl, cls), classname
        assert ctrl.CTRL_CLASS == classname


def test_progress_ctrl_clamps_and_draws_a_partial_bar():
    ctrl = GuiProgressCtrl("DownloadProgress_Bar1")
    ctrl.set("progress", 0.5)
    assert ctrl.get("progress") == 0.5
    ctrl.set("progress", 4)
    assert ctrl.get("progress") == 1.0
    ctrl.set("progress", -2)
    assert ctrl.get("progress") == 0.0
    ctrl.width, ctrl.height = 40.0, 10.0
    ctrl.set("progress", 0.5)
    surf = pygame.Surface((60, 20))
    ctrl.draw(surf, _FakeFonts(), None)
    assert surf.get_at((5, 5)) != surf.get_at((35, 5))


def test_account_password_ctrl_never_renders_the_characters():
    ctrl = GuiAccountPasswordCtrl("gr_LoginScreen_PassEdit")
    ctrl.width, ctrl.height = 120.0, 20.0
    ctrl.text = "hunter2"
    plain = pygame.Surface((160, 30))
    ctrl.draw(plain, _FakeFonts(), None)
    assert ctrl.text == "hunter2"          # only the RENDER is masked
    masked = pygame.Surface((160, 30))
    other = GuiAccountPasswordCtrl("other")
    other.width, other.height = 120.0, 20.0
    other.text = "*******"
    other.draw(masked, _FakeFonts(), None)
    assert pygame.image.tostring(plain, "RGB") == \
        pygame.image.tostring(masked, "RGB")


def test_drawing_panel_records_and_replays_its_ops():
    panel = GuiDrawingPanel("Sprite_Guidelines_Drawing")
    panel.width, panel.height = 40.0, 40.0
    panel.get("drawline")(0, 20, 40, 20, 1)
    assert panel.draw_ops == [("line", 0.0, 20.0, 40.0, 20.0, 1.0)]
    surf = pygame.Surface((60, 60))
    panel.draw(surf, _FakeFonts(), None)
    assert surf.get_at((10, 20)) != surf.get_at((10, 5))
    panel.get("clearall")()
    assert panel.draw_ops == []


def test_drawing_panel_op_log_is_capped():
    panel = GuiDrawingPanel("panel")
    for _ in range(GuiDrawingPanel._MAX_OPS + 50):
        panel.get("drawline")(0, 0, 1, 1, 1)
    assert len(panel.draw_ops) == GuiDrawingPanel._MAX_OPS


def _serverlist_tree(rt):
    tree = rt.gui.create_control("GuiTreeViewCtrl", "Serverlist_ServerList")
    rt.gui.addcontrol(tree)
    tree.width, tree.height = 200.0, 80.0
    tree.get("addnodebypath")("Gold/Zodiac\t42", "/")
    return tree


def test_tree_node_level_is_one_based_depth():
    """Login's connect handler is gated on `node.level <= 1` to skip the
    category folders; an unanswered read made every row look like one."""
    rt = ClientGS2()
    tree = _serverlist_tree(rt)
    folder = tree.root_nodes[0]
    assert folder.get("level") == 1.0
    assert folder.child_nodes[0].get("level") == 2.0


def test_tree_node_addnode_builds_children():
    rt = ClientGS2()
    tree = rt.gui.create_control("GuiTreeViewCtrl", "tree")
    root = tree.get("addnode")("root")
    child = root.get("addnode")("child")
    assert tree.root_nodes == [root] and root.child_nodes == [child]
    assert child.get("level") == 2.0 and child.get("text") == "child"


def test_per_node_profile_paints_its_own_row_background():
    """`node.profile = IRC_TreeViewProfile2;` -- Login restyles its category
    folder rows; the renderer used to draw every row in the tree profile."""
    rt = ClientGS2()
    tree = _serverlist_tree(rt)
    profile = rt.gui.create_control("GuiTreeViewProfile", "IRC_TreeViewProfile2")
    profile.set("opaque", True)
    profile.set("fillcolor", [255, 0, 0, 255])
    folder = tree.root_nodes[0]

    before = pygame.Surface((220, 100))
    tree.draw(before, _FakeFonts(), None)
    folder.set("profile", profile)
    after = pygame.Surface((220, 100))
    tree.draw(after, _FakeFonts(), None)

    row = tree.row_height() // 2
    assert after.get_at((190, row))[:3] == (255, 0, 0)
    assert before.get_at((190, row))[:3] != (255, 0, 0)
    # only the styled row changes: the child row keeps the tree's own style
    child_row = tree.row_height() + tree.row_height() // 2
    assert after.get_at((190, child_row)) == before.get_at((190, child_row))


def test_unstyled_tree_still_uses_the_control_profile():
    rt = ClientGS2()
    tree = _serverlist_tree(rt)
    default = tree.resolve_profile()
    assert tree.node_profile(tree.root_nodes[0], default) is default


def test_addtext_appends_and_can_follow_the_tail():
    rt = ClientGS2()
    scroll = rt.gui.create_control("GuiScrollCtrl", "scroll")
    rt.gui.addcontrol(scroll)
    scroll.height = 20.0
    pane = rt.gui.create_control("GuiMLTextCtrl", "F2LogWindow_logtype_All")
    rt.gui.addcontrol(pane)
    rt.gui.add_to(scroll, pane)
    pane.height = 100.0
    pane.get("addtext")("first\n")
    assert pane.text == "first\n" and scroll.scroll_y == 0.0
    pane.get("addtext")("second\n", True)
    assert pane.text == "first\nsecond\n"
    assert scroll.scroll_y == scroll.max_scroll_y() > 0


def test_scrolltobottom_walks_up_to_the_enclosing_scroll_view():
    rt = ClientGS2()
    scroll = rt.gui.create_control("GuiScrollCtrl", "scroll")
    rt.gui.addcontrol(scroll)
    scroll.height = 30.0
    child = rt.gui.create_control("GuiTextCtrl", "child")
    rt.gui.addcontrol(child)
    rt.gui.add_to(scroll, child)
    child.height = 200.0
    child.get("scrolltobottom")()
    assert scroll.scroll_y == 170.0
    assert GuiControl("loose").get("scrolltobottom")() == 0.0


def test_scrolldelta_scrolls_by_amount_and_clamps():
    rt = ClientGS2()
    scroll = rt.gui.create_control("GuiScrollCtrl", "scroll")
    rt.gui.addcontrol(scroll)
    scroll.height = 30.0
    child = rt.gui.create_control("GuiTextCtrl", "child")
    rt.gui.addcontrol(child)
    rt.gui.add_to(scroll, child)
    child.height = 130.0
    scroll.get("scrolldelta")([0, 40])
    assert scroll.scroll_y == 40.0
    scroll.get("scrolldelta")([0, 500])
    assert scroll.scroll_y == scroll.max_scroll_y() == 100.0
    scroll.get("scrolldelta")([0, -500])
    assert scroll.scroll_y == 0.0


def test_setselection_makes_the_next_keystroke_replace_the_text():
    """`ChatBar.setSelection(0, ChatBar.text.length())` after a message
    recall -- the reference client replaces the whole selection on the next
    keystroke instead of appending to it."""
    rt = ClientGS2()
    edit = rt.gui.create_control("GuiTextEditCtrl", "ChatBar")
    rt.gui.addcontrol(edit)
    edit.text = "recalled"
    edit.get("setselection")(0, len(edit.text))
    assert edit.get("getselection")() == [0.0, 8.0]
    rt.gui.focus(edit)
    rt.gui.handle_event(pygame.event.Event(
        pygame.KEYDOWN, key=pygame.K_a, unicode="a"))
    assert edit.text == "a"
    rt.gui.handle_event(pygame.event.Event(
        pygame.KEYDOWN, key=pygame.K_b, unicode="b"))
    assert edit.text == "ab"


def test_setselection_clamps_out_of_range_ranges():
    edit = make_control("GuiTextEditCtrl", "edit")
    edit.text = "abc"
    edit.get("setselection")(9, -4)
    assert edit.get("getselection")() == [0.0, 3.0]
    assert edit.take_selection() and edit.text == ""


def test_backspace_deletes_a_whole_selection():
    rt = ClientGS2()
    edit = rt.gui.create_control("GuiTextEditCtrl", "edit")
    rt.gui.addcontrol(edit)
    edit.text = "abcdef"
    edit.get("setselection")(2, 5)
    rt.gui.focus(edit)
    rt.gui.handle_event(pygame.event.Event(
        pygame.KEYDOWN, key=pygame.K_BACKSPACE, unicode=""))
    assert edit.text == "abf"


def test_drawimagerectangle_records_and_blits_one_sheet_cell():
    panel = GuiDrawingPanel("panel")
    panel.width, panel.height = 40.0, 40.0
    panel.get("drawimagerectangle")(0, 0, "sheet.png", 16, 0, 16, 16)
    assert panel.draw_ops == [
        ("imagepart", 0.0, 0.0, "sheet.png", (16.0, 0.0, 16.0, 16.0))]
    sheet = pygame.Surface((32, 16))
    sheet.fill((0, 0, 0))
    sheet.fill((0, 0, 255), pygame.Rect(16, 0, 16, 16))
    sprites = SimpleNamespace(load_sheet=lambda name: sheet)
    surf = pygame.Surface((60, 60))
    panel.draw(surf, _FakeFonts(), sprites)
    assert surf.get_at((4, 4))[:3] == (0, 0, 255)


def test_openatmouse_anchors_to_the_last_pointer_position():
    rt = ClientGS2()
    menu = rt.gui.create_control("GuiTextListCtrl", "ItemMenu")
    rt.gui.addcontrol(menu)
    menu.visible = False
    assert rt.gui.last_mouse is None
    menu.get("openatmouse")()
    assert menu.visible and (menu.x, menu.y) == (0.0, 0.0)   # no pointer yet
    menu.visible = False
    rt.gui.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=(120, 80)))
    menu.get("openatmouse")()
    assert menu.visible and (menu.x, menu.y) == (120.0, 80.0)


def test_findobject_resolves_named_controls():
    rt = ClientGS2()
    panel = rt.gui.create_control("GuiWindowCtrl", "Serverlist_Panel")
    rt.gui.addcontrol(panel)
    assert call(rt, "findobject", ["Serverlist_Panel"]) is panel
    assert call(rt, "findobject", ["nope"]) == 0.0


def test_loadvars_round_trips_savevars_through_the_scoped_cache(tmp_path,
                                                                monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    rt = ClientGS2(SimpleNamespace(server_name="login"))
    this = GS2Object(name="this")
    vm = SimpleNamespace(this=this, name="weapon:w")
    this.set("nick", "hosler")
    this.set("count", 3)
    call(rt, "savevars", ["prefs.txt"], vm=vm)
    fresh = GS2Object(name="this")
    call(rt, "loadvars", ["prefs.txt"], vm=SimpleNamespace(this=fresh))
    assert fresh.get("nick") == "hosler" and fresh.get("count") == "3"


def test_loadvars_refuses_paths_outside_the_scoped_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    rt = ClientGS2(SimpleNamespace(server_name="login"))
    assert rt.load_lines("../../../../etc/passwd") == []
    assert rt.load_lines("") == []
    assert rt.load_lines("never-written.txt") == []


def test_loadvarsfromarray_populates_from_an_array():
    rt = ClientGS2()
    this = GS2Object(name="this")
    call(rt, "loadvarsfromarray", [["a=1", "b=two", "junk"]],
         vm=SimpleNamespace(this=this))
    assert this.get("a") == "1" and this.get("b") == "two"
    assert this.get("junk") is None


def test_renderer_and_input_platform_toggles_are_inert():
    rt = ClientGS2()
    for name in ("switchtodirectx", "adventure_setcheatwindows",
                 "adventure_getframetick", "adventure_invokekeyevent"):
        assert call(rt, name, [1]) == 0.0
    assert call(rt, "getiphonemodel") == ""


def test_host_surface_reports_control_subclass_methods():
    """host_surface() used to union GuiControl._METHOD_NAMES only, so every
    subclass method was reported as an unimplemented gap by the crawler."""
    from pyreborn.gs2_client import GS2ClientHost
    surface = {name.casefold() for name in GS2ClientHost.host_surface()}
    for name in ("addnodebypath", "getselectednode", "setselectedbyid",
                 "getselectedtext", "drawline", "open"):
        assert name in surface, name
    assert set(control_method_names()) >= set(GuiControl._METHOD_NAMES)
    assert "addnodebypath" in control_method_names()
    assert "addnodebypath" not in GuiControl._METHOD_NAMES
    assert isinstance(GuiTreeViewCtrl("t").get("addnodebypath"), object)
