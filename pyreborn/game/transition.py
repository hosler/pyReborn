"""Level-transition presentation state owned by the game (``self.transition``).

The held-frame and slide machinery of ``game/render.py``: the framebuffer
snapshot kept while a local level transition is held, the world-only copy of
the last completed frame, the active slide, and the input freeze that goes
with it.

``render.py`` writes ``input_frozen`` from inside the render pass; actions and
input read it, which is how a slide freezes movement. ``death_base_frame`` is
written by ``render_effects._render_combat_presentation``.
"""
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class TransitionState:
    slide: Optional[Dict[str, Any]] = None  # active slide: source/destination/direction/started
    input_frozen: bool = False  # True while a slide is presented
    frame: Optional[Any] = None  # framebuffer snapshot held during a local transition
    scene_frame: Optional[Any] = None  # world-only copy of the last completed frame
    death_base_frame: Optional[Any] = None  # pre-death-overlay frame the hold snapshots
    # Last client.local_level_transition_epoch the visual position synced to;
    # seeded from the client in GameClient.__init__.
    seen_epoch: int = 0
