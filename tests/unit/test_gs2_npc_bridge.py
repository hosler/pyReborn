"""The GS2 NPC-bytecode bridge: a level NPC's script <-> client.npcs[id].

`_NpcThisObject` is what makes a v6 server's PLO_NPCBYTECODE actually DO
something -- it bridges the script's `this.`/bare property writes onto the
dict the renderer draws from (render_entities.py) -- and until 2026-07-24 it
had never been exercised against real server content. These pin the findings
of that run against the local 2006 Era world (GServer-v2 bin/servers/era on
:14901, ~150 NPC bytecodes over six levels):

1. Bytecode that arrived BEFORE ClientGS2.attach() was dropped forever. The
   app logs in and only then builds GameClient (pygame_game.py:191), so the
   whole login burst -- every start-level NPC script -- never got a VM.
2. NPC VMs deliberately outlive their level (gs2emu streams a level's static
   data once per session, so dropping them would kill every script on
   re-entry), but client.npcs IS cleared on a level change, which left every
   departed NPC's settimer loop running against a record that no longer
   exists: 3596 orphan onTimeout calls against 3912 live ones over a
   24-second four-level walk.

Property names are pinned against the reference client's gani-object
property table (Preagonal/FourPlay quattroplay/src/TGaniObjectProperties.cpp)
-- note it has `ani` and NOT `gani`, which is why only the former bridges.
"""
import os
import struct
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

from types import SimpleNamespace

from reborn_protocol.gs2 import FunctionEntry, GS2Container, GS2VM, Op
from reborn_protocol.gs2.container import GS2ContainerError  # noqa: F401

from pyreborn.gs2_client import ClientGS2, _NpcThisObject


# -- minimal hand-assembler (same idiom as test_gs2_client.py) --------------

def _op(opnum: int, marker: int = None, value=None) -> bytes:
    if marker is None:
        return bytes([opnum])
    out = bytearray([opnum, marker])
    if marker == 0xF0:
        out += struct.pack(">B", value)
    elif marker == 0xF3:
        out += struct.pack(">b", value)
    else:
        raise ValueError(f"unsupported marker 0x{marker:02X}")
    return bytes(out)


def _var(strings: list, name: str) -> bytes:
    if name not in strings:
        strings.append(name)
    return _op(Op.OP_TYPE_VAR, 0xF0, strings.index(name))


def _this_inc(strings: list, field: str) -> bytes:
    return (_op(Op.OP_THIS) + _var(strings, field)
            + _op(Op.OP_MEMBER_ACCESS) + _op(Op.OP_INC))


def _timeout_counter_container() -> GS2Container:
    """function onTimeout() { this.hit++; }

    Instruction 0 is a bare return: run_toplevel() always starts there, and
    without it every load would run the function body once as "toplevel"."""
    strings: list = []
    body = _op(Op.OP_RET) + _this_inc(strings, "hit") + _op(Op.OP_RET)
    return GS2Container(functions=[FunctionEntry("onTimeout", 1)],
                        strings=strings, code=body)


def _serialize(container: GS2Container) -> bytes:
    """Re-emit a container as the wire blob GS2VM(bytes) parses."""
    out = bytearray()

    def seg(seg_id: int, payload: bytes):
        out.extend(struct.pack(">II", seg_id, len(payload)))
        out.extend(payload)

    seg(1, struct.pack(">I", container.gs1_flags))
    funcs = b"".join(struct.pack(">I", f.op_index) + f.name.encode() + b"\x00"
                     for f in container.functions)
    seg(2, funcs)
    seg(3, b"".join(s.encode() + b"\x00" for s in container.strings))
    seg(4, container.code)
    out.append(0x0A)
    return bytes(out)


# -- fixtures ---------------------------------------------------------------

def _npc_client(level="a.nw", npcs=None):
    return SimpleNamespace(
        player=SimpleNamespace(x=30.0, y=30.0, account="me", nickname="Me",
                               id=1, direction=2, gani="idle"),
        players={}, x=30.0, y=30.0, weapons={}, server_name="probe",
        connected=False, _current_level_name=level,
        npcs=npcs if npcs is not None else {},
        gs2_bytecode={"weapon": {}, "npc": {}, "gani": {}, "class": {}},
        on_gs2_bytecode=None, on_server_text=None, gs2_host=None,
        _in_update=False)


def _record(**over):
    rec = {"x": 10.0, "y": 20.0, "world_x": 10.0, "world_y": 20.0,
           "image": "thing.png", "_level": "a.nw"}
    rec.update(over)
    return rec


# =============================================================================
# 1. this.<prop> -> the live npc dict
# =============================================================================

def test_position_write_moves_the_record_and_tracks_world_coords():
    """`x = 12.5` must move the sprite: the renderer prefers world_x/world_y
    (client.py stamps them on every PLO_NPCPROPS), so a local-frame write has
    to carry the same delta into the world frame -- and snap rather than lerp,
    because a script placement is not movement."""
    snapped = []
    rec = _record()
    client = _npc_client(npcs={5: rec})
    client._mark_npc_pos_snap = snapped.append
    this = _NpcThisObject(ClientGS2(client), ("npc", 5))

    this.set("x", 12.5)
    this.set("y", 34.25)
    assert (rec["x"], rec["y"]) == (12.5, 34.25)
    assert (rec["world_x"], rec["world_y"]) == (12.5, 34.25)
    assert snapped == [rec, rec]


def test_position_write_keeps_a_gmap_segment_offset():
    rec = _record(x=10.0, y=20.0, world_x=138.0, world_y=84.0)
    this = _NpcThisObject(ClientGS2(_npc_client(npcs={5: rec})), ("npc", 5))
    this.set("x", 11.0)
    # +1 in the local frame is +1 in the world frame, segment origin intact
    assert (rec["x"], rec["world_x"]) == (11.0, 139.0)


def test_appearance_writes_land_on_the_renderer_keys():
    rec = _record()
    this = _NpcThisObject(ClientGS2(_npc_client(npcs={5: rec})), ("npc", 5))
    this.set("ani", "walk")
    this.set("headimg", "head99.png")
    this.set("bodyimg", "body2.png")
    this.set("nick", "BridgeProbe")
    this.set("dir", 3)
    assert rec["gani"] == "walk"          # `ani` is the script name, `gani` the store key
    assert rec["head_image"] == "head99.png"
    assert rec["body_image"] == "body2.png"
    assert rec["nickname"] == "BridgeProbe"
    assert rec["direction"] == 3.0


def test_gani_is_not_a_bridged_name():
    """`gani` is deliberately absent from the claim set: the reference's
    gani-object property table (TGaniObjectProperties.cpp:46) has `ani` and
    no `gani`, so claiming it would steal a name a script may use as its own
    variable. Live-checked against the whole Era corpus: the only bare NPC
    writes that fall through to script storage are the engine's focus*
    camera globals, never an appearance property."""
    rec = _record()
    this = _NpcThisObject(ClientGS2(_npc_client(npcs={5: rec})), ("npc", 5))
    assert this.has("ani") and not this.has("gani")
    this.set("gani", "walk")
    assert "gani" not in rec and this.get("gani") == "walk"


def test_colors_index_writes_reach_the_character_compositor():
    rec = _record()
    this = _NpcThisObject(ClientGS2(_npc_client(npcs={5: rec})), ("npc", 5))
    colors = this.get("colors")
    colors.set("0", 3)
    colors.set("4", 7)
    assert (rec["color0"], rec["color4"]) == ("3", "7")
    assert colors.get("0") == "3"
    # out-of-range indices stay plain member storage, never a bogus slot
    colors.set("9", 1)
    assert "color9" not in rec


def test_reads_mirror_the_live_record_and_survive_a_missing_one():
    rec = _record(gani="idle", nickname="Bob")
    client = _npc_client(npcs={5: rec})
    this = _NpcThisObject(ClientGS2(client), ("npc", 5))
    assert this.get("x") == 10.0 and this.get("ani") == "idle"
    assert this.get("nick") == "Bob"
    # bytecode can arrive before the NPC's props do: reads fall back to plain
    # member storage instead of raising
    orphan = _NpcThisObject(ClientGS2(client), ("npc", 77))
    orphan.set("x", 5)
    assert orphan.get("x") == 5


def test_string_keyed_npc_ids_resolve_to_the_same_record():
    rec = _record()
    this = _NpcThisObject(ClientGS2(_npc_client(npcs={5: rec})), ("npc", "5"))
    this.set("ani", "walk")
    assert rec["gani"] == "walk"


# =============================================================================
# 2. event routing + teardown
# =============================================================================

def _load_npc_vm(rt, npc_id):
    return rt.load_bytecode("npc", npc_id, _serialize(_timeout_counter_container()))


def test_trigger_npc_event_hits_only_that_npc():
    rt = ClientGS2(_npc_client(npcs={5: _record(), 6: _record()}))
    five, six = _load_npc_vm(rt, 5), _load_npc_vm(rt, 6)
    assert rt.trigger_npc_event(5, "onTimeout") is True
    assert five.this.get("hit") == 1 and six.this.get("hit") is None
    # id given as a string (npc VM keys keep the type they arrived with)
    assert rt.trigger_npc_event("5", "onTimeout") is True
    assert five.this.get("hit") == 2
    assert rt.trigger_npc_event(999, "onTimeout") is False
    assert rt.trigger_npc_event(5, "onNoSuchEvent") is False


def test_forget_npc_drops_vm_timeout_and_scheduled_events():
    rt = ClientGS2(_npc_client(npcs={5: _record()}))
    vm = _load_npc_vm(rt, 5)
    rt._timeouts[("npc", 5)] = 1.0
    rt.schedule_event(vm, 0.5, "onTimeout", [])
    rt.forget_npc(5)
    assert 5 not in rt.vms["npc"]
    assert ("npc", 5) not in rt._timeouts
    assert not [item for item in rt._scheduled if item["key"] == ("npc", 5)]


# =============================================================================
# 3. attach() replays bytecode that landed before the hook existed
# =============================================================================

def test_attach_replays_bytecode_received_before_the_hook():
    """The launcher logs in and only then builds GameClient, so the login
    burst's scripts land in client.gs2_bytecode with nobody listening."""
    client = _npc_client(npcs={5: _record()})
    client.gs2_bytecode["npc"][5] = _serialize(_timeout_counter_container())
    rt = ClientGS2(client).attach()
    assert 5 in rt.vms["npc"]
    assert client.on_gs2_bytecode.__func__ is ClientGS2._on_bytecode
    # the replay must not double-load when a live packet then arrives
    rt._on_bytecode("npc", 5, client.gs2_bytecode["npc"][5])
    assert len(rt.vms["npc"]) == 1


def test_attach_loads_classes_before_the_weapons_that_join_them():
    client = _npc_client()
    blob = _serialize(_timeout_counter_container())
    client.gs2_bytecode["weapon"]["-w"] = blob
    client.gs2_bytecode["class"]["c"] = blob
    rt = ClientGS2(client).attach()
    assert set(rt.vms["class"]) == {"c"} and set(rt.vms["weapon"]) == {"-w"}


# =============================================================================
# 4. orphaned-NPC timer suppression
# =============================================================================

def test_timer_of_an_npc_left_behind_by_a_warp_stops_firing():
    rec = _record()
    client = _npc_client(npcs={5: rec})
    rt = ClientGS2(client)
    vm = _load_npc_vm(rt, 5)

    rt.pump_level_events()                    # NPC comes alive in a.nw
    assert getattr(vm, "_gs2_entered_level") == "a.nw"
    rt._timeouts[("npc", 5)] = 0.0
    rt._process_timeout_step(0.01)
    assert vm.this.get("hit") == 1

    # warp: client.npcs is cleared (_reset_level_state) and the record is gone
    client.npcs.clear()
    client._current_level_name = "b.nw"
    rt._timeouts[("npc", 5)] = 0.0
    rt._process_timeout_step(0.01)
    assert vm.this.get("hit") == 1, "orphaned NPC timer must not fire"

    # ...and comes back when we return (the VM is paused, never killed --
    # gs2emu will not re-stream the bytecode)
    client.npcs[5] = rec
    client._current_level_name = "a.nw"
    rt.pump_level_events()
    rt._timeouts[("npc", 5)] = 0.0
    rt._process_timeout_step(0.01)
    assert vm.this.get("hit") == 2


def test_a_never_entered_npc_vm_still_ticks():
    """Props can stream in after the bytecode; that VM has not entered any
    level yet and must keep its timer (as must weapons and headless VMs)."""
    client = _npc_client(npcs={})
    rt = ClientGS2(client)
    vm = _load_npc_vm(rt, 5)
    assert not hasattr(vm, "_gs2_entered_level")
    rt._timeouts[("npc", 5)] = 0.0
    rt._process_timeout_step(0.01)
    assert vm.this.get("hit") == 1


def test_scheduled_events_of_an_orphan_are_suppressed_too():
    rec = _record()
    client = _npc_client(npcs={5: rec})
    rt = ClientGS2(client)
    vm = _load_npc_vm(rt, 5)
    rt.pump_level_events()
    client.npcs.clear()
    client._current_level_name = "b.nw"
    rt.schedule_event(vm, 0.0, "onTimeout", [])
    rt._process_scheduled_events(0.01)
    assert vm.this.get("hit") is None
