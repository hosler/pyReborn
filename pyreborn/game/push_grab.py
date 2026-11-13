"""Push/grab/pull hold state owned by the game (``self.push``).

Pure data plus the two field resets; the ``player.action_mode`` side effect
of clearing a grab stays in ``ActionsMixin._clear_grab_state``.
"""
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class PushGrab:
    hold_dir: Optional[Tuple[int, int]] = None  # (dx, dy) of the currently-blocked held direction
    hold_start: Optional[float] = None  # clock.sim_now() the block started, None when not holding
    counter: int = 38  # push countdown (38 -> 18)
    fire_cycle: int = -1  # last 20-tick push cycle that fired its NPC event
    pushing: bool = False  # True when the push countdown reaches 18
    grab: Optional[str] = None  # None | "grab" | "pull"
    grab_direction: Optional[int] = None  # facing direction pinned for the current grab
    pull_started: Optional[float] = None
    pull_fired: bool = False
    pull_counter: int = 1

    def clear_push(self) -> None:
        self.hold_dir = None
        self.hold_start = None
        self.counter = 38
        self.fire_cycle = -1
        self.pushing = False

    def clear_grab(self) -> None:
        self.grab = None
        self.grab_direction = None
        self.pull_started = None
        self.pull_fired = False
        self.pull_counter = 1
