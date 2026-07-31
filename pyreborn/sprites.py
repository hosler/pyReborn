"""
pyreborn - Sprite sheet manager.

The sprite manager loads and caches sheets, and extracts sprites from them.
Works with pygame surfaces.
"""

from collections import OrderedDict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
import os

from .asset_paths import normalize_asset_name

# Pygame import is optional - only needed when actually used
try:
    import pygame
    from .mng import MNGAnimation, decode_mng
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
    "darkgray": (64, 64, 64), "cyan": (0, 255, 255),
}

REBORN_PALETTE_ALIASES = {
    "cyan": "cynober",
    "darkgray": "gray",
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


def strip_tiledef_image(name: str) -> str:
    """Return the lowercase basename stored for a tile definition. The reference
    uses the last file separator (TFiles.cpp:392-404,610-620).
    """
    return normalize_asset_name(name)


_DIRECTORY_NAME_CACHE: Dict[Path, Dict[str, str]] = {}


def find_asset_file(
    search_paths: List[Path], subdirs: List[str], name: str
) -> Optional[Path]:
    """Find a normalized asset, with a cached case-insensitive fallback."""
    name = normalize_asset_name(name)
    if not name:
        return None
    for search_path in search_paths:
        for subdir in subdirs:
            directory = search_path / subdir if subdir else search_path
            candidate = directory / name
            if candidate.exists():
                return candidate
            names = _DIRECTORY_NAME_CACHE.get(directory)
            if names is None:
                try:
                    names = {
                        entry.name.lower(): entry.name
                        for entry in directory.iterdir()
                        if entry.is_file()
                    }
                except OSError:
                    names = {}
                _DIRECTORY_NAME_CACHE[directory] = names
            real_name = names.get(name)
            if real_name is not None:
                return directory / real_name
    return None


def palette_index_to_rgb(index) -> Tuple[int, int, int]:
    """Resolve a PLPROP_COLORS palette index (0-19) to an RGB triple."""
    try:
        name = REBORN_PALETTE[int(index)]
    except (IndexError, ValueError, TypeError):
        return (255, 255, 255)
    return REBORN_PALETTE_RGB.get(name, (255, 255, 255))


def palette_name_to_index(name) -> int:
    """Resolve a classic color name while preserving the fixed wire palette."""
    normalized = str(name).strip().lower()
    normalized = REBORN_PALETTE_ALIASES.get(normalized, normalized)
    try:
        return REBORN_PALETTE.index(normalized)
    except ValueError:
        return 0


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

# Representative full equipment frames for UI previews. Keeping the rects
# here lets non-animation renderers use the same sheet geometry and crop path
# instead of scaling an entire sheet.
PLAYER_EQUIPMENT_PREVIEW_RECTS = {
    'head': (0, 64, 32, 32),
    'body': (64, 0, 32, 32),
    'sword': (32, 0, 32, 32),
    'shield': (0, 0, 19, 20),
}


class SpriteManager:
    """The sprite manager loads and caches sprite sheets."""

    def __init__(
        self,
        search_paths: Optional[List[Path]] = None,
        fetch_bytes: Optional[Callable[[str], Optional[bytes]]] = None,
    ):
        """
        Create the sprite manager.

        Args:
            search_paths: List of paths to search for sprite images
        """
        if not PYGAME_AVAILABLE:
            raise RuntimeError("pygame is required for SpriteManager")

        self.search_paths = search_paths or []
        self.fetch_bytes = fetch_bytes
        # OrderedDicts so recently-used entries can be pushed to the end and
        # stale ones evicted from the front once the matching _MAX_CACHED_*
        # bound is exceeded (see _evict_lru).
        self.sheet_cache: "OrderedDict[str, pygame.Surface]" = OrderedDict()
        self._missing_sheets: set[str] = set()
        self.animation_cache: "OrderedDict[str, MNGAnimation]" = OrderedDict()
        # Names whose DOWNLOADED bytes failed to decode. A cached None in
        # sheet_cache only means "not on local disk (yet)" — it must NOT stop
        # load_bytes from decoding the file once it arrives from the server, or
        # any custom asset first rendered before it downloads stays invisible
        # forever. Only a real bytes-decode failure belongs here.
        self._undecodable_bytes: set = set()
        self.sprite_cache: "OrderedDict[Tuple[str, int, int, int, int], pygame.Surface]" = OrderedDict()
        # Original 8-bit (indexed) surfaces, stashed before display conversion
        # strips the palette. setbackpal needs both the tileset's index data
        # and the pal file's palette; anything not palettized never lands here.
        self._raw8_cache: "OrderedDict[str, pygame.Surface]" = OrderedDict()
        # Tier 2a: palette-swapped body sheets/sprites, cached per (image,
        # colors-tuple) so a re-render doesn't re-run the pixel remap.
        self._recolor_sheet_cache: "OrderedDict[Tuple[str, Tuple[int, ...]], Optional[pygame.Surface]]" = OrderedDict()
        self._recolor_sprite_cache: "OrderedDict[tuple, Optional[pygame.Surface]]" = OrderedDict()
        # normalized-colors-tuple cache for get_sprite_recolored/recolor_body,
        # keyed by id(colors) - see _colors_key().
        self._colors_key_cache: Dict[int, Tuple[list, Tuple[int, ...]]] = {}

        # Subdirectories to search within each path
        self.subdirs = ['', 'bodies', 'heads', 'swords', 'shields', 'hats',
                        'images', 'sprites', 'ganis', 'npcs', 'baddies', 'bomys',
                        'horses', 'backpals']

    @staticmethod
    def _evict_lru(cache: "OrderedDict", max_size: int):
        """Drop least-recently-used entries once `cache` exceeds `max_size`."""
        while len(cache) > max_size:
            cache.popitem(last=False)

    def find_file(self, name: str) -> Optional[Path]:
        """Find a sprite image file by name in search paths."""
        return find_asset_file(self.search_paths, self.subdirs, name)

    def load_sheet(self, name: str) -> Optional[pygame.Surface]:
        """
        Load a sprite sheet by name.

        Args:
            name: Filename of the sprite sheet (e.g., 'body.png')

        Returns:
            pygame.Surface or None if not found
        """
        name = normalize_asset_name(name)
        if name in self.sheet_cache:
            self.sheet_cache.move_to_end(name)
            return self._display_sheet(name)
        if name in self._missing_sheets:
            return None

        # Find file
        file_path = self.find_file(name)
        if not file_path:
            data = self.fetch_bytes(name) if self.fetch_bytes is not None else None
            if data is not None:
                return self.load_bytes(name, data)
            self._missing_sheets.add(name)
            return None

        # Load image
        try:
            if name.lower().endswith('.mng'):
                animation = decode_mng(file_path.read_bytes())
                surface = self._cache_animation(name, animation)
            else:
                surface = pygame.image.load(str(file_path))
                self._stash_raw8(name, surface)
            # Convert for faster blitting, preserve alpha
            surface = self._convert_surface(
                surface, surface.get_alpha() is not None
                or name.lower().endswith(('.png', '.mng')),
            )
            self.sheet_cache[name] = surface
            self._missing_sheets.discard(name)
            self._evict_lru(self.sheet_cache, _MAX_CACHED_SHEETS)
            return surface
        except Exception as e:
            print(f"Error loading sprite sheet {name}: {e}")
            self._missing_sheets.add(name)
            return None

    def has_sheet(self, name: str) -> bool:
        """True if `name` is loaded in the cache (a cached None miss is not)."""
        name = normalize_asset_name(name)
        return self.sheet_cache.get(name) is not None

    def get_animation(self, name: str) -> Optional[MNGAnimation]:
        """Return decoded animation metadata, loading the asset if necessary."""
        name = normalize_asset_name(name)
        if name not in self.sheet_cache:
            self.load_sheet(name)
        return self.animation_cache.get(name)

    def get_static_sheet(self, name: str) -> Optional[pygame.Surface]:
        """Return frame zero for animated assets and the normal static image."""
        name = normalize_asset_name(name)
        if name not in self.sheet_cache:
            self.load_sheet(name)
        return self.sheet_cache.get(name)

    def _cache_animation(self, name: str, animation: MNGAnimation):
        frames = tuple(self._convert_surface(frame, True) for frame in animation.frames)
        animation = MNGAnimation(
            animation.width, animation.height, animation.ticks_per_second,
            frames, animation.frame_delays, animation.used_static_fallback,
        )
        self.animation_cache[name] = animation
        self._evict_lru(self.animation_cache, _MAX_CACHED_SHEETS)
        return frames[0]

    def _stash_raw8(self, name: str, surface) -> None:
        """Keep the pre-conversion surface when it is palettized (8-bit)."""
        try:
            if surface.get_bitsize() == 8:
                self._raw8_cache[name] = surface
                self._evict_lru(self._raw8_cache, _MAX_CACHED_SHEETS)
        except Exception:
            pass

    def get_raw8(self, name: str):
        """The original 8-bit surface for `name` (palette intact), loading the
        file if it has not been used yet. Returns None for truecolor images or
        misses. Used by TilesetManager's setbackpal palette swap."""
        name = normalize_asset_name(name)
        if name not in self.sheet_cache:
            self.load_sheet(name)
        return self._raw8_cache.get(name)

    @staticmethod
    def _convert_surface(surface, preserve_alpha):
        if pygame.display.get_surface() is None:
            return surface
        if preserve_alpha or surface.get_alpha() is not None:
            return surface.convert_alpha()
        return surface.convert()

    def _display_sheet(self, name: str):
        """Select the current timed frame. Ordinary cached data remains frame 0."""
        animation = self.animation_cache.get(name)
        if animation is None or len(animation.frames) < 2:
            return self.sheet_cache.get(name)
        total = sum(animation.frame_delays)
        if total <= 0:
            return animation.frames[0]
        elapsed = (pygame.time.get_ticks() / 1000.0) % total
        for frame, delay in zip(animation.frames, animation.frame_delays):
            if elapsed < delay:
                return frame
            elapsed -= delay
        return animation.frames[-1]

    def load_bytes(self, name: str, data: bytes) -> Optional[pygame.Surface]:
        """Load a sprite sheet from in-memory bytes (e.g. a file downloaded from
        the server) and cache it under `name`, so load_sheet(name) finds it."""
        name = normalize_asset_name(name)
        # Already known to be undecodable (some bomber assets, e.g.
        # eye_bomb_blackhole*.png, arrive as non-image data) — don't re-decode
        # or re-log every time the server re-sends them. A plain cached-None in
        # sheet_cache is only a disk miss (the NPC rendered before this file
        # downloaded) and must fall through so the freshly downloaded bytes get
        # decoded and cached.
        if name in self._undecodable_bytes:
            return None
        self._invalidate_sheet_derivatives(name)
        import io
        try:
            if name.lower().endswith('.mng'):
                surface = self._cache_animation(name, decode_mng(data))
            else:
                surface = pygame.image.load(io.BytesIO(data), name)
                self._stash_raw8(name, surface)
            surface = self._convert_surface(
                surface, surface.get_alpha() is not None
                or name.lower().endswith(('.png', '.mng')),
            )
            self.sheet_cache[name] = surface
            self._missing_sheets.discard(name)
            self._evict_lru(self.sheet_cache, _MAX_CACHED_SHEETS)
            return surface
        except Exception as e:
            print(f"Error loading downloaded sheet {name}: {e}")
            self.sheet_cache.pop(name, None)
            self._missing_sheets.add(name)
            self._undecodable_bytes.add(name)
            return None

    def _invalidate_sheet_derivatives(self, name: str) -> None:
        """Drop cached surfaces cut or recolored from one source sheet."""
        self.animation_cache.pop(name, None)
        self._raw8_cache.pop(name, None)
        for cache in (
            self.sprite_cache,
            self._recolor_sheet_cache,
            self._recolor_sprite_cache,
        ):
            for key in tuple(cache):
                if key[0] == name:
                    del cache[key]

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
        sheet_name = normalize_asset_name(sheet_name)
        # Check sprite cache
        cache_key = (sheet_name, x, y, width, height)
        if sheet_name not in self.animation_cache and cache_key in self.sprite_cache:
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
            if x < 0 or y < 0:
                # Negative source coords are a deliberate script idiom for "no
                # sprite for this state" (the v6 bomber's -GraalUI heart rows
                # walk part-x to -80, -160, ... for empty heart slots): the
                # real client samples off-sheet and draws nothing. Clamping to
                # x/y 0 instead painted whatever art happens to live at the
                # sheet's corner. Cache the miss like an off-sheet part below.
                self.sprite_cache[cache_key] = None
                self._evict_lru(self.sprite_cache, _MAX_CACHED_SPRITES)
                return None
            if x + width > sheet_w or y + height > sheet_h:
                # Clamp positive overshoot to the valid region
                x = max(0, min(x, sheet_w - 1))
                y = max(0, min(y, sheet_h - 1))
                width = min(width, sheet_w - x)
                height = min(height, sheet_h - y)
                if width <= 0 or height <= 0:
                    return None

            # Create subsurface
            sprite = sheet.subsurface((x, y, width, height)).copy()
            if sheet_name not in self.animation_cache:
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
        (and, incidentally, keeping a reference to it so the id cannot be
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
        Cached per (sheet_name, colors-tuple). Returns None if the base sheet
        is not loaded yet (cache-the-miss - retried once it downloads, same
        policy as load_sheet)."""
        sheet_name = normalize_asset_name(sheet_name)
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
        back to the plain (uncoloured) sprite if colors is not a usable 5-value
        sequence, so callers can pass a possibly-None `colors` unconditionally."""
        sheet_name = normalize_asset_name(sheet_name)
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
        self._missing_sheets.clear()
        self.animation_cache.clear()
        self.sprite_cache.clear()
        self._recolor_sheet_cache.clear()
        self._recolor_sprite_cache.clear()
        self._colors_key_cache.clear()

class TilesetManager:
    """
    Specialized manager for Reborn tilesets.

    The manager uses the non-linear tile ID map from Reborn level files.
    """

    TILE_SIZE = 16

    def __init__(self, sprite_manager: SpriteManager):
        """Create the tileset manager with a sprite manager."""
        self.sprite_mgr = sprite_manager
        self.tile_cache: Dict[Tuple[str, int], pygame.Surface] = {}
        # get_tile_or_color()'s colored fallback for a missing tile, cached per
        # tile_id so a level full of undownloaded tiles doesn't allocate a new
        # placeholder Surface on every miss every frame.
        self._placeholder_cache: Dict[int, pygame.Surface] = {}
        self.default_tileset = "dustynewpics1.png"
        # Tileset overrides set by GS1/GS2 addtiledef(2). Real-client
        # semantics: defs PERSIST across level changes (Bomber v6 sets them
        # once in its preloader) and are scoped by a levelstart prefix --
        # "" applies everywhere, "bombarena" only to bombarena*.nw. Only a
        # script's removetiledefs clears them.
        # Partial-sheet pastes (addtiledef2), in script order. Later entries
        # are blitted last and therefore win where images overlap.
        self.tiledefs: List[Tuple[str, str, int, int]] = []
        # Base definitions (image, prefix, m_type) use the longest matching
        # prefix; ties keep the earlier definition, and defs with
        # m_type >= 3 (except 5) are skipped (TTiles.cpp:568-631). The
        # m_type also selects the tile-TYPE table — see tiletypes.py.
        self.full_tiledefs: List[Tuple[str, str, int]] = []
        # Player's current level, lowercased -- selects which defs apply.
        self.current_level = ""
        # GS1 `setbackpal <file>`: name of an indexed image whose 256-entry
        # PALETTE replaces the tileset's (GTA's underwaterpal/dusk/moonpal +
        # the *Clock weapon's seasonal grayscale). "" = stock palette. Like
        # tiledefs, it persists across level changes until a script changes
        # it. Only applies when the base tileset itself is palettized -- a
        # truecolor tileset has no indices to remap (documented limitation;
        # every classic sheet incl. pics1.png is indexed).
        self.backpal = ""
        self._composed_sheet: Optional[pygame.Surface] = None
        self._composed_sheet_valid = False

    def _applies(self, prefix: str) -> bool:
        return not prefix or self.current_level.startswith(prefix)

    def set_current_level(self, level_name: str):
        """Level change: re-evaluate which tiledefs apply (defs themselves
        persist -- see class comment)."""
        name = (level_name or "").lower()
        if name != self.current_level:
            self.current_level = name
            self.clear_cache()

    def set_tiledef(self, image: str, levelstart: str, x: int, y: int):
        """addtiledef2: paste `image` at sheet pixel (`x`, `y`) in levels
        starting with `levelstart`."""
        entry = (strip_tiledef_image(image), (levelstart or "").lower(),
                 int(x), int(y))
        if entry in self.tiledefs:
            return
        _, prefix, paste_x, paste_y = entry
        self.tiledefs = [
            existing for existing in self.tiledefs
            if not (existing[1] == prefix
                    and existing[2] == paste_x
                    and existing[3] == paste_y)
        ]
        self.tiledefs.append(entry)
        self.clear_cache()

    def set_full_tiledef(self, image: str, levelstart: str = "",
                         tile_type: int = 0):
        """addtiledef: replace the whole default tileset with `image` in
        levels starting with `levelstart`. `tile_type` is the def's m_type
        (0 classic, 1/2 new-world, 5 none)."""
        entry = (strip_tiledef_image(image), (levelstart or "").lower(),
                 int(tile_type))
        if entry in self.full_tiledefs:
            return
        prefix = entry[1]
        self.full_tiledefs = [
            existing for existing in self.full_tiledefs
            if existing[1] != prefix
        ]
        self.tiledefs = [
            existing for existing in self.tiledefs
            if existing[1] != prefix
        ]
        self.full_tiledefs.append(entry)
        self.clear_cache()

    def clear_tiledefs(self, prefix: str = "") -> bool:
        """Remove definitions whose stored prefix starts with `prefix`."""
        prefix = (prefix or "").lower()
        tiledefs = [
            entry for entry in self.tiledefs
            if not entry[1].startswith(prefix)
        ]
        full_tiledefs = [
            entry for entry in self.full_tiledefs
            if not entry[1].startswith(prefix)
        ]
        changed = (tiledefs != self.tiledefs
                   or full_tiledefs != self.full_tiledefs)
        if changed:
            self.tiledefs = tiledefs
            self.full_tiledefs = full_tiledefs
            self.clear_cache()
        return changed

    def set_backpal(self, image: str) -> bool:
        """Set (or clear, with "") the setbackpal palette source. Returns
        whether anything changed. A change drops the extracted-tile and
        composed-sheet caches so the next draw re-derives them."""
        image = normalize_asset_name(image)
        if image == self.backpal:
            return False
        self.backpal = image
        self.clear_cache()
        return True

    def _palettized_base(self, base_name: str) -> Optional[pygame.Surface]:
        """The base sheet with the backpal file's palette applied: both must
        still exist as 8-bit surfaces (SpriteManager stashes those before
        display conversion). None = cannot swap (missing/truecolor), caller
        falls back to the stock sheet."""
        raw = self.sprite_mgr.get_raw8(base_name)
        pal = self.sprite_mgr.get_raw8(self.backpal)
        if raw is None or pal is None:
            return None
        try:
            swapped = raw.copy()
            swapped.set_palette(pal.get_palette())
            return self.sprite_mgr._convert_surface(swapped, True)
        except Exception:
            return None

    def _get_composed_sheet(self) -> Optional[pygame.Surface]:
        """Build the active sheet from its base and applicable pastes."""
        if self._composed_sheet_valid:
            return self._composed_sheet

        base_name = self.default_tileset
        best_prefix_length = -1
        for image, prefix, m_type in self.full_tiledefs:
            # GetLevelTiles skips defs with m_type >= 3 (except 5) for the
            # base image exactly as it does for the tilestype.
            if m_type >= 3 and m_type != 5:
                continue
            if (self._applies(prefix)
                    and len(prefix) > best_prefix_length
                    and self.sprite_mgr.has_sheet(image)):
                base_name = image
                best_prefix_length = len(prefix)

        base = self._palettized_base(base_name) if self.backpal else None
        if base is None:
            base = self.sprite_mgr.load_sheet(base_name)
        if base is None:
            self._composed_sheet = None
            self._composed_sheet_valid = True
            return None

        composed = base.copy()
        for image, prefix, x, y in self.tiledefs:
            if not self._applies(prefix):
                continue
            paste = self.sprite_mgr.load_sheet(image)
            if paste is not None:
                composed.blit(paste, (x, y))

        self._composed_sheet = composed
        self._composed_sheet_valid = True
        return composed

    def get_tile(self, tile_id: int, tileset: Optional[str] = None) -> Optional[pygame.Surface]:
        """
        Get a tile surface by ID.

        Args:
            tile_id: tile ID (0-4095)
            tileset: Tileset filename (uses default if None)

        Returns:
            pygame.Surface or None
        """
        if tileset is not None:
            tileset = normalize_asset_name(tileset)
        if tileset is None:
            # backpal routes through the composed-sheet path too: the palette
            # swap happens on the whole sheet, not per extracted tile.
            if self.backpal or any(self._applies(prefix)
                                   for _, prefix, _, _ in self.tiledefs):
                cache_key = ("<composed>", tile_id)
                if cache_key in self.tile_cache:
                    return self.tile_cache[cache_key]

                sheet = self._get_composed_sheet()
                if sheet is None:
                    return None
                tx = (tile_id // 512) * 16 + (tile_id % 16)
                ty = (tile_id // 16) % 32
                rect = (tx * self.TILE_SIZE, ty * self.TILE_SIZE,
                        self.TILE_SIZE, self.TILE_SIZE)
                if sheet.get_rect().contains(rect):
                    tile = sheet.subsurface(rect).copy()
                    self.tile_cache[cache_key] = tile
                    return tile
            best_prefix_length = -1
            for image, prefix, m_type in self.full_tiledefs:
                if m_type >= 3 and m_type != 5:
                    continue
                if (self._applies(prefix)
                        and len(prefix) > best_prefix_length
                        and self.sprite_mgr.has_sheet(image)):
                    tileset = image
                    best_prefix_length = len(prefix)
            if best_prefix_length < 0:
                tileset = self.default_tileset

        tileset = normalize_asset_name(tileset)
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
        self.sprite_mgr.load_sheet(normalize_asset_name(tileset))

    def clear_cache(self):
        """Clear extracted tiles and the lazily composed sheet."""
        self.tile_cache.clear()
        self._composed_sheet = None
        self._composed_sheet_valid = False


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
