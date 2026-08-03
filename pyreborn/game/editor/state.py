"""game/editor/state.py — the level editor's pure state: tools, brush, undo.

Deliberately free of pygame, the network and GameClient: everything here is
tile arithmetic over plain lists, so the editing rules are unit-testable
without a display or a server. `editor.py` owns the IO and drives this.

The undo stack stores whole rectangles (before AND after tiles) rather than
per-tile deltas. A board edit travels the wire as one PLI_BOARDMODIFY
rectangle, so an undo step that matches that rectangle replays as exactly one
packet, and a stroke that painted the same tile twice still undoes once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# Tools, in the order the toolbar shows them (keys 1..5).
PAINT, RECT, PICKER, SELECT, OBJECT = "paint", "rect", "picker", "select", "object"
TOOLS = (PAINT, RECT, PICKER, SELECT, OBJECT)

# What the object tool places. Signs, chests and links are per-level file
# objects; NPCs are live server entities (see editor.py for who applies what).
OBJECT_KINDS = ("npc", "sign", "chest", "link")

LEVEL_SIZE = 64
MAX_UNDO = 200
MAX_BRUSH = 8


@dataclass
class BoardEdit:
    """One rectangular board change, and how to put it back.

    `before` and `after` are row-major tile ids of a w*h rectangle at (x, y)
    in LEVEL-LOCAL coordinates, which is the frame PLI_BOARDMODIFY speaks.
    """

    level: str
    x: int
    y: int
    w: int
    h: int
    before: List[int]
    after: List[int]

    def inverse(self) -> "BoardEdit":
        return BoardEdit(self.level, self.x, self.y, self.w, self.h,
                         list(self.after), list(self.before))

    def is_noop(self) -> bool:
        return self.before == self.after


def _clamp_tile(value: int) -> int:
    return max(0, min(LEVEL_SIZE - 1, int(value)))


@dataclass
class EditorState:
    """Everything the editor remembers between frames."""

    enabled: bool = False
    tool: str = PAINT
    tile: int = 0                      # the brush tile id
    brush: int = 1                     # brush square edge, in tiles
    object_kind: str = "npc"
    grid_visible: bool = True
    palette_visible: bool = False
    selection: Optional[Tuple[int, int, int, int]] = None   # x, y, w, h
    status: str = ""
    undo_stack: List[BoardEdit] = field(default_factory=list)
    redo_stack: List[BoardEdit] = field(default_factory=list)
    # Tiles touched by the stroke in progress: (x, y) -> tile id before it.
    _stroke: Dict[Tuple[int, int], int] = field(default_factory=dict)
    _stroke_level: str = ""

    # -- tool selection ---------------------------------------------------

    def set_tool(self, tool: str) -> None:
        if tool in TOOLS:
            self.tool = tool

    def cycle_object_kind(self, step: int = 1) -> None:
        idx = (OBJECT_KINDS.index(self.object_kind) + step) % len(OBJECT_KINDS)
        self.object_kind = OBJECT_KINDS[idx]

    def adjust_brush(self, delta: int) -> None:
        self.brush = max(1, min(MAX_BRUSH, self.brush + delta))

    # -- brush geometry ---------------------------------------------------

    def brush_tiles(self, x: int, y: int) -> List[Tuple[int, int]]:
        """The tiles a brush centred on (x, y) covers, clipped to the level.

        An even-sized brush cannot be centred exactly, so it extends right and
        down - the same bias every tile editor uses, and the one that makes a
        2x2 brush paint the tile actually under the cursor.
        """
        half = self.brush // 2
        left, top = int(x) - half, int(y) - half
        return [(tx, ty)
                for ty in range(top, top + self.brush)
                for tx in range(left, left + self.brush)
                if 0 <= tx < LEVEL_SIZE and 0 <= ty < LEVEL_SIZE]

    # -- strokes ----------------------------------------------------------

    def begin_stroke(self, level: str) -> None:
        self._stroke = {}
        self._stroke_level = level

    def stroke_point(self, x: int, y: int, read_tile: Callable[[int, int], int]
                     ) -> List[Tuple[int, int]]:
        """Record the brush at (x, y) and return the tiles to paint now.

        Only tiles not already in this stroke come back, so dragging over the
        same spot neither repaints nor loses the ORIGINAL tile under it - the
        first value seen for a tile is the one undo restores.
        """
        fresh = []
        for tx, ty in self.brush_tiles(x, y):
            if (tx, ty) not in self._stroke:
                self._stroke[(tx, ty)] = read_tile(tx, ty)
                fresh.append((tx, ty))
        return fresh

    def end_stroke(self, read_tile: Callable[[int, int], int]
                   ) -> Optional[BoardEdit]:
        """Close the stroke into one undoable rectangle, or None if empty."""
        if not self._stroke:
            return None
        touched = self._stroke
        self._stroke = {}
        xs = [x for x, _ in touched]
        ys = [y for _, y in touched]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        w, h = x1 - x0 + 1, y1 - y0 + 1

        before: List[int] = []
        after: List[int] = []
        for ty in range(y0, y0 + h):
            for tx in range(x0, x0 + w):
                # A tile inside the bounding box that the stroke never touched
                # keeps its current value on BOTH sides, so replaying the
                # rectangle leaves it alone.
                current = read_tile(tx, ty)
                before.append(touched.get((tx, ty), current))
                after.append(current)
        edit = BoardEdit(self._stroke_level, x0, y0, w, h, before, after)
        return None if edit.is_noop() else edit

    # -- rectangle fill ---------------------------------------------------

    def rect_edit(self, level: str, x0: int, y0: int, x1: int, y1: int,
                  read_tile: Callable[[int, int], int]) -> Optional[BoardEdit]:
        """A filled rectangle of the brush tile between two corners."""
        x0, x1 = sorted((_clamp_tile(x0), _clamp_tile(x1)))
        y0, y1 = sorted((_clamp_tile(y0), _clamp_tile(y1)))
        w, h = x1 - x0 + 1, y1 - y0 + 1
        before = [read_tile(tx, ty)
                  for ty in range(y0, y0 + h) for tx in range(x0, x0 + w)]
        after = [self.tile] * (w * h)
        edit = BoardEdit(level, x0, y0, w, h, before, after)
        return None if edit.is_noop() else edit

    # -- undo / redo ------------------------------------------------------

    def push_undo(self, edit: BoardEdit) -> None:
        self.undo_stack.append(edit)
        del self.undo_stack[:-MAX_UNDO]
        # A fresh edit invalidates the redo branch, as in every editor.
        self.redo_stack.clear()

    def undo(self) -> Optional[BoardEdit]:
        """Pop an edit and return the change that REVERSES it."""
        if not self.undo_stack:
            return None
        edit = self.undo_stack.pop()
        self.redo_stack.append(edit)
        return edit.inverse()

    def redo(self) -> Optional[BoardEdit]:
        if not self.redo_stack:
            return None
        edit = self.redo_stack.pop()
        self.undo_stack.append(edit)
        return edit

    # -- selection --------------------------------------------------------

    def set_selection(self, x0: int, y0: int, x1: int, y1: int) -> None:
        x0, x1 = sorted((_clamp_tile(x0), _clamp_tile(x1)))
        y0, y1 = sorted((_clamp_tile(y0), _clamp_tile(y1)))
        self.selection = (x0, y0, x1 - x0 + 1, y1 - y0 + 1)

    def clear_selection(self) -> None:
        self.selection = None

    def selection_tiles(self, read_tile: Callable[[int, int], int]
                        ) -> Optional[Tuple[int, int, List[int]]]:
        """(w, h, tiles) for the current selection, for copy."""
        if self.selection is None:
            return None
        x, y, w, h = self.selection
        return w, h, [read_tile(tx, ty)
                      for ty in range(y, y + h) for tx in range(x, x + w)]

    def paste_edit(self, level: str, x: int, y: int, w: int, h: int,
                   tiles: Sequence[int],
                   read_tile: Callable[[int, int], int]) -> Optional[BoardEdit]:
        """Stamp `tiles` at (x, y), clipped to the level edges."""
        x, y = _clamp_tile(x), _clamp_tile(y)
        # The clipped size is what gets stamped, but the SOURCE stride stays
        # the copied width - indexing the clipped width would shear the paste
        # diagonally against the level's right edge.
        src_w = w
        w = min(w, LEVEL_SIZE - x)
        h = min(h, LEVEL_SIZE - y)
        if w <= 0 or h <= 0:
            return None
        before, after = [], []
        for row in range(h):
            for col in range(w):
                before.append(read_tile(x + col, y + row))
                after.append(int(tiles[row * src_w + col]))
        edit = BoardEdit(level, x, y, w, h, before, after)
        return None if edit.is_noop() else edit
