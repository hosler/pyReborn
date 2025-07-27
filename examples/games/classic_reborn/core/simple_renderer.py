#!/usr/bin/env python3
"""
Simple, clean GMAP renderer for Classic Reborn

This replaces the complex renderer.py with a clean, PyReborn-focused approach.
No legacy compatibility, no complex parameter passing, just simple rendering.
"""

import pygame
import logging
import time
from typing import Optional, Dict, List, Tuple

logger = logging.getLogger(__name__)

# Colors
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GRAY = (128, 128, 128)
BLUE = (100, 150, 255)
GREEN = (100, 255, 100)
RED = (255, 100, 100)
YELLOW = (255, 255, 100)

class SimpleGMAPRenderer:
    """Clean, simple GMAP renderer that only uses PyReborn data"""
    
    def __init__(self, screen: pygame.Surface, tileset: Optional[pygame.Surface] = None):
        self.screen = screen
        self.tileset = tileset
        self.screen_width = screen.get_width()
        self.screen_height = screen.get_height()
        
        # Fonts
        pygame.font.init()
        self.font_small = pygame.font.Font(None, 16)
        self.font_medium = pygame.font.Font(None, 24)
        
        # Simple state
        self.zoom_level = 1.0  # 1.0 = normal, 0.1 = bird's eye
        
        # Game state reference (set by game client)
        self.game_state = None
        
    def render_gmap(self, client, current_level_name: str, player_x: float, player_y: float):
        """
        Render the GMAP with current zoom level
        
        Args:
            client: PyReborn client with level_manager
            current_level_name: Name of current level (e.g., "chicken1.nw")  
            player_x: Player X position in current level
            player_y: Player Y position in current level
        """
        self.screen.fill(BLACK)
        
        # Get GMAP data from PyReborn
        if not client or not hasattr(client, 'level_manager'):
            self._draw_error("No PyReborn client")
            return
            
        # First check if we have GMAP data and if current level is in it
        gmap_data = client.level_manager.gmap_data
        is_in_gmap = False
        gmap_parser = None
        current_col = current_row = -1
        
        if gmap_data:
            # Check each GMAP to see if current level is in it
            for gmap_name, parser in gmap_data.items():
                for row in range(parser.height):
                    for col in range(parser.width):
                        segment_name = parser.get_segment_at(col, row)
                        if segment_name == current_level_name:
                            is_in_gmap = True
                            gmap_parser = parser
                            current_col, current_row = col, row
                            break
                    if is_in_gmap:
                        break
                if is_in_gmap:
                    break
        
        # If not in GMAP, render as single level
        if not is_in_gmap:
            self._draw_single_level(client, current_level_name)
            return
            
        # We're in GMAP mode - continue with GMAP rendering
        if not gmap_parser:
            self._draw_error("GMAP data error")
            return
            
        # Debug logging removed - too spammy
            
        # Unified rendering - just scale based on zoom
        self._render_unified_view(client, gmap_parser, current_col, current_row, player_x, player_y)
    
    def _render_unified_view(self, client, gmap_parser, current_col: int, current_row: int, 
                           player_x: float, player_y: float):
        """Render the game world with zoom support"""
        # Calculate tile size based on zoom
        base_tile_size = 16
        tile_size = int(base_tile_size * self.zoom_level)
        if tile_size < 1:
            tile_size = 1
            
        # Calculate how many tiles we can show on screen
        tiles_visible_x = self.screen_width // tile_size if tile_size > 0 else 64
        tiles_visible_y = self.screen_height // tile_size if tile_size > 0 else 64
        
        # Get player's world coordinates (x2/y2) from PyReborn
        # These are already in absolute GMAP coordinates
        local_player = None
        if hasattr(client, 'local_player'):
            local_player = client.local_player
        elif hasattr(client, 'player_manager') and hasattr(client.player_manager, 'local_player'):
            local_player = client.player_manager.local_player
            
        if local_player and hasattr(local_player, 'x2') and hasattr(local_player, 'y2') and local_player.x2 is not None and local_player.y2 is not None:
            # Use high-precision world coordinates if available
            player_abs_x = local_player.x2
            player_abs_y = local_player.y2
        else:
            # Fallback: Calculate from segment position + local coordinates
            player_abs_x = current_col * 64 + player_x
            player_abs_y = current_row * 64 + player_y
        
        # Calculate camera center (player position in pixels)
        camera_center_x = player_abs_x * tile_size
        camera_center_y = player_abs_y * tile_size
        
        # Calculate camera offset to center player on screen
        camera_offset_x = camera_center_x - self.screen_width // 2
        camera_offset_y = camera_center_y - self.screen_height // 2
        
        # Clear screen
        self.screen.fill(BLACK)
        
        # Calculate which segments to render based on visible area
        # Start from player's absolute position and work outward
        player_tile_x = int(player_abs_x)
        player_tile_y = int(player_abs_y)
        
        # Calculate visible tile range
        start_tile_x = max(0, player_tile_x - tiles_visible_x // 2 - 1)
        end_tile_x = min(gmap_parser.width * 64, player_tile_x + tiles_visible_x // 2 + 1)
        start_tile_y = max(0, player_tile_y - tiles_visible_y // 2 - 1)
        end_tile_y = min(gmap_parser.height * 64, player_tile_y + tiles_visible_y // 2 + 1)
        
        # Render all visible segments
        for row in range(gmap_parser.height):
            for col in range(gmap_parser.width):
                # Calculate segment bounds
                seg_start_x = col * 64
                seg_end_x = (col + 1) * 64
                seg_start_y = row * 64
                seg_end_y = (row + 1) * 64
                
                # Check if segment is visible
                if (seg_end_x >= start_tile_x and seg_start_x <= end_tile_x and
                    seg_end_y >= start_tile_y and seg_start_y <= end_tile_y):
                    
                    segment_name = gmap_parser.get_segment_at(col, row)
                    if segment_name and segment_name in client.level_manager.levels:
                        # Calculate screen position for this segment
                        screen_x = seg_start_x * tile_size - camera_offset_x
                        screen_y = seg_start_y * tile_size - camera_offset_y
                        
                        # Render the segment
                        self._render_level_at(client, segment_name, screen_x, screen_y, tile_size)
                        
                        # Draw border for current segment
                        if col == current_col and row == current_row:
                            pygame.draw.rect(self.screen, YELLOW, 
                                           (screen_x, screen_y, 64 * tile_size, 64 * tile_size), 2)
        
        # Draw all players (other players first, then local player on top)
        self._draw_all_players(client, camera_offset_x, camera_offset_y, tile_size)
        
        # Draw local player at center (on top of other players)
        player_screen_x = player_abs_x * tile_size - camera_offset_x
        player_screen_y = player_abs_y * tile_size - camera_offset_y
        
        # Scale player size based on zoom
        player_size = max(4, int(16 * self.zoom_level))
        if player_size >= 4:
            pygame.draw.circle(self.screen, RED, 
                             (int(player_screen_x), int(player_screen_y)), 
                             player_size // 2)
        else:
            # Just draw a dot for very zoomed out
            self.screen.set_at((int(player_screen_x), int(player_screen_y)), RED)
        
        # Draw zoom indicator
        zoom_text = self.font_medium.render(f"Zoom: {self.zoom_level:.1f}x", True, WHITE)
        self.screen.blit(zoom_text, (10, 10))
            
    def _render_normal_view(self, client, gmap_parser, current_col: int, current_row: int, 
                          player_x: float, player_y: float):
        """Render normal close-up view"""
        # Adjust tile size based on GMAP size to show more levels
        # For 10x10 GMAP, use smaller tiles to see more of the world
        if gmap_parser.width >= 8:  # Large GMAP
            tile_size = 8  # Smaller tiles to see more levels
        else:  # Small GMAP (like 3x3)
            tile_size = 16  # Larger tiles for detail
        
        # Debug: Normal view tile size and screen dimensions
        
        # Calculate camera offset (apply to all levels for consistent alignment)
        camera_offset_x = int(player_x * tile_size)
        camera_offset_y = int(player_y * tile_size)
        
        # Show ALL levels in the GMAP
        for level_row in range(gmap_parser.height):
            for level_col in range(gmap_parser.width):
                    
                # Get segment name
                segment_name = gmap_parser.get_segment_at(level_col, level_row)
                if not segment_name:
                    continue
                    
                # Position levels with NO gaps - each level is exactly 64*tile_size pixels
                level_pixel_size = 64 * tile_size
                
                # Calculate position relative to current player's level
                col_offset = level_col - current_col
                row_offset = level_row - current_row
                
                # Center the view on the player's current level
                center_x = self.screen_width // 2
                center_y = self.screen_height // 2
                
                # Position relative to center with NO spacing between levels
                screen_x = center_x + col_offset * level_pixel_size - camera_offset_x
                screen_y = center_y + row_offset * level_pixel_size - camera_offset_y
                
                is_current = (level_col == current_col and level_row == current_row)
                is_loaded = segment_name in client.level_manager.levels
                
                # Only print debug for first few levels to avoid spam
                # Debug: Track level type and position (disabled)
                # if level_row < 2 and level_col < 3:
                #     level_type = "Current" if is_current else ("Loaded" if is_loaded else "Unloaded")
                
                # Always render something for each GMAP position (loaded level or placeholder)
                self._render_level_at(client, segment_name, screen_x, screen_y, tile_size)
                
        # Draw player
        center_x = self.screen_width // 2
        center_y = self.screen_height // 2
        pygame.draw.circle(self.screen, YELLOW, (center_x, center_y), 4)
        
    def _render_birds_eye_view(self, client, gmap_parser, current_col: int, current_row: int, gmap_name: str):
        """Render bird's eye overview of entire GMAP"""
        
        # Calculate cell size to fit GMAP on screen
        margin = 50
        available_width = self.screen_width - 2 * margin
        available_height = self.screen_height - 2 * margin - 100  # Space for title
        
        cell_width = available_width // gmap_parser.width
        cell_height = available_height // gmap_parser.height
        cell_size = min(cell_width, cell_height, 200)  # Max 200px per cell
        
        # Calculate grid position to center it
        total_width = gmap_parser.width * cell_size
        total_height = gmap_parser.height * cell_size
        grid_x = (self.screen_width - total_width) // 2
        grid_y = (self.screen_height - total_height) // 2 + 50  # Leave space for title
        
        # Draw title
        title = f"GMAP: {gmap_name} ({gmap_parser.width}x{gmap_parser.height})"
        title_surface = self.font_medium.render(title, True, WHITE)
        title_rect = title_surface.get_rect(center=(self.screen_width // 2, 25))
        self.screen.blit(title_surface, title_rect)
        
        # Draw grid
        for row in range(gmap_parser.height):
            for col in range(gmap_parser.width):
                x = grid_x + col * cell_size
                y = grid_y + row * cell_size
                
                # Get segment info
                segment_name = gmap_parser.get_segment_at(col, row)
                is_current = (col == current_col and row == current_row)
                is_loaded = segment_name and segment_name in client.level_manager.levels
                
                # Debug: Bird's eye view grid (disabled)
                # if not hasattr(self, '_birds_eye_debug'):
                #     self._birds_eye_debug = True
                
                # Choose colors
                if is_current:
                    bg_color = YELLOW
                    border_color = RED
                    border_width = 3
                elif is_loaded:
                    bg_color = GREEN  
                    border_color = WHITE
                    border_width = 2
                elif segment_name:
                    bg_color = BLUE
                    border_color = GRAY
                    border_width = 1
                else:
                    bg_color = BLACK
                    border_color = GRAY
                    border_width = 1
                
                # Draw cell
                pygame.draw.rect(self.screen, bg_color, (x, y, cell_size, cell_size))
                pygame.draw.rect(self.screen, border_color, (x, y, cell_size, cell_size), border_width)
                
                # Draw level miniature if loaded and cell is big enough
                if is_loaded and cell_size >= 32:
                    miniature_size = cell_size - 4
                    level = client.level_manager.levels[segment_name]
                    
                    # Debug: Level content (disabled)
                    # if row < 2 and col < 3 and hasattr(level, 'board_tiles_64x64') and level.board_tiles_64x64:
                    #     sample_tiles = level.board_tiles_64x64[:10]
                    #     unique_tiles = len(set(tile_id for tile_id in level.board_tiles_64x64 if tile_id != 0))
                    
                    miniature = self._create_level_miniature(level, miniature_size)
                    if miniature:
                        self.screen.blit(miniature, (x + 2, y + 2))
                
                # Draw coordinates if cell is big enough
                if cell_size >= 24:
                    coord_text = f"{chr(ord('a')+col)}{row}"
                    coord_surface = self.font_small.render(coord_text, True, BLACK if bg_color != BLACK else WHITE)
                    self.screen.blit(coord_surface, (x + 2, y + 2))
        
        # Draw status info
        loaded_count = sum(1 for name in gmap_parser.segments if name in client.level_manager.levels)
        total_count = len(gmap_parser.segments)
        status = f"Loaded: {loaded_count}/{total_count} levels | Cell size: {cell_size}px"
        status_surface = self.font_small.render(status, True, WHITE)
        status_rect = status_surface.get_rect(center=(self.screen_width // 2, self.screen_height - 25))
        self.screen.blit(status_surface, status_rect)
        
    def _render_level_at(self, client, level_name: str, screen_x: int, screen_y: int, tile_size: int):
        """Render a single level at screen position"""
        if level_name not in client.level_manager.levels:
            # Draw placeholder for unloaded level
            level_width = level_height = 64 * tile_size
            
            # Different colors for different types of unloaded levels
            if "chicken" in level_name:
                color = (60, 100, 60)  # Green tint for chicken levels
            else:
                color = (60, 60, 100)  # Blue tint for other levels
                
            pygame.draw.rect(self.screen, color, (screen_x, screen_y, level_width, level_height))
            pygame.draw.rect(self.screen, (100, 100, 100), (screen_x, screen_y, level_width, level_height), 2)  # Border
            
            # Draw level name if space allows
            if tile_size >= 4:
                name_surface = self.font_small.render(level_name, True, WHITE)
                self.screen.blit(name_surface, (screen_x + 5, screen_y + 5))
            return
            
        level = client.level_manager.levels[level_name]
        
        # Debug level data
        # Debug: Level data validation (disabled)
        # if not hasattr(self, '_level_debug_printed'):
        #     self._level_debug_printed = True
        
        # Render level tiles
        if hasattr(level, 'board_tiles_64x64') and level.board_tiles_64x64:
            self._render_level_tiles(level, screen_x, screen_y, tile_size)
        else:
            # No tile data - draw placeholder
            level_width = level_height = 64 * tile_size
            pygame.draw.rect(self.screen, (60, 60, 60), (screen_x, screen_y, level_width, level_height))
            
    def _render_level_tiles(self, level, screen_x: int, screen_y: int, tile_size: int):
        """Render level tiles from board data"""
        
        # Debug: Tileset status (disabled)
        # if not hasattr(self, '_tileset_debug_printed'):
        #     self._tileset_debug_printed = True
        
        if not self.tileset:
            # No tileset - draw colored rectangles based on tile ID
            for ty in range(64):
                for tx in range(64):
                    tile_id = level.get_board_tile_id(tx, ty)
                        
                    # Generate color from tile ID
                    color = self._tile_id_to_color(tile_id)
                    
                    x = screen_x + tx * tile_size
                    y = screen_y + ty * tile_size
                    
                    if tile_size >= 2:
                        pygame.draw.rect(self.screen, color, (x, y, tile_size, tile_size))
                    else:
                        self.screen.set_at((x, y), color)
        else:
            # Render using tileset
            for ty in range(64):
                for tx in range(64):
                    tile_id = level.get_board_tile_id(tx, ty)
                    
                    # Check if tile_id is actually an int
                    if not isinstance(tile_id, int):
                        print(f"ERROR: tile_id is not int! Type: {type(tile_id)}, Value: {tile_id}")
                        continue
                        
                    # Calculate tileset coordinates using Graal's tile mapping algorithm
                    # This matches the server's tile ID to tileset position mapping
                    tileset_tx = (tile_id // 512) * 16 + (tile_id % 16)
                    tileset_ty = (tile_id // 16) % 32
                    tileset_x = tileset_tx * 16
                    tileset_y = tileset_ty * 16
                    
                    # Screen position
                    x = screen_x + tx * tile_size
                    y = screen_y + ty * tile_size
                    
                    # Only render if on screen and tile_size is reasonable
                    if (x + tile_size > 0 and x < self.screen_width and 
                        y + tile_size > 0 and y < self.screen_height and
                        tile_size >= 1):
                        
                        try:
                            # Extract tile from tileset
                            tile_rect = pygame.Rect(tileset_x, tileset_y, 16, 16)
                            if (tileset_x + 16 <= self.tileset.get_width() and 
                                tileset_y + 16 <= self.tileset.get_height()):
                                
                                tile_surface = self.tileset.subsurface(tile_rect)
                                
                                # Scale if needed
                                if tile_size != 16:
                                    tile_surface = pygame.transform.scale(tile_surface, (tile_size, tile_size))
                                
                                self.screen.blit(tile_surface, (x, y))
                                
                        except (pygame.error, ValueError):
                            # Fallback to colored rectangle if tileset access fails
                            color = self._tile_id_to_color(tile_id)
                            if tile_size >= 2:
                                pygame.draw.rect(self.screen, color, (x, y, tile_size, tile_size))
                            else:
                                self.screen.set_at((x, y), color)
            
    def _create_level_miniature(self, level, size: int) -> Optional[pygame.Surface]:
        """Create a miniature representation of a level"""
        if not hasattr(level, 'board_tiles_64x64') or not level.board_tiles_64x64:
            return None
            
        miniature = pygame.Surface((size, size))
        miniature.fill(BLACK)
        
        # Sample tiles to create miniature
        sample_rate = max(1, 64 // size)  # How many tiles per miniature pixel
        
        if self.tileset:
            # Use tileset for miniature
            for my in range(size):
                for mx in range(size):
                    # Sample from level
                    tx = (mx * sample_rate) % 64
                    ty = (my * sample_rate) % 64
                    
                    tile_id = level.get_board_tile_id(tx, ty)
                    if tile_id != 0:
                        # Calculate tileset coordinates using Graal's tile mapping algorithm
                        tileset_tx = (tile_id // 512) * 16 + (tile_id % 16)
                        tileset_ty = (tile_id // 16) % 32
                        tileset_x = tileset_tx * 16
                        tileset_y = tileset_ty * 16
                        
                        try:
                            # Extract single pixel from center of tile
                            if (tileset_x + 8 < self.tileset.get_width() and 
                                tileset_y + 8 < self.tileset.get_height()):
                                color = self.tileset.get_at((tileset_x + 8, tileset_y + 8))
                                miniature.set_at((mx, my), color)
                        except (pygame.error, ValueError):
                            # Fallback to generated color
                            color = self._tile_id_to_color(tile_id)
                            miniature.set_at((mx, my), color)
        else:
            # Fallback to colored pixels
            for my in range(size):
                for mx in range(size):
                    # Sample from level
                    tx = (mx * sample_rate) % 64
                    ty = (my * sample_rate) % 64
                    
                    tile_id = level.get_board_tile_id(tx, ty)
                    if tile_id != 0:
                        color = self._tile_id_to_color(tile_id)
                        miniature.set_at((mx, my), color)
                    
        return miniature
        
    def _tile_id_to_color(self, tile_id: int) -> Tuple[int, int, int]:
        """Convert tile ID to a representative color"""
        # Generate consistent color from tile ID
        r = (tile_id * 123) % 256
        g = (tile_id * 456) % 256  
        b = (tile_id * 789) % 256
        
        # Ensure it's not too dark
        if r + g + b < 150:
            r = min(255, r + 100)
            g = min(255, g + 100)
            b = min(255, b + 100)
            
        return (r, g, b)
    
    def _draw_all_players(self, client, camera_offset_x: float, camera_offset_y: float, tile_size: int):
        """Draw all connected players"""
        # First try to use game state players (preferred)
        if self.game_state and hasattr(self.game_state, 'players'):
            players_dict = self.game_state.players
            local_player_id = self.game_state.local_player_id if hasattr(self.game_state, 'local_player_id') else None
        # Fallback to PyReborn client players
        elif client and hasattr(client, 'players'):
            players_dict = client.players
            local_player_id = client.local_player.id if hasattr(client, 'local_player') and client.local_player else None
        else:
            return
            
        # Debug: log player count periodically
        if not hasattr(self, '_last_player_debug') or time.time() - self._last_player_debug > 5:
            player_count = len(players_dict)
            logger.info(f"[RENDERER] Drawing {player_count} players (local ID: {local_player_id})")
            for pid, p in players_dict.items():
                    x_str = f"{p.x:.1f}" if hasattr(p, 'x') and p.x is not None else "None"
                    y_str = f"{p.y:.1f}" if hasattr(p, 'y') and p.y is not None else "None"
                    x2_str = f"{p.x2:.1f}" if hasattr(p, 'x2') and p.x2 is not None else "None"
                    y2_str = f"{p.y2:.1f}" if hasattr(p, 'y2') and p.y2 is not None else "None"
                    gx = p.gmaplevelx if hasattr(p, 'gmaplevelx') else "?"
                    gy = p.gmaplevely if hasattr(p, 'gmaplevely') else "?"
                    logger.info(f"  Player {pid}: {p.nickname if hasattr(p, 'nickname') else 'Unknown'} - local:({x_str},{y_str}) world:({x2_str},{y2_str}) gmap:[{gx},{gy}]")
            self._last_player_debug = time.time()
            
        # Draw each player
        for player_id, player in players_dict.items():
            # Skip local player (drawn separately)
            if player_id == local_player_id:
                continue
                
            # Skip players without position
            if not hasattr(player, 'x') or not hasattr(player, 'y') or player.x is None or player.y is None:
                logger.debug(f"Skipping player {player_id} - no valid position")
                continue
                
            # Get player position
            # Check for world coordinates (x2/y2) first
            if hasattr(player, 'x2') and hasattr(player, 'y2') and player.x2 is not None and player.y2 is not None:
                # Player has world coordinates - use them directly
                player_abs_x = player.x2
                player_abs_y = player.y2
                
                # Debug log
                if not hasattr(self, '_logged_x2_usage') or time.time() - self._logged_x2_usage > 5:
                    logger.info(f"[RENDERER] Using x2/y2 for player {player_id}: x2={player.x2:.1f}, y2={player.y2:.1f}")
                    self._logged_x2_usage = time.time()
            elif (hasattr(player, 'gmaplevelx') and hasattr(player, 'gmaplevely') and 
                  player.gmaplevelx is not None and player.gmaplevely is not None):
                # Player is in GMAP - calculate world position from segment + local
                player_abs_x = player.gmaplevelx * 64 + player.x
                player_abs_y = player.gmaplevely * 64 + player.y
            else:
                # No GMAP info - just use local coordinates
                # This might place them incorrectly in GMAP view, but at least shows them
                player_abs_x = player.x
                player_abs_y = player.y
                
            # Calculate screen position
            screen_x = player_abs_x * tile_size - camera_offset_x
            screen_y = player_abs_y * tile_size - camera_offset_y
            
            # Check if player is on screen
            player_size = max(4, int(16 * self.zoom_level))
            if (screen_x + player_size > 0 and screen_x - player_size < self.screen_width and
                screen_y + player_size > 0 and screen_y - player_size < self.screen_height):
                
                # Draw player circle (different color than local player)
                if player_size >= 4:
                    # Choose color based on player state
                    color = GREEN  # Default color for other players
                    
                    # Draw player
                    pygame.draw.circle(self.screen, color,
                                     (int(screen_x), int(screen_y)),
                                     player_size // 2)
                    
                    # Always log first player drawn, then periodically
                    if not hasattr(self, '_drawn_any_player') or (not hasattr(self, '_drawn_players_log') or time.time() - self._drawn_players_log > 5):
                        logger.info(f"[RENDERER] Drew player {player_id} ({player.nickname if hasattr(player, 'nickname') else 'Unknown'}) at screen pos ({int(screen_x)}, {int(screen_y)}) from world pos ({player_abs_x:.1f}, {player_abs_y:.1f})")
                        self._drawn_players_log = time.time()
                        self._drawn_any_player = True
                    
                    # Draw player name if zoom level allows
                    if self.zoom_level >= 0.5 and hasattr(player, 'nickname'):
                        name_text = self.font_small.render(player.nickname, True, WHITE)
                        name_rect = name_text.get_rect(center=(int(screen_x), int(screen_y) - player_size - 5))
                        self.screen.blit(name_text, name_rect)
                else:
                    # Just draw a dot for very zoomed out
                    self.screen.set_at((int(screen_x), int(screen_y)), GREEN)
        
        # DEBUG: Draw all players at their local coordinates in current segment (blue circles)
        if hasattr(self, 'game_state') and self.game_state:
            debug_count = 0
            for player_id, player in players_dict.items():
                if player_id == local_player_id:
                    continue
                    
                # Draw at local coordinates in current segment
                if hasattr(player, 'x') and hasattr(player, 'y') and player.x is not None and player.y is not None:
                    # Use player's local coordinates directly in current segment
                    debug_screen_x = player.x * tile_size - camera_offset_x + (gmap_parser.width // 2 * 64 * tile_size if 'gmap_parser' in locals() else 0)
                    debug_screen_y = player.y * tile_size - camera_offset_y + (gmap_parser.height // 2 * 64 * tile_size if 'gmap_parser' in locals() else 0)
                    
                    # Draw debug circle (blue)
                    if player_size >= 4:
                        pygame.draw.circle(self.screen, BLUE,
                                         (int(debug_screen_x), int(debug_screen_y)),
                                         player_size // 2, 2)  # Draw as outline
                        debug_count += 1
                        
            if debug_count > 0 and (not hasattr(self, '_debug_players_log') or time.time() - self._debug_players_log > 5):
                logger.info(f"[DEBUG] Drew {debug_count} players at local coordinates (blue circles)")
                self._debug_players_log = time.time()
        
    def _draw_single_level(self, client, level_name: str):
        """Draw single level (not GMAP mode)"""
        if not client or not hasattr(client, 'level_manager'):
            self._draw_error("No PyReborn client")
            return
            
        # Debug: log what we're trying to render
        if not hasattr(self, '_last_level_debug') or time.time() - self._last_level_debug > 2:
            logger.info(f"[RENDERER] _draw_single_level called with: {level_name}")
            logger.info(f"[RENDERER] PyReborn current_level: {client.level_manager.current_level.name if client.level_manager.current_level else 'None'}")
            logger.info(f"[RENDERER] Available levels: {list(client.level_manager.levels.keys())}")
            self._last_level_debug = time.time()
            
        level = client.level_manager.get_level(level_name)
        if not level:
            self._draw_error(f"Level {level_name} not found")
            return
            
        # Get local player position
        player_x = player_y = 30.0  # Default center
        local_player = None
        if hasattr(client, 'local_player'):
            local_player = client.local_player
            if local_player:
                player_x = local_player.x
                player_y = local_player.y
                
        # Use standard tile size for single level
        tile_size = int(16 * self.zoom_level)
        if tile_size < 1:
            tile_size = 1
            
        # Calculate camera position to center player
        camera_center_x = player_x * tile_size
        camera_center_y = player_y * tile_size
        camera_offset_x = camera_center_x - self.screen_width // 2
        camera_offset_y = camera_center_y - self.screen_height // 2
        
        # Clear screen
        self.screen.fill(BLACK)
        
        # Render the level
        self._render_level_at(client, level_name, -camera_offset_x, -camera_offset_y, tile_size)
        
        # Draw all players
        self._draw_all_players(client, camera_offset_x, camera_offset_y, tile_size)
        
        # Draw local player on top
        if local_player:
            player_screen_x = player_x * tile_size - camera_offset_x
            player_screen_y = player_y * tile_size - camera_offset_y
            
            player_size = max(4, int(16 * self.zoom_level))
            if player_size >= 4:
                pygame.draw.circle(self.screen, RED,
                                 (int(player_screen_x), int(player_screen_y)),
                                 player_size // 2)
            else:
                self.screen.set_at((int(player_screen_x), int(player_screen_y)), RED)
        
    def _draw_error(self, message: str):
        """Draw error message as a toast at bottom of screen"""
        # Create semi-transparent background
        toast_height = 40
        toast_y = self.screen_height - toast_height - 20
        
        # Draw background
        toast_surface = pygame.Surface((self.screen_width - 40, toast_height))
        toast_surface.set_alpha(200)
        toast_surface.fill((40, 40, 40))
        self.screen.blit(toast_surface, (20, toast_y))
        
        # Draw error text
        error_surface = self.font_small.render(f"⚠ {message}", True, (255, 200, 200))
        error_rect = error_surface.get_rect(center=(self.screen_width // 2, toast_y + toast_height // 2))
        self.screen.blit(error_surface, error_rect)
        
    def set_zoom(self, zoom: float):
        """Set zoom level (1.0 = normal, 0.1 = bird's eye)"""
        self.zoom_level = max(0.1, min(1.0, zoom))
        
    def toggle_birds_eye(self):
        """Toggle between zoom levels"""
        # Cycle through zoom levels: 1.0 -> 0.5 -> 0.25 -> 0.1 -> 1.0
        if self.zoom_level >= 0.8:
            self.zoom_level = 0.5
        elif self.zoom_level >= 0.4:
            self.zoom_level = 0.25
        elif self.zoom_level >= 0.2:
            self.zoom_level = 0.1
        else:
            self.zoom_level = 1.0
    
    def load_tileset_from_data(self, image_data: bytes, filename: str = "server_tileset"):
        """Load tileset from server-provided image data
        
        Args:
            image_data: Raw PNG/image data from server
            filename: Name of the tileset for logging
        """
        try:
            import io
            # Create a file-like object from the bytes
            image_stream = io.BytesIO(image_data)
            # Load the image using pygame
            new_tileset = pygame.image.load(image_stream).convert_alpha()
            
            # Replace the current tileset
            self.tileset = new_tileset
            logger.info(f"Hot-loaded tileset from server: {filename} ({len(image_data)} bytes)")
            
            # Get tileset dimensions for debugging
            if self.tileset:
                width, height = self.tileset.get_size()
                logger.info(f"Tileset dimensions: {width}x{height}")
                
        except Exception as e:
            logger.error(f"Failed to hot-load tileset {filename}: {e}")
            logger.error(f"Image data size: {len(image_data)} bytes")
            logger.error(f"First 16 bytes: {image_data[:16].hex() if image_data else 'None'}")