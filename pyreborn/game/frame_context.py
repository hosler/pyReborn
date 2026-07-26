"""FrameContext — the per-frame scratch the render passes hand each other.

The entity pass produces data that later passes consume: nameplate rectangles
(so two players on one tile stagger their labels), additive light draws that
must land *after* the ambient tint, and the light footprints that tint can
erase. That used to live in ``_frame_*`` attributes on the GameClient, which
made EntityRenderMixin and EffectsRenderMixin one indivisible unit whose output
depended on the order render.py happened to call them in. Here the same data is
one object, created per frame by render.py's `_render_scene` and passed into
every pass that reads or writes it, so the dependency is in the signature.

`in_frame` distinguishes a live frame from the idle context callers outside the
render loop (harnesses, unit tests calling a single renderer) get: deferred
draws only make sense while something is going to flush them, so an idle
context tells the producer to draw immediately instead.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple


@dataclass
class FrameContext:
    """One frame's cross-pass state. Nothing here survives the frame."""

    dt: float = 0.0
    in_frame: bool = False
    # True only while _render_gui_layers walks the screen-space GUI band,
    # which runs after the tint and so must not defer its additive layers.
    gui_pass: bool = False
    # Bounds the entity pass culls against. Resolved when that pass starts,
    # not at frame start: while zoomed the scene is drawn into a smaller
    # scratch surface (render.py's _render_scene_zoomed).
    screen_size: Tuple[int, int] = (0, 0)
    # level name -> gmap grid cell, and the current segment's world origin.
    level_to_grid: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    segment_offset: Tuple[float, float] = (0.0, 0.0)
    # (rect,) nameplates already placed, in placement order.
    nameplate_rects: List[Any] = field(default_factory=list)
    # (eraser_mask, screen_x, screen_y) drawaslight footprints the ambient
    # tint may punch out of itself.
    light_sources: List[Tuple[Any, float, float]] = field(default_factory=list)
    # (surface, screen_x, screen_y) additive glows waiting for the tint.
    light_draws: List[Tuple[Any, float, float]] = field(default_factory=list)

    def defer_light(self, surface: Any, x: float, y: float) -> bool:
        """Queue an additive light draw for after the ambient tint, and report
        whether it was queued. False means nothing will flush it (an idle
        context, or the post-tint GUI pass) and the caller should blit now."""
        if not self.in_frame or self.gui_pass:
            return False
        self.light_draws.append((surface, x, y))
        return True


class FrameContextMixin:
    """Frame-context lifecycle, shared by every render mixin that touches one."""

    def _begin_frame(self) -> FrameContext:
        """Open a frame. Its context replaces the previous frame's, so nothing
        a pass queued and failed to flush can leak into the next one."""
        ctx = self._frame_ctx = FrameContext(
            dt=getattr(self, '_frame_dt', 0.0), in_frame=True)
        return ctx

    def _frame_context(self) -> FrameContext:
        """The frame in progress, or an idle context for callers outside the
        render loop (harnesses, unit tests driving one renderer). The idle
        context is remembered rather than rebuilt per call, so nameplate
        staggering still accumulates across such calls the way the old
        lazily-created ``_frame_nameplate_rects`` list did."""
        ctx = getattr(self, '_frame_ctx', None)
        if ctx is None:
            ctx = self._frame_ctx = FrameContext(
                dt=getattr(self, '_frame_dt', 0.0))
        return ctx
