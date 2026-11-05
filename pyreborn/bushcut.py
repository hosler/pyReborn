"""Classic bush matching and probes from the official client's tile tables."""

import math
from typing import Callable, Optional, Tuple

from .liftobjects import BUSH_OBJECTS as _BUSH_OBJECTS
from .liftobjects import BUSH_REPLACE as _BUSH_REPLACE
from .liftobjects import LIFT_OBJECTS, LIFT_PROBE, LIFT_REPLACE

# TInitStatics.cpp:1506-1509 (bushobj), column-major: xOffset*2+yOffset.
# Row zero is also liftobj[0] (:1517); reuse the existing cut-only row too.
BUSH_OBJECTS = (LIFT_OBJECTS[0], _BUSH_OBJECTS[1])
# TInitStatics.cpp:1502-1505 (bushobjreplace); row zero = liftobjreplace[0].
BUSH_REPLACE = (LIFT_REPLACE[0], _BUSH_REPLACE[1])
# TInitStatics.cpp:1542-1547 (bushtestd), identical to lifttestd (:1548).
BUSH_PROBE = LIFT_PROBE
# TServerLevel.cpp:86-91 (explotestd), in the original traversal order.
_PROBE_EPSILON = 0.0001
EXPLOSION_PROBE = ((0.5, 0.5), (1.5, 0.5), (0.5, 1.5), (1.5, 1.5))


def bush_probe(local_x: float, local_y: float, direction: int) -> Tuple[int, int]:
    """TPlayer.cpp:2318-2323; DOUBLE_00402440 is the 0.0001 epsilon
    (TInitStatics.cpp:1266), not a rounding half."""
    dx, dy = BUSH_PROBE[direction]
    return (math.floor(local_x + dx + _PROBE_EPSILON),
            math.floor(local_y + dy + _PROBE_EPSILON))


def find_bush_block(tiles_getter: Callable[[int, int], int],
                    tile_x: int, tile_y: int) -> Optional[Tuple[int, int, int]]:
    """Return (start_x, start_y, bush_index), as TPlayer.cpp:2312-2362.

    Every read stays within this level's 0..63 board, including at seams.
    """
    if not (0 <= tile_x <= 63 and 0 <= tile_y <= 63):
        return None
    tile = tiles_getter(tile_x, tile_y)
    for bush_index, pattern in enumerate(BUSH_OBJECTS):
        for x_offset in range(2):
            for y_offset in range(2):
                if tile != pattern[x_offset * 2 + y_offset]:
                    continue
                start_x, start_y = tile_x - x_offset, tile_y - y_offset
                next_x, next_y = start_x + 1, start_y + 1
                if not (0 <= start_x <= 63 and 0 <= start_y <= 63):
                    continue
                if not (0 <= next_x <= 63 and 0 <= next_y <= 63):
                    continue
                if (tiles_getter(start_x, start_y) == pattern[0]
                        and tiles_getter(start_x, next_y) == pattern[1]
                        and tiles_getter(next_x, start_y) == pattern[2]
                        and tiles_getter(next_x, next_y) == pattern[3]):
                    return start_x, start_y, bush_index
    return None
