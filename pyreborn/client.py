"""
Main Graal client implementation
"""

import socket
import struct
import threading
import time
import zlib
import bz2
import random
from typing import Optional, Dict, Any, List, Callable, Tuple
from queue import Queue, Empty

from .protocol.enums import (
    PlayerToServer, ServerToPlayer, PlayerProp, 
    Direction, LevelItemType, ClientVersion
)
from .protocol.packets import (
    LoginPacket, PlayerPropsPacket, ToAllPacket, BombAddPacket,
    ArrowAddPacket, FireSpyPacket, WeaponAddPacket, ShootPacket,
    Shoot2Packet, WantFilePacket, FlagSetPacket, PrivateMessagePacket,
    PacketBuilder
)
from .encryption import GraalEncryption, CompressionType
from .handlers.packet_handler import PacketHandler
from .models.player import Player
from .models.level import Level
from .events import EventType
from .events_enhanced import EventManager
from .session import SessionManager
from .level_manager import LevelManager
from .actions import PlayerActions


class RebornClient:
    """Main client for connecting to Graal servers"""
    
    def __init__(self, host: str, port: int = 14900):
        self.host = host
        self.port = port
        
        # Network
        self.socket: Optional[socket.socket] = None
        self.connected = False
        self.running = False
        
        # Packet buffers
        self.send_queue = Queue()
        self.receive_buffer = Queue()
        self.send_thread: Optional[threading.Thread] = None
        self.receive_thread: Optional[threading.Thread] = None
        self.packet_send_rate = 0.1  # 100ms between packets
        
        # Encryption (fixed to match working client)
        self.encryption_key = random.randint(0, 255)
        self.in_codec = GraalEncryption()
        self.out_codec = GraalEncryption()
        self.first_encrypted_packet = True
        
        # Protocol
        self.packet_handler = PacketHandler()
        self.client_version = ClientVersion.VERSION_22
        
        # State
        self.local_player = Player()
        self.players: Dict[int, Player] = {}
        self.current_level: Optional[Level] = None
        self.login_success = False
        self.level_loaded = False
        self.levels: Dict[str, Level] = {}
        self.flags: Dict[str, str] = {}
        
        # Events
        self.events = EventManager()
        
        # Session management
        self.session = SessionManager()
        
        # Level management
        self.level_manager = LevelManager(self)
        
        # Actions delegate
        self._actions = PlayerActions(self)
        
        # Threading
        self._recv_thread: Optional[threading.Thread] = None
        self._send_queue: Queue = Queue()
        self._send_thread: Optional[threading.Thread] = None
        
    def connect(self) -> bool:
        """Connect to server"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
            self.connected = True
            self.running = True
            
            # Start threads
            # Start buffer threads
            self.receive_thread = threading.Thread(target=self._receive_loop, name="GraalReceive")
            self.receive_thread.daemon = True
            self.receive_thread.start()
            
            self.send_thread = threading.Thread(target=self._send_loop, name="GraalSend")
            self.send_thread.daemon = True
            self.send_thread.start()
            
            self.events.emit(EventType.CONNECTED)
            return True
            
        except Exception as e:
            print(f"Connection failed: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from server"""
        self.running = False
        
        # Wait for threads to finish
        if hasattr(self, 'send_thread') and self.send_thread.is_alive():
            self.send_thread.join(timeout=1.0)
        if hasattr(self, 'receive_thread') and self.receive_thread.is_alive():
            self.receive_thread.join(timeout=1.0)
            
        if self.socket:
            self.socket.close()
        self.connected = False
        self.events.emit(EventType.DISCONNECTED)
    
    def login(self, account: str, password: str, timeout: float = 5.0) -> bool:
        """Login to server and wait for response"""
        if not self.connected:
            return False
            
        # Create login packet with encryption key
        packet = LoginPacket(account, password, self.encryption_key)
        raw_data = packet.to_bytes()
        
        # Compress and send (matches working client)
        compressed = zlib.compress(raw_data)
        self._send_packet_raw(compressed)
        
        # Setup encryption
        self.in_codec.reset(self.encryption_key)
        self.out_codec.reset(self.encryption_key)
        self.first_encrypted_packet = True
        self.first_recv_packet = True
        
        print(f"Sent login: account={account}")
        
        # Wait for login response (PLO_SIGNATURE packet)
        self.login_success = False
        self.level_loaded = False
        start_time = time.time()
        
        # Wait for either login success or player warp
        while time.time() - start_time < timeout:
            if self.login_success or self.level_loaded:
                if self.login_success:
                    print("Login accepted by server")
                if self.level_loaded:
                    print("Player warped to level, ready to play!")
                return True
            time.sleep(0.1)
        
        print("Login timeout - no response from server")
        return False
    
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
        print(f"🔧 Decoding {len(truncated_hex)} characters of truncated hex")
        
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
        
        print(f"   Decoded {tile_count} tiles from truncated hex")
        
        # Show first few tile IDs for verification
        first_tiles = []
        for i in range(min(10, tile_count)):
            tile_id = struct.unpack('<H', board_data[i*2:i*2+2])[0]
            first_tiles.append(tile_id)
        print(f"   First 10 tile IDs: {first_tiles}")
        
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
        """Load Graal tile mapping for collision detection"""
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
        self.queue_packet(packet.to_bytes())
    
    def _send_packet_raw(self, data: bytes):
        """Send raw packet immediately (for login)"""
        length = struct.pack('>H', len(data))
        self.socket.sendall(length + data)
    
    def queue_packet(self, data: bytes):
        """Queue packet for threaded sending"""
        # Prepare encrypted packet
        # Determine compression type
        if len(data) <= 55:
            compression_type = CompressionType.UNCOMPRESSED
            compressed_data = data
        else:
            compression_type = CompressionType.ZLIB
            compressed_data = zlib.compress(data)
        
        # Create a new codec for this packet with the appropriate limit
        packet_codec = GraalEncryption(self.encryption_key)
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
        
        # Queue for sending
        self.send_queue.put(final_packet)
    
    def send_encrypted_packet(self, data: bytes):
        """Legacy method - redirects to queue"""
        self.queue_packet(data)
    
    def _send_loop(self):
        """Send thread loop with rate limiting"""
        while self.running:
            try:
                # Get packet from queue (blocking with timeout)
                packet = self.send_queue.get(timeout=0.1)
                
                # Send packet
                self.socket.sendall(packet)
                
                # Rate limiting to prevent encryption desync
                time.sleep(self.packet_send_rate)
                
            except Empty:
                continue
            except Exception as e:
                print(f"Send thread error: {e}")
                break
    
    def _receive_loop(self):
        """Receive thread loop with buffering"""
        self.socket.settimeout(1.0)
        
        while self.running:
            try:
                packet = self.recv_packet()
                if packet:
                    # Buffer received packet
                    self.receive_buffer.put(packet)
                    # Also process immediately for real-time events
                    self._process_packet(packet)
            except Exception as e:
                if self.running:  # Only print if not shutting down
                    print(f"Receive thread error: {e}")
                continue
                
        # Auto-disconnect on receive error
        if self.running:
            self.disconnect()
    
    def recv_packet(self):
        """Receive a packet"""
        try:
            length_data = self._recv_exact(2)
            if not length_data:
                return None
            length = struct.unpack('>H', length_data)[0]
            return self._recv_exact(length)
        except:
            return None
            
    def _recv_exact(self, size: int):
        """Receive exact number of bytes"""
        data = b''
        while len(data) < size:
            try:
                chunk = self.socket.recv(size - len(data))
                if not chunk:
                    return None
                data += chunk
            except:
                if data:
                    continue
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
                            print(f"🎯 Found large packet: ID={packet_id}, Size={packet_size} bytes (likely board data)")
                            
                            # Extract the packet data (truncated hex)
                            packet_data = decrypted[pos+4:pos+4+packet_size]
                            
                            # Initialize board buffer if not exists
                            if not hasattr(self, 'board_hex_buffer'):
                                self.board_hex_buffer = b''
                            
                            # Append truncated hex data
                            self.board_hex_buffer += packet_data
                            print(f"   Collected {packet_size} bytes of truncated hex")
                            print(f"   Total hex buffer: {len(self.board_hex_buffer)} bytes")
                            
                            # Check if we have enough for a full board (8192 characters = 4096 tiles)
                            if len(self.board_hex_buffer) >= 8192:
                                print(f"🎯 Found enough truncated hex data! Converting to binary...")
                                
                                # Take exactly 8192 characters and convert from truncated hex
                                truncated_hex = self.board_hex_buffer[:8192].decode('ascii', errors='ignore')
                                board_data = self._decode_truncated_hex(truncated_hex)
                                
                                # Apply board data to level
                                if self.level_manager.current_level:
                                    self.level_manager.current_level.set_board_data(board_data)
                                    self.level_manager.current_level.width = 64
                                    self.level_manager.current_level.height = 64
                                    print(f"📦 Applied {len(board_data)} bytes to level!")
                                    
                                    # Save for debugging
                                    with open("board_stream_extracted.bin", "wb") as f:
                                        f.write(board_data)
                                    print(f"💾 Saved extracted board data")
                                    
                                    # Test first few tiles
                                    import struct
                                    print(f"🔍 First few tiles from stream:")
                                    for i in range(min(5, len(board_data)//2)):
                                        tile_id = struct.unpack('<H', board_data[i*2:i*2+2])[0]
                                        print(f"   Tile {i}: ID {tile_id}")
                                
                                # Clear board stream state
                                self.board_stream_active = False
                                self.board_hex_buffer = b''
                                print(f"✅ Board stream complete!")
                                return
                        
                        # Move to next packet
                        pos += 4 + packet_size
                    else:
                        break
                
                return  # Don't process as normal packets when in board stream mode
            
            # Process the decrypted data normally
            pos = 0
            while pos < len(decrypted):
                # Find the next newline (packet terminator)
                next_newline = decrypted.find(b'\n', pos)
                
                if next_newline == -1:
                    # No more complete packets
                    break
                    
                # Extract one packet (not including the newline)
                packet = decrypted[pos:next_newline]
                pos = next_newline + 1
                
                if packet and len(packet) >= 1:
                    # First byte is Graal-encoded packet ID
                    packet_id = packet[0] - 32
                    packet_data = packet[1:]
                    
                    # Update session packet count
                    self.session.increment_packet_count()
                    
                    result = self.packet_handler.handle_packet(packet_id, packet_data)
                    if result:
                        self._handle_packet_result(packet_id, result)
                    self.events.emit(EventType.RAW_PACKET_RECEIVED, packet_id=packet_id, data=packet_data)
        except Exception as e:
            pass
    
    def recv_encrypted_packet_data(self, packet: bytes):
        """Decrypt packet data"""
        if not packet or len(packet) == 0:
            return None
            
        compression_type = packet[0]
        encrypted_data = packet[1:]
        
        # Create a new codec for this packet with the appropriate limit
        packet_codec = GraalEncryption(self.encryption_key)
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
                print(f"Unknown compression type: {compression_type}")
                return None
        except Exception as e:
            # Silently ignore decompression errors for now
            return None
    
    def _handle_packet_result(self, packet_id: int, result: Dict[str, Any]):
        """Handle parsed packet result"""
        packet_type = result.get("type")
        
        if packet_type == "player_props":
            # Update local player
            self.local_player.update_from_props(result["props"])
            self.session.set_local_player(self.local_player)
            self.events.emit(EventType.PLAYER_PROPS_UPDATE, player=self.local_player)
            
        elif packet_type == "other_player_props":
            # Update other player
            player_id = result["player_id"]
            if player_id not in self.players:
                self.players[player_id] = Player(player_id)
            self.players[player_id].update_from_props(result["props"])
            self.session.update_player(self.players[player_id])
            self.events.emit(EventType.OTHER_PLAYER_UPDATE, player=self.players[player_id])
            
        elif packet_type == "add_player":
            # Add new player
            player_id = result["player_id"]
            if player_id not in self.players:
                self.players[player_id] = Player(player_id)
            self.players[player_id].update_from_props(result["props"])
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
                print(f"Added unknown player from chat: ID:{player_id}")
            
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
            
        elif packet_type == "server_text":
            # Server message
            self.events.emit(EventType.SERVER_MESSAGE, text=result["text"])
            
        elif packet_type == "signature":
            # Server signature - indicates login accepted
            self.login_success = True
            self.events.emit(EventType.LOGIN_SUCCESS)
            print(f"Login accepted! Signature: {result.get('signature', 'unknown')}")
            
        elif packet_type == "player_warp":
            # Player warp - indicates we're in a level and ready to play
            self.level_loaded = True
            warp_level = result.get('level', 'unknown')
            warp_x = result.get('x', 0)
            warp_y = result.get('y', 0)
            print(f"Warped to level: {warp_level} at ({warp_x}, {warp_y})")
            
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
            print(f"🎯 CLIENT: Received board packet!")
            board_data = result.get("board_data", b'')
            print(f"   Board data size: {len(board_data)} bytes")
            print(f"   Current level: {self.level_manager.current_level.name if self.level_manager.current_level else 'None'}")
            
            if len(board_data) > 0:
                if len(board_data) == 8192:
                    # Complete board data - apply immediately
                    print(f"📦 Complete board packet with {len(board_data)} bytes")
                    if self.level_manager.current_level:
                        self.level_manager.current_level.set_board_data(board_data)
                        print(f"✅ Applied board data to current level!")
                    else:
                        print(f"⚠️ No current level to apply board data to")
                else:
                    # Partial board data - start streaming mode
                    print(f"📦 Initial board packet with {len(board_data)} bytes")
                    print(f"🔄 Board stream starting - expecting truncated hex chunks...")
                    self.board_stream_active = True
                    if not hasattr(self, 'board_hex_buffer'):
                        self.board_hex_buffer = b''
            elif len(board_data) == 0:
                # 0-byte board packet - might be end signal
                print(f"🔄 0-byte board packet received")
                if hasattr(self, 'board_stream_active') and self.board_stream_active:
                    print(f"   Stream already active, continuing...")
                else:
                    print(f"   Starting board stream...")
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
            # Level link
            self.level_manager.handle_level_link(result["data"])
        
        # Many more packet types to handle...