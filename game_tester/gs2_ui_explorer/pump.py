from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .fingerprint import snapshot_and_hash


# One simulation tick per pumped frame (pyreborn/clock.py): a "stable for N
# frames" settle check then means N ticks of unchanged GUI, not N frames in
# which nothing could have changed because no tick ran.
FRAME_DT = 0.05


@dataclass(frozen=True)
class SettleResult:
    frames: int
    seconds: float
    quiescent: bool

    def to_dict(self):
        return {"frames": self.frames, "seconds": round(self.seconds, 4),
                "quiescent": self.quiescent}


class GamePump:
    def __init__(self, game: Any, frame_dt: float = FRAME_DT,
                 stable_frames: int = 3):
        self.game = game
        self.frame_dt = frame_dt
        self.stable_frames = max(1, stable_frames)

    def step(self) -> None:
        """One real frame (GameClient.step)."""
        self.game.step(self.frame_dt, strict=True)

    def _idle(self) -> bool:
        runtime = self.game.gs2
        gui_idle = not runtime.gui.has_active_animations()
        runtime_idle = not runtime.has_pending_explorer_work()
        return gui_idle and runtime_idle

    def settle(self, seconds: float = 3.0) -> SettleResult:
        start = time.monotonic()
        deadline = start + max(0, seconds)
        frames = stable = 0
        _state, previous = snapshot_and_hash(self.game.gs2.gui)
        while time.monotonic() < deadline:
            self.step()
            frames += 1
            _state, digest = snapshot_and_hash(self.game.gs2.gui)
            stable = stable + 1 if digest == previous else 0
            previous = digest
            if stable >= self.stable_frames and self._idle():
                return SettleResult(frames, time.monotonic() - start, True)
        return SettleResult(frames, time.monotonic() - start, False)
