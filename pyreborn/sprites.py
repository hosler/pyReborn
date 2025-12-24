"""
pyreborn - Sprite sheet manager.

Handles loading, caching, and extracting sprites from sprite sheets.
Works with pygame surfaces.
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple
import os

# Pygame import is optional - only needed when actually used
try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False


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
        self.sheet_cache: Dict[str, pygame.Surface] = {}
        self.sprite_cache: Dict[Tuple[str, int, int, int, int], pygame.Surface] = {}

        # Subdirectories to search within each path
        self.subdirs = ['', 'bodies', 'heads', 'swords', 'shields', 'hats',
                        'images', 'sprites', 'ganis', 'npcs', 'baddies', 'bomys']

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
        # Check cache
        if name in self.sheet_cache:
            return self.sheet_cache[name]

        # Find file
        file_path = self.find_file(name)
        if not file_path:
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
            return surface
        except Exception as e:
            print(f"Error loading sprite sheet {name}: {e}")
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
            return sprite
        except Exception as e:
            print(f"Error extracting sprite from {sheet_name} at ({x},{y},{width},{height}): {e}")
            return None

    def get_sprite_or_placeholder(self, sheet_name: str, x: int, y: int,
                                   width: int, height: int,
                                   color: Tuple[int, int, int] = (200, 100, 200)) -> pygame.Surface:
        """
        Get a sprite, or create a colored placeholder if not available.

        Args:
            sheet_name: Name of the sprite sheet file
            x, y, width, height: Sprite region
            color: Fallback color for placeholder

        Returns:
            pygame.Surface (sprite or placeholder)
        """
        sprite = self.get_sprite(sheet_name, x, y, width, height)
        if sprite:
            return sprite

        # Create placeholder
        placeholder = pygame.Surface((width, height), pygame.SRCALPHA)
        placeholder.fill((*color, 128))
        return placeholder

    def preload(self, names: List[str]):
        """Preload multiple sprite sheets."""
        for name in names:
            self.load_sheet(name)

    def clear_cache(self):
        """Clear all cached sprites and sheets."""
        self.sheet_cache.clear()
        self.sprite_cache.clear()

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
        self.default_tileset = "dustynewpics1.png"

    def get_tile(self, tile_id: int, tileset: Optional[str] = None) -> Optional[pygame.Surface]:
        """
        Get a tile surface by ID.

        Args:
            tile_id: tile ID (0-4095)
            tileset: Tileset filename (uses default if None)

        Returns:
            pygame.Surface or None
        """
        if tileset is None:
            tileset = self.default_tileset

        cache_key = (tileset, tile_id)
        if cache_key in self.tile_cache:
            return self.tile_cache[cache_key]

        # Calculate tileset coordinates using Reborn's formula
        # The tileset is organized in a specific pattern
        tileset_x = (tile_id // 512) * 16 + (tile_id % 16)
        tileset_y = (tile_id // 16) % 32

        # Convert to pixels
        px = tileset_x * self.TILE_SIZE
        py = tileset_y * self.TILE_SIZE

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

        # Generate color from tile ID for visual debugging
        r = (tile_id * 17) % 256
        g = (tile_id * 31) % 256
        b = (tile_id * 47) % 256

        placeholder = pygame.Surface((self.TILE_SIZE, self.TILE_SIZE))
        placeholder.fill((r, g, b))
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
