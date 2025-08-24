"""
GMAP Renderer
=============

Handles rendering of multiple levels in GMAP mode.
"""

import pygame
import logging
import time
from typing import Optional, Dict, Tuple, Set

from pyreborn import Client
from .camera import Camera
from .level_renderer import LevelRenderer


logger = logging.getLogger(__name__)


class GMAPRenderer:
    """Renders multiple levels for GMAP view"""
    
    def __init__(self, screen: pygame.Surface, level_renderer: LevelRenderer):
        """Initialize GMAP renderer
        
        Args:
            screen: Pygame screen surface
            level_renderer: Level renderer instance for individual levels
        """
        self.screen = screen
        self.level_renderer = level_renderer
        
        # GMAP settings
        self.visible_range = 2  # Render levels within 2 segments of player
        self.minimap_enabled = False
        self.minimap_size = 200
        self.minimap_alpha = 180
        
        # Performance tracking
        self.levels_rendered = 0
        self.levels_in_view = 0
        
    def render(self, client: Client, camera: Camera):
        """Render GMAP view
        
        Args:
            client: PyReborn client instance
            camera: Camera for viewport transformation
        """
        if not client or not client.level_manager:
            return
            
        # Get current GMAP info
        gmap_name = client.get_current_gmap_name()
        if not gmap_name:
            logger.warning("No current GMAP name")
            return
            
        # Get player position using coordinate manager
        position = client.get_player_render_position()
        if not position:
            logger.warning("No player position available")
            return
            
        player_world_x, player_world_y = position
        
        # Calculate current segment from world position
        current_col = int(player_world_x // 64)
        current_row = int(player_world_y // 64)
        
        # Get GMAP data
        gmap_data = self._get_gmap_data(client, gmap_name)
        if not gmap_data:
            logger.warning(f"No GMAP data for {gmap_name}")
            # Try alternate method - get from level manager's internal data
            if hasattr(client.level_manager, '_gmap_data'):
                gmap_data = client.level_manager._gmap_data.get(gmap_name)
                if gmap_data:
                    logger.info(f"Found GMAP data in _gmap_data: {gmap_name}")
            if not gmap_data:
                return
            
        # Debug log GMAP data
        if not hasattr(self, '_gmap_logged'):
            logger.info(f"GMAP data keys: {list(gmap_data.keys()) if isinstance(gmap_data, dict) else 'Not a dict'}")
            if isinstance(gmap_data, dict):
                logger.info(f"GMAP dimensions: {gmap_data.get('width', '?')}x{gmap_data.get('height', '?')}")
                levels = gmap_data.get('levels', [])
                logger.info(f"GMAP levels count: {len(levels)}")
                if levels:
                    logger.info(f"First few levels: {levels[:5]}")
            
            # Debug what levels are actually loaded
            if client.level_manager:
                if hasattr(client.level_manager, 'levels'):
                    loaded_levels = list(client.level_manager.levels.keys())
                    logger.info(f"Loaded levels in manager: {loaded_levels}")
                if hasattr(client.level_manager, '_levels'):
                    loaded_levels = list(client.level_manager._levels.keys())
                    logger.info(f"Loaded levels in _levels: {loaded_levels}")
            self._gmap_logged = True
            
        # Render visible levels
        self._render_visible_levels(client, gmap_data, current_col, current_row, 
                                   player_world_x, player_world_y, camera)
        
        # Render minimap if enabled
        if self.minimap_enabled:
            self._render_minimap(gmap_data, current_col, current_row)
            
    def _get_gmap_data(self, client: Client, gmap_name: str) -> Optional[dict]:
        """Get GMAP data from client
        
        Args:
            client: PyReborn client
            gmap_name: GMAP file name
            
        Returns:
            GMAP data dictionary or None
        """
        # Try to get from GMAP manager
        if hasattr(client, 'gmap_manager') and client.gmap_manager:
            return client.gmap_manager.get_gmap_data(gmap_name)
            
        # Try to get from level manager
        if hasattr(client.level_manager, 'get_gmap_data'):
            return client.level_manager.get_gmap_data(gmap_name)
            
        return None
        
    def _render_visible_levels(self, client: Client, gmap_data: dict,
                              current_col: int, current_row: int,
                              player_world_x: float, player_world_y: float,
                              camera: Camera):
        """Render levels visible in viewport
        
        Args:
            client: PyReborn client
            gmap_data: GMAP data dictionary
            current_col: Player's current column
            current_row: Player's current row
            player_world_x: Player's world X position
            player_world_y: Player's world Y position
            camera: Camera instance
        """
        # Get GMAP dimensions
        gmap_width = gmap_data.get('width', 0)
        gmap_height = gmap_data.get('height', 0)
        
        if gmap_width == 0 or gmap_height == 0:
            logger.error("Invalid GMAP dimensions")
            return
            
        # Get visible bounds from camera
        left, top, right, bottom = camera.get_visible_bounds()
        
        # Calculate which segments are visible
        min_col = max(0, int(left // 64) - 1)
        max_col = min(gmap_width - 1, int(right // 64) + 1)
        min_row = max(0, int(top // 64) - 1)
        max_row = min(gmap_height - 1, int(bottom // 64) + 1)
        
        # Reset counters
        self.levels_rendered = 0
        self.levels_in_view = 0
        
        # Get tile size from camera
        tile_size = camera.get_tile_size()
        
        # Debug log render bounds
        if not hasattr(self, '_bounds_logged') or time.time() - getattr(self, '_bounds_logged', 0) > 5:
            logger.info(f"Rendering bounds: cols {min_col}-{max_col}, rows {min_row}-{max_row}")
            logger.info(f"Camera bounds: ({left:.1f}, {top:.1f}) to ({right:.1f}, {bottom:.1f})")
            logger.info(f"Player at segment ({current_col}, {current_row})")
            self._bounds_logged = time.time()
        
        # Render each visible segment
        for row in range(min_row, max_row + 1):
            for col in range(min_col, max_col + 1):
                # Get level name for this segment
                level_name_with_ext = self._get_level_at_segment(gmap_data, col, row)
                if not level_name_with_ext:
                    continue
                    
                # Strip .nw extension for cache lookup (level manager stores without extension)
                level_name = level_name_with_ext[:-3] if level_name_with_ext.endswith('.nw') else level_name_with_ext
                    
                self.levels_in_view += 1
                
                # Calculate world position of this level
                level_world_x = col * 64
                level_world_y = row * 64
                
                # Convert to screen position
                screen_x, screen_y = camera.world_to_screen(level_world_x, level_world_y)
                
                # Skip if completely off screen
                level_size = 64 * tile_size
                if (screen_x + level_size < 0 or screen_x > self.screen.get_width() or
                    screen_y + level_size < 0 or screen_y > self.screen.get_height()):
                    continue
                
                # Get level from level manager
                level = None
                if client.level_manager:
                    # Try different ways to get the level
                    if hasattr(client.level_manager, 'get_level'):
                        level = client.level_manager.get_level(level_name)
                    
                    # If not found, try the _level_cache directly
                    if not level and hasattr(client.level_manager, '_level_cache'):
                        level = client.level_manager._level_cache.get(level_name)
                        if level:
                            logger.debug(f"Found {level_name} in _level_cache")
                        
                        # Also try with .nw extension (current level is stored with extension)
                        if not level:
                            level = client.level_manager._level_cache.get(level_name_with_ext)
                    
                    # If not found, try the levels dict directly (backward compatibility)
                    if not level and hasattr(client.level_manager, 'levels'):
                        level = client.level_manager.levels.get(level_name)
                        if level:
                            logger.debug(f"Found {level_name} in levels dict")
                    
                    # Special case: if this is the current level, get it directly
                    if not level and hasattr(client.level_manager, 'get_current_level'):
                        current = client.level_manager.get_current_level()
                        if current and current.name == level_name:
                            level = current
                            logger.debug(f"Using current level for {level_name}")
                        # Also try if current level name with .nw extension matches
                        elif current and f"{current.name}.nw" == level_name_with_ext:
                            level = current
                
                # Debug log what we're trying to render (every 5 seconds or when level status changes)
                debug_key = f"_level_debug_{level_name}"
                last_debug = getattr(self, debug_key, 0)
                current_time = time.time()
                level_has_tiles = level and hasattr(level, 'board_tiles') and level.board_tiles and sum(1 for t in level.board_tiles if t > 0) > 0
                
                if current_time - last_debug > 10 or not hasattr(self, debug_key):
                    logger.info(f"🗺️ GMAP Level {level_name_with_ext} -> {level_name}:")
                    logger.info(f"  • Level loaded: {level is not None}")
                    logger.info(f"  • Screen position: ({screen_x}, {screen_y})")
                    if level:
                        board_tiles_count = len(level.board_tiles) if hasattr(level, 'board_tiles') and level.board_tiles else 0
                        non_zero_tiles = sum(1 for t in level.board_tiles if t > 0) if hasattr(level, 'board_tiles') and level.board_tiles else 0
                        logger.info(f"  • Board tiles: {board_tiles_count} total, {non_zero_tiles} non-zero")
                        logger.info(f"  • Renderable: {level_has_tiles}")
                    else:
                        # Debug available levels in cache
                        if hasattr(client.level_manager, '_level_cache'):
                            cached_levels = list(client.level_manager._level_cache.keys())[:5]  # First 5
                            logger.info(f"  • Available in cache: {cached_levels}")
                    setattr(self, debug_key, current_time)
                
                # Render level
                if self.level_renderer.render_at_position(level, screen_x, screen_y, tile_size):
                    self.levels_rendered += 1
                    
                # Highlight current segment
                if col == current_col and row == current_row:
                    self._highlight_current_segment(screen_x, screen_y, level_size)
                    
    def _get_level_at_segment(self, gmap_data: dict, col: int, row: int) -> Optional[str]:
        """Get level name at specific segment
        
        Args:
            gmap_data: GMAP data
            col: Column
            row: Row
            
        Returns:
            Level name or None
        """
        # Check if we have levels array
        levels = gmap_data.get('levels', [])
        if not levels:
            return None
            
        # Calculate index
        width = gmap_data.get('width', 0)
        if width == 0:
            return None
            
        index = row * width + col
        
        # Check bounds
        if index < 0 or index >= len(levels):
            return None
            
        return levels[index]
        
    def _highlight_current_segment(self, x: int, y: int, size: int):
        """Highlight the current segment
        
        Args:
            x: Screen X position
            y: Screen Y position
            size: Segment size in pixels
        """
        # Draw subtle highlight border
        pygame.draw.rect(self.screen, (255, 255, 100), (x - 2, y - 2, size + 4, size + 4), 3)
        
    def _render_minimap(self, gmap_data: dict, current_col: int, current_row: int):
        """Render GMAP minimap
        
        Args:
            gmap_data: GMAP data
            current_col: Current column
            current_row: Current row
        """
        # Get GMAP dimensions
        width = gmap_data.get('width', 0)
        height = gmap_data.get('height', 0)
        
        if width == 0 or height == 0:
            return
            
        # Calculate minimap position (top-right corner)
        minimap_x = self.screen.get_width() - self.minimap_size - 10
        minimap_y = 10
        
        # Create minimap surface
        minimap = pygame.Surface((self.minimap_size, self.minimap_size))
        minimap.set_alpha(self.minimap_alpha)
        minimap.fill((20, 20, 40))
        
        # Calculate cell size
        cell_width = self.minimap_size // width
        cell_height = self.minimap_size // height
        cell_size = min(cell_width, cell_height)
        
        # Center the minimap grid
        grid_width = width * cell_size
        grid_height = height * cell_size
        offset_x = (self.minimap_size - grid_width) // 2
        offset_y = (self.minimap_size - grid_height) // 2
        
        # Draw grid
        for row in range(height):
            for col in range(width):
                x = offset_x + col * cell_size
                y = offset_y + row * cell_size
                
                # Get level info
                level_name = self._get_level_at_segment(gmap_data, col, row)
                
                # Choose color
                if col == current_col and row == current_row:
                    color = (255, 255, 100)  # Yellow for current
                elif level_name:
                    color = (100, 100, 200)  # Blue for valid level
                else:
                    color = (40, 40, 40)     # Dark for empty
                    
                # Draw cell
                pygame.draw.rect(minimap, color, (x, y, cell_size - 1, cell_size - 1))
                
        # Draw border
        pygame.draw.rect(minimap, (200, 200, 200), minimap.get_rect(), 2)
        
        # Blit to screen
        self.screen.blit(minimap, (minimap_x, minimap_y))
        
    def toggle_minimap(self):
        """Toggle minimap visibility"""
        self.minimap_enabled = not self.minimap_enabled
        logger.info(f"Minimap: {'enabled' if self.minimap_enabled else 'disabled'}")
        
    def get_render_stats(self) -> dict:
        """Get rendering statistics"""
        return {
            'levels_in_view': self.levels_in_view,
            'levels_rendered': self.levels_rendered,
            'minimap_enabled': self.minimap_enabled
        }