"""Liftable objects: the reference client's tile-pattern table.

A liftable object is NOT a tile type. The reference client carries a fixed
table of five 2x2 TILE-ID PATTERNS, the tiles that replace each one when it
comes off the ground, and the carry sprite to draw over the player's head
(``liftobj`` / ``liftobjreplace`` / ``liftsprites``, decompiled at
Preagonal/FourPlay/quattroplay/src/TInitStatics.cpp:1510-1523, driven by
``TPlayer::liftObjects`` at TPlayer.cpp:1926-1981).

Three consequences, all of which this client used to get wrong because it
modelled liftables as invented tile types (BUSH/POT/ROCK/SIGN) tagged by hand
into ``assets/tile_corrections.json``:

* **Glove power is an INDEX CEILING, not a per-object attribute.** The loop
  runs ``for i in 0 .. getGlovePower() + 1``, so a bare hand lifts rows 0-1,
  one glove adds row 2, and so on. There is no "rocks need power 1" rule
  anywhere; the row's POSITION is the rule.
* **An object is an exact 2x2 pattern**, matched at whichever of the four
  alignments puts the touched tile inside it. Four tiles must all match. A
  "3 of 4 tiles look like a bush" object does not exist, so neither does the
  partial-coverage fallback that the corrections overlay needed.
* **Lifting writes ``liftobjreplace``**, not grass. Each row has its own
  ground: the cut stump under a bush is not the tile under a pot.

The tables are classic-tileset (tilestype 0) knowledge, exactly like the art
they name. `match_lift_object` is pure and takes a tile reader, so it needs no
display and no client.
"""

from typing import Callable, List, NamedTuple, Optional, Sequence, Tuple

# Index order inside a row is COLUMN-major: the reference indexes it as
# `liftobj[i][offsetY + offsetX * 2]`, so the four entries are
# (0,0), (0,1), (1,0), (1,1) as (dx, dy).
_QUADRANTS: Tuple[Tuple[int, int], ...] = ((0, 0), (0, 1), (1, 0), (1, 1))

# TInitStatics.cpp:1517. Row order is the glove-power ladder.
LIFT_OBJECTS: Tuple[Tuple[int, int, int, int], ...] = (
    (0x002, 0x012, 0x003, 0x013),      # 0: reachable bare-handed
    (0x200, 0x210, 0x201, 0x211),      # 1: reachable bare-handed
    (0x2ac, 0x2bc, 0x2ad, 0x2bd),      # 2: needs glove power 1
    (0x022, 0x032, 0x023, 0x033),      # 3: needs glove power 2
    (0x3de, 0x3ee, 0x3df, 0x3ef),      # 4: needs glove power 3
)

# TInitStatics.cpp:1510. What the level shows once the object is picked up.
LIFT_REPLACE: Tuple[Tuple[int, int, int, int], ...] = (
    (0x2a5, 0x2b5, 0x2a6, 0x2b6),
    (0x70a, 0x71a, 0x70b, 0x71b),
    (0x6ea, 0x6fa, 0x6eb, 0x6fb),
    (0x72a, 0x73a, 0x72b, 0x73b),
    (0x72a, 0x73a, 0x72b, 0x73b),
)

# TInitStatics.cpp:1137. The sprite index carried over the player's head.
LIFT_SPRITES: Tuple[int, ...] = (0x105, 0x10b, 0x109, 0x107, 0x0ef)

# Names are OURS and cosmetic: the reference identifies a row by its index
# alone, and the carried object is drawn from its own tile ids either way.
# Only row 0 is confirmed - it is the bush pattern GServer-v2 also lists as a
# bush-item drop (PlayerClientPackets.cpp:112, tile 0x002). The rest are
# labelled by convention and never decide a rule; if one turns out to be a
# barrel rather than a pot, only this string changes.
LIFT_NAMES: Tuple[str, ...] = ("bush", "sign", "pot", "stone", "stone")

# TInitStatics.cpp:1506 (`bushobj`). The patterns a SWORD cuts, which is a
# different set from the ones a hand lifts - the plain bush is in both, the
# second one is cut-only.
BUSH_OBJECTS: Tuple[Tuple[int, int, int, int], ...] = (
    (0x002, 0x012, 0x003, 0x013),
    (0x1a4, 0x1b4, 0x1a5, 0x1b5),
)

# TInitStatics.cpp:1502 (`bushobjreplace`). The cut stump, per bush row. Row 0
# leaves the same ground a lifted bush does; row 1 has its own.
BUSH_REPLACE: Tuple[Tuple[int, int, int, int], ...] = (
    (0x2a5, 0x2b5, 0x2a6, 0x2b6),
    (0x2a7, 0x2b7, 0x2a8, 0x2b8),
)

# TInitStatics.cpp:1548 (`lifttestd`), indexed by direction (0=up, 1=left,
# 2=down, 3=right): the offset from the player's local position to the tile
# the lift probes. `bushtestd` and `laytest` hold the same four pairs.
LIFT_PROBE: Tuple[Tuple[float, float], ...] = (
    (1.5, 0.0), (-0.5, 2.0), (1.5, 4.0), (3.5, 2.0),
)


class LiftMatch(NamedTuple):
    """One matched object: which row, where its top-left corner sits."""

    index: int
    origin_x: int
    origin_y: int

    @property
    def tiles(self) -> Tuple[int, int, int, int]:
        return LIFT_OBJECTS[self.index]

    @property
    def replacement(self) -> Tuple[int, int, int, int]:
        return LIFT_REPLACE[self.index]

    @property
    def carry_sprite(self) -> int:
        return LIFT_SPRITES[self.index]

    @property
    def name(self) -> str:
        return LIFT_NAMES[self.index]

    def quadrants(self) -> List[Tuple[int, int, int, int]]:
        """(x, y, current tile id, replacement tile id) for all four tiles."""
        return [(self.origin_x + dx, self.origin_y + dy,
                 self.tiles[i], self.replacement[i])
                for i, (dx, dy) in enumerate(_QUADRANTS)]


def max_lift_index(glove_power: int) -> int:
    """Highest LIFT_OBJECTS row a player with this glove power can lift.

    `TPlayer::liftObjects` runs `for (i = 0; i <= getGlovePower() + 1; ++i)`,
    so power 0 already reaches row 1. Clamped to the table.
    """
    return max(0, min(int(glove_power) + 1, len(LIFT_OBJECTS) - 1))


def match_lift_object(read_tile: Callable[[int, int], int],
                      tile_x: int, tile_y: int,
                      glove_power: int) -> Optional[LiftMatch]:
    """The object the tile at (tile_x, tile_y) belongs to, or None.

    `read_tile(x, y)` returns a tile id in the same frame as the coordinates
    (world tiles for a gmap caller, level-local for a standalone one), and
    anything off the board. Rows are tried in table order, then the four
    alignments, exactly as the reference does.
    """
    tile = read_tile(tile_x, tile_y)
    for index in range(max_lift_index(glove_power) + 1):
        pattern = LIFT_OBJECTS[index]
        for corner, (dx, dy) in enumerate(_QUADRANTS):
            if pattern[corner] != tile:
                continue
            origin_x, origin_y = tile_x - dx, tile_y - dy
            if all(read_tile(origin_x + qx, origin_y + qy) == pattern[i]
                   for i, (qx, qy) in enumerate(_QUADRANTS)):
                return LiftMatch(index, origin_x, origin_y)
    return None


def match_bush(read_tile: Callable[[int, int], int],
               tile_x: int, tile_y: int) -> Optional[Tuple[int, int, int]]:
    """A sword-cuttable bush at (tile_x, tile_y): (row, origin_x, origin_y)."""
    tile = read_tile(tile_x, tile_y)
    for index, pattern in enumerate(BUSH_OBJECTS):
        for corner, (dx, dy) in enumerate(_QUADRANTS):
            if pattern[corner] != tile:
                continue
            origin_x, origin_y = tile_x - dx, tile_y - dy
            if all(read_tile(origin_x + qx, origin_y + qy) == pattern[i]
                   for i, (qx, qy) in enumerate(_QUADRANTS)):
                return (index, origin_x, origin_y)
    return None


def is_lift_tile(tile_id: int, glove_power: int = 3) -> bool:
    """True if the id appears in any liftable pattern this glove can reach.

    A cheap pre-filter only. It says nothing about the other three tiles, so
    the caller still has to match the pattern.
    """
    reachable: Sequence[Tuple[int, ...]] = \
        LIFT_OBJECTS[:max_lift_index(glove_power) + 1]
    return any(tile_id in row for row in reachable)
