#!/usr/bin/env python3
"""
Pygame Client with Server Browser - A visual client for PyReborn with server selection
"""

import sys
import os
import pygame
import threading
import time
import queue
import math
from pyreborn import RebornClient, ServerInfo
from pyreborn.protocol.enums import Direction
from pyreborn.events import EventType

# Import the original pygame_client
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from pygame_client import PygameClient, SCREEN_WIDTH, SCREEN_HEIGHT, TILE_SIZE, BLACK, WHITE, GREEN, RED, BLUE, GRAY, UI_BG, UI_BORDER, UI_TEXT, UI_HIGHLIGHT, DARK_GREEN, YELLOW, PURPLE, CYAN, VIEWPORT_TILES_X, VIEWPORT_TILES_Y
from classic_constants import ClassicConstants, ClassicItems, ItemValues
from item_manager import ItemManager, DroppedItem
from bush_handler import BushHandler
from gani_parser import GaniManager
from tile_defs import TileDefs

class ServerBrowserState:
    """Server browser UI state"""
    
    def __init__(self, screen):
        self.screen = screen
        self.font = pygame.font.Font(None, 24)
        self.title_font = pygame.font.Font(None, 36)
        self.small_font = pygame.font.Font(None, 18)
        
        # Server list
        self.servers = []
        self.selected_index = 0
        self.scroll_offset = 0
        self.max_visible = 15
        
        # Server list state
        self.loading = False
        self.error_message = ""
        
        # Login info
        self.username = ""
        self.password = ""
        self.username_active = True
        self.password_active = False
        
    def connect_to_serverlist(self):
        """Connect to server list and fetch servers"""
        self.loading = True
        self.error_message = ""
        
        try:
            # Use PyReborn's static method to get server list
            servers, status_info = RebornClient.get_server_list(self.username, self.password)
            
            if servers:
                self.servers = servers
                # Sort by player count
                self.servers.sort(key=lambda s: s.players, reverse=True)
            else:
                self.error_message = status_info.get('error', 'No servers found')
                
        except Exception as e:
            self.error_message = f"Error: {str(e)}"
        
        self.loading = False
    
    def handle_event(self, event):
        """Handle input events"""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # Handle mouse clicks
            mouse_x, mouse_y = event.pos
            
            # Check username field
            username_rect = pygame.Rect(150, 98, 200, 28)
            if username_rect.collidepoint(mouse_x, mouse_y):
                self.username_active = True
                self.password_active = False
            
            # Check password field  
            password_rect = pygame.Rect(500, 98, 200, 28)
            if password_rect.collidepoint(mouse_x, mouse_y):
                self.username_active = False
                self.password_active = True
            
            # Check fetch button
            fetch_rect = pygame.Rect(750, 98, 100, 28)
            if fetch_rect.collidepoint(mouse_x, mouse_y) and not self.loading:
                if self.username and self.password:
                    threading.Thread(target=self.connect_to_serverlist, daemon=True).start()
            
            # Check server list
            if self.servers:
                list_y = 190
                for i in range(self.scroll_offset, min(self.scroll_offset + self.max_visible, len(self.servers))):
                    y = list_y + 10 + (i - self.scroll_offset) * 25
                    server_rect = pygame.Rect(55, y - 2, SCREEN_WIDTH - 110, 24)
                    if server_rect.collidepoint(mouse_x, mouse_y):
                        self.selected_index = i
                        # Double-click to connect
                        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                            current_time = pygame.time.get_ticks()
                            if hasattr(self, 'last_click_time') and current_time - self.last_click_time < 500:
                                return 'connect'
                            self.last_click_time = current_time
        
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                return 'quit'
            
            elif event.key == pygame.K_TAB:
                # Switch between username and password fields
                self.username_active = not self.username_active
                self.password_active = not self.password_active
            
            elif event.key == pygame.K_RETURN:
                # If we have servers and not loading, Enter should connect
                if self.servers and not self.loading:
                    # Connect to selected server
                    return 'connect'
                elif self.username and self.password and not self.servers:
                    # Only fetch if we don't have servers yet
                    threading.Thread(target=self.connect_to_serverlist, daemon=True).start()
            
            elif event.key == pygame.K_F5:
                # F5 to refresh server list
                if self.username and self.password and not self.loading:
                    threading.Thread(target=self.connect_to_serverlist, daemon=True).start()
            
            elif event.key == pygame.K_UP and self.servers:
                self.selected_index = max(0, self.selected_index - 1)
                if self.selected_index < self.scroll_offset:
                    self.scroll_offset = self.selected_index
            
            elif event.key == pygame.K_DOWN and self.servers:
                self.selected_index = min(len(self.servers) - 1, self.selected_index + 1)
                if self.selected_index >= self.scroll_offset + self.max_visible:
                    self.scroll_offset = self.selected_index - self.max_visible + 1
            
            elif event.key == pygame.K_BACKSPACE:
                if self.username_active and self.username:
                    self.username = self.username[:-1]
                elif self.password_active and self.password:
                    self.password = self.password[:-1]
            
            else:
                # Text input
                if event.unicode and len(event.unicode) == 1:
                    if self.username_active and len(self.username) < 20:
                        self.username += event.unicode
                    elif self.password_active and len(self.password) < 20:
                        self.password += event.unicode
        
        return None
    
    def draw(self):
        """Draw the server browser UI"""
        self.screen.fill(UI_BG)
        
        # Title
        title = self.title_font.render("PyReborn Server Browser", True, UI_TEXT)
        title_rect = title.get_rect(center=(SCREEN_WIDTH // 2, 40))
        self.screen.blit(title, title_rect)
        
        # Login section
        login_y = 100
        
        # Username field
        username_label = self.font.render("Username:", True, UI_TEXT)
        self.screen.blit(username_label, (50, login_y))
        
        username_rect = pygame.Rect(150, login_y - 2, 200, 28)
        pygame.draw.rect(self.screen, WHITE if self.username_active else GRAY, username_rect, 2)
        username_text = self.font.render(self.username, True, UI_TEXT)
        self.screen.blit(username_text, (155, login_y))
        
        # Password field
        password_label = self.font.render("Password:", True, UI_TEXT)
        self.screen.blit(password_label, (400, login_y))
        
        password_rect = pygame.Rect(500, login_y - 2, 200, 28)
        pygame.draw.rect(self.screen, WHITE if self.password_active else GRAY, password_rect, 2)
        password_text = self.font.render("*" * len(self.password), True, UI_TEXT)
        self.screen.blit(password_text, (505, login_y))
        
        # Fetch button
        fetch_rect = pygame.Rect(750, login_y - 2, 100, 28)
        button_color = GRAY if self.loading else UI_HIGHLIGHT
        pygame.draw.rect(self.screen, button_color, fetch_rect)
        fetch_label = "Loading..." if self.loading else "Fetch (F5)"
        fetch_text = self.font.render(fetch_label, True, WHITE)
        fetch_text_rect = fetch_text.get_rect(center=fetch_rect.center)
        self.screen.blit(fetch_text, fetch_text_rect)
        
        # Server list section
        list_y = 160
        
        # Server list header
        header_text = self.font.render("Available Servers:", True, UI_TEXT)
        self.screen.blit(header_text, (50, list_y))
        
        # Loading/Error message
        if self.loading:
            loading_text = self.font.render("Loading servers...", True, GREEN)
            self.screen.blit(loading_text, (300, list_y))
        elif self.error_message:
            error_text = self.font.render(self.error_message, True, RED)
            self.screen.blit(error_text, (300, list_y))
        
        # Server list
        list_y += 30
        if self.servers:
            # Draw server list box
            list_rect = pygame.Rect(50, list_y, SCREEN_WIDTH - 100, 400)
            pygame.draw.rect(self.screen, UI_BORDER, list_rect, 2)
            
            # Draw servers
            for i in range(self.scroll_offset, min(self.scroll_offset + self.max_visible, len(self.servers))):
                server = self.servers[i]
                y = list_y + 10 + (i - self.scroll_offset) * 25
                
                # Highlight selected server
                if i == self.selected_index:
                    select_rect = pygame.Rect(55, y - 2, SCREEN_WIDTH - 110, 24)
                    pygame.draw.rect(self.screen, UI_HIGHLIGHT, select_rect)
                
                # Server name
                name_text = self.font.render(server.name[:40], True, WHITE if i == self.selected_index else UI_TEXT)
                self.screen.blit(name_text, (60, y))
                
                # Player count
                players_text = self.small_font.render(f"{server.player_count} players", True, GREEN)
                self.screen.blit(players_text, (500, y + 2))
                
                # Server address
                addr_text = self.small_font.render(f"{server.ip}:{server.port}", True, GRAY)
                self.screen.blit(addr_text, (650, y + 2))
        
        # Instructions
        inst_y = SCREEN_HEIGHT - 100
        instructions = [
            "Tab: Switch fields | Enter: Connect | F5: Refresh | Up/Down: Select | Double-click: Connect | Esc: Quit"
        ]
        for i, instruction in enumerate(instructions):
            inst_text = self.small_font.render(instruction, True, GRAY)
            inst_rect = inst_text.get_rect(center=(SCREEN_WIDTH // 2, inst_y + i * 20))
            self.screen.blit(inst_text, inst_rect)
    
    def get_selected_server(self):
        """Get the currently selected server"""
        if self.servers and 0 <= self.selected_index < len(self.servers):
            return self.servers[self.selected_index]
        return None


class PygameClientWithBrowser(PygameClient):
    """Extended pygame client with server browser"""
    
    def __init__(self):
        # Initialize parent but don't create client yet
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption("PyReborn Client")
        self.clock = pygame.time.Clock()
        
        # Don't initialize client until server is selected
        self.client = None
        self.connected = False
        self.running = True
        
        # Server browser
        self.server_browser = ServerBrowserState(self.screen)
        self.state = 'browser'  # 'browser' or 'game'
        
        # Store login credentials
        self.username = ""
        self.password = ""
    
    def connect_to_server(self, host, port, username, password):
        """Connect to a specific server"""
        # Create client for the selected server
        self.client = RebornClient(host, port)
        
        # Initialize the rest of the game state
        self._init_game_state()
        
        # Connect and login
        if not self.client.connect():
            return False
            
        if not self.client.login(username, password):
            self.client.disconnect()
            return False
            
        self.connected = True
        self.client.set_nickname("PygamePlayer")
        
        # Reduce packet send rate for smoother gameplay
        self.client.set_packet_send_rate(0.02)
        
        # Subscribe to events
        self._setup_event_handlers()
        
        # Set initial idle animation
        self.client.set_gani("idle")
        
        # Center camera on player
        self.camera_x = self.client.local_player.x - VIEWPORT_TILES_X // 2
        self.camera_y = self.client.local_player.y - VIEWPORT_TILES_Y // 2
        
        # Start network thread
        self.network_thread = threading.Thread(target=self._network_loop, daemon=True)
        self.network_thread.start()
        
        return True
    
    def _init_game_state(self):
        """Initialize game-specific state (from parent class)"""
        # This is all the initialization from the parent __init__ after client creation
        # We'll import necessary modules here
        
        # Fonts
        self.font_large = pygame.font.Font(None, 36)
        self.font_medium = pygame.font.Font(None, 24)
        self.font_small = pygame.font.Font(None, 18)
        self.font_tiny = pygame.font.Font(None, 14)
        
        # Backward compatibility
        self.font = self.font_medium
        self.small_font = self.font_small
        
        # Load tileset
        self.tileset = None
        self.tileset_cache = {}
        try:
            tileset_path = os.path.join(os.path.dirname(__file__), "assets", "pics1.png")
            if os.path.exists(tileset_path):
                self.tileset = pygame.image.load(tileset_path).convert_alpha()
                print(f"✅ Loaded tileset from {tileset_path}")
                print(f"   Tileset size: {self.tileset.get_size()}")
            else:
                print(f"⚠️  WARNING: Tileset not found at {tileset_path}")
        except Exception as e:
            print(f"❌ Failed to load tileset: {e}")
            
        # Initialize GANI manager
        self.gani_manager = GaniManager(os.path.dirname(__file__))
        
        # Initialize tile definitions for collision detection
        self.tile_defs = TileDefs()
        
        # Initialize bush handler
        self.bush_handler = BushHandler()
        
        # Initialize item manager
        from item_manager import ItemManager
        self.item_manager = ItemManager()
        
        # Track opened chests
        self.opened_chests = set()  # Set of (x, y) tuples
        
        # Sound system
        pygame.mixer.init()
        self.sound_cache = {}
        self.sound_channels = {i: pygame.mixer.Channel(i) for i in range(8)}  # 8 channels
        
        # Preload common GANIs
        for gani_name in ['idle', 'walk', 'sword', 'grab', 'pull', 'carry', 'sit', 'lift', 'push']:
            gani = self.gani_manager.load_gani(gani_name)
            if gani:
                print(f"Loaded GANI: {gani_name}")
                
        # Debug options
        self.debug_updates = False  # Set to True to see update frequency
        self.debug_tiles = False  # Set to True to see tile info under cursor
        self.debug_collision = False  # Set to True to show collision box in red
        
        # Collision configuration
        self.collision_config = {
            'RIGHT': {'x_offset': 1.0, 'y_offset': 1.0},  # 16 pixels right, 16 pixels down
            'DOWN': {'x_offset': 1.0, 'y_offset': 1.0},
            'LEFT': {'x_offset': 1.0, 'y_offset': 1.0},
            'UP': {'x_offset': 1.0, 'y_offset': 1.0},
            'shadow_width': 1.2,  # Twice as wide (was 0.6)
            'shadow_height': 0.6
        }
        
        # Keep sprite cache for performance
        self.sprite_cache = {}
        
        # Camera
        self.camera_x = 0
        self.camera_y = 0
        
        # Input
        self.keys_pressed = set()
        self.chat_mode = False
        self.chat_buffer = ""
        self.chat_history = []  # Store chat messages
        self.max_chat_history = 10
        
        # Game state
        self.players = {}
        self.player_animations = {}  # Track animation states for other players
        self.player_predictions = {}  # Track predicted positions for smooth movement
        self.current_level = None
        self.event_queue = queue.Queue()
        self.grabbed_tile_pos = None  # Position of tile being grabbed
        
        # Movement
        self.move_speed = 0.5  # Half tile per move
        self.is_swimming = False  # Track if player is in water
        self.last_move_time = 0
        self.move_cooldown = 0.02  # 20ms between moves (smoother movement)
        self.is_moving = False
        self.last_direction = Direction.DOWN
        self.step_count = 0  # For alternating step sounds
        
        # Animation
        self.animation_time = 0
        self.animation_frame = 0
        self.animation_speed = 0.02  # Time between frames in seconds (2.5x faster)
        self.sword_animating = False
        self.sword_start_time = 0
        self.grabbing = False
        self.on_chair = False  # Track if sitting on a chair
        self.throwing = False  # Track if throwing animation is playing
        self.throw_start_time = 0
        self.pushing = False  # Track if pushing against a wall
        self.push_start_time = 0
        self.blocked_direction = None  # Direction we're blocked in
        
        # UI State
        self.show_debug = False
        self.show_minimap = False
        self.show_player_list = False
        self.messages = []  # System messages
        self.message_duration = 5.0
        
        # Performance tracking
        self.fps_history = []
        self.fps_sample_size = 60
    
    def _setup_event_handlers(self):
        """Set up event handlers for network events"""
        self.client.events.subscribe(EventType.PLAYER_ADDED, self._on_player_added)
        self.client.events.subscribe(EventType.PLAYER_REMOVED, self._on_player_left)
        self.client.events.subscribe(EventType.OTHER_PLAYER_UPDATE, self._on_player_moved)
        self.client.events.subscribe(EventType.PLAYER_PROPS_UPDATE, self._on_player_props_update)
        self.client.events.subscribe(EventType.CHAT_MESSAGE, self._on_player_chat)
        self.client.events.subscribe(EventType.LEVEL_ENTERED, self._on_level_changed)
    
    def _network_loop(self):
        """Network loop to handle client events"""
        while self.running and self.connected:
            time.sleep(0.01)
    
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
    
    def run(self):
        """Main game loop"""
        while self.running:
            if self.state == 'browser':
                # Handle browser events
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self.running = False
                    else:
                        result = self.server_browser.handle_event(event)
                        if result == 'quit':
                            self.running = False
                        elif result == 'connect':
                            # Get selected server
                            server = self.server_browser.get_selected_server()
                            if server:
                                self.username = self.server_browser.username
                                self.password = self.server_browser.password
                                
                                print(f"Connecting to {server.name} at {server.ip}:{server.port}...")
                                if self.connect_to_server(server.ip, server.port, self.username, self.password):
                                    print("Connected successfully!")
                                    self.state = 'game'
                                    self.current_level = self.client.level_manager.get_current_level()
                                else:
                                    print("Failed to connect!")
                                    self.server_browser.error_message = "Failed to connect to server"
                
                # Draw browser
                self.server_browser.draw()
                
            elif self.state == 'game':
                # Run the actual game
                if self.connected and self.client.connected:
                    # We need to implement these methods since we're not properly inheriting
                    self.handle_events()
                    self.process_game_events()
                    self.update()
                    self.draw()
                else:
                    # Disconnected, go back to browser
                    self.state = 'browser'
                    self.server_browser.error_message = "Disconnected from server"
                    if self.client:
                        self.client.disconnect()
                    self.client = None
                    self.connected = False
            
            # Update display
            pygame.display.flip()
            self.clock.tick(60)
        
        # Cleanup
        if self.client and self.connected:
            self.client.disconnect()
        pygame.quit()
    
    def add_message(self, text: str, color=WHITE):
        """Add a system message"""
        self.messages.append({
            'text': text,
            'color': color,
            'time': time.time()
        })
        
    def _handle_item_pickup(self, item):
        """Handle picking up an item"""
        player = self.client.local_player
        
        if item.item_type == 'heart':
            # Heal the player
            old_hearts = player.hearts
            player.hearts = min(player.hearts + item.value, player.max_hearts)
            if player.hearts > old_hearts:
                self.add_message(f"+{item.value} Heart!", (255, 100, 100))
                # TODO: Send heart update to server
                
        elif item.item_type == 'rupee':
            player.rupees += int(item.value)
            color = GREEN if item.value == 1 else CYAN if item.value == 5 else YELLOW
            self.add_message(f"+{int(item.value)} Rupee{'s' if item.value > 1 else ''}!", color)
            # TODO: Send rupee update to server
            
        elif item.item_type == 'bomb':
            player.bombs += int(item.value)
            self.add_message(f"+{int(item.value)} Bomb!", (128, 64, 0))
            # TODO: Send bomb update to server
            
        elif item.item_type == 'arrow':
            player.arrows += int(item.value)
            self.add_message(f"+{int(item.value)} Arrows!", (150, 75, 0))
            # TODO: Send arrow update to server
            
        elif item.item_type == 'key':
            # Keys are typically handled by server
            self.add_message("Got a key!", YELLOW)
            
        elif item.item_type == 'heart_container':
            player.max_hearts += 1
            player.hearts = player.max_hearts  # Full heal
            self.add_message("Heart Container! Max hearts increased!", (255, 0, 255))
            # TODO: Send max heart update to server
            
        # Play pickup sound based on item type
        if item.item_type == 'heart':
            self.play_classic_sound('heart')
        elif item.item_type == 'rupee':
            self.play_classic_sound('rupee')
        elif item.item_type == 'bomb':
            self.play_classic_sound('bomb')
        elif item.item_type == 'arrow':
            self.play_classic_sound('arrow')
        elif item.item_type == 'key':
            self.play_classic_sound('key')
        elif item.item_type == 'heart_container':
            self.play_classic_sound('heart_container')
        else:
            self.play_classic_sound('pickup')
        
    def _check_sword_hit(self):
        """Check what the sword hits when swinging"""
        if not self.current_level:
            return
            
        # Calculate sword hit area based on direction
        player_x = self.client.local_player.x
        player_y = self.client.local_player.y
        
        # Sword reaches 1 tile in front
        hit_positions = []
        if self.last_direction == Direction.UP:
            hit_positions = [(player_x, player_y - 1), (player_x + 1, player_y - 1)]
        elif self.last_direction == Direction.DOWN:
            hit_positions = [(player_x, player_y + 1), (player_x + 1, player_y + 1)]
        elif self.last_direction == Direction.LEFT:
            hit_positions = [(player_x - 1, player_y), (player_x - 1, player_y + 1)]
        elif self.last_direction == Direction.RIGHT:
            hit_positions = [(player_x + 1, player_y), (player_x + 1, player_y + 1)]
            
        # Check each position
        for hit_x, hit_y in hit_positions:
            tile_x = int(hit_x)
            tile_y = int(hit_y)
            
            if 0 <= tile_x < 64 and 0 <= tile_y < 64:
                tile_id = self.current_level.get_board_tile_id(tile_x, tile_y)
                
                # Check if it's grass or bush
                if self.tile_defs.is_cuttable(tile_id):
                    # Cut the grass/bush - replace with normal ground
                    self.current_level.set_board_tile_id(tile_x, tile_y, 0)  # Replace with empty
                    
                    # Play appropriate cutting sound
                    if self.tile_defs.is_bush(tile_id):
                        # Bush cutting - use a different sound
                        self.play_classic_sound('bomb')  # Use bomb sound for bush destruction
                        self.add_message("Destroyed bush!", YELLOW)
                    else:
                        # Grass cutting
                        self.play_classic_sound('grass_cut')
                    
                    # Drop a random item maybe
                    dropped = self.item_manager.drop_random_item(tile_x, tile_y)
                    if dropped:
                        self.add_message("Found something!", GREEN)
                        self.play_classic_sound('secret', 0.5)  # Quieter secret sound
                        
                    # Add respawn timer for grass
                    self.item_manager.add_respawn_timer(tile_x, tile_y, ClassicConstants.GRASS_RESPAWN_TIME)
                    
                    # TODO: Send tile update to server
        
        # Check for chest hits
        for chest in self.current_level.chests:
            if (chest.x, chest.y) in self.opened_chests:
                continue
                
            # Check if sword hits the 2x2 chest area
            chest_positions = [
                (chest.x, chest.y), (chest.x + 1, chest.y),
                (chest.x, chest.y + 1), (chest.x + 1, chest.y + 1)
            ]
            
            for cx, cy in chest_positions:
                if (cx, cy) in [(int(x), int(y)) for x, y in hit_positions]:
                    # Open the chest!
                    self._open_chest(chest)
                    break
                    
    def _open_chest(self, chest):
        """Open a chest and spawn its contents"""
        # Mark as opened
        self.opened_chests.add((chest.x, chest.y))
        
        # Play chest opening sound
        self.play_classic_sound('chest_open')
        
        # Determine what's in the chest based on item ID
        item_type = None
        if chest.item in [1, 2, 3]:  # Hearts
            item_type = 'heart'
        elif chest.item in [4, 5, 6]:  # Rupees
            item_type = 'rupee'
        elif chest.item in [7, 8]:  # Bombs
            item_type = 'bomb'
        elif chest.item in [9, 10]:  # Arrows
            item_type = 'arrow'
        elif chest.item in [11, 12]:  # Keys
            item_type = 'key'
        elif chest.item >= 20:  # Special items - heart container
            item_type = 'heart_container'
        else:
            # Default to rupees
            item_type = 'rupee'
            
        # Drop the item at chest location
        if item_type:
            dropped = self.item_manager.drop_item(chest.x + 0.5, chest.y + 0.5, item_type)
            if dropped:
                self.add_message("Opened chest!", YELLOW)
                # Play special sound for rare items
                if item_type == 'heart_container':
                    self.play_classic_sound('secret')
                
        # Show sign text if any
        if hasattr(chest, 'sign_text') and chest.sign_text:
            self.add_message(chest.sign_text, WHITE)
            self.play_classic_sound('text', 0.5)
            
        # TODO: Send chest opened message to server
        
    def _check_water_status(self):
        """Check if player is in water and update swimming status"""
        if not self.current_level:
            return
            
        player_x = self.client.local_player.x
        player_y = self.client.local_player.y
        
        # Check the tiles at player's feet
        check_points = [
            (player_x + 0.2, player_y + 0.8),  # Bottom-left
            (player_x + 0.8, player_y + 0.8),  # Bottom-right
            (player_x + 0.5, player_y + 0.9),  # Bottom center
        ]
        
        in_water = False
        for check_x, check_y in check_points:
            tile_x = int(check_x)
            tile_y = int(check_y)
            
            if 0 <= tile_x < 64 and 0 <= tile_y < 64:
                tile_id = self.current_level.get_board_tile_id(tile_x, tile_y)
                if self.tile_defs.is_water(tile_id):
                    in_water = True
                    break
                    
        # Update swimming status
        if in_water != self.is_swimming:
            self.is_swimming = in_water
            if in_water:
                self.add_message("Swimming", BLUE)
                self.play_classic_sound('swim', 0.6)
                # TODO: Change to swimming animation/sprite
                
    def _check_for_sign(self, x: float, y: float):
        """Check if there's a sign at the given position"""
        if not self.current_level:
            return None
            
        tile_x = int(x)
        tile_y = int(y)
        
        # Check level signs
        for sign in self.current_level.signs:
            if sign.x == tile_x and sign.y == tile_y:
                return sign
                
        # Check if it's a sign tile type
        if 0 <= tile_x < 64 and 0 <= tile_y < 64:
            tile_id = self.current_level.get_board_tile_id(tile_x, tile_y)
            if self.tile_defs.get_tile_type(tile_id) == self.tile_defs.SIGN_POST:
                # Create a generic sign
                from pyreborn.models.level import Sign
                return Sign(tile_x, tile_y, "This sign is blank.")
                
        return None
        
    def _read_sign(self, sign):
        """Display sign text"""
        if sign and hasattr(sign, 'text') and sign.text:
            # Play text sound
            self.play_classic_sound('text', 0.6)
            # Split text into multiple lines if needed
            lines = sign.text.split('\\n')
            for line in lines:
                self.add_message(line, WHITE)
        else:
            self.add_message("The sign is blank.", GRAY)
        
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
                    elif event.key == pygame.K_F1:
                        self.show_debug = not self.show_debug
                        self.add_message("Debug: " + ("ON" if self.show_debug else "OFF"), YELLOW)
                    elif event.key == pygame.K_F2:
                        self.debug_collision = not self.debug_collision
                        self.add_message("Collision Debug: " + ("ON" if self.debug_collision else "OFF"), YELLOW)
                    elif event.key == pygame.K_m:
                        self.show_minimap = not self.show_minimap
                        self.add_message("Minimap: " + ("ON" if self.show_minimap else "OFF"), YELLOW)
                    elif event.key == pygame.K_p:
                        self.show_player_list = not self.show_player_list
                        self.add_message("Player list: " + ("ON" if self.show_player_list else "OFF"), YELLOW)
                    elif event.key == pygame.K_SPACE or event.key == pygame.K_s:
                        # Swing sword
                        if not self.sword_animating and not self.throwing:
                            self.client.set_gani("sword")
                            self.animation_frame = 0
                            self.sword_animating = True
                            self.throwing = False  # Cancel any throw pause
                            self.sword_start_time = time.time()
                            # Play sound for first frame
                            self.play_gani_sounds('sword', 0)
                            # Check for grass cutting
                            self._check_sword_hit()
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
                            self.throwing = True  # Start throw pause
                            self.throw_start_time = time.time()
                            # Play throw sound
                            self.play_classic_sound('bush_throw')
                            # Clear carry sprite and notify server about throwing
                            self.set_carry_sprite("")
                            self.throw_carried()
                        else:
                            # Start grabbing - check if there's something to grab in front
                            dx, dy = 0, 0
                            if self.last_direction == Direction.UP:
                                dy = -1
                            elif self.last_direction == Direction.DOWN:
                                dy = 1
                            elif self.last_direction == Direction.LEFT:
                                dx = -1
                            elif self.last_direction == Direction.RIGHT:
                                dx = 1
                                
                            # Grab check starts from player's center position
                            base_x = self.client.local_player.x + 0.5  # Center of tile
                            base_y = self.client.local_player.y + 0.5  # Center of tile
                            
                            # Check multiple distances to detect objects we're touching or near
                            grabbable = None
                            for distance in [0.5, 0.8, 1.0]:  # Check closer and farther
                                check_x = base_x + dx * distance
                                check_y = base_y + dy * distance
                                
                                # Check if there's a grabbable tile at this position
                                grabbable = self.bush_handler.check_grabbable_at_position(
                                    self.current_level, self.tile_defs, check_x, check_y
                                )
                                if grabbable:
                                    break  # Found something, stop searching
                            
                            if grabbable:
                                self.grabbing = True
                                self.client.set_gani("grab")
                                self.animation_frame = 0
                                # Store grabbed tile position for visual feedback
                                self.grabbed_tile_pos = grabbable
                                
                                # Check if it's a bush or just a grabbable object
                                tile_x, tile_y = grabbable
                                tile_id = self.current_level.get_board_tile_id(tile_x, tile_y)
                                if self.bush_handler.is_bush_tile(tile_id):
                                    self.add_message("Grabbing bush - release A to pick up!", GREEN)
                                else:
                                    self.add_message("Grabbing object - pull with opposite arrow!", YELLOW)
                            else:
                                # Check for signs to read
                                sign = self._check_for_sign(check_x, check_y)
                                if sign:
                                    self._read_sign(sign)
                                else:
                                    self.add_message("Nothing to grab here", RED)
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
                            self.tile_defs,
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
                            # Play bush lift sound
                            self.play_classic_sound('bush_lift')
                            # Notify server we're carrying a bush
                            self.set_carry_sprite("bush")
                    self.grabbing = False
                    self.grabbed_tile_pos = None  # Clear grabbed tile position
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
                        # Use nickname if available, otherwise use id
                        player_name = getattr(player, 'nickname', getattr(player, 'name', f"Player{player.id}"))
                        self.add_message(f"{player_name} joined", CYAN)
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
                    if player.id in self.players:
                        self.add_message(f"{self.players[player.id].nickname} left", CYAN)
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
                        
                elif event_type == 'player_chat':
                    player_name = event_data.get('player_name', 'Unknown')
                    message = event_data.get('message', '')
                    if message:
                        chat_entry = f"{player_name}: {message}"
                        self.chat_history.append(chat_entry)
                        if len(self.chat_history) > self.max_chat_history:
                            self.chat_history.pop(0)
                            
                elif event_type == 'level_changed':
                    self.current_level = self.client.level_manager.get_current_level()
                    if self.current_level:
                        self.add_message(f"Entered: {self.current_level.name}", GREEN)
                        # Check if board data is available
                        if hasattr(self.current_level, 'board_tiles_64x64') and self.current_level.board_tiles_64x64:
                            self.add_message(f"Level has board data ({len(self.current_level.board_tiles_64x64)} tiles)", GREEN)
                        else:
                            self.add_message("Level loaded but no board data yet", YELLOW)
                    else:
                        self.add_message("Level changed but no level data", RED)
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
        if self.chat_mode or self.sword_animating or self.throwing:
            return
            
        # Don't allow normal movement while grabbing
        if self.grabbing:
            # Only allow pulling movement
            self._handle_pull_movement()
            return
            
        current_time = time.time()
        if current_time - self.last_move_time < self.move_cooldown:
            return
            
        # Check if player is in water
        self._check_water_status()
        
        # Adjust speed if swimming
        current_speed = ClassicConstants.SWIM_SPEED if self.is_swimming else self.move_speed
        
        dx, dy = 0, 0
        direction = None
        
        if pygame.K_LEFT in self.keys_pressed:
            dx -= current_speed
            direction = Direction.LEFT
        if pygame.K_RIGHT in self.keys_pressed:
            dx += current_speed
            direction = Direction.RIGHT
        if pygame.K_UP in self.keys_pressed:
            dy -= current_speed
            direction = Direction.UP
        if pygame.K_DOWN in self.keys_pressed:
            dy += current_speed
            direction = Direction.DOWN
            
        # Normal movement (not grabbing)
            
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
                
                # Play walking sound (alternating steps)
                if not hasattr(self, 'step_count'):
                    self.step_count = 0
                self.step_count += 1
                if self.step_count % 2 == 0:  # Play sound every other step
                    volume = 0.3 if self.is_swimming else 0.4
                    self.play_classic_sound('step', volume)
                
                # Clear pushing state when we can move
                if self.pushing:
                    self.pushing = False
                    self.blocked_direction = None
                    # Need to set walking animation after clearing push
                    if self.bush_handler.carrying_bush:
                        self.client.set_gani("carry")
                    else:
                        self.client.set_gani("walk")
            else:
                # Blocked! Check for pushing
                if direction is not None:
                    self.last_direction = direction
                    
                    # Start or continue pushing
                    if not self.pushing:
                        self.pushing = True
                        self.push_start_time = current_time
                        self.blocked_direction = direction
                        # Send direction update only when first blocked
                        self.client.move_to(self.client.local_player.x, self.client.local_player.y, direction)
                    elif self.blocked_direction == direction and current_time - self.push_start_time > 0.5:
                        # After 0.5 seconds of being blocked, show push animation
                        if self.client.local_player.gani != "push":
                            self.client.set_gani("push")
                        # Don't send move commands while in push animation
            
            # Set walking animation if not already moving AND not pushing
            if not self.is_moving and not self.pushing:
                self.on_chair = False  # Clear chair state when starting to move
                # Use carry animation if carrying a bush
                if self.bush_handler.carrying_bush:
                    self.client.set_gani("carry")
                else:
                    self.client.set_gani("walk")
                self.is_moving = True
        else:
            # Set idle animation when stopped
            if self.is_moving:
                self.is_moving = False
                self.animation_frame = 0  # Reset animation frame
                # Set idle animation immediately when stopped
                if not self.on_chair and not self.grabbing:
                    if self.bush_handler.carrying_bush:
                        self.client.set_gani("carry")
                    else:
                        self.client.set_gani("idle")
                
            # Clear pushing state when no movement
            if self.pushing:
                self.pushing = False
                self.blocked_direction = None
                # Return to appropriate idle animation
                if self.bush_handler.carrying_bush:
                    self.client.set_gani("carry")
                else:
                    self.client.set_gani("idle")
                
        # Always update camera to follow player
        self.camera_x = self.client.local_player.x - VIEWPORT_TILES_X // 2
        self.camera_y = self.client.local_player.y - VIEWPORT_TILES_Y // 2
        
    def _handle_pull_movement(self):
        """Handle pulling animation while grabbing (no actual movement)"""
        direction = None
        
        # Check for arrow key presses
        if pygame.K_LEFT in self.keys_pressed:
            direction = Direction.LEFT
        elif pygame.K_RIGHT in self.keys_pressed:
            direction = Direction.RIGHT
        elif pygame.K_UP in self.keys_pressed:
            direction = Direction.UP
        elif pygame.K_DOWN in self.keys_pressed:
            direction = Direction.DOWN
            
        if direction is not None:
            # Check if it's opposite direction (for pulling)
            opposite_direction = {
                Direction.LEFT: Direction.RIGHT,
                Direction.RIGHT: Direction.LEFT,
                Direction.UP: Direction.DOWN,
                Direction.DOWN: Direction.UP
            }.get(self.last_direction)
            
            if direction == opposite_direction:
                # Just show pull animation, no movement
                if self.client.local_player.gani != "pull":
                    self.client.set_gani("pull")
            else:
                # Not pulling - just stay in grab animation
                if self.client.local_player.gani != "grab":
                    self.client.set_gani("grab")
        else:
            # No movement - stay in grab animation
            if self.client.local_player.gani != "grab":
                self.client.set_gani("grab")
        
        # Check if we're on a chair
        self.check_chair_status()
        
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
            
        # Player's collision box is their shadow at the feet
        # Use configurable parameters
        shadow_width = self.collision_config['shadow_width']
        shadow_height = self.collision_config['shadow_height']
        
        # Direction-specific offsets to match sprite positioning
        direction_name = self.last_direction.name
        config = self.collision_config.get(direction_name, self.collision_config['UP'])
        x_offset = config['x_offset']
        y_offset = config['y_offset']
        
        check_points = [
            (x + x_offset, y + y_offset),                                    # Top-left
            (x + x_offset + shadow_width, y + y_offset),                    # Top-right
            (x + x_offset, y + y_offset + shadow_height),                   # Bottom-left
            (x + x_offset + shadow_width, y + y_offset + shadow_height),    # Bottom-right
            (x + 0.5, y + 0.5)                                              # Center of shadow
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
        
    def check_chair_status(self):
        """Check if player is on a chair tile and update animation"""
        if not self.current_level:
            return
            
        # Don't sit while moving or grabbing
        if self.is_moving or self.grabbing:
            if self.on_chair:
                self.on_chair = False
            return
            
        # Check tiles around the player's position for special tiles
        player_x = self.client.local_player.x
        player_y = self.client.local_player.y
        
        # Check multiple points around the player
        check_points = [
            (player_x + 0.5, player_y + 0.5),    # Center
            (player_x + 0.2, player_y + 0.2),    # Top-left
            (player_x + 0.8, player_y + 0.2),    # Top-right
            (player_x + 0.2, player_y + 0.8),    # Bottom-left
            (player_x + 0.8, player_y + 0.8),    # Bottom-right
            (player_x + 0.5, player_y + 1.0),    # Bottom center (feet)
        ]
        
        # Check if any of these points are on a chair
        on_chair_tile = False
        for check_x, check_y in check_points:
            tile_x = int(check_x)
            tile_y = int(check_y)
            
            if 0 <= tile_x < 64 and 0 <= tile_y < 64:
                tile_id = self.current_level.get_board_tile_id(tile_x, tile_y)
                tile_type = self.tile_defs.get_tile_type(tile_id)
                
                if tile_type == self.tile_defs.CHAIR:
                    on_chair_tile = True
                    print(f"Found chair tile at ({tile_x}, {tile_y}), tile_id={tile_id}, type={tile_type}")
                    break
        
        # Update chair state based on whether we found a chair tile
        if on_chair_tile:
            if not self.on_chair:
                self.on_chair = True
                self.client.set_gani("sit")
                self.animation_frame = 0
        else:
            if self.on_chair:
                self.on_chair = False
                self.animation_frame = 0
            # Always set appropriate idle animation when not on chair and not moving
            if not self.is_moving and not self.grabbing and not self.pushing:
                if self.bush_handler.carrying_bush:
                    self.client.set_gani("carry")
                else:
                    self.client.set_gani("idle")
        
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
                    
        # Add respawn timer for the bush
        self.item_manager.add_respawn_timer(base_x, base_y, ClassicConstants.BUSH_RESPAWN_TIME)
                    
    def set_carry_sprite(self, sprite_name: str):
        """Set the carry sprite (what player is holding)"""
        # This would normally update the carry sprite on the server
        # For now, we'll just handle it locally
        if hasattr(self.client.local_player, 'carry_sprite'):
            self.client.local_player.carry_sprite = sprite_name
        
    def throw_carried(self):
        """Notify server about throwing carried item"""
        # TODO: PyReborn needs a throw_carried() method in the client/actions
        # For now, the visual throwing is handled locally by the pygame client
        # The server should be notified via a proper PyReborn method when available
        pass
        
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
        
    def update(self):
        """Update game state"""
        # Handle movement
        self.handle_movement()
        
        # Update animation
        current_time = time.time()
        
        # Check for short throw pause (0.2 seconds)
        if self.throwing and current_time - self.throw_start_time > 0.2:
            self.throwing = False
            self.sword_animating = False
            # Check if movement keys are still pressed
            movement_keys = {pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT}
            if any(key in self.keys_pressed for key in movement_keys):
                self.client.set_gani("walk")
                self.is_moving = True
            else:
                self.client.set_gani("idle")
                self.is_moving = False
            self.animation_frame = 0
        
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
                    # Check if this was a throw animation
                    if self.throwing:
                        self.throwing = False
                        # After throw, always return to idle
                        self.client.set_gani("idle")
                    else:
                        # Check if we should return to walking
                        if self.is_moving:
                            if self.bush_handler.carrying_bush:
                                self.client.set_gani("carry")
                            else:
                                self.client.set_gani("walk")
                        else:
                            if self.bush_handler.carrying_bush:
                                self.client.set_gani("carry")
                            else:
                                self.client.set_gani("idle")
                    self.animation_frame = 0
            else:
                # Loop other animations based on their frame count
                gani = self.client.local_player.gani
                max_frames = {'idle': 1, 'walk': 8, 'grab': 1, 'pull': 1, 'carry': 3, 'sit': 1, 'lift': 1, 'push': 1}.get(gani, 1)
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
                    max_frames = {'idle': 1, 'walk': 8, 'grab': 1, 'pull': 1, 'sword': 4, 'carry': 3, 'sit': 1, 'lift': 1, 'push': 1}.get(gani, 1)
                    anim_state['frame'] = (anim_state['frame'] + 1) % max_frames
        
        # Update thrown bushes
        self.bush_handler.update_thrown_bushes(self.current_level, self.tile_defs, current_time)
        self.bush_handler.update_explosions(current_time)
        
        # Update items and check pickups
        self.item_manager.update(current_time)
        picked_up_items = self.item_manager.check_pickup(
            self.client.local_player.x, 
            self.client.local_player.y
        )
        
        # Process pickups
        for item in picked_up_items:
            self._handle_item_pickup(item)
            
        # Check for bush respawns
        if self.current_level:
            tiles_2d = self.current_level.get_board_tiles_2d()
            for y in range(0, 64, 2):  # Check every 2x2 area
                for x in range(0, 64, 2):
                    # Check if this position can respawn and was a bush location
                    if self.item_manager.can_respawn_at(x, y):
                        # Check if it's currently empty (replacement tiles)
                        if (x < 63 and y < 63 and 
                            tiles_2d[y][x] == 677 and tiles_2d[y][x+1] == 678 and
                            tiles_2d[y+1][x] == 693 and tiles_2d[y+1][x+1] == 694):
                            # Respawn the bush!
                            tiles_2d[y][x] = 2
                            tiles_2d[y][x+1] = 3
                            tiles_2d[y+1][x] = 18
                            tiles_2d[y+1][x+1] = 19
                            # Update flat array too
                            for dy in range(2):
                                for dx in range(2):
                                    idx = (y + dy) * 64 + (x + dx)
                                    if hasattr(self.current_level, 'board_tiles_64x64'):
                                        bush_tile = [2, 3, 18, 19][dy * 2 + dx]
                                        self.current_level.board_tiles_64x64[idx] = bush_tile
        
    def draw(self):
        """Draw the game"""
        self.screen.fill(BLACK)
        self._draw_level()
        self._draw_grab_indicators()
        self._draw_thrown_bushes()
        self._draw_players()
        self._draw_collision_debug()  # Debug collision box
        self._draw_ui()
        
    def _draw_level(self):
        """Draw the current level"""
        if not self.current_level:
            # Draw a message if no level is loaded
            text = self.font_large.render("Waiting for level data...", True, WHITE)
            text_rect = text.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2))
            self.screen.blit(text, text_rect)
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
        
        # Draw chests
        for chest in self.current_level.chests:
            # Skip opened chests
            if (chest.x, chest.y) in self.opened_chests:
                continue
                
            # Check if chest is in view (chests are 2x2, so check wider area)
            if (start_x - 1 <= chest.x <= end_x and start_y - 1 <= chest.y <= end_y):
                screen_x = (chest.x - self.camera_x) * TILE_SIZE
                screen_y = (chest.y - self.camera_y) * TILE_SIZE
                
                # In classic Graal, chests use specific tile IDs
                # Brown chest: 640-643, Blue chest: 644-647, etc.
                # The item type determines which chest graphic to use
                # For now, use brown chest (most common)
                base_tile = 640  # Classic brown chest base
                
                # Chest is 2x2 tiles
                chest_tiles = [base_tile, base_tile + 1, base_tile + 16, base_tile + 17]
                chest_offsets = [(0, 0), (1, 0), (0, 1), (1, 1)]
                
                # Draw the 2x2 chest
                for tile_id, (dx, dy) in zip(chest_tiles, chest_offsets):
                    tile_surface = self.get_tile_surface(tile_id)
                    if tile_surface:
                        self.screen.blit(tile_surface, (screen_x + dx * TILE_SIZE, screen_y + dy * TILE_SIZE))
                    else:
                        # Fallback: draw as brown rectangles with border
                        color = (139, 90, 43) if (dx + dy) % 2 == 0 else (160, 82, 45)  # SaddleBrown
                        pygame.draw.rect(self.screen, color,
                                       (screen_x + dx * TILE_SIZE, screen_y + dy * TILE_SIZE, TILE_SIZE, TILE_SIZE))
                        pygame.draw.rect(self.screen, (101, 67, 33),  # Dark brown border
                                       (screen_x + dx * TILE_SIZE, screen_y + dy * TILE_SIZE, TILE_SIZE, TILE_SIZE), 2)
        
        # Draw NPCs
        if hasattr(self.current_level, 'npcs'):
            for npc_id, npc in self.current_level.npcs.items():
                # Check if NPC is in view
                if (start_x <= int(npc.x) <= end_x and start_y <= int(npc.y) <= end_y):
                    screen_x = (npc.x - self.camera_x) * TILE_SIZE
                    screen_y = (npc.y - self.camera_y) * TILE_SIZE
                    
                    # For now, draw NPCs as colored circles with their image name
                    npc_color = (255, 128, 0)  # Orange for NPCs
                    pygame.draw.circle(self.screen, npc_color, 
                                     (int(screen_x + TILE_SIZE/2), int(screen_y + TILE_SIZE/2)), 
                                     TILE_SIZE//2)
                    
                    # Draw NPC nickname if available
                    if hasattr(npc, 'nickname') and npc.nickname:
                        name_text = self.font_tiny.render(npc.nickname, True, WHITE)
                        name_rect = name_text.get_rect(center=(screen_x + TILE_SIZE/2, screen_y - 10))
                        self.screen.blit(name_text, name_rect)
        
        # Draw dropped items with floating animation
        current_time = time.time()
        for item in self.item_manager.dropped_items:
            # Check if item is in view
            if (start_x - 1 <= int(item.x) <= end_x and start_y - 1 <= int(item.y) <= end_y):
                screen_x = (item.x - self.camera_x) * TILE_SIZE
                screen_y = (item.y - self.camera_y) * TILE_SIZE
                
                # Apply floating animation
                if not item.picked_up:
                    float_offset = item.get_float_offset(current_time) * TILE_SIZE
                    screen_y += float_offset
                else:
                    # Pickup animation - rise and fade
                    pickup_elapsed = current_time - item.pickup_time
                    rise_offset = pickup_elapsed * ClassicConstants.PICKUP_RISE_SPEED * TILE_SIZE
                    screen_y -= rise_offset
                    
                # Draw 2x2 item tiles
                offsets = [(0, 0), (1, 0), (0, 1), (1, 1)]
                for i, (dx, dy) in enumerate(offsets):
                    if i < len(item.tile_ids):
                        tile_surface = self.get_tile_surface(item.tile_ids[i])
                        if tile_surface:
                            # Apply fade during pickup
                            if item.picked_up:
                                pickup_elapsed = current_time - item.pickup_time
                                alpha = int(255 * (1 - pickup_elapsed / ClassicConstants.PICKUP_DURATION))
                                tile_surface = tile_surface.copy()
                                tile_surface.set_alpha(alpha)
                            
                            self.screen.blit(tile_surface, (screen_x + dx * TILE_SIZE, screen_y + dy * TILE_SIZE))
                                   
    def _draw_grab_indicators(self):
        """Draw indicators for grabbable tiles when holding grab key"""
        if pygame.K_a in self.keys_pressed and not self.bush_handler.carrying_bush:
            # Calculate position in front of player
            dx, dy = 0, 0
            if self.last_direction == Direction.UP:
                dy = -1
            elif self.last_direction == Direction.DOWN:
                dy = 1
            elif self.last_direction == Direction.LEFT:
                dx = -1
            elif self.last_direction == Direction.RIGHT:
                dx = 1
            
            # Check area in front of player (same as grab detection)
            base_x = self.client.local_player.x + 0.5  # Center of tile
            base_y = self.client.local_player.y + 0.5  # Center of tile
            
            check_x = base_x + dx * 0.8
            check_y = base_y + dy * 0.8
            
            # Get grabbable position
            grabbable = self.bush_handler.check_grabbable_at_position(
                self.current_level, self.tile_defs, check_x, check_y
            )
            
            if grabbable:
                tile_x, tile_y = grabbable
                tile_id = self.current_level.get_board_tile_id(tile_x, tile_y)
                is_bush = self.bush_handler.is_bush_tile(tile_id)
                
                screen_x = (tile_x - self.camera_x) * TILE_SIZE
                screen_y = (tile_y - self.camera_y) * TILE_SIZE
                
                # Draw highlight box with pulsing effect
                pulse = abs(math.sin(time.time() * 4)) * 0.5 + 0.5
                if is_bush:
                    # Green for pickupable bushes
                    color = (0, int(255 * pulse), 0)
                    label = "PICK UP"
                else:
                    # Yellow for pullable objects
                    color = (int(255 * pulse), int(255 * pulse), 0)
                    label = "GRAB"
                    
                pygame.draw.rect(self.screen, color, 
                               (screen_x - 2, screen_y - 2, TILE_SIZE + 4, TILE_SIZE + 4), 3)
                
                # Draw appropriate text
                grab_text = self.font_tiny.render(label, True, color)
                text_rect = grab_text.get_rect(center=(screen_x + TILE_SIZE//2, screen_y - 10))
                self.screen.blit(grab_text, text_rect)
    
    def _draw_thrown_bushes(self):
        """Draw thrown bushes and explosions"""
        current_time = time.time()
        
        # Draw thrown bushes
        for bush in self.bush_handler.thrown_bushes:
            x, y = bush.get_position(current_time)
            screen_x = (x - self.camera_x) * TILE_SIZE
            screen_y = (y - self.camera_y) * TILE_SIZE
            
            # Draw all 4 bush tiles as a smaller 2x2 block while flying
            bush_tiles = [2, 3, 18, 19]
            bush_offsets = [(0, 0), (1, 0), (0, 1), (1, 1)]
            
            for tile_id, (dx, dy) in zip(bush_tiles, bush_offsets):
                bush_surface = self.get_tile_surface(tile_id)
                if bush_surface:
                    # Keep bush nearly full size while flying (90%)
                    scale_factor = 0.9
                    scaled_size = int(TILE_SIZE * scale_factor)
                    small_bush = pygame.transform.scale(bush_surface, (scaled_size, scaled_size))
                    bush_x = screen_x + (dx * scaled_size)
                    bush_y = screen_y + (dy * scaled_size)
                    self.screen.blit(small_bush, (bush_x, bush_y))
        
        # Draw explosions
        for exp_x, exp_y, exp_time in self.bush_handler.bush_explosions:
            age = current_time - exp_time
            if age < 0.5:  # 0.5 second explosion
                screen_x = (exp_x - self.camera_x) * TILE_SIZE
                screen_y = (exp_y - self.camera_y) * TILE_SIZE
                
                # Bush fragment explosion - use actual bush tiles as fragments
                num_fragments = 6
                # Use different bush tiles as fragments (grass/leaf tiles)
                fragment_tiles = [2, 3, 18, 19, 2, 3]  # Repeat some for variety
                
                for i in range(num_fragments):
                    angle = (i / num_fragments) * 2 * 3.14159
                    distance = age * TILE_SIZE * 2.5  # Fragments spread out
                    frag_x = screen_x + TILE_SIZE/2 + math.cos(angle) * distance
                    frag_y = screen_y + TILE_SIZE/2 + math.sin(angle) * distance - (age * TILE_SIZE * 2)  # Add upward motion
                    
                    # Fragment size and alpha based on age
                    scale_factor = max(0.1, 0.5 * (1 - age * 2))
                    alpha = int(255 * (1 - age * 2))
                    
                    if scale_factor > 0 and alpha > 0:
                        # Get the tile surface
                        tile_surface = self.get_tile_surface(fragment_tiles[i])
                        if tile_surface:
                            # Scale down the fragment
                            frag_size = int(TILE_SIZE * scale_factor)
                            if frag_size > 0:
                                scaled_fragment = pygame.transform.scale(tile_surface, (frag_size, frag_size))
                                scaled_fragment.set_alpha(alpha)
                                self.screen.blit(scaled_fragment, (frag_x - frag_size/2, frag_y - frag_size/2))
    
    def _draw_collision_debug(self):
        """Draw collision box for debugging"""
        if not self.debug_collision or not self.client.local_player:
            return
            
        # Get player position
        player_x = self.client.local_player.x
        player_y = self.client.local_player.y
        
        # Calculate collision box using same logic as collision detection
        shadow_width = self.collision_config['shadow_width']
        shadow_height = self.collision_config['shadow_height']
        
        direction_name = self.last_direction.name
        config = self.collision_config.get(direction_name, self.collision_config['UP'])
        x_offset = config['x_offset']
        y_offset = config['y_offset']
        
        # Calculate screen position
        screen_x = (player_x - self.camera_x) * TILE_SIZE
        screen_y = (player_y - self.camera_y) * TILE_SIZE
        
        # Draw collision box in red
        collision_rect = pygame.Rect(
            screen_x + x_offset * TILE_SIZE,
            screen_y + y_offset * TILE_SIZE,
            shadow_width * TILE_SIZE,
            shadow_height * TILE_SIZE
        )
        pygame.draw.rect(self.screen, RED, collision_rect, 2)
        
        # Draw center point in yellow
        center_x = screen_x + (x_offset + shadow_width/2) * TILE_SIZE
        center_y = screen_y + (y_offset + shadow_height/2) * TILE_SIZE
        pygame.draw.circle(self.screen, YELLOW, (int(center_x), int(center_y)), 3)
        
        # Draw direction indicator
        direction_text = self.font_small.render(f"Dir: {direction_name}", True, WHITE)
        self.screen.blit(direction_text, (10, 120))
        
        # Draw collision config info
        config_text = self.font_small.render(f"Offset: ({x_offset:.1f}, {y_offset:.1f})", True, WHITE)
        self.screen.blit(config_text, (10, 140))
                               
    def _draw_players(self):
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
                    # GANI offsets are already relative to the sprite origin
                    # No need for additional -16 offset
                    sprite_x = screen_x + x_offset
                    sprite_y = screen_y + y_offset
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
                             
            # Draw carried object if player is carrying something
            if hasattr(player, 'carry_sprite') and player.carry_sprite and player.carry_sprite != -1:
                # Convert carry_sprite to object name (server sends sprite names)
                self.draw_carried_object(screen_x, screen_y, str(player.carry_sprite))
                
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
                # GANI offsets are already relative to the sprite origin
                # No need for additional -16 offset  
                sprite_x = screen_x + x_offset
                sprite_y = screen_y + y_offset - 8  # Slight upward adjustment for feet position
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
                         
        # Draw carried bush above player if carrying
        if self.bush_handler.carrying_bush:
            # Draw all 4 bush tiles (2,3,18,19) as a 2x2 block above player
            bush_tiles = [2, 3, 18, 19]
            bush_offsets = [(0, 0), (1, 0), (0, 1), (1, 1)]  # Relative positions
            
            for tile_id, (dx, dy) in zip(bush_tiles, bush_offsets):
                bush_surface = self.get_tile_surface(tile_id)
                if bush_surface:
                    # Position bush above player's head, properly centered
                    # Bush is 2x2 tiles, so center it by offsetting by half a tile
                    bush_x = screen_x + (dx * TILE_SIZE)  # No extra offset needed
                    bush_y = screen_y - (TILE_SIZE * 1.5) + (dy * TILE_SIZE)  # Above head, closer
                    self.screen.blit(bush_surface, (bush_x, bush_y))
                         
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
            
    def _draw_ui(self):
        """Draw UI elements"""
        # Draw messages
        self._draw_messages()
        
        # Draw chat
        if self.chat_mode or self.chat_history:
            self._draw_chat()
            
        # Draw debug info
        if self.show_debug:
            self._draw_debug_info()
            
        # Draw minimap
        if self.show_minimap:
            self._draw_minimap()
            
        # Draw player list
        if self.show_player_list:
            self._draw_player_list()
            
        # Draw status bar
        self._draw_status_bar()
        
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
            
    def _draw_messages(self):
        """Draw system messages"""
        y_offset = 100
        current_time = time.time()
        
        for msg in self.messages:
            age = current_time - msg['time']
            if age < self.message_duration:
                alpha = max(0, min(255, 255 * (1 - age / self.message_duration)))
                
                text = self.font_medium.render(msg['text'], True, msg['color'])
                text.set_alpha(alpha)
                
                x = SCREEN_WIDTH // 2 - text.get_width() // 2
                self.screen.blit(text, (x, y_offset))
                y_offset += 30
                
        # Clean up old messages
        self.messages = [msg for msg in self.messages if current_time - msg['time'] < self.message_duration]
        
    def _draw_chat(self):
        """Draw chat interface"""
        chat_y = SCREEN_HEIGHT - 200
        
        # Chat background
        if self.chat_history:
            chat_bg = pygame.Surface((400, 150))
            chat_bg.fill(UI_BG)
            chat_bg.set_alpha(200)
            self.screen.blit(chat_bg, (10, chat_y))
            
        # Chat history
        y_offset = 0
        for message in self.chat_history[-7:]:
            text = self.font_small.render(message, True, UI_TEXT)
            self.screen.blit(text, (15, chat_y + 5 + y_offset))
            y_offset += 20
            
        # Chat input
        if self.chat_mode:
            chat_prompt = self.font_medium.render(f"> {self.chat_buffer}", True, WHITE)
            chat_rect = chat_prompt.get_rect(bottom=SCREEN_HEIGHT - 10, left=10)
            
            # Background
            pygame.draw.rect(self.screen, UI_BG, chat_rect.inflate(10, 5))
            pygame.draw.rect(self.screen, UI_BORDER, chat_rect.inflate(10, 5), 2)
            
            # Text and cursor
            self.screen.blit(chat_prompt, chat_rect)
            if int(time.time() * 2) % 2:
                cursor_x = chat_rect.right + 2
                pygame.draw.line(self.screen, WHITE, (cursor_x, chat_rect.top), (cursor_x, chat_rect.bottom), 2)
                
    def _draw_debug_info(self):
        """Draw debug information"""
        debug_info = [
            f"FPS: {int(self.clock.get_fps())}",
            f"Position: ({self.client.local_player.x:.1f}, {self.client.local_player.y:.1f})",
            f"Level: {self.current_level.name if self.current_level else 'None'}",
            f"Players: {len(self.players) + 1}",
            f"Carrying: {self.bush_handler.carrying_bush}"
        ]
        
        # Add tile debug if enabled
        if self.debug_tiles:
            mouse_x, mouse_y = pygame.mouse.get_pos()
            tile_x = int(mouse_x // TILE_SIZE + self.camera_x)
            tile_y = int(mouse_y // TILE_SIZE + self.camera_y)
            
            if 0 <= tile_x < 64 and 0 <= tile_y < 64 and self.current_level:
                tile_id = self.current_level.get_board_tile_id(tile_x, tile_y)
                debug_info.extend([
                    f"Tile: ({tile_x}, {tile_y}) = {tile_id}",
                    f"Blocking: {self.tile_defs.is_blocking(tile_id)}"
                ])
        
        # Render debug panel
        panel_height = len(debug_info) * 15 + 10
        debug_surface = pygame.Surface((220, panel_height))
        debug_surface.fill(UI_BG)
        debug_surface.set_alpha(200)
        self.screen.blit(debug_surface, (SCREEN_WIDTH - 230, 10))
        
        y = 15
        for line in debug_info:
            text = self.font_tiny.render(line, True, UI_TEXT)
            self.screen.blit(text, (SCREEN_WIDTH - 225, y))
            y += 15
            
    def _draw_minimap(self):
        """Draw minimap"""
        if not self.current_level:
            return
            
        map_size = 150
        map_x = SCREEN_WIDTH - map_size - 10
        map_y = SCREEN_HEIGHT - map_size - 10
        
        # Background
        pygame.draw.rect(self.screen, UI_BG, (map_x - 2, map_y - 2, map_size + 4, map_size + 4))
        pygame.draw.rect(self.screen, UI_BORDER, (map_x - 2, map_y - 2, map_size + 4, map_size + 4), 2)
        
        # Scale factor
        scale = map_size / 64
        
        # Draw simplified level
        for y in range(0, 64, 2):
            for x in range(0, 64, 2):
                tile_id = self.current_level.get_board_tile_id(x, y)
                
                if self.tile_defs.is_blocking(tile_id):
                    color = GRAY
                elif self.tile_defs.is_water(tile_id):
                    color = BLUE
                else:
                    color = DARK_GREEN
                    
                pygame.draw.rect(self.screen, color,
                               (map_x + int(x * scale), map_y + int(y * scale),
                                max(1, int(2 * scale)), max(1, int(2 * scale))))
                                
        # Draw players
        for player in self.players.values():
            px = map_x + int(player.x * scale)
            py = map_y + int(player.y * scale)
            pygame.draw.circle(self.screen, YELLOW, (px, py), 2)
            
        # Draw local player
        px = map_x + int(self.client.local_player.x * scale)
        py = map_y + int(self.client.local_player.y * scale)
        pygame.draw.circle(self.screen, GREEN, (px, py), 3)
        
        # Draw view area
        view_rect = (
            map_x + int(self.camera_x * scale),
            map_y + int(self.camera_y * scale),
            int(VIEWPORT_TILES_X * scale),
            int(VIEWPORT_TILES_Y * scale)
        )
        pygame.draw.rect(self.screen, WHITE, view_rect, 1)
        
    def _draw_player_list(self):
        """Draw player list"""
        list_width = 200
        players_shown = min(15, len(self.players) + 1)
        list_height = 30 + players_shown * 20
        
        # Background
        list_surface = pygame.Surface((list_width, list_height))
        list_surface.fill(UI_BG)
        list_surface.set_alpha(220)
        self.screen.blit(list_surface, (10, 50))
        
        # Border
        pygame.draw.rect(self.screen, UI_BORDER, (10, 50, list_width, list_height), 2)
        
        # Title
        title = self.font_medium.render(f"Players ({len(self.players) + 1})", True, WHITE)
        self.screen.blit(title, (20, 55))
        
        # Players
        y = 80
        
        # Local player
        name = f"• {getattr(self.client.local_player, 'nickname', f'Player{self.client.local_player.id}')} (You)"
        text = self.font_small.render(name, True, GREEN)
        self.screen.blit(text, (20, y))
        y += 20
        
        # Other players
        for player in sorted(self.players.values(), key=lambda p: p.nickname)[:14]:
            name = f"• {getattr(player, 'nickname', f'Player{player.id}')}"
            text = self.font_small.render(name, True, UI_TEXT)
            self.screen.blit(text, (20, y))
            y += 20
            
    def _draw_status_bar(self):
        """Draw bottom status bar"""
        # Draw Classic Graal stats bar at top
        player = self.client.local_player
        stats_y = 5
        stats_x = 10
        
        # Hearts
        heart_text = f"Hearts: {player.hearts:.1f}/{player.max_hearts}"
        hearts_surface = self.font_medium.render(heart_text, True, (255, 100, 100))
        self.screen.blit(hearts_surface, (stats_x, stats_y))
        stats_x += 150
        
        # Rupees
        rupee_text = f"Rupees: {player.rupees}"
        rupee_surface = self.font_medium.render(rupee_text, True, GREEN)
        self.screen.blit(rupee_surface, (stats_x, stats_y))
        stats_x += 120
        
        # Bombs
        bomb_text = f"Bombs: {player.bombs}"
        bomb_surface = self.font_medium.render(bomb_text, True, (128, 64, 0))
        self.screen.blit(bomb_surface, (stats_x, stats_y))
        stats_x += 100
        
        # Arrows
        arrow_text = f"Arrows: {player.arrows}"
        arrow_surface = self.font_medium.render(arrow_text, True, (150, 75, 0))
        self.screen.blit(arrow_surface, (stats_x, stats_y))
        
        # Swimming indicator
        if self.is_swimming:
            swim_text = self.font_medium.render("SWIMMING", True, CYAN)
            swim_rect = swim_text.get_rect(right=SCREEN_WIDTH - 10, top=5)
            self.screen.blit(swim_text, swim_rect)
        
        # Bottom help text
        if not self.chat_mode:
            help_text = self.font_tiny.render(
                "Arrow/WASD: Move | Space/S: Attack | A: Grab/Read | Tab: Chat | F1: Debug | F2: Collision | M: Map | P: Players | Esc: Quit",
                True, GRAY
            )
            self.screen.blit(help_text, (10, SCREEN_HEIGHT - 20))
            
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
                
    def play_classic_sound(self, sound_name: str, volume: float = 0.7):
        """Play a Classic Graal sound effect
        
        Args:
            sound_name: Name of the sound (without .wav extension)
            volume: Volume from 0.0 to 1.0
        """
        # Map sound names to Classic Graal sound files
        sound_map = {
            'pickup': 'item.wav',
            'heart': 'heart.wav',
            'rupee': 'rupee.wav',
            'bomb': 'bomb.wav',
            'arrow': 'arrow.wav',
            'key': 'get_key.wav',
            'heart_container': 'fanfare.wav',
            'sword': 'sword.wav',
            'sword_hit': 'hit.wav',
            'hurt': 'hurt.wav',
            'die': 'die.wav',
            'grass_cut': 'grass.wav',
            'chest_open': 'chest.wav',
            'bush_lift': 'pickup2.wav',
            'bush_throw': 'throw.wav',
            'swim': 'swim.wav',
            'step': 'step.wav',
            'text': 'text.wav',
            'secret': 'secret.wav'
        }
        
        # Get the actual filename
        filename = sound_map.get(sound_name, f"{sound_name}.wav")
        
        # Load and play the sound
        sound = self.load_sound(filename)
        if sound:
            # Find a free channel
            for channel_id, channel in self.sound_channels.items():
                if not channel.get_busy():
                    sound.set_volume(volume)
                    channel.play(sound)
                    break
                
    def draw_carried_object(self, screen_x: float, screen_y: float, carry_sprite: str):
        """Draw a carried object above a player
        
        Args:
            screen_x: Screen X position of player
            screen_y: Screen Y position of player
            carry_sprite: Name of carried object (e.g. "bush", "pot", "bomb")
        """
        if carry_sprite == "bush":
            # Draw all 4 bush tiles (2,3,18,19) as a 2x2 block above player
            tiles = [2, 3, 18, 19]
            offsets = [(0, 0), (1, 0), (0, 1), (1, 1)]
        elif carry_sprite == "pot":
            # Example: pot could be a different set of tiles
            tiles = [128]  # Single tile for pot
            offsets = [(0, 0)]
        elif carry_sprite == "bomb":
            # Example: bomb sprite
            tiles = [130]
            offsets = [(0, 0)]
        else:
            # Unknown carry sprite, skip
            return
            
        # Draw the tiles
        for tile_id, (dx, dy) in zip(tiles, offsets):
            surface = self.get_tile_surface(tile_id)
            if surface:
                # Position object above player's head, properly centered
                obj_x = screen_x + (dx * TILE_SIZE)  # Position relative to player
                obj_y = screen_y - (TILE_SIZE * 1.5) + (dy * TILE_SIZE)  # Above head
                self.screen.blit(surface, (obj_x, obj_y))
        
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
            
        elif gani == "carry":
            # Carry animation with walking frames
            # Based on sit.gani: carrying sprites are 264-275 (3 frames)
            carry_frame = frame % 3  # 3 frames of walking
            base_sprite = 264 + (carry_frame * 4)  # Each frame has 4 directions
            body_sprite_id = base_sprite + dir_idx
            head_sprite_id = 100 + dir_idx
            
        elif gani == "lift":
            # Lift animation - same as carry for now
            body_sprite_id = 256 + dir_idx  # 256=up, 257=left, 258=down, 259=right
            head_sprite_id = 100 + dir_idx
            
        elif gani == "sit":
            # Sitting animation uses specific sprites from sit.gani
            # Based on the sit.gani file: 256=up, 281=left, 279=down, 283=right
            sit_bodies = {0: 256, 1: 281, 2: 279, 3: 283}
            body_sprite_id = sit_bodies.get(dir_idx, 279)
            head_sprite_id = 100 + dir_idx
        
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


def main():
    """Main entry point"""
    print("PyReborn Pygame Client with Server Browser")
    print("==========================================")
    print()
    
    # Create and run client
    game = PygameClientWithBrowser()
    game.run()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())