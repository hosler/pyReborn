"""
Tile type definitions for Reborn.

Each base tile ID (0-4095) maps to a tile type that determines collision
behavior, water state, etc. The type table is loaded from ``tiletypes1.dat`` —
the same authoritative data file the C# (Preagonal) and GServer clients ship —
instead of being baked into this module. The array that used to live here was
truncated to 4068 bytes and disagreed with the canonical data in ~1400 spots,
which is why a pile of hand corrections was needed to paper over it.
"""

import os
from enum import IntEnum
from typing import List


class TileType(IntEnum):
    """Tile type definitions matching Reborn protocol."""
    NONBLOCK = 0           # Walkable tiles
    HURT_UNDERGROUND = 2   # Damage tiles underground
    CHAIR = 3              # Sittable objects
    BED_UPPER = 4          # Upper part of bed (blocking)
    BED_LOWER = 5          # Lower part of bed (blocking)
    SWAMP = 6              # Slows movement
    LAVA_SWAMP = 7         # Damage + slow movement
    NEAR_WATER = 8         # Shallow water (can walk, shows swimming)
    WATER = 11             # Deep water (swimming)
    LAVA = 12              # Lava (damage)
    THROW_THROUGH = 20     # Can throw items through but blocks walking
    JUMP_STONE = 21        # Jump tiles (block walking)
    BLOCKING = 22          # Solid walls and obstacles
    # Liftable objects (a pyReborn client mechanic, not in the base type data).
    # The standard tile data only knows these as BLOCKING; bush/rock/pot are
    # distinguished via the tile-corrections overlay so glove power can gate them.
    BUSH = 23              # Bushes - glove power 1+
    ROCK = 24              # Rocks - glove power 3
    POT = 25               # Pots - glove power 2+


_DAT_PATH = os.path.join(os.path.dirname(__file__), "tiletypes1.dat")


def _load_tile_types() -> bytes:
    """Load the 4096-entry tile-type table from tiletypes1.dat.

    Each byte is the TileType for that base tile id (0-4095). Falls back to an
    all-walkable table if the file is missing so imports never hard-fail.
    """
    try:
        with open(_DAT_PATH, "rb") as f:
            data = f.read()
        if len(data) >= 4096:
            return data[:4096]
    except OSError:
        pass
    return bytes(4096)


# Tile type lookup table (4096 entries, one per base tile ID).
TILE_TYPES = _load_tile_types()


def get_tile_type(tile_id: int) -> int:
    """
    Get the tile type for a given tile ID.

    For tiles 0-4095 (first tileset), uses the lookup table.
    For tiles >= 4096 (other tilesets), returns the type of tile_id % 512.
    """
    if tile_id < 0:
        return TileType.BLOCKING

    # For additional tilesets, use modulo 512 to map back to base tiles
    # This is a simplification - actual behavior may vary
    if tile_id >= 4096:
        # Tiles beyond first tileset - check if in water/blocking range
        base_id = tile_id % 512
        if base_id < len(TILE_TYPES):
            return TILE_TYPES[base_id]
        return TileType.NONBLOCK

    if tile_id < len(TILE_TYPES):
        return TILE_TYPES[tile_id]

    return TileType.NONBLOCK


def type_is_blocking(tile_type: int) -> bool:
    """Whether a tile *type* blocks walking.

    Mirrors Preagonal's IsOnWall, which is just a threshold: anything at
    THROW_THROUGH (20) or above blocks — throw-through, jump-stone, solid walls,
    and the liftable bush/rock/pot objects (23-25). Beds (4/5) block too, so they
    are the one explicit addition below the threshold.
    """
    return (tile_type >= TileType.THROW_THROUGH or
            tile_type in (TileType.BED_UPPER, TileType.BED_LOWER))


def is_blocking(tile_id: int) -> bool:
    """Check if a tile blocks movement."""
    return type_is_blocking(get_tile_type(tile_id))


def is_water(tile_id: int) -> bool:
    """Check if a tile is water (swimming)."""
    tile_type = get_tile_type(tile_id)
    return tile_type in (TileType.WATER, TileType.NEAR_WATER)


def is_swamp(tile_id: int) -> bool:
    """Check if a tile slows movement."""
    tile_type = get_tile_type(tile_id)
    return tile_type in (TileType.SWAMP, TileType.LAVA_SWAMP)


def is_damaging(tile_id: int) -> bool:
    """Check if a tile causes damage."""
    tile_type = get_tile_type(tile_id)
    return tile_type in (TileType.LAVA, TileType.LAVA_SWAMP, TileType.HURT_UNDERGROUND)


def is_chair(tile_id: int) -> bool:
    """Check if a tile is a chair (sittable)."""
    tile_type = get_tile_type(tile_id)
    return tile_type == TileType.CHAIR


def is_liftable(tile_id: int) -> bool:
    """Check if a tile is a liftable object (bush, rock, pot)."""
    tile_type = get_tile_type(tile_id)
    return tile_type in (TileType.BUSH, TileType.ROCK, TileType.POT)


def get_lift_power_required(tile_id: int) -> int:
    """
    Get the glove power required to lift a tile.

    Returns:
        0 = not liftable
        1 = bushes (glove power 1+)
        2 = pots (glove power 2+)
        3 = rocks (glove power 3)
    """
    tile_type = get_tile_type(tile_id)
    if tile_type == TileType.BUSH:
        return 1
    elif tile_type == TileType.POT:
        return 2
    elif tile_type == TileType.ROCK:
        return 3
    return 0


def get_liftable_type_name(tile_id: int) -> str:
    """Get the name of a liftable object type for display."""
    tile_type = get_tile_type(tile_id)
    if tile_type == TileType.BUSH:
        return "bush"
    elif tile_type == TileType.POT:
        return "pot"
    elif tile_type == TileType.ROCK:
        return "rock"
    return ""
