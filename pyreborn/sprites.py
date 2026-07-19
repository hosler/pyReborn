"""
pyreborn - Sprite sheet manager.

Handles loading, caching, and extracting sprites from sprite sheets.
Works with pygame surfaces.
"""

from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import os

# Pygame import is optional - only needed when actually used
try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False


# -- Tier 2a: player body-color recoloring (palette swap) -------------------
#
# Classic Reborn's PLPROP_COLORS carries 5 indices into a 20-color named
# palette (see the C# client's Players/ColorManager.cs AllColors)
# that get painted onto 5 marker colors baked into body*.png. packets.py
# parses PLPROP_COLORS (prop 13, fixed-width: 5 bytes classic / 8 bytes v6
# extended body colors) into Player.colors and the other-player props dict;
# this recolor path activates automatically the moment a `colors` sequence
# (>=5 ints, 0-19 for the classic palette) shows up in the equipment dict
# passed to _render_animated_entity (game/render_entities.py), and is a no-op
# (draws the sprite unmodified) when colors is absent/short.
#
# Marker colors below were read directly off body.png/body2.png/body5.png/
# body12.png with PIL (the C# client ships no reference table): all four share
# the exact same 5 non-outline, non-transparent RGB values, just in different
# pixel proportions per clothing cut, confirming they are the 5 recolor
# markers. The marker -> named-slot assignment (skin/coat/sleeves/shoes/belt,
# matching PLPROP_COLORS' index order) is this module's best-effort guess -
# it has NOT been verified against a live server's rendering of a known
# COLORS value (attempted: memory records one real capture, body12.png with
# COLORS 2,0,10,4,18, but no reference screenshot to check the result
# against). If it turns out wrong once colors actually flow, only
# BODY_COLOR_MARKERS' ordering needs correcting.
REBORN_PALETTE = [
    "white", "yellow", "orange", "pink", "red", "darkred", "lightgreen",
    "green", "darkgreen", "lightblue", "blue", "darkblue", "brown",
    "cynober", "purple", "darkpurple", "lightgray", "gray", "black",
    "transparent",
]

REBORN_PALETTE_RGB: Dict[str, Tuple[int, int, int]] = {
    "white": (255, 255, 255), "yellow": (255, 255, 0), "orange": (255, 140, 0),
    "pink": (255, 175, 175), "red": (220, 30, 30), "darkred": (139, 0, 0),
    "lightgreen": (140, 255, 140), "green": (0, 180, 0), "darkgreen": (0, 100, 0),
    "lightblue": (140, 190, 255), "blue": (30, 60, 220), "darkblue": (0, 0, 139),
    "brown": (139, 90, 43), "cynober": (227, 66, 52), "purple": (160, 32, 240),
    "darkpurple": (100, 20, 150), "lightgray": (200, 200, 200), "gray": (128, 128, 128),
    "black": (20, 20, 20), "transparent": (0, 0, 0),
}

# Marker RGB baked into body*.png, in (skin, coat, sleeves, shoes, belt) slot
# order matching PLPROP_COLORS' 5 indices.
BODY_COLOR_MARKERS: Tuple[Tuple[int, int, int], ...] = (
    (255, 173, 107),  # skin
    (255, 255, 255),  # coat (main clothing)
    (255, 0, 0),       # sleeves
    (206, 24, 41),     # shoes
    (0, 0, 255),       # belt
)


def palette_index_to_rgb(index) -> Tuple[int, int, int]:
    """Resolve a PLPROP_COLORS palette index (0-19) to an RGB triple."""
    try:
        name = REBORN_PALETTE[int(index)]
    except (IndexError, ValueError, TypeError):
        return (255, 255, 255)
    return REBORN_PALETTE_RGB.get(name, (255, 255, 255))


# Bounds on the below caches, same LRU-eviction idea as render_world.py's
# per-segment surface cache: a long play session (many downloaded NPC/baddy
# sheets, many player recolors) must not accumulate surfaces forever. Sized
# generously above what a normal session touches at once - sheets/recolored
# sheets are whole images (worth capping tighter), sprites/recolored sprites
# are small sub-surface cuts (cheaper individually, so a bigger cap).
_MAX_CACHED_SHEETS = 300
_MAX_CACHED_SPRITES = 4000
_MAX_CACHED_RECOLOR_SHEETS = 150
_MAX_CACHED_RECOLOR_SPRITES = 4000

# Representative equipment frames for UI previews.  These are the exact
# down-facing definitions used by the player GANIs and consumed by
# game/render_entities.py through SpriteManager.get_sprite().  Keeping the
# rects here lets non-GANI renderers use the same sheet geometry and crop
# path instead of scaling an entire sheet.
PLAYER_EQUIPMENT_PREVIEW_RECTS = {
    'head': (0, 64, 32, 32),
    'body': (64, 0, 32, 32),
    'sword': (0, 12, 12, 24),
    'shield': (14, 0, 16, 20),
}


class SpriteManager:
    """Manages loading and caching of sprite sheets."""

    def __init__(self, search_paths: Optional[List[Path]] = None):
        """
        Initialize sprite manager.

        Args:
            search_paths: List of paths to search for sprite images
        """
        if not PYGAME_AVAILABLE:
            raise RuntimeError("pygame is required for SpriteManager")

        self.search_paths = search_paths or []
        # OrderedDicts so recently-used entries can be pushed to the end and
        # stale ones evicted from the front once the matching _MAX_CACHED_*
        # bound is exceeded (see _evict_lru).
        self.sheet_cache: "OrderedDict[str, pygame.Surface]" = OrderedDict()
        self.sprite_cache: "OrderedDict[Tuple[str, int, int, int, int], pygame.Surface]" = OrderedDict()
        # Tier 2a: palette-swapped body sheets/sprites, cached per (image,
        # colors-tuple) so a re-render doesn't re-run the pixel remap.
        self._recolor_sheet_cache: "OrderedDict[Tuple[str, Tuple[int, ...]], Optional[pygame.Surface]]" = OrderedDict()
        self._recolor_sprite_cache: "OrderedDict[tuple, Optional[pygame.Surface]]" = OrderedDict()
        # normalized-colors-tuple cache for get_sprite_recolored/recolor_body,
        # keyed by id(colors) - see _colors_key().
        self._colors_key_cache: Dict[int, Tuple[list, Tuple[int, ...]]] = {}

        # Subdirectories to search within each path
        self.subdirs = ['', 'bodies', 'heads', 'swords', 'shields', 'hats',
                        'images', 'sprites', 'ganis', 'npcs', 'baddies', 'bomys']

    @staticmethod
    def _evict_lru(cache: "OrderedDict", max_size: int):
        """Drop least-recently-used entries once `cache` exceeds `max_size`."""
        while len(cache) > max_size:
            cache.popitem(last=False)

    def add_search_path(self, path: Path):
        """Add a search path for finding sprite images."""
        if path not in self.search_paths:
            self.search_paths.append(path)

    def find_file(self, name: str) -> Optional[Path]:
        """Find a sprite image file by name in search paths."""
        for search_path in self.search_paths:
            # Check direct path
            full_path = search_path / name
            if full_path.exists():
                return full_path

            # Check subdirectories
            for subdir in self.subdirs:
                if subdir:
                    sub_path = search_path / subdir / name
                else:
                    sub_path = search_path / name
                if sub_path.exists():
                    return sub_path

        return None

    def load_sheet(self, name: str) -> Optional[pygame.Surface]:
        """
        Load a sprite sheet by name.

        Args:
            name: Filename of the sprite sheet (e.g., 'body.png')

        Returns:
            pygame.Surface or None if not found
        """
        # Check cache (a cached None is a remembered miss — see below)
        if name in self.sheet_cache:
            self.sheet_cache.move_to_end(name)
            return self.sheet_cache[name]

        # Find file
        file_path = self.find_file(name)
        if not file_path:
            # Cache the miss so we don't stat the disk for this name every frame
            # (huge cost with many NPCs whose images are still downloading). When
            # the file arrives, on_file -> load_bytes overwrites this None.
            self.sheet_cache[name] = None
            self._evict_lru(self.sheet_cache, _MAX_CACHED_SHEETS)
            return None

        # Load image
        try:
            surface = pygame.image.load(str(file_path))
            # Convert for faster blitting, preserve alpha
            if surface.get_alpha() is not None or name.endswith('.png'):
                surface = surface.convert_alpha()
            else:
                surface = surface.convert()
            self.sheet_cache[name] = surface
            self._evict_lru(self.sheet_cache, _MAX_CACHED_SHEETS)
            return surface
        except Exception as e:
            print(f"Error loading sprite sheet {name}: {e}")
            self.sheet_cache[name] = None   # don't retry an unloadable file each frame
            self._evict_lru(self.sheet_cache, _MAX_CACHED_SHEETS)
            return None

    def has_sheet(self, name: str) -> bool:
        """True if `name` is loaded in the cache (a cached None miss is not)."""
        return self.sheet_cache.get(name) is not None

    def load_bytes(self, name: str, data: bytes) -> Optional[pygame.Surface]:
        """Load a sprite sheet from in-memory bytes (e.g. a file downloaded from
        the server) and cache it under `name`, so load_sheet(name) finds it."""
        # Already known to be undecodable (some bomber assets, e.g.
        # eye_bomb_blackhole*.png, arrive as non-image data) — don't re-decode
        # or re-log every time the server re-sends them.
        if name in self.sheet_cache and self.sheet_cache[name] is None:
            return None
        import io
        try:
            surface = pygame.image.load(io.BytesIO(data), name)
            if surface.get_alpha() is not None or name.endswith('.png'):
                surface = surface.convert_alpha()
            else:
                surface = surface.convert()
            self.sheet_cache[name] = surface
            self._evict_lru(self.sheet_cache, _MAX_CACHED_SHEETS)
            return surface
        except Exception as e:
            print(f"Error loading downloaded sheet {name}: {e}")
            self.sheet_cache[name] = None   # remember the miss; stop retrying
            self._evict_lru(self.sheet_cache, _MAX_CACHED_SHEETS)
            return None

    def get_sprite(self, sheet_name: str, x: int, y: int,
                   width: int, height: int) -> Optional[pygame.Surface]:
        """
        Extract a sprite from a sprite sheet.

        Args:
            sheet_name: Name of the sprite sheet file
            x: X coordinate in sheet
            y: Y coordinate in sheet
            width: Width of sprite
            height: Height of sprite

        Returns:
            pygame.Surface or None if sheet not found
        """
        # Check sprite cache
        cache_key = (sheet_name, x, y, width, height)
        if cache_key in self.sprite_cache:
            self.sprite_cache.move_to_end(cache_key)
            return self.sprite_cache[cache_key]

        # Load sheet
        sheet = self.load_sheet(sheet_name)
        if not sheet:
            return None

        # Extract sprite region
        try:
            # Validate bounds
            sheet_w, sheet_h = sheet.get_size()
            if x < 0 or y < 0 or x + width > sheet_w or y + height > sheet_h:
                # Clamp to valid region
                x = max(0, min(x, sheet_w - 1))
                y = max(0, min(y, sheet_h - 1))
                width = min(width, sheet_w - x)
                height = min(height, sheet_h - y)
                if width <= 0 or height <= 0:
                    return None

            # Create subsurface
            sprite = sheet.subsurface((x, y, width, height)).copy()
            self.sprite_cache[cache_key] = sprite
            self._evict_lru(self.sprite_cache, _MAX_CACHED_SPRITES)
            return sprite
        except Exception as e:
            print(f"Error extracting sprite from {sheet_name} at ({x},{y},{width},{height}): {e}")
            return None

    def preload(self, names: List[str]):
        """Preload multiple sprite sheets."""
        for name in names:
            self.load_sheet(name)

    def _colors_key(self, colors) -> Tuple[int, ...]:
        """Normalize a >=5-value colors sequence into the int tuple used as a
        recolor cache key, memoized by the colors list's identity. The local
        player's colors sequence (player.colors) is a live attribute re-read
        every frame by _render_animated_entity, but player.py replaces it
        wholesale (`self.colors = props['colors']`) rather than mutating it in
        place, so the same unchanged list is passed in every frame the colors
        prop hasn't changed - rebuilding `tuple(int(c) for c in colors[:5])`
        each time is wasted work. Guarded against id() reuse after garbage
        collection by verifying the cached entry is still the same object
        (and, incidentally, keeping a reference to it so the id can't be
        recycled by an unrelated list while the entry is live)."""
        cache = self._colors_key_cache
        entry = cache.get(id(colors))
        if entry is not None and entry[0] is colors:
            return entry[1]
        key = tuple(int(c) for c in colors[:5])
        if len(cache) > 300:
            cache.clear()
        cache[id(colors)] = (colors, key)
        return key

    def recolor_body(self, sheet_name: str, colors) -> Optional[pygame.Surface]:
        """Return a palette-swapped copy of `sheet_name` for a 5-value
        PLPROP_COLORS sequence (see the module-level Tier 2a notes above).
        Cached per (sheet_name, colors-tuple); returns None if the base sheet
        isn't loaded yet (cache-the-miss - retried once it downloads, same
        policy as load_sheet)."""
        if not colors or len(colors) < 5:
            return None
        key = (sheet_name, self._colors_key(colors))
        if key in self._recolor_sheet_cache:
            self._recolor_sheet_cache.move_to_end(key)
            return self._recolor_sheet_cache[key]

        base = self.load_sheet(sheet_name)
        if base is None:
            return None

        surf = base.copy()
        arr = pygame.PixelArray(surf)
        try:
            for marker, idx in zip(BODY_COLOR_MARKERS, key[1]):
                target = palette_index_to_rgb(idx)
                if target != marker:
                    arr.replace(marker, target)
        finally:
            del arr
        self._recolor_sheet_cache[key] = surf
        self._evict_lru(self._recolor_sheet_cache, _MAX_CACHED_RECOLOR_SHEETS)
        return surf

    def get_sprite_recolored(self, sheet_name: str, colors, x: int, y: int,
                              width: int, height: int) -> Optional[pygame.Surface]:
        """Like get_sprite(), but drawn from the colors-recolored sheet. Falls
        back to the plain (uncoloured) sprite if colors isn't a usable 5-value
        sequence, so callers can pass a possibly-None `colors` unconditionally."""
        if not colors or len(colors) < 5:
            return self.get_sprite(sheet_name, x, y, width, height)

        cache_key = (sheet_name, self._colors_key(colors), x, y, width, height)
        if cache_key in self._recolor_sprite_cache:
            self._recolor_sprite_cache.move_to_end(cache_key)
            return self._recolor_sprite_cache[cache_key]

        sheet = self.recolor_body(sheet_name, colors)
        if sheet is None:
            return None
        try:
            sheet_w, sheet_h = sheet.get_size()
            cx = max(0, min(x, sheet_w - 1))
            cy = max(0, min(y, sheet_h - 1))
            cw = min(width, sheet_w - cx)
            ch = min(height, sheet_h - cy)
            if cw <= 0 or ch <= 0:
                return None
            sprite = sheet.subsurface((cx, cy, cw, ch)).copy()
        except Exception:
            return None
        self._recolor_sprite_cache[cache_key] = sprite
        self._evict_lru(self._recolor_sprite_cache, _MAX_CACHED_RECOLOR_SPRITES)
        return sprite

    def clear_cache(self):
        """Clear all cached sprites and sheets."""
        self.sheet_cache.clear()
        self.sprite_cache.clear()
        self._recolor_sheet_cache.clear()
        self._recolor_sprite_cache.clear()
        self._colors_key_cache.clear()

    def get_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        return {
            'sheets_cached': len(self.sheet_cache),
            'sprites_cached': len(self.sprite_cache),
        }


class TilesetManager:
    """
    Specialized manager for Reborn tilesets.

    Handles the non-linear tile ID mapping used in Reborn level files.
    """

    TILE_SIZE = 16
    TILESET_COLS = 128  # Tiles per row in tileset (128 * 16 = 2048 pixels)
    TILESET_ROWS = 32   # Rows in tileset

    def __init__(self, sprite_manager: SpriteManager):
        """Initialize with a sprite manager."""
        self.sprite_mgr = sprite_manager
        self.tile_cache: Dict[Tuple[str, int], pygame.Surface] = {}
        # get_tile_or_color()'s colored fallback for a missing tile, cached per
        # tile_id so a level full of undownloaded tiles doesn't allocate a new
        # placeholder Surface on every miss every frame.
        self._placeholder_cache: Dict[int, pygame.Surface] = {}
        self.default_tileset = "dustynewpics1.png"
        # Per-block tileset overrides set by GS1 addtiledef2 (Bomber Arena's
        # chocolate tiles). Maps a Reborn tile-block (tile_id // 512) to its own
        # 256x512 image; the whole level tileset is these blocks side by side.
        self.tiledefs: Dict[int, str] = {}

    def set_tiledef(self, block: int, image: str):
        """addtiledef2: use `image` for tile-block `block` (tile_id // 512)."""
        if self.tiledefs.get(block) != image:
            self.tiledefs[block] = image
            self.tile_cache.clear()

    def clear_tiledefs(self):
        """removetiledefs / level change: revert to the default tileset."""
        if self.tiledefs:
            self.tiledefs.clear()
            self.tile_cache.clear()

    def get_tile(self, tile_id: int, tileset: Optional[str] = None) -> Optional[pygame.Surface]:
        """
        Get a tile surface by ID.

        Args:
            tile_id: tile ID (0-4095)
            tileset: Tileset filename (uses default if None)

        Returns:
            pygame.Surface or None
        """
        # A per-block tiledef (addtiledef2) wins over the default tileset. The
        # block image is one Reborn block: 16 cols x 32 rows of 16px tiles, so
        # the tile sits at its LOCAL position within the 256x512 image.
        if tileset is None:
            tdef = self.tiledefs.get(tile_id // 512)
            if tdef is not None:
                cache_key = (tdef, tile_id)
                if cache_key in self.tile_cache:
                    return self.tile_cache[cache_key]
                px = (tile_id % 16) * self.TILE_SIZE
                py = ((tile_id // 16) % 32) * self.TILE_SIZE
                tile = self.sprite_mgr.get_sprite(tdef, px, py,
                                                  self.TILE_SIZE, self.TILE_SIZE)
                if tile:                       # image not downloaded yet -> None,
                    self.tile_cache[cache_key] = tile  # fall through to default
                    return tile
            tileset = self.default_tileset

        cache_key = (tileset, tile_id)
        if cache_key in self.tile_cache:
            return self.tile_cache[cache_key]

        # Calculate tileset coordinates using Reborn's formula
        # The tileset is organized in 16-column blocks, 32 rows each
        tx = (tile_id // 512) * 16 + (tile_id % 16)
        ty = (tile_id // 16) % 32
        px = tx * self.TILE_SIZE
        py = ty * self.TILE_SIZE

        tile = self.sprite_mgr.get_sprite(tileset, px, py,
                                          self.TILE_SIZE, self.TILE_SIZE)
        if tile:
            self.tile_cache[cache_key] = tile
        return tile

    def get_tile_or_color(self, tile_id: int, tileset: Optional[str] = None) -> pygame.Surface:
        """
        Get a tile, or generate a colored placeholder based on tile ID.

        Args:
            tile_id: tile ID
            tileset: Tileset filename

        Returns:
            pygame.Surface (tile or colored placeholder)
        """
        tile = self.get_tile(tile_id, tileset)
        if tile:
            return tile

        cached = self._placeholder_cache.get(tile_id)
        if cached is not None:
            return cached

        # Generate color from tile ID for visual debugging
        r = (tile_id * 17) % 256
        g = (tile_id * 31) % 256
        b = (tile_id * 47) % 256

        placeholder = pygame.Surface((self.TILE_SIZE, self.TILE_SIZE))
        placeholder.fill((r, g, b))
        self._placeholder_cache[tile_id] = placeholder
        return placeholder

    def preload_tileset(self, tileset: Optional[str] = None):
        """Preload all tiles from a tileset."""
        if tileset is None:
            tileset = self.default_tileset

        # Just load the sheet - tiles will be cached on demand
        self.sprite_mgr.load_sheet(tileset)

    def clear_cache(self):
        """Clear tile cache."""
        self.tile_cache.clear()


def create_placeholder_sprite(width: int = 32, height: int = 32,
                               color: Tuple[int, int, int] = (255, 0, 255)) -> pygame.Surface:
    """Create a simple placeholder sprite surface."""
    if not PYGAME_AVAILABLE:
        raise RuntimeError("pygame is required")

    surface = pygame.Surface((width, height), pygame.SRCALPHA)

    # Draw a semi-transparent filled rectangle
    surface.fill((*color, 100))

    # Draw border
    pygame.draw.rect(surface, color, (0, 0, width, height), 2)

    # Draw X pattern
    pygame.draw.line(surface, color, (0, 0), (width-1, height-1), 1)
    pygame.draw.line(surface, color, (width-1, 0), (0, height-1), 1)

    return surface


def create_shadow_sprite(width: int = 24, height: int = 12) -> pygame.Surface:
    """Create a shadow sprite (ellipse)."""
    if not PYGAME_AVAILABLE:
        raise RuntimeError("pygame is required")

    surface = pygame.Surface((width, height), pygame.SRCALPHA)
    pygame.draw.ellipse(surface, (0, 0, 0, 80), (0, 0, width, height))
    return surface
