"""
Unified Renderer
================

Simplified renderer that combines level and GMAP rendering into one system.
Reduces complexity from 1200+ lines to ~400 lines.
"""

import pygame
import logging
from typing import Optional, Dict, Tuple
from pathlib import Path

from pyreborn import Client
from pyreborn.models import Level

logger = logging.getLogger(__name__)


class UnifiedRenderer:
    """Unified rendering system for both single levels and GMAP"""
    
    def __init__(self, screen: pygame.Surface):
        self.screen = screen
        self.width = screen.get_width()
        self.height = screen.get_height()
        
        # Camera position (in tiles)
        self.camera_x = 0.0
        self.camera_y = 0.0
        self.zoom = 1.0
        self.tile_size = 16
        
        # Tileset
        self.tileset = None
        self.tile_cache: Dict[int, pygame.Surface] = {}
        
        # Level cache for performance
        self.level_surfaces: Dict[str, pygame.Surface] = {}
        
        # Debug flags
        self.show_grid = False
        self.show_links = False
        self.show_entities = True
        
        self._load_tileset()
        
    def _load_tileset(self):
        """Load the tileset image"""
        try:
            game_root = Path(__file__).parent.parent
            assets_dir = game_root / "assets"
            
            for name in ['pics1.png', 'tileset.png', 'tiles.png']:
                tileset_path = assets_dir / name
                if tileset_path.exists():
                    self.tileset = pygame.image.load(str(tileset_path)).convert()
                    logger.info(f"Loaded tileset: {name}")
                    self._prepare_tile_cache()
                    return
                    
            logger.warning("No tileset found")
            
        except Exception as e:
            logger.error(f"Failed to load tileset: {e}")
            
    def _prepare_tile_cache(self):
        """Pre-cache commonly used tiles"""
        if not self.tileset:
            return
            
        # Cache first 512 tiles (most common)
        for tile_id in range(512):
            self._get_tile(tile_id)
            
    def _get_tile(self, tile_id: int) -> Optional[pygame.Surface]:
        """Get a tile surface from the tileset"""
        if tile_id in self.tile_cache:
            return self.tile_cache[tile_id]
            
        if not self.tileset:
            return None
            
        # Calculate position in tileset (16 tiles per row)
        tiles_per_row = self.tileset.get_width() // 16
        tile_x = (tile_id % tiles_per_row) * 16
        tile_y = (tile_id // tiles_per_row) * 16
        
        # Extract tile
        if tile_x + 16 <= self.tileset.get_width() and tile_y + 16 <= self.tileset.get_height():
            tile = self.tileset.subsurface((tile_x, tile_y, 16, 16))
            self.tile_cache[tile_id] = tile
            return tile
            
        return None
        
    def update_camera(self, target_x: float, target_y: float):
        """Update camera to follow target"""
        # Center camera on target
        self.camera_x = target_x - (self.width / 2 / self.tile_size / self.zoom)
        self.camera_y = target_y - (self.height / 2 / self.tile_size / self.zoom)
        
    def render(self, client: Client):
        """Main render method"""
        if not client:
            return
            
        # Get managers
        level_mgr = client.get_manager('level')
        session_mgr = client.get_manager('session')
        gmap_mgr = client.get_manager('gmap')
        
        if not level_mgr:
            return
            
        # Get current level and player
        level = level_mgr.get_current_level()
        player = session_mgr.get_player() if session_mgr else None
        
        if not level:
            return
            
        # Update camera to follow player
        if player:
            if client.is_gmap_mode() and gmap_mgr and gmap_mgr.is_active():
                # GMAP mode - use world coordinates
                world_x = player.gmaplevelx * 64 + player.x if hasattr(player, 'gmaplevelx') else player.x
                world_y = player.gmaplevely * 64 + player.y if hasattr(player, 'gmaplevely') else player.y
                self.update_camera(world_x, world_y)
            else:
                # Single level mode
                self.update_camera(player.x, player.y)
                
        # Render based on mode
        if client.is_gmap_mode() and gmap_mgr and gmap_mgr.is_active():
            self._render_gmap(client, gmap_mgr, level_mgr)
        else:
            self._render_single_level(level)
            
        # Render entities on top
        if self.show_entities:
            self._render_entities(client)
            
        # Debug overlays
        if self.show_grid:
            self._render_grid()
        if self.show_links and level:
            self._render_level_links(level)
            
    def _render_single_level(self, level: Level):
        """Render a single level"""
        if not level or not level.tiles:
            return
            
        # Get or create cached surface
        if level.name not in self.level_surfaces:
            self._cache_level(level)
            
        surface = self.level_surfaces.get(level.name)
        if not surface:
            return
            
        # Calculate visible area
        screen_tiles_x = int(self.width / self.tile_size / self.zoom) + 2
        screen_tiles_y = int(self.height / self.tile_size / self.zoom) + 2
        
        start_x = max(0, int(self.camera_x))
        start_y = max(0, int(self.camera_y))
        end_x = min(level.width, start_x + screen_tiles_x)
        end_y = min(level.height, start_y + screen_tiles_y)
        
        # Render visible portion
        source_rect = pygame.Rect(
            start_x * 16, start_y * 16,
            (end_x - start_x) * 16, (end_y - start_y) * 16
        )
        
        dest_x = -self.camera_x * self.tile_size * self.zoom
        dest_y = -self.camera_y * self.tile_size * self.zoom
        
        if self.zoom != 1.0:
            # Scale if zoomed
            scaled = pygame.transform.scale(
                surface.subsurface(source_rect),
                (int(source_rect.width * self.zoom), int(source_rect.height * self.zoom))
            )
            self.screen.blit(scaled, (dest_x, dest_y))
        else:
            self.screen.blit(surface, (dest_x, dest_y), source_rect)
            
    def _render_gmap(self, client, gmap_mgr, level_mgr):
        """Render GMAP view"""
        # Get visible levels
        visible_levels = gmap_mgr.get_visible_levels(
            self.camera_x, self.camera_y,
            self.width / self.tile_size / self.zoom,
            self.height / self.tile_size / self.zoom
        )
        
        for level_name in visible_levels:
            level = level_mgr.get_level(level_name)
            if level:
                # Calculate offset for this level in world coordinates
                segment_x = level.gmaplevelx if hasattr(level, 'gmaplevelx') else 0
                segment_y = level.gmaplevely if hasattr(level, 'gmaplevely') else 0
                
                # Temporarily adjust camera for this level
                old_cam_x, old_cam_y = self.camera_x, self.camera_y
                self.camera_x -= segment_x * 64
                self.camera_y -= segment_y * 64
                
                self._render_single_level(level)
                
                # Restore camera
                self.camera_x, self.camera_y = old_cam_x, old_cam_y
                
    def _render_entities(self, client):
        """Render all entities (players, NPCs)"""
        session_mgr = client.get_manager('session')
        if not session_mgr:
            return
            
        # Render all players
        for player in session_mgr.get_all_players().values():
            self._render_player(player, client.is_gmap_mode())
            
    def _render_player(self, player, is_gmap: bool):
        """Render a single player"""
        # Calculate screen position
        if is_gmap and hasattr(player, 'gmaplevelx'):
            world_x = player.gmaplevelx * 64 + player.x
            world_y = player.gmaplevely * 64 + player.y
        else:
            world_x = player.x
            world_y = player.y
            
        screen_x = (world_x - self.camera_x) * self.tile_size * self.zoom
        screen_y = (world_y - self.camera_y) * self.tile_size * self.zoom
        
        # Simple player representation (red square for now)
        player_rect = pygame.Rect(screen_x, screen_y, 24 * self.zoom, 32 * self.zoom)
        pygame.draw.rect(self.screen, (255, 0, 0), player_rect)
        
        # Draw nickname
        font = pygame.font.Font(None, 12)
        text = font.render(player.nickname, True, (255, 255, 255))
        text_rect = text.get_rect(centerx=screen_x + 12 * self.zoom, bottom=screen_y - 2)
        self.screen.blit(text, text_rect)
        
    def _render_grid(self):
        """Render tile grid for debugging"""
        color = (100, 100, 100)
        
        # Vertical lines
        for x in range(0, self.width, int(self.tile_size * self.zoom)):
            pygame.draw.line(self.screen, color, (x, 0), (x, self.height))
            
        # Horizontal lines
        for y in range(0, self.height, int(self.tile_size * self.zoom)):
            pygame.draw.line(self.screen, color, (0, y), (self.width, y))
            
    def _render_level_links(self, level: Level):
        """Render level links for debugging"""
        if not level.links:
            return
            
        for link in level.links:
            # Calculate screen position
            screen_x = (link.x - self.camera_x) * self.tile_size * self.zoom
            screen_y = (link.y - self.camera_y) * self.tile_size * self.zoom
            width = link.width * self.tile_size * self.zoom
            height = link.height * self.tile_size * self.zoom
            
            # Draw semi-transparent yellow rectangle
            link_surface = pygame.Surface((width, height), pygame.SRCALPHA)
            link_surface.fill((255, 255, 0, 100))
            self.screen.blit(link_surface, (screen_x, screen_y))
            
    def _cache_level(self, level: Level):
        """Cache a level's rendered surface"""
        if not level or not level.tiles or not self.tileset:
            return
            
        # Create surface for entire level
        surface = pygame.Surface((level.width * 16, level.height * 16))
        surface.fill((0, 0, 0))
        
        # Render all tiles
        for y in range(level.height):
            for x in range(level.width):
                tile_id = level.tiles[y][x]
                if tile_id > 0:
                    tile = self._get_tile(tile_id)
                    if tile:
                        surface.blit(tile, (x * 16, y * 16))
                        
        self.level_surfaces[level.name] = surface
        
    def invalidate_cache(self, level_name: str):
        """Invalidate cached level surface"""
        if level_name in self.level_surfaces:
            del self.level_surfaces[level_name]
            
    def zoom_in(self):
        """Increase zoom level"""
        self.zoom = min(2.0, self.zoom * 1.25)
        
    def zoom_out(self):
        """Decrease zoom level"""
        self.zoom = max(0.5, self.zoom / 1.25)
        
    def toggle_grid(self):
        """Toggle grid display"""
        self.show_grid = not self.show_grid
        
    def toggle_links(self):
        """Toggle level link display"""
        self.show_links = not self.show_links