"""Host surface closed from the 2026-07-24 static call-site census.

Every name here was confirmed missing at RUNTIME first (the census source
was compiled with the real gs2test compiler and run against a live
GS2ClientHost until it showed up in GS2VM.builtins_missing), then shaped
from the reference client's binding tables in Preagonal/FourPlay
(quattroplay/src). Names the census listed that turned out NOT to be host
gaps are pinned at the bottom so a later round doesn't chase them again.
"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import math
from types import SimpleNamespace

import pygame

from reborn_protocol.gs2 import GS2Object, NOT_HANDLED

from pyreborn.gs1_client import ClientGS1
from pyreborn.gs2_client import ClientGS2, GS2ClientHost
from pyreborn.game.gs2_gui import (
    GuiPopUpMenuCtrl, GuiTextEditCtrl, GuiTextListCtrl, GuiTreeViewCtrl,
)

pygame.init()


def call(rt, name, args=(), obj=None, vm=None):
    return rt.host.call_builtin(vm, name, list(args), obj=obj)


def _client(**over):
    base = dict(
        player=SimpleNamespace(x=30.0, y=30.0, account="me", nickname="Me (Team)",
                               id=1, direction=2, gani="idle", colors=[1, 2, 3, 4, 5],
                               gattribs={}),
        players={2: {"x": 31.0, "y": 30.0, "account": "near", "nickname": "Near (Foes)",
                     "gattrib3": "carried", "colors": [9, 8, 7, 6, 5]}},
        x=30.0, y=30.0, npcs={}, weapons={}, server_name="probe",
        connected=False, _current_level_name="a.nw", tiles=[0] * 4096)
    base.update(over)
    return SimpleNamespace(**base)


def _rt(**over):
    client = _client(**over)
    return ClientGS2(client, ClientGS1(client))


def test_contains_requires_word_borders_on_both_sides():
    """TInitStatics.cpp:1962-1990 walks matches and accepts one only when it
    is bounded by TStringConstants::wordborder (vars24, :283) or by the ends
    of the string, case-insensitively. GServer-v2/bin/servers/era/scripts/
    weapongun.txt:236 uses the GS1 builtin
    strcontains(#s(this.weapon_opposite),Dual), so it is not evidence for GS2
    contains() word-boundary behaviour. GServer-v2/bin/servers/era/weapons/
    weapon%045Commands.txt:1185 uses contains(player.level.name, "mall")."""
    rt = _rt()
    assert call(rt, "contains", ["hello world", "world"]) is True
    assert call(rt, "contains", ["era_mall-01.nw", "mall"]) is True
    assert call(rt, "contains", ["Dual Pistols", "dual"]) is True     # case-insensitive
    assert call(rt, "contains", ["smallroom", "mall"]) is False       # no left border
    assert call(rt, "contains", ["mallet", "mall"]) is False          # no right border
    assert call(rt, "contains", ["a mall", "mall"]) is True           # ends the string
    assert call(rt, "contains", ["anything", ""]) is False            # empty needle


def test_contains_keeps_scanning_past_a_rejected_match():
    rt = _rt()
    assert call(rt, "contains", ["smallroom the mall", "mall"]) is True


def test_degtorad_and_radtodeg_round_trip():
    """TInitStatics.cpp:1999/2004, bindings :2289-2290 `{'d', "d"}`."""
    rt = _rt()
    assert call(rt, "degtorad", [180]) == math.pi
    assert call(rt, "degtorad", [0]) == 0.0
    assert abs(call(rt, "radtodeg", [math.pi]) - 180.0) < 1e-9


def test_findplayer_returns_the_same_objects_identity_comparisons_expect():
    """Reference TInitStatics.cpp:2127 (binding :2301 `{'o', "s"}`) checks
    the local player's account first, then the other players. Zelda compares
    the result's .account against player.account, so the local hit must be
    the very object `player` resolves to."""
    rt = _rt()
    assert call(rt, "findplayer", ["me"]) is rt.player_object
    near = call(rt, "findplayer", ["near"])
    assert near.get("account") == "near"
    # stable per id: the same object findnearestplayers hands out
    assert call(rt, "findplayer", ["near"]) is near
    assert near in call(rt, "findnearestplayers", [31.0, 30.0])
    assert call(rt, "findplayer", ["NEAR"]) is near        # case-insensitive
    assert call(rt, "findplayer", ["nobody"]) == 0.0
    assert call(rt, "findplayer", []) == 0.0


def test_findplayer_accepts_a_player_object_the_way_zelda_calls_it():
    """graal-lttp weapon-Player_Movement.txt:91 does
    `findplayer(players[pls[i]])` -- the argument is an OBJECT, resolved
    through its account member rather than stringified into a repr."""
    rt = _rt()
    players = rt.player_list_objects()
    assert call(rt, "findplayer", [players[1]]).get("account") == "near"


def test_objecttype_reports_the_control_class():
    """TGraalVarProperties.cpp:475-483 `{'s', ""}`. Login filters its taskbar
    with `temp.button.objecttype() != "GuiButtonCtrl"`."""
    rt = _rt()
    button = rt.gui.create_control("GuiButtonCtrl", "b")
    assert call(rt, "objecttype", obj=button) == "GuiButtonCtrl"
    assert call(rt, "objecttype", obj=rt.gui.create_control("GuiWindowCtrl", "w")) \
        == "GuiWindowCtrl"
    # a plain `new Foo()` object is named after its classname
    assert call(rt, "objecttype", obj=GS2Object(name="Foo")) == "Foo"


def test_cursor_visibility_toggles_are_real():
    """GuiCanvas.cpp:47-63, bindings :83-85. Login's serverlist calls
    cursorOn() when it takes over the screen; nothing in any corpus calls
    cursorOff, so in practice this only ever confirms the pointer visible."""
    rt = _rt()
    assert rt.gui.cursor_on is True
    call(rt, "cursoroff")
    assert rt.gui.cursor_on is False and call(rt, "iscursoron") == 0.0
    call(rt, "cursoron")
    assert rt.gui.cursor_on is True and call(rt, "iscursoron") == 1.0


def test_imgwidth_is_the_legacy_spelling_of_getimgwidth():
    """v6's table has only the get* pair (TInitStatics.cpp:2297-2298);
    imgwidth/imgheight are in reborn_protocol.gs1's FUNCTIONS table, so both
    engines answer them from one implementation here."""
    sizes = {"x.png": (24, 48)}
    rt = _rt()
    rt.image_size = sizes.get
    assert call(rt, "imgwidth", ["x.png"]) == 24.0
    assert call(rt, "imgheight", ["x.png"]) == 48.0
    assert call(rt, "getimgwidth", ["x.png"]) == 24.0
    assert call(rt, "imgwidth", ["missing.png"]) == 0.0


def test_keycode_shares_the_gs1_engine_keymap():
    rt = _rt()
    assert call(rt, "keycode", ["f"]) == float(ord("F"))
    assert call(rt, "keycode", [" "]) == 0x20
    assert call(rt, "keycode", [""]) == 0.0


def test_onwater_reaches_the_shared_tile_test():
    """TInitStatics.cpp:4240 `{'b', "dd"}` -> TServerLevel::isOnWater.
    Zelda's movement weapon gates its swim branch on it."""
    rt = _rt()
    seen = []
    rt.gs1.is_water_at = lambda x, y: seen.append((x, y)) or (x == 3)
    assert call(rt, "onwater", [3, 4]) is True
    assert call(rt, "onwater", [5, 6]) is False
    assert seen == [(3, 4), (5, 6)]


def test_text_control_isempty_answers_the_login_autologin_gate():
    """`if (!PassEdit.isEmpty()) doLogin();` -- unanswered it returned 0.0,
    i.e. "not empty", which took the auto-login branch. pyReborn never lets a
    script fill a password field, so the field IS empty."""
    edit = GuiTextEditCtrl("PassEdit")
    assert edit.get("isempty")() is True
    edit.set("text", "hunter2")
    assert edit.get("isempty")() is False


def test_list_findtext_returns_the_row_index_not_the_id():
    """GuiTextListCtrlProperties.cpp:420 -> findEntryByText, which returns
    the array position (GuiTextListCtrl.cpp:747-758); findTextId is the
    separate binding that maps it to an id."""
    lst = GuiTextListCtrl("l")
    lst.get("addrow")(70, "Admins")
    lst.get("addrow")(71, "Players")
    assert lst.get("findtext")("Players") == 1.0
    assert lst.get("findtext")("nobody") == -1.0


def test_popup_findtext_and_setselected_use_the_reference_argument_kinds():
    """setSelected takes a row ID (GuiPopUpMenuCtrl.cpp:316-327 resolves it
    with findEntryById), findText returns an INDEX."""
    menu = GuiPopUpMenuCtrl("m")
    menu.add_row(5, "five")
    menu.add_row(9, "nine")
    assert menu.get("findtext")("nine") == 1.0
    assert menu.get("findtext")("none") == -1.0
    menu.get("setselected")(9)
    assert menu.get_selected_row() == 9
    assert menu.text == "nine"


def test_every_new_name_is_on_the_reported_host_surface():
    """host_surface() is what the crawler diffs gaps against, so a builtin
    that works but isn't listed still reads as a gap."""
    surface = GS2ClientHost.host_surface()
    for name in ("contains", "degtorad", "radtodeg", "findplayer", "objecttype",
                 "cursoron", "cursoroff", "iscursoron", "keycode",
                 "imgwidth", "imgheight", "onwater", "onwater2",
                 "isempty", "findtext", "setselected",
                 "getandroiddevicemodel"):
        assert name in surface, name


def test_array_remove_insert_delete_are_opcodes_not_builtins():
    """The census counted `arr.remove(x)` / `.insert(i,v)` / `.delete(i)` as
    unimplemented names, but the compiler lowers them to OP_OBJ_REMOVESTRING
    / OP_OBJ_INSERTSTRING / OP_OBJ_DELETESTRING (verified by compiling them
    with gs2test) and the VM implements all three -- they never reach the
    host at all. The host must keep NOT claiming them, or it would shadow
    the VM's own array semantics."""
    rt = _rt()
    for name in ("remove", "insert", "delete"):
        assert call(rt, name, [0], obj=[1, 2, 3]) is NOT_HANDLED


def test_tree_node_select_is_already_a_node_method():
    tree = GuiTreeViewCtrl("t")
    tree.get("addnodebypath")("Folder/Leaf", "/")
    node = tree.get("nodes")[0]
    node.get("select")()
    assert tree.selected_node is node


# --- 2026-07-26 mobile Login corpus round -----------------------------------

def test_localization_wrapper_is_identity():
    """`text = _(temp.text);` (weapon-Mobile_Login.txt:176) -- the mobile
    client's localization lookup, absent from FourPlay and not script-
    defined anywhere; identity is the default-language behaviour. Unanswered
    it read Number 0.0 on every wrapped label."""
    rt = _rt()
    assert call(rt, "_", ["Account:"]) == "Account:"
    assert call(rt, "_", [12.5]) == "12.5"
    assert call(rt, "_", []) == ""


def test_char_is_chr_with_out_of_range_answering_empty():
    """char(33) builds a key suffix in weapon-LoginScreen.txt:341."""
    rt = _rt()
    assert call(rt, "char", [33]) == "!"
    assert call(rt, "char", [65]) == "A"
    assert call(rt, "char", [-1]) == ""
    assert call(rt, "char", [0x110000]) == ""


def test_des_decrypt_is_policy_inert_like_des_encrypt():
    """The mobile saveCredentials/getSavedPassword pair (weapon-
    Mobile_Login.txt:325-336) round-trips credentials through DES on a
    cache file; BOTH endpoints must be inert stubs -- this client never
    derives or recovers credential material for a script."""
    rt = _rt()
    assert call(rt, "des_decrypt", ["key", "blob"]) == 0.0
    assert call(rt, "des_encrypt", ["key", "secret"]) == 0.0
    assert call(rt, "initializeiphonedisplay", []) == 0.0
    surface = GS2ClientHost.host_surface()
    for name in ("_", "char", "des_decrypt", "initializeiphonedisplay"):
        assert name in surface, name
