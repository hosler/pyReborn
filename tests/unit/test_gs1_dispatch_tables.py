"""GS1ClientHost's dispatch registries (pyreborn/gs1_client.py).

`_dispatch` and `get_builtin` used to be flat if/elif chains (494 and 137
lines). These pin what the table-driven version has to keep:

* STAGE ORDER, for the five names that appear in two stages with different
  behaviour -- `destroy` (NPC vs weapon), `showimg`/`hideimg` (layer store vs
  embedder callback) and `setcharprop`/`setplayerprop` (a #P player gattrib vs
  an NPC appearance slot / the on_setplayerprop callback);
* the arg-count fall-throughs: a command called with too few arguments must
  stay a silent no-op, not raise and not half-apply;
* `statsoff` returning UNSET so the interpreter falls back to the plain flag
  lookup.
"""

import os
import sys
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pytest

from reborn_protocol.gs1.runtime import UNSET
from pyreborn.gs1_client import (
    NPC_ATTR, PLAYER_ATTR, ClientGS1, _GS1_BUILTINS, _GS1_LAYER_COMMANDS,
    _GS1_MAIN_COMMANDS, _GS1_NPC_BUILTINS, _GS1_NPC_COMMANDS,
    _GS1_NPC_TAIL_COMMANDS, _GS1_PLAYER_BUILTINS, _GS1_PRE_COMMANDS,
)

_TABLES = (_GS1_PLAYER_BUILTINS, _GS1_NPC_BUILTINS, _GS1_BUILTINS,
           _GS1_PRE_COMMANDS, _GS1_LAYER_COMMANDS, _GS1_NPC_COMMANDS,
           _GS1_MAIN_COMMANDS, _GS1_NPC_TAIL_COMMANDS)


@pytest.fixture
def rt():
    return ClientGS1(client=None)


def _npc_ctx(npc, npc_id=7):
    return SimpleNamespace(this_obj=npc, _npc_id=npc_id,
                           _prog_key=f"npc_{npc_id}", _is_weapon=False,
                           tokenize_tokens=[])


def _weapon_ctx(wname="-test"):
    return SimpleNamespace(this_obj=None, _npc_id=0,
                           _prog_key=f"weapon_{wname}", _is_weapon=True,
                           tokenize_tokens=[])


# --- registry structure -----------------------------------------------------

def test_every_registered_name_is_lowercase_and_callable():
    for table in _TABLES:
        for name, handler in table.items():
            assert name == name.lower(), name
            assert callable(handler), name


def test_builtin_handlers_do_not_shadow_the_attribute_tables():
    """PLAYER_ATTR / NPC_ATTR are read AFTER their stage's handlers, so an
    entry in both would be dead (the decorator enforces this at import; this
    states it as a fact of the design)."""
    assert not set(_GS1_PLAYER_BUILTINS) & set(PLAYER_ATTR)
    assert not set(_GS1_NPC_BUILTINS) & set(NPC_ATTR)


# --- stage order: destroy ---------------------------------------------------

def test_destroy_hides_an_npc_but_unloads_a_weapon(rt):
    npc = {}
    rt._host._dispatch("destroy", [], _npc_ctx(npc))
    assert npc["visible"] is False
    assert "imgs" not in npc

    ctx = _weapon_ctx()
    rt._progs[ctx._prog_key] = object()
    rt.scripts[ctx._prog_key] = "code"
    rt._host._dispatch("showimg", [3, "a.png", 1, 2], ctx)
    assert rt._weapon_imgs[ctx._prog_key]
    rt._host._dispatch("destroy", [], ctx)
    assert ctx._prog_key not in rt._progs
    assert ctx._prog_key not in rt.scripts
    assert ctx._prog_key not in rt._weapon_imgs


# --- stage order: showimg / hideimg -----------------------------------------

def test_showimg_prefers_the_layer_store_over_the_embedder_callback(rt):
    seen = []
    rt.on_showimg = lambda *a: seen.append(a)
    npc = {}
    rt._host._dispatch("showimg", [1, "sign.png", 4, 5], _npc_ctx(npc))
    assert npc["imgs"][1]["image"] == "sign.png"
    assert seen == []


def test_showimg_falls_back_to_the_callback_with_no_layer_store(rt):
    seen = []
    rt.on_showimg = lambda *a: seen.append(a)
    # an NPC script whose NPC is gone: _layer_store() returns None, so nothing
    # may be stored (a warp-orphaned script must not keep painting)
    ctx = SimpleNamespace(this_obj=None, _npc_id=3, _prog_key=None,
                          _is_weapon=False)
    rt._host._dispatch("showimg", [1, "sign.png", 4, 5], ctx)
    assert seen == [(1, "sign.png", 4.0, 5.0)]


# --- stage order: setcharprop / setplayerprop -------------------------------

def test_pcode_charprop_targets_the_player_other_codes_the_npc(rt):
    npc = {}
    ctx = _npc_ctx(npc)
    rt._host._dispatch("setcharprop", ["#P1", "open,join"], ctx)
    assert rt._player_props == {"P1": "open,join"}
    assert npc == {}

    rt._host._dispatch("setcharprop", ["#3", "head19.png"], ctx)
    assert npc["head_image"] == "head19.png"


def test_pcode_setplayerprop_never_reaches_the_callback(rt):
    seen = []
    rt.on_setplayerprop = lambda *a: seen.append(a)
    ctx = _npc_ctx({})
    rt._host._dispatch("setplayerprop", ["#P2", "x"], ctx)
    assert seen == []
    rt._host._dispatch("setplayerprop", ["#1", "sword3.png"], ctx)
    assert seen == [("#1", "sword3.png")]


# --- arg-count fall-through -------------------------------------------------

@pytest.mark.parametrize("name,args", [
    ("showimg", [1]),                       # needs >= 2
    ("showani", [1, 2]),                    # needs >= 3
    ("showtext", [1, 2, 3, "f", "s"]),      # needs 6
    ("showtext2", [1, 2, 3, 1, "f", "s"]),  # needs 7
    ("changeimgpart", [1, 2, 3, 4]),        # needs 5
    ("changeimgzoom", [1]),                 # needs 2
    ("showpoly", [1]),                      # needs 2
    ("hideimg", []),
    ("setshape", [1, 32]),                  # needs 3
    ("hitobjects", [1, 2]),                 # needs 3
])
def test_too_few_arguments_is_a_silent_noop(rt, name, args):
    npc = {}
    rt._host._dispatch(name, args, _npc_ctx(npc))
    assert npc.get("imgs") in (None, {})
    assert rt.shapes == {}


def test_changeimgcolors_with_too_few_args_is_swallowed_not_retried(rt):
    """The flat chain had a second, bodyless `changeimgcolors` arm for exactly
    this case -- it must NOT fall through to a later stage."""
    npc = {"imgs": {1: {}}}
    rt._host._dispatch("changeimgcolors", [1, 0.5], _npc_ctx(npc))
    assert "colors" not in npc["imgs"][1]
    rt._host._dispatch("changeimgcolors", [1, 1, 1, 1, 1], _npc_ctx(npc))
    assert npc["imgs"][1]["colors"] == (1.0, 1.0, 1.0, 1.0)


# --- the NOOP set and the NPC tail stage ------------------------------------

def test_noop_commands_are_swallowed(rt):
    # `callweapon` used to be in this set, which is what silently discarded
    # classic Bomber's tailor event; it is a real command now (see
    # test_gs1_tailor_callweapon.py).
    npc = {}
    for name in ("serverwarp", "sleep", "setcursor"):
        assert rt._host._dispatch(name, ["x"], _npc_ctx(npc)) is None
    assert npc == {}


def test_hide_show_move_are_the_last_stage(rt):
    npc = {"x": 10.0, "y": 20.0}
    ctx = _npc_ctx(npc)
    rt._host._dispatch("hide", [], ctx)
    assert npc["visible"] is False
    rt._host._dispatch("show", [], ctx)
    assert npc["visible"] is True
    rt._host._dispatch("move", [1.5, -2.0], ctx)
    assert (npc["x"], npc["y"]) == (11.5, 18.0)
    rt._host._dispatch("move", [1.5], ctx)          # too few: no-op
    assert (npc["x"], npc["y"]) == (11.5, 18.0)


# --- get_builtin ------------------------------------------------------------

def test_statsoff_only_claims_the_name_while_the_hud_is_hidden(rt):
    ctx = _npc_ctx({})
    assert rt._host.get_builtin("statsoff", [], ctx) is UNSET
    rt.stats_mask = 0
    assert rt._host.get_builtin("statsoff", [], ctx) is True


def test_npc_attribute_table_still_answers_after_the_handler_stage(rt):
    ctx = _npc_ctx({"x": 12.0, "gani": "idle"})
    assert rt._host.get_builtin("x", [], ctx) == 12.0
    assert rt._host.get_builtin("ani", [], ctx) == "idle"
    assert rt._host.get_builtin("visible", [], ctx) is True


def test_unknown_names_fall_through_to_the_flag_lookup(rt):
    assert rt._host.get_builtin("nosuchflag", [], _npc_ctx({})) is UNSET
