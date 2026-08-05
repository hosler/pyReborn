from types import SimpleNamespace

import pytest

from pyreborn.gs2_client import ClientGS2
from pyreborn.liftobjects import LIFT_SPRITES


def call(rt, name, args=()):
    return rt.host.call_builtin(None, name, list(args))


def test_array_string_and_math_globals():
    rt = ClientGS2()
    assert call(rt, "aindexof", [2, [1, 2, 2]]) == 1
    assert call(rt, "aindexof", [3, [1, 2]]) == -1
    assert call(rt, "getascii", [""]) == 0
    assert call(rt, "getascii", ["A"]) == 65
    assert call(rt, "escapestring", ["a'\\\"\nb"]) == "a\\'\\\\\\\"b"
    assert call(rt, "escapestringkeepnewline", ["a\nb"]) == "a\nb"
    assert call(rt, "randomstring", ["one,two,"]) == "one,two"
    assert call(rt, "strcmp", ["Alpha", "alpha"]) == 0
    assert call(rt, "arccos", [1]) == 0
    assert call(rt, "arcsin", [1]) == pytest.approx(1.5707963267948966)
    assert call(rt, "arccos", [2]) == 0


def test_carry_globals_read_player_wire_state():
    player = SimpleNamespace(carry_npc=0, carry_sprite=LIFT_SPRITES[0])
    rt = ClientGS2(SimpleNamespace(player=player))
    assert rt.host.get_object("carriesbush") is True
    assert rt.host.get_object("carriessign") is False
    player.carry_npc = 17
    assert rt.host.get_object("carriesnpc") is True


def test_class_load_queries_store_and_requests_without_joining():
    requested = []
    client = SimpleNamespace(
        gs2_bytecode={"class": {"AlreadyHere": b"bytecode"}},
        request_class_bytecode=lambda name: requested.append(name) or True,
    )
    rt = ClientGS2(client)
    assert call(rt, "isclassloaded", ["alreadyhere"]) == 1
    assert call(rt, "isclassloaded", ["missing"]) == 0
    assert call(rt, "loadclass", ["Missing"]) == 0
    assert requested == ["Missing"]
    assert rt._pending_joins == {}


def test_nearest_singular_and_admin_guild():
    client = SimpleNamespace(
        player=SimpleNamespace(x=0, y=0),
        players={7: SimpleNamespace(x=10, y=10)},
        staff_guilds=["Admin)"],
    )
    rt = ClientGS2(client)
    assert call(rt, "getnearestplayer", [10, 10]) == 1
    assert call(rt, "isadminguild", ["Admin"]) == 1
    assert call(rt, "isadminguild", ["Players"]) == 0
