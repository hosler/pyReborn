"""
Tile type definitions for Reborn.

Each base tile ID (0-4095) maps to a tile type that determines collision
behavior, water state, etc. The type table is loaded from ``tiletypes1.dat`` —
the same authoritative data file the C# client and GServer clients ship —
instead of being baked into this module. The array that used to live here was
truncated to 4068 bytes and disagreed with the canonical data in ~1400 spots,
which is why a pile of hand corrections was needed to paper over it.

There are TWO type tables, selected per level by the registered tiledefs
(``TTiles::GetLevelTiles``, Preagonal/FourPlay/quattroplay/src/TTiles.cpp:568):
the active *tilestype* is reset to 0 on level change and set from the type of
the tiledef whose prefix is the longest match on the level name; defs with
type >= 3 are skipped unless the type is 5 (so ``addtiledef2``, which
registers type 4, never affects it). Reads then route by that value
(``TServerLevel::getTileType``, src/TServerLevel.cpp:688-708): tilestype 0
reads the classic table, 1 and 2 read the new-world table, and 5 means the
level has no tile types at all (every tile reports 0).

``tiletypesnw.dat`` (the new-world table) was extracted from the official
v6.0.3.7 Linux client binary, where it sits at 0x541740, directly after the
classic table at 0x540740 (which matches tiletypes1.dat). Sanity check: on
real era_ levels (a tilestype-1 server) the classic table calls 96% of board
tiles blocking; the new-world table gives a plausible 57%.

Like the real client's ``TTiles::tilestype``, the active tilestype and the
registered tiledefs are PROCESS-GLOBAL. Multiple in-process clients (multi-bot
QA) share them; that is only observable if bots sit on levels with different
tilestype defs at the same time, which mirrors what a single real client
process could express anyway.
"""

import logging
import os
from enum import IntEnum
from typing import Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


class TileType(IntEnum):
    """Tile type definitions matching Reborn protocol."""
    NONBLOCK = 0           # Walkable tiles
    HURT_UNDERGROUND = 2   # Damage tiles underground
    CHAIR = 3              # Sittable objects
    BED_UPPER = 4          # Upper part of bed (blocking)
    BED_LOWER = 5          # Lower part of bed (blocking)
    SWAMP = 6              # Slows movement
    LAVA_SWAMP = 7         # Damage + slow movement
    NEAR_WATER = 8         # Shallow water (normal walking)
    WATER = 11             # Deep water (swimming)
    LAVA = 12              # Lava (damage)
    THROW_THROUGH = 20     # Can throw items through but blocks walking
    JUMP_STONE = 21        # Jump tiles (block walking)
    BLOCKING = 22          # Solid walls and obstacles
    # Liftable objects (a pyReborn client mechanic, not in the base type data).
    # The standard tile data only knows these as blocking; object kinds are
    # distinguished via the tile-corrections overlay so glove power can gate them.
    BUSH = 23              # Bushes - bare-handed (glove power 0)
    ROCK = 24              # Rocks - need a glove (power 1)
    POT = 25               # Pots - bare-handed (glove power 0)
    SIGN = 26              # Standalone post signs - bare-handed


_DAT_PATH = os.path.join(os.path.dirname(__file__), "tiletypes1.dat")
_NW_DAT_PATH = os.path.join(os.path.dirname(__file__), "tiletypesnw.dat")


def _load_tile_types() -> bytes:
    """Load the 4096-entry classic tile-type table from tiletypes1.dat.

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


def _load_tile_types_nw() -> Optional[bytes]:
    """Load the new-world tile-type table (tilestypesnw). None if absent."""
    try:
        with open(_NW_DAT_PATH, "rb") as f:
            data = f.read()
        if len(data) >= 4096:
            return data[:4096]
    except OSError:
        pass
    return None


# Classic tile type lookup table (4096 entries, one per base tile ID).
TILE_TYPES = _load_tile_types()
# New-world table, read when the active tilestype is 1 or 2.
TILE_TYPES_NW = _load_tile_types_nw()

#: Tilestype value meaning "this level has no tile types at all".
TILESTYPE_NONE = 5

# --- per-level tilestype selection (TTiles::GetLevelTiles) -----------------

# Registered full-tileset defs, in registration order: (prefix, m_type).
# addtiledef2 pastes register type 4 in the real client; since type 4 is
# always skipped by the selection rule they are simply not recorded here.
_registered_tiledefs: List[Tuple[str, int]] = []
_current_level = ""
_active_tilestype = 0
_warned_nw_missing = False


def _strip_level_name(level_name: str) -> str:
    """TFiles::stripFileName + our lowercase-prefix convention."""
    if not isinstance(level_name, str):
        return ""
    name = level_name.replace("\\", "/").rsplit("/", 1)[-1]
    return name.lower()


def select_tilestype(defs: Iterable[Tuple[str, int]], level_name: str) -> int:
    """The selection rule of TTiles::GetLevelTiles (TTiles.cpp:568-631).

    Reset to 0, then take the type of the def whose prefix is the LONGEST
    match on the level name (first registered wins ties; an empty prefix
    matches everything). Defs with type >= 3 are skipped unless type == 5.
    """
    name = _strip_level_name(level_name)
    best_len = -1
    result = 0
    for prefix, m_type in defs:
        if m_type >= 3 and m_type != TILESTYPE_NONE:
            continue
        prefix = (prefix or "").lower()
        if not name.startswith(prefix):
            continue
        if len(prefix) <= best_len:
            continue
        best_len = len(prefix)
        result = m_type
    return result


def _recompute_active() -> None:
    global _active_tilestype
    _active_tilestype = select_tilestype(_registered_tiledefs, _current_level)


def register_tiledef(levelstart: str, m_type: int) -> None:
    """Record an addtiledef's (levelstart, type) for tilestype selection.

    Mirrors TilesetManager.set_full_tiledef: a re-register for the same
    prefix replaces the earlier entry.
    """
    prefix = (levelstart or "").lower()
    global _registered_tiledefs
    _registered_tiledefs = [
        entry for entry in _registered_tiledefs if entry[0] != prefix
    ]
    _registered_tiledefs.append((prefix, int(m_type)))
    _recompute_active()


def remove_tiledefs(prefix: str = "") -> None:
    """removetiledefs: drop defs whose stored prefix starts with `prefix`."""
    prefix = (prefix or "").lower()
    global _registered_tiledefs
    _registered_tiledefs = [
        entry for entry in _registered_tiledefs
        if not entry[0].startswith(prefix)
    ]
    _recompute_active()


def reset_tiledefs() -> None:
    """Forget all registered defs (tests / full client reset)."""
    global _registered_tiledefs
    _registered_tiledefs = []
    _recompute_active()


def set_current_level(level_name: str) -> None:
    """Level change: recompute the active (module-default) tilestype."""
    global _current_level
    _current_level = _strip_level_name(level_name)
    _recompute_active()


def active_tilestype() -> int:
    """The tilestype in force for the current level (TTiles::tilestype)."""
    return _active_tilestype


def tilestype_for_level(level_name: str) -> int:
    """The tilestype a specific level would select (per-client probes)."""
    return select_tilestype(_registered_tiledefs, level_name)


def _table_for(tilestype: int) -> bytes:
    """The byte table a tilestype reads (TServerLevel.cpp:705-708, :741)."""
    global _warned_nw_missing
    if tilestype == 0:
        return TILE_TYPES
    if TILE_TYPES_NW is None:
        if not _warned_nw_missing:
            _warned_nw_missing = True
            logger.warning(
                "tilestype %d selected but tiletypesnw.dat is missing; "
                "falling back to the classic table", tilestype)
        return TILE_TYPES
    return TILE_TYPES_NW


def get_tile_type(tile_id: int, tilestype: Optional[int] = None) -> int:
    """
    Get the tile type for a given tile ID.

    For tiles 0-4095 (first tileset), uses the lookup table selected by
    `tilestype` (default: the active per-level selection).
    For tiles >= 4096 (other tilesets), returns the type of tile_id % 512.
    """
    if tile_id < 0:
        return TileType.BLOCKING

    if tilestype is None:
        tilestype = _active_tilestype
    if tilestype == TILESTYPE_NONE:
        # "No tiles": every valid tile reports type 0 (getTileType:698-699).
        return TileType.NONBLOCK
    table = _table_for(tilestype)

    # For additional tilesets, use modulo 512 to map back to base tiles
    # This is a simplification - actual behavior may vary
    if tile_id >= 4096:
        # Tiles beyond first tileset - check if in water/blocking range
        base_id = tile_id % 512
        if base_id < len(table):
            return table[base_id]
        return TileType.NONBLOCK

    if tile_id < len(table):
        return table[tile_id]

    return TileType.NONBLOCK


def type_is_blocking(tile_type: int) -> bool:
    """Whether a tile *type* blocks walking.

    Mirrors the C# client's IsOnWall, which is just a threshold: anything at
    THROW_THROUGH (20) or above blocks — throw-through, jump-stone, solid walls,
    and the liftable object types (23-26). Beds (4/5) block too, so they
    are the one explicit addition below the threshold.
    """
    return (tile_type >= TileType.THROW_THROUGH or
            tile_type in (TileType.BED_UPPER, TileType.BED_LOWER))


def is_blocking(tile_id: int) -> bool:
    """Check if a tile blocks movement."""
    return type_is_blocking(get_tile_type(tile_id))


def is_water(tile_id: int) -> bool:
    """Check if a tile is deep or shallow water."""
    tile_type = get_tile_type(tile_id)
    return tile_type in (TileType.WATER, TileType.NEAR_WATER)


def is_swimming_water(tile_id: int) -> bool:
    """Check if a tile is deep enough to trigger swimming."""
    return get_tile_type(tile_id) == TileType.WATER


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
    """Check if a tile is a liftable object."""
    tile_type = get_tile_type(tile_id)
    return tile_type in (TileType.BUSH, TileType.ROCK, TileType.POT, TileType.SIGN)


def get_lift_power_required(tile_id: int) -> int:
    """
    Get the glove power required to lift a tile.

    Returns:
        0 = bushes, pots, and post signs (bare-handed) or not liftable
        1 = rocks (need a glove)
    """
    tile_type = get_tile_type(tile_id)
    if tile_type == TileType.ROCK:
        return 1
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
    elif tile_type == TileType.SIGN:
        return "sign"
    return ""
