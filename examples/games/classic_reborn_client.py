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
        self.game_state.set_level(level)
        self.ui_manager.add_message(f"Entered {level.name}", GREEN)
        
        # Transition to game state
        if self.state == "loading":
            self.state = "game"
            self.loading_message = "Ready!"
            
            # Update camera to center on player
            if self.game_state.local_player:
                self.renderer.update_camera(
                    self.game_state.local_player.x,
                    self.game_state.local_player.y
                )
            
    def _setup_event_handlers(self):
        """Setup network event handlers"""
        from pyreborn.events import EventType
        events = self.client.events
        events.subscribe(EventType.PLAYER_ADDED, self._on_player_added)
        events.subscribe(EventType.PLAYER_LEFT, self._on_player_left)
        events.subscribe(EventType.OTHER_PLAYER_UPDATE, self._on_player_moved)
        events.subscribe(EventType.PLAYER_PROPS_UPDATE, self._on_player_props_update)
        events.subscribe(EventType.CHAT_MESSAGE, self._on_player_chat)
            
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
                # Filter out direction updates for local player
                filtered_kwargs = {k: v for k, v in kwargs.items() if k != 'direction'}
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
            
    def handle_movement(self):
        """Process movement input"""
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
        
        new_x = self.game_state.local_player.x + dx * speed
        new_y = self.game_state.local_player.y + dy * speed
        
        # Check collision
        if self.physics.can_move_to(new_x, new_y, self.game_state.current_level,
                                   self.game_state.bush_handler.carrying_bush,
                                   self.game_state.local_player.direction):
            # Move player
            self.client.move_to(new_x, new_y, direction)
            self.game_state.local_player.x = new_x
            self.game_state.local_player.y = new_y
            self.game_state.local_player.direction = direction
            self.game_state.last_move_time = time.time()
            self.game_state.last_direction = direction
            
            
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
                self.renderer.update_camera(
                    self.game_state.local_player.x,
                    self.game_state.local_player.y
                )
                
            # Handle movement
            self.handle_movement()
            
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
                self.renderer.draw_level(
                    self.game_state.current_level,
                    self.game_state.opened_chests,
                    self.game_state.item_manager.respawn_timers
                )
                
            # Draw items
            self.renderer.draw_items(self.game_state.item_manager.dropped_items)
            
            # Draw thrown bushes
            self.renderer.draw_thrown_bushes(self.game_state.bush_handler)
            
            # Draw players
            for player in self.game_state.players.values():
                gani, frame = self.animation_manager.update_player_animation(player.id)
                self.renderer.draw_player(player, frame, gani)
                
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
                    is_local=True
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
                
            self.ui_manager.draw_debug_info(self.renderer.debug_tiles)
            self.ui_manager.draw_help_text(self.input_manager.chat_mode)
            
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
                self.auto_login_info['password']
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
                            host, port = server_info
                            # Switch to loading state
                            self.state = "loading"
                            self.loading_start_time = time.time()
                            self.loading_message = f"Connecting to {host}:{port}"
                            
                            # Start connection
                            self.connection_manager.connect_async(
                                host, port,
                                self.server_browser.username,
                                self.server_browser.password
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
    
    args = parser.parse_args()
    
    game = ClassicRebornClient()
    
    # If username and password provided, auto-login
    if args.username and args.password:
        game.auto_login_info = {
            'username': args.username,
            'password': args.password,
            'server': args.server,
            'port': args.port
        }
    
    game.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())