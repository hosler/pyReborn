"""
Main Reborn client implementation
"""

import socket
import struct
import threading
import time
import zlib
import bz2
import random
import logging
from typing import Optional, Dict, Any, List, Callable, Tuple
from queue import Queue, Empty

from ..protocol.enums import (
    PlayerToServer, ServerToPlayer, PlayerProp, 
    Direction, LevelItemType, ClientVersion
)
from ..protocol.packets import (
    LoginPacket, PlayerPropsPacket, ToAllPacket, BombAddPacket,
    ArrowAddPacket, FireSpyPacket, WeaponAddPacket, ShootPacket,
    Shoot2Packet, WantFilePacket, FlagSetPacket, PrivateMessagePacket
)
from .encryption import RebornEncryption, CompressionType
from ..protocol.version_codecs import create_codec
from ..handlers.packet_handler import PacketHandler
from ..models.player import Player
from ..models.level import Level
from .events import EventType, EventManager
from ..managers.session import SessionManager
from ..managers.level_manager import LevelManager
from ..actions.core_actions import PlayerActions
from ..file_request_tracker import FileRequestTracker
from ..managers import ItemManager, CombatManager, NPCManager
from ..utils.gmap_utils import GMAPUtils
from ..actions.items import ItemActions
from ..actions.combat import CombatActions
from ..actions.npcs import NPCActions
from ..serverlist.client import ServerListClient
from ..serverlist.models import ServerInfo
from .cache_manager import CacheManager


class RebornClient:
    """Main client for connecting to Reborn servers"""
    
    def __init__(self, host: str, port: int = 14900, version: str = "2.22", cache_dir: Optional[str] = None, disable_cache: bool = False):
        self.host = host
        self.port = port
        self.disable_cache = disable_cache
        
        # Setup logger with module prefix
        from ..utils.logging_config import ModuleLogger
        self.logger = ModuleLogger.get_logger(__name__)
        
        # Initialize cache manager (disable_cache means ignore cached files)
        self.cache_manager = CacheManager(cache_dir, disabled=disable_cache)
        
        # Version configuration
        from ..protocol.versions import get_version_config, get_default_version
        self.version_config = get_version_config(version) or get_default_version()
        
        # Network
        self.socket: Optional[socket.socket] = None
        self.connected = False
        self.running = False
        self._recent_packets = []  # Track last packets for disconnect debugging
        
        # Packet buffers
        self.send_queue = Queue()
        self.receive_buffer = Queue()
        self.send_thread: Optional[threading.Thread] = None
        self.receive_thread: Optional[threading.Thread] = None
        self.packet_send_rate = 0.05  # 50ms between packets for faster response
        
        # Encryption 
        self.encryption_key = random.randint(0, 255)
        self.version_codec = None  # Created after login based on version
        # Keep old codecs for compatibility during transition
        self.in_codec = RebornEncryption()
        self.out_codec = RebornEncryption()
        self.first_encrypted_packet = True
        
        # Protocol
        self.packet_handler = PacketHandler(self)
        self.client_version = ClientVersion.VERSION_22
        
        # State
        self.local_player = Player()
        self.local_player.is_local = True  # Mark as local player
        self.players: Dict[int, Player] = {}
        self.current_level: Optional[Level] = None
        self.login_success = False
        self.level_loaded = False
        self.levels: Dict[str, Level] = {}
        self.flags: Dict[str, str] = {}
        
        # GMAP state tracking
        self._is_gmap_mode = False  # Are we currently on a GMAP?
        self._gmap_enabled = True  # Allow clients to disable GMAP behavior
        self._current_gmap_name = None  # Base name of current GMAP (without .gmap)
        self._gmap_data = {}  # Cached GMAP metadata from server
        
        # Multi-packet board data handling (for ENCRYPT_GEN_5)
        self.partial_board_data = b''
        self.expecting_board_continuation = False
        self.expected_next_packet_size = 0  # Size from PLO_RAWDATA
        self.pending_board_data = None  # Board data waiting for level
        self.board_data_level_name = None  # Which level the pending board data belongs to
        self.expecting_text_board_data = False  # True when expecting BOARD text lines after PLO_FILE
        
        # Events
        self.events = EventManager()
        
        # Session management
        self.session = SessionManager()
        
        # Level management
        self.level_manager = LevelManager(self)
        
        # GMAP management (separate from level management)
        from ..managers.gmap_manager import GMapManager
        self.gmap_manager = GMapManager(self)
        
        # File request tracking for debugging
        self.file_tracker = FileRequestTracker()
        
        # Board collector for text-based board data
        from .board_collector import BoardCollector
        from .text_data_handler import TextDataHandler
        from .raw_data_handler import RawDataHandler
        self._board_collector = BoardCollector(self.events)
        self._text_handler = TextDataHandler(self.events)
        self._raw_data_handler = RawDataHandler(self.events, self.level_manager, self.cache_manager)
        
        # Actions delegate
        self._actions = PlayerActions(self)
        self.actions = self._actions  # Expose actions publicly
        
        # Extended managers
        self.item_manager = ItemManager()
        self.combat_manager = CombatManager()
        self.npc_manager = NPCManager()
        
        # Extended actions
        self.items = ItemActions(self)
        self.combat = CombatActions(self)
        self.npcs = NPCActions(self)
        
        # Threading
        self._recv_thread: Optional[threading.Thread] = None
        self._send_queue: Queue = Queue()
        self._send_thread: Optional[threading.Thread] = None
        self._keepalive_thread: Optional[threading.Thread] = None
        self._last_packet_time = 0
        
        # Register extended packet handlers
        self._register_extended_handlers()
        
        # Subscribe to board complete event
        self.events.subscribe(EventType.LEVEL_BOARD_COMPLETE, self._on_board_complete)
        
        # Subscribe to FILE_RECEIVED event from raw_data_handler
        self.events.subscribe(EventType.FILE_RECEIVED, self._on_file_received_from_raw_handler)
    
    @staticmethod
    def get_server_list(account: str, password: str) -> Tuple[List[ServerInfo], dict]:
        """Get list of available servers from the listserver.
        
        This is a static method that doesn't require a connected client.
        
        Args:
            account: Account name for authentication
            password: Account password
            
        Returns:
            Tuple of (list of ServerInfo objects, dict with status/urls)
        """
        client = ServerListClient()
        try:
            servers, status_info = client.get_servers(account, password)
            return servers, status_info
        finally:
            client.disconnect()
    
    def connect(self) -> bool:
        """Connect to server"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
            self.connected = True
            self.running = True
            
            # Set server info in cache manager
            self.cache_manager.set_server(self.host, self.port)
            
            # Start threads
            # Start buffer threads
            self.receive_thread = threading.Thread(target=self._receive_loop, name="RebornReceive")
            self.receive_thread.daemon = True
            self.receive_thread.start()
            
            self.send_thread = threading.Thread(target=self._send_loop, name="RebornSend")
            self.send_thread.daemon = True
            self.send_thread.start()
            
            self.events.emit(EventType.CONNECTED)
            return True
            
        except Exception as e:
            self.logger.error(f"Connection failed: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from server"""
        self.running = False
        
        # Print file tracker summary on disconnect
        if hasattr(self, 'file_tracker'):
            self.logger.info("Printing file tracker summary...")
            self.file_tracker.print_summary()
            self.file_tracker.save_log("file_requests.log")
        
        # Wait for threads to finish
        if hasattr(self, 'send_thread') and self.send_thread and self.send_thread.is_alive():
            self.send_thread.join(timeout=1.0)
        if hasattr(self, 'receive_thread') and self.receive_thread and self.receive_thread.is_alive():
            self.receive_thread.join(timeout=1.0)
        if hasattr(self, '_keepalive_thread') and self._keepalive_thread and self._keepalive_thread.is_alive():
            self._keepalive_thread.join(timeout=1.0)
            
        if self.socket:
            self.socket.close()
        self.connected = False
        self.events.emit(EventType.DISCONNECTED)
    
    def login(self, account: str, password: str, timeout: float = 5.0) -> bool:
        """Login to server and wait for response"""
        if not self.connected:
            return False
            
        # Create login packet with encryption key and version config
        packet = LoginPacket(account, password, self.encryption_key, self.version_config)
        raw_data = packet.to_bytes()
        
        # Send login packet with proper compression based on encryption generation
        from ..protocol.versions import EncryptionType
        if self.version_config.encryption == EncryptionType.ENCRYPT_GEN_1:
            # No compression
            self._send_packet_raw(raw_data)
        elif self.version_config.encryption == EncryptionType.ENCRYPT_GEN_2:
            # Zlib compression
            compressed = zlib.compress(raw_data)
            self._send_packet_raw(compressed)
        elif self.version_config.encryption == EncryptionType.ENCRYPT_GEN_3:
            # Zlib compression (individual packets encrypted later)
            compressed = zlib.compress(raw_data)
            self._send_packet_raw(compressed)
        elif self.version_config.encryption == EncryptionType.ENCRYPT_GEN_4:
            # Zlib compression for login packet (BZ2 is for subsequent packets)
            compressed = zlib.compress(raw_data)
            self._send_packet_raw(compressed)
        elif self.version_config.encryption == EncryptionType.ENCRYPT_GEN_5:
            # Dynamic compression - use zlib for login packet
            compressed = zlib.compress(raw_data)
            self._send_packet_raw(compressed)
        else:
            # Fallback - no compression
            self._send_packet_raw(raw_data)
        
        # Setup encryption based on version AFTER sending login packet
        self.version_codec = create_codec(self.version_config.encryption, self.encryption_key)
        # Also setup old codecs for compatibility
        self.in_codec.reset(self.encryption_key)
        self.out_codec.reset(self.encryption_key)
        self.first_encrypted_packet = True
        self.first_recv_packet = True
        
        # Track connection time
        self.connection_start_time = time.time()
        self._last_world_time = 0  # Track last NEWWORLDTIME packet
        
        self.logger.info(f"Sent login: account={account}")
        
        # Wait for login response (PLO_SIGNATURE packet)
        self.login_success = False
        self.level_loaded = False
        self.board_data_received = False
        start_time = time.time()
        
        # Wait for login success first
        while time.time() - start_time < timeout:
            if self.login_success:
                self.logger.info("Login accepted by server")
                break
            time.sleep(0.1)
            
        if not self.login_success:
            self.logger.error("Login timeout - no response from server")
            return False
            
        # Now wait for initial board data
        self.logger.info("Waiting for initial level data...")
        board_wait_start = time.time()
        while time.time() - board_wait_start < 5.0:  # Wait up to 5 more seconds
            # Check if we have board data
            if hasattr(self, 'board_buffer') and len(self.board_buffer) >= 8192:
                self.board_data_received = True
                self.logger.debug("Board data received through buffer")
                break
            # Check both level manager and client level for board data
            level_has_board = False
            if self.level_manager.current_level and hasattr(self.level_manager.current_level, 'board_tiles_64x64') and self.level_manager.current_level.board_tiles_64x64:
                level_has_board = True
            elif self.current_level and hasattr(self.current_level, 'board_tiles_64x64') and self.current_level.board_tiles_64x64:
                level_has_board = True
            # Also check if any non-gmap level has board data
            elif any(hasattr(level, 'board_tiles_64x64') and level.board_tiles_64x64 
                    for name, level in self.levels.items() if not name.endswith('.gmap')):
                level_has_board = True
                
            if level_has_board:
                self.board_data_received = True
                self.logger.debug("Board data received in level")
                break
            time.sleep(0.1)
            
        if not self.board_data_received:
            self.logger.warning("No board data received yet (may come later)")
            
        return True
    
    # Movement and properties
    def move_to(self, x: float, y: float, direction: Optional[Direction] = None):
        """Move to position"""
        self._actions.move_to(x, y, direction)
    
    def set_nickname(self, nickname: str):
        """Set nickname"""
        self._actions.set_nickname(nickname)
    
    def set_chat(self, message: str):
        """Set chat bubble"""
        self._actions.set_chat(message)
    
    def say(self, message: str):
        """Send chat message to all"""
        self._actions.say(message)
    
    def set_body_image(self, body_image: str):
        """Set body image"""
        self._actions.set_body_image(body_image)
    
    def set_head_image(self, head_image: str):
        """Set head image"""
        self._actions.set_head_image(head_image)
    
    def set_gani(self, gani: str):
        """Set animation"""
        self._actions.set_gani(gani)
    
    def set_carry_sprite(self, sprite_id: int):
        """Set carry sprite (item being carried)"""
        self._actions.set_carry_sprite(sprite_id)
    
    def warp_to_level(self, level_name: str, x: float = 30.0, y: float = 30.0):
        """Warp to a specific level"""
        self._actions.warp_to_level(level_name, x, y)
    
    def request_adjacent_level(self, x: int, y: int):
        """Request adjacent level data for gmap streaming"""
        self._actions.request_adjacent_level(x, y)
    
    # Combat
    def drop_bomb(self, x: Optional[float] = None, y: Optional[float] = None, 
                  power: int = 1, timer: int = 55):
        """Drop a bomb"""
        self._actions.drop_bomb(x, y, power)
    
    def shoot_arrow(self):
        """Shoot arrow (simple)"""
        self._actions.shoot_arrow()
    
    def fire_effect(self):
        """Create fire effect"""
        self._actions.fire_effect()
    
    def add_weapon(self, weapon_id: LevelItemType):
        """Add weapon"""
        packet = WeaponAddPacket(int(weapon_id))
        self._send_packet(packet)
    
    def shoot_projectile(self, x: Optional[float] = None, y: Optional[float] = None,
                        angle: float = 0, speed: int = 20, gani: str = ""):
        """Shoot projectile (v1 format)"""
        if x is None:
            x = self.local_player.x
        if y is None:
            y = self.local_player.y
            
        packet = ShootPacket(x, y, angle, speed, gani)
        self._send_packet(packet)
    
    def shoot_projectile_v2(self, x: Optional[float] = None, y: Optional[float] = None,
                           angle: float = 0, speed: int = 20, gravity: int = 8, gani: str = ""):
        """Shoot projectile (v2 format with gravity)"""
        if x is None:
            x = self.local_player.x
        if y is None:
            y = self.local_player.y
            
        packet = Shoot2Packet(x, y, angle, speed, gravity, gani)
        self._send_packet(packet)
    
    # Items and inventory
    def set_arrows(self, count: int):
        """Set arrow count"""
        self._actions.set_arrows(count)
    
    def set_bombs(self, count: int):
        """Set bomb count"""
        self._actions.set_bombs(count)
    
    def set_rupees(self, count: int):
        """Set rupee count"""
        self._actions.set_rupees(count)
    
    def set_hearts(self, current: float, maximum: Optional[float] = None):
        """Set hearts"""
        self._actions.set_hearts(current, maximum)
    
    # Files and flags
    def request_file(self, filename: str):
        """Request file from server"""
        # Track all file requests
        if not hasattr(self, '_all_file_requests'):
            self._all_file_requests = []
        self._all_file_requests.append((time.time(), filename))
        
        # Log if we're requesting a lot of files quickly
        recent_requests = [f for t, f in self._all_file_requests if time.time() - t < 5.0]
        if len(recent_requests) > 10:
            self.logger.warning(f"High file request rate: {len(recent_requests)} files in 5 seconds")
            self.logger.debug(f"Recent file requests: {recent_requests[-5:]}")
        
        self.logger.debug(f"[FILE REQUEST] Requesting file: {filename}")
        packet = WantFilePacket(filename)
        self._send_packet(packet)
    
    def set_flag(self, flag_name: str, value: str = ""):
        """Set server flag"""
        packet = FlagSetPacket(flag_name, value)
        self._send_packet(packet)
        self.flags[flag_name] = value
    
    def send_pm(self, player_id: int, message: str):
        """Send private message"""
        self._actions.send_pm(player_id, message)
    
    def _decode_truncated_hex(self, truncated_hex):
        """Decode truncated hex board data to binary format"""
        self.logger.debug(f"Decoding {len(truncated_hex)} characters of truncated hex")
        
        # Base64 character set for truncated hex  
        base64_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
        
        board_data = bytearray(8192)  # 4096 tiles * 2 bytes each
        
        tile_count = 0
        for i in range(0, len(truncated_hex), 2):
            if i + 1 < len(truncated_hex) and tile_count < 4096:
                char1 = truncated_hex[i]
                char2 = truncated_hex[i + 1]
                
                if char1 in base64_chars and char2 in base64_chars:
                    # Convert two chars to tile ID
                    tile_id = base64_chars.index(char1) * 64 + base64_chars.index(char2)
                    
                    # Store as little-endian 2-byte value
                    struct.pack_into('<H', board_data, tile_count * 2, tile_id)
                    tile_count += 1
                else:
                    # Invalid character, use tile ID 0
                    struct.pack_into('<H', board_data, tile_count * 2, 0)
                    tile_count += 1
        
        self.logger.debug(f"   Decoded {tile_count} tiles from truncated hex")
        
        # Show first few tile IDs for verification
        first_tiles = []
        for i in range(min(10, tile_count)):
            tile_id = struct.unpack('<H', board_data[i*2:i*2+2])[0]
            first_tiles.append(tile_id)
        self.logger.debug(f"   First 10 tile IDs: {first_tiles}")
        
        return bytes(board_data)
    
    
    # Event subscription
    def on(self, event_type: EventType, handler: Callable):
        """Subscribe to event"""
        self.events.subscribe(event_type, handler)
    
    def off(self, event_type: EventType, handler: Callable):
        """Unsubscribe from event"""
        self.events.unsubscribe(event_type, handler)
    
    # Packet buffer access
    def get_buffered_packet(self, timeout: float = 0.1):
        """Get a packet from receive buffer (non-blocking)"""
        try:
            return self.receive_buffer.get(timeout=timeout)
        except Empty:
            return None
    
    def has_buffered_packets(self) -> bool:
        """Check if there are buffered packets"""
        return not self.receive_buffer.empty()
    
    def clear_send_queue(self):
        """Clear pending send packets"""
        while not self.send_queue.empty():
            try:
                self.send_queue.get_nowait()
            except Empty:
                break
    
    def set_packet_send_rate(self, rate: float):
        """Set delay between sent packets (seconds)"""
        self.packet_send_rate = max(0.01, rate)  # Minimum 10ms
    
    # Game state access methods
    def get_all_players(self) -> Dict[int, 'Player']:
        """Get all tracked players"""
        return self.players.copy()
    
    def get_player_by_id(self, player_id: int) -> Optional['Player']:
        """Get player by ID"""
        return self.players.get(player_id)
    
    def get_players_by_nickname(self, nickname: str) -> List['Player']:
        """Get players by nickname"""
        return [p for p in self.players.values() if p.nickname == nickname]
    
    def get_nearby_players(self, x: float, y: float, radius: float = 5.0) -> List['Player']:
        """Get players within radius of position"""
        nearby = []
        for player in self.players.values():
            dx = player.x - x
            dy = player.y - y
            distance = (dx * dx + dy * dy) ** 0.5
            if distance <= radius:
                nearby.append(player)
        return nearby
    
    def get_current_level_name(self) -> Optional[str]:
        """Get current level name"""
        return self.current_level.name if self.current_level else None
    
    def get_player_count(self) -> int:
        """Get number of tracked players"""
        return len(self.players)
    
    def is_player_online(self, nickname: str) -> bool:
        """Check if player with nickname is online"""
        return any(p.nickname == nickname for p in self.players.values())
    
    # Session management methods
    def get_session_summary(self) -> Dict[str, Any]:
        """Get comprehensive session summary"""
        return self.session.get_session_summary()
        
    def get_conversation_with(self, player_id: int) -> List[Any]:
        """Get PM conversation with player"""
        return self.session.get_conversation_with(player_id)
        
    def get_recent_chat(self, level_name: Optional[str] = None, limit: int = 10) -> List[Any]:
        """Get recent chat messages"""
        return self.session.get_recent_chat(level_name, limit)
        
    def get_level_session_info(self, level_name: str) -> Optional[Dict[str, Any]]:
        """Get level session information"""
        return self.session.get_level_session_info(level_name)
        
    def get_player_stats(self, player_id: int) -> Optional[Dict[str, Any]]:
        """Get detailed player statistics"""
        return self.session.get_player_stats(player_id)
        
    def find_players_by_name(self, name: str) -> List[Player]:
        """Find players by name (fuzzy search)"""
        return self.session.find_players_by_name(name)
        
    def get_level_visit_history(self) -> List[Tuple[str, float, float]]:
        """Get level visit history with durations"""
        return self.session.get_level_visit_history()
    
    # Cache management methods
    def get_cache_info(self) -> Dict[str, Any]:
        """Get information about cache usage"""
        return self.cache_manager.get_cache_info()
    
    def clear_cache(self, levels_only: bool = False):
        """Clear cache files
        
        Args:
            levels_only: If True, only clear level files for current server
        """
        self.cache_manager.clear_cache(levels_only)
    
    def get_asset_paths(self) -> Dict[str, Any]:
        """Get asset directory paths for game loading"""
        return self.cache_manager.get_asset_paths()
    
    # Level management convenience methods
    def get_current_level(self) -> Optional[Level]:
        """Get the current level object"""
        return self.level_manager.get_current_level()
    
    def get_level(self, name: str) -> Optional[Level]:
        """Get a level by name"""
        return self.level_manager.get_level(name)
    
    def get_tile(self, x: int, y: int, layer: int = 0) -> int:
        """Get tile at position in current level"""
        return self.level_manager.get_tile(x, y, layer)
    
    def is_position_blocked(self, x: float, y: float) -> bool:
        """Check if position is blocked by tiles"""
        return self.level_manager.is_position_blocked(x, y)
    
    def find_level_links_at(self, x: float, y: float) -> List:
        """Find level links at position"""
        return self.level_manager.find_level_links_at(x, y)
    
    def get_current_level_signs(self) -> List:
        """Get all signs in current level"""
        level = self.get_current_level()
        return level.signs if level else []
    
    def get_current_level_chests(self) -> List:
        """Get all chests in current level"""
        level = self.get_current_level()
        return level.chests if level else []
    
    def get_current_level_npcs(self) -> Dict:
        """Get all NPCs in current level"""
        level = self.get_current_level()
        return level.npcs if level else {}
    
    def get_level_size(self) -> Tuple[int, int]:
        """Get current level dimensions (width, height)"""
        level = self.get_current_level()
        return (level.width, level.height) if level else (0, 0)
    
    def request_level_file(self, level_name: str, callback: Optional[Callable] = None):
        """Request a level file from the server"""
        filename = f"{level_name}.nw"
        self.level_manager.request_file(filename, callback)
    
    def set_level_cache_directory(self, cache_dir: str):
        """Set directory for caching level files and assets"""
        self.level_manager.set_cache_directory(cache_dir)
    
    def get_level_summary(self) -> Dict[str, Any]:
        """Get comprehensive level manager summary"""
        return self.level_manager.get_level_summary()
    
    def get_loaded_levels(self) -> List[str]:
        """Get names of all loaded levels"""
        return list(self.level_manager.levels.keys())
    
    def get_cached_assets(self) -> List[str]:
        """Get list of cached asset filenames"""
        return list(self.level_manager.assets.keys())
    
    def load_tile_mapping(self, tileset_dir: str) -> bool:
        """Load Reborn tile mapping for collision detection"""
        return self.level_manager.load_tile_mapping(tileset_dir)
    
    def analyze_current_level_tiles(self) -> Dict[str, Any]:
        """Analyze tile composition of current level"""
        return self.level_manager.analyze_current_level_tiles()
    
    def is_position_blocked_precise(self, x: float, y: float) -> bool:
        """Check if position is blocked using tile mapping data"""
        return self.level_manager.is_position_blocked_by_tiles(x, y)
    
    # Internal methods (fixed to match working client)
    def _send_packet(self, packet: Any):
        """Queue packet for sending"""
        # Log property packets for debugging
        if hasattr(packet, '__class__') and packet.__class__.__name__ == 'PlayerPropsPacket':
            props_sent = []
            if hasattr(packet, 'properties'):
                for prop_id, _ in packet.properties:
                    props_sent.append(prop_id.name if hasattr(prop_id, 'name') else str(prop_id))
            if props_sent:
                self.logger.debug(f"[PROPS] Sending properties: {', '.join(props_sent)}")
        
        self.queue_packet(packet.to_bytes())
    
    def _send_packet_raw(self, data: bytes):
        """Send raw packet immediately (for login)"""
        length = struct.pack('>H', len(data))
        self.socket.sendall(length + data)
    
    def queue_packet(self, data: bytes):
        """Queue packet for threaded sending"""
        # Track file requests (PLI_WANTFILE = 23, so with +32 encoding = 55)
        if len(data) >= 2 and data[0] == 55:  # PLI_WANTFILE with +32 encoding
            # Extract filename from packet (skip packet ID)
            try:
                filename = data[1:].decode('ascii', errors='ignore').rstrip('\n')
                self.file_tracker.on_file_requested(filename)
                self.events.emit(EventType.FILE_REQUESTED, filename=filename)
            except:
                pass
        
        # Use version-specific codec if available
        if self.version_codec:
            packet = self.version_codec.send_packet(data)
            
            # Drop movement packets if queue is getting full
            queue_size = self.send_queue.qsize()
            is_movement_packet = len(data) >= 1 and data[0] == 34  # PLI_PLAYERMOVE (2 + 32 = 34)
            
            if is_movement_packet and queue_size > 5:
                # Drop movement packet to prevent queue buildup
                self.logger.debug(f"[QUEUE] Dropped movement packet, queue size: {queue_size}")
                return
                
            self.send_queue.put(packet)
            return
            
        # Fallback to ENCRYPT_GEN_5 behavior for compatibility
        # Determine compression type (matches GServer behavior)
        if len(data) <= 55:
            compression_type = CompressionType.UNCOMPRESSED
            compressed_data = data
        elif len(data) > 0x2000:  # > 8KB
            compression_type = CompressionType.BZ2
            compressed_data = bz2.compress(data)
        else:
            compression_type = CompressionType.ZLIB
            compressed_data = zlib.compress(data)
        
        # Create a new codec for this packet with the appropriate limit
        packet_codec = RebornEncryption(self.encryption_key)
        packet_codec.iterator = self.out_codec.iterator  # Copy current iterator state
        packet_codec.limit_from_type(compression_type)
        
        # Encrypt data
        encrypted_data = packet_codec.encrypt(compressed_data)
        
        # Update our main codec's iterator to maintain state
        self.out_codec.iterator = packet_codec.iterator
        
        # Build final packet
        packet = bytes([compression_type]) + encrypted_data
        length = struct.pack('>H', len(packet))
        final_packet = length + packet
        
        # Drop movement packets if queue is getting full
        queue_size = self.send_queue.qsize()
        is_movement_packet = len(data) >= 1 and data[0] == 34  # PLI_PLAYERMOVE (2 + 32 = 34)
        
        if is_movement_packet and queue_size > 5:
            # Drop movement packet to prevent queue buildup
            self.logger.debug(f"[QUEUE] Dropped movement packet (fallback), queue size: {queue_size}")
            return
            
        # Queue for sending
        self.send_queue.put(final_packet)
    
    def send_encrypted_packet(self, data: bytes):
        """Legacy method - redirects to queue"""
        self.queue_packet(data)
    
    def _send_loop(self):
        """Send thread loop with rate limiting"""
        packets_sent = 0
        packets_per_second = []
        last_stats_time = time.time()
        packet_type_counts = {}  # Track packet types
        
        while self.running:
            try:
                # Get packet from queue (blocking with timeout)
                packet = self.send_queue.get(timeout=0.1)
                
                # Send packet only if socket is still connected
                if self.socket and self.connected:
                    # Debug packet info
                    if len(packet) >= 3:
                        packet_type = packet[2] if len(packet) > 2 else -1
                        # Only log every 10th packet to reduce spam
                        if packets_sent % 10 == 0:
                            self.logger.debug(f"[SEND] Packet #{packets_sent}, type: {packet_type}, size: {len(packet)} bytes, rate: {len(packets_per_second)}/sec")
                        
                        # Track packet types
                        if packet_type not in packet_type_counts:
                            packet_type_counts[packet_type] = 0
                        packet_type_counts[packet_type] += 1
                    
                    self.socket.sendall(packet)
                    self._last_packet_time = time.time()
                    packets_sent += 1
                    
                    # Track packets per second
                    current_time = time.time()
                    packets_per_second.append(current_time)
                    # Remove packets older than 1 second
                    packets_per_second = [t for t in packets_per_second if current_time - t < 1.0]
                    
                    # Log stats every 5 seconds
                    if current_time - last_stats_time >= 5.0:
                        self.logger.info(f"[SEND STATS] Total sent: {packets_sent}, Rate: {len(packets_per_second)}/sec, Queue size: {self.send_queue.qsize()}")
                        # Show top packet types
                        top_types = sorted(packet_type_counts.items(), key=lambda x: x[1], reverse=True)[:5]
                        self.logger.info(f"[SEND TYPES] Top packets: {top_types}")
                        last_stats_time = current_time
                else:
                    # Socket closed, exit loop
                    break
                
                # Rate limiting to prevent encryption desync
                time.sleep(self.packet_send_rate)
                
            except Empty:
                continue
            except (BrokenPipeError, ConnectionResetError, OSError) as e:
                # Connection lost - this is expected when disconnecting
                if self.running:
                    self.logger.error(f"Connection lost in send thread: {e}")
                    self.logger.error(f"Stats at disconnect: packets_sent={packets_sent}, last_rate={len(packets_per_second)}/sec")
                    if isinstance(e, BrokenPipeError):
                        self.logger.info("Server closed the connection - likely due to timeout (5 minute limit)")
                        self.logger.info("Keepalive should have prevented this - checking keepalive status...")
                        if hasattr(self, '_last_packet_time'):
                            time_since_last = time.time() - self._last_packet_time
                            self.logger.info(f"Last packet was sent {time_since_last:.1f} seconds ago")
                self.connected = False
                self.running = False
                # Calculate connection duration
                if hasattr(self, 'connection_start_time'):
                    duration = time.time() - self.connection_start_time
                    self.logger.error(f"[DISCONNECT] Connection lasted {duration:.1f} seconds")
                # Check last world time
                if hasattr(self, '_last_world_time') and self._last_world_time > 0:
                    world_time_ago = time.time() - self._last_world_time
                    self.logger.error(f"[DISCONNECT] Last NEWWORLDTIME was {world_time_ago:.1f} seconds ago (should be <5s)")
                # Dump final packet type stats
                self.logger.error(f"[DISCONNECT] Final packet type breakdown:")
                for ptype, count in sorted(packet_type_counts.items(), key=lambda x: x[1], reverse=True):
                    self.logger.error(f"  Type {ptype}: {count} packets")
                self.events.emit(EventType.DISCONNECTED, reason="Server timeout")
                break
            except Exception as e:
                # Other unexpected errors
                if self.running:
                    self.logger.error(f"Unexpected send thread error: {e}", exc_info=True)
                break
    
    def _receive_loop(self):
        """Receive thread loop with buffering"""
        self.socket.settimeout(1.0)
        packets_received = 0
        last_packet_time = time.time()
        
        while self.running:
            try:
                packet = self.recv_packet()
                if packet:
                    packets_received += 1
                    current_time = time.time()
                    time_since_last = current_time - last_packet_time
                    last_packet_time = current_time
                    
                    # Log unusual gaps
                    if time_since_last > 10.0:
                        self.logger.warning(f"[RECV] Long gap since last packet: {time_since_last:.1f}s")
                    
                    # Debug packet type
                    if len(packet) >= 1:
                        packet_type = packet[0]
                        self.logger.debug(f"[RECV] Packet type: {packet_type}, size: {len(packet)} bytes, total received: {packets_received}")
                    
                    # Buffer received packet
                    self.receive_buffer.put(packet)
                    # Also process immediately for real-time events
                    self._process_packet(packet)
            except socket.timeout:
                continue  # Normal timeout, continue
            except socket.error as e:
                if self.running:
                    self.logger.error(f"Socket error in receive thread: {e}")
                    self.logger.error(f"Stats at disconnect: packets_received={packets_received}, time_since_last_packet={time.time() - last_packet_time:.1f}s")
                    break
            except Exception as e:
                if self.running:  # Only print if not shutting down
                    self.logger.error(f"Receive thread error: {e}", exc_info=True)
                break
                
        # Auto-disconnect on receive error
        if self.running:
            self.logger.error("Connection lost - disconnecting...")
            self.disconnect()
    
    def recv_packet(self):
        """Receive a packet"""
        try:
            length_data = self._recv_exact(2)
            if not length_data:
                return None
            length = struct.unpack('>H', length_data)[0]
            return self._recv_exact(length)
        except socket.timeout:
            return None
        except Exception as e:
            if self.running:
                self.logger.warning(f"Error receiving packet: {e}")
            return None
            
    def _recv_exact(self, size: int):
        """Receive exact number of bytes"""
        data = b''
        while len(data) < size:
            try:
                chunk = self.socket.recv(size - len(data))
                if not chunk:
                    if self.connected:  # Only log once
                        self.logger.error(f"[DISCONNECT] socket.recv returned empty data - connection closed by remote")
                        self.connected = False
                    return None
                data += chunk
            except socket.timeout:
                if data:
                    continue
                return None
            except Exception as e:
                if self.running:
                    self.logger.warning(f"Error receiving exact bytes: {e}")
                return None
        return data
    
    def _process_packet(self, data: bytes):
        """Process incoming packet"""
        if not data:
            return
            
        # Try to decrypt and process
        try:
            decrypted = self.recv_encrypted_packet_data(data)
            if not decrypted:
                return
            
            
            # Check if we're in board data streaming mode - collect truncated hex from large packets!
            if hasattr(self, 'board_stream_active') and self.board_stream_active:
                # Look for large packets containing truncated hex board data
                # These appear as negative packet IDs with 1900+ bytes of data
                pos = 0
                while pos < len(decrypted):
                    if pos + 3 < len(decrypted):
                        # Read packet ID and size
                        packet_id = struct.unpack('<h', decrypted[pos:pos+2])[0]  # signed short
                        packet_size = struct.unpack('<H', decrypted[pos+2:pos+4])[0]  # unsigned short
                        
                        # Check if this is a large packet with board data
                        if packet_size >= 1900 and pos + 4 + packet_size <= len(decrypted):
                            self.logger.debug(f"Found large packet: ID={packet_id}, Size={packet_size} bytes (likely board data)")
                            
                            # Extract the packet data (truncated hex)
                            packet_data = decrypted[pos+4:pos+4+packet_size]
                            
                            # Initialize board buffer if not exists
                            if not hasattr(self, 'board_hex_buffer'):
                                self.board_hex_buffer = b''
                            
                            # Append truncated hex data
                            self.board_hex_buffer += packet_data
                            self.logger.debug(f"   Collected {packet_size} bytes of truncated hex")
                            self.logger.debug(f"   Total hex buffer: {len(self.board_hex_buffer)} bytes")
                            
                            # Check if we have enough for a full board (8192 characters = 4096 tiles)
                            if len(self.board_hex_buffer) >= 8192:
                                self.logger.debug(f"Found enough truncated hex data! Converting to binary...")
                                
                                # Take exactly 8192 characters and convert from truncated hex
                                truncated_hex = self.board_hex_buffer[:8192].decode('ascii', errors='ignore')
                                board_data = self._decode_truncated_hex(truncated_hex)
                                
                                # Apply board data to level
                                if self.level_manager.current_level:
                                    self.level_manager.current_level.set_board_data(board_data)
                                    self.level_manager.current_level.width = 64
                                    self.level_manager.current_level.height = 64
                                    self.logger.debug(f"Applied {len(board_data)} bytes to level!")
                                    
                                    # Save for debugging
                                    with open("board_stream_extracted.bin", "wb") as f:
                                        f.write(board_data)
                                    self.logger.debug(f"Saved extracted board data")
                                    
                                    # Test first few tiles
                                    import struct
                                    self.logger.debug(f"First few tiles from stream:")
                                    for i in range(min(5, len(board_data)//2)):
                                        tile_id = struct.unpack('<H', board_data[i*2:i*2+2])[0]
                                        self.logger.debug(f"   Tile {i}: ID {tile_id}")
                                
                                # Clear board stream state
                                self.board_stream_active = False
                                self.board_hex_buffer = b''
                                self.logger.debug(f"Board stream complete!")
                                return
                        
                        # Move to next packet
                        pos += 4 + packet_size
                    else:
                        break
                
                return  # Don't process as normal packets when in board stream mode
            
            # Process the decrypted data normally
            pos = 0
            
            # Debug: Check if this looks like it contains board data
            if len(decrypted) > 1000:
                self.logger.debug(f"Large decrypted chunk: {len(decrypted)} bytes")
                # Check for PLO_BOARDPACKET (101 + 32 = 133 = 0x85)
                board_marker = bytes([133])  # PLO_BOARDPACKET encoded
                if board_marker in decrypted:
                    board_pos = decrypted.find(board_marker)
                    self.logger.debug(f"Found PLO_BOARDPACKET marker at position {board_pos}!")
                    
                    # Debug: Show what's around the marker
                    start = max(0, board_pos - 10)
                    end = min(len(decrypted), board_pos + 20)
                    snippet = decrypted[start:end]
                    self.logger.debug(f"   Context: {snippet.hex()}")
                    self.logger.debug(f"   As text: {repr(snippet)}")
                    
                    # Check if there's a newline before it (packet boundary)
                    prev_newline = decrypted.rfind(b'\n', 0, board_pos)
                    next_newline = decrypted.find(b'\n', board_pos)
                    self.logger.debug(f"   Previous newline at: {prev_newline}")
                    self.logger.debug(f"   Next newline at: {next_newline}")
                    
                    if next_newline > board_pos:
                        packet_size = next_newline - board_pos
                        self.logger.debug(f"   Packet size would be: {packet_size} bytes")
                    
            packets_processed = 0
            had_raw_data = False  # Track if we processed raw data
            original_size = len(decrypted)  # Remember original size for debugging
            
            while pos < len(decrypted):
                # Check if raw data handler is active
                if self._raw_data_handler.active:
                    # Feed all remaining data to raw handler
                    remaining = decrypted[pos:]
                    self.logger.debug(f"Feeding {len(remaining)} bytes to raw data handler")
                    leftover = self._raw_data_handler.process_data(remaining)
                    had_raw_data = True
                    
                    if leftover is not None:
                        if len(leftover) > 0:
                            # Raw handler returned leftover data to process normally
                            self.logger.debug(f"Raw handler returned {len(leftover)} bytes of leftover data")
                            # Check for GMAP data in leftover
                            if b'zlttp' in leftover[:100]:
                                self.logger.info(f"[GMAP DEBUG] Found 'zlttp' in leftover data!")
                                self.logger.info(f"[GMAP DEBUG] First 100 bytes: {leftover[:100]}")
                            decrypted = leftover
                            pos = 0
                            continue
                        else:
                            # Raw handler consumed exactly its expected data
                            # Update position and continue if there's more data
                            consumed = self._raw_data_handler.consumed_size
                            self.logger.debug(f"Raw handler consumed exactly {consumed} bytes")
                            pos += consumed
                            if pos >= len(decrypted):
                                break
                            # Continue processing remaining data
                            continue
                    else:
                        # Still collecting data
                        self.logger.debug("Raw handler still collecting data")
                        break
                
                # Find the next newline (packet terminator)
                next_newline = decrypted.find(b'\n', pos)
                
                if next_newline == -1:
                    # No more complete packets
                    break
                    
                # Extract one packet (not including the newline)
                packet = decrypted[pos:next_newline]
                
                # Debug position tracking
                if len(decrypted) > 1000:  # For large chunks
                    self.logger.debug(f"   Packet #{packets_processed}: pos={pos}, next_newline={next_newline}, packet_len={len(packet)}")
                    if packet:
                        self.logger.debug(f"     First byte: {packet[0]} (ID: {packet[0] - 32})")
                    
                    # Show what's coming next
                    if pos < len(decrypted):
                        next_10 = decrypted[pos:pos+10]
                        self.logger.debug(f"     Next in stream: {next_10.hex()}")
                
                pos = next_newline + 1
                packets_processed += 1
                
                if packet and len(packet) >= 1:
                    # Check if we're expecting text board data
                    if self.expecting_text_board_data:
                        # Try to decode as text
                        try:
                            text = packet.decode('latin-1')
                            if text.startswith("BOARD "):
                                # This is BOARD text data!
                                text_result = self._text_handler.check_for_text_data(packet)
                                if text_result:
                                    self._handle_text_data_result(text_result)
                                    continue
                            else:
                                # Not BOARD data, stop expecting it
                                self.expecting_text_board_data = False
                                self.logger.debug(f"End of BOARD text data (got: {text[:20]}...)")
                        except:
                            # Failed to decode as text, stop expecting board data
                            self.expecting_text_board_data = False
                    
                    # First byte is Reborn-encoded packet ID
                    packet_id = packet[0] - 32
                    packet_data = packet[1:]
                    
                    # Update session packet count
                    self.session.increment_packet_count()
                    
                    # Special handling for PLO_BOARDPACKET (101)
                    if packet_id == 101:  # PLO_BOARDPACKET
                        self.logger.debug(f"PLO_BOARDPACKET detected!")
                        
                        # When preceded by PLO_RAWDATA with size 8194, the board data comes in packet_data
                        # The 8194 bytes include: PLO_BOARDPACKET header (1 byte) + board data (8192 bytes) + newline (1 byte)
                        if hasattr(self, 'expected_next_packet_size') and self.expected_next_packet_size == 8194:
                            self.logger.debug(f"   This is part of a PLO_RAWDATA stream with board data")
                            # The packet_data contains the board tiles (8192 bytes total expected)
                            if len(packet_data) >= 8192:
                                board_data = packet_data[:8192]
                                self.logger.debug(f"Got complete board data: {len(board_data)} bytes")
                                
                                # Use level manager to apply board data
                                self.level_manager.handle_board_packet(board_data)
                                
                                # Show first few tiles for debugging
                                import struct
                                first_tiles = []
                                for i in range(min(10, len(board_data)//2)):
                                    tile_id = struct.unpack('<H', board_data[i*2:i*2+2])[0]
                                    first_tiles.append(tile_id)
                                self.logger.debug(f"   First 10 tile IDs: {first_tiles}")
                                
                                self.board_data_received = True
                                self.expected_next_packet_size = 0  # Reset
                            else:
                                # Start collecting board data
                                self.logger.debug(f"   Starting board collection: {len(packet_data)} bytes")
                                self.partial_board_data = packet_data
                                self.expecting_board_continuation = True
                        else:
                            # Check if this PLO_BOARDPACKET has board data directly in packet_data
                            if len(packet_data) >= 8192:
                                # Direct board data without PLO_RAWDATA
                                board_data = packet_data[:8192]
                                self.logger.debug(f"   Direct PLO_BOARDPACKET with {len(board_data)} bytes of board data")
                                
                                # Use level manager to apply board data
                                self.level_manager.handle_board_packet(board_data)
                                
                                # Show first few tiles for debugging
                                import struct
                                first_tiles = []
                                for i in range(min(10, len(board_data)//2)):
                                    tile_id = struct.unpack('<H', board_data[i*2:i*2+2])[0]
                                    first_tiles.append(tile_id)
                                self.logger.debug(f"   First 10 tile IDs: {first_tiles}")
                                
                                self.board_data_received = True
                            else:
                                # Regular PLO_BOARDPACKET - board data might follow in the stream
                                self.logger.debug(f"   Regular PLO_BOARDPACKET with {len(packet_data)} bytes")
                                # Start collecting board data
                                self.partial_board_data = packet_data
                                self.expecting_board_continuation = True
                        
                        # Continue processing remaining packets
                        continue
                    
                    # Handle board data continuation
                    elif hasattr(self, 'expecting_board_continuation') and self.expecting_board_continuation:
                        # This is continuation data - we need to include the full packet
                        # including the packet ID since it's part of the board data
                        full_packet = bytes([packet[0]]) + packet_data
                        self.logger.debug(f"Board continuation: adding {len(full_packet)} bytes (packet ID {packet_id})")
                        self.partial_board_data += full_packet
                        
                        # Check if we have enough now
                        if len(self.partial_board_data) >= 8192:
                            board_data = self.partial_board_data[:8192]
                            self.logger.debug(f"Collected full board data: {len(board_data)} bytes")
                            
                            # Use level manager to apply board data
                            self.level_manager.handle_board_packet(board_data)
                            
                            # Show first few tiles for debugging
                            import struct
                            first_tiles = []
                            for i in range(min(10, len(board_data)//2)):
                                tile_id = struct.unpack('<H', board_data[i*2:i*2+2])[0]
                                first_tiles.append(tile_id)
                            self.logger.debug(f"First 10 tile IDs: {first_tiles}")
                            
                            self.board_data_received = True
                            self.expecting_board_continuation = False
                            self.partial_board_data = b''
                            self.expected_next_packet_size = 0
                        else:
                            self.logger.debug(f"   Total collected: {len(self.partial_board_data)} bytes")
                        
                        # Skip normal handler for continuation packets
                        continue
                    
                    result = self.packet_handler.handle_packet(packet_id, packet_data)
                    if result:
                        self._handle_packet_result(packet_id, result)
                    self.events.emit(EventType.RAW_PACKET_RECEIVED, packet_id=packet_id, packet_data=packet_data)
            
            # Debug: Did we process all the data?
            if original_size > 1000:
                self.logger.debug(f"Large chunk processing: original={original_size}, current={len(decrypted)}, pos={pos}, had_raw_data={had_raw_data}")
                if pos < len(decrypted):
                    # We have unprocessed data
                    if had_raw_data and len(decrypted) == pos:
                        # This is expected - we reset the buffer after raw data
                        self.logger.debug("All data processed after raw data handling")
                    else:
                        self.logger.warning(f"{len(decrypted) - pos} bytes remaining unprocessed! (had_raw_data={had_raw_data})")
                        # Show what's left
                        remaining = decrypted[pos:pos+50]
                        self.logger.debug(f"   Remaining data starts with: {remaining.hex()}")
                        self.logger.debug(f"   Remaining data as text: {repr(remaining)}")
                        
                        # Check if it starts with PLO_RAWDATA (100 + 32 = 132 = 0x84)
                        if len(remaining) > 0 and remaining[0] == 132:
                            self.logger.debug("   Remaining data starts with PLO_RAWDATA packet!")
                        
                        # Check if it's all nulls or padding
                        if all(b == 0 for b in decrypted[pos:]):
                            self.logger.debug("   (All remaining bytes are null - likely padding)")
                        else:
                            # Show the first non-null byte
                            for i, b in enumerate(decrypted[pos:]):
                                if b != 0:
                                    self.logger.debug(f"   First non-null byte at offset {i}: 0x{b:02x} (char: '{chr(b)}' if 32 <= b < 127 else '?')")
                                    break
        except Exception as e:
            self.logger.error(f"Error processing packet: {e}", exc_info=True)
            import traceback
            traceback.print_exc()
    
    def recv_encrypted_packet_data(self, packet: bytes):
        """Decrypt packet data"""
        if not packet or len(packet) == 0:
            return None
            
        # Use version-specific codec if available
        if self.version_codec:
            return self.version_codec.recv_packet(packet)
        
        # Fallback to ENCRYPT_GEN_5 behavior
        compression_type = packet[0]
        encrypted_data = packet[1:]
        
        # Debug unknown compression types
        if compression_type not in [CompressionType.UNCOMPRESSED, CompressionType.ZLIB, CompressionType.BZ2]:
            self.logger.warning(f"Unknown compression type: {compression_type}")
            return None
        
        # Create a new codec for this packet with the appropriate limit
        packet_codec = RebornEncryption(self.encryption_key)
        packet_codec.iterator = self.in_codec.iterator  # Copy current iterator state
        packet_codec.limit_from_type(compression_type)
            
        # Decrypt the data
        decrypted = packet_codec.decrypt(encrypted_data)
        
        # Update our main codec's iterator to maintain state
        self.in_codec.iterator = packet_codec.iterator
        
        # Decompress based on type
        try:
            if compression_type == CompressionType.ZLIB:
                return zlib.decompress(decrypted)
            elif compression_type == CompressionType.BZ2:
                return bz2.decompress(decrypted)
            elif compression_type == CompressionType.UNCOMPRESSED:
                return decrypted
            else:
                # Unknown compression type
                self.logger.warning(f"Unknown compression type: {compression_type}")
                return None
        except Exception as e:
            # Silently ignore decompression errors for now
            return None
    
    def _handle_text_data_result(self, result: Dict[str, Any]):
        """Handle text data result
        
        Args:
            result: Parsed text data result
        """
        data_type = result.get("type")
        
        if data_type == "board_data_text":
            # Board data is already handled by the event emission in TextDataHandler
            # The board collector will pick it up from the event
            pass  # BoardCollector now subscribes to the event directly
        
    def _handle_packet_result(self, packet_id: int, result: Dict[str, Any]):
        """Handle parsed packet result"""
        packet_type = result.get("type")
        
        if packet_type == "player_props":
            # Player props can be for local or other players
            player_id = result.get("player_id", 0)
            props = result.get("props", {})
            
            # Check if this is the initial login packet for local player
            from ..protocol.enums import PlayerProp
            is_initial_login = (self.local_player.id == -1 and 
                              PlayerProp.PLPROP_ID in props and 
                              len(props) > 10)  # Initial login has many properties
            
            # Debug logging
            if len(props) > 5:  # Only log substantial property packets
                self.logger.info(f"Player props: player_id={player_id}, local_id={self.local_player.id}, props_count={len(props)}, has_ID={PlayerProp.PLPROP_ID in props}, is_initial={is_initial_login}")
            
            # Check if this packet contains the local player's ID and we haven't set it yet
            if self.local_player.id == -1 and PlayerProp.PLPROP_ID in props and len(props) > 15:
                # This must be the initial login properties for local player
                self.local_player.id = props[PlayerProp.PLPROP_ID]
                self.logger.info(f"Set local player ID to {self.local_player.id} from initial login")
            
            # Check if this is for the local player
            # Handle multiple scenarios: player_id 0 (common server assignment), 
            # matching our known ID, or if we haven't set our ID yet and this looks like local player props
            is_local_player = (
                player_id == 0 or 
                player_id == self.local_player.id or
                (self.local_player.id == -1 and len(props) > 5 and player_id not in self.players)
            )
            
            if is_local_player:
                # This is for the local player
                
                # Sync local player ID if it doesn't match
                if self.local_player.id != player_id:
                    old_id = self.local_player.id
                    self.local_player.id = player_id
                    self.logger.info(f"Synced local player ID from {old_id} to {player_id} via PLO_PLAYERPROPS")
                
                self.local_player.update_from_props(props)
                self.session.set_local_player(self.local_player)
                self.events.emit(EventType.PLAYER_PROPS_UPDATE, player=self.local_player)
            else:  # Other player
                if player_id not in self.players:
                    self.players[player_id] = Player(player_id)
                self.players[player_id].update_from_props(props)
                self.session.update_player(self.players[player_id])
                self.events.emit(EventType.OTHER_PLAYER_UPDATE, player=self.players[player_id])
            
        elif packet_type == "other_player_props":
            # Update other player
            player_id = result["player_id"]
            is_new_player = player_id not in self.players
            
            if is_new_player:
                self.players[player_id] = Player(player_id)
            
            self.players[player_id].update_from_props(result["props"])
            self.session.update_player(self.players[player_id])
            
            # Emit appropriate event
            if is_new_player:
                self.events.emit(EventType.PLAYER_ADDED, player=self.players[player_id])
            else:
                self.events.emit(EventType.OTHER_PLAYER_UPDATE, player=self.players[player_id])
            
        elif packet_type == "add_player":
            # Add new player
            player_id = result["player_id"]
            props = result.get("props", {})
            
            # Check if this is actually the local player being added
            # This happens when server assigns us player ID 0 but we still have -1
            if self.local_player.id == -1 and len(props) > 5:
                # This could be the local player - update our ID
                self.local_player.id = player_id
                self.local_player.update_from_props(props)
                self.session.set_local_player(self.local_player)
                self.logger.info(f"Updated local player ID from -1 to {player_id} via PLO_ADDPLAYER")
                self.events.emit(EventType.PLAYER_PROPS_UPDATE, player=self.local_player)
            else:
                # This is another player
                if player_id not in self.players:
                    self.players[player_id] = Player(player_id)
                self.players[player_id].update_from_props(props)
                self.session.update_player(self.players[player_id])
                self.events.emit(EventType.PLAYER_ADDED, player=self.players[player_id])
            
        elif packet_type == "del_player":
            # Remove player
            player_id = result["player_id"]
            if player_id in self.players:
                player = self.players.pop(player_id)
                self.session.remove_player(player_id)
                self.events.emit(EventType.PLAYER_REMOVED, player=player)
                
        elif packet_type == "level_name":
            # Entered new level
            level_name = result["name"]
            self.logger.info(f"[LEVEL_NAME] Current level: {level_name}")
            
            # Clear transition flag when we receive confirmation of level change
            if hasattr(self, 'actions') and hasattr(self.actions, '_transition_this_frame'):
                self.actions._transition_this_frame = False
                self.logger.debug("[LEVEL_NAME] Cleared transition flag")
            
            # Check for transition timeout
            if hasattr(self, 'level_manager'):
                self.level_manager.check_transition_timeout()
            
            # Check if this is a GMAP file - don't create Level objects for GMAPs
            if level_name.endswith('.gmap'):
                # This is a GMAP, not an actual level
                self.logger.info(f"Entering GMAP: {level_name}")
                gmap_base_name = level_name[:-5]  # Remove .gmap extension
                self.gmap_manager.enter_gmap(gmap_base_name)
                
                # Request GMAP file if we don't have it
                if gmap_base_name not in self.gmap_manager.gmaps:
                    self.level_manager.request_file(level_name)
            else:
                # Regular level handling
                if level_name not in self.levels:
                    self.levels[level_name] = Level(level_name)
                
                old_level = self.current_level
                self.current_level = self.levels[level_name]
                
                if old_level:
                    self.events.emit(EventType.LEVEL_LEFT, level=old_level)
                self.session.current_level = self.current_level
                self.events.emit(EventType.LEVEL_ENTERED, level=self.current_level)
                
                # Update level manager
                self.level_manager.handle_level_name(level_name)
                
                # Check if this level is part of a GMAP
                if self.gmap_manager.is_active:
                    # Update segment coordinates based on level name
                    segment_coords = self.gmap_manager.update_segment_from_level(level_name)
                    if segment_coords:
                        self.logger.info(f"Updated GMAP segment to {segment_coords}")
                    else:
                        # Level not in GMAP - exit GMAP mode
                        self.logger.info(f"Level {level_name} not in GMAP, exiting GMAP mode")
                        self.gmap_manager.exit_gmap()
            
            # Apply any pending board data (but only to non-gmap levels and correct target)
            if (hasattr(self, 'pending_board_data') and self.pending_board_data and 
                not level_name.endswith('.gmap') and 
                (self.board_data_level_name == level_name or self.board_data_level_name is None)):
                
                self.logger.debug(f"Applying pending board data to level: {level_name}")
                self.current_level.set_board_data(self.pending_board_data)
                self.board_data_received = True
                # Show first few tiles for verification
                import struct
                first_tiles = []
                for i in range(min(10, len(self.pending_board_data)//2)):
                    tile_id = struct.unpack('<H', self.pending_board_data[i*2:i*2+2])[0]
                    first_tiles.append(tile_id)
                self.logger.debug(f"   Applied board data: {len(self.pending_board_data)} bytes, first tiles: {first_tiles}")
                self.pending_board_data = None  # Clear it
                self.board_data_level_name = None
                
            elif level_name.endswith('.gmap'):
                self.logger.debug(f"Entered gmap: {level_name} (world map - no board data needed)")
                
            elif hasattr(self, 'pending_board_data') and self.pending_board_data:
                self.logger.debug(f"Entered level: {level_name} (board data is for: {self.board_data_level_name})")
            
            # Mark that we've loaded a level
            self.level_loaded = True
            
        elif packet_type == "toall":
            # Chat message
            player_id = result["player_id"]
            message = result["message"]
            
            # If we don't know this player, create a placeholder
            if player_id not in self.players:
                self.players[player_id] = Player(player_id)
                self.session.update_player(self.players[player_id])
                self.logger.debug(f"Added unknown player from chat: ID:{player_id}")
            
            # Add to session
            self.session.add_chat_message(player_id, message)
            
            self.events.emit(EventType.CHAT_MESSAGE, 
                           player_id=player_id, 
                           message=message)
            
        elif packet_type == "private_message":
            # Private message
            from_player_id = result["player_id"]
            message = result["message"]
            
            # Assume it's to us (local player)
            to_player_id = getattr(self.local_player, 'id', -1)
            
            # Add to session
            self.session.add_private_message(from_player_id, to_player_id, message)
            
            self.events.emit(EventType.PRIVATE_MESSAGE,
                           player_id=from_player_id,
                           message=message)
            
        elif packet_type == "rawdata":
            # PLO_RAWDATA - specifies size of next packet
            self.expected_next_packet_size = result["expected_size"]
            # print(f"📏 Expecting next packet to be {self.expected_next_packet_size} bytes")
            
            # Start raw data mode
            current_level = self.level_manager.current_level.name if self.level_manager.current_level else None
            self._raw_data_handler.start_raw_data(self.expected_next_packet_size, 
                                                {'level': current_level})
            
        elif packet_type == "server_text":
            # Server message
            self.events.emit(EventType.SERVER_MESSAGE, text=result["text"])
            
        elif packet_type == "signature":
            # Server signature - indicates login accepted
            self.login_success = True
            self.events.emit(EventType.LOGIN_SUCCESS)
            self.logger.info(f"Login accepted! Signature: {result.get('signature', 'unknown')}")
            
            # Send initial properties after successful login
            if hasattr(self, '_actions'):
                self._actions.send_initial_properties()
            
        elif packet_type == "player_warp":
            # Player warp - indicates we're in a level and ready to play
            self.level_loaded = True
            warp_level = result.get('level', 'unknown')
            warp_x = result.get('x', 0)
            warp_y = result.get('y', 0)
            self.logger.debug(f"Warped to level: {warp_level} at ({warp_x}, {warp_y})")
            
            # Update our position
            self.local_player.x = warp_x
            self.local_player.y = warp_y
            
            # Create level if it doesn't exist
            if warp_level not in self.levels:
                self.levels[warp_level] = Level(warp_level)
            self.current_level = self.levels[warp_level]
            self.session.current_level = self.current_level
            
            # Update level manager
            self.level_manager.handle_player_warp(warp_x, warp_y, warp_level)
            
            self.events.emit(EventType.PLAYER_WARP, level=warp_level, x=warp_x, y=warp_y)
            
        elif packet_type == "flag_set":
            # Flag set
            self.flags[result["flag"]] = result["value"]
            self.events.emit(EventType.FLAG_SET, flag=result["flag"], value=result["value"])
            
        elif packet_type == "flag_del":
            # Flag deleted
            if result["flag"] in self.flags:
                del self.flags[result["flag"]]
            self.events.emit(EventType.FLAG_DELETED, flag=result["flag"])
            
        elif packet_type == "file":
            # File received
            filename = result["filename"]
            data = result["data"]
            
            # Check if this is a GMAP chunk file (header only)
            if filename.endswith('.nw') and len(data) == 9 and data.startswith(b'GLEVNW01'):
                self.logger.debug(f"GMAP chunk file received: {filename} - expecting BOARD text data")
                self.expecting_text_board_data = True
                
                # Set the target level for the board collector
                level_name = filename[:-3] if filename.endswith('.nw') else filename
                if hasattr(self, '_board_collector'):
                    self._board_collector.set_target_level(level_name)
            
            # Handle GMAP files in both managers
            if filename.endswith('.gmap'):
                self.gmap_manager.handle_gmap_file(filename, data)
                # Also let level manager handle GMAP files for pending adjacent requests
                self.level_manager.handle_file_data(filename, data)
            else:
                # Handle through level manager
                self.level_manager.handle_file_data(filename, data)
            
            self.events.emit(EventType.FILE_RECEIVED, 
                           filename=filename, 
                           data=data)
        
        elif packet_type == "level_board":
            # Level board data (tile data)
            self.level_manager.handle_level_board(result["data"])
        
        elif packet_type == "board_packet":
            # Board packet in streaming protocol
            # print(f"🎯 CLIENT: Received board packet!")
            board_data = result.get("board_data", b'')
            is_complete = result.get("is_complete", False)
            self.logger.debug(f"   Board data size: {len(board_data)} bytes")
            # print(f"   Expected size: {self.expected_next_packet_size} bytes")
            self.logger.debug(f"   Is complete: {is_complete}")
            self.logger.debug(f"   Current level: {self.level_manager.current_level.name if self.level_manager.current_level else 'None'}")
            
            if len(board_data) > 0:
                if is_complete and len(board_data) == 8192:
                    # Complete board data - apply immediately
                    # print(f"📦 Complete board packet with {len(board_data)} bytes")
                    if self.level_manager.current_level:
                        self.level_manager.current_level.set_board_data(board_data)
                        self.logger.debug(f"Applied board data to current level!")
                    else:
                        self.logger.warning(f"No current level to apply board data to")
                    
                    # Reset expected size
                    self.expected_next_packet_size = 0
                else:
                    # Partial board data - check if we should expect more
                    # print(f"📦 Partial board packet with {len(board_data)} bytes")
                    
                    # If we know the expected size, start multi-packet assembly
                    if self.expected_next_packet_size > len(board_data):
                        # print(f"🔄 Starting multi-packet board assembly (need {self.expected_next_packet_size} bytes)")
                        self.partial_board_data = board_data
                        self.expecting_board_continuation = True
                    else:
                        self.logger.warning(f"Unexpected board data size mismatch")
                        # Try to apply what we have
                        if self.level_manager.current_level and len(board_data) >= 8192:
                            self.level_manager.current_level.set_board_data(board_data[:8192])
                            self.logger.debug(f"Applied truncated board data to current level!")
                    if not hasattr(self, 'board_hex_buffer'):
                        self.board_hex_buffer = b''
            elif len(board_data) == 0:
                # 0-byte board packet - might be end signal
                # print(f"🔄 0-byte board packet received")
                if hasattr(self, 'board_stream_active') and self.board_stream_active:
                    self.logger.debug(f"   Stream already active, continuing...")
                else:
                    self.logger.debug(f"   Starting board stream...")
                    self.board_stream_active = True
                if not hasattr(self, 'board_chunks'):
                    self.board_chunks = []
        
            
        elif packet_type == "board_modify":
            # Tile modification
            self.level_manager.handle_board_modify(
                result["x"], result["y"], 
                result["width"], result["height"], 
                result["tiles"]
            )
            
        elif packet_type == "level_sign":
            # Level sign
            self.level_manager.handle_level_sign(
                result["x"], result["y"], result["text"]
            )
            
        elif packet_type == "level_chest":
            # Level chest
            self.level_manager.handle_level_chest(
                result["x"], result["y"], 
                result["item"], result["sign_text"]
            )
            
        elif packet_type == "level_link":
            # Level link - pass the parsed result dict
            self.level_manager.handle_level_link(result)
        
        elif packet_type == "trigger_action":
            # Trigger action from server
            action = result.get("action", "")
            params = result.get("params", [])
            
            # Special handling for known actions
            if action == "gr.setgroup" and params:
                self.local_player.group = params[0]
                self.events.emit(EventType.GROUP_CHANGED, group=params[0])
            elif action == "gr.setlevelgroup" and params:
                self.local_player.group = params[0]
                self.events.emit(EventType.LEVELGROUP_CHANGED, group=params[0])
            
            # Always emit the raw event
            self.events.emit(EventType.TRIGGER_ACTION, 
                           action=action, 
                           params=params,
                           raw=result.get("raw", ""))
        
        elif packet_type == "board_data":
            # This is actually PLO_NPCWEAPONDEL (ID 34), not board data
            # Board data comes via PLO_BOARDPACKET (ID 101)
            pass
        
        elif packet_type == "ghost_text":
            # Ghost mode text
            self.events.emit(EventType.GHOST_TEXT, text=result.get("text", ""))
        
        elif packet_type == "ghost_icon":
            # Ghost mode icon
            self.events.emit(EventType.GHOST_ICON, enabled=result.get("enabled", False))
        
        elif packet_type == "minimap":
            # Minimap data
            self.events.emit(EventType.MINIMAP_UPDATE, 
                           text_file=result.get("text_file", ""),
                           image_file=result.get("image_file", ""),
                           x=result.get("x", 0),
                           y=result.get("y", 0))
        
        elif packet_type == "server_warp":
            # Server-initiated warp to another server
            self.events.emit(EventType.SERVER_WARP, data=result.get("data", b''))
        
        elif packet_type == "fullstop":
            # Client freeze
            self.events.emit(EventType.CLIENT_FREEZE, freeze_type="fullstop")
        
        elif packet_type == "fullstop2":
            # Client freeze type 2
            self.events.emit(EventType.CLIENT_FREEZE, freeze_type="fullstop2")
        
        elif packet_type == "newworld_time":
            # Server world time update
            time_value = result.get("time", 0)
            self.logger.info(f"[NEWWORLDTIME] Received world time update: {time_value}")
            self._last_world_time = time.time()  # Track when we last got world time
            self.events.emit(EventType.WORLD_TIME_UPDATE, time=time_value)
        
        elif packet_type == "unknown_49":
            # This is a GMAP name packet!
            raw_gmap_name = result.get('data', '')
            if raw_gmap_name.endswith('.gmap'):
                # Clean corrupted GMAP name - extract just the .gmap filename
                # Server sometimes sends corrupted data like "$1ÿ%(zlttp.gmap"
                clean_gmap_name = self._clean_gmap_name(raw_gmap_name)
                self.logger.debug(f"Detected GMAP: {raw_gmap_name} -> cleaned: {clean_gmap_name}")
                self.level_manager.handle_level_name(clean_gmap_name)
        
        elif packet_type == "disconnect_message":
            # Server is disconnecting us with a message
            message = result.get('message', 'Unknown reason')
            self.logger.error(f"[SERVER DISCONNECT] Server disconnected us: {message}")
            self.running = False
            self.connected = False
            self.events.emit(EventType.DISCONNECTED, reason=f"Server: {message}")
        
        # board_data_text is now handled by TextDataHandler, not through packet system
    
    def _clean_gmap_name(self, raw_name: str) -> str:
        """Clean corrupted GMAP name from server packet 49
        
        Server sometimes sends corrupted data like "$1ÿ%(zlttp.gmap"
        Extract just the clean .gmap filename.
        """
        if not raw_name.endswith('.gmap'):
            return raw_name
            
        # Find the start of the actual filename (look for letters followed by .gmap)
        import re
        match = re.search(r'([a-zA-Z0-9_-]+\.gmap)$', raw_name)
        if match:
            clean_name = match.group(1)
            if clean_name != raw_name:
                self.logger.warning(f"[PACKET_CORRUPTION] Cleaned corrupted GMAP name: '{raw_name}' -> '{clean_name}'")
            return clean_name
        
        # Fallback: return as-is if no pattern found
        return raw_name
    
    # Extended packet handler registration
    def _register_extended_handlers(self):
        """Register handlers for new packet types"""
        # Import from the new packet type modules
        try:
            from ..protocol.packet_types.items import (
                ServerItemAddPacket, ServerItemDeletePacket, ServerThrowCarriedPacket
            )
            from ..protocol.packet_types.combat import (
                ServerHurtPlayerPacket, ServerExplosionPacket, ServerHitObjectsPacket,
                ServerPushAwayPacket
            )
            from ..protocol.packet_types.npcs import (
                ServerNPCPropsPacket, ServerNPCDeletePacket,
                ServerNPCDelete2Packet, ServerNPCActionPacket, ServerNPCMovedPacket,
                ServerTriggerActionPacket
            )
        except ImportError:
            # Fall back to trying to import from packets module
            from ..protocol.packets import (
                ServerItemAddPacket, ServerItemDeletePacket, ServerThrowCarriedPacket,
                ServerHurtPlayerPacket, ServerExplosionPacket, ServerHitObjectsPacket,
                ServerPushAwayPacket, ServerNPCPropsPacket, ServerNPCDeletePacket,
                ServerNPCDelete2Packet, ServerNPCActionPacket, ServerNPCMovedPacket,
                ServerTriggerActionPacket
            )
        
        # Item handlers
        self.packet_handler.handlers[ServerToPlayer.PLO_ITEMADD] = self._handle_item_add
        self.packet_handler.handlers[ServerToPlayer.PLO_ITEMDEL] = self._handle_item_delete
        self.packet_handler.handlers[ServerToPlayer.PLO_THROWCARRIED] = self._handle_throw_carried
        
        # Combat handlers
        self.packet_handler.handlers[ServerToPlayer.PLO_HURTPLAYER] = self._handle_hurt_player
        self.packet_handler.handlers[ServerToPlayer.PLO_EXPLOSION] = self._handle_explosion
        self.packet_handler.handlers[ServerToPlayer.PLO_HITOBJECTS] = self._handle_hit_objects
        self.packet_handler.handlers[ServerToPlayer.PLO_PUSHAWAY] = self._handle_push_away
        
        # NPC handlers
        self.packet_handler.handlers[ServerToPlayer.PLO_NPCPROPS] = self._handle_npc_props
        self.packet_handler.handlers[ServerToPlayer.PLO_NPCDEL] = self._handle_npc_delete
        self.packet_handler.handlers[ServerToPlayer.PLO_NPCDEL2] = self._handle_npc_delete2
        self.packet_handler.handlers[ServerToPlayer.PLO_NPCACTION] = self._handle_npc_action
        self.packet_handler.handlers[ServerToPlayer.PLO_NPCMOVED] = self._handle_npc_moved
        self.packet_handler.handlers[ServerToPlayer.PLO_TRIGGERACTION] = self._handle_trigger_action
        
        # Level handler
        self.packet_handler.handlers[ServerToPlayer.PLO_SETACTIVELEVEL] = self._handle_set_active_level
        
    # Item packet handlers
    def _handle_item_add(self, packet: 'ServerItemAddPacket'):
        """Handle item spawn"""
        level = self.local_player.level
        try:
            item_type = LevelItemType(packet.item_type)
        except ValueError:
            item_type = LevelItemType.GREENRUPEE
            
        self.item_manager.add_item(level, packet.x, packet.y, item_type, packet.item_id)
        
        self.events.emit(EventType.ITEM_SPAWNED, item={
            'x': packet.x,
            'y': packet.y,
            'type': item_type,
            'id': packet.item_id,
            'level': level
        })
        
    def _handle_item_delete(self, packet: 'ServerItemDeletePacket'):
        """Handle item removal"""
        level = self.local_player.level
        item = self.item_manager.remove_item(level, packet.x, packet.y)
        
        if item:
            self.events.emit(EventType.ITEM_REMOVED, item=item)
            
    def _handle_throw_carried(self, reader: 'PacketReader'):
        """Handle thrown object"""
        # TODO: Parse the actual packet format
        # For now, just return a basic result to avoid errors
        return {"type": "throw_carried"}
                           
    # Combat packet handlers
    def _handle_hurt_player(self, reader: 'PacketReader'):
        """Handle player damage"""
        # Parse hurt player packet
        # Format: target_id, attacker_id, damage/health
        try:
            # Read the packet data - format may vary by server version
            # For now, just skip the data to avoid errors
            remaining = reader.remaining()
            if remaining > 0:
                reader.read_remaining()  # Skip the rest
                
            # Return a basic result
            return {"type": "hurt_player"}
        except Exception as e:
            self.logger.debug(f"Error parsing hurt player packet: {e}")
            return {"type": "hurt_player"}
                       
    def _handle_explosion(self, reader: 'PacketReader'):
        """Handle explosion"""
        # TODO: Parse explosion packet format
        return {"type": "explosion"}
                       
    def _handle_hit_objects(self, reader: 'PacketReader'):
        """Handle hit confirmation"""
        # TODO: Parse hit objects packet format
        return {"type": "hit_objects"}
                       
    def _handle_push_away(self, reader: 'PacketReader'):
        """Handle push effect"""
        # TODO: Parse push away packet format
        return {"type": "push_away"}
            
        self.events.emit(EventType.PLAYER_PUSHED,
                       player_id=packet.player_id,
                       dx=packet.dx,
                       dy=packet.dy,
                       force=packet.force)
                       
    # NPC packet handlers
    def _handle_npc_props(self, reader: 'PacketReader'):
        """Handle NPC properties - this needs custom parsing based on prop IDs"""
        # Read NPC ID (2 bytes)
        if reader.remaining() < 2:
            return
        
        npc_id = reader.read_short()
        
        # Read the rest as raw data
        raw_data = reader.read_remaining()
        
        # For now, just emit the raw data
        self.events.emit(EventType.NPC_UPDATED,
                       npc_id=npc_id,
                       raw_data=raw_data)
                       
    def _handle_npc_delete(self, packet: 'ServerNPCDeletePacket'):
        """Handle NPC deletion"""
        npc = self.npc_manager.remove_npc(packet.npc_id)
        if npc:
            self.events.emit(EventType.NPC_REMOVED, npc=npc)
            
    def _handle_npc_delete2(self, packet: 'ServerNPCDelete2Packet'):
        """Handle NPC deletion v2"""
        npc = self.npc_manager.remove_npc(packet.npc_id)
        if npc:
            self.events.emit(EventType.NPC_REMOVED, npc=npc, level=packet.level)
            
    def _handle_npc_action(self, packet: 'ServerNPCActionPacket'):
        """Handle NPC action"""
        self.events.emit(EventType.NPC_ACTION,
                       npc_id=packet.npc_id,
                       action=packet.action,
                       params=packet.params)
                       
    def _handle_npc_moved(self, packet: 'ServerNPCMovedPacket'):
        """Handle NPC movement/hiding"""
        if packet.hidden:
            npc = self.npc_manager.get_npc(packet.npc_id)
            if npc:
                npc.visible = False
        else:
            self.npc_manager.update_npc_position(packet.npc_id, packet.x, packet.y)
            
        self.events.emit(EventType.NPC_MOVED,
                       npc_id=packet.npc_id,
                       x=packet.x,
                       y=packet.y,
                       hidden=packet.hidden)
                       
    def _handle_trigger_action(self, packet: 'ServerTriggerActionPacket'):
        """Handle trigger action response"""
        self.events.emit(EventType.TRIGGER_RESPONSE,
                       action=packet.action,
                       params=packet.params)
                       
    def _handle_set_active_level(self, reader: 'PacketReader'):
        """Handle set active level packet - sets the active level for incoming packets"""
        # Read the remaining data as the level name
        level_name = reader.read_remaining().decode('latin-1', errors='ignore')
        
        # This sets which level receives updates for items, NPCs, board data, etc.
        # IMPORTANT: This is different from PLO_LEVELNAME which sets the current level
        # PLO_SETACTIVELEVEL tells us which level subsequent packets will modify
        
        if hasattr(self, 'level_manager'):
            # Tell the level manager to set the active level for packet processing
            self.level_manager.set_active_level_for_packets(level_name)
        
        # Check if debug_packets exists (it may not be initialized yet)
        if hasattr(self, 'debug_packets') and self.debug_packets:
            self.logger.debug(f"   Handler result: set_active_level:{level_name}")
        return None  # Don't return a string that will cause errors
                       
    # Extended API methods
    def _on_board_complete(self, **kwargs):
        """Handle complete board data from board collector"""
        level_name = kwargs.get('level')
        width = kwargs.get('width', 64)
        height = kwargs.get('height', 64)
        tiles = kwargs.get('tiles', [])
        
        if hasattr(self, 'level_manager'):
            self.level_manager.handle_board_complete(level_name, width, height, tiles)
            
        # Reset the text board data flag
        self.expecting_text_board_data = False
    
    def _on_file_received_from_raw_handler(self, event):
        """Handle FILE_RECEIVED event from raw_data_handler"""
        self.logger.info(f"[FILE_RECEIVED] Event received: {type(event)}")
        
        # Extract data from event dict
        if isinstance(event, dict):
            filename = event.get('filename', '')
            data = event.get('data', b'')
        else:
            # Event object
            filename = event.get('filename', '') if hasattr(event, 'get') else getattr(event, 'filename', '')
            data = event.get('data', b'') if hasattr(event, 'get') else getattr(event, 'data', b'')
        
        self.logger.info(f"[FILE_RECEIVED] File: {filename}, Size: {len(data) if data else 0} bytes")
        
        # Track file received
        if filename:
            self.file_tracker.on_file_received(filename, len(data) if data else 0)
        
        if filename and data and hasattr(self, 'level_manager'):
            self.logger.info(f"[FILE_RECEIVED] Forwarding to level manager: {filename} ({len(data)} bytes)")
            self.level_manager.handle_file_data(filename, data)
            
            # If this is a GMAP file and we're in GMAP mode, update segment coordinates
            if filename.endswith('.gmap') and hasattr(self, 'gmap_manager') and self.gmap_manager.is_active:
                current_level = getattr(self.local_player, 'level', None)
                if current_level:
                    self.logger.info(f"[GMAP] Attempting to set segment coordinates for level: {current_level}")
                    result = self.gmap_manager.update_segment_from_level(current_level)
                    if result:
                        self.logger.info(f"[GMAP] Successfully set segment coordinates to {result}")
                    else:
                        self.logger.warning(f"[GMAP] Failed to set segment coordinates for level: {current_level}")
        else:
            self.logger.warning(f"[FILE_RECEIVED] Not forwarding: filename={filename}, has_data={bool(data)}, has_lm={hasattr(self, 'level_manager')}")
    
    def pickup_item(self, x: float, y: float) -> bool:
        """Pick up an item at position"""
        return self.items.pickup_item(x, y)
        
    def drop_item(self, item_type: LevelItemType, x: Optional[float] = None, y: Optional[float] = None):
        """Drop an item"""
        self.items.drop_item(item_type, x, y)
        
    def open_chest(self, x: int, y: int) -> bool:
        """Open a chest"""
        return self.items.open_chest(x, y)
        
    def throw_carried(self, power: float = 1.0):
        """Throw carried object"""
        self.items.throw_carried(power)
        
    def hurt_player(self, player_id: int, damage: float = 0.5):
        """Attack another player"""
        self.combat.hurt_player(player_id, damage)
        
    def check_hit(self, x: float, y: float, width: float = 2.0, height: float = 2.0) -> List[int]:
        """Check for hits in an area"""
        return self.combat.check_hit(x, y, width, height)
        
    def create_explosion(self, x: float, y: float, power: float = 1.0, radius: float = 3.0):
        """Create an explosion"""
        self.combat.create_explosion(x, y, power, radius)
        
    def touch_npc(self, npc_id: int) -> bool:
        """Touch an NPC"""
        return self.npcs.touch_npc(npc_id)
        
    def create_npc(self, x: float, y: float, image: str = "", script: str = "") -> int:
        """Create a new NPC"""
        return self.npcs.create_npc(x, y, image, script)
        
    def trigger_action(self, action: str, params: str = ""):
        """Send a trigger action"""
        self.npcs.trigger_action(action, params)
        
        # Many more packet types to handle...
    # GMAP detection and mode management
    @property
    def is_gmap_mode(self) -> bool:
        """Check if we're currently in GMAP mode"""
        return self.gmap_manager.is_active
    
    @property
    def current_gmap_name(self) -> Optional[str]:
        """Get the current GMAP name (without .gmap extension)"""
        return self.gmap_manager.current_gmap
    
    def set_gmap_enabled(self, enabled: bool):
        """Enable or disable GMAP mode behavior
        
        When disabled, the client will treat all levels as individual levels
        even if they are part of a GMAP. Level warps will use traditional
        level links instead of seamless transitions.
        
        Args:
            enabled: True to enable GMAP mode, False to disable
        """
        self._gmap_enabled = enabled
        self.logger.info(f"GMAP mode {'enabled' if enabled else 'disabled'}")
        
        # If disabling GMAP mode while on a GMAP, reset state
        if not enabled and self._is_gmap_mode:
            self._is_gmap_mode = False
            self._current_gmap_name = None
            self.events.emit(EventType.GMAP_MODE_CHANGED, {
                'is_gmap': False,
                'gmap_name': None,
                'level_name': self.level_manager.current_level.name if self.level_manager.current_level else None
            })
    
    def _detect_gmap_mode(self, level_name: str) -> bool:
        """Detect if a level is part of a GMAP
        
        Args:
            level_name: Name of the level to check
            
        Returns:
            True if level is part of a GMAP
        """
        # If GMAP mode is disabled, always return False
        if not self._gmap_enabled:
            return False
            
        was_gmap = self._is_gmap_mode
        old_gmap_name = self._current_gmap_name
        new_mode = False
        
        # Check if it's a .gmap file itself
        if level_name.endswith('.gmap'):
            # Extract base name
            self._current_gmap_name = level_name.replace('.gmap', '')
            new_mode = True
            
        # Check if level is in the gmap_segments set (most reliable)
        elif hasattr(self.level_manager, 'gmap_segments') and level_name in self.level_manager.gmap_segments:
            # Extract GMAP name from level name
            if '-' in level_name:
                self._current_gmap_name = level_name.split('-')[0]
            new_mode = True
            
        # Check if we have GMAP data for this level's base name
        elif hasattr(self.level_manager, 'gmap_data') and '-' in level_name:
            base_name = level_name.split('-')[0]
            if base_name in self.level_manager.gmap_data:
                self._current_gmap_name = base_name
                new_mode = True
        
        # Emit event if GMAP mode changed
        if new_mode != was_gmap or (new_mode and self._current_gmap_name != old_gmap_name):
            self.events.emit(EventType.GMAP_MODE_CHANGED, {
                'is_gmap': new_mode,
                'gmap_name': self._current_gmap_name
            })
            self.logger.info(f"GMAP mode changed: {new_mode}, GMAP: {self._current_gmap_name}")
                    
        return new_mode
    
    def _update_gmap_mode(self, level_name: str):
        """Update GMAP mode based on current level
        
        Args:
            level_name: Name of the current level
        """
        was_gmap = self._is_gmap_mode
        self._is_gmap_mode = self._detect_gmap_mode(level_name)
        
        # Emit event if mode changed
        if was_gmap != self._is_gmap_mode:
            self.logger.info(f"GMAP mode changed: {was_gmap} -> {self._is_gmap_mode} (level: {level_name})")
            self.events.emit(EventType.GMAP_MODE_CHANGED, {
                'is_gmap': self._is_gmap_mode,
                'gmap_name': self._current_gmap_name,
                'level_name': level_name
            })
            
        # Update player GMAP segment coordinates if entering GMAP
        if self._is_gmap_mode and self.local_player:
            import re
            # Use GMAP file as authoritative source - don't guess from level names
            # Let the level manager handle GMAP coordinate determination
            # It will set gmaplevelx/gmaplevely based on the actual GMAP file position
            pass

