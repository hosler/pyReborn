"""Level-arrival and link-warp bookkeeping owned by the game (``self.arrival``).

Everything that answers "did we just arrive somewhere, and what does that
suppress": which level the GS1 engine is loaded for, the settle timer before
a reload, a queued script warp, and the link-warp re-fire guards.

``gs1_level`` and ``visual_epoch`` are ``None`` until ``start()`` stamps them;
a ``None`` ``visual_epoch`` means "no epoch seen yet" and is never treated as
a level change.
"""
from dataclasses import dataclass
from typing import Any, Optional, Tuple


@dataclass
class LevelArrival:
    gs1_level: Optional[str] = None  # level the GS1 engine is loaded for
    visual_epoch: Optional[int] = None  # last plain_level_change_epoch seen
    playerenters_pending: bool = False  # reload skipped playerenters (no board yet)
    change_pending: Optional[str] = None  # level waiting for its NPCs to stream in
    change_at: float = 0.0  # clock.frame_now() when change_pending was set
    pending_warp: Optional[Tuple[str, float, float]] = None  # queued setlevel2/serverwarp
    # True while standing on a warp link, so links only fire on the rising
    # edge (stepping ON): no bounce across overlapping links.
    on_link: bool = False
    # The spot a warp last dropped us; while within ~1.5 tiles of it, link
    # warps stay suppressed even if the destination's links stream in late.
    link_arrival: Optional[Any] = None
    # Last position probed by _check_scripted_link_warp (scripted movement
    # writes x/y from the VM, bypassing _move()'s link check).
    scripted_link_pos: Optional[Any] = None
    scripted_gmap_cell: Optional[Any] = None
