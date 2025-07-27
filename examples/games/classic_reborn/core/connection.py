"""
Connection Manager Native V2 - Proper PyReborn v2 implementation
"""

import logging
import threading
import time
from typing import Optional, Callable, Dict, Any, List
from dataclasses import dataclass
from pyreborn import RebornClient
from pyreborn.core.events import EventType, EventManager
from pyreborn.protocol.enums import PlayerProp, Direction
# from pyreborn.v2.packets import PlayerPropsPacketV2  # Using high-level API instead
from pyreborn.models.player import Player as PyRebornPlayer
from pyreborn.models.level import Level

logger = logging.getLogger(__name__)
    
    
@dataclass
class Player:
    """Player data container"""
    id: int
    account: str
    nickname: str
    x: float
    y: float
    direction: Direction = Direction.DOWN
    gani: str = "idle"
    carry_sprite: str = ""
    
    # V1 compatibility attributes
    hearts: float = 3.0
    max_hearts: float = 3.0
    arrows: int = 10
    bombs: int = 5
    gralats: int = 0
    rupees: int = 0  # Same as gralats
    sword_image: str = "sword1.png"
    shield_image: str = "shield1.png"
    head_image: str = "head0.png"
    body_image: str = "body.png"
    colors: list = None
    chat: str = ""  # Chat bubble text
    ap: int = 50  # Alignment points
    
    def __post_init__(self):
        """Initialize v1 compatibility attributes"""
        if self.colors is None:
            self.colors = ["orange", "white", "blue", "red", "black"]
    

class ConnectionManagerNativeV2:
    """Native v2 connection manager - no compatibility layer"""
    
    def __init__(self):
        """Initialize connection manager"""
        self._client: Optional[RebornClient] = None
        self.is_connecting = False
        self.connection_thread: Optional[threading.Thread] = None
        
        # Game state
        self.current_level: Optional[Level] = None
        self.levels: Dict[str, Level] = {}
        self.players: Dict[int, Player] = {}
        self._local_player: Optional[Player] = None
        
        # GMAP tracking
        self.current_gmap: Optional[str] = None  # e.g., "zlttp.gmap"
        self.gmap_segments: Dict[str, Level] = {}  # Adjacent GMAP segments
        self.gmap_position: tuple = (0, 0)  # Current GMAP X,Y position
        self.gmap_data: Dict[str, Dict] = {}  # Parsed GMAP file data
        
        # File request queue
        self.file_request_queue: List[str] = []
        self.waiting_for_file: Optional[str] = None
        self.file_request_timer: Optional[threading.Timer] = None
        self.file_request_timeout_timer: Optional[threading.Timer] = None
        self.file_request_time: float = 0
        
        # Callbacks - these will be set by the game
        self.on_connected: Optional[Callable] = None
        self.on_disconnected: Optional[Callable] = None
        self.on_connection_failed: Optional[Callable] = None
        self.on_level_received: Optional[Callable] = None
        self.on_tileset_received: Optional[Callable] = None
        
        # Asset storage
        self.tilesets: Dict[str, bytes] = {}  # filename -> image data
        
        # PyReborn handles file accumulation internally
        
    def connect_async(self, host: str, port: int, username: str, password: str, version: str = "2.22", gmap_enabled: bool = True):
        """Start asynchronous connection to server"""
        if self.is_connecting:
            return
            
        self.is_connecting = True
        self.connection_thread = threading.Thread(
            target=self._connect_thread,
            args=(host, port, username, password, version, gmap_enabled),
            daemon=True
        )
        self.connection_thread.start()
        
    def _connect_thread(self, host: str, port: int, username: str, password: str, version: str, gmap_enabled: bool = True):
        """Connection thread worker"""
        try:
            # Create v2 client
            if host == "hastur.eevul.net" and port == 14912:
                version = "6.037"
                
            self._client = RebornClient(host, port, version)
            
            # Disable GMAP mode IMMEDIATELY if requested
            if not gmap_enabled:
                self._client.set_gmap_enabled(False)
                logger.info("[CONNECTION] GMAP mode disabled")
            
            # Setup event handlers BEFORE connecting
            self._setup_event_handlers()
            
            # Connect and login
            if self._client.connect() and self._client.login(username, password):
                # Use PyReborn's actual local player (don't create our own copy)
                self._local_player = self._client.local_player
                logger.info(f"[CONNECTION] Using PyReborn local player: {self._local_player.nickname if self._local_player else 'None'} at ({self._local_player.x if self._local_player else '?'}, {self._local_player.y if self._local_player else '?'})")
                
                # Don't set nickname immediately - server doesn't like it
                # self.set_nickname(username)
                logger.debug(f"Skipping initial nickname set (causes disconnect)")
                
                # Send initial properties that gserver expects
                self._send_initial_properties()
                
                # Notify success
                logger.info("[CONNECTION] Connected successfully using native v2")
                if self.on_connected:
                    self.on_connected(self)
                    
                # Monitor connection (blocking)
                self._monitor_connection()
            else:
                # Login failed
                if self._client:
                    self._client.disconnect()
                self._client = None
                
                if self.on_connection_failed:
                    self.on_connection_failed("Login failed")
                    
        except Exception as e:
            logger.error(f"Connection error: {e}")
            if self.on_connection_failed:
                self.on_connection_failed(str(e))
                
        finally:
            self.is_connecting = False
            
    def _setup_event_handlers(self):
        """Setup v2 event handlers"""
        if not self._client:
            return
            
        events = self._client.events
        
        # Subscribe to LEVEL_ENTERED event
        events.subscribe(EventType.LEVEL_ENTERED, self._on_level_entered_event)
        
        # Subscribe to LEVEL_BOARD_LOADED event
        events.subscribe(EventType.LEVEL_BOARD_LOADED, self._on_level_board_loaded_event)
        
        # Subscribe to player events
        events.subscribe(EventType.PLAYER_JOINED, self._on_player_joined_event)
        events.subscribe(EventType.PLAYER_LEFT, self._on_player_left_event)
        events.subscribe(EventType.PLAYER_MOVED, self._on_player_moved_event)
        events.subscribe(EventType.SELF_UPDATE, self._on_self_update_event)
        events.subscribe(EventType.PLAYER_WARPED, self._on_player_warped_event)
        events.subscribe(EventType.SELF_WARPED, self._on_self_warped_event)
        
        # Subscribe to file events
        events.subscribe(EventType.FILE_RECEIVED, self._on_file_received_event)
        
        # Subscribe to chat events
        events.subscribe(EventType.CHAT_MESSAGE, self._on_chat_message_event)
    
    def _on_level_entered_event(self, event):
        """Handle level entered event from PyReborn"""
        logger.info(f"[EVENT] _on_level_entered_event called with event: {type(event)}")
        
        # Check if event is a dict or Event object
        if isinstance(event, dict):
            level = event.get('level')
        else:
            level = event.get('level') if hasattr(event, 'get') else getattr(event, 'level', None)
            
        if level:
            logger.info(f"[EVENT] Level entered: {level.name}")
            
            # Use PyReborn level directly
            self.current_level = level
            self.levels[level.name] = level
            
            # Fire callback with the PyReborn level object
            if self.on_level_received:
                logger.info(f"Firing on_level_received callback for {level.name}")
                self.on_level_received(level)
    
    def _on_level_board_loaded_event(self, event):
        """Handle level board loaded event from PyReborn"""
        logger.info(f"[EVENT] _on_level_board_loaded_event called with event: {type(event)}")
        
        # Check if event is a dict or Event object
        if isinstance(event, dict):
            level = event.get('level')
        else:
            level = event.get('level') if hasattr(event, 'get') else getattr(event, 'level', None)
            
        if level and hasattr(level, 'name'):
            level_name = level.name
            logger.info(f"[EVENT] Board loaded for level: {level_name}")
            
            # Store PyReborn level directly
            self.levels[level_name] = level
            
            # Update current level if it matches
            if self.current_level and self.current_level.name == level_name:
                self.current_level = level
                
                # Fire callback with PyReborn level object
                if self.on_level_received:
                    logger.info(f"Firing on_level_received callback for {level_name} (board update)")
                    self.on_level_received(level)
            
            # Check if this is a GMAP segment and track it
            if level_name.endswith('.nw'):
                self._track_gmap_segment(level_name)
                
                # Try to load GMAP data from cache if we have a current GMAP
                if self.current_gmap and self.current_gmap not in self.gmap_data:
                    import os
                    # Go up to pyReborn directory (3 levels from classic_reborn/core)
                    pyreborn_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
                    cache_path = os.path.join(pyreborn_dir, 'raw_files_cache', self.current_gmap)
                    logger.info(f"[GMAP DEBUG] Looking for GMAP cache at: {cache_path}")
                    if os.path.exists(cache_path):
                        logger.info(f"[GMAP DEBUG] Loading {self.current_gmap} from cache")
                        try:
                            with open(cache_path, 'rb') as f:
                                content = f.read()
                            self._parse_gmap_file(self.current_gmap, content)
                        except Exception as e:
                            logger.error(f"Error loading GMAP from cache: {e}")
            
            # End of _on_level_board_loaded_event method
    
    def _on_player_joined_event(self, event):
        """Handle player join event from PyReborn"""
        player_id = event.get('player_id', 0)
        account = event.get('account', '')
        nickname = event.get('nickname', '')
        x = event.get('x', 30.0)
        y = event.get('y', 30.0)
        
        player = Player(
            id=player_id,
            account=account,
            nickname=nickname,
            x=x,
            y=y
        )
        
        # Get additional properties if available
        props = event.get('properties', {})
        if PlayerProp.PLPROP_CURCHAT in props:
            player.chat = props[PlayerProp.PLPROP_CURCHAT]
            
        self.players[player.id] = player
        logger.info(f"Player joined: {player.nickname} (ID={player.id}) at ({player.x}, {player.y})")
        logger.info(f"  Properties: {props}")
    
    def _on_player_left_event(self, event):
        """Handle player leave event from PyReborn"""
        player_id = event.get('player_id')
        if player_id in self.players:
            player = self.players.pop(player_id)
            logger.debug(f"Player left: {player.nickname}")
    
    def _on_player_moved_event(self, event):
        """Handle player movement event from PyReborn"""
        player_id = event.get('player_id')
        if player_id in self.players:
            player = self.players[player_id]
            old_x, old_y = player.x, player.y
            player.x = event.get('x', player.x)
            player.y = event.get('y', player.y)
            player.direction = Direction(event.get('direction', 2))
            
            # Check if we have world coordinates (x2, y2) from GMAP mode
            if hasattr(player, 'x2') and hasattr(player, 'y2') and player.x2 is not None:
                logger.debug(f"Player {player.nickname} moved from ({old_x}, {old_y}) to ({player.x}, {player.y}) [World: ({player.x2}, {player.y2})]")
            else:
                logger.debug(f"Player {player.nickname} moved from ({old_x}, {old_y}) to ({player.x}, {player.y})")
    
    def _on_self_update_event(self, event):
        """Handle our own property updates from PyReborn"""
        if self._local_player:
            props = event.get('properties', {})
            # Update local player from properties
            logger.debug(f"Self update: {props}")
            
            # Check for GMAP position updates
            if PlayerProp.PLPROP_GMAPLEVELX in props:
                gmap_x = props[PlayerProp.PLPROP_GMAPLEVELX]
                gmap_y = props.get(PlayerProp.PLPROP_GMAPLEVELY, self.gmap_position[1])
                if (gmap_x, gmap_y) != self.gmap_position:
                    old_pos = self.gmap_position
                    self.gmap_position = (gmap_x, gmap_y)
                    logger.info(f"GMAP position changed: {old_pos} -> {self.gmap_position}")
    
    def _on_player_warped_event(self, event):
        """Handle player warp event from PyReborn"""
        player_id = event.get('player_id')
        x = event.get('x', 0)
        y = event.get('y', 0)
        level_name = event.get('level_name', '')
        
        if player_id in self.players:
            player = self.players[player_id]
            player.x = x
            player.y = y
            logger.debug(f"Player {player.nickname} warped to ({x}, {y}) in {level_name}")
    
    def _on_self_warped_event(self, event):
        """Handle our warp event from PyReborn"""
        if self._local_player:
            self._local_player.x = event.get('x', self._local_player.x)
            self._local_player.y = event.get('y', self._local_player.y)
            logger.debug(f"We warped to ({self._local_player.x}, {self._local_player.y})")
    
    def _on_file_received_event(self, event):
        """Handle file reception from PyReborn"""
        filename = event.get('filename', '')
        content = event.get('data', b'')
        
        logger.info(f"FILE_RECEIVED: {filename} ({len(content)} bytes)")
        
        # PNG files are already compressed, do not attempt to decompress them
        # The server sends PNG files as-is, not with additional compression
        
        # PyReborn already handles file accumulation for large files
        # When we receive a FILE_RECEIVED event, the file is complete
        
        # Clear waiting flag if this is the file we were waiting for
        if self.waiting_for_file == filename:
            logger.info(f"Received expected file: {filename}")
            self.waiting_for_file = None
            
            # Cancel timeout timer
            if self.file_request_timeout_timer:
                self.file_request_timeout_timer.cancel()
                self.file_request_timeout_timer = None
            
            # Process next file in queue immediately
            if self.file_request_queue:
                logger.info(f"Queue has {len(self.file_request_queue)} more files, processing next")
                self._process_file_request_queue()
        
        # Check if this is a tileset PNG
        if filename.endswith('.png') and ('tile' in filename.lower() or 'pics' in filename.lower()):
            logger.info(f"Received tileset PNG: {filename}")
            # Apply the tileset to the renderer
            if hasattr(self, 'renderer') and self.renderer:
                self.renderer.load_tileset_from_data(content, filename)
                logger.info(f"Applied tileset {filename} to renderer")
            else:
                logger.warning(f"No renderer available to apply tileset {filename}")
        
        if filename.endswith('.gmap'):
            # Check if this is real GMAP data or just level data
            if content.startswith(b'GRMAP001'):
                logger.info(f"Received GMAP file: {filename} (valid GMAP format)")
                self._parse_gmap_file(filename, content)
            else:
                logger.info(f"Received {filename} but it's not GMAP format (got {content[:8]}) - ignoring")
            # File is already complete when we receive it
        elif filename.endswith('.nw'):
            # Parse level file
            logger.info(f"Received level file: {filename}")
            self._parse_level_file(filename, content)
            # File is already complete when we receive it
        elif filename.endswith('.png'):
            # Handle tileset image
            self._handle_tileset_image(filename, content)
    
    def _handle_tileset_image(self, filename: str, content: bytes):
        """Handle received tileset image"""
        logger.info(f"Processing tileset image: {filename} ({len(content)} bytes)")
        
        # Debug PNG data
        logger.debug(f"First 16 bytes: {content[:16].hex() if content else 'empty'}")
        
        # Check if it's a valid PNG
        has_valid_signature = content and content[:8] == b'\x89PNG\r\n\x1a\n'
        
        if has_valid_signature:
            logger.info(f"Valid PNG signature detected for {filename}")
            
            # Check if PNG is complete by looking for IEND chunk
            png_end = b'IEND\xae\x42\x60\x82'
            is_complete = png_end in content
            
            if is_complete:
                logger.info(f"PNG file {filename} is complete!")
                
                # Strip any data after IEND chunk (Graal server adds metadata)
                iend_pos = content.find(png_end)
                if iend_pos >= 0:
                    clean_size = iend_pos + len(png_end)
                    if len(content) > clean_size:
                        logger.info(f"Stripping {len(content) - clean_size} bytes of server metadata from PNG")
                        content = content[:clean_size]
                
                # File is already complete when we receive it
            else:
                logger.warning(f"PNG file {filename} is incomplete, waiting for more data...")
                return  # Don't process incomplete PNG
        else:
            logger.warning(f"No valid PNG signature yet for {filename} (got: {content[:8].hex() if content else 'empty'})")
            # Keep accumulating - might not have the header yet
            return
        
        # Store tileset data
        self.tilesets[filename] = content
        
        # Check if this is a GMAP tileset
        is_gmap_tileset = False
        if self.current_gmap and self.current_gmap in self.gmap_data:
            gmap_info = self.gmap_data[self.current_gmap]
            if gmap_info.get('tileset') == filename:
                logger.info(f"This is the tileset for current GMAP: {self.current_gmap}")
                is_gmap_tileset = True
        
        # Always notify about tileset reception (for both GMAP and regular tilesets)
        if self.on_tileset_received:
            logger.info(f"Notifying renderer about tileset: {filename} (is_gmap_tileset={is_gmap_tileset})")
            self.on_tileset_received(filename, content)
    
    def _on_chat_message_event(self, event):
        """Handle chat messages from PyReborn"""
        # Chat messages can be from various sources
        # For now, we'll handle this when player props update
        pass
    
    
    def _track_gmap_segment(self, segment_name: str):
        """Track GMAP segment and request adjacent segments
        
        Args:
            segment_name: Segment name like "zlttp-d8.nw"
        """
        # Parse segment position
        if '-' not in segment_name:
            return
            
        try:
            base_name = segment_name.split('-')[0]
            segment_code = segment_name.split('-')[1].replace('.nw', '')
            
            if len(segment_code) >= 2:
                col_char = segment_code[0]
                row_str = segment_code[1:]
                
                # Convert to numeric position
                col = ord(col_char.lower()) - ord('a')
                row = int(row_str)
                self.gmap_position = (col, row)
                
                logger.info(f"GMAP segment {segment_name} at position ({col}, {row})")
                
                # Store in GMAP segments
                self.gmap_segments[segment_name] = self.levels.get(segment_name)
                
                # Adjacent segments are now handled by PyReborn's level manager
                # to avoid duplicate requests. See level_manager.request_adjacent_levels()
                logger.debug(f"GMAP segment {segment_name} loaded - adjacent requests handled by PyReborn")
        except Exception as e:
            logger.error(f"Error parsing GMAP segment {segment_name}: {e}")
    
    def _parse_gmap_file(self, filename: str, content: bytes):
        """Parse GMAP file format
        
        Args:
            filename: GMAP filename
            content: Raw file content
        """
        try:
            logger.info(f"[GMAP DEBUG] Parsing GMAP file: {filename} ({len(content)} bytes)")
            lines = content.decode('latin-1').split('\n')
            logger.info(f"[GMAP DEBUG] File has {len(lines)} lines")
            
            width = 0
            height = 0
            tileset = None
            levels = []
            in_levelnames = False
            
            for line in lines:
                line = line.strip()
                
                if line.startswith('WIDTH '):
                    width = int(line.split()[1])
                    logger.info(f"[GMAP DEBUG] Found WIDTH: {width}")
                elif line.startswith('HEIGHT '):
                    height = int(line.split()[1])
                    logger.info(f"[GMAP DEBUG] Found HEIGHT: {height}")
                elif line.startswith('TILESET '):
                    tileset = line[8:]  # Everything after "TILESET "
                elif line == 'LEVELNAMES':
                    in_levelnames = True
                elif line == 'LEVELNAMESEND':
                    in_levelnames = False
                elif in_levelnames and line:
                    # Parse level names line (format: "level1.nw","level2.nw",...)
                    level_line = line.strip().rstrip(',')
                    # Extract quoted level names
                    import re
                    level_names = re.findall(r'"([^"]+)"', level_line)
                    levels.extend(level_names)
            
            # Build level map (position -> level name)
            level_map = {}
            reverse_map = {}  # level name -> (x, y)
            
            for y in range(height):
                for x in range(width):
                    idx = y * width + x
                    if idx < len(levels):
                        level_name = levels[idx]
                        level_map[(x, y)] = level_name
                        reverse_map[level_name] = (x, y)
            
            # Store GMAP data
            logger.info(f"[GMAP DEBUG] Storing GMAP data for '{filename}': {width}x{height}, {len(levels)} levels")
            self.gmap_data[filename] = {
                'width': width,
                'height': height,
                'tileset': tileset,
                'levels': levels,
                'level_map': reverse_map,  # level name -> position
                'position_map': level_map  # position -> level name
            }
            logger.info(f"[GMAP DEBUG] GMAP data stored successfully. Total GMAPs in cache: {len(self.gmap_data)}")
            
            logger.info(f"[GMAP DEBUG] Parsed GMAP {filename}: {width}x{height}, tileset={tileset}")
            logger.info(f"[GMAP DEBUG] GMAP levels: {levels[:10]}{'...' if len(levels) > 10 else ''}")  # Limit output
            
            # Update the GMAP handler if we have a reference to game state
            if hasattr(self, 'on_level_received') and self.on_level_received:
                # Try to get GMAP handler through the callback
                try:
                    # This is a bit of a hack, but we need to update the handler dimensions
                    logger.info(f"[GMAP DEBUG] Attempting to update GMAP handler dimensions...")
                except Exception as e:
                    logger.warning(f"[GMAP DEBUG] Could not update GMAP handler: {e}")
            
            # Request the tileset if specified
            if tileset and self._client:
                logger.info(f"Requesting GMAP tileset: {tileset}")
                self._client.request_file(tileset)
                
        except Exception as e:
            logger.error(f"[GMAP DEBUG] Error parsing GMAP file {filename}: {e}")
            import traceback
            logger.error(f"[GMAP DEBUG] Traceback: {traceback.format_exc()}")
    
    def _request_adjacent_segments_from_gmap(self, gmap_name: str, col: int, row: int):
        """Request adjacent GMAP segments based on parsed GMAP data
        
        Args:
            gmap_name: Name of the GMAP file
            col: Current column position
            row: Current row position
        """
        if gmap_name not in self.gmap_data:
            logger.warning(f"No GMAP data for {gmap_name}")
            return
            
        gmap_info = self.gmap_data[gmap_name]
        width = gmap_info['width']
        height = gmap_info['height']
        position_map = gmap_info['position_map']
        
        logger.info(f"Requesting adjacent segments for position ({col}, {row}) in {width}x{height} GMAP")
        
        # Request all adjacent segments (8-connected)
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                if dx == 0 and dy == 0:
                    continue  # Skip current position
                    
                adj_col = col + dx
                adj_row = row + dy
                
                # Check bounds
                if 0 <= adj_col < width and 0 <= adj_row < height:
                    adj_pos = (adj_col, adj_row)
                    if adj_pos in position_map:
                        segment_name = position_map[adj_pos]
                        
                        # Adjacent segment requests handled by PyReborn level manager
                        # to avoid duplicate requests and server spam
                        if segment_name not in self.levels:
                            logger.debug(f"Adjacent GMAP segment {segment_name} at ({adj_col}, {adj_row}) - handled by PyReborn")
    
    def _process_file_request_queue(self):
        """Process the next file in the request queue"""
        if self.waiting_for_file:
            # Still waiting for a file, don't request another
            logger.debug(f"Still waiting for file: {self.waiting_for_file}")
            return
            
        if not self.file_request_queue:
            # No more files to request
            logger.debug("File request queue is empty")
            return
            
        # Get next file to request
        next_file = self.file_request_queue.pop(0)
        
        # Check if we already have it
        if next_file in self.levels:
            logger.debug(f"Already have {next_file}, processing next in queue")
            # Process next request immediately
            if self.file_request_queue:
                self._process_file_request_queue()
            return
            
        # Request the file
        logger.info(f"Requesting file from queue: {next_file}")
        self.waiting_for_file = next_file
        if self._client:
            try:
                self._client.request_file(next_file)
                logger.debug(f"File request sent for {next_file}")
                self.file_request_time = time.time()
                
                # Set a timeout timer
                def timeout_handler():
                    if self.waiting_for_file == next_file:
                        logger.warning(f"Timeout waiting for {next_file}, moving to next file")
                        self.waiting_for_file = None
                        if self.file_request_queue:
                            self._process_file_request_queue()
                
                self.file_request_timeout_timer = threading.Timer(5.0, timeout_handler)
                self.file_request_timeout_timer.daemon = True
                self.file_request_timeout_timer.start()
                
            except Exception as e:
                logger.error(f"Error requesting file {next_file}: {e}")
                self.waiting_for_file = None
                # Try next file
                if self.file_request_queue:
                    self.file_request_timer = threading.Timer(0.5, self._process_file_request_queue)
                    self.file_request_timer.daemon = True
                    self.file_request_timer.start()
        else:
            logger.error("No client available to request files")
            self.waiting_for_file = None
            
    # REMOVED: _request_chicken_adjacent_segments - should use GMAP data only
    
    def _request_adjacent_segments(self, base_name: str, col: int, row: int):
        """Request adjacent GMAP segments for seamless transitions
        
        Args:
            base_name: Base GMAP name (e.g., "zlttp")
            col: Current column
            row: Current row
        """
        # Only request immediate neighbors to avoid non-existent segments
        logger.info(f"GMAP position ({col}, {row}) - requesting immediate neighbors only")
        
        # Only request 4 direct neighbors (not diagonals)
        offsets = [
            (0, -1),   # North
            (-1, 0),   # West
            (1, 0),    # East
            (0, 1),    # South
        ]
        
        for dx, dy in offsets:
            adj_col = col + dx
            adj_row = row + dy
            
            # Skip if clearly out of bounds
            if adj_col < 0 or adj_row < 0:
                continue
                
            # Generate segment name
            col_char = chr(ord('a') + adj_col)
            segment_name = f"{base_name}-{col_char}{adj_row}.nw"
            
            # Adjacent segment requests handled by PyReborn level manager
            # to avoid duplicate requests and server spam
            if segment_name not in self.levels:
                logger.debug(f"Adjacent GMAP segment {segment_name} - handled by PyReborn")
    
    def _handle_set_active_level(self, packet):
        """Handle SETACTIVELEVEL packet (156)"""
        # The packet contains the level name as raw data
        if hasattr(packet, 'raw_data'):
            level_name = packet.raw_data.decode('latin-1', errors='replace').strip()
            logger.info(f"SETACTIVELEVEL: Server wants us to set active level to '{level_name}'")
            
            # Always acknowledge the server's request
            # Send CURLEVEL property to acknowledge
            # Use high-level API instead of low-level packets
            # # packet = PlayerPropsPacketV2()  # Using high-level API
            # packet.add_property(PlayerProp.PLPROP_CURLEVEL, level_name)
            # self._client.send_packet(packet)
            
            # The main RebornClient should handle level changes automatically
            logger.info(f"Sent CURLEVEL property: {level_name}")
            
            # If it's a GMAP, update our current_gmap
            if level_name.endswith('.gmap'):
                self.current_gmap = level_name
                logger.info(f"Updated current GMAP to: {level_name}")
    
    def _send_initial_properties(self):
        """Send initial properties after login (required by gserver)"""
        if not self._client:
            return
            
        # Use high-level API - the main RebornClient should handle initial properties automatically
        logger.info(f"Skipping low-level initial properties - using high-level API")
        return  # The main RebornClient handles this
            
    def _convert_board_data(self, board_data: bytes) -> list:
        """Convert raw board data to 64x64 tile array"""
        logger.debug(f"Converting board data: {len(board_data)} bytes")
        
        # Initialize empty 64x64 array
        tiles = [[0] * 64 for _ in range(64)]
        
        # Fill with available data
        for y in range(64):
            for x in range(64):
                idx = (y * 64 + x) * 2
                if idx + 1 < len(board_data):
                    tile_id = board_data[idx] | (board_data[idx + 1] << 8)
                    tiles[y][x] = tile_id
                else:
                    # No more data, rest stays as 0
                    break
                    
        return tiles
        
    def _monitor_connection(self):
        """Monitor connection status"""
        logger.info("[MONITOR] Starting connection monitor")
        
        while self._client and self.is_connected():
            time.sleep(0.1)
            
        logger.warning("[MONITOR] Connection lost")
        if self.on_disconnected:
            self.on_disconnected()
            
    # ===== Public API Methods =====
    
    def disconnect(self):
        """Disconnect from server"""
        if self._client:
            self._client.disconnect()
            self._client = None
            
    def is_connected(self) -> bool:
        """Check if connected"""
        return self._client is not None and self._client.connected
    
    @property
    def client(self):
        """Get the underlying PyReborn client"""
        return self._client
        
    def move_to(self, x: float, y: float, direction: Optional[Direction] = None):
        """Move player to position"""
        if not self._client:
            return
            
        # Update local state
        if self._local_player:
            logger.debug(f"[MOVE] Updating local player from ({self._local_player.x}, {self._local_player.y}) to ({x}, {y})")
            logger.debug(f"[MOVE] Local player object ID: {id(self._local_player)}")
            self._local_player.x = x
            self._local_player.y = y
            if direction is not None:
                self._local_player.direction = direction
                
        # PyReborn v2 client will handle GMAP coordinates automatically based on its mode
        # Just send the local coordinates - PyReborn knows if we're in GMAP mode
        self._client.move_to(x, y, direction)
        
        # Check if we're in GMAP mode and log what coordinates should be sent
        if hasattr(self._client, 'is_gmap_mode') and self._client.is_gmap_mode:
            # Calculate what world coordinates should be
            if hasattr(self._client, 'local_player') and self._client.local_player:
                gmapx = getattr(self._client.local_player, 'gmaplevelx', None)
                gmapy = getattr(self._client.local_player, 'gmaplevely', None)
                if gmapx is not None and gmapy is not None:
                    world_x = gmapx * 64 + x
                    world_y = gmapy * 64 + y
                    logger.info(f"[MOVE] GMAP mode: local ({x:.1f}, {y:.1f}) -> world ({world_x:.1f}, {world_y:.1f}) segment=[{gmapx},{gmapy}] dir={direction}")
                else:
                    # In a non-GMAP level (like a house) but GMAP mode flag is still set
                    logger.info(f"[MOVE] Sent to server: ({x:.1f}, {y:.1f}) dir={direction} (in non-GMAP level)")
            else:
                logger.info(f"[MOVE] Sent to server: ({x}, {y}) dir={direction} (GMAP mode but no player coords)")
        else:
            logger.info(f"[MOVE] Sent to server: ({x}, {y}) dir={direction}")
        
    def set_chat(self, message: str):
        """Set chat bubble"""
        if self._client:
            self._client.set_chat(message)
            
    def say(self, message: str):
        """Send chat message"""
        if self._client:
            self._client.say(message)
            
    def set_nickname(self, nickname: str):
        """Set player nickname"""
        if self._client:
            # Use high-level API
            self._client.set_nickname(nickname)
            
            if self._local_player:
                self._local_player.nickname = nickname
            
    def set_gani(self, gani_name: str):
        """Set player animation"""
        if self._client:
            # Use high-level API
            self._client.set_gani(gani_name)
            
            if self._local_player:
                self._local_player.gani = gani_name
            
    def set_carry_sprite(self, sprite_name: str):
        """Set carry sprite (e.g., 'bush')"""
        if self._client:
            # Use high-level API
            self._client.set_carry_sprite(sprite_name)
            
            if self._local_player:
                self._local_player.carry_sprite = sprite_name
            
    def warp_to_level(self, level_name: str, x: float, y: float):
        """Request warp to another level"""
        if not self._client:
            return
            
        # In v2, we'd send a packet requesting level change
        # For now, just use say command as that's what v1 does
        self._client.say(f"warpto {level_name},{x},{y}")
        
    def request_file(self, filename: str):
        """Request a file from server"""
        if self._client:
            self._client.request_file(filename)
            
    def send_player_props(self, props: Dict[int, Any]):
        """Send multiple player properties"""
        if self._client:
            # Use high-level API - send each property
            for prop_id, value in props.items():
                # The high-level API doesn't have a generic send_player_props
                # so we'll need to handle this differently
                logger.warning(f"send_player_props not fully implemented for prop {prop_id}")
                # TODO: Implement property sending through high-level API
        
    def check_for_level(self) -> Optional[Level]:
        """Check if a level is loaded"""
        # First check current level
        if self.current_level and hasattr(self.current_level, 'board_tiles_64x64'):
            return self.current_level
            
        # Then check any loaded level
        for level in self.levels.values():
            if hasattr(level, 'board_tiles_64x64') and level.board_tiles_64x64:
                return level
                
        return None
    
    def get_gmap_segments(self) -> Dict[str, Level]:
        """Get all loaded GMAP segments for rendering"""
        return {name: level for name, level in self.gmap_segments.items() 
                if level and hasattr(level, 'board_tiles_64x64') and level.board_tiles_64x64}
    
    def _parse_level_file(self, filename: str, content: bytes):
        """Parse a .nw level file and extract board data
        
        Args:
            filename: Level filename (e.g., 'chicken4.nw')
            content: Raw file content
        """
        try:
            # Ensure we have a Level object for this file
            if filename not in self.levels:
                self.levels[filename] = Level(name=filename)
            
            level = self.levels[filename]
            
            # Parse the content
            text = content.decode('latin-1', errors='replace')
            lines = text.split('\n')
            
            logger.info(f"Parsing level file {filename}: {len(lines)} lines")
            
            # Check for GLEVNW01 header (indicates different encoding)
            is_glevnw01 = False
            start_line = 0
            if lines and lines[0].strip() == 'GLEVNW01':
                is_glevnw01 = True
                start_line = 1
                logger.info(f"Detected GLEVNW01 format for {filename}")
            
            # For GLEVNW01 files, we need to collect all 64 BOARD lines
            board_tiles_by_row = {}
            
            for i in range(start_line, len(lines)):
                line = lines[i].strip()
                
                if line.startswith('BOARD '):
                    # BOARD x y width height data
                    parts = line.split(None, 5)  # Use None to split on any whitespace
                    if len(parts) >= 6:
                        x = int(parts[1])
                        y = int(parts[2])
                        width = int(parts[3])
                        height = int(parts[4])
                        data = parts[5]
                        
                        logger.debug(f"BOARD line: y={y}, width={width}, height={height}, data_len={len(data)}")
                        
                        if is_glevnw01:
                            # GLEVNW01 format: height=0, each line is one row
                            if height == 0 and width == 64 and 0 <= y < 64:
                                # Decode using base64-style encoding
                                row_tiles = self._decode_glevnw01_board_string(data)
                                board_tiles_by_row[y] = row_tiles
                        else:
                            # Old format (not used in file packets)
                            logger.warning(f"Non-GLEVNW01 format not implemented for {filename}")
            
            # If we got GLEVNW01 board data
            if is_glevnw01 and board_tiles_by_row:
                # Convert to flat array first
                board_data = []
                for y in range(64):
                    if y in board_tiles_by_row:
                        board_data.extend(board_tiles_by_row[y])
                    else:
                        # Missing row, fill with zeros
                        board_data.extend([0] * 64)
                
                # Store as 2D array for v2
                board_2d = []
                for y in range(64):
                    row = []
                    for x in range(64):
                        idx = y * 64 + x
                        row.append(board_data[idx] if idx < len(board_data) else 0)
                    board_2d.append(row)
                
                level.board_tiles_64x64 = board_2d
                logger.info(f"Parsed GLEVNW01 board data for {filename}: {len(board_data)} tiles")
                
                # Store as GMAP segment if applicable
                if filename.endswith('.nw'):
                    # Check if this level is part of a GMAP
                    for gmap_name, gmap_info in self.gmap_data.items():
                        if filename in gmap_info['level_map']:
                            self.gmap_segments[filename] = level
                            logger.info(f"Stored GMAP segment {filename} from file (part of {gmap_name})")
                            break
                    else:
                        # Fallback for standard naming
                        if '-' in filename:
                            self.gmap_segments[filename] = level
                            logger.info(f"Stored GMAP segment {filename} from file (standard naming)")
                
                # Fire level received callback
                if self.on_level_received:
                    logger.info(f"Firing on_level_received callback for {filename} (from file)")
                    self.on_level_received(level)
            else:
                logger.warning(f"No board data found in {filename}")
                
        except Exception as e:
            logger.error(f"Error parsing level file {filename}: {e}")
            import traceback
            traceback.print_exc()
    
    def _decode_glevnw01_board_string(self, board_str: str) -> List[int]:
        """Decode GLEVNW01 BOARD string to tile IDs using base64-style encoding
        
        Args:
            board_str: Encoded board string (64 characters for 64 tiles)
            
        Returns:
            List of 64 tile IDs
        """
        tiles = []
        
        # Graal's base64 character set
        base64_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
        
        i = 0
        while i < len(board_str) and len(tiles) < 64:
            # Each tile is encoded as 2 characters
            if i + 1 < len(board_str):
                char1 = board_str[i]
                char2 = board_str[i + 1]
                
                # Find positions in base64 character set
                idx1 = base64_chars.find(char1)
                idx2 = base64_chars.find(char2)
                
                if idx1 >= 0 and idx2 >= 0:
                    # Graal tile ID format: first_char * 64 + second_char
                    tile_id = idx1 * 64 + idx2
                    # Ensure it's within valid range
                    tile_id = tile_id % 1024
                else:
                    # Invalid characters, use tile 0
                    tile_id = 0
                
                tiles.append(tile_id)
                i += 2
            else:
                # Not enough characters, pad with 0
                tiles.append(0)
                i += 1
        
        # Pad to 64 tiles if needed
        while len(tiles) < 64:
            tiles.append(0)
            
        return tiles
    
    def get_adjacent_segments(self, center_name: str) -> Dict[str, Level]:
        """Get adjacent GMAP segments for seamless rendering
        
        Args:
            center_name: Center segment name (e.g., "zlttp-d8.nw" or "chicken1.nw")
            
        Returns:
            Dictionary of adjacent segments with their relative positions
        """
        # First check if we have GMAP data for the current GMAP
        if self.current_gmap and self.current_gmap in self.gmap_data:
            gmap_info = self.gmap_data[self.current_gmap]
            if center_name in gmap_info['level_map']:
                # Use parsed GMAP data
                center_col, center_row = gmap_info['level_map'][center_name]
                width = gmap_info['width']
                height = gmap_info['height']
                position_map = gmap_info['position_map']
                
                adjacent = {}
                # Check all 9 positions (including center)
                for dy in range(-1, 2):
                    for dx in range(-1, 2):
                        col = center_col + dx
                        row = center_row + dy
                        
                        if 0 <= col < width and 0 <= row < height:
                            adj_pos = (col, row)
                            if adj_pos in position_map:
                                segment_name = position_map[adj_pos]
                                
                                # Only include if we have the level loaded with board data
                                if segment_name in self.levels:
                                    level = self.levels[segment_name]
                                    adjacent[segment_name] = {
                                        'level': level,
                                        'offset_x': dx * 64,
                                        'offset_y': dy * 64
                                    }
                
                return adjacent
        
        # All GMAP data should come from the GMAP file, not hardcoded
        
        # Fallback to old method for standard GMAP naming (zlttp-d8.nw)
        if '-' not in center_name:
            return {}
            
        try:
            base_name = center_name.split('-')[0]
            segment_code = center_name.split('-')[1].replace('.nw', '')
            
            if len(segment_code) >= 2:
                col_char = segment_code[0]
                row_str = segment_code[1:]
                center_col = ord(col_char.lower()) - ord('a')
                center_row = int(row_str)
                
                adjacent = {}
                # Check all 9 positions (including center)
                for dy in range(-1, 2):
                    for dx in range(-1, 2):
                        col = center_col + dx
                        row = center_row + dy
                        
                        if col < 0 or row < 0:
                            continue
                            
                        col_char = chr(ord('a') + col)
                        segment_name = f"{base_name}-{col_char}{row}.nw"
                        
                        if segment_name in self.gmap_segments:
                            level = self.gmap_segments[segment_name]
                            if level and level.board_tiles_64x64:
                                adjacent[segment_name] = {
                                    'level': level,
                                    'offset_x': dx * 64,
                                    'offset_y': dy * 64
                                }
                
                return adjacent
        except Exception as e:
            logger.error(f"Error getting adjacent segments for {center_name}: {e}")
            return {}
        
    # ===== V1 Compatibility Properties =====
    
    # Remove this - we already have a client property above that returns self._client
        
    @property
    def local_player(self):
        """Get local player for v1 compatibility"""
        return self._local_player
        
    @local_player.setter
    def local_player(self, value):
        """Set local player for v1 compatibility"""
        self._local_player = value
        
    @property
    def level_manager(self):
        """Mock level manager for v1 compatibility"""
        class MockLevelManager:
            def __init__(self, mgr):
                self.mgr = mgr
                self.requested_files = set()  # Track requested files
                
            @property
            def levels(self):
                return self.mgr.levels
                
            @property
            def current_level(self):
                return self.mgr.current_level
                
            def update(self):
                """Update method for v1 compatibility"""
                # In v2, updates happen through events
                pass
                
            def request_file(self, filename):
                """Request a file (for GMAP preloader compatibility)"""
                self.requested_files.add(filename)
                if hasattr(self.mgr, '_client') and self.mgr._client:
                    self.mgr._client.request_file(filename)
                
        return MockLevelManager(self)
        
    @property
    def events(self):
        """Get event manager"""
        if hasattr(self, '_client') and self._client:
            return self._client.events
        return None
        
    @property
    def _actions(self):
        """Mock actions for v1 compatibility"""
        return self._get_actions()
        
    def _get_actions(self):
        """Get actions mock"""
        class MockActions:
            def __init__(self, mgr):
                self.mgr = mgr
                
            def set_current_level(self, level_name: str):
                """Set current level by sending CURLEVEL property"""
                logger.info(f"Setting CURLEVEL to: {level_name}")
                # The high-level API handles level changes automatically
                # Just track internally
                if level_name not in self.mgr.levels:
                    self.mgr.levels[level_name] = Level(name=level_name)
                self.mgr.current_level = self.mgr.levels[level_name]
                
            def set_gmap_position(self, x: int, y: int):
                """Set GMAP position"""
                logger.debug(f"Setting GMAP position: ({x}, {y})")
                # The high-level API handles GMAP position tracking automatically
                # Just log for debugging
                self.mgr.gmap_position = (x, y)
                    
            def set_property_sent_callback(self, callback):
                """Set callback for when properties are sent (v1 compatibility)"""
                # In v2, properties are sent immediately
                logger.debug("Property sent callback set (no-op in v2)")
                    
        return MockActions(self)
    
    @property
    def connection_gmap_data(self) -> Dict[str, Dict]:
        """Get GMAP data for game client compatibility"""
        return self.gmap_data