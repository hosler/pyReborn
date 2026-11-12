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
* The match is exact by default. Both references compare lower-cased names.
  This client keeps level names in the spelling the server sent and compares
  them exactly everywhere else (`in_gmap_segment`, the warp handlers), so the
  library stays exact until those change together. ``casefold=True`` is the
  reference comparison. The QA harness uses it.
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
    'Cell', 'Grid', 'grid_of', 'grid_index', 'level_at', 'level_origin',
    'origin_at', 'world_from_local', 'local_from_world', 'world_from_wire',
    'position_is_local',
]


def _key(name, casefold: bool):
    if casefold and isinstance(name, str):
        return name.casefold()
    return name


def grid_of(grid: Optional[Grid], level, *,
            casefold: bool = False) -> Optional[Cell]:
    """Grid cell of segment `level`: its first cell, or None when `level` is
    empty or not a segment of `grid` (including no gmap loaded)."""
    if not grid or not level:
        return None
    wanted = _key(level, casefold)
    for cell, name in grid.items():
        if _key(name, casefold) == wanted:
            return cell
    return None


def grid_index(grid: Optional[Grid], *,
               casefold: bool = False) -> Dict[str, Cell]:
    """Level name -> cell for every segment, first cell winning like
    `grid_of`. For callers that resolve many names per pass (a frame's
    entity collection); a single lookup should call `grid_of`."""
    index: Dict[str, Cell] = {}
    for cell, name in (grid or {}).items():
        index.setdefault(_key(name, casefold), cell)
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
    """One axis of an NPC wire position, tolerating either frame.

    A value inside 0..63 is taken as level-local and gets the segment
    `origin` added. A value at or past LEVEL_SIZE, or below 0, is taken as
    already world and passed through. That keeps a re-run idempotent
    (`_update_npc_world_coords` after the grid reloads) and accepted servers
    that sent NPC X2/Y2 in the world frame. Players do NOT use this: their
    X2/Y2 are always level-local (see handlers/entities.py)."""
    if raw >= LEVEL_SIZE or raw < 0:
        return raw
    return raw + origin


def position_is_local(x: float, y: float) -> bool:
    """Whether the local player's position still reads as level-local when a
    .gmap finishes loading. PLO_PLAYERWARP2 lands before the file, so the
    coordinates it set are local until `load_gmap` folds the spawn origin
    in. Both axes below LEVEL_SIZE; no lower bound (a local just past the
    top/left edge is still local)."""
    return x < LEVEL_SIZE and y < LEVEL_SIZE
