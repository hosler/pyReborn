"""Camera2D — a single source of truth for world<->screen coordinate mapping.

Before this existed, the world->screen offset math was copy-pasted into ~8
render methods (props, doors, chests, bombs, projectiles, explosions, signs,
entities). Each recomputed `cam_offset = SCREEN//2 - visual*TILE` by hand, so a
change to the camera model meant editing every call site.

The camera works entirely in **render-frame tile coordinates** — the same frame
the tiles and entities are drawn in. For a GMAP the caller folds the segment
offset into the center (see `RenderMixin`); the camera itself stays oblivious to
GMAP vs single-level, which is what keeps it simple.

Borrowed from Preagonal's Camera2D (Camera2D.cs): a center position, a clamped
zoom, a dirty flag so the transform is only recomputed when something changes,
and bounds clamping so you can't scroll past the edge of the world.
"""

from typing import Optional, Tuple


class Camera2D:
    """Maps render-frame tile coordinates to screen pixels and back.

    `tile_size` is pixels-per-tile at zoom 1.0. `zoom` scales around the screen
    center. Positions (`cx`, `cy`) are the world-tile coordinates the camera is
    centered on.
    """

    MIN_ZOOM = 0.25
    MAX_ZOOM = 4.0

    def __init__(self, screen_w: int, screen_h: int, tile_size: int = 16):
        self.screen_w = screen_w
        self.screen_h = screen_h
        self.tile_size = tile_size

        self._cx = 0.0
        self._cy = 0.0
        self._zoom = 1.0

        # Cached derived transform (pixels-per-tile and screen-space origin of
        # tile (0,0)). Recomputed lazily when _dirty is set.
        self._dirty = True
        self._scale = float(tile_size)
        self._ox = 0.0
        self._oy = 0.0

        # Optional world bounds (in tiles) for clamping: (min_x, min_y, max_x, max_y).
        self._bounds: Optional[Tuple[float, float, float, float]] = None

    # -- properties -------------------------------------------------------

    @property
    def center(self) -> Tuple[float, float]:
        return (self._cx, self._cy)

    @property
    def zoom(self) -> float:
        return self._zoom

    @zoom.setter
    def zoom(self, value: float):
        value = max(self.MIN_ZOOM, min(self.MAX_ZOOM, value))
        if value != self._zoom:
            self._zoom = value
            self._dirty = True

    def zoom_by(self, factor: float):
        """Multiply zoom by `factor` (e.g. 1.1 to zoom in, 0.9 to zoom out)."""
        self.zoom = self._zoom * factor

    # -- configuration ----------------------------------------------------

    def set_center(self, cx: float, cy: float):
        """Center the camera on render-frame tile coordinate (cx, cy)."""
        if cx != self._cx or cy != self._cy:
            self._cx = cx
            self._cy = cy
            self._dirty = True
        if self._bounds is not None:
            self._clamp_center()

    def resize(self, screen_w: int, screen_h: int):
        """Update the viewport size (e.g. when the virtual canvas changes)."""
        if screen_w != self.screen_w or screen_h != self.screen_h:
            self.screen_w = screen_w
            self.screen_h = screen_h
            self._dirty = True

    def set_bounds(self, min_x: float, min_y: float, max_x: float, max_y: float):
        """Constrain the visible area to a world rectangle (in tiles).

        Mirrors Preagonal's SetPosition(campos, bounds): once set, the camera
        won't scroll past the world edge as long as the world is larger than the
        viewport. If the world is smaller than the viewport it stays centered.
        """
        self._bounds = (min_x, min_y, max_x, max_y)
        self._clamp_center()

    def clear_bounds(self):
        self._bounds = None

    # -- transform --------------------------------------------------------

    def _recompute(self):
        self._scale = self.tile_size * self._zoom
        self._ox = self.screen_w * 0.5 - self._cx * self._scale
        self._oy = self.screen_h * 0.5 - self._cy * self._scale
        self._dirty = False

    def world_to_screen(self, wx: float, wy: float) -> Tuple[float, float]:
        """Render-frame tile coords -> screen pixel coords."""
        if self._dirty:
            self._recompute()
        return (wx * self._scale + self._ox, wy * self._scale + self._oy)

    def screen_to_world(self, sx: float, sy: float) -> Tuple[float, float]:
        """Screen pixel coords -> render-frame tile coords (for mouse picking)."""
        if self._dirty:
            self._recompute()
        return ((sx - self._ox) / self._scale, (sy - self._oy) / self._scale)

    @property
    def scale(self) -> float:
        """Effective pixels-per-tile (tile_size * zoom)."""
        if self._dirty:
            self._recompute()
        return self._scale

    @property
    def origin(self) -> Tuple[float, float]:
        """Screen-space position of render-frame tile (0, 0)."""
        if self._dirty:
            self._recompute()
        return (self._ox, self._oy)

    def visible_tile_range(self) -> Tuple[int, int, int, int]:
        """Inclusive (min_tx, min_ty, max_tx, max_ty) of tiles touching the view.

        Lets renderers cull tiles outside the viewport instead of iterating a
        whole 64x64 (or larger GMAP) board every frame.
        """
        left, top = self.screen_to_world(0, 0)
        right, bottom = self.screen_to_world(self.screen_w, self.screen_h)
        import math
        return (math.floor(left), math.floor(top),
                math.ceil(right), math.ceil(bottom))

    # -- helpers ----------------------------------------------------------

    def _clamp_center(self):
        min_x, min_y, max_x, max_y = self._bounds
        half_w = self.screen_w / (2 * self.tile_size * self._zoom)
        half_h = self.screen_h / (2 * self.tile_size * self._zoom)

        world_w = max_x - min_x
        world_h = max_y - min_y

        if world_w <= 2 * half_w:
            cx = (min_x + max_x) / 2          # world narrower than view: center it
        else:
            cx = max(min_x + half_w, min(max_x - half_w, self._cx))
        if world_h <= 2 * half_h:
            cy = (min_y + max_y) / 2
        else:
            cy = max(min_y + half_h, min(max_y - half_h, self._cy))

        if cx != self._cx or cy != self._cy:
            self._cx = cx
            self._cy = cy
            self._dirty = True
