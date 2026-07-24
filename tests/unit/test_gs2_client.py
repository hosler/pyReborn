"""Regression tests for the 2026-07-19 GS2 client-runtime bugs (ClientGS2 in
pyreborn/gs2_client.py):

1. settimer()/onTimeout per-VM-instance identity: two joiners of the same
   class used to share one ("class", cname) timeout slot (GS2ClientHost.
   settimer + ClientGS2._attach_class/process_timeouts), so the second
   joiner's settimer() clobbered the first's, and onTimeout ran against the
   wrong instance's state.
2. Script reload (a re-sent weapon/npc bytecode blob) used to skip
   run_toplevel() entirely, silently dropping any join("class") the script's
   toplevel makes -- a re-sent script's class attachments never came back.
3. GS2ClientHost.sleep()'s fallback branch (no client to pump / nested /
   in-packet) always truncated the wait to <=50ms and returned as though the
   full duration had elapsed, compressing scripted pacing.

These build minimal hand-assembled GS2 bytecode containers directly (no
external gs2parser compiler dependency, unlike the fixture-driven VM-opcode
suite in reborn-protocol/tests/test_gs2_vm.py) -- just enough instructions to
exercise the ClientGS2 orchestration layer these bugs live in, not general
VM semantics (already covered there).
"""

import os
import struct
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pytest

from reborn_protocol.gs2 import GS2Container, FunctionEntry, GS2VM, Op
from pyreborn.gs1_client import ClientGS1
from pyreborn.gs2_client import ClientGS2


# =============================================================================
# Minimal hand-assembler: just enough GS2 bytecode to drive ClientGS2's
# orchestration logic (settimer/join/onCreated/toplevel), not general VM
# opcode coverage.
# =============================================================================

def _op(opnum: int, marker: int = None, value=None) -> bytes:
    """One decoded instruction's raw bytes (see disasm.py's format)."""
    if marker is None:
        return bytes([opnum])
    out = bytearray([opnum, marker])
    if marker == 0xF0:
        out += struct.pack(">B", value)
    elif marker == 0xF3:
        out += struct.pack(">b", value)
    else:
        raise ValueError(f"unsupported marker 0x{marker:02X} in test helper")
    return bytes(out)


def _num(v: int) -> bytes:
    """Push a small integer literal (OP_TYPE_NUMBER, signed i8 operand)."""
    return _op(Op.OP_TYPE_NUMBER, 0xF3, v)


def _var(strings: list, name: str) -> bytes:
    """Push a VarRef(name) (OP_TYPE_VAR, unsigned index into the string
    table -- appends `name` to `strings` if not already present)."""
    if name not in strings:
        strings.append(name)
    return _op(Op.OP_TYPE_VAR, 0xF0, strings.index(name))


def _strlit(strings: list, s: str) -> bytes:
    """Push a string literal (OP_TYPE_STRING)."""
    if s not in strings:
        strings.append(s)
    return _op(Op.OP_TYPE_STRING, 0xF0, strings.index(s))


def _call(strings: list, fname: str, *arg_bytes: bytes) -> bytes:
    """`fname(args...)` as a global/builtin call: ARRAY_START, then args
    pushed in reverse source order, then the function VarRef, then CALL --
    see GS2VM._op_call/_pop_args."""
    code = _op(Op.OP_TYPE_ARRAY)
    for a in reversed(arg_bytes):
        code += a
    code += _var(strings, fname)
    code += _op(Op.OP_CALL)
    return code


def _this_assign(strings: list, field: str, value_bytes: bytes) -> bytes:
    """`this.<field> = <value>;`"""
    return (_op(Op.OP_THIS) + _var(strings, field) + _op(Op.OP_MEMBER_ACCESS)
            + value_bytes + _op(Op.OP_ASSIGN))


def _this_inc(strings: list, field: str) -> bytes:
    """`this.<field>++;`"""
    return _op(Op.OP_THIS) + _var(strings, field) + _op(Op.OP_MEMBER_ACCESS) + _op(Op.OP_INC)


def _ret() -> bytes:
    """`return;` -- every hand-assembled function body needs one: without it
    _execute() falls off the end of the function's instructions straight
    into whatever comes next in the shared code stream (real compiled
    functions always end with a return)."""
    return _op(Op.OP_RET)


def _count_instrs(code: bytes) -> int:
    from reborn_protocol.gs2 import decode
    return len(decode(code))


def _skip_to_toplevel(target_idx: int) -> bytes:
    """An unconditional prelude jump (OP_TYPE_TRUE + OP_SET_INDEX_TRUE),
    matching the compiler's real mechanism for making run_toplevel() (which
    always starts at instruction 0) skip over inline function bodies -- see
    GS2VM.run_toplevel's docstring."""
    return _op(Op.OP_TYPE_TRUE) + _op(Op.OP_SET_INDEX_TRUE, 0xF3, target_idx)


# =============================================================================
# 1. settimer()/onTimeout per-VM-instance identity
# =============================================================================

def _build_class_with_arm_and_timeout():
    """A class with:
        function arm() { settimer(5); }
        function onTimeout() { this.hit++; }
    `arm` calls the settimer() builtin directly from a joined-class-instance
    VM (the exact call site the bug was in)."""
    strings: list = []
    arm_body = _call(strings, "settimer", _num(5)) + _ret()
    arm_idx = 0
    timeout_idx = _count_instrs(arm_body)
    timeout_body = _this_inc(strings, "hit") + _ret()
    code = arm_body + timeout_body
    functions = [
        FunctionEntry("arm", arm_idx),
        FunctionEntry("onTimeout", timeout_idx),
    ]
    return GS2Container(functions=functions, strings=strings, code=code)


class TestSettimerPerInstanceIdentity:
    def test_two_joiners_get_independent_timeout_slots(self):
        rt2 = ClientGS2()
        rt2.load_bytecode("class", "cls", _build_class_with_arm_and_timeout())

        joiner1 = rt2.load_bytecode("npc", 1, GS2Container())
        joiner2 = rt2.load_bytecode("npc", 2, GS2Container())
        assert rt2.join_class(joiner1, "cls")
        assert rt2.join_class(joiner2, "cls")

        # Both joiners call the class's arm() -> settimer(5) executes on
        # THEIR OWN joined-class instance VM, not a VM shared between them.
        joiner1.call("arm")
        joiner2.call("arm")

        key1 = rt2._timeout_key(joiner1)
        key2 = rt2._timeout_key(joiner2)
        assert key1 != key2
        # The old bug filed both under the single shared ("class", "cls")
        # key, so the second settimer() call clobbered the first's slot and
        # _timeouts ended up with exactly one entry.
        assert len(rt2._timeouts) == 2
        assert rt2._timeouts[key1] == pytest.approx(5.0)
        assert rt2._timeouts[key2] == pytest.approx(5.0)

    def test_ontimeout_fires_on_the_correct_joiner_not_the_class_def_vm(self):
        rt2 = ClientGS2()
        class_vm = rt2.load_bytecode("class", "cls", _build_class_with_arm_and_timeout())

        joiner1 = rt2.load_bytecode("npc", 1, GS2Container())
        joiner2 = rt2.load_bytecode("npc", 2, GS2Container())
        rt2.join_class(joiner1, "cls")
        rt2.join_class(joiner2, "cls")
        joiner1.call("arm")
        joiner2.call("arm")

        for _ in range(20):
            rt2.process_timeouts(0.25)

        assert joiner1.this.get("hit") == pytest.approx(1.0)
        assert joiner2.this.get("hit") == pytest.approx(1.0)
        # The shared class-DEFINITION VM's own (unused) this-object never
        # saw either onTimeout -- if the old code's ("class", "cls") key had
        # resolved back to `class_vm` (self.vms["class"]["cls"]) instead of
        # a joiner, this is what would have been mutated instead.
        assert class_vm.this.get("hit") is None
        assert rt2._timeouts == {}


# =============================================================================
# 2. Script reload runs toplevel (rebuilding joins) but doesn't re-fire
#    onCreated
# =============================================================================

def _build_weapon_with_join_and_oncreated():
    """function onCreated() { this.createdCount++; }
    toplevel: join("cls");
    (functions are placed after an unconditional prelude jump so
    run_toplevel(), which always starts at instruction 0, skips over them --
    exactly like real compiled bytecode.)"""
    strings: list = []
    oncreated_body = _this_inc(strings, "createdCount") + _ret()
    toplevel_body = _call(strings, "join", _strlit(strings, "cls"))

    prelude = _skip_to_toplevel(0)  # placeholder, patched below
    oncreated_idx = _count_instrs(prelude)
    toplevel_idx = oncreated_idx + _count_instrs(oncreated_body)
    prelude = _skip_to_toplevel(toplevel_idx)

    code = prelude + oncreated_body + toplevel_body
    functions = [FunctionEntry("onCreated", oncreated_idx)]
    return GS2Container(functions=functions, strings=strings, code=code)


class TestScriptReload:
    def test_reload_reruns_toplevel_and_rebuilds_joins_without_refiring_oncreated(self):
        rt2 = ClientGS2()
        rt2.load_bytecode("class", "cls", GS2Container())
        container = _build_weapon_with_join_and_oncreated()

        vm1 = rt2.load_bytecode("weapon", "w1", container)
        assert len(vm1.joined) == 1
        assert vm1.this.get("createdcount") == pytest.approx(1.0)

        # Re-send of the identical bytecode (e.g. a hot-reloaded weapon).
        vm2 = rt2.load_bytecode("weapon", "w1", container)

        assert vm2 is not vm1
        assert vm2.this is vm1.this          # state (this.) carries over
        # The bug: toplevel (and its join("cls")) never ran on reload, so
        # vm2.joined stayed permanently empty.
        assert len(vm2.joined) == 1
        # onCreated is constructor semantics -- it must NOT re-fire on a
        # re-send of the same object.
        assert vm2.this.get("createdcount") == pytest.approx(1.0)


class TestClientBuiltinsAndFrameEvents:
    def test_isleader_uses_the_gs1_truth_value(self):
        client = _FakeClient()
        client.level = "room.nw"
        client.players = {}
        gs1 = ClientGS1(client)
        rt2 = ClientGS2(client, gs1)

        assert rt2.host.get_object("isleader") is True
        client.players[2] = {"level": "room.nw"}
        assert rt2.host.get_object("isleader") is False
        gs1.is_leader = True
        assert rt2.host.get_object("isleader") is True
        assert rt2.host.get_object("not_a_builtin") is None

    def test_onupdate_only_runs_when_declared_and_not_active(self):
        strings = []
        body = _this_inc(strings, "updates") + _ret()
        prelude = _skip_to_toplevel(2 + _count_instrs(body))
        container = GS2Container(
            functions=[FunctionEntry("onUpdate", 2)], strings=strings,
            code=prelude + body)
        rt2 = ClientGS2()
        vm = rt2.load_bytecode("npc", 1, container)
        rt2.load_bytecode("npc", 2, GS2Container())

        key = rt2._timeout_key(vm)
        rt2._active_coro_keys.add(key)
        rt2.process_timeouts(1 / 60)
        assert vm.this.get("updates") is None

        rt2._active_coro_keys.clear()
        rt2.process_timeouts(1 / 60)
        assert vm.this.get("updates") == pytest.approx(2.0)


# =============================================================================
# 3. sleep() fallback no longer silently truncates to <=50ms
# =============================================================================

class _FakeClient:
    def __init__(self, connected=True, in_update=False):
        self.connected = connected
        self._in_update = in_update


class TestSleepFallback:
    def test_disconnected_sleep_waits_the_full_duration(self):
        rt2 = ClientGS2()
        rt2.client = None
        vm = GS2VM(GS2Container())

        start = time.time()
        rt2.host.sleep(vm, 0.15)
        elapsed = time.time() - start

        # Old behavior: time.sleep(min(secs, 0.05)) -- capped near 0.05s
        # regardless of the requested duration.
        assert elapsed >= 0.13

    def test_nested_sleep_waits_the_full_duration(self):
        rt2 = ClientGS2()
        rt2.client = _FakeClient(connected=True, in_update=False)
        rt2._sleeping = True  # another script's sleep() is already pumping
        vm = GS2VM(GS2Container())

        start = time.time()
        rt2.host.sleep(vm, 0.15)
        elapsed = time.time() - start

        assert elapsed >= 0.13

    def test_in_packet_sleep_bounds_the_wait_and_records_the_remainder(self):
        rt2 = ClientGS2()
        rt2.client = _FakeClient(connected=True, in_update=True)
        vm = GS2VM(GS2Container())

        start = time.time()
        rt2.host.sleep(vm, 0.4)
        elapsed = time.time() - start

        # Must NOT block the packet loop for anywhere near the full 0.4s...
        assert elapsed < 0.15
        # ...but the unpaid remainder is recorded, not silently dropped.
        assert vm._gs2_sleep_debt == pytest.approx(0.35, abs=0.02)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
