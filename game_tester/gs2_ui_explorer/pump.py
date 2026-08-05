from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .fingerprint import snapshot_and_hash


FRAME_DT = 1.0 / 60.0


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
        game = self.game
        client = game.client
        game._frame_dt = self.frame_dt
        client.update(timeout=0)
        for name in ("_load_new_npcs", "_process_pending_warp",
                     "_process_self_shoots"):
            getattr(game, name)()
        game.gs1.process_coroutines(self.frame_dt)
        game.gs1.process_timeouts(self.frame_dt)
        game.gs2.process_coroutines(self.frame_dt)
        game.gs2.process_timeouts(self.frame_dt)
        for name in ("_check_scripted_link_warp",):
            getattr(game, name)()
        game.gs1.advance_input_frame()
        for name in ("_check_level_change", "_update_swimming_state"):
            getattr(game, name)()
        game._update_visual_position(self.frame_dt)
        game._update_animations(self.frame_dt)
        game._last_dt = self.frame_dt
        game._render()

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
