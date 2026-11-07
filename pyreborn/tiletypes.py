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
the tiledef whose prefix is the longest match on the level name. Defs with
type >= 3 are skipped unless the type is 5 (so ``addtiledef2``, which
registers type 4, never affects it). Reads then route by that value
(``TServerLevel::getTileType``, src/TServerLevel.cpp:688-708): tilestype 0
reads the classic table, 1 and 2 read the new-world table, and 5 means the
level has no tile types at all (every tile reports 0).

``tiletypesnw.dat`` (the new-world table) was extracted from the official
v6.0.3.7 Linux client binary, where it sits at 0x541740, directly after the
classic table at 0x540740 (which matches tiletypes1.dat). Sanity check: on
real era_ levels (a tilestype-1 server) the classic table calls 96% of board
tiles blocking. The new-world table gives a plausible 57%.

Client instances own their selection state; the module-level helpers retain a
standalone default for callers without a network client. The immutable tables
are shared, while registrations and level selection are isolated per session.
"""

import logging
import os
from enum import IntEnum
from typing import Iterable, Optional, Tuple

logger = logging.getLogger(__name__)


class TileType(IntEnum):
    """Tile type definitions matching Reborn protocol."""
    NONBLOCK = 0           # Walkable tiles
    HURT_UNDERGROUND = 2   # Damage tiles underground
    CHAIR = 3              # Sittable objects
    BED_UPPER = 4          # Upper part of bed (blocking)
    BED_LOWER = 5          # Lower part of bed (passable)
    SWAMP = 6              # Slows movement
    LAVA_SWAMP = 7         # Lava swamp (not a damage type)
    NEAR_WATER = 8         # Shallow water (normal walking)
    # GServer-v2/server/include/level/LevelTileTypes.h:27-44.
    NEAR_LAVA = 9
    DESERT = 10
    WATER = 11             # Deep water (swimming)
    LAVA = 12              # Lava (damage)
    THROW_THROUGH = 20     # Can throw items through but blocks walking
    JUMP_STONE = 21        # Jump tiles (block walking)
    BLOCKING = 22          # Solid walls and obstacles
    BLOCKING_FOREGROUND = 23  # New-world foreground wall (LevelTileTypes.h:44)
    # Liftable objects are tile-ID patterns; see pyreborn/liftobjects.py.


_DAT_PATH = os.path.join(os.path.dirname(__file__), "tiletypes1.dat")
_NW_DAT_PATH = os.path.join(os.path.dirname(__file__), "tiletypesnw.dat")


_warned_classic_missing = False


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
    global _warned_classic_missing
    if not _warned_classic_missing:
        _warned_classic_missing = True
        logger.warning("MISSING OR TRUNCATED tiletypes1.dat: collision data unavailable; "
                       "falling back to an all-walkable classic table")
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

class TileTypeSelection:
    """Session-owned tiledefs (TServerList.cpp:333; TTiles.cpp:285-287)."""

    def __init__(self):
        self.reset_tiledefs()

    def reset_tiledefs(self):
        self.defs = []
        self.current_level = ""
        # TTiles.cpp:18, :46-48: zero default, unrestricted double setter.
        self.waterheight = 0.0

    def set_waterheight(self, value):
        from reborn_protocol.gs1.values import to_num
        self.waterheight = to_num(value)

    def has_water_plane(self):
        # The isOnWater assembly compares DOUBLE_00402670 (0.3), despite
        # TServerLevel.cpp:928's inaccurate 0.0 transcription. See asm/
        # TServerLevel/_ZN12TServerLevel9isOnWaterEdd.s_decomped:12-13 and
        # Preagonal/FourPlay/quattroplay/src/TInitStatics.cpp:1242.
        return self.waterheight >= 0.3

    def register_tiledef(self, levelstart, m_type):
        prefix = (levelstart or "").lower()
        self.defs = [entry for entry in self.defs if entry[0] != prefix]
        self.defs.append((prefix, int(m_type)))

    def remove_tiledefs(self, prefix=""):
        prefix = (prefix or "").lower()
        self.defs = [entry for entry in self.defs if not entry[0].startswith(prefix)]

    def set_current_level(self, level_name):
        self.current_level = _strip_level_name(level_name)

    def tilestype_for_level(self, level_name):
        return select_tilestype(self.defs, level_name)

    def active_tilestype(self):
        return self.tilestype_for_level(self.current_level)


_default_selection = TileTypeSelection()
_warned_nw_missing = False


def selection_for(client=None):
    """Use the client's session registry, or the standalone compatibility one."""
    return getattr(getattr(client, "level_state", None), "tiletypes", _default_selection)


def _strip_level_name(level_name: str) -> str:
    """TFiles::stripFileName + our lowercase-prefix convention."""
    if not isinstance(level_name, str):
        return ""
    name = level_name.replace("\\", "/").rsplit("/", 1)[-1]
    return name.lower()


def select_tilestype(defs: Iterable[Tuple[str, int]], level_name: str) -> int:
    """The selection rule of TTiles::GetLevelTiles (TTiles.cpp:568-631).

    Reset to 0, then take the type of the def whose prefix is the LONGEST
    match on the level name (first registered wins ties. An empty prefix
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


# Compatibility helpers for standalone table users (no Client instance).
register_tiledef = _default_selection.register_tiledef
remove_tiledefs = _default_selection.remove_tiledefs
reset_tiledefs = _default_selection.reset_tiledefs
set_current_level = _default_selection.set_current_level
tilestype_for_level = _default_selection.tilestype_for_level


def active_tilestype(client=None):
    return selection_for(client).active_tilestype()


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


def get_tile_type(tile_id: int, tilestype: Optional[int] = None, *, client=None) -> int:
    """
    Get the tile type for a given tile ID.

    For tiles 0-4095 (first tileset), uses the lookup table selected by
    `tilestype` (default: the client's selection, or the standalone selection).
    The reference indexes directly (TServerLevel.cpp:705-708), with no wrap.
    Its arrays have fixed bounds (:95-96); reads beyond them are undefined C++
    behavior, not another tileset. Python safely returns NONBLOCK for ids outside
    the shipped table instead of emulating an arbitrary out-of-bounds byte.
    """
    if tile_id < 0:
        return TileType.BLOCKING

    if tilestype is None:
        tilestype = active_tilestype(client)
    if tilestype == TILESTYPE_NONE:
        # "No tiles": every valid tile reports type 0 (getTileType:698-699).
        return TileType.NONBLOCK
    table = _table_for(tilestype)

    if tile_id < len(table):
        return table[tile_id]

    return TileType.NONBLOCK


def effective_tile_type(tile_id, npc_type=0, tilestype=None):
    """Shared board/overlay query (TServerLevel.cpp:688-708).

    getNPCTileType stops on the first nonzero answer (:199-203, :536-561),
    but only an answer above one overrides the board (:694-696).
    """
    if npc_type > 1:
        return npc_type
    return get_tile_type(tile_id, tilestype) if tile_id is not None else 0


def type_is_blocking(tile_type: int) -> bool:
    """Return True if a tile *type* blocks walking.

    TServerLevel.cpp:742 blocks types >=20 and type 4; type 5 is passable.
    """
    return (tile_type >= TileType.THROW_THROUGH or
            tile_type == TileType.BED_UPPER)


def is_blocking(tile_id: int, tilestype=None, *, client=None) -> bool:
    """Check if a tile blocks movement."""
    return type_is_blocking(get_tile_type(tile_id, tilestype, client=client))


def is_water(tile_id: int, tilestype=None, *, client=None) -> bool:
    """Check if a tile is deep or shallow water."""
    tile_type = get_tile_type(tile_id, tilestype, client=client)
    return tile_type in (TileType.WATER, TileType.NEAR_WATER)


def is_swimming_water(tile_id: int, tilestype=None, *, client=None) -> bool:
    """Check if a tile is deep enough to trigger swimming."""
    # TServerLevel.cpp:923-928 includes lava in the swimming water set.
    return get_tile_type(tile_id, tilestype, client=client) in (TileType.WATER, TileType.LAVA)


def is_damaging(tile_id: int, tilestype=None, *, client=None) -> bool:
    """Check if a tile causes damage."""
    tile_type = get_tile_type(tile_id, tilestype, client=client)
    # TPlayer.cpp:5887 / pyreborn/ground_effects.py:8: lava shore hurts; swamp does not.
    return tile_type in (TileType.LAVA, TileType.NEAR_LAVA, TileType.HURT_UNDERGROUND)

