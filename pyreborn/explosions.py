"""Classic explosion cells and board effects, without presentation state.

Pure geometry. The client simulation (client_combat.py) applies it: fuse,
chain detonation (TServerLevel.cpp:1497-1500) and damage to the local player
(TExplosion.cpp:62-91) all run in the client, as in the reference.
"""

from dataclasses import dataclass
from typing import Optional, Tuple

from reborn_protocol.coords import in_level_bounds

from .bushcut import BUSH_OBJECTS, BUSH_REPLACE, EXPLOSION_PROBE
from .liftobjects import LIFT_OBJECTS, LIFT_REPLACE

# TServerLevel.cpp:60-70: expsprites, rows indexed by explosion direction.
EXPLOSION_SPRITES = (
    (0x116, 0x117, 0x118, 0x119),
    (0x11a, 0x11b, 0x11c, 0x11d),
    (0x12a, 0x12e, 0x132, 0x136),
    (0x12b, 0x12f, 0x133, 0x137),
    (0x11e, 0x11f, 0x120, 0x121),
    (0x122, 0x123, 0x124, 0x125),
    (0x126, 0x127, 0x128, 0x129),
    (0x12c, 0x130, 0x134, 0x138),
    (0x12d, 0x131, 0x135, 0x139),
)
ARM_SPRITE_ROWS = ((6, 1, 0), (8, 3, 2), (0, 5, 6), (2, 7, 8))  # TServerLevel.cpp:73
ARM_STEP = ((0, -2), (-2, 0), (0, 2), (2, 0))  # TServerLevel.cpp:80
BUSH_LEAPS = (1, 0, 3, 2, 2, 2, 0, 2)  # TServerLevel.cpp:56
CENTER_ROW = 4  # TServerLevel.cpp:1620
EXPLOSION_TICKS = 11  # TServerLevel.cpp:1606; zero is visible too, TExplosion.cpp:102.
MAX_RADIUS = 15  # TServerLevel.cpp:1616
SUPERBOMB_OFFSET = 2.0  # TServerLevel.cpp:1712; TInitStatics.cpp:1277.
SUPERBOMB_CENTER_RADIUS = 4  # TServerLevel.cpp:1720
BOMB_RADIUS = 2  # TServerLevel.cpp:1724
HIT_HALF_EXTENT = 1.0  # TExplosion.cpp:66; TInitStatics.cpp:1226.


@dataclass(frozen=True)
class ExplosionCell:
    """One putExplosion object (TServerLevel.cpp:1600-1608)."""

    x: float
    y: float
    sprite_row: int


@dataclass(frozen=True)
class BlastBlock:
    """One board patch and its effects (TServerLevel.cpp:1533-1585)."""

    start_x: int
    start_y: int
    replacement_column_major: Tuple[int, int, int, int]
    leap_type: Optional[int]
    bush_index: Optional[int] = None


def bomb_crosses(x, y, bomb_type):
    # TServerLevel.cpp:1710-1724: corner order precedes the larger centre.
    if bomb_type == 2:
        d = SUPERBOMB_OFFSET
        return [(x - d, y - d, BOMB_RADIUS), (x + d, y - d, BOMB_RADIUS),
                (x - d, y + d, BOMB_RADIUS), (x + d, y + d, BOMB_RADIUS),
                (x, y, SUPERBOMB_CENTER_RADIUS)]
    return [(x, y, BOMB_RADIUS)]


def cross_cells(x, y, radius):
    # TServerLevel.cpp:1616-1641: centre, then each arm's interior and tip.
    radius = min(int(radius), MAX_RADIUS)
    cells = [ExplosionCell(x, y, CENTER_ROW)]
    for direction, (dx, dy) in enumerate(ARM_STEP):
        for distance in range(1, radius):
            cells.append(ExplosionCell(x + dx * distance, y + dy * distance,
                                       ARM_SPRITE_ROWS[direction][1]))
        cells.append(ExplosionCell(x + dx * radius, y + dy * radius,
                                   ARM_SPRITE_ROWS[direction][2]))
    return cells


def explosion_sprite(sprite_row):
    return EXPLOSION_SPRITES[sprite_row][0]  # TServerLevel.cpp:1607


def order_point_y(cell_y, order_offset, ticks_left):
    # TExplosion.cpp:28-29; TInitStatics.cpp:1277 (2.0).
    return cell_y + order_offset + 2.0 + ticks_left / 5.0


def explosion_sound(bomb_type):
    return 'thunder.wav' if bomb_type == 3 else 'bomb.wav'  # TServerLevel.cpp:1697


def explosion_damage(bomb_type):
    # TExplosion.cpp:86; TInitStatics.cpp:1274 (1.0), TInitStatics.cpp:1253 (0.5).
    return 1.0 if bomb_type == 3 else 0.5


def hits_player(cell_x, cell_y, player_x, player_y):
    # TExplosion.cpp:54-72; TInitStatics.cpp:1274-1278 (centre offsets).
    return (abs(cell_x + 1.0 - (player_x + 1.5)) <= HIT_HALF_EXTENT
            and abs(cell_y + 1.0 - (player_y + 2.0)) <= HIT_HALF_EXTENT)


def knockback(sprite_row):
    # TExplosion.cpp:89-90; TInitStatics.cpp:1159 (explodir), TInput.cpp:13 (movevec).
    # explodir has 5 entries but arm cells use sprite rows up to 8
    # (TInitStatics.cpp:1159): the reference reads past the array there, which
    # is unspecified. Fall back to the centre's direction for those rows.
    direction = (0, 1, 2, 3, 0)[sprite_row] if sprite_row < 5 else 0
    return ((0.0, -1.0), (-1.0, 0.0), (0.0, 1.0), (1.0, 0.0))[direction]


def board_blocks_at(tiles_getter, tilestype, local_x, local_y):
    """PutExplosion's probe loop on one local board (TServerLevel.cpp:1505-1590).

    An overlay models immediate modifyBoard writes between probes while leaving
    the supplied board untouched. Each matched block therefore appears once.
    """
    blocks = []
    patched = {}

    def read(x, y):
        return patched[(x, y)] if (x, y) in patched else tiles_getter(x, y)

    def matches(x, y, pattern):
        # TServerLevel.cpp:218-227: bounds and column-major comparison.
        return (in_level_bounds(x, y) and in_level_bounds(x + 1, y + 1)
                and all(read(x + dx, y + dy) == pattern[dx * 2 + dy]
                        for dx in range(2) for dy in range(2)))

    def classic_block(tx, ty, tile):
        # TServerLevel.cpp:1547-1590: bushes first, then all five lift rows.
        for patterns, replacements, bushes in (
                (BUSH_OBJECTS, BUSH_REPLACE, True),
                (LIFT_OBJECTS, LIFT_REPLACE, False)):
            for index, pattern in enumerate(patterns):
                for dx in range(2):
                    for dy in range(2):
                        if pattern[dx * 2 + dy] != tile:
                            continue
                        sx, sy = tx - dx, ty - dy
                        if matches(sx, sy, pattern):
                            leap = index if bushes else index + 2 if index < 2 else None
                            return BlastBlock(sx, sy, replacements[index], leap,
                                              index if bushes else None)
                        break
        return None

    for dx, dy in EXPLOSION_PROBE:
        # TServerLevel.cpp:1505-1508: cast truncates before unsigned bounds test.
        tx, ty = int(local_x + dx), int(local_y + dy)
        if not in_level_bounds(tx, ty):
            continue
        tile = read(tx, ty)
        block = None
        if tilestype in (1, 2):
            # TServerLevel.cpp:1514-1540: new-world bombable block formula.
            low, high = tile % 16, tile // 16
            if high in (0x1a, 0x1b) and low // 2 != 5:
                sx, sy = tx - (low & 1), ty - (high & 1)
                base = low & 0xe
                expected = (base + 0x1a0, base + 0x1b0,
                            base + 0x1a1, base + 0x1b1)
                if matches(sx, sy, expected):
                    # TServerLevel.cpp:1486-1488: buildArray is column-major.
                    replacement = (base + 0x1c0, base + 0x1d0,
                                   base + 0x1c1, base + 0x1d1)
                    block = BlastBlock(sx, sy, replacement, BUSH_LEAPS[low // 2])
        elif tilestype == 0:
            block = classic_block(tx, ty, tile)
        if block is not None:
            blocks.append(block)
            for dx in range(2):
                for dy in range(2):
                    patched[block.start_x + dx, block.start_y + dy] = (
                        block.replacement_column_major[dx * 2 + dy])
    return blocks
