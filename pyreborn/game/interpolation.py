"""Draw positions between the last two simulation ticks.

The simulation changes positions 20 times a second (pyreborn/clock.py); the
display runs faster. A moving thing is drawn at

    previous + (current - previous) * alpha

where `current` is its position after the latest tick, `previous` its
position after the tick before, and `alpha = clock.accumulator / tick_length`
how far the next tick is along. This is presentation only: the result goes
into draw calls and the game's `visual_*` caches, never back into an entity,
collision, a script value or a packet.

Positions are recorded lazily, the first time something is drawn after a tick
(step() runs network and ticks before the render, so that is the state at the
end of the tick). A thing seen for the first time, one that jumped further
than SNAP_TILES in a tick (a warp, a respawn) and one whose caller says the
jump was not a move (`snap=True`) is drawn where it is, without a slide.
"""

import math
from typing import Any, Dict, Hashable, Optional, Tuple

Position = Tuple[float, float]


class _Track:
    __slots__ = ("previous", "current", "tick", "owner")

    def __init__(self, position: Position, tick: int, owner: Any) -> None:
        self.previous = position
        self.current = position
        self.tick = tick
        self.owner = owner


class TickInterpolator:
    """Per-key (previous, current) tick positions and the blend between."""

    #: A per-tick jump longer than this (tiles) is a teleport: no slide.
    SNAP_TILES = 2.0

    def __init__(self) -> None:
        self._tracks: Dict[Hashable, _Track] = {}

    def position(self, key: Hashable, live: Position, tick: int,
                 alpha: float, *, snap: bool = False,
                 owner: Any = None, follow_between_ticks: bool = False
                 ) -> Position:
        """The draw position of `key`, whose simulated position is `live`.

        `owner` is the object the key names, when the key is an id(): a track
        whose owner is a different object is a new thing that reused the id.
        `follow_between_ticks`: a move that happened without a tick (only
        possible from outside the simulation, e.g. a server correction of the
        local player) is drawn at once instead of from the next tick on.
        """
        live = (float(live[0]), float(live[1]))
        track = self._tracks.get(key)
        if track is None or snap or (owner is not None and track.owner is not owner):
            self._tracks[key] = _Track(live, tick, owner)
            return live
        if tick != track.tick:
            # The first draw after a tick: the live position is that tick's.
            track.previous = track.current if tick == track.tick + 1 else live
            track.current = live
            track.tick = tick
        elif live != track.current:
            # Moved without a tick (a packet, a warp between ticks): show it
            # from the next tick on, or at once when asked or when it jumped.
            if follow_between_ticks or math.hypot(
                    live[0] - track.current[0],
                    live[1] - track.current[1]) > self.SNAP_TILES:
                track.previous = track.current = live
        prev, cur = track.previous, track.current
        if math.hypot(cur[0] - prev[0], cur[1] - prev[1]) > self.SNAP_TILES:
            track.previous = cur
            return cur
        a = max(0.0, min(1.0, alpha))
        return prev[0] + (cur[0] - prev[0]) * a, prev[1] + (cur[1] - prev[1]) * a

    def forget(self, key: Hashable) -> None:
        self._tracks.pop(key, None)

    def prune(self, tick: int, keep_ticks: int = 2) -> None:
        """Drop tracks not drawn for `keep_ticks` ticks (things that left)."""
        stale = [key for key, track in self._tracks.items()
                 if tick - track.tick > keep_ticks]
        for key in stale:
            del self._tracks[key]

    def reset(self) -> None:
        self._tracks.clear()

    def __len__(self) -> int:
        return len(self._tracks)

    def current(self, key: Hashable) -> Optional[Position]:
        track = self._tracks.get(key)
        return None if track is None else track.current
