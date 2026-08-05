"""`clientr.<registered player property>` is the ENGINE property, not a flag.

Reference chain: `client`/`clientr`/`serverr` resolve to the EXECUTING PLAYER
(quattroplay/src/TScriptMachine.cpp:5123-5130), and member resolution consults
the class property tables BEFORE attached flag storage (TGraalVar::getProperty,
quattroplay/src/TGraalVar.cpp:1682-1705). So a name registered in
TPlayerProperties.cpp / TServerPlayerProperties.cpp / TGaniObjectProperties.cpp
NEVER reads or writes a flag through those scopes.

The live bug this pins (LTTP, hastur.eevul.net:14912, 2026-08-05): the server's
own -Player/Functions writes `clientr.freezetime = -1` at login (observed as
the outbound `modifyclientr,...,freezetime,-1` echo). Under flag-first
resolution that left a literal -1 flag which shadowed the live freeze counter,
so -Player/Movement's `clientr.freezetime == -1` DoMovement gate
(bytecode instrs #1828-1834) stayed true during DoSword's freezeplayer(0.6)
and the player kept walking through the whole sword swing.

freezetime semantics oracle: propfun_player_freezetime_r/w
(quattroplay/src/TPlayerProperties.cpp:11-37) -- reads are >= 0 while frozen
and exactly -1 when not.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                '../../../reborn-protocol'))

from reborn_protocol.gs2 import to_num

from pyreborn import Client
from pyreborn.gs1_client import ClientGS1
from pyreborn.gs2_client import ClientGS2


def _rt():
    client = Client("localhost", 14900)
    client.player.account = "local"
    gs1 = ClientGS1(client)
    rt = ClientGS2(client, gs1)
    return client, gs1, rt


class TestClientrFreezetimeIsTheEngineCounter:
    def test_gs1_property_write_is_visible_to_gs2(self):
        client, gs1, rt = _rt()
        gs1.load_weapon("-probe", "if (ping) { clientr.freezetime = 2; clientr.hearts = 2; }")
        gs1.call_weapon("-probe", "ping")
        scope = rt.flag_scope_object("clientr")
        assert to_num(scope.get("freezetime")) >= 0.0
        assert client.player.hearts == 2.0
        assert to_num(scope.get("hearts")) == 2.0
        assert "freezetime" not in gs1._shared["client"]
        assert "hearts" not in gs1._shared["client"]

    def test_unregistered_flag_round_trips_between_engines(self):
        client, gs1, rt = _rt()
        gs1.load_weapon("-probe", "if (ping) { clientr.sworddisabled = 7; }")
        gs1.call_weapon("-probe", "ping")
        scope = rt.flag_scope_object("clientr")
        assert to_num(scope.get("sworddisabled")) == 7.0
        scope.set("sworddisabled", 9.0)
        assert gs1._shared["client"]["sworddisabled"] == 9.0

    def test_flag_write_does_not_shadow_a_live_freeze(self):
        client, gs1, rt = _rt()
        scope = rt.flag_scope_object("clientr")
        # The LTTP intro's own write. Under the reference resolution this IS
        # a property write (freeze for 0 ticks), not a flag.
        scope.set("freezetime", -1.0)
        assert to_num(scope.get("freezetime")) == -1.0
        # Engine freeze arrives (DoSword's freezeplayer(0.6) path).
        gs1._host.call_command("freezeplayer", [0.6], rt._gs1_ctx(None))
        assert to_num(scope.get("freezetime")) >= 0.0, \
            "clientr.freezetime must read the live freeze counter while frozen"
        # player.freezetime and clientr.freezetime are the same storage
        # (a live countdown, so two reads only agree approximately).
        assert abs(to_num(rt.player_object.get("freezetime"))
                   - to_num(scope.get("freezetime"))) < 0.05

    def test_unfrozen_reads_minus_one(self):
        client, gs1, rt = _rt()
        scope = rt.flag_scope_object("clientr")
        assert to_num(scope.get("freezetime")) == -1.0

    def test_property_write_through_clientr_freezes_the_player(self):
        client, gs1, rt = _rt()
        scope = rt.flag_scope_object("clientr")
        # A serverside cutscene freeze: clientr.freezetime = 2 is
        # propfun_player_freezetime_w(player, 2) in the reference.
        scope.set("freezetime", 2.0)
        assert to_num(rt.player_object.get("freezetime")) >= 0.0
        # And the script's own unfreeze write clears it again.
        scope.set("freezetime", -1.0)
        assert to_num(rt.player_object.get("freezetime")) == -1.0

    def test_registered_position_write_moves_the_player(self):
        client, gs1, rt = _rt()
        scope = rt.flag_scope_object("clientr")
        scope.set("x", 41.5)
        assert client.player.x == 41.5
        assert to_num(scope.get("x")) == 41.5
        assert "x" not in gs1._shared["client"]

    def test_unregistered_names_stay_flags(self):
        client, gs1, rt = _rt()
        scope = rt.flag_scope_object("clientr")
        # LTTP's other clientr toggles are NOT registered properties, so they
        # keep flag semantics (storage + spelling rules unchanged).
        scope.set("sworddisabled", 0.0)
        scope.set("ganidisabled", 0.0)
        scope.set("strafe", 0.0)
        assert to_num(scope.get("sworddisabled")) == 0.0
        assert to_num(scope.get("ganidisabled")) == 0.0
        shared = gs1._shared["client"]
        assert "sworddisabled" in shared
        assert "freezetime" not in shared, \
            "a registered property name must never land in the flag store"
