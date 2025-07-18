#!/usr/bin/env python3
"""
Classic Reborn Client - A clean, modular implementation of the Classic Graal game
"""

import sys
import pygame
import time
import math
from typing import Optional

from pyreborn.protocol.enums import Direction

# Import all our modules
from server_browser import ServerBrowserState
from connection_manager import ConnectionManager
from audio_manager import AudioManager
from input_manager import InputManager
from renderer import GameRenderer, SCREEN_WIDTH, SCREEN_HEIGHT
from ui_manager import UIManager
from animation_manager import AnimationManager
from game_state import GameState
from physics import Physics
from tile_defs import TileDefs
from gani_parser import GaniManager
from gmap_handler import GmapHandler
from classic_constants import ClassicConstants

# Colors
WHITE = (255, 255, 255)
GREEN = (0, 255, 0)
RED = (255, 0, 0)
YELLOW = (255, 255, 0)
BLUE = (0, 0, 255)
GRAY = (128, 128, 128)


class ClassicRebornClient:
    """Main game client that coordinates all modules"""
    
    def __init__(self):
        """Initialize the game client"""
        # Pygame setup
        pygame.init()
        # Use standard window size
        self.window_width = 1024
        self.window_height = 768
        self.screen = pygame.display.set_mode((self.window_width, self.window_height))
        pygame.display.set_caption("Classic Reborn")
        self.clock = pygame.time.Clock()
        self.running = False
        
        # Connection manager
        self.connection_manager = ConnectionManager()
        self._setup_connection_callbacks()
        
        # Initialize managers
        self.tile_defs = TileDefs()
        # Get correct base path for GANI files
        import os
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.gani_manager = GaniManager(base_dir)  # Pass the games directory as base
        self.audio_manager = AudioManager()
        self.input_manager = InputManager()
        
        # Create game surface for proper scaling
        self.game_surface = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        
        # Initialize renderer with game surface
        self.renderer = GameRenderer(self.game_surface, self.gani_manager, self.tile_defs)
        self.ui_manager = UIManager(self.screen)  # UI uses full screen
        self.animation_manager = AnimationManager(self.gani_manager)
        self.game_state = GameState(self.tile_defs)
        self.physics = Physics(self.tile_defs)
        self.gmap_handler = GmapHandler()
        
        # States
        self.state = "browser"  # "browser", "loading", or "game"
        self.server_browser = ServerBrowserState(self.screen)
        
        # Loading screen
        self.loading_start_time = 0
        self.loading_dots = 0
        self.loading_message = "Connecting..."
        
        # Setup input callbacks
        self._setup_input_callbacks()
        
        # Performance tracking
        self.fps_history = []
        self.fps_sample_size = 60
        
        # Auto-login info (set from command line)
        self.auto_login_info = None
        
        # UI toggles
        self.show_minimap = True
        
    def _setup_connection_callbacks(self):
        """Setup connection manager callbacks"""
        self.connection_manager.on_connected = self._on_connected
        self.connection_manager.on_disconnected = self._on_disconnected
        self.connection_manager.on_connection_failed = self._on_connection_failed
        self.connection_manager.on_level_received = self._on_level_received
        
    def _setup_input_callbacks(self):
        """Setup input manager callbacks"""
        self.input_manager.on_attack = self._handle_attack
        self.input_manager.on_grab = self._handle_grab
        self.input_manager.on_grab_release = self._handle_grab_release
        self.input_manager.on_chat_send = self._handle_chat_send
        self.input_manager.on_quit = self._handle_quit
        self.input_manager.on_debug_toggle = self._handle_debug_toggle
        self.input_manager.on_click_move = self._handle_click_move
        self.input_manager.on_warp_menu = self._handle_warp_menu
        self.input_manager.on_clear_cache = self._handle_clear_cache
        
    def _handle_attack(self):
        """Handle attack button press"""
        if self.game_state.is_attacking or self.game_state.is_throwing:
            return
            
        if self.game_state.bush_handler.carrying_bush:
            # Throw the bush
            self._throw_bush()
        else:
            # Swing sword
            print(f"→ ACTION: Sword swing")
            self._swing_sword()
            
    def _swing_sword(self):
        """Perform sword swing attack"""
        self.game_state.start_attack()
        self.animation_manager.set_player_animation(-1, "sword")  # -1 for local player
        self.client.set_gani("sword")
        
        # Play sword sound
        self.audio_manager.play_gani_sound("sword.wav", 1.0, 0)
        
        # Check sword hits
        self._check_sword_hits()
        
    def _check_sword_hits(self):
        """Check what the sword hits"""
        if not self.game_state.current_level or not self.game_state.local_player:
            return
            
        player = self.game_state.local_player
        hit_positions = self.physics.get_sword_hit_positions(
            player.x, player.y, self.game_state.last_direction
        )
        
        for hit_x, hit_y in hit_positions:
            tile_x = int(hit_x)
            tile_y = int(hit_y)
            
            if 0 <= tile_x < 64 and 0 <= tile_y < 64:
                tile_id = self.game_state.current_level.get_board_tile_id(tile_x, tile_y)
                
                # Check if it's grass or bush
                if self.tile_defs.is_cuttable(tile_id):
                    # Cut it
                    self.game_state.current_level.set_tile(tile_x, tile_y, 0)
                    
                    # Different sounds for different tiles
                    if self.tile_defs.is_bush(tile_id):
                        self.audio_manager.play_classic_sound('grass_cut')
                        self.ui_manager.add_message("Destroyed bush!", GREEN)
                    else:
                        self.audio_manager.play_classic_sound('grass_cut')
                        
                    # Maybe drop an item
                    dropped = self.game_state.item_manager.drop_random_item(tile_x, tile_y)
                    if dropped:
                        self.ui_manager.add_message("Found something!", GREEN)
                        self.audio_manager.play_classic_sound('secret', 0.5)
                        
                    # Add respawn timer
                    self.game_state.item_manager.add_respawn_timer(
                        tile_x, tile_y, ClassicConstants.GRASS_RESPAWN_TIME
                    )
                    
        # Check chest hits
        for chest in self.game_state.current_level.chests:
            if (chest.x, chest.y) in self.game_state.opened_chests:
                continue
                
            for hit_x, hit_y in hit_positions:
                if self.physics.check_chest_collision(hit_x, hit_y, chest.x, chest.y):
                    self._open_chest(chest)
                    break
                    
    def _open_chest(self, chest):
        """Open a chest"""
        self.game_state.opened_chests.add((chest.x, chest.y))
        self.audio_manager.play_classic_sound('chest_open')
        
        # Determine item type and drop it
        item_type = self._get_chest_item_type(chest.item)
        if item_type:
            self.game_state.item_manager.drop_item(chest.x + 0.5, chest.y + 0.5, item_type)
            self.ui_manager.add_message("Opened chest!", YELLOW)
            
            if item_type == 'heart_container':
                self.audio_manager.play_classic_sound('secret')
                
    def _get_chest_item_type(self, chest_item: int) -> Optional[str]:
        """Get item type from chest item ID"""
        if chest_item in [1, 2, 3]:
            return 'heart'
        elif chest_item in [4, 5, 6]:
            return 'rupee'
        elif chest_item in [7, 8]:
            return 'bomb'
        elif chest_item in [9, 10]:
            return 'arrow'
        elif chest_item in [11, 12]:
            return 'key'
        elif chest_item >= 20:
            return 'heart_container'
        else:
            return 'rupee'
            
    def _handle_grab(self):
        """Handle grab button press"""
        if self.game_state.bush_handler.carrying_bush:
            print(f"→ ACTION: Throw bush")
            self._throw_bush()
        else:
            # Just start grabbing, don't pick up yet
            print(f"→ ACTION: Start grab")
            self.game_state.is_grabbing = True
            self.client.set_gani("grab")
            self.animation_manager.set_player_animation(-1, "grab")
            
    def _handle_grab_release(self):
        """Handle grab button release"""
        if self.game_state.is_grabbing and not self.game_state.bush_handler.carrying_bush:
            # Try to pick up bush when releasing grab
            if not self.game_state.local_player:
                return
                
            player = self.game_state.local_player
            bush_pos = self.game_state.bush_handler.try_pickup_bush(
                self.game_state.current_level,
                self.tile_defs,
                player.x,
                player.y,
                self.game_state.last_direction
            )
            if bush_pos:
                # Replace bush tiles with new tiles  
                tile_x, tile_y = bush_pos
                self._replace_bush_tiles(tile_x, tile_y)
                self.client.set_gani("lift")  # Lift animation
                self.animation_manager.set_player_animation(-1, "lift")
                # Notify server we're carrying a bush
                self.client.set_carry_sprite("bush")
                self.ui_manager.add_message("Picked up bush!", GREEN)
            else:
                # Return to idle if nothing picked up
                self.client.set_gani("idle")
                self.animation_manager.set_player_animation(-1, "idle")
                
        self.game_state.is_grabbing = False
        self.game_state.grabbed_tile_pos = None
            
    def _try_grab(self):
        """Try to grab something in front of player"""
        if not self.game_state.local_player:
            return
            
        player = self.game_state.local_player
        positions = self.physics.get_grab_check_positions(
            player.x, player.y, self.game_state.last_direction
        )
        
        # Check for grabbable objects
        for check_x, check_y in positions:
            # Check for bush
            grabbable = self.game_state.bush_handler.check_grabbable_at_position(
                self.game_state.current_level, self.tile_defs, check_x, check_y
            )
            
            if grabbable:
                self.game_state.is_grabbing = True
                self.game_state.grabbed_tile_pos = grabbable
                self.animation_manager.set_player_animation(-1, "grab")
                self.client.set_gani("grab")
                
                tile_x, tile_y = grabbable
                tile_id = self.game_state.current_level.get_board_tile_id(tile_x, tile_y)
                
                if self.tile_defs.is_bush(tile_id):
                    self.ui_manager.add_message("Grabbing bush - release A to pick up!", GREEN)
                else:
                    self.ui_manager.add_message("Grabbing object - pull with opposite arrow!", YELLOW)
                return
                
        # Check for signs
        for check_x, check_y in positions:
            sign = self._check_for_sign(check_x, check_y)
            if sign:
                self._read_sign(sign)
                return
                
        self.ui_manager.add_message("Nothing to grab here", RED)
        
    def _check_for_sign(self, x: float, y: float):
        """Check for a sign at position"""
        if not self.game_state.current_level:
            return None
            
        tile_x = int(x)
        tile_y = int(y)
        
        # Check level signs
        for sign in self.game_state.current_level.signs:
            if sign.x == tile_x and sign.y == tile_y:
                return sign
                
        return None
        
    def _read_sign(self, sign):
        """Read a sign"""
        if sign and hasattr(sign, 'text') and sign.text:
            self.audio_manager.play_classic_sound('text', 0.6)
            lines = sign.text.split('\\n')
            for line in lines:
                self.ui_manager.add_message(line, WHITE)
        else:
            self.ui_manager.add_message("The sign is blank.", GRAY)
            
    def _throw_bush(self):
        """Throw carried bush"""
        if not self.game_state.local_player:
            return
            
        player = self.game_state.local_player
        self.game_state.bush_handler.throw_bush(
            player.x, player.y, self.game_state.last_direction
        )
        
        self.game_state.start_throw()
        self.animation_manager.set_player_animation(-1, "sword")
        self.client.set_gani("sword")
        self.audio_manager.play_classic_sound('bush_throw')
        
        # Clear carry state
        self.client.set_carry_sprite("")
        # Note: throw_carried() is for notifying server, not a client method
        
    def _replace_bush_tiles(self, tile_x: int, tile_y: int):
        """Replace a bush (2x2 tiles) with the picked-up tiles"""
        if not self.game_state.current_level:
            return
            
        # Get the current tile to determine which bush tile it is
        current_tile = self.game_state.current_level.get_board_tile_id(tile_x, tile_y)
        
        # Determine the top-left corner of the bush based on which tile was grabbed
        if current_tile == 2:  # Top-left
            base_x, base_y = tile_x, tile_y
        elif current_tile == 3:  # Top-right
            base_x, base_y = tile_x - 1, tile_y
        elif current_tile == 18:  # Bottom-left
            base_x, base_y = tile_x, tile_y - 1
        elif current_tile == 19:  # Bottom-right
            base_x, base_y = tile_x - 1, tile_y - 1
        else:
            return  # Not a bush tile
            
        # Replace the 2x2 bush with the new tiles
        replacement_tiles = [
            (base_x, base_y, 677),      # Top-left
            (base_x + 1, base_y, 678),  # Top-right
            (base_x, base_y + 1, 693),  # Bottom-left
            (base_x + 1, base_y + 1, 694)  # Bottom-right
        ]
        
        # Update the tile data in memory for display
        for x, y, new_tile_id in replacement_tiles:
            if 0 <= x < 64 and 0 <= y < 64:
                self.game_state.current_level.set_tile(x, y, new_tile_id)
        
    def _handle_chat_send(self, message: str):
        """Handle sending a chat message"""
        if self.client and message:
            # Check for commands
            if message.startswith("/"):
                self._handle_command(message)
            else:
                print(f"→ CHAT: {message}")
                self.client.set_chat(message)
                self.ui_manager.add_chat_message(f"{self.game_state.local_player.nickname}: {message}", WHITE)
            
    def _handle_quit(self):
        """Handle quit request"""
        self.running = False
        
    def _handle_debug_toggle(self, debug_type: str):
        """Handle debug toggle"""
        if debug_type == 'debug':
            # Toggle general debug
            pass
        elif debug_type == 'collision':
            self.renderer.debug_collision = not self.renderer.debug_collision
            self.ui_manager.add_message(
                f"Collision Debug: {'ON' if self.renderer.debug_collision else 'OFF'}", 
                YELLOW
            )
        elif debug_type == 'tiles':
            self.renderer.debug_tiles = not self.renderer.debug_tiles
            self.ui_manager.add_message(
                f"Tile Debug: {'ON' if self.renderer.debug_tiles else 'OFF'}", 
                YELLOW
            )
        elif debug_type == 'minimap':
            self.show_minimap = not self.show_minimap
            self.ui_manager.add_message(
                f"Minimap: {'ON' if self.show_minimap else 'OFF'}", 
                YELLOW
            )
                
    def _handle_click_move(self, screen_x: int, screen_y: int):
        """Handle click-to-move functionality
        
        Args:
            screen_x: Screen X coordinate
            screen_y: Screen Y coordinate
        """
        if not self.game_state.local_player or not self.game_state.current_level:
            return
            
        # Only work in game state
        if self.state != "game":
            return
            
        # Convert screen coordinates to game coordinates
        # Account for scaling and centering
        scale_x = self.window_width / SCREEN_WIDTH
        scale_y = self.window_height / SCREEN_HEIGHT
        scale = min(scale_x, scale_y)
        
        scaled_width = int(SCREEN_WIDTH * scale)
        scaled_height = int(SCREEN_HEIGHT * scale)
        x_offset = (self.window_width - scaled_width) // 2
        y_offset = (self.window_height - scaled_height) // 2
        
        # Convert to game surface coordinates
        game_x = (screen_x - x_offset) / scale
        game_y = (screen_y - y_offset) / scale
        
        # Convert to pixel coordinates (Graal's internal coordinate system)
        pixel_x = game_x
        pixel_y = game_y
        
        if self.game_state.is_gmap:
            # GMAP mode: calculate global pixel position, then determine target
            current_seg_x = getattr(self.game_state.local_player, 'gmaplevelx', 0) or 0
            current_seg_y = getattr(self.game_state.local_player, 'gmaplevely', 0) or 0
            
            # Player's current global pixel position
            player_local_pixels_x = self.game_state.local_player.x * 16
            player_local_pixels_y = self.game_state.local_player.y * 16
            player_global_x = current_seg_x * 1024 + player_local_pixels_x
            player_global_y = current_seg_y * 1024 + player_local_pixels_y
            
            # Calculate click offset from player (screen center)
            screen_center_x = SCREEN_WIDTH / 2
            screen_center_y = SCREEN_HEIGHT / 2
            click_offset_x = pixel_x - screen_center_x
            click_offset_y = pixel_y - screen_center_y
            
            # Target global pixel position
            target_global_x = player_global_x + click_offset_x
            target_global_y = player_global_y + click_offset_y
            
            # Convert back to segment + local coordinates
            target_seg_x = int(target_global_x // 1024)
            target_seg_y = int(target_global_y // 1024)
            target_local_pixels_x = target_global_x % 1024
            target_local_pixels_y = target_global_y % 1024
            target_local_tiles_x = target_local_pixels_x / 16
            target_local_tiles_y = target_local_pixels_y / 16
            
            # Check if clicking in different segment (cross-segment warp)
            if target_seg_x != current_seg_x or target_seg_y != current_seg_y:
                if hasattr(self.game_state.current_level, 'name') and '-' in self.game_state.current_level.name:
                    base_name = self.game_state.current_level.name.split('-')[0]
                    if target_seg_x >= 0 and target_seg_y >= 0:
                        target_col_char = chr(ord('a') + target_seg_x)
                        target_level = f"{base_name}-{target_col_char}{target_seg_y}.nw"
                        
                        # Clamp local coordinates and convert to tiles
                        target_x = max(0, min(63, target_local_tiles_x))
                        target_y = max(0, min(63, target_local_tiles_y))
                        
                        self.client.warp_to_level(target_level, target_x, target_y)
                        self.ui_manager.add_message(f"Warping to {target_level}", GREEN)
                        return
                        
            # Same segment or fallback: move within current segment
            target_x = max(0, min(63, target_local_tiles_x))
            target_y = max(0, min(63, target_local_tiles_y))
        else:
            # Single level mode: simple tile coordinates
            target_x = pixel_x / 16
            target_y = pixel_y / 16
            target_x = max(0, min(63, target_x))
            target_y = max(0, min(63, target_y))
        
        # Always use local coordinates for movement
        self.client.move_to(target_x, target_y)
        self.ui_manager.add_message(f"Moving to ({target_x:.1f}, {target_y:.1f})", GREEN)
        
    def _handle_warp_menu(self):
        """Handle opening the warp menu"""
        if not self.client:
            return
        # The warp dialog will be shown automatically when warp_mode is True
        
    def _handle_clear_cache(self):
        """Handle clearing all caches (F5 key)"""
        print("[CLIENT] Clearing all caches...")
        
        # Clear rendering caches
        self.renderer.clear_cache()
        self.gmap_handler.clear_cache()
        
        # Clear level download cache if connected
        if self.connection_manager.is_connected():
            client = self.connection_manager.client
            if hasattr(client, '_raw_data_handler'):
                client._raw_data_handler.clear_file_cache()
        
        self.ui_manager.add_message("All caches cleared!", GREEN)
        
    def _handle_command(self, command: str):
        """Handle slash commands
        
        Args:
            command: Command string starting with /
        """
        parts = command[1:].split()
        if not parts:
            return
            
        cmd = parts[0].lower()
        args = parts[1:]
        
        if cmd == "warp":
            if not args:
                self.ui_manager.add_message("Usage: /warp <level> or /warp <x> <y>", RED)
                return
                
            # Try to parse as coordinates
            if len(args) == 2:
                try:
                    x = float(args[0])
                    y = float(args[1])
                    
                    # Warp to position
                    if self.game_state.local_player:
                        self.client.move_to(x, y)
                        self.game_state.local_player.x = x
                        self.game_state.local_player.y = y
                        self.ui_manager.add_message(f"Warped to ({x}, {y})", GREEN)
                    return
                except ValueError:
                    pass
                    
            # Otherwise treat as level name
            level_name = ' '.join(args)
            
            # Request warp to level (server will validate)
            self.client.warp_to_level(level_name, 30.0, 30.0)
            self.ui_manager.add_message(f"Warping to {level_name}...", GREEN)
            return
                
            self.ui_manager.add_message(f"Unknown level: {level_name}", RED)
            
        elif cmd == "pos":
            if self.game_state.local_player:
                p = self.game_state.local_player
                level_name = self.game_state.current_level.name if self.game_state.current_level else 'unknown'
                
                # Basic position
                self.ui_manager.add_message(
                    f"Position: ({p.x:.2f}, {p.y:.2f}) in {level_name}",
                    YELLOW
                )
                
                # GMAP position if available
                if hasattr(p, 'gmaplevelx') and p.gmaplevelx is not None:
                    self.ui_manager.add_message(
                        f"GMAP Segment: [{p.gmaplevelx}, {p.gmaplevely}]",
                        CYAN
                    )
                if hasattr(p, 'x2') and p.x2 is not None:
                    self.ui_manager.add_message(
                        f"GMAP Position: ({p.x2:.2f}, {p.y2:.2f}, {p.z2:.2f})",
                        CYAN
                    )
            else:
                self.ui_manager.add_message("No player position available", RED)
                
        elif cmd == "levels":
            levels = []
            if hasattr(self.client, 'level_manager') and self.client.level_manager:
                levels.extend(self.client.level_manager.levels.keys())
            if hasattr(self.client, 'levels'):
                levels.extend(self.client.levels.keys())
                
            levels = sorted(set(l for l in levels if not l.endswith('.gmap')))
            
            self.ui_manager.add_message(f"Available levels ({len(levels)}):", YELLOW)
            for level in levels[:20]:
                self.ui_manager.add_message(f"  {level}", GREEN)
            if len(levels) > 20:
                self.ui_manager.add_message(f"  ... and {len(levels) - 20} more", GRAY)
                
        elif cmd == "help":
            self.ui_manager.add_message("=== Debug Commands ===", YELLOW)
            self.ui_manager.add_message("/warp <level> - Warp to a level", WHITE)
            self.ui_manager.add_message("/warp <x> <y> - Warp to coordinates", WHITE)
            self.ui_manager.add_message("/pos - Show current position", WHITE)
            self.ui_manager.add_message("/levels - List available levels", WHITE)
            self.ui_manager.add_message("/help - Show this help", WHITE)
            self.ui_manager.add_message("F4 - Open warp menu", WHITE)
            self.ui_manager.add_message("Click - Move to position", WHITE)
            
        else:
            self.ui_manager.add_message(f"Unknown command: {cmd}", RED)
            
    @property
    def client(self):
        """Get the current client instance"""
        return self.connection_manager.client
            
    def _on_connected(self, client):
        """Handle successful connection
        
        Args:
            client: Connected RebornClient instance
        """
        print(f"Connected to server!")
        
        # Setup event handlers
        self._setup_event_handlers()
        
        # Store local player
        self.game_state.local_player = client.local_player
        self.loading_message = "Loading level..."
        
        print(f"Local player: {client.local_player}")
        
        # Note: GMAP camera initialization moved to _on_level_received to ensure level is loaded first
        
    def _on_disconnected(self):
        """Handle disconnection from server"""
        print("Disconnected from server")
        self.ui_manager.add_message("Disconnected from server", RED)
        self.state = "browser"
        
    def _on_connection_failed(self, error_msg: str):
        """Handle connection failure
        
        Args:
            error_msg: Error message
        """
        print(f"Connection failed: {error_msg}")
        self.ui_manager.add_message(f"Connection failed: {error_msg}", RED)
        self.state = "browser"
        
    def _on_level_received(self, level):
        """Handle level received from server
        
        Args:
            level: Level object
        """
        print(f"← LEVEL: Received {level.name}")
        
        # Add ALL received levels to level map if they are GMAP segments
        if self.gmap_handler.is_gmap_level(level.name) and not level.name.endswith('.gmap'):
            self.gmap_handler.add_level(level.name, level)
            print(f"[GMAP] Added {level.name} to adjacency map (from _on_level_received)")
            
            # If this is our first level, set it as current
            if not self.gmap_handler.current_level_name:
                self.gmap_handler.set_current_level(level.name)
        
        # Only set as current level if player is actually in this level
        # Check if this matches the player's current level name
        player_level = ""
        if self.game_state.local_player and hasattr(self.game_state.local_player, 'level'):
            player_level = self.game_state.local_player.level
            
        print(f"[LEVEL] Player level: '{player_level}', Received level: '{level.name}'")
        print(f"[LEVEL] Current game level: {self.game_state.current_level.name if self.game_state.current_level else 'None'}")
        
        # Set as current level if:
        # 1. Player level matches this level, OR
        # 2. No current level is set (first level received), OR  
        # 3. Loading state (initial level), OR
        # 4. This is the current GMAP segment
        should_set_current = (
            (self.game_state.local_player and 
             hasattr(self.game_state.local_player, 'level') and
             self.game_state.local_player.level == level.name) or
            (not self.game_state.current_level) or
            (self.state == "loading") or
            (self.gmap_handler.current_level_name == level.name)
        )
        
        if should_set_current:
            print(f"[LEVEL] Setting {level.name} as current level")
            
            # Set player's level property when setting current level
            if self.game_state.local_player:
                self.game_state.local_player.level = level.name
                print(f"[LEVEL] Set player level to {level.name}")
            
            self.game_state.set_level(level)
            self.ui_manager.add_message(f"Entered {level.name}", GREEN)
            
            # Update gmap handler
            self.gmap_handler.update_position_from_level(level.name)
            
            # Add level to gmap level map if it's a segment
            if self.gmap_handler.is_gmap_level(level.name) and not level.name.endswith('.gmap'):
                self.gmap_handler.update_level_from_name(level.name, level)
                
            # Initialize GMAP camera position if this is the first GMAP level
            if self.gmap_handler.is_gmap_level(level.name) and not level.name.endswith('.gmap') and self.game_state.local_player:
                # Check if we need to convert coordinates
                segment_info = self.gmap_handler.parse_segment_name(level.name)
                if segment_info:
                    base_name, seg_x, seg_y = segment_info
                    
                    # The x/y property setters will automatically maintain x2/y2
                    print(f"[GMAP INIT] Player at local ({self.game_state.local_player.x:.2f}, {self.game_state.local_player.y:.2f}) in segment [{seg_x},{seg_y}]")
                    print(f"            Expected world coordinates: ({self.game_state.local_player.x + seg_x * 64:.2f}, {self.game_state.local_player.y + seg_y * 64:.2f})")
                    if hasattr(self.game_state.local_player, 'x2') and self.game_state.local_player.x2 is not None:
                        print(f"            Actual world coordinates: ({self.game_state.local_player.x2:.2f}, {self.game_state.local_player.y2:.2f})")
                    
                    # Update camera with local position
                    self.renderer.update_camera(
                        self.game_state.local_player.x,
                        self.game_state.local_player.y,
                        True, seg_x, seg_y)
                    print(f"[GMAP INIT] Updated camera to local position ({self.game_state.local_player.x:.2f}, {self.game_state.local_player.y:.2f})")
            
            # If it's a GMAP segment, set game state and request adjacent levels
            if self.gmap_handler.is_gmap_level(level.name):
                print(f"[GMAP] Detected GMAP level: {level.name}")
                self.game_state.is_gmap = True
                
                # If it's a .gmap file, request it; if it's a segment, request adjacent levels
                if level.name.endswith('.gmap'):
                    self.client.request_file(level.name)
                    print(f"[GMAP] Requesting gmap file: {level.name}")
                elif '-' in level.name:
                    # This is a GMAP segment - request adjacent levels for seamless rendering
                    print(f"[GMAP] Requesting adjacent levels for segment: {level.name}")
                    self._request_adjacent_gmap_levels(level.name)
        else:
            print(f"[LEVEL] Received adjacent segment: {level.name} (not setting as current level)")
            # Still store adjacent segments in level manager for rendering
            if self.client.level_manager and hasattr(self.client.level_manager, 'levels'):
                self.client.level_manager.levels[level.name] = level
                print(f"[LEVEL] Stored adjacent segment {level.name} in level manager")
        
        # Transition to game state
        if self.state == "loading":
            self.state = "game"
            self.loading_message = "Ready!"
            
            # Check if player spawned on a blocking tile
            if self.game_state.local_player and self.game_state.current_level:
                player = self.game_state.local_player
                level = self.game_state.current_level
                
                # Check current position for blocking tiles
                is_gmap = self.gmap_handler.current_gmap is not None
                # Try to move in place - if it fails, we're on a blocking tile
                if not self.physics.can_move_to(player.x, player.y, level, is_gmap=is_gmap, gmap_handler=self.gmap_handler):
                    print(f"[SPAWN FIX] Player spawned on blocking tile at ({player.x:.2f}, {player.y:.2f})")
                    
                    # Find nearest safe position
                    safe_x, safe_y = player.x, player.y
                    found_safe = False
                    
                    # Search in expanding circles
                    for radius in range(1, 5):
                        for dx in range(-radius, radius + 1):
                            for dy in range(-radius, radius + 1):
                                if abs(dx) == radius or abs(dy) == radius:  # Only check perimeter
                                    test_x = player.x + dx * 0.5
                                    test_y = player.y + dy * 0.5
                                    
                                    # Make sure position is valid
                                    if is_gmap or (0 <= test_x < 64 and 0 <= test_y < 64):
                                        if self.physics.can_move_to(test_x, test_y, level, is_gmap=is_gmap, gmap_handler=self.gmap_handler):
                                            safe_x, safe_y = test_x, test_y
                                            found_safe = True
                                            break
                            if found_safe:
                                break
                        if found_safe:
                            break
                    
                    if found_safe:
                        # Use local coordinates - property setter will update x2/y2
                        self.client.move_to(safe_x, safe_y)
                        player.x = safe_x
                        player.y = safe_y
                        
                        print(f"[SPAWN FIX] Moved player to safe position ({safe_x:.2f}, {safe_y:.2f})")
                        self.ui_manager.add_message("Moved to safe position", YELLOW)
            
            # Update camera to center on player
            if self.game_state.local_player and self.game_state.current_level:
                # Get GMAP segment coordinates if available
                gmaplevelx = getattr(self.game_state.local_player, 'gmaplevelx', None)
                gmaplevely = getattr(self.game_state.local_player, 'gmaplevely', None)
                
                # If GMAP coords not set but level name looks like a GMAP segment, parse coordinates
                if gmaplevelx is None:
                    current_level = self.game_state.current_level
                    if current_level and '-' in current_level.name and current_level.name.endswith('.nw'):
                        try:
                            # Parse GMAP coordinates from level name (e.g., "zlttp-d8.nw" -> col=3, row=8)
                            base_name = current_level.name.split('-')[0]
                            segment_code = current_level.name.split('-')[1].replace('.nw', '')
                            if len(segment_code) >= 2:
                                col_char = segment_code[0]
                                row_str = segment_code[1:]
                                gmaplevelx = ord(col_char.lower()) - ord('a')
                                gmaplevely = int(row_str)
                                pass  # Parsed GMAP coords successfully
                        except Exception as e:
                            pass  # Error parsing GMAP coords
                            pass
                
                # Determine if we're on a GMAP by checking level name directly
                is_gmap_level = (current_level and '-' in current_level.name and 
                               current_level.name.endswith('.nw'))
                
                # Update camera - always use local coordinates
                self.renderer.update_camera(
                    self.game_state.local_player.x,
                    self.game_state.local_player.y,
                    is_gmap_level,
                    gmaplevelx or 0,
                    gmaplevely or 0
                )
                print(f"[LOADING->GAME] Updated camera for player at local ({self.game_state.local_player.x:.2f}, {self.game_state.local_player.y:.2f})")
            
    def _setup_event_handlers(self):
        """Setup network event handlers"""
        from pyreborn.events import EventType
        events = self.client.events
        events.subscribe(EventType.PLAYER_ADDED, self._on_player_added)
        events.subscribe(EventType.PLAYER_LEFT, self._on_player_left)
        events.subscribe(EventType.OTHER_PLAYER_UPDATE, self._on_player_moved)
        events.subscribe(EventType.PLAYER_PROPS_UPDATE, self._on_player_props_update)
        events.subscribe(EventType.CHAT_MESSAGE, self._on_player_chat)
        events.subscribe(EventType.FILE_RECEIVED, self._on_file_received)
            
    def _on_player_added(self, **kwargs):
        """Handle player added event"""
        player = kwargs.get('player')
        if player:
            print(f"← PLAYER: Added {player.nickname} (id:{player.id})")
            self.game_state.add_player(player)
            # Initialize animation state
            if player.gani:
                self.animation_manager.set_player_animation(player.id, player.gani)
            
    def _on_player_left(self, **kwargs):
        """Handle player left event"""
        player_id = kwargs.get('player_id')
        if player_id:
            self.game_state.remove_player(player_id)
            self.animation_manager.cleanup_player(player_id)
            
    def _on_player_moved(self, **kwargs):
        """Handle player movement event"""
        player = kwargs.get('player')
        if player and self.client and self.client.local_player:
            # Don't update local player from server events
            if player.id != self.client.local_player.id:
                self.game_state.update_player(player.id, 
                    x=player.x, y=player.y, direction=player.direction, gani=player.gani)
                # Update animation manager
                if player.gani:
                    self.animation_manager.set_player_animation(player.id, player.gani)
                
    def _on_player_props_update(self, **kwargs):
        """Handle player property update"""
        player = kwargs.get('player')
        if player and self.client and self.client.local_player:
            # Don't update direction for local player - we control that locally
            if player.id == self.client.local_player.id:
                # For GMAP levels, the server sends x/y as local coords
                # The client must maintain x2/y2 world coordinates
                if self.gmap_handler.current_gmap and hasattr(player, 'x') and hasattr(player, 'y'):
                        # Server sends local segment coordinates (0-64)
                        # We need to convert to world coordinates
                        
                        # Parse current level to get segment coordinates
                        seg_x = 0
                        seg_y = 0
                        if self.game_state.current_level:
                            segment_info = self.gmap_handler.parse_segment_name(self.game_state.current_level.name)
                            if segment_info:
                                base_name, seg_x, seg_y = segment_info
                        
                        # Store original server coords
                        server_x = player.x
                        server_y = player.y
                        
                        # Convert to world coordinates
                        world_x = server_x + (seg_x * 64)
                        world_y = server_y + (seg_y * 64)
                        
                        print(f"[PLAYER UPDATE] Server sent local coords ({server_x:.2f}, {server_y:.2f}) for segment [{seg_x}, {seg_y}]")
                        print(f"[PLAYER UPDATE] Converting to world coords: ({world_x:.2f}, {world_y:.2f})")
                        
                        # Server sends local coordinates - update player's x2/y2 with world coordinates
                        player.x2 = world_x
                        player.y2 = world_y
                        # Keep x/y as local coordinates
                        player.x = server_x
                        player.y = server_y
                        
                        # Update our local player's x2/y2 if this is us
                        if self.game_state.local_player and player.id == self.game_state.local_player.id:
                            self.game_state.local_player.x2 = world_x
                            self.game_state.local_player.y2 = world_y
                
                # Filter out direction updates for local player
                filtered_kwargs = {k: v for k, v in kwargs.items() if k != 'direction'}
                # For GMAP, also filter out position updates since we've already converted them
                if self.gmap_handler.current_gmap:
                    filtered_kwargs = {k: v for k, v in filtered_kwargs.items() if k not in ['x', 'y']}
                self.game_state.update_player(player.id, **filtered_kwargs)
            else:
                self.game_state.update_player(player.id, **kwargs)
            # Update animation manager if gani changed
            if player.gani:
                self.animation_manager.set_player_animation(player.id, player.gani)
            
    def _on_player_chat(self, **kwargs):
        """Handle player chat message"""
        player = kwargs.get('player')
        message = kwargs.get('message')
        if player and message:
            self.ui_manager.add_chat_message(f"{player.nickname}: {message}", WHITE)
            
    def _on_file_received(self, **kwargs):
        """Handle file received from server"""
        filename = kwargs.get('filename', '')
        data = kwargs.get('data', b'')
        
        if filename.endswith('.gmap'):
            # Let the gmap handler parse it
            self.gmap_handler.parse_gmap_file(filename, data)
            
            # Update game state with gmap info
            gmap_info = self.gmap_handler.get_gmap_info()
            self.game_state.gmap_width = gmap_info.get('gmap_width', 1)
            self.game_state.gmap_height = gmap_info.get('gmap_height', 1)
            self.game_state.is_gmap = True
            
            self.ui_manager.add_message(
                f"GMAP loaded: {self.game_state.gmap_width}x{self.game_state.gmap_height}",
                GREEN
            )
            
            # Request adjacent segments
            self._request_gmap_segments()
                                

            
    def handle_movement(self):
        """Process movement input"""
        # Track old position for gmap segment detection
        # In GMAP mode, use x2/y2 (world coordinates) if available
        if self.gmap_handler.current_gmap and self.game_state.local_player:
            old_x = getattr(self.game_state.local_player, 'x2', None)
            old_y = getattr(self.game_state.local_player, 'y2', None)
            # Fall back to calculated world coordinates if x2/y2 not set
            if old_x is None or old_y is None:
                seg_x = 0
                seg_y = 0
                if self.game_state.current_level:
                    segment_info = self.gmap_handler.parse_segment_name(self.game_state.current_level.name)
                    if segment_info:
                        base_name, seg_x, seg_y = segment_info
                old_x = self.game_state.local_player.x + (seg_x * 64)
                old_y = self.game_state.local_player.y + (seg_y * 64)
        else:
            old_x = self.game_state.local_player.x if self.game_state.local_player else 0
            old_y = self.game_state.local_player.y if self.game_state.local_player else 0
        
        # Special handling for grabbing state
        if self.game_state.is_grabbing:
            self._handle_pull_movement()
            return
            
        if not self.game_state.can_move():
            return
            
        # Get movement input
        direction = self.input_manager.get_movement_direction()
        if direction is None:
            # No movement - check for idle state
            if self.game_state.is_moving:
                self.game_state.is_moving = False
                
                # Set appropriate idle animation
                if self.game_state.on_chair:
                    self.client.set_gani("sit")
                    self.animation_manager.set_player_animation(-1, "sit")
                else:
                    self.client.set_gani("idle")
                    self.animation_manager.set_player_animation(-1, "idle")
            return
            
        # Calculate new position
        dx, dy = self.input_manager.get_movement_vector()
        speed = self.game_state.get_current_speed()
        
        # Always use local coordinates for movement
        current_x = self.game_state.local_player.x
        current_y = self.game_state.local_player.y
            
        new_x = current_x + dx * speed
        new_y = current_y + dy * speed
        
        # Check collision
        is_gmap = self.gmap_handler.current_gmap is not None
        
        # For GMAP, use the current level for collision checking
        level_to_check = self.game_state.current_level
        if is_gmap and self.gmap_handler.current_gmap:
            # Use current level for collision checking
            current_level = self.gmap_handler.get_current_level()
            if current_level:
                level_to_check = current_level
        
        can_move = self.physics.can_move_to(new_x, new_y, level_to_check,
                                   self.game_state.bush_handler.carrying_bush,
                                   self.game_state.local_player.direction, is_gmap, self.gmap_handler)
        
        # Debug movement blocking
        if not can_move:
            print(f"🚫 Movement blocked: from ({old_x:.2f}, {old_y:.2f}) to ({new_x:.2f}, {new_y:.2f})")
            print(f"   Direction: {direction}, Speed: {speed}")
            print(f"   is_gmap: {is_gmap}")
            print(f"   Current level: {self.game_state.current_level.name if self.game_state.current_level else 'None'}")
            
        if can_move:
            # Store old segment coordinates for boundary crossing detection
            old_gmaplevelx = getattr(self.game_state.local_player, 'gmaplevelx', 0)
            old_gmaplevely = getattr(self.game_state.local_player, 'gmaplevely', 0)
            
            # Debug current state
            current_level_name = self.game_state.current_level.name if self.game_state.current_level else 'None'
            print(f"[BOUNDARY DEBUG] Current level: {current_level_name}")
            print(f"[BOUNDARY DEBUG] Player segment coords: [{old_gmaplevelx}, {old_gmaplevely}]")
            print(f"[BOUNDARY DEBUG] Movement: x={current_x:.2f} -> {new_x:.2f}, y={current_y:.2f} -> {new_y:.2f}")
            
            # Check for GMAP boundary crossing BEFORE moving
            target_level_name = None
            target_gmaplevelx = old_gmaplevelx
            target_gmaplevely = old_gmaplevely
            wrapped_x = new_x
            wrapped_y = new_y
            
            if self.gmap_handler.current_gmap:
                # Use adjacency map to determine target levels instead of math
                current_level_name = self.game_state.current_level.name if self.game_state.current_level else None
                boundary_direction = None
                
                # Check if trying to move outside current level bounds
                if new_x < 0:
                    # Moving west
                    boundary_direction = 'west'
                    wrapped_x = 63.5  # Enter west level on the east side
                    print(f"[GMAP BOUNDARY] West crossing: x={new_x:.2f}")
                elif new_x >= 64:
                    # Moving east  
                    boundary_direction = 'east'
                    wrapped_x = 0.5   # Enter east level on the west side
                    print(f"[GMAP BOUNDARY] East crossing: x={new_x:.2f}")
                
                if new_y < 0:
                    # Moving north
                    boundary_direction = 'north'
                    wrapped_y = 63.5  # Enter north level on the south side
                    print(f"[GMAP BOUNDARY] North crossing: y={new_y:.2f}")
                elif new_y >= 64:
                    # Moving south
                    boundary_direction = 'south'
                    wrapped_y = 0.5   # Enter south level on the north side
                    print(f"[GMAP BOUNDARY] South crossing: y={new_y:.2f}")
                
                # Get target level from adjacency map
                if boundary_direction and current_level_name:
                    # First, let's see what the adjacency map contains for the current level
                    current_adjacency = self.gmap_handler.level_adjacency.get(current_level_name, {})
                    print(f"[DEBUG] Current level '{current_level_name}' adjacency: {current_adjacency}")
                    
                    target_level_name = self.gmap_handler.get_adjacent_level(current_level_name, boundary_direction)
                    if target_level_name:
                        print(f"[GMAP] Adjacency map says {boundary_direction} of {current_level_name} is {target_level_name}")
                        
                        # Let's also check what the renderer is showing as west
                        if boundary_direction == 'west':
                            print(f"[DEBUG] Renderer should be showing {target_level_name} to the west")
                            print(f"[DEBUG] Warping will take you to {target_level_name}")
                            print(f"[DEBUG] Are these the same? {target_level_name == target_level_name}")
                        
                        # Parse target level coordinates
                        target_segment_info = self.gmap_handler.parse_segment_name(target_level_name)
                        if target_segment_info:
                            _, target_gmaplevelx, target_gmaplevely = target_segment_info
                            
                            # Update player's segment coordinates
                            self.game_state.local_player.gmaplevelx = target_gmaplevelx
                            self.game_state.local_player.gmaplevely = target_gmaplevely
                            
                            # Use wrapped coordinates for the new level
                            new_x = wrapped_x
                            new_y = wrapped_y
                            
                            print(f"[GMAP] Using adjacency: target segment [{target_gmaplevelx}, {target_gmaplevely}]")
                        else:
                            print(f"[GMAP] Failed to parse target level {target_level_name}")
                            target_level_name = None
                    else:
                        print(f"[GMAP] No adjacent level found for {boundary_direction} of {current_level_name}")
                        target_level_name = None
            
            # Move player locally using final coordinates (wrapped if boundary crossed)
            self.game_state.local_player.x = new_x
            self.game_state.local_player.y = new_y
            
            # Handle level switching if boundary was crossed
            if target_level_name:
                print(f"[GMAP BOUNDARY] Switching from [{old_gmaplevelx}, {old_gmaplevely}] to [{target_gmaplevelx}, {target_gmaplevely}]")
                
                # Check if the target level is already loaded
                target_level = self.gmap_handler.get_level_object(target_level_name)
                if target_level:
                    print(f"[GMAP] Target level {target_level_name} already loaded, switching to it")
                    
                    # Update player's level property
                    if self.game_state.local_player:
                        self.game_state.local_player.level = target_level_name
                        print(f"[GMAP] Updated player level to {target_level_name}")
                    
                    # Set the new current level
                    self.gmap_handler.set_current_level(target_level_name)
                    self.game_state.set_level(target_level)
                    self.ui_manager.add_message(f"Switched to {target_level_name}", GREEN)
                    
                    # Update camera to new segment - use local coordinates
                    self.renderer.update_camera(
                        self.game_state.local_player.x,
                        self.game_state.local_player.y,
                        True,  # is_gmap
                        target_gmaplevelx,
                        target_gmaplevely
                    )
                    print(f"[GMAP] Updated camera to new segment [{target_gmaplevelx}, {target_gmaplevely}] at local ({self.game_state.local_player.x:.2f}, {self.game_state.local_player.y:.2f})")
                    
                    # Debug: Check what level we think we're in vs what we're rendering
                    game_state_level = self.game_state.current_level.name if self.game_state.current_level else "None"
                    client_level = self.connection_manager.client.level_manager.get_current_level()
                    client_level_name = client_level.name if client_level else "None"
                    print(f"[DEBUG LEVELS] GameState thinks level: {game_state_level}")
                    print(f"[DEBUG LEVELS] Client level manager thinks level: {client_level_name}")
                    print(f"[DEBUG LEVELS] Player level property: {getattr(self.game_state.local_player, 'level', 'None')}")
                    print(f"[DEBUG LEVELS] Player GMAP coords: [{self.game_state.local_player.gmaplevelx}, {self.game_state.local_player.gmaplevely}]")
                else:
                    print(f"[GMAP] Target level {target_level_name} not loaded, need to request it")
                    
                    # Update player's level property to the target level
                    if self.game_state.local_player:
                        self.game_state.local_player.level = target_level_name
                        print(f"[GMAP] Updated player level to {target_level_name} (requesting)")
                        
                    self.client.request_file(target_level_name)
                    self.ui_manager.add_message(f"Loading {target_level_name}...", YELLOW)
                    
                    # Update camera even when level isn't loaded yet - use local coordinates
                    self.renderer.update_camera(
                        self.game_state.local_player.x,
                        self.game_state.local_player.y,
                        True,  # is_gmap
                        target_gmaplevelx,
                        target_gmaplevely
                    )
                    print(f"[GMAP] Updated camera for loading segment [{target_gmaplevelx}, {target_gmaplevely}] at local ({self.game_state.local_player.x:.2f}, {self.game_state.local_player.y:.2f})")
                
                # Request new adjacent segments
                self._request_gmap_segments()
            self.game_state.local_player.direction = direction
            self.game_state.last_move_time = time.time()
            self.game_state.last_direction = direction
            
            # Always send local coordinates to server
            # The property setters have already wrapped the coordinates, so use the actual values
            actual_x = self.game_state.local_player.x
            actual_y = self.game_state.local_player.y
            if 0 <= actual_x <= 63.5 and 0 <= actual_y <= 63.5:
                self.client.move_to(actual_x, actual_y, direction)
                # Segment boundary check has been moved before movement sending
            
            # Clear push state
            if self.game_state.is_pushing:
                self.game_state.stop_push()
                
            # Set moving animation
            if not self.game_state.is_moving:
                self.game_state.is_moving = True
                self.game_state.on_chair = False
                
                if self.game_state.bush_handler.carrying_bush:
                    self.client.set_gani("carry")
                    self.animation_manager.set_player_animation(-1, "carry")
                    # Make sure carry sprite is set
                    self.client.set_carry_sprite("bush")
                else:
                    self.client.set_gani("walk")
                    self.animation_manager.set_player_animation(-1, "walk")
            # Ensure animation is playing even if already moving
            elif not self.game_state.is_attacking and not self.game_state.is_throwing:
                current_anim = self.animation_manager.get_player_animation(-1).gani_name
                if self.game_state.bush_handler.carrying_bush and current_anim != "carry":
                    self.client.set_gani("carry")
                    self.animation_manager.set_player_animation(-1, "carry")
                elif not self.game_state.bush_handler.carrying_bush and current_anim != "walk":
                    self.client.set_gani("walk")
                    self.animation_manager.set_player_animation(-1, "walk")
        else:
            # Blocked - start push
            if direction is not None:
                self.game_state.last_direction = direction
                self.game_state.start_push(direction)
                
                # Send direction update
                self.client.move_to(
                    self.game_state.local_player.x,
                    self.game_state.local_player.y,
                    direction
                )
                
                # Show push animation after delay
                if self.game_state.should_show_push_animation():
                    if self.game_state.local_player.gani != "push":
                        print(f"→ ACTION: Push animation (blocked)")
                        self.client.set_gani("push")
                        self.animation_manager.set_player_animation(-1, "push")
                        
    def _handle_pull_movement(self):
        """Handle pulling animation while grabbing (no actual movement)"""
        direction = self.input_manager.get_movement_direction()
        
        if direction is not None:
            # Check if it's opposite direction (for pulling)
            opposite_direction = {
                Direction.LEFT: Direction.RIGHT,
                Direction.RIGHT: Direction.LEFT,
                Direction.UP: Direction.DOWN,
                Direction.DOWN: Direction.UP
            }.get(self.game_state.last_direction)
            
            current_gani = self.animation_manager.get_player_animation(-1).gani_name
            
            if direction == opposite_direction:
                # Show pull animation
                if current_gani != "pull":
                    print(f"→ ACTION: Pull animation (opposite dir)")
                    self.client.set_gani("pull")
                    self.animation_manager.set_player_animation(-1, "pull")
            else:
                # Not pulling - stay in grab animation
                if current_gani != "grab":
                    self.client.set_gani("grab")
                    self.animation_manager.set_player_animation(-1, "grab")
        else:
            # No movement - stay in grab animation
            current_gani = self.animation_manager.get_player_animation(-1).gani_name
            if current_gani != "grab":
                self.client.set_gani("grab")
                self.animation_manager.set_player_animation(-1, "grab")
                        
    def update(self):
        """Update game logic"""
        current_time = time.time()
        
        # Check for level during loading state
        if self.state == "loading":
            level = self.connection_manager.check_for_level()
            if level:
                self._on_level_received(level)
        
        # Update game state
        self.game_state.update(current_time)
        
        # Update gmap status from player properties
        if self.game_state.local_player:
            self.game_state.update_gmap_status(self.game_state.local_player)
        
        # Update UI
        self.ui_manager.update()
        
        # Update animations
        if self.state == "game":
            # Check for animation transitions
            if self.game_state.attack_just_finished:
                self.game_state.attack_just_finished = False
                # Return to appropriate idle state
                if self.game_state.is_moving:
                    if self.game_state.bush_handler.carrying_bush:
                        self.client.set_gani("carry")
                        self.animation_manager.set_player_animation(-1, "carry")
                    else:
                        self.client.set_gani("walk")
                        self.animation_manager.set_player_animation(-1, "walk")
                else:
                    self.client.set_gani("idle")
                    self.animation_manager.set_player_animation(-1, "idle")
                    
            if hasattr(self.game_state, 'throw_just_finished') and self.game_state.throw_just_finished:
                self.game_state.throw_just_finished = False
                # Return to appropriate idle state
                if self.game_state.is_moving:
                    self.client.set_gani("walk")
                    self.animation_manager.set_player_animation(-1, "walk")
                else:
                    self.client.set_gani("idle")
                    self.animation_manager.set_player_animation(-1, "idle")
            
            # Update local player animation
            if self.game_state.local_player:
                # Update camera based on player position
                # In GMAP mode, use x2/y2 if available
                if self.gmap_handler.current_gmap:
                    player_x = getattr(self.game_state.local_player, 'x2', None)
                    player_y = getattr(self.game_state.local_player, 'y2', None)
                    
                    # Debug x2/y2 availability
                    if not hasattr(self, '_last_x2_debug') or time.time() - self._last_x2_debug > 2:
                        print(f"[X2Y2 DEBUG] x2={player_x}, y2={player_y}, x={self.game_state.local_player.x}, y={self.game_state.local_player.y}")
                        self._last_x2_debug = time.time()
                    
                    # Fall back to calculated world coordinates if x2/y2 not set
                    if player_x is None or player_y is None:
                        seg_x = 0
                        seg_y = 0
                        if self.game_state.current_level:
                            segment_info = self.gmap_handler.parse_segment_name(self.game_state.current_level.name)
                            if segment_info:
                                base_name, seg_x, seg_y = segment_info
                        player_x = self.game_state.local_player.x + (seg_x * 64)
                        player_y = self.game_state.local_player.y + (seg_y * 64)
                        if not hasattr(self, '_last_fallback_debug') or time.time() - self._last_fallback_debug > 2:
                            print(f"[X2Y2 DEBUG] Using fallback: world=({player_x}, {player_y}) from local=({self.game_state.local_player.x}, {self.game_state.local_player.y}) + segment=[{seg_x},{seg_y}]")
                            self._last_fallback_debug = time.time()
                    self.renderer.update_camera(player_x, player_y, True)
                else:
                    self.renderer.update_camera(
                        self.game_state.local_player.x,
                        self.game_state.local_player.y,
                        False
                    )
                
                old_gani, old_frame = self.animation_manager.get_player_animation(-1).gani_name, self.animation_manager.get_player_animation(-1).frame
                gani, frame = self.animation_manager.update_player_animation(-1)
                
                # Play GANI sounds if frame changed
                if gani == old_gani and frame != old_frame:
                    self._play_gani_frame_sounds(gani, frame)
                
            # Update other player animations
            for player_id in self.game_state.players:
                self.animation_manager.update_player_animation(player_id)
                
            # Check water status
            if self.game_state.local_player and self.game_state.current_level:
                was_swimming = self.game_state.is_swimming
                self.game_state.is_swimming = self.physics.is_in_water(
                    self.game_state.local_player.x,
                    self.game_state.local_player.y,
                    self.game_state.current_level
                )
                
                if self.game_state.is_swimming and not was_swimming:
                    self.ui_manager.add_message("Swimming", BLUE)
                    self.audio_manager.play_classic_sound('swim', 0.6)
                    
            # Check item pickups
            if self.game_state.local_player:
                picked_items = self.game_state.item_manager.check_pickup(
                    self.game_state.local_player.x,
                    self.game_state.local_player.y
                )
                
                for item in picked_items:
                    self._handle_item_pickup(item)
                    
            # Update camera
            if self.game_state.local_player:
                # Get GMAP segment coordinates if available
                gmaplevelx = getattr(self.game_state.local_player, 'gmaplevelx', None)
                gmaplevely = getattr(self.game_state.local_player, 'gmaplevely', None)
                
                # Get current level for processing
                current_level = self.game_state.current_level
                
                # If GMAP coords not set but level name looks like a GMAP segment, parse coordinates
                if gmaplevelx is None:
                    if current_level and '-' in current_level.name and current_level.name.endswith('.nw'):
                        try:
                            # Parse GMAP coordinates from level name (e.g., "zlttp-d8.nw" -> col=3, row=8)
                            base_name = current_level.name.split('-')[0]
                            segment_code = current_level.name.split('-')[1].replace('.nw', '')
                            if len(segment_code) >= 2:
                                col_char = segment_code[0]
                                row_str = segment_code[1:]
                                gmaplevelx = ord(col_char.lower()) - ord('a')
                                gmaplevely = int(row_str)
                                pass  # Parsed GMAP coords successfully
                        except Exception as e:
                            pass  # Error parsing GMAP coords
                            pass
                
                # Determine if we're on a GMAP by checking level name directly
                is_gmap_level = (current_level and '-' in current_level.name and 
                               current_level.name.endswith('.nw'))
                
                # Always use local coordinates for camera
                self.renderer.update_camera(
                    self.game_state.local_player.x,
                    self.game_state.local_player.y,
                    is_gmap_level,
                    gmaplevelx or 0,
                    gmaplevely or 0
                )
                
            # Handle movement
            self.handle_movement()
            
            # Request adjacent levels if in gmap
            self._check_adjacent_level_requests()
            
            # Check for animation state transitions using animation manager
            if self.game_state.is_attacking:
                if self.animation_manager.is_animation_finished(-1, "sword"):
                    self.game_state.is_attacking = False
                    # Return to appropriate animation
                    if self.game_state.is_moving:
                        self.client.set_gani("walk")
                        self.animation_manager.set_player_animation(-1, "walk")
                    else:
                        self.client.set_gani("idle")
                        self.animation_manager.set_player_animation(-1, "idle")
                    
            if self.game_state.is_throwing:
                if self.animation_manager.is_animation_finished(-1, "sword"):
                    self.game_state.is_throwing = False
                    # Return to appropriate animation
                    if self.game_state.is_moving:
                        if self.game_state.bush_handler.carrying_bush:
                            self.client.set_gani("carry")
                            self.animation_manager.set_player_animation(-1, "carry")
                        else:
                            self.client.set_gani("walk")
                            self.animation_manager.set_player_animation(-1, "walk")
                    else:
                        self.client.set_gani("idle")
                        self.animation_manager.set_player_animation(-1, "idle")
                        
            # Check for lift animation finished
            current_anim = self.animation_manager.get_player_animation(-1)
            if current_anim.gani_name == "lift":
                if self.animation_manager.is_animation_finished(-1, "lift"):
                    # Transition to carry or idle based on bush state
                    if self.game_state.bush_handler.carrying_bush:
                        if self.game_state.is_moving:
                            self.client.set_gani("carry")
                            self.animation_manager.set_player_animation(-1, "carry")
                        else:
                            self.client.set_gani("idle")
                            self.animation_manager.set_player_animation(-1, "idle")
                            # Keep the carry sprite visible
                            self.client.set_carry_sprite("bush")
            
        # Update debug info
        self.ui_manager.update_debug_info('FPS', f"{self.clock.get_fps():.1f}")
        if self.game_state.local_player:
            self.ui_manager.update_debug_info(
                'Position', 
                f"{self.game_state.local_player.x:.1f}, {self.game_state.local_player.y:.1f}"
            )
            
    def _handle_item_pickup(self, item):
        """Handle picking up an item"""
        if not self.game_state.local_player:
            return
            
        player = self.game_state.local_player
        
        # Apply item effects
        if item.item_type == 'heart':
            player.hearts = min(player.hearts + item.value, player.max_hearts)
            self.ui_manager.add_message("Recovered health!", GREEN)
        elif item.item_type == 'rupee':
            player.rupees += int(item.value)
            self.ui_manager.add_message(f"+{int(item.value)} Rupees!", GREEN)
        elif item.item_type == 'bomb':
            player.bombs += int(item.value)
            self.ui_manager.add_message(f"+{int(item.value)} Bombs!", GRAY)
        elif item.item_type == 'arrow':
            player.arrows += int(item.value)
            self.ui_manager.add_message(f"+{int(item.value)} Arrows!", YELLOW)
        elif item.item_type == 'key':
            if hasattr(player, 'keys'):
                player.keys += 1
            self.ui_manager.add_message("Got a key!", BLUE)
        elif item.item_type == 'heart_container':
            player.max_hearts += 1
            player.hearts = player.max_hearts
            self.ui_manager.add_message("Heart Container! Max hearts increased!", (255, 0, 255))
            
        # Play pickup sound
        self.audio_manager.play_item_pickup_sound(item.item_type)
        
    def _get_current_gmap_segment_level(self):
        """Get the current GMAP segment level based on player position
        
        Returns:
            Level object for current segment or None
        """
        if not self.game_state.local_player:
            return None
            
        # Get player's GMAP coordinates
        gmaplevelx = getattr(self.game_state.local_player, 'gmaplevelx', None)
        gmaplevely = getattr(self.game_state.local_player, 'gmaplevely', None)
        
        print(f"[CLIENT] Player GMAP coords: gmaplevelx={gmaplevelx}, gmaplevely={gmaplevely}")
        
        # If GMAP coords not set, try to parse from current level name
        if gmaplevelx is None or gmaplevely is None:
            current_level = self.game_state.current_level
            if current_level and '-' in current_level.name:
                try:
                    from pyreborn.gmap_utils import GMAPUtils
                    _, seg_x, seg_y = GMAPUtils.gmap_name_to_segment(current_level.name)
                    gmaplevelx = seg_x
                    gmaplevely = seg_y
                    print(f"[CLIENT] Parsed GMAP coords from level name: {current_level.name} -> ({seg_x}, {seg_y})")
                except Exception as e:
                    print(f"[CLIENT] Failed to parse GMAP coords: {e}")
                    return None
            else:
                return None
            
        # Convert to segment name
        gmap_name = self.client.level_manager.current_gmap
        if not gmap_name:
            return None
            
        # Use GMAPUtils for proper segment naming
        from pyreborn.gmap_utils import GMAPUtils
        base_name = gmap_name.replace('.gmap', '')
        segment_name = GMAPUtils.segment_to_gmap_name(base_name, gmaplevelx, gmaplevely)
        
        print(f"[CLIENT] Looking for segment: {segment_name}")
        
        # Look for this segment in loaded levels
        result = self.client.level_manager.levels.get(segment_name)
        if not result:
            print(f"[CLIENT] Available levels: {list(self.client.level_manager.levels.keys())}")
        return result
    
    def _request_gmap_segments(self):
        """Request adjacent gmap segments"""
        segments = self.gmap_handler.get_segments_to_request()
        for segment in segments:
            self.client.request_file(segment)
            self.gmap_handler.mark_segment_requested(segment)
            print(f"[GMAP] Requested segment: {segment}")
            
    def _check_adjacent_level_requests(self):
        """Check if we need to request gmap files and adjacent levels"""
        # If we're in a gmap (detected by handler), request adjacent segments
        if self.gmap_handler.current_gmap:
            self._request_gmap_segments()
        
    def _draw_loading_screen(self):
        """Draw a cool loading screen"""
        # Background with gradient effect
        self.screen.fill((5, 20, 5))  # Very dark green
        
        # Draw animated border
        current_time = time.time()
        border_phase = (current_time * 2) % (math.pi * 2)
        border_color = (
            int(50 + 50 * math.sin(border_phase)),
            int(150 + 100 * math.sin(border_phase)),
            int(50 + 50 * math.sin(border_phase))
        )
        pygame.draw.rect(self.screen, border_color, self.screen.get_rect(), 5)
        
        # Center of screen
        center_x = self.window_width // 2
        center_y = self.window_height // 2
        
        # Draw spinning squares
        for i in range(8):
            angle = (current_time * 2 + i * math.pi / 4) % (math.pi * 2)
            radius = 100 + 20 * math.sin(current_time * 3 + i)
            x = center_x + radius * math.cos(angle)
            y = center_y + radius * math.sin(angle)
            
            size = 20 + 10 * math.sin(current_time * 4 + i)
            color_intensity = int(100 + 155 * ((i + current_time) % 8) / 8)
            color = (0, color_intensity, 0)
            
            rect = pygame.Rect(x - size/2, y - size/2, size, size)
            pygame.draw.rect(self.screen, color, rect)
            pygame.draw.rect(self.screen, (0, 255, 0), rect, 2)
        
        # Draw title
        title_font = pygame.font.Font(None, 48)
        title = title_font.render("Classic Reborn", True, (0, 255, 0))
        title_rect = title.get_rect(centerx=center_x, y=center_y - 150)
        
        # Shadow effect
        shadow = title_font.render("Classic Reborn", True, (0, 50, 0))
        shadow_rect = title_rect.copy()
        shadow_rect.x += 3
        shadow_rect.y += 3
        self.screen.blit(shadow, shadow_rect)
        self.screen.blit(title, title_rect)
        
        # Loading message with animated dots
        dots = "." * (int(current_time * 2) % 4)
        loading_font = pygame.font.Font(None, 36)
        loading_text = loading_font.render(self.loading_message + dots, True, (144, 238, 144))
        loading_rect = loading_text.get_rect(centerx=center_x, y=center_y + 100)
        self.screen.blit(loading_text, loading_rect)
        
        # Progress bar
        bar_width = 400
        bar_height = 20
        bar_x = center_x - bar_width // 2
        bar_y = center_y + 150
        
        # Bar background
        pygame.draw.rect(self.screen, (0, 50, 0), (bar_x, bar_y, bar_width, bar_height))
        pygame.draw.rect(self.screen, (0, 100, 0), (bar_x, bar_y, bar_width, bar_height), 2)
        
        # Animated fill
        fill_progress = (math.sin(current_time * 3) + 1) / 2  # 0 to 1
        fill_width = int(bar_width * fill_progress)
        if fill_width > 0:
            fill_rect = pygame.Rect(bar_x, bar_y, fill_width, bar_height)
            pygame.draw.rect(self.screen, (0, 200, 0), fill_rect)
            
            # Glow effect
            for i in range(3):
                glow_rect = fill_rect.inflate(i * 4, i * 4)
                glow_color = (0, 100 - i * 30, 0)
                pygame.draw.rect(self.screen, glow_color, glow_rect, 1)
    
    def draw(self):
        """Draw everything"""
        # Debug state
        if hasattr(self, '_last_state') and self._last_state != self.state:
            print(f"State changed from {getattr(self, '_last_state', 'None')} to {self.state}")
            self._last_state = self.state
        elif not hasattr(self, '_last_state'):
            self._last_state = self.state
            
        if self.state == "browser":
            self.screen.fill((10, 30, 10))  # Dark green background
            self.server_browser.draw()
        elif self.state == "loading":
            self._draw_loading_screen()
        else:
            # Clear game surface
            self.renderer.clear()
            
            # Draw game world to game surface
            if self.game_state.current_level:
                # Check if we're on a GMAP by looking at the level name
                current_level_name = self.game_state.current_level.name
                is_gmap = '-' in current_level_name and current_level_name.count('-') == 1
                
                if is_gmap:
                    # For GMAP segments, always try to draw adjacent levels
                    try:
                        # Parse the base gmap name from the segment name
                        base_name = current_level_name.split('-')[0]
                        gmap_name = f"{base_name}.gmap"
                        
                        # Draw multiple levels seamlessly using level map
                        # Debug output (reduced frequency)
                        if not hasattr(self, '_last_render_debug') or time.time() - self._last_render_debug > 2:
                            print(f"[GMAP RENDER] Current level: {self.game_state.current_level.name if self.game_state.current_level else 'None'}")
                            print(f"[GMAP RENDER] Adjacency map has {len(self.gmap_handler.level_adjacency)} levels")
                            print(f"[GMAP RENDER] Current level adjacency: {self.gmap_handler.level_adjacency.get(self.game_state.current_level.name, {}) if self.game_state.current_level else {}}")
                            self._last_render_debug = time.time()
                        self.renderer.draw_gmap_levels(
                            self.game_state.current_level,
                            self.gmap_handler,
                            gmap_name,
                            self.game_state.opened_chests,
                            self.game_state.item_manager.respawn_timers
                        )
                    except Exception as e:
                        # Fallback to single level
                        print(f"[GMAP RENDER] Exception in draw_gmap_levels: {e}")
                        import traceback
                        traceback.print_exc()
                        self.renderer.draw_level(
                            self.game_state.current_level,
                            self.game_state.opened_chests,
                            self.game_state.item_manager.respawn_timers
                        )
                else:
                    # Draw single level
                    self.renderer.draw_level(
                        self.game_state.current_level,
                        self.game_state.opened_chests,
                        self.game_state.item_manager.respawn_timers
                    )
                
            # Draw items
            self.renderer.draw_items(self.game_state.item_manager.dropped_items)
            
            # Draw thrown bushes
            self.renderer.draw_thrown_bushes(self.game_state.bush_handler)
            
            # Get GMAP coordinates for player rendering
            gmaplevelx = gmaplevely = None
            current_level = self.game_state.current_level
            if current_level and '-' in current_level.name and current_level.name.endswith('.nw'):
                try:
                    segment_code = current_level.name.split('-')[1].replace('.nw', '')
                    if len(segment_code) >= 2:
                        col_char = segment_code[0]
                        row_str = segment_code[1:]
                        gmaplevelx = ord(col_char.lower()) - ord('a')
                        gmaplevely = int(row_str)
                except:
                    pass
            
            # Draw players
            for player in self.game_state.players.values():
                gani, frame = self.animation_manager.update_player_animation(player.id)
                self.renderer.draw_player(player, frame, gani, "", False, gmaplevelx, gmaplevely)
                
            # Draw local player
            if self.game_state.local_player:
                gani, frame = self.animation_manager.update_player_animation(-1)
                carry_sprite = "bush" if self.game_state.bush_handler.carrying_bush else ""
                
                # Default to idle if no gani
                if not gani:
                    gani = self.game_state.local_player.gani or "idle"
                
                self.renderer.draw_player(
                    self.game_state.local_player, 
                    frame, 
                    gani,
                    carry_sprite,
                    is_local=True,
                    gmaplevelx=gmaplevelx,
                    gmaplevely=gmaplevely
                )
                
            # Draw collision debug
            if self.renderer.debug_collision:
                self.renderer.draw_collision_debug(self.game_state.current_level, self.game_state.local_player)
                
            # Scale and center game surface to screen
            # Calculate scale to fit window while maintaining aspect ratio
            scale_x = self.window_width / SCREEN_WIDTH
            scale_y = self.window_height / SCREEN_HEIGHT
            scale = min(scale_x, scale_y)
            
            # Calculate centered position
            scaled_width = int(SCREEN_WIDTH * scale)
            scaled_height = int(SCREEN_HEIGHT * scale)
            x_offset = (self.window_width - scaled_width) // 2
            y_offset = (self.window_height - scaled_height) // 2
            
            # Clear screen and draw scaled game
            self.screen.fill((0, 0, 0))  # Black borders
            scaled_surface = pygame.transform.scale(self.game_surface, (scaled_width, scaled_height))
            self.screen.blit(scaled_surface, (x_offset, y_offset))
            
            # Draw UI on top (full screen)
            if self.game_state.local_player:
                self.ui_manager.draw_status_bar(self.game_state.local_player)
                
            self.ui_manager.draw_messages()
            self.ui_manager.draw_chat_history()
            
            if self.input_manager.chat_mode:
                self.ui_manager.draw_chat_input(self.input_manager.chat_buffer)
                
            # Draw warp dialog if in warp mode
            if self.input_manager.warp_mode:
                # Get available levels
                levels = []
                if hasattr(self.client, 'level_manager') and self.client.level_manager:
                    levels.extend(self.client.level_manager.levels.keys())
                if hasattr(self.client, 'levels'):
                    levels.extend(self.client.levels.keys())
                levels = sorted(set(levels))
                
                self.ui_manager.draw_warp_dialog(self.input_manager.warp_input, levels)
                
            self.ui_manager.draw_debug_info(self.renderer.debug_tiles)
            self.ui_manager.draw_help_text(self.input_manager.chat_mode)
            
            # Draw minimap if enabled
            if self.show_minimap and self.game_state.local_player and self.game_state.current_level:
                # Prepare gmap info if in a gmap
                gmap_info = None
                
                # Use gmap handler info if available
                if self.gmap_handler.current_gmap:
                    # Parse current level to get segment coordinates
                    seg_x = 0
                    seg_y = 0
                    if self.game_state.current_level:
                        segment_info = self.gmap_handler.parse_segment_name(self.game_state.current_level.name)
                        if segment_info:
                            base_name, seg_x, seg_y = segment_info
                    
                    gmap_info = {
                        'gmaplevelx': seg_x,
                        'gmaplevely': seg_y,
                        'gmap_width': self.gmap_handler.gmap_width,
                        'gmap_height': self.gmap_handler.gmap_height
                    }
                # Fall back to player properties if available
                elif hasattr(self.game_state.local_player, 'gmaplevelx') and self.game_state.local_player.gmaplevelx is not None:
                    gmap_info = {
                        'gmaplevelx': self.game_state.local_player.gmaplevelx,
                        'gmaplevely': self.game_state.local_player.gmaplevely,
                        'gmap_width': self.game_state.gmap_width,
                        'gmap_height': self.game_state.gmap_height
                    }
                
                self.ui_manager.draw_minimap(
                    self.game_state.current_level.name,
                    self.game_state.local_player.x,
                    self.game_state.local_player.y,
                    self.game_state.players,
                    gmap_info
                )
            
        pygame.display.flip()
        
    def _play_gani_frame_sounds(self, gani_name: str, frame: int):
        """Play sounds for a specific GANI frame
        
        Args:
            gani_name: Name of the GANI animation
            frame: Current frame number
        """
        gani = self.gani_manager.load_gani(gani_name)
        if not gani or frame >= len(gani.animation_frames):
            return
            
        frame_data = gani.animation_frames[frame]
        # Check if this frame has a sound (stored as tuple: filename, volume, channel)
        if frame_data.sound:
            sound_file, volume, channel = frame_data.sound
            if sound_file:
                self.audio_manager.play_gani_sound(sound_file, volume, channel)
    
    def _request_adjacent_gmap_levels(self, level_name: str):
        """Request adjacent GMAP levels for seamless rendering
        
        Args:
            level_name: Current GMAP segment name (e.g., 'zlttp-d8.nw')
        """
        try:
            # Parse current segment position
            base_name = level_name.split('-')[0]
            segment_code = level_name.split('-')[1].replace('.nw', '')
            
            if len(segment_code) >= 2:
                col_char = segment_code[0]
                row_str = segment_code[1:]
                
                current_col = ord(col_char.lower()) - ord('a')
                current_row = int(row_str)
                
                # Request 3x3 grid of adjacent levels
                for dy in range(-1, 2):
                    for dx in range(-1, 2):
                        if dx == 0 and dy == 0:
                            continue  # Skip current level
                            
                        seg_col = current_col + dx
                        seg_row = current_row + dy
                        
                        if seg_col >= 0 and seg_row >= 0:
                            seg_col_char = chr(ord('a') + seg_col)
                            seg_name = f"{base_name}-{seg_col_char}{seg_row}.nw"
                            
                            # Only request if we don't already have it
                            if seg_name not in self.client.level_manager.levels:
                                print(f"[GMAP] Requesting adjacent level: {seg_name}")
                                self.client.request_file(seg_name)
                                
        except Exception as e:
            print(f"[GMAP] Error requesting adjacent levels: {e}")
        
    def run(self):
        """Main game loop"""
        self.running = True
        
        # Handle auto-login if provided
        if self.auto_login_info and self.state == "browser":
            self.state = "loading"
            self.loading_start_time = time.time()
            self.loading_message = "Auto-connecting..."
            
            # Start connection in background
            self.connection_manager.connect_async(
                self.auto_login_info['server'],
                self.auto_login_info['port'],
                self.auto_login_info['username'],
                self.auto_login_info['password'],
                self.auto_login_info['version']
            )
        
        while self.running:
            # Handle events
            for event in pygame.event.get():
                # Always check for quit event
                if event.type == pygame.QUIT:
                    self.running = False
                    break
                    
                if self.state == "browser":
                    action = self.server_browser.handle_event(event)
                    if action == 'connect':
                        server_info = self.server_browser.get_selected_server()
                        if server_info:
                            host, port, version = server_info
                            # Switch to loading state
                            self.state = "loading"
                            self.loading_start_time = time.time()
                            self.loading_message = f"Connecting to {host}:{port} with version {version}"
                            
                            # Start connection
                            self.connection_manager.connect_async(
                                host, port,
                                self.server_browser.username,
                                self.server_browser.password,
                                version
                            )
                    elif action == 'quit':
                        self.running = False
                elif self.state == "loading":
                    # Allow ESC to cancel loading
                    if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                        self.running = False
                        break
                else:
                    # Handle input for game
                    
                    # Direct ESC key handling
                    if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                        self.running = False
                        break
                        
                    self.input_manager.handle_event(event)
                    
                    # Special handling for key release on grab
                    if event.type == pygame.KEYUP and event.key == pygame.K_a:
                        if self.game_state.is_grabbing and not self.game_state.bush_handler.carrying_bush:
                            # Try to pick up bush
                            bush_pos = self.game_state.bush_handler.try_pickup_bush(
                                self.game_state.current_level,
                                self.tile_defs,
                                self.game_state.local_player.x,
                                self.game_state.local_player.y,
                                self.game_state.last_direction
                            )
                            
                            if bush_pos:
                                # Remove bush from level
                                tile_x, tile_y = bush_pos
                                for dx in range(2):
                                    for dy in range(2):
                                        self.game_state.current_level.set_tile(
                                            tile_x + dx, tile_y + dy, 0
                                        )
                                        
                                # Add respawn timer
                                self.game_state.item_manager.add_respawn_timer(
                                    tile_x, tile_y, ClassicConstants.BUSH_RESPAWN_TIME
                                )
                                
                                # Play sound and set animation
                                self.audio_manager.play_classic_sound('bush_lift')
                                self.client.set_gani("lift")
                                self.animation_manager.set_player_animation(-1, "lift")
                                self.client.set_carry_sprite("bush")
                                
                        self.game_state.is_grabbing = False
                        self.game_state.grabbed_tile_pos = None
                        
                        if not self.game_state.bush_handler.carrying_bush:
                            self.client.set_gani("idle")
                            self.animation_manager.set_player_animation(-1, "idle")
                            
            # Update
            self.update()
            
            # Draw
            self.draw()
            
            # Cap FPS
            self.clock.tick(60)
            
        # Cleanup
        self.connection_manager.disconnect()
        pygame.quit()


def main():
    """Entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Classic Reborn Client')
    parser.add_argument('username', nargs='?', help='Username for auto-login')
    parser.add_argument('password', nargs='?', help='Password for auto-login')
    parser.add_argument('--server', '-s', default='localhost', help='Server hostname (default: localhost)')
    parser.add_argument('--port', '-p', type=int, default=14900, help='Server port (default: 14900)')
    parser.add_argument('--version', '-v', default='2.1', help='Client version (default: 2.1, use 6.034 for hastur)')
    
    args = parser.parse_args()
    
    game = ClassicRebornClient()
    
    # If username and password provided, auto-login
    if args.username and args.password:
        game.auto_login_info = {
            'username': args.username,
            'password': args.password,
            'server': args.server,
            'port': args.port,
            'version': args.version
        }
    
    game.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())