#!/usr/bin/env python3
"""
Pygame Client - A visual client for PyReborn using Pygame
Arrow keys to move, Tab to chat, Escape to quit
"""

import sys
import os
import pygame
import threading
import time
import queue
from pyreborn import RebornClient
from pyreborn.protocol.enums import Direction
from pyreborn.events import EventType
from gani_parser import GaniManager
from tile_defs import TileDefs
from bush_handler import BushHandler

# Constants
SCREEN_WIDTH = 1024
SCREEN_HEIGHT = 768
TILE_SIZE = 16
VIEWPORT_TILES_X = SCREEN_WIDTH // TILE_SIZE
VIEWPORT_TILES_Y = SCREEN_HEIGHT // TILE_SIZE

# Colors
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GREEN = (0, 255, 0)
RED = (255, 0, 0)
BLUE = (0, 0, 255)
GRAY = (128, 128, 128)
DARK_GREEN = (0, 128, 0)

class PygameClient:
    def __init__(self):
        # Initialize Pygame
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption("PyReborn Pygame Client")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 24)
        self.small_font = pygame.font.Font(None, 16)
        
        # Load tileset
        self.tileset = None
        self.tileset_cache = {}
        try:
            tileset_path = os.path.join(os.path.dirname(__file__), "assets", "pics1.png")
            if os.path.exists(tileset_path):
                self.tileset = pygame.image.load(tileset_path).convert_alpha()
                print(f"Loaded tileset from {tileset_path}")
            else:
                print(f"Tileset not found at {tileset_path}")
        except Exception as e:
            print(f"Failed to load tileset: {e}")
            
        # Initialize GANI manager
        self.gani_manager = GaniManager(os.path.dirname(__file__))
        
        # Initialize tile definitions for collision detection
        self.tile_defs = TileDefs()
        
        # Initialize bush handler
        self.bush_handler = BushHandler()
        
        # Sound system
        pygame.mixer.init()
        self.sound_cache = {}
        self.sound_channels = {i: pygame.mixer.Channel(i) for i in range(8)}  # 8 channels
        
        # Preload common GANIs
        for gani_name in ['idle', 'walk', 'sword', 'grab', 'pull']:
            gani = self.gani_manager.load_gani(gani_name)
            if gani:
                print(f"Loaded GANI: {gani_name}")
                
        # Debug options
        self.debug_updates = False  # Set to True to see update frequency
        self.debug_tiles = False  # Set to True to see tile info under cursor
        
        # Keep sprite cache for performance
        self.sprite_cache = {}
        
        # Client
        self.client = RebornClient("localhost", 14900)
        self.connected = False
        self.running = True
        
        # Camera
        self.camera_x = 0
        self.camera_y = 0
        
        # Input
        self.keys_pressed = set()
        self.chat_mode = False
        self.chat_buffer = ""
        
        # Game state
        self.players = {}
        self.player_animations = {}  # Track animation states for other players
        self.player_predictions = {}  # Track predicted positions for smooth movement
        self.current_level = None
        self.event_queue = queue.Queue()
        
        # Movement
        self.move_speed = 0.5  # Half tile per move
        self.last_move_time = 0
        self.move_cooldown = 0.02  # 20ms between moves (smoother movement)
        self.is_moving = False
        self.last_direction = Direction.DOWN
        
        # Animation
        self.animation_time = 0
        self.animation_frame = 0
        self.animation_speed = 0.02  # Time between frames in seconds (2.5x faster)
        self.sword_animating = False
        self.sword_start_time = 0
        self.grabbing = False
        
        # Setup event handlers
        self._setup_events()
        
    def _setup_events(self):
        """Setup PyReborn event handlers"""
        self.client.events.subscribe(EventType.PLAYER_ADDED, self._on_player_added)
        self.client.events.subscribe(EventType.PLAYER_REMOVED, self._on_player_left)
        self.client.events.subscribe(EventType.OTHER_PLAYER_UPDATE, self._on_player_moved)
        self.client.events.subscribe(EventType.PLAYER_PROPS_UPDATE, self._on_player_props_update)
        self.client.events.subscribe(EventType.CHAT_MESSAGE, self._on_player_chat)
        self.client.events.subscribe(EventType.LEVEL_ENTERED, self._on_level_changed)
        
    def _on_player_added(self, **kwargs):
        """Handle player added (when we receive info about existing players)"""
        self.event_queue.put(('player_added', kwargs))
        
    def _on_player_left(self, **kwargs):
        """Handle player leave"""
        self.event_queue.put(('player_left', kwargs))
        
    def _on_player_moved(self, **kwargs):
        """Handle player movement"""
        self.event_queue.put(('player_moved', kwargs))
        
    def _on_player_props_update(self, **kwargs):
        """Handle player property updates (including animations)"""
        self.event_queue.put(('player_props_update', kwargs))
        
    def _on_player_chat(self, **kwargs):
        """Handle player chat"""
        self.event_queue.put(('player_chat', kwargs))
        
    def _on_level_changed(self, **kwargs):
        """Handle level change"""
        self.event_queue.put(('level_changed', kwargs))
        
    def connect_and_login(self, username, password):
        """Connect to server and login"""
        if not self.client.connect():
            return False
            
        if not self.client.login(username, password):
            self.client.disconnect()
            return False
            
        self.connected = True
        self.client.set_nickname("PygamePlayer")
        
        # Reduce packet send rate for smoother gameplay
        self.client.set_packet_send_rate(0.02)  # 20ms between packets
        
        # Set initial idle animation
        self.client.set_gani("idle")
        
        # Center camera on player
        self.camera_x = self.client.local_player.x - VIEWPORT_TILES_X // 2
        self.camera_y = self.client.local_player.y - VIEWPORT_TILES_Y // 2
        
        return True
        
    def handle_events(self):
        """Handle pygame events"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                
            elif event.type == pygame.KEYDOWN:
                if self.chat_mode:
                    # Chat input
                    if event.key == pygame.K_RETURN:
                        if self.chat_buffer:
                            self.client.set_chat(self.chat_buffer)
                            self.chat_buffer = ""
                        self.chat_mode = False
                    elif event.key == pygame.K_ESCAPE:
                        self.chat_buffer = ""
                        self.chat_mode = False
                    elif event.key == pygame.K_BACKSPACE:
                        self.chat_buffer = self.chat_buffer[:-1]
                    else:
                        if event.unicode and len(self.chat_buffer) < 200:
                            self.chat_buffer += event.unicode
                else:
                    # Normal input
                    if event.key == pygame.K_TAB:
                        self.chat_mode = True
                    elif event.key == pygame.K_ESCAPE:
                        self.running = False
                    elif event.key == pygame.K_SPACE or event.key == pygame.K_s:
                        # Swing sword
                        if not self.sword_animating:
                            self.client.set_gani("sword")
                            self.animation_frame = 0
                            self.sword_animating = True
                            self.sword_start_time = time.time()
                            # Play sound for first frame
                            self.play_gani_sounds('sword', 0)
                    elif event.key == pygame.K_a:
                        # Grab/pull/throw
                        if self.bush_handler.carrying_bush:
                            # Throw the bush
                            self.bush_handler.throw_bush(
                                self.client.local_player.x,
                                self.client.local_player.y,
                                self.last_direction
                            )
                            self.client.set_gani("sword")  # Use sword animation for throwing
                            self.animation_frame = 0
                            # Clear carry sprite
                            self.set_carry_sprite("")
                        else:
                            # Try to grab
                            self.grabbing = True
                            self.client.set_gani("grab")
                            self.animation_frame = 0
                    elif event.key == pygame.K_F3:
                        # Toggle tile debug
                        self.debug_tiles = not self.debug_tiles
                        print(f"Tile debug: {'ON' if self.debug_tiles else 'OFF'}")
                    else:
                        self.keys_pressed.add(event.key)
                        
            elif event.type == pygame.KEYUP:
                if event.key == pygame.K_a:
                    if self.grabbing and not self.bush_handler.carrying_bush:
                        # Try to pick up bush when releasing grab
                        bush_pos = self.bush_handler.try_pickup_bush(
                            self.current_level,
                            self.client.local_player.x,
                            self.client.local_player.y,
                            self.last_direction
                        )
                        if bush_pos:
                            # Replace bush tiles with new tiles
                            tile_x, tile_y = bush_pos
                            self.replace_bush_tiles(tile_x, tile_y)
                            self.client.set_gani("lift")  # Lift animation
                            self.animation_frame = 0
                            # Notify server we're carrying a bush
                            self.set_carry_sprite("bush")
                    self.grabbing = False
                    if not self.bush_handler.carrying_bush:
                        self.client.set_gani("idle")
                self.keys_pressed.discard(event.key)
                
    def process_game_events(self):
        """Process events from the game"""
        while not self.event_queue.empty():
            try:
                event_type, event_data = self.event_queue.get_nowait()
                
                if event_type == 'player_added':
                    player = event_data.get('player')
                    if player and player.id != self.client.local_player.id:
                        self.players[player.id] = player
                        # Initialize animation state
                        self.player_animations[player.id] = {
                            'gani': player.gani or 'idle',
                            'frame': 0,
                            'last_update': time.time()
                        }
                        # Initialize prediction state
                        current_time = time.time()
                        self.player_predictions[player.id] = {
                            'start_x': player.x,
                            'start_y': player.y,
                            'target_x': player.x,
                            'target_y': player.y,
                            'current_x': player.x,
                            'current_y': player.y,
                            'start_time': current_time,
                            'interpolation_duration': 0.1,
                            'moving': False
                        }
                    
                elif event_type == 'player_left':
                    player = event_data['player']
                    self.players.pop(player.id, None)
                    self.player_animations.pop(player.id, None)
                    self.player_predictions.pop(player.id, None)
                    
                elif event_type == 'player_moved':
                    player = event_data.get('player')
                    if player and player.id in self.players:
                        old_player = self.players.get(player.id)
                        self.players[player.id] = player
                        
                        # Track movement for interpolation
                        current_time = time.time()
                        
                        if player.id not in self.player_predictions:
                            self.player_predictions[player.id] = {
                                'start_x': player.x,
                                'start_y': player.y,
                                'target_x': player.x,
                                'target_y': player.y,
                                'current_x': player.x,
                                'current_y': player.y,
                                'start_time': current_time,
                                'interpolation_duration': 0.1  # 100ms interpolation
                            }
                        
                        pred = self.player_predictions[player.id]
                        
                        # Start new interpolation from current position to new target
                        pred['start_x'] = pred['current_x']
                        pred['start_y'] = pred['current_y']
                        pred['target_x'] = player.x
                        pred['target_y'] = player.y
                        pred['start_time'] = current_time
                        
                        # Check if player is moving
                        dx = pred['target_x'] - pred['start_x']
                        dy = pred['target_y'] - pred['start_y']
                        pred['moving'] = abs(dx) > 0.01 or abs(dy) > 0.01
                        
                        # Ensure animation state exists
                        if player.id not in self.player_animations:
                            self.player_animations[player.id] = {
                                'gani': player.gani or 'idle',
                                'frame': 0,
                                'last_update': time.time()
                            }
                        
                elif event_type == 'player_props_update':
                    player = event_data.get('player')
                    if player:
                        # Update player data
                        self.players[player.id] = player
                        
                        # Track animation changes
                        if player.id not in self.player_animations:
                            self.player_animations[player.id] = {
                                'gani': player.gani or 'idle',
                                'frame': 0,
                                'last_update': time.time()
                            }
                        elif self.player_animations[player.id].get('gani') != player.gani:
                            # Animation changed
                            old_gani = self.player_animations[player.id].get('gani')
                            self.player_animations[player.id]['gani'] = player.gani
                            
                            # Only reset frame if it's a significant change
                            # Don't reset if going from walk to idle or vice versa (smooth transition)
                            if not ((old_gani == 'walk' and player.gani == 'idle') or 
                                    (old_gani == 'idle' and player.gani == 'walk')):
                                self.player_animations[player.id]['frame'] = 0
                        
                elif event_type == 'level_changed':
                    self.current_level = self.client.level_manager.get_current_level()
                    # Clear player list - will be repopulated by player events
                    self.players = {}
                    self.player_animations = {}
                    self.player_predictions = {}
                            
            except queue.Empty:
                break
                
    def handle_movement(self):
        """Handle player movement based on input
        
        Note: move_to() sets absolute position, so we move in small increments
        to create smooth movement rather than teleporting.
        """
        if self.chat_mode or self.sword_animating:
            return
            
        current_time = time.time()
        if current_time - self.last_move_time < self.move_cooldown:
            return
            
        dx, dy = 0, 0
        direction = None
        
        if pygame.K_LEFT in self.keys_pressed:
            dx -= self.move_speed
            direction = Direction.LEFT
        if pygame.K_RIGHT in self.keys_pressed:
            dx += self.move_speed
            direction = Direction.RIGHT
        if pygame.K_UP in self.keys_pressed:
            dy -= self.move_speed
            direction = Direction.UP
        if pygame.K_DOWN in self.keys_pressed:
            dy += self.move_speed
            direction = Direction.DOWN
            
        # Check for pulling (grabbing + opposite direction)
        if self.grabbing and direction is not None:
            opposite_direction = {
                Direction.LEFT: Direction.RIGHT,
                Direction.RIGHT: Direction.LEFT,
                Direction.UP: Direction.DOWN,
                Direction.DOWN: Direction.UP
            }.get(self.last_direction)
            
            if direction == opposite_direction:
                self.client.set_gani("pull")
            
        if dx != 0 or dy != 0:
            # Calculate new position based on small increments
            new_x = self.client.local_player.x + dx
            new_y = self.client.local_player.y + dy
            
            # Check collision before moving
            if self.can_move_to(new_x, new_y):
                # Determine final direction (prioritize last pressed)
                if direction is None:
                    direction = self.last_direction
                
                self.client.move_to(new_x, new_y, direction)
                self.last_move_time = current_time
                self.last_direction = direction
            else:
                # Still update direction even if blocked
                if direction is not None:
                    self.last_direction = direction
                    # Update direction by sending a movement packet with current position
                    self.client.move_to(self.client.local_player.x, self.client.local_player.y, direction)
            
            # Set walking animation if not already moving
            if not self.is_moving:
                self.client.set_gani("walk")
                self.is_moving = True
        else:
            # Set idle animation when stopped
            if self.is_moving:
                self.client.set_gani("idle")
                self.is_moving = False
                self.animation_frame = 0  # Reset animation frame
                
        # Always update camera to follow player
        self.camera_x = self.client.local_player.x - VIEWPORT_TILES_X // 2
        self.camera_y = self.client.local_player.y - VIEWPORT_TILES_Y // 2
        
    def can_move_to(self, x: float, y: float) -> bool:
        """Check if player can move to a position (collision detection)
        
        Args:
            x: Target X position
            y: Target Y position
            
        Returns:
            True if movement is allowed, False if blocked
        """
        if not self.current_level:
            return True
            
        # Check bounds
        if x < 0 or y < 0 or x >= 64 or y >= 64:
            return False
            
        # Get player's bounding box (player is roughly 1x1.5 tiles)
        # Check multiple points for better collision
        check_points = [
            (x, y),                    # Top-left
            (x + 0.9, y),             # Top-right
            (x, y + 1.4),             # Bottom-left
            (x + 0.9, y + 1.4),       # Bottom-right
            (x + 0.45, y + 0.7)       # Center
        ]
        
        for check_x, check_y in check_points:
            # Get tile at this position
            tile_x = int(check_x)
            tile_y = int(check_y)
            
            if tile_x < 0 or tile_y < 0 or tile_x >= 64 or tile_y >= 64:
                return False
                
            tile_id = self.current_level.get_board_tile_id(tile_x, tile_y)
            
            # Check if tile is blocking
            if self.tile_defs.is_blocking(tile_id):
                return False
                
        return True
        
    def replace_bush_tiles(self, tile_x: int, tile_y: int):
        """Replace a bush (2x2 tiles) with the picked-up tiles"""
        if not self.current_level:
            return
            
        # Get the current tile to determine which bush tile it is
        current_tile = self.current_level.get_board_tile_id(tile_x, tile_y)
        
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
        # Note: We're modifying the local display only - server would handle the actual change
        replacement_tiles = [
            (base_x, base_y, 677),      # Top-left
            (base_x + 1, base_y, 678),  # Top-right
            (base_x, base_y + 1, 693),  # Bottom-left
            (base_x + 1, base_y + 1, 694)  # Bottom-right
        ]
        
        # Update the tile data in memory for display
        tiles_2d = self.current_level.get_board_tiles_2d()
        for x, y, new_tile_id in replacement_tiles:
            if 0 <= x < 64 and 0 <= y < 64:
                tiles_2d[y][x] = new_tile_id
                # Also update the flat array
                idx = y * 64 + x
                if hasattr(self.current_level, 'board_tiles_64x64'):
                    self.current_level.board_tiles_64x64[idx] = new_tile_id
                    
    def set_carry_sprite(self, sprite_name: str):
        """Set the carry sprite (what player is holding)"""
        from pyreborn.protocol.enums import PlayerProp
        from pyreborn.protocol.packets import PlayerPropsPacket
        
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_CARRYSPRITE, sprite_name)
        self.client._send_packet(packet)
        
    def get_tile_surface(self, tile_id):
        """Get a surface for a specific tile ID from the tileset
        
        Uses the Reborn tile coordinate conversion algorithm:
        tx = (tile_id // 512) * 16 + (tile_id % 16)
        ty = (tile_id // 16) % 32
        """
        if tile_id in self.tileset_cache:
            return self.tileset_cache[tile_id]
            
        if self.tileset is None:
            return None
            
        # Apply Reborn's tile coordinate conversion
        tx = (tile_id // 512) * 16 + (tile_id % 16)
        ty = (tile_id // 16) % 32
        
        # Each tile is 16x16 pixels
        rect = pygame.Rect(tx * TILE_SIZE, ty * TILE_SIZE, TILE_SIZE, TILE_SIZE)
        
        # Check if rect is within tileset bounds
        if (rect.right <= self.tileset.get_width() and 
            rect.bottom <= self.tileset.get_height()):
            tile_surface = self.tileset.subsurface(rect).copy()
            self.tileset_cache[tile_id] = tile_surface
            return tile_surface
            
        return None
        
    def get_player_sprites_with_positions(self, direction, gani="idle", frame=0):
        """Get sprites and their positions for a player based on GANI data
        
        Returns list of (surface, x_offset, y_offset) tuples
        """
        # Map directions
        dir_map = {
            Direction.UP: 'up',
            Direction.LEFT: 'left',
            Direction.DOWN: 'down',
            Direction.RIGHT: 'right'
        }
        dir_name = dir_map.get(direction, 'down')
        
        # Load the GANI file
        gani_file = self.gani_manager.load_gani(gani)
        if not gani_file:
            return []
            
        # Get sprite placements for this frame and direction
        # For single-frame animations like idle, always use frame 0
        actual_frame = 0 if gani == "idle" else frame
        sprite_placements = gani_file.get_frame_sprites(actual_frame, dir_name)
        
        
        # Convert sprite IDs to surfaces with positions
        result = []
        for sprite_id, x_offset, y_offset in sprite_placements:
            # Get the sprite surface
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
    
    def get_player_sprites(self, direction, gani="idle", frame=0):
        """Get body, head, and sword sprites for a player based on direction and animation
        
        Returns tuple of (body_surface, head_surface, sword_surface)
        """
        # Map directions to sprite IDs
        dir_map = {
            Direction.UP: 0,
            Direction.LEFT: 1,
            Direction.DOWN: 2,
            Direction.RIGHT: 3
        }
        
        dir_idx = dir_map.get(direction, 2)  # Default to down
        
        # Load the appropriate GANI
        gani_file = self.gani_manager.load_gani(gani)
        if not gani_file:
            return None, None, None
        
        # Calculate sprite IDs based on animation and frame
        body_sprite_id = None
        head_sprite_id = None
        sword_sprite_id = None
        
        if gani == "idle":
            # Idle sprites
            body_sprite_id = 200 + dir_idx  # 200=up, 201=left, 202=down, 203=right
            head_sprite_id = 100 + dir_idx  # 100=up, 101=left, 102=down, 103=right
            
        elif gani == "walk":
            # Walking animation (5 frames)
            walk_frame = frame % 5
            body_sprite_id = 204 + (walk_frame * 4) + dir_idx
            head_sprite_id = 100 + dir_idx  # Head stays same
            
        elif gani == "sword":
            # Sword animation (4 frames)
            sword_frame = frame % 4
            body_sprite_id = 224 + (sword_frame * 4) + dir_idx
            head_sprite_id = 100 + dir_idx
            
            # Get sword sprite from GANI data
            if direction == Direction.UP:
                sword_sprite_id = [22, 34, 33, 22][sword_frame]
            elif direction == Direction.DOWN:
                sword_sprite_id = [23, 20, 21, 23][sword_frame]
            elif direction == Direction.LEFT:
                sword_sprite_id = [35, 32, 30, 35][sword_frame]
            elif direction == Direction.RIGHT:
                sword_sprite_id = [27, 26, 25, 27][sword_frame]
                
        elif gani == "grab":
            # Grab animation
            body_sprite_id = 240 + dir_idx
            head_sprite_id = 100 + dir_idx
            
        elif gani == "pull":
            # Pull animation
            if direction == Direction.UP:
                pull_frame = frame % 3
                body_sprite_id = 252 + (pull_frame * 32)  # Special case for up
            else:
                body_sprite_id = 253 + (dir_idx - 1)  # 253=left, 254=down, 255=right
            head_sprite_id = 104 + dir_idx  # Special pulling heads
        
        # Get surfaces from GANI manager
        body_surface = None
        head_surface = None
        sword_surface = None
        
        if body_sprite_id is not None:
            cache_key = f"{gani}_body_{body_sprite_id}"
            if cache_key in self.sprite_cache:
                body_surface = self.sprite_cache[cache_key]
            else:
                body_surface = self.gani_manager.get_sprite_surface(gani, body_sprite_id)
                if body_surface:
                    self.sprite_cache[cache_key] = body_surface
        
        if head_sprite_id is not None:
            cache_key = f"{gani}_head_{head_sprite_id}"
            if cache_key in self.sprite_cache:
                head_surface = self.sprite_cache[cache_key]
            else:
                head_surface = self.gani_manager.get_sprite_surface(gani, head_sprite_id)
                if head_surface:
                    self.sprite_cache[cache_key] = head_surface
                    
        if sword_sprite_id is not None:
            cache_key = f"{gani}_sword_{sword_sprite_id}"
            if cache_key in self.sprite_cache:
                sword_surface = self.sprite_cache[cache_key]
            else:
                sword_surface = self.gani_manager.get_sprite_surface('sword', sword_sprite_id)
                if sword_surface:
                    self.sprite_cache[cache_key] = sword_surface
        
        return body_surface, head_surface, sword_surface
        
    def load_sound(self, filename):
        """Load a sound file into cache"""
        if filename in self.sound_cache:
            return self.sound_cache[filename]
            
        # Try different paths
        sound_paths = [
            os.path.join(os.path.dirname(__file__), "assets", "sounds", filename),
            os.path.join(os.path.dirname(__file__), "assets", "levels", "sounds", filename),
            os.path.join(os.path.dirname(__file__), "assets", filename),
        ]
        
        for path in sound_paths:
            if os.path.exists(path):
                try:
                    sound = pygame.mixer.Sound(path)
                    self.sound_cache[filename] = sound
                    return sound
                except Exception as e:
                    print(f"Failed to load sound {filename}: {e}")
                    
        return None
        
    def play_gani_sounds(self, gani_name, frame):
        """Play sounds for a specific GANI frame"""
        gani = self.gani_manager.load_gani(gani_name)
        if not gani or frame >= len(gani.animation_frames):
            return
            
        anim_frame = gani.animation_frames[frame]
        if anim_frame.sound:
            sound_file, volume, channel = anim_frame.sound
            sound = self.load_sound(sound_file)
            if sound and channel in self.sound_channels:
                sound.set_volume(min(1.0, volume))  # Cap at 1.0
                self.sound_channels[channel].play(sound)
            
    def draw_level(self):
        """Draw the current level"""
        if not self.current_level:
            return
            
        # Get tile data
        tiles_2d = self.current_level.get_board_tiles_2d()
        
        # Calculate visible range
        start_x = max(0, int(self.camera_x))
        start_y = max(0, int(self.camera_y))
        end_x = min(64, start_x + VIEWPORT_TILES_X + 1)
        end_y = min(64, start_y + VIEWPORT_TILES_Y + 1)
        
        # Draw tiles
        for y in range(start_y, end_y):
            for x in range(start_x, end_x):
                tile_id = tiles_2d[y][x]
                screen_x = (x - self.camera_x) * TILE_SIZE
                screen_y = (y - self.camera_y) * TILE_SIZE
                
                # Try to use tileset first
                tile_surface = self.get_tile_surface(tile_id)
                if tile_surface:
                    # Apply tint for special tiles
                    tile_type = self.tile_defs.get_tile_type(tile_id)
                    if tile_type != 0:  # Not a normal tile
                        tinted_surface = tile_surface.copy()
                        if self.tile_defs.is_water(tile_id):
                            # Blue tint for water
                            tinted_surface.fill((100, 100, 255, 100), special_flags=pygame.BLEND_MULT)
                        elif self.tile_defs.is_damaging(tile_id):
                            # Red tint for damaging tiles
                            tinted_surface.fill((255, 100, 100, 100), special_flags=pygame.BLEND_MULT)
                        elif self.tile_defs.is_blocking(tile_id):
                            # Slight dark tint for blocking
                            tinted_surface.fill((200, 200, 200, 255), special_flags=pygame.BLEND_MULT)
                        self.screen.blit(tinted_surface, (screen_x, screen_y))
                    else:
                        self.screen.blit(tile_surface, (screen_x, screen_y))
                else:
                    # Fallback to colored rectangles
                    if tile_id == 0:
                        color = DARK_GREEN  # Grass
                    elif tile_id < 100:
                        color = GREEN
                    elif tile_id < 500:
                        color = GRAY
                    else:
                        # Generate color from tile ID
                        r = (tile_id * 7) % 256
                        g = (tile_id * 13) % 256
                        b = (tile_id * 23) % 256
                        color = (r, g, b)
                        
                    pygame.draw.rect(self.screen, color, 
                                   (screen_x, screen_y, TILE_SIZE, TILE_SIZE))
                                   
    def draw_thrown_bushes(self):
        """Draw thrown bushes and explosions"""
        current_time = time.time()
        
        # Draw thrown bushes
        for bush in self.bush_handler.thrown_bushes:
            x, y = bush.get_position(current_time)
            screen_x = (x - self.camera_x) * TILE_SIZE
            screen_y = (y - self.camera_y) * TILE_SIZE
            
            # Draw a small bush sprite (using tile 2 for now)
            bush_surface = self.get_tile_surface(2)
            if bush_surface:
                # Make it smaller while flying
                small_bush = pygame.transform.scale(bush_surface, (TILE_SIZE//2, TILE_SIZE//2))
                self.screen.blit(small_bush, (screen_x + TILE_SIZE//4, screen_y + TILE_SIZE//4))
            else:
                # Fallback to green circle
                pygame.draw.circle(self.screen, (0, 150, 0), 
                                 (int(screen_x + TILE_SIZE/2), int(screen_y + TILE_SIZE/2)), 
                                 TILE_SIZE//3)
        
        # Draw explosions
        for exp_x, exp_y, exp_time in self.bush_handler.bush_explosions:
            age = current_time - exp_time
            if age < 0.5:  # 0.5 second explosion
                screen_x = (exp_x - self.camera_x) * TILE_SIZE
                screen_y = (exp_y - self.camera_y) * TILE_SIZE
                
                # Explosion effect - expanding circles
                radius = int(TILE_SIZE * (1 + age * 2))
                alpha = int(255 * (1 - age * 2))
                
                # Draw multiple circles for effect
                colors = [(255, 200, 0), (255, 150, 0), (200, 100, 0)]
                for i, color in enumerate(colors):
                    r = radius - i * 5
                    if r > 0:
                        # Create a surface for alpha blending
                        surf = pygame.Surface((r*2, r*2), pygame.SRCALPHA)
                        pygame.draw.circle(surf, (*color, alpha), (r, r), r)
                        self.screen.blit(surf, (screen_x + TILE_SIZE/2 - r, screen_y + TILE_SIZE/2 - r))
                               
    def draw_players(self):
        """Draw all players"""
        # Draw other players
        for player_id, player in self.players.items():
            if player_id == self.client.local_player.id:
                continue  # Draw local player last
                
            # Use interpolated position for smoother movement
            display_x = player.x
            display_y = player.y
            
            # Only interpolate movement animations, not action animations
            should_interpolate = player.gani in ['walk', 'idle', None, '']
            
            if should_interpolate and player.id in self.player_predictions:
                pred = self.player_predictions[player.id]
                current_time = time.time()
                elapsed = current_time - pred['start_time']
                
                # Calculate interpolation progress (0 to 1)
                progress = min(1.0, elapsed / pred['interpolation_duration'])
                
                # Smooth interpolation using ease-in-out
                smooth_progress = progress * progress * (3.0 - 2.0 * progress)
                
                # Interpolate position
                pred['current_x'] = pred['start_x'] + (pred['target_x'] - pred['start_x']) * smooth_progress
                pred['current_y'] = pred['start_y'] + (pred['target_y'] - pred['start_y']) * smooth_progress
                
                display_x = pred['current_x']
                display_y = pred['current_y']
                
            screen_x = (display_x - self.camera_x) * TILE_SIZE
            screen_y = (display_y - self.camera_y) * TILE_SIZE
            
            # Get player sprites with GANI positions
            # Get animation frame from tracked state
            anim_state = self.player_animations.get(player.id, {})
            player_frame = anim_state.get('frame', 0)
            
            # Use walking animation if player is moving (even if server hasn't sent walk gani yet)
            display_gani = player.gani
            if player.id in self.player_predictions and self.player_predictions[player.id].get('moving'):
                # Only override to walk if they're currently idle
                if player.gani == 'idle' or not player.gani:
                    display_gani = 'walk'
            else:
                # If not moving, use their actual gani (which should be idle)
                display_gani = player.gani or 'idle'
                    
            sprites_with_pos = self.get_player_sprites_with_positions(player.direction, display_gani, player_frame)
            
            if sprites_with_pos:
                # Draw all sprites at their GANI-defined positions
                for surface, x_offset, y_offset in sprites_with_pos:
                    # GANI positions are relative to player position
                    sprite_x = screen_x + x_offset - 16  # Adjust for tile center
                    sprite_y = screen_y + y_offset - 16
                    self.screen.blit(surface, (sprite_x, sprite_y))
            else:
                # Fallback to colored circle
                    
                color = BLUE
                if player.gani == "walk":
                    color = (0, 100, 255)
                elif player.gani == "sword":
                    color = RED
                    
                center_x = int(screen_x + TILE_SIZE/2)
                center_y = int(screen_y + TILE_SIZE/2)
                pygame.draw.circle(self.screen, color, (center_x, center_y), TILE_SIZE//2)
                
                # Draw direction indicator
                dir_length = TILE_SIZE // 3
                if player.direction == Direction.UP:
                    pygame.draw.line(self.screen, WHITE, (center_x, center_y), 
                                   (center_x, center_y - dir_length), 2)
                elif player.direction == Direction.DOWN:
                    pygame.draw.line(self.screen, WHITE, (center_x, center_y), 
                                   (center_x, center_y + dir_length), 2)
                elif player.direction == Direction.LEFT:
                    pygame.draw.line(self.screen, WHITE, (center_x, center_y), 
                                   (center_x - dir_length, center_y), 2)
                elif player.direction == Direction.RIGHT:
                    pygame.draw.line(self.screen, WHITE, (center_x, center_y), 
                                   (center_x + dir_length, center_y), 2)
                             
            # Draw nickname
            name_text = self.small_font.render(player.nickname, True, WHITE)
            name_rect = name_text.get_rect(center=(screen_x + TILE_SIZE/2, screen_y - 20))
            self.screen.blit(name_text, name_rect)
            
            # Draw chat
            if player.chat:
                chat_text = self.small_font.render(player.chat, True, WHITE)
                chat_rect = chat_text.get_rect(center=(screen_x + TILE_SIZE/2, screen_y - 35))
                # Chat bubble background
                pygame.draw.rect(self.screen, BLACK, chat_rect.inflate(4, 2))
                self.screen.blit(chat_text, chat_rect)
                
        # Draw local player
        local_player = self.client.local_player
        screen_x = (local_player.x - self.camera_x) * TILE_SIZE
        screen_y = (local_player.y - self.camera_y) * TILE_SIZE
        
        # Get player sprites with GANI positions
        sprites_with_pos = self.get_player_sprites_with_positions(local_player.direction, local_player.gani, self.animation_frame)
        
        if sprites_with_pos:
            # Draw all sprites at their GANI-defined positions
            for surface, x_offset, y_offset in sprites_with_pos:
                # GANI positions are relative to player position
                sprite_x = screen_x + x_offset - 16  # Adjust for tile center
                sprite_y = screen_y + y_offset - 16
                self.screen.blit(surface, (sprite_x, sprite_y))
        else:
            # Fallback to colored circle
            color = GREEN
            if local_player.gani == "walk":
                color = (0, 200, 0)  # Darker green when walking
            elif local_player.gani == "sword":
                color = (255, 255, 0)  # Yellow when attacking
                
            center_x = int(screen_x + TILE_SIZE/2)
            center_y = int(screen_y + TILE_SIZE/2)
            pygame.draw.circle(self.screen, color, (center_x, center_y), TILE_SIZE//2)
            
            # Draw direction indicator
            dir_length = TILE_SIZE // 3
            if local_player.direction == Direction.UP:
                pygame.draw.line(self.screen, WHITE, (center_x, center_y), 
                               (center_x, center_y - dir_length), 2)
            elif local_player.direction == Direction.DOWN:
                pygame.draw.line(self.screen, WHITE, (center_x, center_y), 
                               (center_x, center_y + dir_length), 2)
            elif local_player.direction == Direction.LEFT:
                pygame.draw.line(self.screen, WHITE, (center_x, center_y), 
                               (center_x - dir_length, center_y), 2)
            elif local_player.direction == Direction.RIGHT:
                pygame.draw.line(self.screen, WHITE, (center_x, center_y), 
                               (center_x + dir_length, center_y), 2)
                         
        # Draw local player name
        name_text = self.small_font.render(local_player.nickname, True, WHITE)
        name_rect = name_text.get_rect(center=(screen_x + TILE_SIZE/2, screen_y - 20))
        self.screen.blit(name_text, name_rect)
        
        # Draw local player chat
        if local_player.chat:
            chat_text = self.small_font.render(local_player.chat, True, WHITE)
            chat_rect = chat_text.get_rect(center=(screen_x + TILE_SIZE/2, screen_y - 35))
            pygame.draw.rect(self.screen, BLACK, chat_rect.inflate(4, 2))
            self.screen.blit(chat_text, chat_rect)
            
    def draw_ui(self):
        """Draw UI elements"""
        # Position info
        pos_text = self.font.render(f"Position: ({self.client.local_player.x:.1f}, {self.client.local_player.y:.1f})", 
                                   True, WHITE)
        self.screen.blit(pos_text, (10, 10))
        
        # Level info
        if self.current_level:
            level_text = self.font.render(f"Level: {self.current_level.name}", True, WHITE)
            self.screen.blit(level_text, (10, 35))
            
        # Player count
        player_text = self.font.render(f"Players: {len(self.players) + 1}", True, WHITE)
        self.screen.blit(player_text, (10, 60))
        
        # Tile debug info
        if self.debug_tiles:
            mouse_x, mouse_y = pygame.mouse.get_pos()
            tile_x = int(mouse_x // TILE_SIZE + self.camera_x)
            tile_y = int(mouse_y // TILE_SIZE + self.camera_y)
            
            if 0 <= tile_x < 64 and 0 <= tile_y < 64 and self.current_level:
                tile_id = self.current_level.get_board_tile_id(tile_x, tile_y)
                tile_type = self.tile_defs.get_tile_type(tile_id)
                tile_name = self.tile_defs.get_tile_name(tile_type)
                
                debug_text = [
                    f"Tile ({tile_x}, {tile_y})",
                    f"ID: {tile_id}",
                    f"Type: {tile_name}"
                ]
                
                y_offset = 90
                for text in debug_text:
                    debug_surface = self.small_font.render(text, True, WHITE)
                    self.screen.blit(debug_surface, (10, y_offset))
                    y_offset += 15
        
        # Chat mode
        if self.chat_mode:
            chat_prompt = self.font.render(f"Chat: {self.chat_buffer}_", True, WHITE)
            chat_rect = chat_prompt.get_rect(bottom=SCREEN_HEIGHT - 10, left=10)
            pygame.draw.rect(self.screen, BLACK, chat_rect.inflate(10, 5))
            self.screen.blit(chat_prompt, chat_rect)
        else:
            help_text = self.small_font.render("Arrow keys: Move | S: Sword | A: Grab/Pull | Tab: Chat | F3: Tile Debug | Esc: Quit", 
                                             True, WHITE)
            self.screen.blit(help_text, (10, SCREEN_HEIGHT - 20))
            
    def run(self):
        """Main game loop"""
        # Get initial level
        self.current_level = self.client.level_manager.get_current_level()
        
        while self.running and self.connected and self.client.connected:
            # Handle events
            self.handle_events()
            self.process_game_events()
            
            # Update
            self.handle_movement()
            
            # Update animation
            current_time = time.time()
            
            # Sword animation runs at half speed
            anim_speed = self.animation_speed * 2 if self.sword_animating else self.animation_speed
            
            if current_time - self.animation_time > anim_speed:
                self.animation_time = current_time
                
                # Handle sword animation (play once)
                if self.sword_animating:
                    old_frame = self.animation_frame
                    self.animation_frame = self.animation_frame + 1
                    
                    # Play sound for new frame
                    if self.animation_frame != old_frame:
                        self.play_gani_sounds('sword', self.animation_frame)
                    
                    if self.animation_frame >= 4:  # Sword has 4 frames
                        self.sword_animating = False
                        # Check if we should return to walking
                        if self.is_moving:
                            self.client.set_gani("walk")
                        else:
                            self.client.set_gani("idle")
                        self.animation_frame = 0
                else:
                    # Loop other animations based on their frame count
                    gani = self.client.local_player.gani
                    max_frames = {'idle': 1, 'walk': 8, 'grab': 1, 'pull': 1}.get(gani, 1)
                    old_frame = self.animation_frame
                    self.animation_frame = (self.animation_frame + 1) % max_frames
                    
                    # Play sound if frame changed
                    if self.animation_frame != old_frame and gani:
                        self.play_gani_sounds(gani, self.animation_frame)
                    
            # Update other players' animations
            for player_id, anim_state in list(self.player_animations.items()):
                player = self.players.get(player_id)
                if not player:
                    continue
                    
                # Use faster animation speed for walking
                player_anim_speed = 0.02 if player.gani == 'walk' else anim_speed
                
                if current_time - anim_state['last_update'] > player_anim_speed:
                    anim_state['last_update'] = current_time
                    gani = player.gani or 'idle'
                    
                    # Update stored gani if it changed
                    if anim_state.get('gani') != gani:
                        anim_state['gani'] = gani
                        anim_state['frame'] = 0
                    else:
                        max_frames = {'idle': 1, 'walk': 8, 'grab': 1, 'pull': 1, 'sword': 4}.get(gani, 1)
                        anim_state['frame'] = (anim_state['frame'] + 1) % max_frames
            
            # Update thrown bushes
            self.bush_handler.update_thrown_bushes(self.current_level, self.tile_defs, current_time)
            self.bush_handler.update_explosions(current_time)
            
            # Draw
            self.screen.fill(BLACK)
            self.draw_level()
            self.draw_thrown_bushes()
            self.draw_players()
            self.draw_ui()
            
            # Update display
            pygame.display.flip()
            self.clock.tick(60)  # 60 FPS
            
        # Cleanup
        self.client.disconnect()
        pygame.quit()

def main():
    """Main entry point"""
    print("PyReborn Pygame Client")
    print("=====================")
    print()
    
    # Get login credentials
    username = input("Username (default: pygameplayer): ").strip() or "pygameplayer"
    password = input("Password (default: 1234): ").strip() or "1234"
    
    # Create client
    game = PygameClient()
    
    print("\nConnecting to server...")
    if not game.connect_and_login(username, password):
        print("Failed to connect or login!")
        return 1
        
    print("Connected! Starting game...")
    print("\nControls:")
    print("- Arrow keys: Move")
    print("- S or Space: Swing sword")
    print("- A: Grab (hold A + opposite arrow to pull)")
    print("- Tab: Enter chat mode")
    print("- Escape: Quit")
    print()
    
    # Wait for initial data
    time.sleep(2)
    
    # Run game
    game.run()
    
    print("\nThanks for playing!")
    return 0

if __name__ == "__main__":
    sys.exit(main())