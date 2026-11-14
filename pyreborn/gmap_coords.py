"""Gmap grid lookups and wire-to-world conversion: the one implementation.

`reborn_protocol.coords` owns the frame arithmetic (segment of a world value,
segment origin, local <-> world for a known cell). This module adds the part
that needs the client's loaded grid, ``{(grid_x, grid_y): level_name}``
(`GmapState.gmap_grid`). Every caller used to re-derive it inline. The
level-name -> cell reverse scan alone had 17 copies, and the copies did not
agree on duplicate names.

All functions are pure over explicit inputs. They take the grid mapping, not
a Client, so they are unit-testable alone and work with the lightweight fakes
the tests and harnesses pass around. A ``None`` grid counts as "no gmap
loaded" (empty).

Rules, with their reference:

* A level name resolves to its FIRST cell in row-major (file) order. The
  reference client looks the name up with ``TStringList::indexOf``
  (FourPlay quattroplay/src/unsorted.cpp:1014-1020 getLevelPos), and the
  reference server's ``string_map::insert`` keeps the first entry
  (GServer-v2 server/src/level/Map.cpp:65). `load_gmap` fills the grid in
  that same order, so dict iteration order is file order.
* The match is case-insensitive. The reference server lower-cases every
  name it puts in the grid (GServer-v2 server/src/level/Map.cpp:67-68, :154,
  :193, :337) and the reference client lower-cases the name it looks up
  (FourPlay quattroplay/src/unsorted.cpp:1014-1020, TClient.cpp:1281-1282,
  :1354). The grid keeps the spelling the .gmap file used, because that
  spelling goes back to the server (`request_level`); only the COMPARISON
  folds (`fold`: ASCII `lower()`, as the references do, not `casefold()`).
  `in_grid`, `same_level` and `get_ci` are the same comparison for a name, a
  pair of names and a dict keyed by level name.
* A level that is not a segment (an interior, an unknown name, or no gmap at
  all) has no cell. Position conversions then leave the value unchanged,
  because that level's local frame IS the client's frame.
* Whether to look a level up at all is the caller's decision. A client that
  stands in an interior while a grid is still loaded (`is_gmap` True,
  `in_gmap_segment` False) is in that interior's local frame. Callers that
  convert the LOCAL player's frame gate on `in_gmap_segment` and pass an
  empty grid otherwise.
"""

from __future__ import annotations

from typing import Dict, Mapping, Optional, Tuple

from reborn_protocol.coords import (
    LEVEL_SIZE, local_to_world, segment_at, segment_origin,
)

Cell = Tuple[int, int]
Grid = Mapping[Cell, str]

__all__ = [
    'Cell', 'Grid', 'fold', 'same_level', 'in_grid', 'get_ci', 'has_level', 'grid_of',
    'grid_index', 'LevelIndex', 'level_at', 'level_origin', 'origin_at', 'world_from_local',
    'local_from_world', 'world_from_wire', 'position_is_local',
]

_MISSING = object()


def fold(name):
    """The comparison key of a level name: ASCII lower case. A value that is
    not a string is returned as it is."""
    return name.lower() if isinstance(name, str) else name


def same_level(a, b) -> bool:
    """Whether two level names are one level, whatever their case."""
    return fold(a) == fold(b)


def in_grid(grid: Optional[Grid], level) -> bool:
    """Whether `level` names a segment of `grid` (False when there is no grid
    or no name)."""
    if not grid or not level:
        return False
    wanted = fold(level)
    return any(fold(name) == wanted for name in grid.values())


def get_ci(mapping, name, default=None):
    """`mapping[name]` for a dict keyed by level name: the exact spelling
    first, else the first key that folds to the same name."""
    if name in mapping:
        return mapping[name]
    wanted = fold(name)
    for key, value in mapping.items():
        if fold(key) == wanted:
            return value
    return default


def has_level(mapping, name) -> bool:
    """`name in mapping`, ignoring case (see `get_ci`)."""
    return get_ci(mapping, name, _MISSING) is not _MISSING


def grid_of(grid: Optional[Grid], level, *,
            casefold: bool = True) -> Optional[Cell]:
    """Grid cell of segment `level`: its first cell, or None when `level` is
    empty or not a segment of `grid` (including no gmap loaded). Case is
    ignored unless `casefold` is False."""
    if not grid or not level:
        return None
    wanted = fold(level) if casefold else level
    for cell, name in grid.items():
        if (fold(name) if casefold else name) == wanted:
            return cell
    return None


class LevelIndex(dict):
    """A name -> cell dict that ignores the case of the name it is asked
    about: its keys are stored folded, and `get`, `[]` and `in` fold the
    probe. Iteration yields the folded names."""

    def __getitem__(self, name):
        return dict.__getitem__(self, fold(name))

    def get(self, name, default=None):
        return dict.get(self, fold(name), default)

    def __contains__(self, name):
        return dict.__contains__(self, fold(name))


def grid_index(grid: Optional[Grid], *,
               casefold: bool = True) -> Dict[str, Cell]:
    """Level name -> cell for every segment, first cell winning like
    `grid_of`. The result ignores the case of the name it is asked about
    (`LevelIndex`) unless `casefold` is False. For callers that resolve many
    names per pass (a frame's entity collection); a single lookup should call
    `grid_of`."""
    index: Dict[str, Cell] = LevelIndex() if casefold else {}
    for cell, name in (grid or {}).items():
        index.setdefault(fold(name) if casefold else name, cell)
    return index


def level_at(grid: Optional[Grid], world_x: float,
             world_y: float) -> Optional[str]:
    """Segment whose board holds world position (x, y), or None for a hole
    in the grid, a position off its edge, or no gmap loaded."""
    if not grid:
        return None
    return grid.get(segment_at(world_x, world_y))


def level_origin(grid: Optional[Grid], level) -> Tuple[int, int]:
    """World origin of segment `level`; (0, 0) when it is not a segment."""
    cell = grid_of(grid, level)
    return segment_origin(*cell) if cell is not None else (0, 0)


def origin_at(world_x: float, world_y: float) -> Tuple[int, int]:
    """World origin of the segment that world position (x, y) falls in,
    whatever level the grid names there (floor, so negatives are right)."""
    return segment_origin(*segment_at(world_x, world_y))


def world_from_local(grid: Optional[Grid], level, x: float,
                     y: float) -> Tuple[float, float]:
    """World position of level-local (x, y) on segment `level`. The value is
    not wrapped: a local just past an edge (70.25, -1.5) is legitimate. A
    level that is not a segment returns (x, y) unchanged."""
    cell = grid_of(grid, level)
    if cell is None:
        return x, y
    return local_to_world(x, y, *cell)


def local_from_world(grid: Optional[Grid], level, x: float,
                     y: float) -> Tuple[float, float]:
    """Level-local position of world (x, y) measured from segment `level`'s
    origin, unwrapped (the reference client's ``world - (mapX << 6)``).
    A level that is not a segment returns (x, y) unchanged."""
    ox, oy = level_origin(grid, level)
    return x - ox, y - oy


def world_from_wire(raw: float, origin: float) -> float:
    """One axis of a wire position: the level-local `raw` plus the segment
    `origin`.

    NPC X/Y and X2/Y2 are always level-local: the reference server keeps
    them in the NPC's local pixel position and sends its cell separately in
    GMAPLEVELX/Y (GServer-v2 server/include/object/NPC.h:668-669, :702-703).
    The reference client adds ``mapX << 6`` to the local value it stores,
    whatever its size (FourPlay quattroplay/src/TServerNPC.cpp:330), so a
    value outside 0..63 is a position just past the segment's edge, never a
    world value. Callers recompute from the stored local value, so a re-run
    does not add the origin twice."""
    return raw + origin


def position_is_local(x: float, y: float) -> bool:
    """Whether the local player's position still reads as level-local when a
    .gmap finishes loading. PLO_PLAYERWARP2 lands before the file, so the
    coordinates it set are local until `load_gmap` folds the spawn origin
    in. Both axes below LEVEL_SIZE; no lower bound (a local just past the
    top/left edge is still local)."""
    return x < LEVEL_SIZE and y < LEVEL_SIZE
