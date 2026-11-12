"""The one clock of the library and the game: a fixed simulation tick plus a
monotonic frame time.

The reference client runs its whole simulation on a fixed 50 ms tick and never
catches up late time (Preagonal/FourPlay/quattroplay/src/AndroidInterface.cpp:
170-179; spec: scratchpad/pygame-framework-1111/timing-spec.md). This module
owns that policy. There are exactly two time reads, and their names say which
is which:

``sim_now()``
    Simulation time. Virtual: ``SIM_ORIGIN + tick * TICK_SECONDS``. It
    advances only when a tick runs (``begin_tick``), by exactly
    ``TICK_SECONDS`` (0.05). Every timer that affects state or packets reads
    it: movement, hurt/freeze/death, fuses, explosions, arrows, thrown and
    flying objects, item ages, NPC movement, cooldowns. The reference counts
    all of these in ticks (spec section 3), so simulation seconds are ticks
    in disguise: when a script changes the frame tick, every one of them runs
    faster or slower in real time with it, as in the reference. Durations the
    reference counts in ticks compare the integer ``tick`` counter, not
    seconds.

``script_now()``
    Script time: the script universe's clock (``initTime``,
    TScriptUniverse.cpp:226-231). With a frame tick of 50 ms or more it
    advances by frametick/1000 per tick; below 50 ms it follows measured real
    time. GS1/GS2 timeouts, sleep, scheduleevent and waitfor run on it
    (``script_dt`` is this tick's step).

``frame_now()``
    Frame time. Monotonic real seconds since an arbitrary start. For
    presentation only (interpolation, shimmer, fades, caret blink, camera
    shake) and for real-world waits (a network or file deadline, a login
    timeout), which must keep running while no tick does. Never compare it
    with ``sim_now()``. tests/unit/test_clock_discipline.py lists every
    ``frame_now()`` site with its reason.

``wall()`` is the time of day, for the few script builtins and report stamps
that truly need it.

The frame tick (``frame_tick_ms``, TTime::frametick) is the real length of a
tick: 50 ms from the start of a session (TServerList.cpp:376), changeable by
a script through ``adventure_setframetick`` (TTime.cpp:23-26, ``set_frame_tick``).
It paces the ticks and drives the script clock; it never changes what one
tick does.

The tick policy (``ticks_due``): a frame adds its real ``dt`` to an
accumulator; while the accumulator holds a whole ``tick_length`` (the frame
tick in seconds) and fewer than
``MAX_TICKS_PER_FRAME`` ticks ran this frame, one more tick is due. Time still
pending after that is dropped (the reference rebases ``next = now``), so a
stall never bursts ticks or movement packets afterwards. ``alpha`` is the
fraction of a tick the accumulator holds after the frame's ticks: the
interpolation factor for presentation.

Who runs the ticks: a host that owns a frame loop (``GameClient.step``) sets
``host_driven`` and calls ``ticks_due(dt)`` itself. Without a host,
``Client.update()`` measures the frame time between its own calls and runs
the due ticks (``pump_headless``), with the same policy.

Pure Python, no pygame. This module and its two time sources are the only
place in pyreborn/ that calls ``time.time`` or ``time.monotonic``; a test
enforces it.
"""

import math
import time
from typing import Callable, Optional

#: Slack for comparing a simulation duration with a whole number of ticks.
#: Two sim_now() readings differ from k * TICK_SECONDS by ~1e-10 (float at the
#: SIM_ORIGIN magnitude); the reference's own deadline slack is 0.0001
#: (TScriptSpace.cpp:1036). Use it, or the integer `tick`, never a bare >=.
SIM_EPSILON = 0.0001


class Clock:
    """Simulation ticks, monotonic frame time and time of day.

    ``source`` / ``wall_source`` / ``sleep_source`` are injectable so a test
    can drive the clock without patching the ``time`` module."""

    #: Simulation seconds per tick: the unit sim_now() counts ticks in. Fixed:
    #: the reference's own seconds-to-ticks conversions are fixed numbers
    #: (NPC move steps = seconds * 20, TServerNPC.cpp:1655), so a changed
    #: frame tick changes how often ticks run, never what one tick does.
    TICK_SECONDS = 0.05
    #: TTime::frametick at the start of a session: 50 ms, set at server-list
    #: login (TServerList.cpp:376; it is 0 before that, TTime.cpp:8).
    DEFAULT_FRAME_TICK_MS = 50
    #: Below this frame tick the script clock follows real time instead of
    #: advancing frametick/1000 per tick (TScriptUniverse.cpp:226, `< 0x32`).
    SCRIPT_WALL_BELOW_MS = 50
    #: Real seconds per tick (pacing): frame_tick_ms / 1000. Reassigned only
    #: by set_frame_tick; the class value is the session default.
    tick_length = DEFAULT_FRAME_TICK_MS / 1000.0
    #: Ticks one frame may run. The reference runs one; time beyond that is
    #: dropped (AndroidInterface.cpp:178-179). Raise it here, nowhere else.
    MAX_TICKS_PER_FRAME = 1
    #: ``sim_now()`` at tick 0. Large, so a stamp initialised to 0.0 ("never")
    #: reads as long ago from the first tick on, as it did with monotonic time.
    SIM_ORIGIN = 1_000_000.0
    #: Slack when comparing the accumulator with a tick: three 1/60 s frames
    #: are one tick even though their float sum is a hair under 0.05.
    _EPSILON = 1e-9

    def __init__(self, source: Optional[Callable[[], float]] = None,
                 wall_source: Optional[Callable[[], float]] = None,
                 sleep_source: Optional[Callable[[float], None]] = None) -> None:
        # None = read the `time` module at call time, so a test that patches
        # time.monotonic still moves a clock built before the patch.
        self._source = source
        self._wall_source = wall_source
        self._sleep_source = sleep_source
        #: Completed simulation ticks.
        self.tick = 0
        #: Real seconds not yet turned into a tick.
        self.accumulator = 0.0
        #: Ticks dropped because a frame brought more than it may run.
        self.dropped_ticks = 0
        #: True while a host (GameClient) runs the ticks; Client.update()
        #: then leaves them alone.
        self.host_driven = False
        self._headless_last: Optional[float] = None
        self._in_tick = False
        #: TTime::frametick in ms, an unsigned 32-bit value like the
        #: reference's uint32_t. Session state: a new Client starts at the
        #: default (see set_frame_tick).
        self.frame_tick_ms = self.DEFAULT_FRAME_TICK_MS
        self.tick_length = self.DEFAULT_FRAME_TICK_MS / 1000.0
        #: The script universe's clock (TScriptUniverse::initTime) and the
        #: step the current tick advanced it by.
        self._script_time = self.SIM_ORIGIN
        self.script_dt = 0.0
        #: frame_now() + offset = the real time the script clock follows
        #: below a 50 ms frame tick. Anchored at the first tick (and again
        #: when the time source changes), so the script clock starts on real
        #: time like the reference's (its first runScripts runs at frametick
        #: 0, TClientEnvironment.cpp:139-142).
        self._script_wall_offset: Optional[float] = None
        #: True once this tick's script pass has run (and before the first
        #: tick): a script timer armed now belongs to the next tick's pass.
        self._scripts_done = True

    # -- the two reads ------------------------------------------------------

    def sim_now(self) -> float:
        """Simulation seconds: advances by ``TICK_SECONDS`` per tick, only."""
        return self.SIM_ORIGIN + self.tick * self.TICK_SECONDS

    def script_now(self) -> float:
        """Script-universe seconds (see the module docstring)."""
        return self._script_time

    def frame_now(self) -> float:
        """Monotonic real seconds, for presentation and real-world waits."""
        source = self._source
        return time.monotonic() if source is None else source()

    def frame_now_ms(self) -> int:
        """`frame_now()` in whole milliseconds (pygame's get_ticks unit)."""
        return int(self.frame_now() * 1000)

    def wall(self) -> float:
        """Seconds since the epoch (time of day)."""
        source = self._wall_source
        return time.time() if source is None else source()

    def passed(self, stamp: float, seconds: float = 0.0) -> bool:
        """True once at least ``seconds`` of simulation time have passed since
        ``stamp`` (a ``sim_now()`` reading; for a deadline ``sim_now() + d``,
        ``seconds`` 0 asks "is it due"). See `sim_passed`."""
        return sim_passed(self.sim_now(), stamp, seconds)

    def ticks_since(self, stamp: float) -> int:
        """Whole ticks from ``stamp`` (a ``sim_now()`` reading) to now:
        ``passed(stamp, n * TICK_SECONDS)`` is ``ticks_since(stamp) >= n``."""
        return math.floor((self.sim_now() - stamp + SIM_EPSILON)
                          / self.TICK_SECONDS)

    def ticks_for(self, seconds: float) -> int:
        """A duration in seconds as a whole number of ticks (nearest)."""
        return int(round(float(seconds) / self.TICK_SECONDS))

    # -- the frame tick -------------------------------------------------------

    def set_frame_tick(self, ms: int) -> None:
        """adventure_setframetick: store the new tick length, in ms.

        ``ms`` is the reference's uint32_t (TTime.cpp:23-26): no clamp, no
        limit. It applies from the next frame (the pacing) and the next tick
        (the script clock). 0 means the reference's "no wait": one tick every
        loop pass (AndroidInterface.cpp:170-179), here one tick per frame. A
        huge value (a negative script argument wraps to ~4.29e9 ms) stops the
        ticks, as the reference's loop stops; frames still render and
        packets still arrive here."""
        ms = int(ms) & 0xFFFFFFFF
        self.frame_tick_ms = ms
        self.tick_length = ms / 1000.0

    def get_frame_tick(self) -> int:
        """adventure_getframetick / getFrameTick (TTime.cpp:18-21)."""
        return self.frame_tick_ms

    # -- the tick policy ----------------------------------------------------

    def ticks_due(self, dt: float) -> int:
        """Add a frame's real ``dt`` and return how many ticks to run now.

        At most ``MAX_TICKS_PER_FRAME``; whatever whole ticks remain after
        those are dropped. ``dt`` <= 0 adds nothing. A frame tick of 0 runs
        one tick per frame that has a positive ``dt``."""
        if self.tick_length <= 0.0:
            self.accumulator = 0.0
            return 1 if dt > 0 else 0
        if dt > 0:
            self.accumulator += dt
        due = 0
        while (due < self.MAX_TICKS_PER_FRAME
               and self.accumulator + self._EPSILON >= self.tick_length):
            self.accumulator -= self.tick_length
            due += 1
        if self.accumulator + self._EPSILON >= self.tick_length:
            # Late by a whole tick or more: rebase instead of catching up.
            self.dropped_ticks += int(
                (self.accumulator + self._EPSILON) / self.tick_length)
            self.accumulator = 0.0
        if self.accumulator < 0.0:
            self.accumulator = 0.0
        return due

    @property
    def alpha(self) -> float:
        """How far the next tick is along, 0..1 (presentation only)."""
        if self.tick_length <= 0.0:
            return 1.0
        return max(0.0, min(1.0, self.accumulator / self.tick_length))

    def begin_tick(self) -> None:
        """Advance simulation time by one tick and the script clock by its
        step. Call once at the start of each tick, before anything in it
        reads ``sim_now()`` or ``script_dt``."""
        self.tick += 1
        self._scripts_done = False
        self._advance_script_clock()

    # -- script timers: which pass counts them --------------------------------
    #
    # The reference runs every script once per tick, after the network and
    # the player's own timer (TPlayer.cpp:7374 doNPCActions, which runs every
    # script universe, :6395-6399). An event raised during the tick (a
    # packet, a touch while walking) is queued and runs in that pass, after
    # the pass checked the timers (TScriptSpace.cpp:459, before the queued
    # events), and setTimeout stamps the pass's script time
    # (TScriptSpace.cpp:134-135). So a timer armed at any
    # point first counts down in the NEXT pass: `timeout = 0.05` fires one
    # tick later, whatever raised the event. Our events run when they are
    # raised, so each timer records the pass it belongs to.

    def script_pass(self) -> int:
        """The script pass a timer armed now belongs to: this tick's while
        its scripts have not finished, else the next tick's."""
        return self.tick + (1 if self._scripts_done else 0)

    def end_script_pass(self) -> None:
        """This tick's scripts (GS1 and GS2) have run."""
        self._scripts_done = True

    def timer_counts(self, armed_pass: Optional[int]) -> bool:
        """True when a timer armed in ``armed_pass`` counts down in this
        tick's pass. Outside a tick (an engine driven directly, no game loop)
        every timer counts."""
        return not self._in_tick or armed_pass is None or armed_pass < self.tick

    def _advance_script_clock(self) -> None:
        """TScriptUniverse::runScripts (TScriptUniverse.cpp:226-231): below a
        50 ms frame tick initTime = the time now; otherwise initTime +=
        frametick/1000. Switching down to a short tick therefore jumps the
        script clock up to real time (by however far the per-tick steps had
        fallen behind it), and pending timers inside that jump fire on that
        tick, as in the reference. Never backwards: the reference reads the
        time of day; this reads monotonic time and keeps the larger value."""
        now = self.frame_now()
        step = self.frame_tick_ms / 1000.0
        if (self._script_wall_offset is not None
                and self.frame_tick_ms < self.SCRIPT_WALL_BELOW_MS):
            step = max(0.0, now + self._script_wall_offset - self._script_time)
        # The step itself is the tick's script time (exact 0.05 at the
        # default, not a difference of two large clock readings).
        self.script_dt = step
        self._script_time += step
        if self._script_wall_offset is None:
            # First tick (or a new time source): one tick's step, and real
            # time is anchored to the result, so the per-tick steps trail
            # real time from here on and never lead it (a tick only runs
            # once its length has passed).
            self._script_wall_offset = self._script_time - now

    def pump_headless(self) -> int:
        """Ticks due for a host-less ``Client.update()``: the frame time since
        the previous call, through ``ticks_due``. 0 on the first call, and 0
        whenever a host drives the ticks or a tick is already running."""
        if self.host_driven or self._in_tick:
            return 0
        now = self.frame_now()
        last, self._headless_last = self._headless_last, now
        if last is None:
            return 0
        return self.ticks_due(now - last)

    def time_to_next_tick(self) -> float:
        """Real seconds until the accumulator holds a whole tick (infinite at
        a frame tick of 0: the next tick waits for the next frame)."""
        if self.tick_length <= 0.0:
            return math.inf
        return max(0.0, self.tick_length - self.accumulator)

    # -- sources ------------------------------------------------------------

    def sleep(self, seconds: float) -> None:
        """Block for `seconds` of real time (a harness's sleep source may
        advance a fake clock instead of waiting)."""
        source = self._sleep_source
        if source is None:
            time.sleep(seconds)
        else:
            source(seconds)

    def set_sources(self, source: Optional[Callable[[], float]] = None,
                    wall_source: Optional[Callable[[], float]] = None,
                    sleep_source: Optional[Callable[[float], None]] = None) -> None:
        """Replace the time sources (a harness drives the clock this way).
        The headless pump restarts its measurement from the new source."""
        if source is not None:
            self._source = source
            self._headless_last = None
            self._script_wall_offset = None
        if wall_source is not None:
            self._wall_source = wall_source
        if sleep_source is not None:
            self._sleep_source = sleep_source


def sim_passed(now: float, stamp: float, seconds: float = 0.0) -> bool:
    """True when at least ``seconds`` of simulation time lie between
    ``stamp`` and ``now`` (both ``sim_now()`` readings, or a reading plus a
    duration). The one way to compare simulation time with a duration or a
    deadline (``Clock.passed`` is the same with ``now = sim_now()``): exact
    in ticks whatever the start tick, so a whole number of ticks is reached
    on its tick and a fraction rounds up to the next tick. A bare ``>``/``<``
    on sim_now() readings is not exact (``SIM_ORIGIN + n * 0.05`` is a
    float: ``now - stamp > 0.3`` is 6 ticks from some start ticks and 7 from
    others) and tests/unit/test_clock_discipline.py refuses it."""
    return now - stamp + SIM_EPSILON >= seconds


#: TTime::calcTimeVar's epoch offset: 0xc5866212 as a signed 32-bit int
#: (TTime.cpp:116-120), i.e. 2001-02-01 17:33:34 UTC.
TIMEVAR_EPOCH = 981048814


def calc_timevar(wall_seconds: float) -> int:
    """TTime::calcTimeVar: 5-second ticks since TIMEVAR_EPOCH."""
    return int((wall_seconds - TIMEVAR_EPOCH) / 5)


def world_timevar(client, clock: "Clock") -> int:
    """Script `timevar`: the world time the server last sent (stored, never
    advanced locally), else calcTimeVar of the time of day (TTime.cpp:10-16)."""
    stored = getattr(client, 'server_time', 0) if client is not None else 0
    if stored:
        return int(stored)
    return calc_timevar(clock.wall())
