"""
Renderer Module - Handles all game rendering for Classic Graal
"""

import pygame
import math
import time
from typing import Dict, List, Tuple, Optional, Any
from pyreborn.protocol.enums import Direction
from pyreborn.models.level import Level
from pyreborn.models.player import Player

from classic_constants import ClassicItems
from item_manager import DroppedItem
from bush_handler import BushHandler
from gani_parser import GaniManager
from tile_defs import TileDefs

# Constants
TILE_SIZE = 16
VIEWPORT_TILES_X = 120
VIEWPORT_TILES_Y = 90
SCREEN_WIDTH = VIEWPORT_TILES_X * TILE_SIZE
SCREEN_HEIGHT = VIEWPORT_TILES_Y * TILE_SIZE

# Colors
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GREEN = (0, 255, 0)
RED = (255, 0, 0)
BLUE = (0, 0, 255)
YELLOW = (255, 255, 0)
GRAY = (128, 128, 128)
DARK_GREEN = (0, 128, 0)
BROWN = (139, 69, 19)
ORANGE = (255, 165, 0)
PURPLE = (128, 0, 128)
CYAN = (0, 255, 255)


class GameRenderer:
    """Handles all rendering for the game"""
    
    def __init__(self, screen: pygame.Surface, gani_manager: GaniManager, tile_defs: TileDefs):
        """Initialize the renderer
        
        Args:
            screen: Pygame screen surface
            gani_manager: GANI animation manager
            tile_defs: Tile definitions
        """
        self.screen = screen
        self.gani_manager = gani_manager
        self.tile_defs = tile_defs
        
        # Tile cache
        self.tile_cache: Dict[int, pygame.Surface] = {}
        self.sprite_cache: Dict[str, pygame.Surface] = {}
        
        # Camera position
        self.camera_x = 0
        self.camera_y = 0
        
        # Debug flags
        self.debug_collision = False
        self.debug_tiles = False
        
        # Fonts
        self.font_large = pygame.font.Font(None, 36)
        self.font_medium = pygame.font.Font(None, 24)
        self.font_small = pygame.font.Font(None, 18)
        self.font_tiny = pygame.font.Font(None, 14)
        
        # Load tileset
        self._load_tileset()
        
    def _load_tileset(self):
        """Load the tileset image"""
        import os
        try:
            # Try to find tileset in assets directory
            base_dir = os.path.dirname(os.path.abspath(__file__))
            tileset_path = os.path.join(base_dir, "assets", "pics1.png")
            self.tileset = pygame.image.load(tileset_path).convert_alpha()
            print(f"Loaded tileset from {tileset_path}")
        except Exception as e:
            print(f"Failed to load tileset: {e}")
            self.tileset = None
            
    def update_camera(self, player_x: float, player_y: float, is_gmap: bool = False, 
                     gmaplevelx: int = 0, gmaplevely: int = 0):
        """Update camera position to follow player
        
        Args:
            player_x: Player X position in tiles (may exceed 64 in GMAP mode)
            player_y: Player Y position in tiles (may exceed 64 in GMAP mode)
            is_gmap: Whether we're in GMAP mode (no bounds clamping)
            gmaplevelx: Current GMAP segment X coordinate
            gmaplevely: Current GMAP segment Y coordinate
        """
        # Always use local coordinates for camera (0-64)
        self.camera_x = player_x - (VIEWPORT_TILES_X // 2)
        self.camera_y = player_y - (VIEWPORT_TILES_Y // 2)
        
        # In single-level mode, clamp to level bounds
        if not is_gmap:
            self.camera_x = max(0, min(self.camera_x, 64 - VIEWPORT_TILES_X))
            self.camera_y = max(0, min(self.camera_y, 64 - VIEWPORT_TILES_Y))
        
        # Debug camera position
        if not hasattr(self, '_last_camera_debug') or time.time() - self._last_camera_debug > 2:
            mode = "GMAP" if is_gmap else "Single"
            print(f"[CAMERA] {mode} mode - Player at ({player_x:.2f}, {player_y:.2f}), Camera at ({self.camera_x:.2f}, {self.camera_y:.2f})")
            self._last_camera_debug = time.time()
        
        # Always ensure camera is initialized with valid values
        if self.camera_x == 0 and self.camera_y == 0 and (player_x != (VIEWPORT_TILES_X // 2) or player_y != (VIEWPORT_TILES_Y // 2)):
            print(f"[CAMERA] WARNING: Camera at (0,0) but player not at center - possible initialization issue")
        
    def get_tile_surface(self, tile_id: int) -> Optional[pygame.Surface]:
        """Get a tile surface from the tileset
        
        Args:
            tile_id: Tile ID to get
            
        Returns:
            Tile surface or None if not available
        """
        if tile_id in self.tile_cache:
            return self.tile_cache[tile_id]
            
        if not self.tileset:
            if not hasattr(self, '_logged_no_tileset'):
                print(f"[RENDERER] ERROR: No tileset loaded!")
                self._logged_no_tileset = True
            return None
            
        # Apply Reborn's tile coordinate conversion
        tx = (tile_id // 512) * 16 + (tile_id % 16)
        ty = (tile_id // 16) % 32
        
        tile_x = tx * TILE_SIZE
        tile_y = ty * TILE_SIZE
        
        # Check bounds
        if tile_x >= self.tileset.get_width() or tile_y >= self.tileset.get_height():
            return None
            
        # Extract tile
        try:
            tile_surface = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
            tile_surface.blit(self.tileset, (0, 0), 
                            (tile_x, tile_y, TILE_SIZE, TILE_SIZE))
            self.tile_cache[tile_id] = tile_surface
            return tile_surface
        except:
            return None
            
    def draw_level(self, level: Level, opened_chests: set, respawn_timers: dict):
        """Draw the level tiles
        
        Args:
            level: Level to draw
            opened_chests: Set of opened chest positions
            respawn_timers: Dict of positions with respawn timers
        """
        if not level:
            return
        
        # Draw at offset (0, 0) - for single level mode
        self._draw_level_at_offset(level, 0, 0, opened_chests, respawn_timers)
    
    def draw_gmap_levels(self, current_level: Level, gmap_handler, gmap_name: str, 
                        opened_chests: set, respawn_timers: dict):
        """Draw multiple GMAP levels seamlessly using adjacency map
        
        Args:
            current_level: The level the player is currently in
            gmap_handler: GmapHandler instance with adjacency map
            gmap_name: Name of the current GMAP
            opened_chests: Set of opened chest positions
            respawn_timers: Dict of positions with respawn timers
        """
        # Debug: Track render calls
        if not hasattr(self, '_render_count'):
            self._render_count = 0
        self._render_count += 1
        
        if self._render_count % 60 == 0:  # Log every second at 60fps
            print(f"[GMAP RENDERER] Render call #{self._render_count}, current_level={current_level.name if current_level else 'None'}")
            print(f"[GMAP RENDERER] Camera at ({self.camera_x:.2f}, {self.camera_y:.2f})")
        
        if not current_level:
            print(f"[GMAP RENDERER] WARNING: No current level set! (call #{self._render_count})")
            # If we have any loaded levels, try to use one
            if gmap_handler and gmap_handler.level_objects:
                # Try to use the current level from gmap handler
                if gmap_handler.current_level_name and gmap_handler.current_level_name in gmap_handler.level_objects:
                    current_level = gmap_handler.level_objects[gmap_handler.current_level_name]
                    print(f"[GMAP RENDERER] Using level from gmap handler: {current_level.name}")
                else:
                    # Use any loaded level as fallback
                    first_level_name = next(iter(gmap_handler.level_objects.keys()))
                    current_level = gmap_handler.level_objects[first_level_name]
                    print(f"[GMAP RENDERER] Using first available level: {current_level.name}")
            else:
                print(f"[GMAP RENDERER] ERROR: No levels available to render! Screen will be black.")
                return
            
        # If no gmap handler, fall back to single level drawing
        if not gmap_handler or not gmap_handler.level_adjacency:
            print(f"[GMAP RENDERER] No adjacency map, falling back to single level")
            self.draw_level(current_level, opened_chests, respawn_timers)
            return
            
        # Parse current level position from name (e.g., "zlttp-d8" -> col=3, row=8)
        level_name = current_level.name
        if '-' not in level_name:
            # Fallback to single level drawing
            self.draw_level(current_level, opened_chests, respawn_timers)
            return
            
        try:
            base_name = level_name.split('-')[0]
            segment_code = level_name.split('-')[1].replace('.nw', '')
            
            if len(segment_code) >= 2:
                col_char = segment_code[0]
                row_str = segment_code[1:]
                
                # Convert to numeric position
                current_col = ord(col_char.lower()) - ord('a')
                current_row = int(row_str)
                
                # Debug output for GMAP rendering (reduced spam)
                if not hasattr(self, '_last_debug_time') or time.time() - self._last_debug_time > 3:
                    print(f"[GMAP RENDERER] Current segment: {level_name} -> col={current_col}, row={current_row}")
                    print(f"[GMAP RENDERER] Available levels: {list(gmap_handler.level_adjacency.keys())}")
                    print(f"[GMAP RENDERER] Camera: ({self.camera_x}, {self.camera_y})")
                    self._last_debug_time = time.time()
                
                segments_rendered = 0
                
                # Draw current level at origin (0, 0) since camera is in local coordinates
                self._draw_level_at_offset(current_level, 0, 0, 
                                         opened_chests, respawn_timers)
                segments_rendered += 1
                
                if not hasattr(self, '_last_debug_time') or time.time() - self._last_debug_time > 3:
                    print(f"[GMAP RENDERER] Drawing current level {level_name} at center position ({current_col * 64}, {current_row * 64})")
                    print(f"[GMAP RENDERER] Level objects available: {list(gmap_handler.level_objects.keys())}")
                    
                    # Show sample tiles from current level being rendered
                    sample_tiles = []
                    for y in range(0, min(3, 64)):
                        for x in range(0, min(3, 64)):
                            tile_id = current_level.get_board_tile_id(x, y)
                            if tile_id != 0:
                                sample_tiles.append(f"{tile_id}")
                            if len(sample_tiles) >= 5:
                                break
                        if len(sample_tiles) >= 5:
                            break
                    print(f"[GMAP RENDERER] CENTER LEVEL {level_name} sample tiles: {sample_tiles}")
                
                # Draw adjacent levels using adjacency map
                if level_name in gmap_handler.level_adjacency:
                    adjacent_levels = gmap_handler.level_adjacency[level_name]
                    
                    # Map directions to offsets
                    direction_offsets = {
                        'north': (0, -1),
                        'south': (0, 1),
                        'east': (1, 0),
                        'west': (-1, 0),
                        'northeast': (1, -1),
                        'northwest': (-1, -1),
                        'southeast': (1, 1),
                        'southwest': (-1, 1)
                    }
                    
                    for direction, adj_level_name in adjacent_levels.items():
                        if adj_level_name in gmap_handler.level_objects:
                            level = gmap_handler.level_objects[adj_level_name]
                            
                            # Use the direction from adjacency map instead of calculating from coordinates
                            if direction in direction_offsets:
                                dir_x, dir_y = direction_offsets[direction]
                                relative_offset_x = dir_x * 64
                                relative_offset_y = dir_y * 64
                                
                                # Parse coordinates for debug output only
                                adj_segment_info = gmap_handler.parse_segment_name(adj_level_name)
                                if adj_segment_info:
                                    adj_base, adj_col, adj_row = adj_segment_info
                                else:
                                    adj_col, adj_row = 0, 0
                                
                                if not hasattr(self, '_last_debug_time') or time.time() - self._last_debug_time > 3:
                                    print(f"[GMAP RENDERER] Drawing {adj_level_name} ({direction}) at relative position ({relative_offset_x}, {relative_offset_y})")
                                    print(f"[GMAP RENDERER]   - Adjacent level: col={adj_col}, row={adj_row}")
                                    print(f"[GMAP RENDERER]   - Current level: col={current_col}, row={current_row}")
                                    print(f"[GMAP RENDERER]   - Direction offset: ({dir_x}, {dir_y}) * 64 = ({relative_offset_x}, {relative_offset_y})")
                                    print(f"[GMAP RENDERER]   - Camera position: ({self.camera_x}, {self.camera_y})")
                                    
                                    # Show sample tiles from adjacent level
                                    sample_tiles = []
                                    for y in range(0, min(3, 64)):
                                        for x in range(0, min(3, 64)):
                                            tile_id = level.get_board_tile_id(x, y)
                                            if tile_id != 0:
                                                sample_tiles.append(f"{tile_id}")
                                            if len(sample_tiles) >= 5:
                                                break
                                        if len(sample_tiles) >= 5:
                                            break
                                    print(f"[GMAP RENDERER] {direction.upper()} LEVEL {adj_level_name} sample tiles: {sample_tiles}")
                                    
                                    # Special debug for west direction
                                    if direction == 'west':
                                        print(f"[WEST DEBUG] Renderer is now using DIRECTION-BASED positioning")
                                        print(f"[WEST DEBUG] Direction 'west' maps to offset (-1, 0) * 64 = ({relative_offset_x}, {relative_offset_y})")
                                        print(f"[WEST DEBUG] This should place {adj_level_name} to the LEFT of {level_name}")
                                        print(f"[WEST DEBUG] Visual west level: {adj_level_name} at offset ({relative_offset_x}, {relative_offset_y})")
                                
                                self._draw_level_at_offset(level, relative_offset_x, relative_offset_y, 
                                                         opened_chests, respawn_timers)
                                segments_rendered += 1
                
                if not hasattr(self, '_last_debug_time') or time.time() - self._last_debug_time > 3:
                    print(f"[GMAP RENDERER] Rendered {segments_rendered} segments")
                        
        except Exception as e:
            print(f"Error parsing GMAP position: {e}")
            # Fallback to single level
            self.draw_level(current_level, opened_chests, respawn_timers)
    
    def _draw_level_at_offset(self, level: Level, world_offset_x: int, world_offset_y: int,
                             opened_chests: set, respawn_timers: dict):
        """Draw a level at a specific world offset
        
        Args:
            level: Level to draw
            world_offset_x: X offset in world tiles
            world_offset_y: Y offset in world tiles
            opened_chests: Set of opened chest positions
            respawn_timers: Dict of positions with respawn timers
        """
        # Get view bounds in world coordinates
        # Use floor for start to ensure we include partially visible tiles
        view_start_x = int(self.camera_x)  # Floor
        view_start_y = int(self.camera_y)  # Floor
        # Add extra tiles to ensure we render enough
        view_end_x = view_start_x + VIEWPORT_TILES_X + 2
        view_end_y = view_start_y + VIEWPORT_TILES_Y + 2
        
        # Calculate which part of this level is visible
        level_start_x = max(0, view_start_x - world_offset_x)
        level_start_y = max(0, view_start_y - world_offset_y)
        level_end_x = min(64, view_end_x - world_offset_x)
        level_end_y = min(64, view_end_y - world_offset_y)
        
        # Skip if level is completely out of view
        if level_start_x >= level_end_x or level_start_y >= level_end_y:
            return
            
        current_time = time.time()
        tiles_drawn = 0
        
            
        # Draw tiles
        for y in range(level_start_y, level_end_y):
            for x in range(level_start_x, level_end_x):
                tile_id = level.get_board_tile_id(x, y)
                
                # Check if this position has a respawn timer (grass/bush)
                world_x = x + world_offset_x
                world_y = y + world_offset_y
                if (world_x, world_y) in respawn_timers:
                    continue  # Skip drawing, it's been cut/removed
                
                # Draw the tile
                surface = self.get_tile_surface(tile_id)
                if surface:
                    screen_x = (world_x - self.camera_x) * TILE_SIZE
                    screen_y = (world_y - self.camera_y) * TILE_SIZE
                    self.screen.blit(surface, (screen_x, screen_y))
                    tiles_drawn += 1
                elif tile_id != 0:  # Don't log for empty tiles
                    if not hasattr(self, '_logged_missing_tiles'):
                        self._logged_missing_tiles = set()
                    if tile_id not in self._logged_missing_tiles:
                        print(f"[RENDERER] No surface for tile ID {tile_id}")
                        self._logged_missing_tiles.add(tile_id)
                    
        # Draw chests
        for chest in level.chests:
            world_chest_x = chest.x + world_offset_x
            world_chest_y = chest.y + world_offset_y
            
            if (world_chest_x, world_chest_y) in opened_chests:
                continue  # Skip opened chests
                
            # Check if chest is in view (accounting for 2x2 size)
            if (world_chest_x < view_start_x - 1 or world_chest_x >= view_end_x or 
                world_chest_y < view_start_y - 1 or world_chest_y >= view_end_y):
                continue
                
            # Get chest tiles based on item
            base_tile = self._get_chest_base_tile(chest.item)
            chest_tiles = [base_tile, base_tile + 1, base_tile + 16, base_tile + 17]
            
            # Draw 2x2 chest
            for i, tile_id in enumerate(chest_tiles):
                dx = i % 2
                dy = i // 2
                surface = self.get_tile_surface(tile_id)
                if surface:
                    screen_x = (world_chest_x + dx - self.camera_x) * TILE_SIZE
                    screen_y = (world_chest_y + dy - self.camera_y) * TILE_SIZE
                    self.screen.blit(surface, (screen_x, screen_y))
                    
        # Only log occasionally to reduce spam
        if not hasattr(self, '_last_tiles_debug') or time.time() - self._last_tiles_debug > 5:
            print(f"[RENDERER] Drew {tiles_drawn} tiles for level {level.name}")
            # Sample a few tiles to show what's being rendered
            if tiles_drawn > 0:
                sample_tiles = []
                for y in range(level_start_y, min(level_start_y + 3, level_end_y)):
                    for x in range(level_start_x, min(level_start_x + 3, level_end_x)):
                        tile_id = level.get_board_tile_id(x, y)
                        if tile_id != 0:
                            sample_tiles.append(f"{tile_id}")
                        if len(sample_tiles) >= 5:
                            break
                    if len(sample_tiles) >= 5:
                        break
                print(f"[RENDERER] Sample tiles from {level.name}: {sample_tiles}")
            self._last_tiles_debug = time.time()
                    
        # Draw NPCs
        for npc in level.npcs:
            world_npc_x = npc.x + world_offset_x
            world_npc_y = npc.y + world_offset_y
            
            if (world_npc_x < view_start_x or world_npc_x >= view_end_x or 
                world_npc_y < view_start_y or world_npc_y >= view_end_y):
                continue
                
            # For now, draw NPCs as colored circles
            screen_x = (world_npc_x - self.camera_x) * TILE_SIZE + TILE_SIZE // 2
            screen_y = (world_npc_y - self.camera_y) * TILE_SIZE + TILE_SIZE // 2
            pygame.draw.circle(self.screen, ORANGE, (int(screen_x), int(screen_y)), TILE_SIZE // 2)
            
    def _get_chest_base_tile(self, chest_item: int) -> int:
        """Get the base tile ID for a chest based on its item"""
        if chest_item >= 20:
            return ClassicItems.CHEST_RED
        elif chest_item >= 10:
            return ClassicItems.CHEST_BLUE
        elif chest_item >= 5:
            return ClassicItems.CHEST_GREEN
        else:
            return ClassicItems.CHEST_BROWN
            
    def draw_items(self, items: List[DroppedItem]):
        """Draw dropped items with floating animation
        
        Args:
            items: List of dropped items
        """
        current_time = time.time()
        
        for item in items:
            # Skip if out of view
            if (item.x < self.camera_x - 1 or item.x >= self.camera_x + VIEWPORT_TILES_X + 1 or
                item.y < self.camera_y - 1 or item.y >= self.camera_y + VIEWPORT_TILES_Y + 1):
                continue
                
            # Calculate screen position
            screen_x = (item.x - self.camera_x) * TILE_SIZE
            screen_y = (item.y - self.camera_y) * TILE_SIZE
            
            # Apply floating animation
            if not item.picked_up:
                float_offset = item.get_float_offset(current_time)
                screen_y += float_offset * TILE_SIZE
            else:
                # Rise up when picked up
                pickup_progress = (current_time - item.pickup_time) / 1.0
                screen_y -= pickup_progress * TILE_SIZE * 2
                
                # Fade out
                alpha = int(255 * (1.0 - pickup_progress))
                
            # Draw 2x2 item tiles
            for i, tile_id in enumerate(item.tile_ids):
                dx = (i % 2) * TILE_SIZE
                dy = (i // 2) * TILE_SIZE
                
                surface = self.get_tile_surface(tile_id)
                if surface:
                    if item.picked_up:
                        # Apply fade
                        faded = surface.copy()
                        faded.set_alpha(alpha)
                        self.screen.blit(faded, (screen_x + dx, screen_y + dy))
                    else:
                        self.screen.blit(surface, (screen_x + dx, screen_y + dy))
                        
    def draw_player(self, player: Player, animation_frame: int, gani_name: str, 
                   carry_sprite: str = "", is_local: bool = False, 
                   gmaplevelx: int = None, gmaplevely: int = None):
        """Draw a player with their current animation
        
        Args:
            player: Player to draw
            animation_frame: Current animation frame
            gani_name: GANI animation name
            carry_sprite: Carried object sprite name
            is_local: Whether this is the local player
            gmaplevelx: GMAP segment X coordinate (for world positioning)
            gmaplevely: GMAP segment Y coordinate (for world positioning)
        """
        # Calculate player position
        if is_local:
            # Local player uses local coordinates (camera is already relative to local player)
            player_x = player.x
            player_y = player.y
        else:
            # Other players need world coordinates if in GMAP
            if gmaplevelx is not None and gmaplevely is not None:
                # Use x2/y2 if available for other players
                if hasattr(player, 'x2') and player.x2 is not None:
                    player_x = player.x2
                    player_y = player.y2 or (player.gmaplevely * 64 + player.y)
                else:
                    # Fallback to calculated world position
                    player_x = player.gmaplevelx * 64 + player.x if player.gmaplevelx is not None else player.x
                    player_y = player.gmaplevely * 64 + player.y if player.gmaplevely is not None else player.y
            else:
                # Single level mode
                player_x = player.x
                player_y = player.y
        
        # Calculate screen position - round to integer pixels to prevent blurring
        screen_x = int((player_x - self.camera_x) * TILE_SIZE)
        screen_y = int((player_y - self.camera_y) * TILE_SIZE)
        
        # Get sprites for current animation
        sprites = self._get_player_sprites(player.direction, gani_name, animation_frame)
        
        # Draw each sprite layer
        for surface, x_offset, y_offset in sprites:
            self.screen.blit(surface, (screen_x + x_offset, screen_y + y_offset))
            
        # Draw carried object
        if carry_sprite:
            self._draw_carried_object(screen_x, screen_y, carry_sprite)
            
        # Draw player name
        if not is_local:
            name_text = self.font_tiny.render(player.nickname, True, WHITE)
            name_rect = name_text.get_rect(centerx=screen_x + TILE_SIZE, 
                                          bottom=screen_y - 2)
            self.screen.blit(name_text, name_rect)
            
        # Draw chat bubble
        if player.chat:
            self._draw_chat_bubble(screen_x, screen_y, player.chat)
            
    def _get_player_sprites(self, direction: Direction, gani: str, frame: int) -> List[Tuple[pygame.Surface, int, int]]:
        """Get sprites and positions for a player animation"""
        dir_map = {
            Direction.UP: 'up',
            Direction.LEFT: 'left',
            Direction.DOWN: 'down',
            Direction.RIGHT: 'right'
        }
        dir_name = dir_map.get(direction, 'down')
        
        # Load GANI file
        gani_file = self.gani_manager.load_gani(gani)
        if not gani_file:
            return []
            
        # Get sprite placements
        # Single frame animations should always use frame 0
        single_frame_ganis = ['idle', 'push', 'pull', 'grab', 'sit', 'lift']
        actual_frame = 0 if gani in single_frame_ganis else frame
        sprite_placements = gani_file.get_frame_sprites(actual_frame, dir_name)
        
        # Convert to surfaces
        result = []
        for sprite_id, x_offset, y_offset in sprite_placements:
            cache_key = f"{gani}_{sprite_id}"
            surface = None
            
            if cache_key in self.sprite_cache:
                surface = self.sprite_cache[cache_key]
            else:
                surface = self.gani_manager.get_sprite_surface(gani, sprite_id)
                if surface:
                    self.sprite_cache[cache_key] = surface
                    
            if surface:
                result.append((surface, x_offset, y_offset))
                
        return result
        
    def _draw_carried_object(self, screen_x: float, screen_y: float, carry_sprite: str):
        """Draw object carried above player's head"""
        if carry_sprite == "bush":
            tiles = [2, 3, 18, 19]
            offsets = [(0, 0), (1, 0), (0, 1), (1, 1)]
        else:
            return
            
        for tile_id, (dx, dy) in zip(tiles, offsets):
            surface = self.get_tile_surface(tile_id)
            if surface:
                obj_x = screen_x + (dx * TILE_SIZE)
                obj_y = screen_y - (TILE_SIZE * 1.5) + (dy * TILE_SIZE)
                self.screen.blit(surface, (obj_x, obj_y))
                
    def _draw_chat_bubble(self, x: float, y: float, text: str):
        """Draw a chat bubble above a player"""
        # Create text surface
        chat_surface = self.font_small.render(text, True, BLACK)
        
        # Create bubble
        padding = 6
        bubble_width = chat_surface.get_width() + padding * 2
        bubble_height = chat_surface.get_height() + padding * 2
        
        bubble_x = int(x + TILE_SIZE - bubble_width // 2)
        bubble_y = int(y - bubble_height - 10)
        
        # Draw bubble background
        bubble_rect = pygame.Rect(bubble_x, bubble_y, bubble_width, bubble_height)
        pygame.draw.rect(self.screen, WHITE, bubble_rect)
        pygame.draw.rect(self.screen, BLACK, bubble_rect, 2)
        
        # Draw tail
        tail_points = [
            (bubble_x + bubble_width // 2 - 5, bubble_y + bubble_height),
            (bubble_x + bubble_width // 2 + 5, bubble_y + bubble_height),
            (bubble_x + bubble_width // 2, bubble_y + bubble_height + 5)
        ]
        pygame.draw.polygon(self.screen, WHITE, tail_points)
        pygame.draw.lines(self.screen, BLACK, False, tail_points, 2)
        
        # Draw text
        self.screen.blit(chat_surface, (bubble_x + padding, bubble_y + padding))
        
    def draw_collision_debug(self, level: Level, local_player=None):
        """Draw collision debug overlay and player collision box"""
        if not self.debug_collision:
            return
            
        # Draw blocking tiles overlay
        if level:
            start_x = int(self.camera_x)
            start_y = int(self.camera_y) 
            end_x = min(start_x + VIEWPORT_TILES_X + 1, 64)
            end_y = min(start_y + VIEWPORT_TILES_Y + 1, 64)
            
            for y in range(start_y, end_y):
                for x in range(start_x, end_x):
                    tile_id = level.get_board_tile_id(x, y)
                    
                    if self.tile_defs.is_blocking(tile_id):
                        screen_x = (x - self.camera_x) * TILE_SIZE
                        screen_y = (y - self.camera_y) * TILE_SIZE
                        
                        # Draw red overlay
                        overlay = pygame.Surface((TILE_SIZE, TILE_SIZE))
                        overlay.set_alpha(100)
                        overlay.fill(RED)
                        self.screen.blit(overlay, (screen_x, screen_y))
                        
        # Draw player collision box
        if local_player:
            self.draw_player_collision_box(local_player)
                    
    def draw_player_collision_box(self, player):
        """Draw the player's collision box for debugging"""
        # Use EXACT same values from physics.py can_move_to()
        x_offset = 1.0  # 1 tile right
        y_offset = 1.0  # 1 tile down (base offset)
        
        # Shadow/collision box dimensions (from physics.py)
        shadow_width = 1.2
        shadow_height = 1.6  # Taller box for all directions (was 0.6, now 1.6)
        shadow_x_start = 0.1  # slight offset within the shadow
        
        # Direction-specific adjustments (matching physics.py)
        if player.direction == Direction.LEFT:
            x_offset -= 3.0 / 16.0  # 3 pixels left (3/16 of a tile)
        
        # Calculate screen position
        screen_x = (player.x - self.camera_x) * TILE_SIZE
        screen_y = (player.y - self.camera_y) * TILE_SIZE
        
        # Draw collision box in red - using exact physics calculations
        collision_rect = pygame.Rect(
            int(screen_x + (x_offset + shadow_x_start) * TILE_SIZE),
            int(screen_y + y_offset * TILE_SIZE),
            int(shadow_width * TILE_SIZE),
            int(shadow_height * TILE_SIZE)
        )
        pygame.draw.rect(self.screen, RED, collision_rect, 2)
        
        # Draw all collision check points from physics.py (with direction-adjusted y_offset)
        check_points = [
            (player.x + x_offset + shadow_x_start, player.y + y_offset),                    # Top-left
            (player.x + x_offset + shadow_x_start + shadow_width, player.y + y_offset),     # Top-right
            (player.x + x_offset + shadow_x_start, player.y + y_offset + shadow_height),    # Bottom-left
            (player.x + x_offset + shadow_x_start + shadow_width, player.y + y_offset + shadow_height), # Bottom-right
            (player.x + x_offset + 0.5, player.y + y_offset + shadow_height/2),             # Center
        ]
        
        # Draw each collision check point
        for i, (px, py) in enumerate(check_points):
            point_x = int((px - self.camera_x) * TILE_SIZE)
            point_y = int((py - self.camera_y) * TILE_SIZE)
            color = YELLOW if i == 4 else GREEN  # Center in yellow, corners in green
            pygame.draw.circle(self.screen, color, (point_x, point_y), 3)
        
        # Draw direction indicator
        dir_name = player.direction.name if hasattr(player.direction, 'name') else str(player.direction)
        direction_text = self.font_small.render(f"Dir: {dir_name}", True, WHITE)
        self.screen.blit(direction_text, (10, 120))
        
        # Draw position info
        pos_text = self.font_small.render(f"Pos: ({player.x:.1f}, {player.y:.1f})", True, WHITE)
        self.screen.blit(pos_text, (10, 140))
                    
    def draw_thrown_bushes(self, bush_handler):
        """Draw thrown bushes
        
        Args:
            bush_handler: BushHandler instance with thrown bushes
        """
        for bush in bush_handler.thrown_bushes:
            # Skip if out of view
            if (bush.x < self.camera_x - 2 or bush.x >= self.camera_x + VIEWPORT_TILES_X + 2 or
                bush.y < self.camera_y - 2 or bush.y >= self.camera_y + VIEWPORT_TILES_Y + 2):
                continue
                
            # Calculate screen position
            screen_x = (bush.x - self.camera_x) * TILE_SIZE
            screen_y = (bush.y - self.camera_y) * TILE_SIZE
            
            # Draw 2x2 bush tiles
            bush_tiles = [2, 3, 18, 19]
            for i, tile_id in enumerate(bush_tiles):
                dx = (i % 2) * TILE_SIZE
                dy = (i // 2) * TILE_SIZE
                
                surface = self.get_tile_surface(tile_id)
                if surface:
                    self.screen.blit(surface, (screen_x + dx, screen_y + dy))
                    
    def clear_cache(self):
        """Clear all rendering caches"""
        print("[RENDERER] Clearing tile cache and sprite cache...")
        self.tile_cache.clear()
        self.sprite_cache.clear()
        print(f"[RENDERER] Cleared {len(self.tile_cache)} tile cache entries")
        print(f"[RENDERER] Cleared {len(self.sprite_cache)} sprite cache entries")
                    
    def clear(self):
        """Clear the screen"""
        self.screen.fill(BLACK)