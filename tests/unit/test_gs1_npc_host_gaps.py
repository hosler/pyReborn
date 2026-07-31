"""The NPC-to-NPC surface classic Bomber's furniture is built on.

room0.nw's rooms are driven by NPCs talking to each other: every furniture NPC
advertises a role in its own `save[]` slots, and the room controller and the
arcade cabinets scan `npcs[0..npcscount-1].save[j]` to find who to poke with
`callnpc`. All four of those pieces were missing or inert on this client, so
furniture rendered and nothing ever activated:

* `npcscount` was unimplemented, so every scan loop had zero iterations.
* `npcs[i].<attr>` had no handler at all.
* a bare `save[i] = n` write fell through to VarStore's indexed-set, which
  drops a write into a non-existent array (runtime.py:199) — so every NPC
  advertised 0.
* `callnpc` was in the no-op set.

The replay at the bottom runs the real captured scripts (bomber_room0_fixture).
"""

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pytest

from pyreborn import Client
from pyreborn.gs1_client import ClientGS1
from reborn_protocol.gs1.runtime import Context, VarStore

from .bomber_room0_fixture import load_capture, load_flags, load_scripts


class _SentRecorder:
    connected = True

    def __init__(self):
        self.sent = []

    def send_packet(self, packet_id, data=b""):
        self.sent.append((int(packet_id), bytes(data)))
        return True


def _client(level="room0.nw", board_tile=0x278):
    c = Client("localhost", 14900)
    c._authenticated = True
    c._protocol = _SentRecorder()
    c._current_level_name = level
    c.tiles = [board_tile] * 4096
    c._tiles_level_name = level
    return c


def _engine(scripts, level="room0.nw", board_tile=0x278):
    """A ClientGS1 with `scripts` ({npc id -> source}) loaded as level NPCs."""
    c = _client(level, board_tile)
    for npc_id, src in scripts.items():
        c.npcs[npc_id] = {"x": float(npc_id), "y": 1.0, "image": "-",
                          "script": src, "_level": level}
    gs1 = ClientGS1(c)
    for npc_id, src in scripts.items():
        gs1.load_script("npc_%d" % npc_id, src, npc_id=npc_id,
                        x=float(npc_id), y=1.0)
    return c, gs1


def _this(gs1, npc_id):
    return gs1._progs["npc_%d" % npc_id]["scopes"]["this"]


def _finish_ready_slices(gs1):
    # The captured room scripts exceed the cooperative frame budget.  Drain
    # only zero-delay preemption continuations when a test needs completed
    # state; numeric sleeps still wait for the explicit frame time below.
    while any(c["remaining"] <= 0 for c in gs1._coros):
        gs1.process_coroutines(0.0)


# -- npcscount / npcs[i] -----------------------------------------------------

def test_npcscount_counts_the_level_npcs():
    _c, gs1 = _engine({5: "if (timeout) { this.n = npcscount; }", 9: ";"})
    gs1.trigger_npc_event(5, "timeout")
    assert _this(gs1, 5)["n"] == 2.0


def test_npcs_index_is_ordinal_over_the_sorted_ids():
    # GS1's npcs[] is a level-order array; ours is a dict keyed by server id.
    _c, gs1 = _engine({40: ";", 7: ";",
                       5: "if (timeout) { this.a = npcs[0].x; this.b = npcs[2].x; }"})
    gs1.trigger_npc_event(5, "timeout")
    assert (_this(gs1, 5)["a"], _this(gs1, 5)["b"]) == (5.0, 40.0)


def test_npcs_index_out_of_range_reads_zero():
    _c, gs1 = _engine({5: "if (timeout) { this.a = npcs[9].x; }"})
    gs1.trigger_npc_event(5, "timeout")
    assert _this(gs1, 5)["a"] == 0.0


# -- save[] ------------------------------------------------------------------

def test_bare_save_write_is_readable_by_the_owning_npc():
    _c, gs1 = _engine({5: "if (timeout) { save[1] = 13; this.back = save[1]; }"})
    gs1.trigger_npc_event(5, "timeout")
    assert _this(gs1, 5)["back"] == 13.0
    assert gs1.npc_save_slots(5)[1] == 13.0


def test_bare_save_and_this_save_are_the_same_slots():
    _c, gs1 = _engine({5: "if (timeout) { save[0] = 9; this.back = this.save[0]; }"})
    gs1.trigger_npc_event(5, "timeout")
    assert _this(gs1, 5)["back"] == 9.0


def test_another_npcs_save_slot_is_readable_by_index():
    # The whole point: the second index (`[1]`) must survive to the host —
    # `npcs[n].save[0]` and `npcs[n].save[1]` are different questions.
    scripts = {
        5: "if (playerenters) { save[0] = 9; save[1] = 13; }",
        8: "if (timeout) { this.a = npcs[0].save[0]; this.b = npcs[0].save[1]; }",
    }
    _c, gs1 = _engine(scripts)
    gs1.trigger_npc_event(5, "playerenters")
    gs1.trigger_npc_event(8, "timeout")
    assert (_this(gs1, 8)["a"], _this(gs1, 8)["b"]) == (9.0, 13.0)


def test_a_weapon_has_no_save_slots():
    # Weapons run with npc_id -1; `save` must fall through to a plain var so a
    # weapon script that uses the name keeps its old behaviour.
    _c, gs1 = _engine({})
    gs1.load_weapon("-probe", "if (timeout) { save[0] = 4; this.back = save[0]; }")
    gs1.trigger_event("timeout", name="weapon_-probe")
    assert gs1.npc_save_slots(-1) is None


# -- callnpc -----------------------------------------------------------------

def test_callnpc_runs_the_indexed_npcs_handler():
    scripts = {5: "if (timeout) { callnpc 1,BOUT; }",
               8: "if (BOUT) { this.played = 1; }"}
    _c, gs1 = _engine(scripts)
    gs1.trigger_npc_event(5, "timeout")
    assert _this(gs1, 8)["played"] == 1.0


def test_callnpc_binds_trailing_args_to_p():
    # `callnpc this.n,timeout,2` — the lexer hands us "timeout,2" as one arg.
    scripts = {5: "if (playerenters) { callnpc 1,timeout,2; }",
               8: "if (timeout) { setstring this.p0,#p(0); }"}
    _c, gs1 = _engine(scripts)
    gs1.trigger_npc_event(5, "playerenters")
    assert _this(gs1, 8)["p0"] == "2"


def test_callnpc_restores_the_callers_own_p_params():
    scripts = {5: "if (keypressed) { callnpc 1,poke,x; setstring this.p1,#p(1); }",
               8: "if (poke) { this.ran = 1; }"}
    _c, gs1 = _engine(scripts)
    gs1.fire_keypress(65, "a")
    assert _this(gs1, 8)["ran"] == 1.0
    assert _this(gs1, 5)["p1"] == "a"
    assert gs1._proj_params == []


def test_mutually_calling_npcs_stop_at_the_nesting_cap():
    # Untrusted server scripts: a callnpc cycle must not recurse to a stack
    # overflow. Each hop bumps its own counter, so the cap is visible in them.
    scripts = {5: "if (poke) { this.hits += 1; callnpc 1,poke; }",
               8: "if (poke) { this.hits += 1; callnpc 0,poke; }"}
    _c, gs1 = _engine(scripts)
    gs1.trigger_npc_event(5, "poke")
    total = _this(gs1, 5)["hits"] + _this(gs1, 8)["hits"]
    assert total == ClientGS1._CALLNPC_MAX_DEPTH + 1
    assert gs1._callnpc_depth == 0


def test_callnpc_out_of_range_index_is_a_no_op():
    _c, gs1 = _engine({5: "if (timeout) { callnpc 9,BOUT; this.after = 1; }"})
    gs1.trigger_npc_event(5, "timeout")
    assert _this(gs1, 5)["after"] == 1.0


# -- parse failures are no longer silent -------------------------------------

def test_dropped_statements_are_reported(caplog):
    _c, gs1 = _engine({})
    with caplog.at_level(logging.WARNING, logger="pyreborn.gs1_client"):
        gs1.load_script("npc_5", "if (created) { this.a = (; this.b = 2; }", npc_id=5)
    assert any("dropped by parse recovery" in r.getMessage()
               for r in caplog.records)


def test_unparseable_scripts_are_reported(caplog):
    # Junk chars are contained by lexer/parser recovery now (2gta wave: a
    # single '\' typo used to kill a whole weapon via LexError): the broken
    # statement is dropped WITH a warning, the prog survives.
    _c, gs1 = _engine({})
    with caplog.at_level(logging.WARNING, logger="pyreborn.gs1_client"):
        gs1.load_script("npc_5", "this.a = #v(;", npc_id=5)
    prog = gs1._progs["npc_5"]["prog"]
    assert prog is not None and prog.body == []
    assert any("dropped by parse recovery" in r.getMessage()
               for r in caplog.records)


def test_join_requests_late_class_and_completes_once():
    c, gs1 = _engine({5: "join Lamp; if (timeout) { classTick(); }"})
    gs1.trigger_npc_event(5, "created")
    requests = [packet for packet in c._protocol.sent if packet[0] == 161]
    assert len(requests) == 1
    assert gs1.receive_class_source(
        "Lamp", "function classTick() { this.lit += 1; }")
    gs1.trigger_npc_event(5, "timeout")
    assert _this(gs1, 5)["lit"] == 1.0
    gs1.trigger_npc_event(5, "created")
    gs1.trigger_npc_event(5, "timeout")
    assert _this(gs1, 5)["lit"] == 2.0
    assert len([packet for packet in c._protocol.sent if packet[0] == 161]) == 1


def test_binary_join_response_is_rejected_and_can_be_requested_again():
    c, gs1 = _engine({5: "join Lamp; if (created) { this.runs += 1; }"})
    gs1.trigger_npc_event(5, "created")
    assert not gs1.receive_class_source("Lamp", b"\x00\x00\x00\x02junk")
    assert "lamp" not in gs1._gs1_classes
    assert "lamp" not in gs1._requested_classes
    assert "lamp" in gs1._pending_class_joins

    gs1.trigger_npc_event(5, "created")
    requests = [packet for packet in c._protocol.sent if packet[0] == 161]
    assert len(requests) == 2


def test_late_join_refires_created_for_joining_script():
    _c, gs1 = _engine({
        5: "join Lamp; if (created) { this.createdruns += 1; }"
    })
    gs1.trigger_npc_event(5, "created")
    assert _this(gs1, 5)["createdruns"] == 1.0
    assert gs1.receive_class_source("Lamp", "function lampReady() {}")
    assert _this(gs1, 5)["createdruns"] == 2.0


def test_missing_join_class_is_a_safe_no_op():
    _c, gs1 = _engine({5: "join Missing; if (timeout) { this.alive += 1; }"})
    gs1.trigger_npc_event(5, "created")
    gs1.trigger_npc_event(5, "timeout")
    assert _this(gs1, 5)["alive"] == 1.0


def test_with_getplayer_writes_the_live_player():
    c, gs1 = _engine({5: 'if (timeout) { with (getplayer("player")) { x = 22; } }'})
    c.player.account_name = "player"
    gs1.trigger_npc_event(5, "timeout")
    assert c.player.x == 22.0


def test_remote_getplayer_reads_live_record_drops_writes_and_falls_through():
    c, gs1 = _engine({
        5: ('if (timeout) { with (getplayer("bob")) {'
            ' this.before=x; x=99; this.after=x; this.mouse=mousex;'
            ' timeout=0.5; } }')
    })
    c.players[7] = {"id": 7, "account": "bob", "nickname": "Bob",
                    "x": 33.0, "y": 9.0}
    gs1.mouse_world_source = lambda: (12, 13)
    gs1.trigger_npc_event(5, "timeout")

    assert _this(gs1, 5)["before"] == 33.0
    assert _this(gs1, 5)["after"] == 33.0
    assert _this(gs1, 5)["mouse"] == 12.0
    assert c.players[7]["x"] == 33.0
    assert gs1._weapon_timeouts["npc_5"] == pytest.approx(0.5)


def test_makevar_accepts_read_only_namespace_aliases():
    _c, gs1 = _engine({})
    ctx = Context(gs1._host, VarStore(
        scopes={"client": {"seed": "client-value"},
                "server": {"seed": "server-value"}}))
    assert gs1._host.call_function(
        "makevar", ["clientr.seed"], ctx) == "client-value"
    assert gs1._host.call_function(
        "makevar", ["serverr.seed"], ctx) == "server-value"


def test_image_dimensions_and_misc_functions():
    _c, gs1 = _engine({
        5: 'if (timeout) { this.w=imgwidth("lamp.png");'
           'this.h=getimgheight("lamp.png"); this.r=degtorad(180);'
           'this.t=textheight(2,"font","b","x"); this.seed=9;'
           'this.m=makevar("this.seed"); }'
    })
    gs1.image_size_source = lambda name: (24, 40) if name == "lamp.png" else None
    gs1.trigger_npc_event(5, "timeout")
    assert (_this(gs1, 5)["w"], _this(gs1, 5)["h"]) == (24.0, 40.0)
    assert _this(gs1, 5)["r"] == pytest.approx(3.141592653589793)
    assert _this(gs1, 5)["t"] == 32.0
    assert _this(gs1, 5)["m"] == 9.0


def test_projectile_and_baddy_position_probes():
    c, gs1 = _engine({
        5: "if (timeout) { this.c=testcompu(4,5); this.b=testbomb(6,7);"
           "this.e=testexplo(8,9); }"
    })
    c.baddies[12] = {"x": 4.0, "y": 5.0}
    gs1.bombs_source = lambda: [{"x": 6.0, "y": 7.0}]
    c.active_explosions = [{"x": 8.0, "y": 9.0}]
    gs1.trigger_npc_event(5, "timeout")
    assert (_this(gs1, 5)["c"], _this(gs1, 5)["b"],
            _this(gs1, 5)["e"]) == (12.0, 0.0, 0.0)


def test_misc_commands_are_explicit_safe_noops():
    _c, gs1 = _engine({
        5: 'if (timeout) { savelog2 "chan","line"; setletters "font.png";'
           'timershow; this.after=1; }'
    })
    gs1.trigger_npc_event(5, "timeout")
    assert _this(gs1, 5)["after"] == 1.0


def test_fatal_lex_failures_are_reported(caplog):
    # A still-fatal lexer state (a char V mode never admits, lexer.py:765)
    # keeps the whole-script None + warning path. NB a FUNCTION name with
    # no '(' is no longer fatal — it re-emits as an identifier now.
    _c, gs1 = _engine({})
    with caplog.at_level(logging.WARNING, logger="pyreborn.gs1_client"):
        gs1.load_script("npc_6", "set this.a^b;", npc_id=6)
    assert gs1._progs["npc_6"]["prog"] is None
    assert any("failed to parse" in r.getMessage() for r in caplog.records)


# -- the live room0 replay ---------------------------------------------------

@pytest.fixture
def room0():
    """The captured room0.nw, replayed offline: every NPC loaded, the captured
    flags fed in, `created` + `playerenters` fired against a wall board (so
    ResetObj has nothing to delete)."""
    cap = load_capture()
    c = _client(cap["level"])
    c.player.x = cap["player_x"]
    c.player.y = cap["player_y"]
    scripts = load_scripts()
    for npc_id, src in scripts.items():
        info = cap["npcs"][str(npc_id)]
        c.npcs[npc_id] = {"x": info["x"], "y": info["y"], "image": info["image"],
                          "script": src, "_level": cap["level"]}
    gs1 = ClientGS1(c)
    for name, value in load_flags().items():
        gs1.recv_flag(name, value)
    calls = []
    inner = gs1.call_npc

    def _spy(npc_id, event, params=()):
        calls.append((npc_id, event, list(params)))
        return inner(npc_id, event, params)

    gs1.call_npc = _spy
    for npc_id, src in scripts.items():
        gs1.load_script("npc_%d" % npc_id, src, npc_id=npc_id,
                        x=c.npcs[npc_id]["x"], y=c.npcs[npc_id]["y"])
    gs1.trigger_event("created")
    gs1.trigger_event("playerenters")
    _finish_ready_slices(gs1)
    return c, gs1, calls


def test_room0_builds_the_whole_furniture_catalog(room0):
    _c, gs1, _calls = room0
    flags = gs1._shared["client"]
    names = {k for k in flags if k.startswith("dn")}
    # 57 catalog entries, not the single dn0 the truncated parse produced
    assert len(names) == 57
    assert flags["dn47"].startswith('"Game: Break Out!"')
    assert flags["dn49"].startswith('"Game: Snake!"')
    # every entry also publishes its a/b/c/o shape tables
    for obj in range(57):
        assert "rm_o%db" % obj in flags


def test_room0_npcs_advertise_their_roles_in_save(room0):
    _c, gs1, _calls = room0
    # the room controller's scan key (save[1]==13) and the arcade cabinets'
    # (save[0]==10 Break Out, 8 Snake)
    assert gs1.npc_save_slots(91)[1] == 13.0
    assert gs1.npc_save_slots(96)[0] == 10.0
    assert gs1.npc_save_slots(97)[0] == 8.0


def test_room0_arcade_cabinet_activates(room0):
    c, gs1, calls = room0
    # The Break Out cabinet (catalog type 47) stands at (49, 45) in the
    # captured room; face it from below and press grab.
    c.player.x, c.player.y, c.player.direction = 48.0, 46.0, 0
    gs1.keys_dir = {6}
    gs1.process_coroutines(0.05)
    assert (96, "BOUT", []) in calls


def test_room0_controller_refreshes_the_furniture_npcs(room0):
    _c, gs1, calls = room0
    for _ in range(3):
        gs1.process_coroutines(0.05)
        gs1.process_timeouts(0.05)
        _finish_ready_slices(gs1)
    # `for(n..npcscount) if(npcs[n].save[1]==13) callnpc n,timeout,2`
    refreshed = {npc_id for npc_id, event, params in calls
                 if event == "timeout" and params == ["2"]}
    assert refreshed and refreshed <= {91, 92, 98}


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
