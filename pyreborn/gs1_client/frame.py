"""Whole-map GS1 coordinates on a gmap, client side: the one boundary.

The reference client keeps every object on a gmap in its map cell (mapX,
mapY) with a position local to that cell, and a script sees the WHOLE-MAP
tile: an NPC's `x` reads ``local + (mapX << 6)`` and a write stores
``x - (mapX << 6)`` as the new local, in the same cell
(Preagonal/FourPlay/quattroplay/src/TServerNPCProperties.cpp:331-345). An
NPC on a segment joins the map with that segment's cell
(TServerLevel.cpp:931-957 updateMapPos, TServerNPC.cpp:316-324), and
`setlocalx` only stores the value (TGaniObject.cpp:1346-1358), so a write
that leaves 0..63 keeps the NPC's cell and an out-of-range local. Objects
the player's level owns (items, baddies) are placed at
``x - (level.mapX << 6)`` in that level (TServerLevel.cpp:1348-1351
putExtra).

This client keeps the same split: an NPC dict holds its local `x`/`y`, its
cell (`npc_handler.npc_cell`) and `world_x`/`world_y`; the player position,
`players[]`, `tiles[]`, the board probes and the layer images are already
whole-map while the player stands on a segment. The GS1 host converts NPC
and level-object positions here, and only here:

* a position a script READS gets the object's cell origin added
  (`npc_axis`, `npc_xy`, `level_object_xy`);
* a position a script WRITES is made relative to the object's cell
  (`write_npc_axis`); the cell itself never changes;
* a coordinate that PLACES an object in the player's level is made relative
  to that level (`to_level`).

Off a gmap, and for an NPC or level that is not a cell of the loaded gmap,
the origin is (0, 0) and every function returns what the host returned
before this module existed. Server-sent positions (props, NPC moves) never
come through here: they are local on the wire.
"""
from __future__ import annotations

from typing import Tuple

from reborn_protocol.coords import segment_origin
from reborn_protocol.gs1.host_shared import host_value
from reborn_protocol.gs1.values import to_num

from ..gmap_coords import grid_of
from ..npc_handler import npc_cell


def _write_npc_attr(npc, key, value):
    """Store a LOCAL-frame write to an NPC attribute (a server NPC move, or
    a script write off a gmap). x/y also move world_x/world_y by the same
    delta: the renderer, touch tests and collision all read the world pair
    first (render_collect._collect_npcs, npc_handler, runtime
    npc_image_rect), so a bare `x = 34.5;` used to change nothing on screen
    until the server re-stamped the position. The delta keeps whatever gmap
    segment offset the pair already carries."""
    if key in ("x", "y"):
        world_key = "world_" + key
        try:
            offset = float(npc[world_key]) - float(npc.get(key, 0))
        except (KeyError, TypeError, ValueError):
            offset = None
        npc[key] = value
        if offset is not None:
            npc[world_key] = to_num(value) + offset
        return
    npc[key] = value


def npc_origin(client, npc) -> Tuple[int, int]:
    """The whole-map tile of the NPC's cell corner. The cell is the NPC's
    stored cell props whether or not the .gmap has loaded (the reference
    sets mapX straight from props 0x29/0x2a, TServerNPC.cpp:1271-1282), else
    the cell of the segment it names in a loaded grid; (0, 0) for an NPC with
    neither (the same rule `place_npc` uses to set world_x/world_y)."""
    if client is None or not isinstance(npc, dict):
        return 0, 0
    cell = npc_cell(client.gmap_grid, npc)
    if cell is None:
        return 0, 0
    return segment_origin(*cell)


def npc_map_owned(client, npc) -> bool:
    """Whether the reference holds this NPC in a map (its `m_ganiObject_unknown56`
    is set, TServerNPC.cpp:318). That is the NPC's own `_map_owned` mark,
    set from the owner's name when the NPC arrives (handlers/entities.py), or
    a segment of the loaded grid: loading the map re-adds every NPC of a
    segment to the map (TServerLevel.cpp:951-953). Before the grid exists an
    NPC of a plain segment is not map-owned."""
    if npc.get("_map_owned"):
        return True
    return grid_of(client.gmap_grid, npc.get("_level")) is not None


def npc_axis(client, npc, key):
    """What a script reads for the NPC's `x` or `y` (`key`)."""
    ox, oy = npc_origin(client, npc)
    origin = oy if key == "y" else ox
    value = npc.get(key, 0)
    if not origin:
        return host_value(value)
    return to_num(value) + origin


def npc_xy(client, npc) -> Tuple[float, float]:
    """The NPC's whole-map (x, y) as numbers, for queries that compare it
    with script coordinates."""
    ox, oy = npc_origin(client, npc)
    return to_num(npc.get("x", 0)) + ox, to_num(npc.get("y", 0)) + oy


def write_npc_axis(client, npc, key, value) -> None:
    """A script write of the NPC's `x` or `y`: local = value - cell origin,
    world = value, cell unchanged (TServerNPCProperties.cpp:334-345). The
    write applies only when the NPC is map-owned or the value is a tile of a
    plain level, 0 <= value < 64 (TServerNPCProperties.cpp:336, :343);
    otherwise it is ignored. Applied or ignored, the NPC's queued server
    moves are dropped (`removeNPCMoves()` after the gate,
    TServerNPCProperties.cpp:338, :345)."""
    ox, oy = npc_origin(client, npc)
    origin = oy if key == "y" else ox
    whole = to_num(value)
    npc.pop("_move_queue", None)
    if not (npc_map_owned(client, npc) or 0 <= whole < 64):
        return
    if not origin:
        _write_npc_attr(npc, key, value)
        return
    npc[key] = whole - origin
    npc["world_" + key] = whole


def level_origin(client) -> Tuple[int, int]:
    """The whole-map tile of the player's level corner (the reference's
    `level.mapX << 6`); (0, 0) off a segment."""
    if client is None or not client.in_gmap_segment:
        return 0, 0
    cell = grid_of(client.gmap_grid, client._current_level_name)
    return segment_origin(*cell) if cell is not None else (0, 0)


def level_object_xy(client, obj) -> Tuple[float, float]:
    """Whole-map (x, y) of an object stored level-local in the player's
    level (a baddy)."""
    ox, oy = level_origin(client)
    return to_num(obj.get("x", 0)) + ox, to_num(obj.get("y", 0)) + oy


def to_level(client, x, y) -> Tuple[float, float]:
    """Whole-map (x, y) -> relative to the player's level (may leave
    0..63, like putExtra's local)."""
    ox, oy = level_origin(client)
    return x - ox, y - oy


def board_probe(client, x, y) -> Tuple[float, float]:
    """A board probe (`is_water_at`) for a whole-map point: unchanged on a
    segment, where the probes are whole-map, and wrapped into the level
    otherwise, as the callers always did."""
    if client is not None and client.in_gmap_segment:
        return x, y
    return x % 64, y % 64
