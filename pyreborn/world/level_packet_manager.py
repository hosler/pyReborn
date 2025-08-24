"""
Level Packet Manager - Handles level-related packets

This manager implements IManager to handle level packets:
- PLO_LEVELNAME (packet 6) - level name
- PLO_BOARDPACKET (packet 101) - level board data
- PLO_BOARDMODIFY (packet 7) - board modifications
- PLO_LEVELSIGN (packet 5) - level signs
- PLO_LEVELCHEST (packet 4) - level chests
- PLO_LEVELLINK (packet 1) - level links
- PLO_FILE (packet 102) - level file transfers
"""

import logging
from typing import Dict, Any, Optional
from ..protocol.interfaces import IManager
from ..session.events import EventType

logger = logging.getLogger(__name__)


class LevelPacketManager(IManager):
    """Manager for handling level-related packets"""
    
    def __init__(self):
        self.event_manager = None
        self.config = None
        self.level_manager = None  # Reference to the actual level manager
        self.session_manager = None  # Reference to session manager for notifications
        self.client = None  # Reference to client for requesting files
        self.logger = logger
        
        # Track discovered level links for GMAP mode
        self.discovered_links = set()
        self.gmap_mode_active = False
        
    def initialize(self, config, event_manager) -> None:
        """Initialize the manager"""
        self.config = config
        self.event_manager = event_manager
        logger.info("Level packet manager initialized")
        
    def cleanup(self) -> None:
        """Clean up manager resources"""
        logger.info("Level packet manager cleaned up")
        
    @property
    def name(self) -> str:
        """Get manager name"""
        return "level_packet_manager"
        
    def set_level_manager(self, level_manager):
        """Set reference to the actual level manager"""
        self.level_manager = level_manager
        
    def set_session_manager(self, session_manager):
        """Set reference to session manager for level change notifications"""
        self.session_manager = session_manager
    
    def set_client(self, client):
        """Set client reference for file requests"""
        self.client = client
        logger.debug("Client reference set in level packet manager")
        
    def handle_packet(self, packet_id: int, packet_data: Dict[str, Any]) -> None:
        """Handle incoming level packets"""
        packet_name = packet_data.get('packet_name', 'UNKNOWN')
        
        logger.debug(f"Level packet manager handling packet: {packet_name} ({packet_id})")
        
        # Route based on packet ID
        if packet_id == 6:  # PLO_LEVELNAME
            self._handle_level_name(packet_data)
        elif packet_id == 101:  # PLO_BOARDPACKET
            self._handle_board_packet(packet_data)
        elif packet_id == 7:  # PLO_BOARDMODIFY
            self._handle_board_modify(packet_data)
        elif packet_id == 5:  # PLO_LEVELSIGN
            self._handle_level_sign(packet_data)
        elif packet_id == 4:  # PLO_LEVELCHEST
            self._handle_level_chest(packet_data)
        elif packet_id == 1:  # PLO_LEVELLINK
            self._handle_level_link(packet_data)
        elif packet_id == 102:  # PLO_FILE
            self._handle_file(packet_data)
        else:
            logger.warning(f"Level packet manager received unhandled packet: {packet_name} ({packet_id})")
    
    def _handle_level_name(self, parsed_packet: Dict[str, Any]) -> None:
        """Handle PLO_LEVELNAME - level name"""
        import time
        current_time = time.time()
        
        # Try to get parsed data first (from enhanced packet parsing)
        parsed_data = parsed_packet.get('parsed_data', {})
        if parsed_data and 'level_name' in parsed_data:
            level_name = parsed_data['level_name']
            is_gmap = parsed_data.get('is_gmap', False)
            # Throttle repetitive level name parsing logs
            if not hasattr(self, '_last_level_log') or level_name != getattr(self, '_last_level_name', ''):
                logger.info(f"🏗️ Using enhanced PLO_LEVELNAME parsing: {level_name} (GMAP: {is_gmap})")
                self._last_level_name = level_name
                self._last_level_log = time.time()
            else:
                logger.debug(f"🏗️ Using enhanced PLO_LEVELNAME parsing: {level_name} (GMAP: {is_gmap})")
        else:
            # Fallback to basic field parsing
            fields = parsed_packet.get('fields', {})
            level_name = fields.get('level_name', '')
            
            # Convert bytes to string if needed
            if isinstance(level_name, bytes):
                # Remove null terminator if present
                if level_name and level_name[-1] == 0:
                    level_name = level_name[:-1]
                level_name = level_name.decode('latin-1', errors='replace')
            
            is_gmap = level_name.endswith('.gmap')
            # Throttle repetitive level name parsing logs
            if not hasattr(self, '_last_level_log') or level_name != getattr(self, '_last_level_name', ''):
                logger.info(f"🏗️ Basic PLO_LEVELNAME parsing: {level_name} (GMAP: {is_gmap})")
                self._last_level_name = level_name
                self._last_level_log = time.time()
            else:
                logger.debug(f"🏗️ Basic PLO_LEVELNAME parsing: {level_name} (GMAP: {is_gmap})")
        
        # 🎯 FIX: Check if this level change should be blocked by client movement
        if self.session_manager and hasattr(self.session_manager, 'gmap_manager') and self.session_manager.gmap_manager:
            if not self.session_manager.gmap_manager.should_accept_server_level_name(level_name):
                logger.debug(f"🚫 Blocking server level name '{level_name}' due to active client movement")
                return  # Block this level name change
        
        # 🎯 FIX: Enhanced throttling to prevent rapid level switching
        rapid_switch_key = f"_last_level_change_{level_name}"
        if hasattr(self, rapid_switch_key):
            time_since_last = current_time - getattr(self, rapid_switch_key)
            if time_since_last < 0.5:  # Prevent changes faster than 0.5 seconds
                logger.debug(f"🚫 Throttling rapid level switch to '{level_name}' (last change {time_since_last:.2f}s ago)")
                return  # Block rapid switching
        setattr(self, rapid_switch_key, current_time)
        
        # 🎯 CRITICAL: Notify session manager of level change
        if self.session_manager and hasattr(self.session_manager, 'set_current_level'):
            self.session_manager.set_current_level(level_name)
            logger.info(f"✅ Notified session manager of level change: {level_name}")
        else:
            logger.warning("❌ Session manager not available for level change notification")
        
        # Update level manager with the level name
        if self.level_manager:
            # Update the current level
            if hasattr(self.level_manager, 'set_current_level'):
                self.level_manager.set_current_level(level_name)
            logger.debug(f"Updated level manager current level: {level_name}")
        
        # Emit event
        if self.event_manager:
            self.event_manager.emit(EventType.LEVEL_CHANGED, {
                'level_name': level_name,
                'is_gmap': is_gmap,
                'parsed_packet': parsed_packet
            })
    
    def _handle_board_packet(self, parsed_packet: Dict[str, Any]) -> None:
        """Handle PLO_BOARDPACKET - level board data"""
        logger.info("🎮 Received PLO_BOARDPACKET packet")
        
        # Get parsed data from packet
        parsed_data = parsed_packet.get('parsed_data', {})
        tiles = parsed_data.get('tiles', [])
        width = parsed_data.get('width', 64)
        height = parsed_data.get('height', 64)
        data_size = parsed_data.get('data_size', 0)
        statistics = parsed_data.get('statistics', {})
        
        logger.info(f"Board data: {data_size} bytes, {len(tiles)} tiles ({width}x{height})")
        if statistics:
            non_zero = statistics.get('non_zero', 0)
            logger.info(f"  Statistics: {non_zero} non-zero tiles ({non_zero/len(tiles)*100:.1f}% density)")
            
        # For backward compatibility, we need to provide raw board_data 
        # Reconstruct from tiles array if available
        board_data = b''
        if tiles and len(tiles) == width * height:
            # Convert tiles back to bytes (2 bytes per tile, big-endian to match parsing)
            import struct
            board_data = b''.join(struct.pack('>H', tile_id) for tile_id in tiles)
            logger.info(f"  Reconstructed {len(board_data)} bytes from tile array")
        
        # Update level manager with board data
        if self.level_manager:
            # Create a level data object and add to cache
            current_level_name = getattr(self.level_manager, 'current_level', None)
            if current_level_name:
                self._create_level_from_board_data(current_level_name, tiles, board_data, width, height)
            else:
                logger.warning("No current level name set, cannot store board data")
        
        # Emit event
        if self.event_manager:
            self.event_manager.emit(EventType.LEVEL_LOADED, {
                'board_data': board_data,
                'tiles': tiles,
                'parsed_data': parsed_data
            })
    
    def _create_level_from_board_data(self, level_name: str, tiles: list, board_data: bytes, width: int, height: int):
        """Create a level object from received board data and add to cache"""
        from ..models.level import Level
        
        # Convert bytes to string if needed
        if isinstance(level_name, bytes):
            # Remove null terminator if present
            if level_name and level_name[-1] == 0:
                level_name = level_name[:-1]
            level_name = level_name.decode('latin-1', errors='replace')
        
        logger.info(f"🏗️ Creating level '{level_name}' from board data ({width}x{height}, {len(tiles)} tiles)")
        
        # Convert flat array to 2D array for Level model
        tiles_2d = []
        for y in range(height):
            row = []
            for x in range(width):
                idx = y * width + x
                if idx < len(tiles):
                    row.append(tiles[idx])
                else:
                    row.append(0)
            tiles_2d.append(row)
        
        # Create level object
        level = Level(level_name)
        level.width = width
        level.height = height
        level.board_data = board_data
        level.tiles = tiles_2d  # Use 2D array
        
        # Add to level manager cache manually (since it expects to load from disk)
        if hasattr(self.level_manager, 'levels'):
            self.level_manager.levels[level_name] = level
            # Update access time
            if hasattr(self.level_manager, 'access_times'):
                import time
                self.level_manager.access_times[level_name] = time.time()
            logger.info(f"✅ Level '{level_name}' added to cache with {len(tiles)} tiles")
        else:
            logger.warning("Level manager has no 'levels' cache")
    
    def _handle_board_modify(self, packet_data: Dict[str, Any]) -> None:
        """Handle PLO_BOARDMODIFY - board modifications"""
        logger.debug("Received PLO_BOARDMODIFY packet")
        
        # Extract modification data
        fields = packet_data.get('fields', {})
        x = fields.get('x', 0)
        y = fields.get('y', 0)
        tile_id = fields.get('tile_id', 0)
        
        # Update level manager
        if self.level_manager and hasattr(self.level_manager, 'modify_tile'):
            self.level_manager.modify_tile(x, y, tile_id)
        
        # Emit event
        if self.event_manager:
            self.event_manager.emit(EventType.LEVEL_CHANGED, {
                'modification_type': 'tile',
                'x': x,
                'y': y,
                'tile_id': tile_id,
                'fields': fields
            })
    
    def _handle_level_sign(self, packet_data: Dict[str, Any]) -> None:
        """Handle PLO_LEVELSIGN - level signs"""
        logger.debug("Received PLO_LEVELSIGN packet")
        
        fields = packet_data.get('fields', {})
        x = fields.get('x', 0)
        y = fields.get('y', 0)
        text = fields.get('text', '')
        
        logger.info(f"Level sign at ({x}, {y}): {text}")
        
        # Update level manager
        if self.level_manager and hasattr(self.level_manager, 'add_sign'):
            self.level_manager.add_sign(x, y, text)
        
        # Emit event
        if self.event_manager:
            self.event_manager.emit(EventType.LEVEL_CHANGED, {
                'modification_type': 'sign',
                'x': x,
                'y': y,
                'text': text,
                'fields': fields
            })
    
    def _handle_level_chest(self, packet_data: Dict[str, Any]) -> None:
        """Handle PLO_LEVELCHEST - level chests"""
        logger.debug("Received PLO_LEVELCHEST packet")
        
        fields = packet_data.get('fields', {})
        x = fields.get('x', 0)
        y = fields.get('y', 0)
        item_id = fields.get('item_id', 0)
        item_count = fields.get('item_count', 1)
        
        logger.info(f"Level chest at ({x}, {y}): item {item_id} x{item_count}")
        
        # Update level manager
        if self.level_manager and hasattr(self.level_manager, 'add_chest'):
            self.level_manager.add_chest(x, y, item_id, item_count)
        
        # Emit event
        if self.event_manager:
            self.event_manager.emit(EventType.CHEST_OPENED, {
                'x': x,
                'y': y,
                'item_id': item_id,
                'item_count': item_count,
                'fields': fields
            })
    
    def _handle_level_link(self, packet_data: Dict[str, Any]) -> None:
        """Handle PLO_LEVELLINK - level links with automatic GMAP level requests"""
        logger.debug("Received PLO_LEVELLINK packet")
        
        fields = packet_data.get('fields', {})
        link_data = fields.get('link_data', '')
        
        # Extract level name from link data for GMAP auto-request
        level_name = None
        if link_data:
            # Link data format: "levelname.nw x y w h destx desty"
            parts = link_data.split()
            if parts:
                level_name = parts[0]
                if level_name and level_name.endswith('.nw'):
                    # Check if we're in GMAP mode or current level suggests GMAP context
                    should_request = False
                    
                    if self.session_manager and hasattr(self.session_manager, 'is_gmap_mode'):
                        should_request = self.session_manager.is_gmap_mode()
                    
                    # Also check if current level name suggests GMAP context
                    if not should_request and self.session_manager:
                        current_level = getattr(self.session_manager, 'current_level_name', '')
                        if current_level and (current_level.endswith('.gmap') or current_level.startswith('chicken')):
                            should_request = True
                            logger.debug(f"🗺️ Detected GMAP context from level: {current_level}")
                    
                    if should_request:
                        self._auto_request_gmap_level(level_name)
        
        # Update level manager (if it has add_link method)
        if self.level_manager and hasattr(self.level_manager, 'add_link'):
            self.level_manager.add_link(link_data)
        
        # Emit event
        if self.event_manager:
            self.event_manager.emit(EventType.LEVEL_CHANGED, {
                'modification_type': 'link',
                'link_data': link_data,
                'level_name': level_name,
                'fields': fields
            })
    
    def _auto_request_gmap_level(self, level_name: str):
        """Automatically request a level file in GMAP mode
        
        Args:
            level_name: Name of level to request
        """
        if not self.client or not level_name:
            return
        
        # Avoid duplicate requests
        if level_name in self.discovered_links:
            return
        
        try:
            # Check if client is authenticated before making requests
            is_authenticated = getattr(self.client, 'authenticated', False)
            
            if not is_authenticated:
                # Defer the request until authentication is complete
                logger.info(f"🗺️ Deferring GMAP level request until authenticated: {level_name}")
                
                # Store for later retry
                if not hasattr(self, 'deferred_requests'):
                    self.deferred_requests = set()
                self.deferred_requests.add(level_name)
                return
            
            logger.info(f"🗺️ Auto-requesting GMAP level: {level_name}")
            
            # Request the level file
            if hasattr(self.client, 'request_file'):
                success = self.client.request_file(level_name)
                if success:
                    self.discovered_links.add(level_name)
                    logger.info(f"✅ GMAP level request sent: {level_name}")
                else:
                    logger.warning(f"⚠️ Failed to request GMAP level: {level_name}")
            else:
                logger.warning("Client does not have request_file method")
                
        except Exception as e:
            logger.error(f"Failed to auto-request GMAP level {level_name}: {e}")
    
    def process_deferred_requests(self):
        """Process any deferred file requests once authentication is complete"""
        if not hasattr(self, 'deferred_requests') or not self.deferred_requests:
            return
        
        deferred_files = list(self.deferred_requests)
        logger.info(f"🔄 Processing {len(deferred_files)} deferred file requests...")
        
        for level_name in deferred_files:
            # Remove from deferred list first to avoid infinite loops
            self.deferred_requests.discard(level_name)
            
            # Try to request now that authentication is complete
            self._auto_request_gmap_level(level_name)
    
    def _handle_file(self, packet_data: Dict[str, Any]) -> None:
        """Handle PLO_FILE - file transfers (usually level files)"""
        logger.info("📁 Received PLO_FILE packet")
        
        fields = packet_data.get('fields', {})
        filename = fields.get('filename', '')
        file_data = fields.get('file_data', b'')
        
        logger.info(f"File received: {filename} ({len(file_data)} bytes)")
        
        # Update level manager with file
        if self.level_manager and hasattr(self.level_manager, 'load_file'):
            self.level_manager.load_file(filename, file_data)
        
        # Emit event
        if self.event_manager:
            self.event_manager.emit(EventType.LEVEL_LOADED, {
                'filename': filename,
                'file_data': file_data,
                'fields': fields
            })