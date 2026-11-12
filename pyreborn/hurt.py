"""Classic hurt timing and geometry, independent of networking and pygame."""

import math
from dataclasses import dataclass

from .clock import sim_passed

# TInitStatics.cpp:1554-1559, hurtflyd: three wall probes per edge,
# in up/left/down/right order. These are collision offsets, not motion deltas.
HURT_FLY_PROBES = (
    (0.6, 1.1, 1.5, 1.1, 2.4, 1.1),
    (0.6, 1.1, 0.6, 2.0, 0.6, 2.9),
    (0.6, 2.9, 1.5, 2.9, 2.4, 2.9),
    (2.4, 1.1, 2.4, 2.0, 2.4, 2.9),
)
TICK_SECONDS = 0.05
HURT_TICKS = 40  # TPlayer.cpp:6575, unknown15 = 0x28.
HURT_SECONDS = HURT_TICKS * TICK_SECONDS
INPUT_LOCK_TICKS = 11  # keyAction :2256 refuses while counter > 0x1d.


def hurt_vector(dx, dy):
    """TPlayer.cpp:6582-6601: normalize, defaulting a zero vector to right."""
    if dx == 0 and dy == 0:
        return 1.0, 0.0
    length = math.hypot(dx, dy)
    return dx / length, dy / length


@dataclass
class HurtState:
    started: float = -100.0
    until: float = -100.0
    dx: float = 0.0
    dy: float = 0.0
    ticks: int = 0
    elapsed: float = 0.0
    generation: int = 0

    def immune(self, now):
        return not sim_passed(now, self.until)

    def input_locked(self, now):
        return not sim_passed(now, self.started, INPUT_LOCK_TICKS * TICK_SECONDS)

    def start(self, dx, dy, now):
        self.started, self.until = now, now + HURT_SECONDS
        self.dx, self.dy = hurt_vector(dx, dy)
        self.ticks, self.elapsed = 0, 0.0
        self.generation += 1

    def advance(self, dt, move):
        """TPlayer::hurtFly :2880-2923, with a fixed 20 Hz accumulator.

        The decrement precedes the >34 test: counters 39..35 move (five
        steps), then 34..0 only count down. A blocked step consumes its tick.
        """
        if not self.generation or self.ticks >= HURT_TICKS:
            return
        self.elapsed += max(0.0, dt)
        target = min(HURT_TICKS, int((self.elapsed + 1e-9) / TICK_SECONDS))
        while self.ticks < target:
            self.ticks += 1
            if HURT_TICKS - self.ticks > 34:
                move(self.dx, self.dy)
