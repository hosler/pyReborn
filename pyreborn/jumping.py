"""Classic ledge-jump paths from TPlayer.cpp:95-99 and :6453-6482."""

from dataclasses import dataclass

from .hurt import TICK_SECONDS

JUMP_DELTA_Y_UP = (-0.2, 0.2, 0.5, 1.5, 2.8, 4.0, 5.4, 7.0)
JUMP_DELTA_Y_SIDE = (-0.2, -0.5, 0.0, 0.5, 1.1, 1.7, 2.3, 3.0)
JUMP_DELTA_X_SIDE = (1.0, 2.0, 3.0, 3.8, 4.5, 5.2, 5.8, 6.5)
JUMP_DELTA_Y_DOWN = (1.5, 2.7, 3.8, 4.5, 5.0, 5.2, 5.2, 5.0)
JUMP_LANDING_OFFSET = ((0.0, -5.0), (-6.5, 3.0), (0.0, 7.0), (6.5, 3.0))
JUMP_TICKS = 8
JUMP_PUSH_TICKS = 18  # movementAction, TPlayer.cpp:7562 (counter == 0x12).


def jump_offset(direction, tick):
    """Zero-based tick, preserving the oracle's Up/Down table naming."""
    if direction == 0:
        return 0.0, -JUMP_DELTA_Y_DOWN[tick]
    if direction == 1:
        return -JUMP_DELTA_X_SIDE[tick], JUMP_DELTA_Y_SIDE[tick]
    if direction == 2:
        return 0.0, JUMP_DELTA_Y_UP[tick]
    return JUMP_DELTA_X_SIDE[tick], JUMP_DELTA_Y_SIDE[tick]


@dataclass
class JumpState:
    origin_x: float
    origin_y: float
    direction: int
    ticks: int = 0
    elapsed: float = 0.0

    def advance(self, dt, move_to):
        self.elapsed += max(0.0, dt)
        target = min(JUMP_TICKS, int((self.elapsed + 1e-9) / TICK_SECONDS))
        while self.ticks < target:
            dx, dy = jump_offset(self.direction, self.ticks)
            move_to(self.origin_x + dx, self.origin_y + dy)
            self.ticks += 1
        return self.ticks == JUMP_TICKS
