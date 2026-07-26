"""GuiTextListCtrl's row API, plus the TGraalVar root methods it sits next to.

Semantics come from the reference client's binding tables, decompiled at
Preagonal/FourPlay/quattroplay/ -- primarily src/gui/GuiTextListCtrlProperties.
cpp (14 properties at :399-415, 30 methods at :416-448) and the control itself
at src/gui/GuiTextListCtrl.cpp.
"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from types import SimpleNamespace                                # noqa: E402

from reborn_protocol.gs2 import GS2Object                        # noqa: E402

from pyreborn.game.gs2_gui import (                              # noqa: E402
    GuiMLTextCtrl, GuiPopUpMenuCtrl, GuiTextListCtrl,
)
from pyreborn.gs2_client import ClientGS2                        # noqa: E402


def _list(*rows) -> GuiTextListCtrl:
    ctrl = GuiTextListCtrl("list")
    for row_id, text in rows:
        ctrl.get("addrow")(row_id, text)
    return ctrl


#: ids deliberately unequal to their row numbers -- the whole point of the
#: id/row-number split, and what the old getSelectedRow got wrong.
SAMPLE = ((11, "Global Chat"), (12, "Log"), (13, "Trades"))


# -- counts and lookups -------------------------------------------------------

def test_rowcount_and_id_row_number_conversion():
    """rowCount -> getNumEntries (GuiTextListCtrl.cpp:677-680);
    getRowNumById -> findEntryById, -1 on a miss (:664-676)."""
    ctrl = _list(*SAMPLE)
    assert ctrl.get("rowcount")() == 3.0
    assert ctrl.get("getrownumbyid")(12) == 1.0
    assert ctrl.get("getrownumbyid")(99) == -1.0
    assert _list().get("rowcount")() == 0.0


def test_findtext_gives_the_row_number_and_findtextid_the_id():
    """The pair is deliberately asymmetric: findText is findEntryByText's
    array position, findTextId composes getEntryId over it
    (GuiTextListCtrlProperties.cpp:224-237)."""
    ctrl = _list(*SAMPLE)
    assert ctrl.get("findtext")("Log") == 1.0
    assert ctrl.get("findtextid")("Log") == 12
    assert ctrl.get("findtext")("nope") == -1.0
    assert ctrl.get("findtextid")("nope") == -1.0


def test_row_at_point_uses_canvas_coordinates():
    """getCellAt globalToLocalCoord()s its argument, so the binding takes
    CANVAS coordinates (src/gui/GuiArrayCtrl.cpp:439-460)."""
    ctrl = _list(*SAMPLE)
    ctrl.x, ctrl.y, ctrl.width = 10.0, 20.0, 100.0
    ctrl.height = float(len(SAMPLE) * ctrl.ROW_H)
    y = 20.0 + ctrl.ROW_H + 2
    assert ctrl.get("getrowatpoint")(15, y) == 1.0
    assert ctrl.get("getrowidatpoint")(15, y) == 12
    assert ctrl.get("getrowatpoint")(500, 500) == -1.0
    assert ctrl.get("getrowidatpoint")(500, 500) == -1.0


# -- selection ----------------------------------------------------------------

def test_getselectedrow_is_the_row_number_and_getselectedid_the_id():
    """getselectedrow reuses propfun_guitextlistctrl_selectedrow_r
    (GuiTextListCtrlProperties.cpp:423, body :156-159 = getSelectedCell().y);
    getselectedid is the separate id binding (:421)."""
    ctrl = _list(*SAMPLE)
    ctrl.get("setselectedrow")(2)
    assert ctrl.get("getselectedrow")() == 2.0
    assert ctrl.get("getselectedid")() == 13
    assert ctrl.get("selectedrow") == 2.0
    assert ctrl.get("selectedid") == 13
    assert ctrl.get("selected") is ctrl.list_rows[2]


def test_selection_is_a_list_of_cells():
    """GuiArrayCtrl keeps every selected cell and getSelectedCell() is the
    FIRST of them (src/gui/GuiArrayCtrl.cpp:378-385) -- which is why
    isRowSelected and the getSelected*s pair exist."""
    ctrl = _list(*SAMPLE)
    ctrl.set("allowmultipleselections", 1)
    ctrl.get("setselectedrows")("0,2")
    assert ctrl.get("getselectedrows")() == [0.0, 2.0]
    assert ctrl.get("getselectedids")() == [11, 13]
    assert ctrl.get("isrowselected")(0) is True
    assert ctrl.get("isrowselected")(1) is False
    assert ctrl.get("isidselected")(13) is True
    assert ctrl.get("isidselected")(12) is False
    assert ctrl.get("getselectedrow")() == 0.0
    ctrl.get("clearselection")()
    assert ctrl.get("getselectedrows")() == []
    assert ctrl.get("getselectedid")() == -1.0


def test_multi_select_bindings_degrade_to_single_selection():
    """One token, or a control that does not allow multiple selections, is a
    plain select; an empty argument clears
    (GuiTextListCtrlProperties.cpp:344-376)."""
    ctrl = _list(*SAMPLE)
    ctrl.get("setselectedbyids")("13,11")     # multi off -> first token only
    assert ctrl.get("getselectedrows")() == [2.0]
    ctrl.set("allowmultipleselections", 1)
    ctrl.get("setselectedbyids")("13,11")
    assert ctrl.get("getselectedids")() == [13, 11]
    ctrl.get("setselectedrows")("")
    assert ctrl.get("getselectedrows")() == []


def test_setselectedbytext_ignores_a_miss():
    """The reference gates on `row >= 0` (:378-383), so a text that matches
    nothing leaves the previous selection alone rather than clearing it."""
    ctrl = _list(*SAMPLE)
    ctrl.get("setselectedbytext")("Trades")
    assert ctrl.get("getselectedrow")() == 2.0
    ctrl.get("setselectedbytext")("does not exist")
    assert ctrl.get("getselectedrow")() == 2.0


def test_setselectedbyid_uses_the_id_not_the_row_number():
    ctrl = _list(*SAMPLE)
    ctrl.get("setselectedbyid")(13)
    assert ctrl.get("getselectedrow")() == 2.0
    ctrl.get("setselectedbyid")(99)           # miss -> unchanged
    assert ctrl.get("getselectedrow")() == 2.0


# -- row mutation -------------------------------------------------------------

def test_insertrow_argument_order_and_selection_shift():
    """insertRow(index, id, text) forwards to insertEntry(id, text, index)
    (GuiTextListCtrlProperties.cpp:281-289), and every selected cell at or
    after the insert point shifts down (GuiTextListCtrl.cpp:561-566)."""
    ctrl = _list(*SAMPLE)
    ctrl.get("setselectedrow")(1)
    row = ctrl.get("insertrow")(0, 99, "Top")
    assert row.get("id") == 99 and row.get("text") == "Top"
    assert [r.get("text") for r in ctrl.list_rows][0] == "Top"
    assert ctrl.get("getselectedrow")() == 2.0
    assert ctrl.get("getselectedid")() == 12
    ctrl.get("insertrow")(500, 77, "Past the end")   # appends
    assert ctrl.list_rows[-1].get("id") == 77


def test_removerow_repairs_the_selection():
    """removeEntryByIndex drops the removed row's selected cell and shifts
    the later ones down (GuiTextListCtrl.cpp:868-894)."""
    ctrl = _list(*SAMPLE)
    ctrl.set("allowmultipleselections", 1)
    ctrl.get("setselectedrows")("0,2")
    ctrl.get("removerow")(0)
    assert ctrl.get("rowcount")() == 2.0
    assert ctrl.get("getselectedrows")() == [1.0]
    assert ctrl.get("getselectedids")() == [13]
    ctrl.get("removerowbyid")(13)
    assert ctrl.get("getselectedrows")() == []
    ctrl.get("removerow")(42)                 # out of range -> no-op
    assert ctrl.get("rowcount")() == 1.0


def test_setrowbyid_adds_a_missing_row():
    """setEntry falls through to addEntry when no row has that id
    (GuiTextListCtrl.cpp:897-903) -- counter-intuitive, but RC-style lists
    build themselves entirely out of setRowById."""
    ctrl = _list(*SAMPLE)
    ctrl.get("setrowbyid")(12, "Log (2)")
    assert ctrl.list_rows[1].get("text") == "Log (2)"
    ctrl.get("setrowbyid")(50, "Brand new")
    assert ctrl.get("rowcount")() == 4.0
    assert ctrl.get("getrownumbyid")(50) == 3.0


def test_sort_enum_properties_answer_and_validate():
    """sortorder/groupsortorder/sortmode are string enums whose writers only
    accept a member by name or index (GuiTextListCtrlProperties.cpp:9-19,
    :117-122). Being string-typed they must answer even when unset."""
    ctrl = _list(*SAMPLE)
    assert ctrl.get("sortmode") == ""
    assert ctrl.get("sortorder") == "sortascending"
    assert ctrl.get("groupsortorder") == "sortascending"
    ctrl.set("sortorder", "sortdescending")
    assert ctrl.get("sortorder") == "sortdescending"
    ctrl.set("sortorder", "nonsense")         # ignored, not stored
    assert ctrl.get("sortorder") == "sortdescending"
    ctrl.set("sortmode", 2)                   # by index
    assert ctrl.get("sortmode") == "lexical"


# -- neighbouring cluster -----------------------------------------------------

def test_resize_is_on_every_control():
    """resize(x, y, w, h) -- GuiControlProperties.cpp:883, body :806-811."""
    ctrl = _list()
    ctrl.get("resize")(5, 6, 70, 80)
    assert (ctrl.x, ctrl.y, ctrl.width, ctrl.height) == (5.0, 6.0, 70.0, 80.0)


def test_reflow_lives_on_the_ml_text_control():
    """reflow() is registered on GuiMLTextCtrl, NOT on the text list
    (GuiMLTextCtrlProperties.cpp:334)."""
    ml = GuiMLTextCtrl("log")
    ml.set("text", "hello")
    ml._paragraphs()
    assert ml._ml_cache_key == "hello"
    ml.get("reflow")()
    assert ml._ml_cache_key is None
    assert "reflow" not in GuiTextListCtrl._METHOD_NAMES


def test_popup_menu_has_its_own_rowcount_and_setselectedbytext():
    """GuiPopUpMenuCtrl's chain is GuiPopUpMenuCtrl -> GuiTextCtrl, so it
    inherits nothing from the text list and carries its own bindings
    (GuiPopUpMenuCtrlProperties.cpp:73, :75)."""
    ctrl = GuiPopUpMenuCtrl("combo")
    ctrl.get("addrow")(3, "down")
    ctrl.get("addrow")(4, "left")
    assert ctrl.get("rowcount")() == 2.0
    ctrl.get("setselectedbytext")("left")
    assert ctrl.get("getselectedtext")() == "left"
    ctrl.get("setselectedbytext")("missing")
    assert ctrl.get("getselectedtext")() == "left"


# -- TGraalVar root methods (host-side gating) --------------------------------

def _runtime(tmp_path=None):
    return ClientGS2(SimpleNamespace(server_name="root-methods"))


def test_root_methods_answer_on_a_plain_object(tmp_path, monkeypatch):
    """savelines/sortascending/sortdescending/settimer are registered on
    TGraalVar, i.e. on EVERY object (quattroplay/src/TGraalVarProperties.cpp:
    494, :557, :566, :548). The host is consulted before the VM, so an
    array-only gate here made `this.savelines(...)` answer 0.0 no matter what
    the VM's own root surface did."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    rt = _runtime()
    obj = GS2Object(name="this")
    call = rt.host.call_builtin
    assert call(None, "savelines", ["notes.txt", 0], obj=obj) == 0.0
    assert call(None, "sortascending", [], obj=obj) == 0.0
    assert call(None, "sortdescending", [], obj=obj) == 0.0
    # an object with no array cells has nothing to write
    assert not list(tmp_path.rglob("notes.txt"))


def test_root_methods_still_do_the_work_on_an_array(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    rt = _runtime()
    values = ["z", "A", "b"]
    sorted_back = rt.host.call_builtin(None, "sortascending", [], obj=values)
    assert sorted_back == values
    assert values == ["A", "b", "z"]
    rt.host.call_builtin(None, "sortdescending", [], obj=values)
    assert values == ["z", "b", "A"]
    rt.host.call_builtin(None, "savelines", ["notes.txt", 0], obj=values)
    files = list(tmp_path.rglob("notes.txt"))
    assert len(files) == 1 and files[0].read_text() == "z\nb\nA"


def test_settimer_answers_in_the_object_form():
    """this.settimer(1) is a valid official spelling
    (src/TGraalVarProperties.cpp:548); it used to live only in the bare
    table."""
    rt = _runtime()
    vm = SimpleNamespace(_gs2_owner=("weapon", "-test"),
                         name="-test")
    rt.host.call_builtin(vm, "settimer", [2.5], obj=GS2Object(name="this"))
    assert rt._timeouts[("weapon", "-test")] == 2.5
