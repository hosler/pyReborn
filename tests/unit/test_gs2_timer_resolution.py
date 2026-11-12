"""GS2 script-timer cadence vs the reference client: the frame tick decides it.

The decompiled reference client runs its script universe on a clock
(TScriptUniverse::initTime) that steps once per tick
(Preagonal/FourPlay/quattroplay/src/TScriptUniverse.cpp:226-231): by
frametick/1000 when the frame tick is 50 ms or more, and to the current real
time when it is shorter. A timeout fires once less than 0.0001 of it is left
(TScriptSpace.cpp:1030-1047). So a self-rearming setTimer(0.01) loop fires
once per tick, and the tick rate is TTime::frametick: 50 ms (20 fires a
second) from server-list login (TServerList.cpp:376), or whatever a script set
with adventure_setframetick (TTime.cpp:23-26).

History: the v6 bomber's lobby cogs (CadavreTest) and its -Test/Movement
weapon both run such a loop, and both scripts call
Adventure_setFrameTick(1000/60) first (the bomber GS2 server tree's
weapon-Test_Movement.txt:94 and world/bomblobby.nw:1047-1048). A 2026-07 wave
floored timers at 1/120 s instead (copied from the C# client's 120 Hz Update
loop, GameEngine.cs:171), which made the cogs fast enough that they no longer
looked "really slow"; that floor approximated the effect of the
script-raised frame tick, at twice its rate. The 2026-11-11 fixed-tick
switch set the floor to one 50 ms tick and ignored the script's frame tick,
which brought the slow cogs back. Now there is no floor: the frame tick the
script sets paces the ticks and the script clock, as in the reference.

Bytecode assembly mirrors test_gs2_client.py's minimal hand-assembler (kept
local: tests/ is not a package, so cross-test-module imports are fragile).
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
from pyreborn.clock import Clock
from pyreborn.gs2_client import ClientGS2


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


def _build_rearming_ticker(interval: float, frame_tick=None) -> GS2Container:
    """function onTimeout() { this.ticks++; settimer(interval); }
    toplevel: [adventure_setframetick(frame_tick);] settimer(interval);
    — the CadavreTest / -Test_Movement self-rearming loop shape."""
    strings: list = []
    body = (_this_inc(strings, "ticks")
            + _call(strings, "settimer", _numf(interval)) + _ret())
    prelude = _skip_to_toplevel(0)  # placeholder, patched below
    ontimeout_idx = len(decode(prelude))
    toplevel_idx = ontimeout_idx + len(decode(body))
    prelude = _skip_to_toplevel(toplevel_idx)
    toplevel = b""
    if frame_tick is not None:
        toplevel += _call(strings, "adventure_setframetick", _numf(frame_tick))
    toplevel += _call(strings, "settimer", _numf(interval))
    code = prelude + body + toplevel
    return GS2Container(functions=[FunctionEntry("onTimeout", ontimeout_idx)],
                        strings=strings, code=code)


class _Session:
    """A ClientGS2 on a clock driven by a fake frame-time source: frames of
    `1/fps` seconds through the real tick policy, one script step per tick
    (what GameClient._simulation_tick does)."""

    def __init__(self):
        self.t = 0.0
        self.clock = Clock(source=lambda: self.t)
        self.rt2 = ClientGS2()
        self.rt2.__dict__["_own_clock"] = self.clock

    def run(self, seconds: float, fps: float) -> int:
        ticks = 0
        for _ in range(int(round(seconds * fps))):
            self.t += 1.0 / fps
            for _ in range(self.clock.ticks_due(1.0 / fps)):
                self.clock.begin_tick()
                self.rt2.process_timeouts(self.clock.script_dt)
                ticks += 1
        return ticks


def _ticks(vm) -> float:
    return float(vm.this.get("ticks") or 0)


class TestNoFloor:
    def test_settimer_stores_the_value_as_given(self):
        rt2 = ClientGS2()
        vm = rt2.load_bytecode("weapon", "wcog", _build_rearming_ticker(0.01))
        assert rt2._timeouts[rt2._timeout_key(vm)] == pytest.approx(0.01)
        rt2.process_timeouts(0.05)          # one default tick fires it
        assert _ticks(vm) == 1

    def test_this_timeout_stores_the_value_as_given(self):
        rt2 = ClientGS2()
        vm = rt2.load_bytecode("weapon", "w", GS2Container())
        key = rt2._timeout_key(vm)
        vm.this.set("timeout", 0.001)
        assert rt2._timeouts[key] == pytest.approx(0.001)
        vm.this.set("timeout", 0.5)
        assert rt2._timeouts[key] == pytest.approx(0.5)

    def test_the_old_resolution_constant_is_gone(self):
        import pyreborn.gs2_client as gs2_client
        from pyreborn.gs2_client import registry
        assert not hasattr(gs2_client, "TIMER_RESOLUTION")
        assert not hasattr(registry, "TIMER_RESOLUTION")


class TestRearmingLoopCadence:
    """A self-rearming setTimer(0.01) loop fires once per tick."""

    @pytest.mark.parametrize("fps", [30, 60, 144])
    def test_default_frame_tick_fires_twenty_times_a_second(self, fps):
        session = _Session()
        vm = session.rt2.load_bytecode("weapon", "wcog",
                                       _build_rearming_ticker(0.01))
        ticks = session.run(1.0, fps)
        assert abs(ticks - 20) <= 1
        assert _ticks(vm) == ticks

    @pytest.mark.parametrize("fps", [60, 144])
    def test_script_raised_frame_tick_fires_about_sixty_times(self, fps):
        """Adventure_setFrameTick(1000/60): a 16 ms tick, a real-time script
        clock, one fire per tick: ~60 a second on a 60 Hz display, 62.5 when
        the display is faster than the tick."""
        session = _Session()
        vm = session.rt2.load_bytecode(
            "weapon", "wcog", _build_rearming_ticker(0.01, 1000 / 60))
        assert session.clock.frame_tick_ms == 16
        session.run(1.0, fps)
        assert 58 <= _ticks(vm) <= 63

    def test_a_0_1_timer_fires_every_second_tick(self):
        rt2 = ClientGS2()
        vm = rt2.load_bytecode("weapon", "wcog", _build_rearming_ticker(0.1))
        fired = []
        for _ in range(6):
            rt2.process_timeouts(0.05)
            fired.append(_ticks(vm))
        assert fired == [0, 1, 1, 2, 2, 3]

    def test_a_long_frame_tick_steps_the_script_clock_by_the_tick(self):
        """frametick >= 50: initTime += frametick/1000 per tick, so a 100 ms
        tick moves a 0.1 timer once per tick, ten times a second."""
        session = _Session()
        vm = session.rt2.load_bytecode(
            "weapon", "wcog", _build_rearming_ticker(0.1, 100))
        ticks = session.run(2.0, 60)
        assert abs(ticks - 20) <= 1
        assert _ticks(vm) == ticks
