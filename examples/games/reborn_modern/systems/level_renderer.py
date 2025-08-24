"""
Level Renderer
==============

Handles efficient rendering of level tiles with caching support.
"""

import pygame
import logging
from typing import Optional, Dict, Tuple
from collections import OrderedDict

from pyreborn.models import Level
from .camera import Camera


logger = logging.getLogger(__name__)


class LevelRenderer:
    """Renders individual levels with tile caching"""
    
    def __init__(self, screen: pygame.Surface, tileset: Optional[pygame.Surface] = None):
        """Initialize level renderer
        
        Args:
            screen: Pygame screen surface
            tileset: Optional tileset image
        """
        self.screen = screen
        self.tileset = tileset
        
        # Surface cache (LRU)
        self.cache_size = 10  # Maximum cached level surfaces
        self.surface_cache: OrderedDict[str, pygame.Surface] = OrderedDict()
        
        # Tile size constants
        self.TILE_SIZE = 16
        self.LEVEL_WIDTH = 64
        self.LEVEL_HEIGHT = 64
        
        # Colors for missing data
        self.MISSING_DATA_COLOR = (80, 40, 40)  # Dark red
        self.LOADING_COLOR = (40, 40, 80)       # Dark blue
        self.EMPTY_TILE_COLOR = (20, 30, 20)    # Very dark green
        
        # Performance tracking
        self.tiles_rendered = 0
        self.cache_hits = 0
        self.cache_misses = 0
        
    def render_single(self, level: Optional[Level], camera: Camera):
        """Render a single level
        
        Args:
            level: Level to render (None shows loading screen)
            camera: Camera for viewport transformation
        """
        if not level:
            self._render_loading_screen(camera)
            return
            
        # Check if level has board data
        if not hasattr(level, 'board_tiles') or not level.board_tiles:
            self._render_missing_data(level.name, camera)
            return
            
        # Get or create level surface
        surface = self._get_level_surface(level)
        if not surface:
            self._render_missing_data(level.name, camera)
            return
            
        # Calculate screen position
        screen_x = -int(camera.x * self.TILE_SIZE * camera.zoom)
        screen_y = -int(camera.y * self.TILE_SIZE * camera.zoom)
        
        # Scale surface if zoomed
        if camera.zoom != 1.0:
            scaled_width = int(surface.get_width() * camera.zoom)
            scaled_height = int(surface.get_height() * camera.zoom)
            scaled_surface = pygame.transform.scale(surface, (scaled_width, scaled_height))
            self.screen.blit(scaled_surface, (screen_x, screen_y))
        else:
            self.screen.blit(surface, (screen_x, screen_y))
            
    def render_at_position(self, level: Optional[Level], screen_x: int, screen_y: int, 
                          tile_size: int) -> bool:
        """Render a level at specific screen position (for GMAP)
        
        Args:
            level: Level to render
            screen_x: Screen X position
            screen_y: Screen Y position
            tile_size: Size of each tile in pixels
            
        Returns:
            True if rendered successfully
        """
        if not level:
            # Draw placeholder for missing level
            self._draw_placeholder(screen_x, screen_y, tile_size, "Not Loaded")
            return False
            
        # Check if level has board data with meaningful content
        if not hasattr(level, 'board_tiles') or not level.board_tiles:
            self._draw_placeholder(screen_x, screen_y, tile_size, "No Data")
            return False
            
        # Check if board data has meaningful content
        # Don't check for non-zero tiles since tile 0 is valid (grass)
        # Just ensure board_tiles exists and has the right size
        if len(level.board_tiles) != self.LEVEL_WIDTH * self.LEVEL_HEIGHT:
            self._draw_placeholder(screen_x, screen_y, tile_size, "Invalid Data")
            return False
            
        # Get or create level surface
        surface = self._get_level_surface(level)
        if not surface:
            self._draw_placeholder(screen_x, screen_y, tile_size, "Error")
            return False
            
        # Scale if needed
        if tile_size != self.TILE_SIZE:
            scale_factor = tile_size / self.TILE_SIZE
            scaled_width = int(surface.get_width() * scale_factor)
            scaled_height = int(surface.get_height() * scale_factor)
            scaled_surface = pygame.transform.scale(surface, (scaled_width, scaled_height))
            self.screen.blit(scaled_surface, (screen_x, screen_y))
        else:
            self.screen.blit(surface, (screen_x, screen_y))
            
        return True
        
    def _get_level_surface(self, level: Level) -> Optional[pygame.Surface]:
        """Get cached level surface or render new one
        
        Args:
            level: Level to get surface for
            
        Returns:
            Level surface or None if rendering failed
        """
        cache_key = f"{level.name}_{id(level.board_tiles)}"
        
        # Check cache
        if cache_key in self.surface_cache:
            # Move to end (LRU)
            self.surface_cache.move_to_end(cache_key)
            self.cache_hits += 1
            return self.surface_cache[cache_key]
            
        # Cache miss - render level
        self.cache_misses += 1
        surface = self._render_level_surface(level)
        
        if surface:
            # Add to cache
            self.surface_cache[cache_key] = surface
            
            # Evict oldest if cache full
            if len(self.surface_cache) > self.cache_size:
                self.surface_cache.popitem(last=False)
                
        return surface
        
    def _render_level_surface(self, level: Level) -> Optional[pygame.Surface]:
        """Render a level to a surface
        
        Args:
            level: Level to render
            
        Returns:
            Rendered surface or None if failed
        """
        try:
            # Create surface
            width = self.LEVEL_WIDTH * self.TILE_SIZE
            height = self.LEVEL_HEIGHT * self.TILE_SIZE
            surface = pygame.Surface((width, height))
            surface.fill(self.EMPTY_TILE_COLOR)
            
            # Reset tile counter
            self.tiles_rendered = 0
            
            # Render tiles
            for y in range(self.LEVEL_HEIGHT):
                for x in range(self.LEVEL_WIDTH):
                    tile_id = level.get_tile(x, y, 0)  # Layer 0
                    
                    # Render all tiles including tile 0 (grass)
                    # Tile 0 is grass at position (0,0) on the tileset
                    if self.tileset:
                        self._render_tile_from_tileset(surface, tile_id, x, y)
                    else:
                        self._render_tile_as_color(surface, tile_id, x, y)
                    self.tiles_rendered += 1
                        
            logger.debug(f"Rendered level {level.name}: {self.tiles_rendered} tiles")
            return surface
            
        except Exception as e:
            logger.error(f"Failed to render level {level.name}: {e}")
            return None
            
    def _render_tile_from_tileset(self, surface: pygame.Surface, tile_id: int, 
                                  x: int, y: int):
        """Render a tile from tileset
        
        Args:
            surface: Surface to render to
            tile_id: Tile ID
            x: Tile X position
            y: Tile Y position
        """
        try:
            # Calculate tileset coordinates using Reborn's algorithm
            tileset_tx = (tile_id // 512) * 16 + (tile_id % 16)
            tileset_ty = (tile_id // 16) % 32
            source_x = tileset_tx * self.TILE_SIZE
            source_y = tileset_ty * self.TILE_SIZE
            
            # Check bounds
            if (source_x + self.TILE_SIZE <= self.tileset.get_width() and
                source_y + self.TILE_SIZE <= self.tileset.get_height()):
                
                # Extract and blit tile
                tile_rect = pygame.Rect(source_x, source_y, self.TILE_SIZE, self.TILE_SIZE)
                dest_pos = (x * self.TILE_SIZE, y * self.TILE_SIZE)
                surface.blit(self.tileset, dest_pos, tile_rect)
            else:
                # Fallback to color
                self._render_tile_as_color(surface, tile_id, x, y)
                
        except Exception:
            # Fallback to color on any error
            self._render_tile_as_color(surface, tile_id, x, y)
            
    def _render_tile_as_color(self, surface: pygame.Surface, tile_id: int, 
                             x: int, y: int):
        """Render a tile as a colored rectangle
        
        Args:
            surface: Surface to render to
            tile_id: Tile ID
            x: Tile X position
            y: Tile Y position
        """
        # Generate color from tile ID
        color = self._tile_id_to_color(tile_id)
        rect = pygame.Rect(x * self.TILE_SIZE, y * self.TILE_SIZE, 
                          self.TILE_SIZE, self.TILE_SIZE)
        pygame.draw.rect(surface, color, rect)
        
        # Add subtle border
        border_color = tuple(min(255, c + 30) for c in color)
        pygame.draw.rect(surface, border_color, rect, 1)
        
    def _tile_id_to_color(self, tile_id: int) -> Tuple[int, int, int]:
        """Convert tile ID to a color
        
        Args:
            tile_id: Tile ID
            
        Returns:
            RGB color tuple
        """
        # Generate consistent color from tile ID
        r = (tile_id * 123) % 256
        g = (tile_id * 456) % 256
        b = (tile_id * 789) % 256
        
        # Ensure not too dark
        brightness = r + g + b
        if brightness < 150:
            r = min(255, r + 80)
            g = min(255, g + 80)
            b = min(255, b + 80)
            
        return (r, g, b)
        
    def _render_loading_screen(self, camera: Camera):
        """Render loading screen"""
        font = pygame.font.Font(None, 48)
        text = font.render("Loading Level...", True, (255, 255, 255))
        text_rect = text.get_rect(center=(self.screen.get_width() // 2, 
                                         self.screen.get_height() // 2))
        self.screen.blit(text, text_rect)
        
    def _render_missing_data(self, level_name: str, camera: Camera):
        """Render missing data indicator"""
        # Fill with error color
        self.screen.fill(self.MISSING_DATA_COLOR)
        
        # Draw error message
        font = pygame.font.Font(None, 36)
        text1 = font.render(f"Level: {level_name}", True, (255, 255, 255))
        text2 = font.render("Waiting for board data...", True, (255, 200, 200))
        
        center_x = self.screen.get_width() // 2
        center_y = self.screen.get_height() // 2
        
        text1_rect = text1.get_rect(center=(center_x, center_y - 20))
        text2_rect = text2.get_rect(center=(center_x, center_y + 20))
        
        self.screen.blit(text1, text1_rect)
        self.screen.blit(text2, text2_rect)
        
    def _draw_placeholder(self, x: int, y: int, tile_size: int, text: str):
        """Draw a placeholder for missing level
        
        Args:
            x: Screen X position
            y: Screen Y position
            tile_size: Size of each tile
            text: Text to display
        """
        size = self.LEVEL_WIDTH * tile_size
        
        # Draw background
        pygame.draw.rect(self.screen, self.LOADING_COLOR, (x, y, size, size))
        pygame.draw.rect(self.screen, (100, 100, 200), (x, y, size, size), 2)
        
        # Draw text if tile size allows
        if tile_size >= 8:
            font = pygame.font.Font(None, min(24, tile_size * 2))
            text_surface = font.render(text, True, (255, 255, 255))
            text_rect = text_surface.get_rect(center=(x + size // 2, y + size // 2))
            self.screen.blit(text_surface, text_rect)
            
    def invalidate_cache(self, level_name: Optional[str] = None):
        """Invalidate cache for a specific level or all levels
        
        Args:
            level_name: Level name to invalidate, or None for all
        """
        if level_name:
            # Remove specific level from cache
            keys_to_remove = [k for k in self.surface_cache.keys() 
                            if k.startswith(f"{level_name}_")]
            for key in keys_to_remove:
                del self.surface_cache[key]
            logger.debug(f"Invalidated cache for level: {level_name}")
        else:
            # Clear entire cache
            self.surface_cache.clear()
            logger.debug("Cleared entire level cache")
            
    def get_cache_stats(self) -> dict:
        """Get cache statistics"""
        total_requests = self.cache_hits + self.cache_misses
        hit_rate = self.cache_hits / total_requests if total_requests > 0 else 0
        
        return {
            'cache_size': len(self.surface_cache),
            'max_size': self.cache_size,
            'hits': self.cache_hits,
            'misses': self.cache_misses,
            'hit_rate': hit_rate,
            'tiles_rendered': self.tiles_rendered
        }