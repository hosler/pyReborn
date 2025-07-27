"""
Classic Reborn Client - Main game client implementation
"""

import sys
import os
import pygame
import time
import logging
from typing import Optional, List

# Add the current directory to Python path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from pyreborn.protocol.enums import Direction
from pyreborn.core.events import EventType

# Import core systems
from core import (
    ConnectionManagerNativeV2,
    Physics,
    InputManager
)
from core.simple_renderer import SimpleGMAPRenderer
from core.connection import Level

# Use larger window size for Classic Reborn
SCREEN_WIDTH = 1600
SCREEN_HEIGHT = 1200

# Import managers
from managers import (
    AnimationManager,
    AudioManager,
    ItemManager,
    UIManager
)
# Note: GmapHandler removed - now using PyReborn's level manager directly

# Import game components
from game.state import GameState

# Import UI components
from ui import ServerBrowserState

# Import parsers
from parsers import GaniManager, TileDefs

# Import systems
from systems import BushHandler

logger = logging.getLogger(__name__)


class ClassicRebornClient:
    """Main game client that coordinates all modules"""
    
    def __init__(self):
        """Initialize the game client"""
        pygame.init()
        pygame.display.set_caption("Classic Reborn")
        
        # Initialize display
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.clock = pygame.time.Clock()
        self.running = True  # Start as running
        
        # Game state
        self.show_server_browser = True
        self.server_browser_state = ServerBrowserState(self.screen)
        
        # Defer initialization of game systems until after server selection
        self.game_initialized = False
        
        # Debug mode flag
        self.debug_mode = True  # Start with debug mode on
        
        # Movement throttling
        self.last_move_sent = 0
        self.move_send_interval = 0.05  # Send movement updates at 20Hz max
        self.was_moving = False  # Track if player was moving last frame
        
        # PyReborn client reference (set after connection)
        self.client = None
        
        # Connection defaults
        self.default_server = "localhost"
        self.default_port = 14900
        self.default_version = "2.1"
        
        # GMAP mode setting
        self.gmap_enabled = True  # Default to enabled
        
        logger.info("Classic Reborn Client initialized")
    
    def _init_game_systems(self):
        """Initialize game systems after server selection"""
        if self.game_initialized:
            return
            
        logger.info("Initializing game systems...")
        self._init_managers()
        self._init_systems()
        self._setup_callbacks()
        self.game_initialized = True
        logger.info("Game systems initialized")
    
    @property 
    def level_manager(self):
        """Get PyReborn's level manager"""
        if hasattr(self, 'connection_manager') and self.connection_manager and self.connection_manager.client:
            return self.connection_manager.client.level_manager
        return None
    
    @property
    def gmap_handler(self):
        """Compatibility property - returns level manager for game logic that needs GMAP access"""
        # Simple adapter for backward compatibility
        class GmapAdapter:
            def __init__(self, level_manager):
                self.level_manager = level_manager
            
            @property 
            def level_objects(self):
                return self.level_manager.levels if self.level_manager else {}
            
            @property
            def level_adjacency(self):
                return self.level_manager.level_adjacency if self.level_manager else {}
            
            @property
            def current_gmap(self):
                return self.level_manager.current_gmap if self.level_manager else None
            
            @current_gmap.setter
            def current_gmap(self, value):
                # PyReborn's level_manager handles GMAP tracking internally
                # This setter is here for compatibility but doesn't need to do anything
                pass
            
            @property
            def connection_gmap_data(self):
                """Convert PyReborn's gmap_data to renderer-compatible format"""
                if not self.level_manager or not self.level_manager.gmap_data:
                    return {}
                
                result = {}
                for gmap_name, gmap_parser in self.level_manager.gmap_data.items():
                    # Build level_map: level_name -> (col, row)
                    level_map = {}
                    position_map = {}
                    
                    for row in range(gmap_parser.height):
                        for col in range(gmap_parser.width):
                            segment_name = gmap_parser.get_segment_at(col, row)
                            if segment_name:
                                level_map[segment_name] = (col, row)
                                position_map[(col, row)] = segment_name
                    
                    gmap_key = f"{gmap_name}.gmap"
                    result[gmap_key] = {
                        'level_map': level_map,
                        'position_map': position_map,
                        'width': gmap_parser.width,
                        'height': gmap_parser.height
                    }
                
                return result
            
            @connection_gmap_data.setter
            def connection_gmap_data(self, value):
                # The adapter dynamically generates this data from PyReborn's level_manager
                # This setter is here for compatibility but doesn't need to do anything
                pass
            
            @property
            def gmap_width(self):
                """Get width of current GMAP"""
                if self.level_manager and self.level_manager.current_gmap:
                    gmap_name = self.level_manager.current_gmap.replace('.gmap', '')
                    if gmap_name in self.level_manager.gmap_data:
                        return self.level_manager.gmap_data[gmap_name].width
                return 1
            
            @gmap_width.setter
            def gmap_width(self, value):
                # The adapter dynamically gets width from PyReborn's level_manager
                # This setter is here for compatibility but doesn't need to do anything
                pass
            
            @property
            def gmap_height(self):
                """Get height of current GMAP"""
                if self.level_manager and self.level_manager.current_gmap:
                    gmap_name = self.level_manager.current_gmap.replace('.gmap', '')
                    if gmap_name in self.level_manager.gmap_data:
                        return self.level_manager.gmap_data[gmap_name].height
                return 1
            
            @gmap_height.setter
            def gmap_height(self, value):
                # The adapter dynamically gets height from PyReborn's level_manager
                # This setter is here for compatibility but doesn't need to do anything
                pass
            
            def is_gmap_level(self, level_name: str) -> bool:
                return self.level_manager.is_gmap_level(level_name) if self.level_manager else False
            
            def parse_segment_name(self, level_name: str):
                return self.level_manager.parse_segment_name(level_name) if self.level_manager else None
            
            def get_gmap_info(self):
                return self.level_manager.get_gmap_info() if self.level_manager else {}
            
            def get_segment_name(self, seg_x: int, seg_y: int) -> str:
                if self.level_manager and self.level_manager.current_gmap:
                    base_name = self.level_manager.current_gmap.replace('.gmap', '') if self.level_manager.current_gmap.endswith('.gmap') else self.level_manager.current_gmap
                    return self.level_manager.get_segment_name(base_name, seg_x, seg_y)
                return ""
            
            def get_level_object(self, level_name: str):
                return self.level_manager.get_level(level_name) if self.level_manager else None
            
            # Add other methods for compatibility
            def add_level(self, level_name: str, level_obj):
                pass  # PyReborn manages this automatically
            
            def set_current_level(self, level_name: str):
                pass  # PyReborn manages this automatically
            
            def update_position_from_level(self, level_name: str):
                pass  # PyReborn manages this automatically
            
            def update_level_from_name(self, level_name: str, level_obj):
                pass  # PyReborn manages this automatically
            
            def get_segments_to_request(self):
                # This is game logic - determine which segments to request based on player position
                if not self.level_manager or not self.level_manager.current_level or not self.level_manager.is_on_gmap:
                    return set()
                
                # Get current segment coordinates
                segment_info = self.level_manager.get_gmap_segment_coords(self.level_manager.current_level.name)
                if not segment_info:
                    return set()
                
                gmap_name, seg_x, seg_y = segment_info
                
                # Request adjacent segments (game logic)
                to_request = set()
                for dx in [-1, 0, 1]:
                    for dy in [-1, 0, 1]:
                        if dx == 0 and dy == 0:
                            continue
                        
                        adj_x, adj_y = seg_x + dx, seg_y + dy
                        if adj_x >= 0 and adj_y >= 0:
                            adj_segment = self.level_manager.get_segment_name(gmap_name, adj_x, adj_y)
                            if adj_segment not in self.level_manager.levels:
                                to_request.add(adj_segment)
                
                return to_request
            
            def mark_segment_requested(self, segment_name: str):
                pass  # PyReborn manages this automatically
            
            def clear_cache(self):
                pass  # PyReborn manages its own cache
            
            def parse_gmap_file(self, filename: str, data: bytes):
                pass  # PyReborn handles GMAP parsing automatically
        
        lm = self.level_manager
        return GmapAdapter(lm) if lm else None
    
    def _init_managers(self):
        """Initialize all game managers"""
        # Initialize in correct order
        # 1. Basic systems first
        self.tile_defs = TileDefs()
        # GANI manager needs the base directory, not assets/levels
        import os
        base_path = os.path.dirname(os.path.abspath(__file__))  # game directory
        base_path = os.path.dirname(base_path)  # classic_reborn directory
        self.gani_manager = GaniManager(base_path)
        
        # 2. Core systems
        self.connection_manager = ConnectionManagerNativeV2()
        self.game_state = GameState()
        self.physics = Physics(self.tile_defs)
        self.input_manager = InputManager()
        
        # 3. Managers that depend on other systems
        self.animation_manager = AnimationManager(self.gani_manager)
        self.audio_manager = AudioManager()
        self.ui_manager = UIManager(self.screen)
        self.item_manager = ItemManager()
        
        # 4. Special systems
        self.bush_handler = BushHandler()
        self.player_props_window = None
        
        # 5. Simple renderer (clean PyReborn-focused approach)
        self.renderer = SimpleGMAPRenderer(self.screen)
        # Give renderer access to game state for player rendering
        self.renderer.game_state = self.game_state
        
        # Give connection manager access to renderer for tileset updates
        self.connection_manager.renderer = self.renderer
        
        # Load local tileset immediately at startup
        self._try_load_local_tileset()
        
    def _init_systems(self):
        """Initialize game systems with references"""
        # Set up cross-references between systems
        self.physics.game_state = self.game_state
        self.physics.tile_defs = self.tile_defs
        self.physics.gmap_handler = self.gmap_handler
        
        # Simple renderer doesn't need complex references - it uses client directly
        
        self.ui_manager.game_state = self.game_state
        self.ui_manager.audio_manager = self.audio_manager
        
        self.item_manager.game_state = self.game_state
        self.item_manager.audio_manager = self.audio_manager
        
        self.animation_manager.gani_manager = self.gani_manager
        
    def _setup_callbacks(self):
        """Setup all callbacks between systems"""
        # Connection callbacks
        self._setup_connection_callbacks()
        
        # Input callbacks
        self._setup_input_callbacks()
        
    def _setup_connection_callbacks(self):
        """Setup connection manager callbacks"""
        self.connection_manager.on_connected = self._on_connected
        self.connection_manager.on_disconnected = self._on_disconnected
        self.connection_manager.on_connection_failed = self._on_connection_failed
        self.connection_manager.on_level_received = self._on_level_received
        
        # Subscribe to player events - will be done when connected
        # Events aren't available until after connection is established
        
    def _setup_input_callbacks(self):
        """Setup input manager callbacks"""
        self.input_manager.on_attack = self._handle_attack
        self.input_manager.on_grab = self._handle_grab
        self.input_manager.on_grab_release = self._handle_grab_release
        self.input_manager.on_chat_send = self._handle_chat_send
        self.input_manager.on_quit = self._handle_quit
        # ... more callbacks as needed
        
    def run(self, args: List[str]):
        """Main game loop"""
        # Parse command line arguments
        self._parse_args(args)
        
        # Show server browser or connect directly
        if self.show_server_browser:
            self._run_server_browser()
            # If we exit server browser without selecting a server, quit
            if self.show_server_browser:
                return
            # Server was selected, connect to it
            self._connect_to_server()
        else:
            # Set server info from defaults/command line args
            self.server_host = self.default_server
            self.server_port = self.default_port
            self.server_version = self.default_version
            self._connect_to_server()
        
        # Only run main game loop if connected to a server
        if self.game_initialized:
            # Main game loop
            while self.running:
                self._update()
                self._render()
                self.clock.tick(60)  # 60 FPS
        
        # Cleanup
        self._cleanup()
        
    def _parse_args(self, args: List[str]):
        """Parse command line arguments"""
        # Basic argument parsing
        if len(args) >= 2:
            self.account = args[0]
            self.password = args[1]
            self.show_server_browser = False
            
            # Parse additional options
            i = 2
            while i < len(args):
                if args[i] == '--server' and i + 1 < len(args):
                    self.default_server = args[i + 1]
                    i += 2
                elif args[i] == '--port' and i + 1 < len(args):
                    self.default_port = int(args[i + 1])
                    i += 2
                elif args[i] == '--version' and i + 1 < len(args):
                    self.default_version = args[i + 1]
                    i += 2
                elif args[i] == '--no-gmap':
                    self.gmap_enabled = False
                    logger.info("GMAP mode disabled via command line")
                    i += 1
                else:
                    i += 1
        else:
            self.show_server_browser = True
            
    def _run_server_browser(self):
        """Run the server browser"""
        # Show instructions
        logger.info("Server Browser: Press F5 to refresh server list, or enter username/password and press Enter")
        logger.info(f"Screen size: {self.screen.get_width()}x{self.screen.get_height()}")
        logger.info("Entering server browser loop...")
        
        # Basic server browser display
        while self.show_server_browser and self.running:
            # Handle events
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                    break
                    
                # Let server browser handle the event
                result = self.server_browser_state.handle_event(event)
                if result == 'connect':
                    # Get selected server info
                    server_info = self.server_browser_state.get_selected_server()
                    if server_info:
                        host, port, version = server_info
                        self.server_host = host
                        self.server_port = port
                        self.server_version = version
                        self.account = self.server_browser_state.username
                        self.password = self.server_browser_state.password
                        self.show_server_browser = False
                        # Will connect after exiting browser loop
                        break
                elif result == 'quit':
                    self.running = False
                    break
            
            # Render
            try:
                # First fill with a test color to make sure rendering is happening
                self.screen.fill((0, 50, 0))  # Dark green to test
                
                # Draw a test rectangle
                pygame.draw.rect(self.screen, (0, 255, 0), (10, 10, 100, 50))
                
                # Now draw the server browser
                self.server_browser_state.draw()
            except Exception as e:
                logger.error(f"Error drawing server browser: {e}", exc_info=True)
                # Fallback - show error on screen
                self.screen.fill((50, 0, 0))  # Dark red
                font = pygame.font.Font(None, 36)
                error_text = font.render(f"Server Browser Error: {str(e)}", True, (255, 255, 255))
                self.screen.blit(error_text, (50, 50))
            
            pygame.display.flip()
            self.clock.tick(60)
        
    def _connect_to_server(self):
        """Connect to the game server"""
        # Initialize game systems before connecting
        self._init_game_systems()
        
        # Connect to server
        host = getattr(self, 'server_host', self.default_server)
        port = getattr(self, 'server_port', self.default_port)
        version = getattr(self, 'server_version', self.default_version)
        
        logger.info(f"Connecting to {host}:{port} with version {version}")
        
        # Create client and connect asynchronously
        self.connection_manager.connect_async(host, port, self.account, self.password, version, self.gmap_enabled)
        
        # Wait for connection to establish
        max_wait = 5.0  # 5 seconds timeout
        wait_time = 0.0
        while wait_time < max_wait and not self.connection_manager.is_connected:
            time.sleep(0.1)
            wait_time += 0.1
        
        if not self.connection_manager.is_connected:
            logger.error("Failed to connect to server within timeout")
            self.running = False
        else:
            logger.info("Successfully connected to server")
        
    def _update(self):
        """Update game state"""
        # Handle events
        events = pygame.event.get()
        for event in events:
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_F3:
                    self.debug_mode = not self.debug_mode
                    logger.info(f"Debug mode: {self.debug_mode}")
                elif event.key == pygame.K_g:
                    # GMAP grid overlay not supported in simple renderer
                    logger.info("GMAP grid overlay not supported in simple renderer")
                elif event.key == pygame.K_r:
                    # Manually request adjacent levels (for debugging)
                    if hasattr(self.connection_manager.client, 'level_manager'):
                        logger.info("[DEBUG] Manually requesting adjacent levels")
                        self.connection_manager.client.level_manager.request_adjacent_levels()
                elif event.key == pygame.K_m:
                    # Toggle bird's eye view - check if we're actually in GMAP mode
                    current_level_name = self.game_state.current_level.name if self.game_state.current_level else "None"
                    
                    # M key pressed - toggle bird's eye view
                    
                    # Check PyReborn's level manager for GMAP state
                    is_gmap_level = False
                    if hasattr(self, 'client') and self.client:
                        if hasattr(self.client, 'level_manager') and hasattr(self.client.level_manager, 'is_on_gmap'):
                            is_gmap_level = self.client.level_manager.is_on_gmap
                            # Check GMAP state from PyReborn
                    
                    if is_gmap_level:
                        # Toggling bird's eye view
                        
                        # Get GMAP name from level manager
                        gmap_name = 'unknown'
                        if self.client.level_manager.current_gmap:
                            # current_gmap includes .gmap extension, remove it
                            gmap_name = self.client.level_manager.current_gmap.replace('.gmap', '')
                        
                        if self.gmap_handler.current_gmap != gmap_name:
                            # Update GMAP handler
                            self.gmap_handler.current_gmap = gmap_name
                            
                        # Update GMAP dimensions from PyReborn data
                        if gmap_name in self.client.level_manager.gmap_data:
                            gmap_parser = self.client.level_manager.gmap_data[gmap_name]
                            self.gmap_handler.gmap_width = gmap_parser.width
                            self.gmap_handler.gmap_height = gmap_parser.height
                            logger.info(f"Updated GMAP dimensions: {gmap_parser.width}x{gmap_parser.height}")
                            
                            # Sync loaded levels from PyReborn to gmap_handler
                            synced_count = 0
                            
                            # First check if the current level is part of the GMAP and add it
                            current_level = self.client.level_manager.current_level
                            if current_level and current_level.name in gmap_parser.segments:
                                # Debug: Check if current level has board data
                                has_board_data = hasattr(current_level, 'board_tiles_64x64') and current_level.board_tiles_64x64
                                board_data_len = len(current_level.board_tiles_64x64) if has_board_data else 0
                                logger.info(f"Current level {current_level.name}: has_board_data={has_board_data}, length={board_data_len}")
                                
                                # Add current level to GMAP handler
                                self.gmap_handler.add_level(current_level.name, current_level)
                                logger.info(f"Added current level {current_level.name} to GMAP handler")
                                synced_count += 1
                            
                            # Then sync all other loaded levels
                            for segment_name in gmap_parser.segments:
                                if segment_name in self.client.level_manager.levels:
                                    # Use PyReborn level directly - it has all the methods we need
                                    pyreborn_level = self.client.level_manager.levels[segment_name]
                                    self.gmap_handler.add_level(segment_name, pyreborn_level)
                                    logger.info(f"Added PyReborn level {segment_name} to GMAP handler")
                                    synced_count += 1
                            # Synced levels to GMAP handler
                        
                        self.renderer.toggle_birds_eye()
                        # Zoom level updated
                    else:
                        pass  # Bird's eye view only available in GMAP mode
        
        # Only update game systems if initialized
        if self.game_initialized:
            # Update input
            for event in events:
                self.input_manager.handle_event(event)
            
            # Update connection
            # TODO: self.connection_manager.update()
            
            # Update PyReborn's level manager (for file request processing)
            # Use the real PyReborn client's level manager, not the mock
            if hasattr(self, 'client') and self.client:
                if hasattr(self.client, 'level_manager'):
                    self.client.level_manager.update()
                elif hasattr(self.client, 'managers') and hasattr(self.client.managers, 'level'):
                    # V2 client structure
                    self.client.managers.level.update()
                
                # Sync GMAP levels from PyReborn to our GmapHandler
                if hasattr(self.client, 'level_manager') and self.client.level_manager.is_on_gmap and self.gmap_handler:
                    # Get the current GMAP name
                    if self.client.level_manager.current_gmap:
                        gmap_name = self.client.level_manager.current_gmap.replace('.gmap', '')
                        
                        # Get GMAP parser to know which levels belong to this GMAP
                        if gmap_name in self.client.level_manager.gmap_data:
                            gmap_parser = self.client.level_manager.gmap_data[gmap_name]
                            
                            # Sync all segments that belong to this GMAP
                            for segment_name in gmap_parser.segments:
                                if segment_name in self.client.level_manager.levels:
                                    pyreborn_level = self.client.level_manager.levels[segment_name]
                                    
                                    # Add to gmap_handler if not already there
                                    if segment_name not in self.gmap_handler.level_objects:
                                        # Use PyReborn level directly - it has all the methods we need
                                        self.gmap_handler.add_level(segment_name, pyreborn_level)
                                        logger.info(f"Synced level {segment_name} from PyReborn to GmapHandler")
            
            # Update game systems
            if self.game_state.local_player:
                self._update_movement()
                self._update_animation()
                
            # Update managers
            current_time = time.time()
            if hasattr(self.ui_manager, 'update'):
                self.ui_manager.update()
            if hasattr(self.item_manager, 'update'):
                self.item_manager.update(current_time)
                
            # Periodically check PyReborn's player list and sync
            if not hasattr(self, '_last_player_sync') or current_time - self._last_player_sync > 1:  # Check every second
                if self.client and hasattr(self.client, 'players'):
                    pyreborn_count = len(self.client.players)
                    game_state_count = len(self.game_state.players)
                    
                    # Always sync all players to ensure we have latest data
                    for player_id, pyreborn_player in self.client.players.items():
                        # Always update/add player to ensure we have latest position data
                        self.game_state.players[player_id] = pyreborn_player
                        
                    # Remove players that no longer exist in PyReborn
                    for player_id in list(self.game_state.players.keys()):
                        if player_id not in self.client.players and player_id != self.game_state.local_player_id:
                            del self.game_state.players[player_id]
                            logger.info(f"[SYNC] Removed player no longer in PyReborn: {player_id}")
                    
                    # Log sync status
                    if pyreborn_count != game_state_count:
                        logger.info(f"[SYNC] Synced players - PyReborn: {pyreborn_count}, GameState: {len(self.game_state.players)}")
                        
                    # Debug player positions every 5 seconds
                    if not hasattr(self, '_last_player_pos_debug') or current_time - self._last_player_pos_debug > 5:
                        logger.info(f"[PLAYER POSITIONS] {len(self.client.players)} players in PyReborn:")
                        for pid, p in self.client.players.items():
                            logger.info(f"  Player {pid}: {p.nickname} at ({p.x},{p.y}) world:({getattr(p, 'x2', 'None')},{getattr(p, 'y2', 'None')})")
                        self._last_player_pos_debug = current_time
                else:
                    logger.debug(f"[SYNC CHECK] No client or players: client={self.client is not None}, has_players={hasattr(self.client, 'players') if self.client else False}")
                self._last_player_sync = current_time
            
            # Simple renderer doesn't need transition updates - instant toggle
        
    def _render(self):
        """Render the game"""
        # Clear screen - brighter color in debug mode
        if self.debug_mode:
            self.screen.fill((0, 64, 128))  # Brighter blue for debug
        else:
            self.screen.fill((0, 0, 0))  # Black for normal
        
        # Debug info overlay
        if self.debug_mode:
            # Add debug text to show what state we're in
            font = pygame.font.Font(None, 36)
            debug_y = 10
            
            # Show current state
            if self.show_server_browser:
                debug_text = font.render("State: Server Browser", True, (255, 255, 255))
                self.screen.blit(debug_text, (10, debug_y))
                debug_y += 40
                
            if self.game_initialized:
                debug_text = font.render("State: Game Initialized", True, (0, 255, 0))
                self.screen.blit(debug_text, (10, debug_y))
                debug_y += 40
                
                if self.game_state.current_level:
                    # Strip null characters and whitespace from level name for display
                    level_name = self.game_state.current_level.name.rstrip('\x00').strip()
                    debug_text = font.render(f"Level: {level_name}", True, (0, 255, 0))
                    self.screen.blit(debug_text, (10, debug_y))
                    debug_y += 40
                    
                if self.game_state.local_player:
                    debug_text = font.render(f"Player: ({self.game_state.local_player.x:.1f}, {self.game_state.local_player.y:.1f})", True, (0, 255, 0))
                    self.screen.blit(debug_text, (10, debug_y))
                    debug_y += 40
                    
                # Additional debug info
                debug_text = font.render(f"Connection: {self.connection_manager.is_connected}", True, (255, 255, 0))
                self.screen.blit(debug_text, (10, debug_y))
                debug_y += 40
                
                debug_text = font.render(f"Screen: {self.screen.get_width()}x{self.screen.get_height()}", True, (255, 255, 0))
                self.screen.blit(debug_text, (10, debug_y))
                debug_y += 40
                
                # Show debug mode toggle hint
                debug_text = font.render("Press F3 to toggle debug mode", True, (255, 255, 0))
                self.screen.blit(debug_text, (10, self.screen.get_height() - 40))
            
            # Draw multiple borders to be more visible
            pygame.draw.rect(self.screen, (255, 0, 0), (0, 0, self.screen.get_width(), self.screen.get_height()), 5)
            pygame.draw.rect(self.screen, (255, 255, 0), (10, 10, self.screen.get_width() - 20, self.screen.get_height() - 20), 3)
            
            # Draw diagonal lines to confirm rendering
            pygame.draw.line(self.screen, (0, 255, 0), (0, 0), (self.screen.get_width(), self.screen.get_height()), 3)
            pygame.draw.line(self.screen, (0, 255, 0), (self.screen.get_width(), 0), (0, self.screen.get_height()), 3)
        
        # Render server browser if active
        if self.show_server_browser and self.server_browser_state:
            self.server_browser_state.draw()
        # Only render game if initialized
        elif self.game_initialized and self.game_state.current_level:
            # Try to load local tileset if not already loaded
            if not self.renderer.tileset:
                self._try_load_local_tileset()
            # Update camera position if we have a local player
            if self.game_state.local_player:
                # Check GMAP mode from PyReborn client
                is_gmap = False
                if hasattr(self.connection_manager, 'client') and self.connection_manager.client:
                    if hasattr(self.connection_manager.client, 'is_gmap_mode'):
                        is_gmap = self.connection_manager.client.is_gmap_mode
                    else:
                        # Fallback to GMAP handler detection
                        is_gmap = self.gmap_handler.is_gmap_level(self.game_state.current_level.name)
                else:
                    is_gmap = self.gmap_handler.is_gmap_level(self.game_state.current_level.name)
                
                # Always use player's actual coordinates
                # PyReborn handles the conversion between local and world coords
                camera_x = self.game_state.local_player.x
                camera_y = self.game_state.local_player.y
                
                # If we have world coordinates from PyReborn, use those
                if is_gmap and hasattr(self.game_state.local_player, 'x2') and self.game_state.local_player.x2 is not None:
                    camera_x = self.game_state.local_player.x2
                    camera_y = self.game_state.local_player.y2
                    pass  # Debug logging removed - too spammy
                
                # Debug camera update - reduced frequency
                if not hasattr(self, '_last_cam_debug') or time.time() - self._last_cam_debug > 5:
                    logger.debug(f"Camera update: player at ({self.game_state.local_player.x:.1f}, {self.game_state.local_player.y:.1f})")
                    if is_gmap:
                        logger.debug(f"World coords: ({camera_x:.1f}, {camera_y:.1f})")
                    self._last_cam_debug = time.time()
                    
                # Simple renderer doesn't need camera updates - it calculates positions directly
            
            # Draw GMAP levels if applicable, otherwise draw single level
            if self.gmap_handler.current_gmap:
                # Only log periodically to avoid spam - reduced to every 10 seconds
                if not hasattr(self, '_last_gmap_render_debug') or time.time() - self._last_gmap_render_debug > 10:
                    logger.debug(f"Drawing GMAP {self.gmap_handler.current_gmap} with {len(self.gmap_handler.level_objects)} levels")
                    self._last_gmap_render_debug = time.time()
                
                # Simple renderer handles everything - GMAP and single level
                # Use PyReborn's current level as the authoritative source
                pyreborn_level = self.client.level_manager.current_level if self.client and self.client.level_manager else None
                current_level_name = pyreborn_level.name if pyreborn_level else "unknown"
                player_x = self.game_state.local_player.x if self.game_state.local_player else 30.0
                player_y = self.game_state.local_player.y if self.game_state.local_player else 30.0
                
                self.renderer.render_gmap(self.client, current_level_name, player_x, player_y)
            else:
                # Not in GMAP mode - simple renderer handles this too
                # Use PyReborn's current level as the authoritative source
                pyreborn_level = self.client.level_manager.current_level if self.client and self.client.level_manager else None
                current_level_name = pyreborn_level.name if pyreborn_level else "unknown"
                player_x = self.game_state.local_player.x if self.game_state.local_player else 30.0
                player_y = self.game_state.local_player.y if self.game_state.local_player else 30.0
                
                self.renderer.render_gmap(self.client, current_level_name, player_x, player_y)
                
                # Log why we're not drawing GMAP
                if not hasattr(self, '_last_gmap_debug') or time.time() - self._last_gmap_debug > 2:
                    logger.debug(f"Not drawing GMAP: current_gmap={self.gmap_handler.current_gmap}")
                    if self.game_state.current_level:
                        logger.debug(f"Current level: {self.game_state.current_level.name}")
                        logger.debug(f"Is GMAP level: {self.gmap_handler.is_gmap_level(self.game_state.current_level.name)}")
                    self._last_gmap_debug = time.time()
            
            # Simple renderer handles items internally - no separate draw call needed
            
            # Simple renderer handles players internally - no separate draw call needed
            
            # Draw UI elements
            if hasattr(self.ui_manager, 'draw'):
                self.ui_manager.draw()
        
        # Flip display
        pygame.display.flip()
        
    def _cleanup(self):
        """Clean up resources"""
        if self.game_initialized:
            self.connection_manager.disconnect()
            # TODO: self.audio_manager.cleanup()
        pygame.quit()
        
    # Event handlers
    def _on_connected(self, connection_manager):
        """Handle successful connection"""
        logger.info("Connected to server")
        # Store reference to the PyReborn client for direct access
        self.client = connection_manager.client
        logger.info(f"PyReborn client reference: {self.client}")
        logger.info(f"Has 'players' attribute: {hasattr(self.client, 'players') if self.client else False}")
        if self.client and hasattr(self.client, 'players'):
            logger.info(f"Initial PyReborn players: {len(self.client.players)}")
        
        
        
        # Subscribe to events now that we're connected
        if self.client and hasattr(self.client, 'events'):
            events = self.client.events
            if events:
                # Player events - use EventType enum values
                events.subscribe(EventType.PLAYER_ADDED, self._on_player_join)
                events.subscribe(EventType.PLAYER_REMOVED, self._on_player_leave)  
                events.subscribe(EventType.PLAYER_UPDATE, self._on_player_moved)  # Local player updates
                events.subscribe(EventType.OTHER_PLAYER_UPDATE, self._on_other_player_moved)  # Other player updates
                events.subscribe(EventType.PLAYER_PROPS_UPDATE, self._on_player_props)
                
                # Level events
                events.subscribe(EventType.LEVEL_BOARD_LOADED, self._on_level_board_loaded)
                events.subscribe(EventType.FILE_RECEIVED, self._on_file_received)
                logger.info("Subscribed to all events including level and file events")
                
                # List all available events
                if hasattr(events, '_subscribers'):
                    logger.info(f"Available events: {list(events._subscribers.keys())}")
        elif hasattr(connection_manager, '_client') and connection_manager._client:
            # Try accessing internal client
            events = connection_manager._client.events
            if events:
                events.subscribe('player_join', self._on_player_join)
                events.subscribe('player_leave', self._on_player_leave)  
                events.subscribe('player_moved', self._on_player_moved)
                events.subscribe('player_props', self._on_player_props)
            
        # Get local player info
        logger.info(f"Checking for local player in connection_manager")
        logger.info(f"Has local_player attr: {hasattr(connection_manager, 'local_player')}")
        if hasattr(connection_manager, 'local_player'):
            logger.info(f"Local player value: {connection_manager.local_player}")
            if connection_manager.local_player:
                self.game_state.local_player = connection_manager.local_player
                self.game_state.local_player_id = connection_manager.local_player.id
                self.game_state.add_player(connection_manager.local_player)
                logger.info(f"Local player set: {connection_manager.local_player.nickname} (ID: {connection_manager.local_player.id})")
                logger.info(f"Players in game state: {len(self.game_state.players)}")
                
                # Sync all existing players from PyReborn
                if self.client and hasattr(self.client, 'players'):
                    logger.info(f"Syncing {len(self.client.players)} players from PyReborn")
                    for player_id, player in self.client.players.items():
                        if player_id not in self.game_state.players:
                            self.game_state.add_player(player)
                            logger.info(f"Added existing player: {player.nickname if hasattr(player, 'nickname') else 'Unknown'} (ID: {player.id})")
                    logger.info(f"Game state now has {len(self.game_state.players)} total players")
                
                # Simple renderer doesn't need camera initialization - calculates positions dynamically
                
                # Load local tileset immediately as fallback
                self._try_load_local_tileset()
            else:
                logger.warning("connection_manager.local_player is None!")
        else:
            logger.error("connection_manager has no local_player attribute!")
        
    def _try_load_local_tileset(self):
        """Try to load local tileset from assets folder or PyReborn cache"""
        import os
        import pygame
        
        logger.info("Attempting to load local tileset...")
        
        # Don't load if we already have a good tileset
        if self.renderer.tileset:
            logger.info("Tileset already loaded, skipping local load")
            return
            
        # Try different tileset names in order of preference
        tileset_names = ['pics1.png', 'dustynewpics1.png']
        # Get the classic_reborn directory, then go to assets
        current_file_dir = os.path.dirname(os.path.abspath(__file__))  # game/
        parent_dir = os.path.dirname(current_file_dir)  # classic_reborn/
        assets_dir = os.path.join(parent_dir, 'assets')
        
        logger.info(f"Looking for tilesets in: {assets_dir}")
        
        # First try assets directory
        for tileset_name in tileset_names:
            tileset_path = os.path.join(assets_dir, tileset_name)
            if os.path.exists(tileset_path):
                try:
                    tileset_surface = pygame.image.load(tileset_path)
                    width, height = tileset_surface.get_size()
                    if width >= 512 and height >= 512:
                        self.renderer.tileset = tileset_surface
                        logger.info(f"Loaded local tileset: {tileset_name} ({width}x{height})")
                        return
                    else:
                        logger.warning(f"Local tileset {tileset_name} has invalid size: {width}x{height}")
                except (pygame.error, OSError) as e:
                    logger.warning(f"Failed to load local tileset {tileset_name}: {e}")
        
        # Try PyReborn's cache directory for any tileset PNG
        if hasattr(self.connection_manager, 'client') and self.connection_manager.client:
            try:
                asset_paths = self.connection_manager.client.get_asset_paths()
                images_dir = asset_paths.get('images')
                if images_dir and os.path.exists(str(images_dir)):
                    logger.info(f"Checking PyReborn cache for tilesets: {images_dir}")
                    # Look for any tileset PNG in cache
                    for filename in os.listdir(str(images_dir)):
                        if filename.endswith('.png') and ('tile' in filename.lower() or 'pics' in filename.lower()):
                            cache_path = os.path.join(str(images_dir), filename)
                            try:
                                tileset_surface = pygame.image.load(cache_path)
                                width, height = tileset_surface.get_size()
                                if width >= 512 and height >= 512:
                                    self.renderer.tileset = tileset_surface
                                    logger.info(f"Loaded cached tileset: {filename} ({width}x{height})")
                                    return
                            except Exception as e:
                                logger.warning(f"Failed to load cached tileset {filename}: {e}")
            except Exception as e:
                logger.debug(f"Could not check PyReborn cache for tilesets: {e}")
        
        logger.warning("No valid local tileset found in assets folder or cache")

    def _on_disconnected(self):
        """Handle disconnection"""
        logger.info("Disconnected from server")
        self.running = False
        
    def _on_connection_failed(self, error_msg: str):
        """Handle connection failure"""
        logger.error(f"Connection failed: {error_msg}")
        self.running = False
        
    def _on_level_received(self, level):
        """Handle level received"""
        logger.info(f"Received level: {level.name}")
        
        # Smart level switching: set initial level, then only switch when player moves
        player = self.game_state.local_player
        
        # Always set the first level that comes in (no current level yet) 
        if not self.game_state.current_level:
            # Debug what's happening
            logger.info(f"[LEVEL_RECEIVED] No current level yet, checking {level.name}")
            logger.info(f"[LEVEL_RECEIVED] Player exists: {player is not None}")
            if player:
                logger.info(f"[LEVEL_RECEIVED] Player level property: {player.level if hasattr(player, 'level') else 'NO LEVEL ATTR'}")
            
            # But first check if this is actually the player's level
            if (player and hasattr(player, 'level') and 
                (player.level == level.name or player.level == level.name.replace('.nw', ''))):
                self.game_state.current_level = level
                logger.info(f"Set {level.name} as INITIAL current level (matches player level)")
            else:
                # For initial load, we might need to set it anyway if no player level yet
                if not player or not hasattr(player, 'level'):
                    self.game_state.current_level = level
                    logger.info(f"Set {level.name} as INITIAL current level (no player level to compare)")
                else:
                    logger.info(f"Received {level.name} but player is in {player.level}, not setting as current")
        # For other levels, only switch if we're sure the player moved there
        elif (player and hasattr(player, 'level') and 
              (player.level == level.name or player.level == level.name.replace('.nw', ''))):
            self.game_state.current_level = level
            logger.info(f"Set {level.name} as current level (player moved here)")
        # Otherwise, it's just a background GMAP level - don't switch to it
        else:
            logger.info(f"Level {level.name} loaded for GMAP/background (keeping current level)")
        
        # Physics uses level as parameter, not stored
        
        # Simple renderer gets level data directly from client - no need to store
        
        # Initialize GMAP if this is a GMAP level
        if self.gmap_handler.is_gmap_level(level.name):
            logger.info(f"Initializing GMAP for {level.name}")
            
            # If this is a .gmap file, enter the GMAP
            if level.name.endswith('.gmap'):
                self.gmap_handler.enter_gmap(level.name)
                logger.info(f"Entered GMAP: {level.name}")
            else:
                # This is a GMAP segment - add it to the handler
                self.gmap_handler.add_level(level.name, level)
                logger.info(f"Added GMAP segment {level.name} to handler")
            
            # Update GMAP handler with connection data
            if hasattr(self.connection_manager, 'connection_gmap_data'):
                self.gmap_handler.connection_gmap_data = self.connection_manager.connection_gmap_data
            
            # Add level to GMAP handler for adjacent rendering
            self.gmap_handler.add_level(level.name, level)
            logger.info(f"Added level {level.name} to GMAP handler")
            
            # Update GMAP position
            self.gmap_handler.update_position_from_level(level.name)
        else:
            # Handle both GMAP and non-GMAP levels
            # Try to update position in case we're entering a GMAP
            self.gmap_handler.update_position_from_level(level.name)
        
    def _handle_attack(self):
        """Handle attack action"""
        # TODO: Implement attack
        pass
        
    def _handle_grab(self):
        """Handle grab action"""
        # TODO: Implement grab
        pass
        
    def _handle_grab_release(self):
        """Handle grab release"""
        # TODO: Implement grab release
        pass
        
    def _handle_chat_send(self, message: str):
        """Handle chat message"""
        # TODO: Implement chat
        pass
        
    def _handle_quit(self):
        """Handle quit request"""
        self.running = False
        
    def _update_movement(self):
        """Update player movement"""
        if not self.game_state.local_player or not self.connection_manager.is_connected:
            return
            
        # Get keyboard state
        keys = pygame.key.get_pressed()
        
        # Get current position
        player = self.game_state.local_player
        current_x = player.x
        current_y = player.y
        
        # Calculate movement vector (allow diagonal movement)
        dx = 0
        dy = 0
        
        if keys[pygame.K_LEFT]:
            dx = -1
        if keys[pygame.K_RIGHT]:
            dx = 1
        if keys[pygame.K_UP]:
            dy = -1
        if keys[pygame.K_DOWN]:
            dy = 1
            
        # Update direction based on movement (prioritize last pressed or largest component)
        if dx != 0 or dy != 0:
            if abs(dx) > abs(dy):
                player.direction = Direction.LEFT if dx < 0 else Direction.RIGHT
            elif dy != 0:
                player.direction = Direction.UP if dy < 0 else Direction.DOWN
            # If moving diagonally with equal components, keep current direction
            
        # Apply movement if there's input
        if dx != 0 or dy != 0:
            # Calculate new position
            # Movement speed from constants
            from game.constants import ClassicConstants
            move_speed = ClassicConstants.MOVE_SPEED
            dt = 1.0 / 60.0  # 60 FPS
            
            # Normalize diagonal movement so it's not faster than cardinal movement
            if dx != 0 and dy != 0:
                # Diagonal movement - normalize by dividing by sqrt(2) ≈ 1.414
                diagonal_factor = 0.707  # 1/sqrt(2)
                new_x = current_x + dx * move_speed * dt * diagonal_factor
                new_y = current_y + dy * move_speed * dt * diagonal_factor
            else:
                # Cardinal movement
                new_x = current_x + dx * move_speed * dt
                new_y = current_y + dy * move_speed * dt
            
            # Update position locally - PyReborn will handle all GMAP logic
            player.x = new_x
            player.y = new_y
            
            # Send to server with throttling
            current_time = time.time()
            if current_time - self.last_move_sent >= self.move_send_interval:
                if hasattr(self.connection_manager, 'client') and self.connection_manager.client:
                    self.connection_manager.move_to(player.x, player.y, player.direction)
                    self.last_move_sent = current_time
            
            # Debug movement
            if not hasattr(self, '_last_move_debug') or time.time() - self._last_move_debug > 0.5:
                logger.info(f"Player moved to ({new_x:.2f}, {new_y:.2f})")
                self._last_move_debug = time.time()
            
            # Update animation
            if self.animation_manager:
                self.animation_manager.set_animation(player.id, 'walk', player.direction)
            
            # Track that we're moving
            self.was_moving = True
        else:
            # Player is not moving
            if self.was_moving:
                # Player just stopped - send final position immediately
                if hasattr(self.connection_manager, 'client') and self.connection_manager.client:
                    self.connection_manager.move_to(player.x, player.y, player.direction)
                    self.last_move_sent = time.time()
                
                # Update animation to idle
                if self.animation_manager:
                    self.animation_manager.set_animation(player.id, 'idle', player.direction)
                
                self.was_moving = False
        
    def _update_animation(self):
        """Update animations"""
        if not self.animation_manager:
            return
            
        # Update all player animations
        for player in self.game_state.players.values():
            # For non-local players, ensure they have animations
            if player.id != self.game_state.local_player_id:
                if not self.animation_manager.has_animation(player.id):
                    self.animation_manager.set_animation(player.id, 'idle', player.direction)
                    
        # Update animation frames
        self.animation_manager.update(1.0 / 60.0)  # 60 FPS delta
    
    # Player event handlers
    def _on_player_join(self, event):
        """Handle player join event"""
        logger.info(f"_on_player_join called with event: {event}")
        player = event.get('player')
        if player:
            self.game_state.add_player(player)
            logger.info(f"Player joined: {player.nickname if hasattr(player, 'nickname') else 'Unknown'} (ID: {player.id})")
            logger.info(f"Game state now has {len(self.game_state.players)} players")
            
            # Also ensure animation state is created for new player
            if self.animation_manager and player.id != self.game_state.local_player_id:
                self.animation_manager.set_animation(player.id, 'idle', Direction.DOWN)
        else:
            logger.warning(f"No player in join event: {event}")
    
    def _on_player_leave(self, event):
        """Handle player leave event"""
        player_id = event.get('player_id')
        if player_id:
            self.game_state.remove_player(player_id)
            logger.info(f"Player left: ID {player_id}")
    
    def _on_player_moved(self, event):
        """Handle local player movement event"""
        player = event.get('player')
        if player:
            logger.debug(f"Local player moved event: ID={player.id if hasattr(player, 'id') else '?'}, pos=({player.x if hasattr(player, 'x') else '?'},{player.y if hasattr(player, 'y') else '?'})")
            self.game_state.update_player(player)
    
    def _on_other_player_moved(self, event):
        """Handle other player movement event"""
        player = event.get('player')
        if player:
            # Log with more detail for debugging
            x_str = f"{player.x:.1f}" if hasattr(player, 'x') and player.x is not None else "None"
            y_str = f"{player.y:.1f}" if hasattr(player, 'y') and player.y is not None else "None"
            x2_str = f"{player.x2:.1f}" if hasattr(player, 'x2') and player.x2 is not None else "None"
            y2_str = f"{player.y2:.1f}" if hasattr(player, 'y2') and player.y2 is not None else "None"
            gx = player.gmaplevelx if hasattr(player, 'gmaplevelx') else "?"
            gy = player.gmaplevely if hasattr(player, 'gmaplevely') else "?"
            
            # Only log every 10th update to reduce spam, or if position changed significantly
            if not hasattr(self, '_last_other_player_log') or not hasattr(self, '_last_other_player_pos'):
                self._last_other_player_log = {}
                self._last_other_player_pos = {}
                
            player_id = player.id if hasattr(player, 'id') else 0
            last_pos = self._last_other_player_pos.get(player_id, (0, 0))
            
            # Check if position changed significantly
            current_x = player.x if hasattr(player, 'x') and player.x is not None else 0
            current_y = player.y if hasattr(player, 'y') and player.y is not None else 0
            distance = ((current_x - last_pos[0]) ** 2 + (current_y - last_pos[1]) ** 2) ** 0.5
            
            # Log if position changed by more than 1 tile or it's been more than 5 seconds
            import time
            current_time = time.time()
            last_log_time = self._last_other_player_log.get(player_id, 0)
            
            if distance > 1.0 or current_time - last_log_time > 5:
                logger.info(f"OTHER_PLAYER_UPDATE: ID={player.id if hasattr(player, 'id') else '?'}, {player.nickname if hasattr(player, 'nickname') else 'Unknown'} - local:({x_str},{y_str}) world:({x2_str},{y2_str}) gmap:[{gx},{gy}]")
                self._last_other_player_log[player_id] = current_time
                self._last_other_player_pos[player_id] = (current_x, current_y)
            
            # Update the player in our game state
            self.game_state.update_player(player)
    
    def _on_player_props(self, event):
        """Handle player properties update"""
        player = event.get('player')
        if player:
            self.game_state.update_player(player)
    
    def _on_level_board_loaded(self, event):
        """Handle level board loaded event from PyReborn"""
        level = event.get('level')
        if level:
            logger.info(f"Level board loaded: {level.name}")
            
            # Add to GMAP handler if it's a GMAP level
            if self.gmap_handler.is_gmap_level(level.name):
                self.gmap_handler.add_level(level.name, level)
                logger.info(f"Added level {level.name} to GMAP handler (board loaded)")
                
                # Update GMAP position
                self.gmap_handler.update_position_from_level(level.name)
                
                # Simple renderer gets level data directly from client - no trigger needed
    
    def _on_file_received(self, event):
        """Handle file received event"""
        filename = event.get('filename')
        data = event.get('data')
        if filename:
            logger.info(f"File received: {filename} ({len(data) if data else 0} bytes)")
            
            # Handle GMAP files
            if filename.endswith('.gmap'):
                self.gmap_handler.parse_gmap_file(filename, data)
                logger.info(f"Parsed GMAP file: {filename}")
            
            # Handle level files (.nw)
            elif filename.endswith('.nw'):
                # For level files, PyReborn should handle them automatically
                # But we need to check if it's a GMAP segment that needs syncing
                if self.gmap_handler.is_gmap_level(filename):
                    logger.info(f"Received GMAP segment file: {filename}")
                    # The level is automatically added to PyReborn's level manager
                    # We'll sync it in the update loop
            
            # Handle tileset updates
            elif filename.endswith('.png'):
                # Only load pics1.png as tileset, ignore other PNG files
                if filename == 'pics1.png' or (filename == 'dustynewpics1.png' and not self.renderer.tileset):
                    # Load tileset into simple renderer with corruption fallback
                    import pygame
                    import io
                    try:
                        tileset_surface = pygame.image.load(io.BytesIO(data))
                        # Verify the tileset is valid (reasonable size)
                        width, height = tileset_surface.get_size()
                        if width >= 512 and height >= 512:  # Standard tileset dimensions
                            self.renderer.tileset = tileset_surface
                            logger.info(f"Hot-loaded tileset: {filename}")
                            logger.info(f"Tileset size: {tileset_surface.get_size()}")
                        else:
                            logger.warning(f"Tileset {filename} has invalid size: {width}x{height}, requesting pics1.png")
                            if filename != 'pics1.png' and hasattr(self.client, 'request_file'):
                                self.client.request_file('pics1.png')
                    except (pygame.error, OSError) as e:
                        logger.error(f"Failed to load tileset {filename}: {e}")
                        if filename != 'pics1.png' and hasattr(self.client, 'request_file'):
                            logger.info("Requesting fallback tileset pics1.png")
                            self.client.request_file('pics1.png')
                else:
                    logger.debug(f"Ignoring non-tileset PNG: {filename}")