"""GS2 script-timer resolution vs the v6 reference client.

A prior wave floored settimer()/this.timeout at 0.05s ("real-client timer
resolution") — but that tradition is the LEGACY GS1 path (OpenGraal.Common
ScriptObj.cs:100, `timeout -= 0.05` per tick). The v6 GS2 path has no such
floor: GS2Engine 1.8.3 Script.cs SetTimer() fires onTimeout from a ThreadPool
sleeper at Thread.Sleep(value * 1500) (no floor), and GameEngine.cs:755 polls
due timers every fixed-timestep Update (TargetElapsedTime = 1/120 s). So a
self-rearming setTimer(0.01) loop ticks at roughly frame rate — that cadence
sizes the bomber lobby's CadavreTest cog spin (0.03 rad/tick ⇒ ~1.8 rad/s at
60fps, not the 0.6 rad/s the 0.05 floor produced).

Bytecode assembly mirrors test_gs2_client.py's minimal hand-assembler (kept
local: tests/ isn't a package, so cross-test-module imports are fragile).
"""

import os
import struct
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pytest

from reborn_protocol.gs2 import GS2Container, FunctionEntry, Op, decode
from pyreborn.gs2_client import ClientGS2, TIMER_RESOLUTION


def _op(opnum: int) -> bytes:
    return bytes([opnum])


def _numf(v: float) -> bytes:
    """Push a float literal (OP_TYPE_NUMBER, 0xF6 = NUL-terminated cstr —
    the encoding real compiled scripts use for setTimer(0.01))."""
    return bytes([Op.OP_TYPE_NUMBER, 0xF6]) + f"{v}".encode("ascii") + b"\x00"


def _var(strings: list, name: str) -> bytes:
    if name not in strings:
        strings.append(name)
    return bytes([Op.OP_TYPE_VAR, 0xF0, strings.index(name)])


def _call(strings: list, fname: str, *arg_bytes: bytes) -> bytes:
    code = _op(Op.OP_TYPE_ARRAY)
    for a in reversed(arg_bytes):
        code += a
    code += _var(strings, fname)
    code += _op(Op.OP_CALL)
    return code


def _this_inc(strings: list, field: str) -> bytes:
    return (_op(Op.OP_THIS) + _var(strings, field)
            + _op(Op.OP_MEMBER_ACCESS) + _op(Op.OP_INC))


def _ret() -> bytes:
    return _op(Op.OP_RET)


def _skip_to_toplevel(target_idx: int) -> bytes:
    return _op(Op.OP_TYPE_TRUE) + bytes([Op.OP_SET_INDEX_TRUE, 0xF3]) \
        + struct.pack(">b", target_idx)


def _build_rearming_ticker(interval: float) -> GS2Container:
    """function onTimeout() { this.ticks++; settimer(interval); }
    toplevel: settimer(interval);   — the CadavreTest / -Test_Movement
    self-rearming loop shape."""
    strings: list = []
    body = (_this_inc(strings, "ticks")
            + _call(strings, "settimer", _numf(interval)) + _ret())
    prelude = _skip_to_toplevel(0)  # placeholder, patched below
    ontimeout_idx = len(decode(prelude))
    toplevel_idx = ontimeout_idx + len(decode(body))
    prelude = _skip_to_toplevel(toplevel_idx)
    code = prelude + body + _call(strings, "settimer", _numf(interval))
    return GS2Container(functions=[FunctionEntry("onTimeout", ontimeout_idx)],
                        strings=strings, code=code)


class TestTimerFloor:
    def test_settimer_0_01_is_not_floored_to_0_05(self):
        rt2 = ClientGS2()
        vm = rt2.load_bytecode("weapon", "wcog", _build_rearming_ticker(0.01))
        key = rt2._timeout_key(vm)
        assert rt2._timeouts[key] == pytest.approx(0.01)

    def test_sub_resolution_values_floor_at_the_reference_update_tick(self):
        rt2 = ClientGS2()
        vm = rt2.load_bytecode("weapon", "w", GS2Container())
        key = rt2._timeout_key(vm)
        vm.this.set("timeout", 0.001)
        assert rt2._timeouts[key] == pytest.approx(TIMER_RESOLUTION)
        vm.this.set("timeout", 0.5)
        assert rt2._timeouts[key] == pytest.approx(0.5)


class TestRearmingLoopCadence:
    """The CadavreTest cogs step rotation 0.03 rad per onTimeout with a
    setTimer(0.01) re-arm; the visual rate is ticks/s * 0.03. The reference
    runs that loop at ~60-120Hz (frame-bound); with the old 0.05 floor we
    ticked at 20Hz (0.6 rad/s — hosler's 'really slow' cogs)."""

    def _ticks_after_one_second(self, fps: int) -> float:
        rt2 = ClientGS2()
        vm = rt2.load_bytecode("weapon", "wcog", _build_rearming_ticker(0.01))
        for _ in range(fps):
            rt2.process_timeouts(1.0 / fps)
        return float(vm.this.get("ticks") or 0)

    def test_cadence_matches_at_30_and_120_fps(self):
        slow = self._ticks_after_one_second(30)
        fast = self._ticks_after_one_second(120)
        assert abs(slow - fast) <= 1
        assert 55 <= slow <= 65
