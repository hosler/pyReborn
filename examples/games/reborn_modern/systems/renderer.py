"""
Elegant Renderer
================

A single, clean renderer that handles everything: levels, GMAP, entities, and UI.
Consolidates 4 separate renderers (~2000 lines) into one elegant solution (~400 lines).

Features:
- Unified rendering for single levels and GMAP
- Automatic camera management
- Entity rendering (players, NPCs, items)
- Debug overlays
- Tileset caching for performance
"""

import pygame
import logging
from typing import Optional, Dict, Tuple, List
from pathlib import Path

logger = logging.getLogger(__name__)


class Renderer:
    """Single renderer for all game rendering needs"""
    
    def __init__(self, screen: pygame.Surface):
        """Initialize the renderer
        
        Args:
            screen: Pygame surface to render to
        """
        self.screen = screen
        self.width = screen.get_width()
        self.height = screen.get_height()
        
        # Camera (in tile coordinates)
        self.camera_x = 0.0
        self.camera_y = 0.0
        self.tile_size = 16
        
        # Tileset
        self.tileset = None
        self.tile_cache: Dict[int, pygame.Surface] = {}
        self._load_tileset()
        
        # Debug options
        self.show_grid = False
        self.show_links = True
        self.show_collision = False
        self.show_coords = False
        
        logger.info(f"ElegantRenderer initialized: {self.width}x{self.height}")
    
    def _load_tileset(self):
        """Load the tileset image"""
        # Try multiple possible locations
        search_paths = [
            Path(__file__).parent.parent / 'assets' / 'pics1.png',
            Path(__file__).parent.parent / 'assets' / 'tileset.png',
            Path(__file__).parent.parent / 'assets' / 'pics1.png',
        ]
        
        for path in search_paths:
            if path.exists():
                try:
                    self.tileset = pygame.image.load(str(path)).convert_alpha()
                    logger.info(f"Loaded tileset: {path.name}")
                    self._cache_common_tiles()
                    return
                except Exception as e:
                    logger.warning(f"Failed to load {path}: {e}")
        
        logger.warning("No tileset found - using colored rectangles")
    
    def _cache_common_tiles(self):
        """Pre-cache commonly used tiles for performance"""
        if not self.tileset:
            return
            
        # Cache first 256 tiles (most common)
        for tile_id in range(256):
            self._get_tile_surface(tile_id)
    
    def render(self, client) -> None:
        """Main render method - handles everything
        
        Args:
            client: Game client with level and entity data
        """
        # Clear screen
        self.screen.fill((0, 20, 0))  # Dark green background
        
        # Get current state from client
        level_mgr = getattr(client, 'level_manager', None)
        session_mgr = getattr(client, 'session_manager', None)
        
        if not level_mgr:
            return
            
        # Update camera to follow player
        if session_mgr:
            player = session_mgr.get_player()
            if player:
                self._update_camera(player.x, player.y)
        
        # Get current level
        level = level_mgr.get_current_level()
        if not level:
            return
        
        # Render tiles (handles both single level and GMAP)
        self._render_tiles(level, level_mgr)
        
        # Render links if enabled
        if self.show_links and hasattr(level, 'links'):
            self._render_links(level.links)
        
        # Render entities
        self._render_entities(client)
        
        # Render debug overlays
        if self.show_grid:
            self._render_grid()
        if self.show_coords:
            self._render_coordinates()
    
    def _update_camera(self, player_x: float, player_y: float):
        """Update camera to center on player
        
        Args:
            player_x: Player X position in tiles
            player_y: Player Y position in tiles
        """
        # Center camera on player
        screen_tiles_x = self.width / self.tile_size
        screen_tiles_y = self.height / self.tile_size
        
        self.camera_x = player_x - screen_tiles_x / 2
        self.camera_y = player_y - screen_tiles_y / 2
        
        # Clamp to level bounds (0-64 for standard levels)
        self.camera_x = max(0, min(64 - screen_tiles_x, self.camera_x))
        self.camera_y = max(0, min(64 - screen_tiles_y, self.camera_y))
    
    def _render_tiles(self, level, level_mgr):
        """Render level tiles (unified for single level and GMAP)
        
        Args:
            level: Current level object
            level_mgr: Level manager for GMAP data
        """
        # Calculate visible tile range
        start_x = max(0, int(self.camera_x))
        start_y = max(0, int(self.camera_y))
        end_x = min(64, int(self.camera_x + self.width / self.tile_size) + 1)
        end_y = min(64, int(self.camera_y + self.height / self.tile_size) + 1)
        
        # Render each visible tile
        for y in range(start_y, end_y):
            for x in range(start_x, end_x):
                # Get tile ID from level
                tile_id = self._get_tile_at(level, x, y)
                
                # Calculate screen position
                screen_x = (x - self.camera_x) * self.tile_size
                screen_y = (y - self.camera_y) * self.tile_size
                
                # Render tile
                if self.tileset and tile_id is not None:
                    tile_surface = self._get_tile_surface(tile_id)
                    if tile_surface:
                        self.screen.blit(tile_surface, (screen_x, screen_y))
                else:
                    # Fallback: colored rectangle based on tile type
                    color = self._get_tile_color(tile_id)
                    pygame.draw.rect(self.screen, color,
                                   (screen_x, screen_y, self.tile_size, self.tile_size))
    
    def _get_tile_at(self, level, x: int, y: int) -> int:
        """Get tile ID at position
        
        Args:
            level: Level object
            x: X position in tiles
            y: Y position in tiles
            
        Returns:
            Tile ID or 0
        """
        if not level:
            return 0
            
        # HACK: Access the cached board packet data directly if board_tiles is empty
        # This works around the issue where PLO_FILE overwrites PLO_BOARDPACKET data
        if hasattr(level, '_cached_board_packet'):
            tiles = level._cached_board_packet
            if tiles and len(tiles) > 0:
                if 0 <= x < 64 and 0 <= y < 64:
                    idx = y * 64 + x
                    if idx < len(tiles):
                        return tiles[idx]
        
        # Try different tile data formats
        if hasattr(level, 'board_tiles'):
            # Flat array format (new)
            if 0 <= x < 64 and 0 <= y < 64:
                idx = y * 64 + x
                if idx < len(level.board_tiles):
                    tile = level.board_tiles[idx]
                    # Handle case where tile might be a list
                    if isinstance(tile, list):
                        return tile[0] if tile else 0
                    return tile
        elif hasattr(level, 'tiles'):
            # 2D array format (compatibility)
            tiles = level.tiles
            if isinstance(tiles, list) and 0 <= y < len(tiles):
                if isinstance(tiles[y], list) and 0 <= x < len(tiles[y]):
                    return tiles[y][x]
        
        return 0  # Default tile
    
    def _get_tile_surface(self, tile_id: int) -> Optional[pygame.Surface]:
        """Get tile surface from tileset
        
        Args:
            tile_id: Tile ID
            
        Returns:
            Tile surface or None
        """
        if not self.tileset or tile_id < 0:
            return None
            
        # Check cache
        if tile_id in self.tile_cache:
            return self.tile_cache[tile_id]
        
        # Use Reborn's special tile mapping algorithm
        # This is NOT a simple row/column calculation!
        tileset_tx = (tile_id // 512) * 16 + (tile_id % 16)
        tileset_ty = (tile_id // 16) % 32
        tile_x = tileset_tx * 16  # Convert to pixels
        tile_y = tileset_ty * 16  # Convert to pixels
        
        # Extract tile if within bounds
        if (tile_x + 16 <= self.tileset.get_width() and 
            tile_y + 16 <= self.tileset.get_height()):
            tile = self.tileset.subsurface((tile_x, tile_y, 16, 16))
            self.tile_cache[tile_id] = tile
            return tile
            
        return None
    
    def _get_tile_color(self, tile_id: Optional[int]) -> Tuple[int, int, int]:
        """Get color for tile (fallback rendering)
        
        Args:
            tile_id: Tile ID
            
        Returns:
            RGB color tuple
        """
        if tile_id is None or tile_id == 0:
            return (34, 139, 34)  # Forest green (grass)
        elif tile_id < 512:
            return (139, 69, 19)  # Brown (dirt/path)
        elif tile_id < 1024:
            return (128, 128, 128)  # Gray (stone/wall)
        elif tile_id < 1536:
            return (0, 100, 200)  # Blue (water)
        else:
            return (50, 50, 50)  # Dark gray (special)
    
    def _render_links(self, links):
        """Render level links as semi-transparent overlays
        
        Args:
            links: List of level links
        """
        for link in links:
            # Calculate screen position
            screen_x = (link.x - self.camera_x) * self.tile_size
            screen_y = (link.y - self.camera_y) * self.tile_size
            width = link.width * self.tile_size
            height = link.height * self.tile_size
            
            # Skip if off-screen
            if (screen_x + width < 0 or screen_x > self.width or
                screen_y + height < 0 or screen_y > self.height):
                continue
            
            # Draw semi-transparent yellow rectangle
            s = pygame.Surface((width, height))
            s.set_alpha(64)
            s.fill((255, 255, 0))
            self.screen.blit(s, (screen_x, screen_y))
            
            # Draw border
            pygame.draw.rect(self.screen, (255, 255, 0),
                           (screen_x, screen_y, width, height), 1)
    
    def _render_entities(self, client):
        """Render all entities (players, NPCs, items)
        
        Args:
            client: Game client with entity data
        """
        session_mgr = getattr(client, 'session_manager', None)
        if not session_mgr:
            return
        
        # Render local player
        player = session_mgr.get_player()
        if player:
            self._render_player(player, is_local=True)
        
        # Render other players
        if hasattr(session_mgr, 'players'):
            for other_id, other_player in session_mgr.players.items():
                if other_player != player:
                    self._render_player(other_player, is_local=False)
        
        # Render NPCs
        npc_mgr = getattr(client, 'npc_manager', None)
        if npc_mgr and hasattr(npc_mgr, 'npcs'):
            for npc in npc_mgr.npcs.values():
                self._render_npc(npc)
    
    def _render_player(self, player, is_local: bool = False):
        """Render a player
        
        Args:
            player: Player object
            is_local: True if this is the local player
        """
        # Calculate screen position
        screen_x = (player.x - self.camera_x) * self.tile_size + 8
        screen_y = (player.y - self.camera_y) * self.tile_size + 8
        
        # Skip if off-screen
        if screen_x < -16 or screen_x > self.width + 16:
            return
        if screen_y < -16 or screen_y > self.height + 16:
            return
        
        # Draw player (for now just a colored circle)
        color = (255, 255, 0) if is_local else (0, 255, 0)
        pygame.draw.circle(self.screen, color, (int(screen_x), int(screen_y)), 6)
        
        # Draw player name
        if hasattr(player, 'nickname') and player.nickname:
            font = pygame.font.Font(None, 12)
            text = font.render(player.nickname, True, (255, 255, 255))
            text_rect = text.get_rect(center=(int(screen_x), int(screen_y) - 12))
            self.screen.blit(text, text_rect)
    
    def _render_npc(self, npc):
        """Render an NPC
        
        Args:
            npc: NPC object
        """
        if not hasattr(npc, 'x') or not hasattr(npc, 'y'):
            return
            
        # Calculate screen position
        screen_x = (npc.x - self.camera_x) * self.tile_size
        screen_y = (npc.y - self.camera_y) * self.tile_size
        
        # Skip if off-screen
        if screen_x < -16 or screen_x > self.width + 16:
            return
        if screen_y < -16 or screen_y > self.height + 16:
            return
        
        # Draw NPC as purple square
        pygame.draw.rect(self.screen, (128, 0, 128),
                       (screen_x, screen_y, 16, 16))
    
    def _render_grid(self):
        """Render tile grid overlay"""
        color = (50, 50, 50)
        
        # Vertical lines
        for x in range(0, self.width, self.tile_size):
            pygame.draw.line(self.screen, color, (x, 0), (x, self.height))
        
        # Horizontal lines
        for y in range(0, self.height, self.tile_size):
            pygame.draw.line(self.screen, color, (0, y), (self.width, y))
    
    def _render_coordinates(self):
        """Render coordinate overlay"""
        font = pygame.font.Font(None, 16)
        text = f"Camera: ({self.camera_x:.1f}, {self.camera_y:.1f})"
        surface = font.render(text, True, (255, 255, 255))
        self.screen.blit(surface, (5, 5))
    
    def toggle_grid(self):
        """Toggle grid display"""
        self.show_grid = not self.show_grid
        
    def toggle_links(self):
        """Toggle link display"""
        self.show_links = not self.show_links
        
    def toggle_coords(self):
        """Toggle coordinate display"""
        self.show_coords = not self.show_coords