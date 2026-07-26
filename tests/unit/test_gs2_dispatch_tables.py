"""GS2ClientHost's dispatch registries (pyreborn/gs2_client.py).

`call_builtin` and `get_object` used to be flat if/elif chains (871 and 148
lines). These pin the properties the table-driven version has to keep:

* the STAGE ORDER, for the names that appear in more than one table with
  different behaviour (`stubbed`, `getchild`/`setactive`, `destroy`);
* the fall-through/catch-all answers (_EngineObject inert 0.0 vs GS2Object
  NOT_HANDLED), so a bad arg count still answers exactly as before;
* that host_surface() -- which game_tester/server_crawl.py uses to decide
  what this client supports -- is the registries' key set.

The `sort` case additionally pins the 2026-07-25 case-folding fix: the sort key
is GS2's ASCII-only fold (reborn_protocol.gs2.values.casefold), not Python's
str.casefold().
"""

import os
import sys
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pytest

from reborn_protocol.gs2 import GS2Object, NOT_HANDLED
from pyreborn.gs1_client import ClientGS1
from pyreborn.gs2_client import (
    _FALL_THROUGH, _GS2_BARE, _GS2_OBJECTS, _GS2_TABLES, ClientGS2,
    GS2ClientHost, _engine_object,
)


@pytest.fixture
def host():
    rt1 = ClientGS1(client=None)
    return ClientGS2(client=None, gs1=rt1).host


# --- registry structure -----------------------------------------------------

def test_every_registered_name_is_lowercase_and_callable():
    for table in _GS2_TABLES + (_GS2_OBJECTS,):
        for name, handler in table.items():
            assert name == name.lower(), name
            assert callable(handler), name


def test_host_surface_is_the_registry_key_set():
    surface = GS2ClientHost.host_surface()
    for table in _GS2_TABLES:
        assert set(table) <= surface
    assert GS2ClientHost.stubbed <= surface
    # spot-check names from each dispatch stage
    for name in ("catchevent", "objecttype", "sortascending", "lowercase",
                 "addcontrol", "getcallstack", "gettextheight", "findweapon"):
        assert name in surface


# --- stage order: `stubbed` answers differently per call form ---------------

def test_stubbed_patcher_values_only_apply_to_the_bare_form(host):
    """The obj-method stage returns a flat 0.0; the bare stage consults
    _PATCHER_STUB_VALUES (IRC_Installer's progress loop needs the 1.0)."""
    assert host.call_builtin(None, "getpackagesdownloadcomplete", []) == 1.0
    assert host.call_builtin(None, "getpackagesdownloadcomplete", [],
                             GS2Object()) == 0.0
    assert host.call_builtin(None, "getdownloadingpackage", []) == ""


# --- stage order: the _EngineObject stage precedes the GUI stage ------------

def test_engine_object_methods_win_over_the_gui_stage(host):
    obj = _engine_object(host.rt2, "worldsf")
    child = host.call_builtin(None, "getchild", [0.0], obj)
    assert isinstance(child, GS2Object)
    # the same object, every call -- the C# client's Find/GetChild chains only
    # need stable non-null traversal
    assert host.call_builtin(None, "getchild", [0.0], obj) is child
    host.call_builtin(None, "setactive", [1.0], obj)
    assert obj.get("active") == 1.0


def test_unknown_engine_object_method_is_inert_but_unknown_gs2object_is_not(host):
    """Two different catch-alls, and the distinction is load-bearing: the VM
    implements list/string methods natively and only gets the chance when the
    host answers NOT_HANDLED."""
    assert host.call_builtin(None, "nosuchmethod", [],
                             _engine_object(host.rt2, "worldsf")) == 0.0
    assert host.call_builtin(None, "nosuchmethod", [],
                             GS2Object()) is NOT_HANDLED


def test_native_list_methods_are_left_to_the_vm(host):
    for name in ("add", "addarray", "size", "index", "sortbyvalue"):
        assert host.call_builtin(None, name, [], [1.0, 2.0]) is NOT_HANDLED


# --- _GS2_ANY: answered for both call forms ---------------------------------

def test_objecttype_answers_bare_and_as_a_method(host):
    vm = SimpleNamespace(this=GS2Object(name="-Weapon"))
    assert host.call_builtin(vm, "objecttype", []) == "-Weapon"
    assert host.call_builtin(None, "objecttype", [],
                             GS2Object(name="Panel")) == "Panel"


# --- coercion: the sort key uses GS2's ASCII-only case fold ------------------

def test_sort_uses_ascii_only_case_folding(host):
    """str.casefold() maps 'ß' onto 'ss', which would make these two elements
    compare EQUAL and leave the list untouched. C strcasecmp does not."""
    values = ["ß", "ss"]
    assert host.call_builtin(None, "sort", [], values) == ["ss", "ß"]
    assert sorted(["ß", "ss"], key=lambda v: v.casefold()) == ["ß", "ss"]


def test_sort_still_folds_ascii(host):
    values = ["b", "A", "c"]
    assert host.call_builtin(None, "sortascending", [], values) == ["A", "b", "c"]
    assert host.call_builtin(None, "sortdescending", [], values) == ["c", "b", "A"]


# --- get_object -------------------------------------------------------------

def test_get_object_registry_answers_engine_globals(host):
    assert host.get_object("ALLSTATS") == 2047.0          # case-insensitive
    assert host.get_object("serverstartconnect") == ""     # a STRING, not 0.0
    assert isinstance(host.get_object("guicontainer"), GS2Object)
    assert host.get_object("nosuchglobalanywhere") is None


def test_get_object_viewport_parents_under_the_canvas(host):
    viewport = host.get_object("graalcontrol")
    assert viewport.get("parent") is host.get_object("guicontainer")


# --- no sentinel ever escapes ----------------------------------------------

@pytest.mark.parametrize("name", sorted(_GS2_BARE))
def test_bare_handlers_never_leak_the_fallthrough_sentinel(host, name):
    """Every bare builtin is reachable with no arguments (scripts do call them
    that way) and must answer with a value, not the internal sentinel."""
    vm = SimpleNamespace(name="-test", this=GS2Object(name="-test"))
    assert host.call_builtin(vm, name, []) is not _FALL_THROUGH
