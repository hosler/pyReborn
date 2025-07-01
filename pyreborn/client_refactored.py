"""
Refactored RebornClient - maintains backward compatibility while improving architecture.
"""

import time
import threading
import random
from typing import Optional, Dict, Any
from queue import Queue

from .core.connection import Connection
from .core.protocol import ProtocolCodec
from .encryption import GraalEncryption
from .protocol.enums import PlayerToServer, ServerToPlayer, PlayerProp, Direction
from .protocol.packets import (
    LoginPacket, PlayerPropsPacket, ToAllPacket, 
    BombAddPacket, ArrowAddPacket, FireSpyPacket
)
from .handlers.packet_handler import PacketHandler
from .models.player import Player
from .models.level import Level
from .events import EventManager
from .session import SessionManager
from .level_manager import LevelManager

class RebornClient:
    """Main client for connecting to Graal servers - refactored version"""
    
    def __init__(self, host: str, port: int = 14900):
        self.host = host
        self.port = port
        
        # Core components
        self.connection = Connection()
        self.codec = ProtocolCodec()
        self.in_codec = GraalEncryption()
        self.out_codec = GraalEncryption()
        
        # State
        self.connected = False
        self.login_success = False
        self.level_loaded = False
        self.encryption_key = random.randint(0, 255)
        self.first_encrypted_packet = True
        self.first_recv_packet = True
        
        # Game state
        self.local_player = Player()
        self.players: Dict[int, Player] = {}
        self.current_level: Optional[Level] = None
        self.levels: Dict[str, Level] = {}
        
        # Components
        self.events = EventManager()
        self.session = SessionManager()
        self.level_manager = LevelManager(self)
        self.packet_handler = PacketHandler()
        
        # Threading
        self._send_queue = Queue()
        self._send_thread: Optional[threading.Thread] = None
        self.running = False
        
        # Setup connections between components
        self._setup_components()
        
    def _setup_components(self):
        """Wire up components"""
        # Connection callbacks
        self.connection.on_data_received = self._on_raw_data
        self.connection.on_disconnected = self._on_disconnected
        
        # Codec callbacks
        self.codec.on_packet_received = self._on_packet_received
        
        # Setup packet handler
        self.packet_handler.setup_handlers(self)
        
    def connect(self) -> bool:
        """Connect to server"""
        if not self.connection.connect(self.host, self.port):
            return False
            
        self.connected = True
        self.running = True
        
        # Start send thread
        self._send_thread = threading.Thread(target=self._send_loop, daemon=True)
        self._send_thread.start()
        
        return True
        
    def disconnect(self):
        """Disconnect from server"""
        self.running = False
        self.connected = False
        self.connection.disconnect()
        
        # Clear state
        self.login_success = False
        self.level_loaded = False
        self.players.clear()
        self.levels.clear()
        
    def login(self, account: str, password: str, timeout: float = 5.0) -> bool:
        """Login to server"""
        if not self.connected:
            return False
            
        # Create and send login packet
        login_packet = LoginPacket(account, password, self.encryption_key)
        packet_data = login_packet.to_bytes()
        self._send_raw_packet(packet_data)
        
        # Reset encryption state
        self.in_codec.reset(self.encryption_key)
        self.out_codec.reset(self.encryption_key)
        self.first_encrypted_packet = True
        self.first_recv_packet = True
        
        # Wait for login response
        self.login_success = False
        self.level_loaded = False
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if self.login_success or self.level_loaded:
                return True
            time.sleep(0.1)
            
        return False
        
    # === Backward Compatible API ===
    
    def move_to(self, x: float, y: float, direction: Optional[Direction] = None):
        """Move to position"""
        if direction is None:
            direction = self.local_player.direction
            
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_X, x)
        packet.add_property(PlayerProp.PLPROP_Y, y)
        packet.add_property(PlayerProp.PLPROP_SPRITE, direction)
        self._send_packet(packet)
        
        # Update local state
        self.local_player.x = x
        self.local_player.y = y
        self.local_player.direction = direction
        
    def set_nickname(self, nickname: str):
        """Set nickname"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_NICKNAME, nickname)
        self._send_packet(packet)
        self.local_player.nickname = nickname
        
    def set_chat(self, message: str):
        """Set chat bubble"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_CURCHAT, message)
        self._send_packet(packet)
        self.local_player.chat = message
        
    def set_head_image(self, image: str):
        """Set head image"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_HEADGIF, image)
        self._send_packet(packet)
        self.local_player.head_image = image
        
    def set_body_image(self, image: str):
        """Set body image"""
        packet = PlayerPropsPacket()
        packet.add_property(PlayerProp.PLPROP_BODYIMG, image)
        self._send_packet(packet)
        self.local_player.body_image = image
        
    def drop_bomb(self, x: Optional[float] = None, y: Optional[float] = None, power: int = 1):
        """Drop a bomb"""
        if x is None:
            x = self.local_player.x
        if y is None:
            y = self.local_player.y
        packet = BombAddPacket(x, y, power)
        self._send_packet(packet)
        
    def shoot_arrow(self):
        """Shoot an arrow"""
        packet = ArrowAddPacket()
        self._send_packet(packet)
        
    def fire_effect(self):
        """Fire effect"""
        packet = FireSpyPacket()
        self._send_packet(packet)
        
    # === Internal Methods ===
    
    def _on_raw_data(self, data: bytes):
        """Handle raw data from connection"""
        self.codec.feed_data(data)
        
    def _on_packet_received(self, compression_type: int, encrypted_data: bytes):
        """Handle compressed/encrypted packet"""
        # Decrypt
        if self.first_recv_packet:
            # First packet is unencrypted
            decrypted = encrypted_data
            self.first_recv_packet = False
        else:
            # Create per-packet codec for decryption
            packet_codec = GraalEncryption(self.encryption_key)
            packet_codec.iterator = self.in_codec.iterator
            packet_codec.limit_from_type(compression_type)
            
            decrypted = packet_codec.decrypt(encrypted_data)
            self.in_codec.iterator = packet_codec.iterator
            
        # Decompress
        decompressed = self.codec.decode_packet(compression_type, decrypted)
        if not decompressed:
            return
            
        # Parse individual packets
        packets = self.codec.parse_graal_packets(decompressed)
        for packet_id, packet_data in packets:
            self.packet_handler.handle_packet(packet_id, packet_data)
            
    def _on_disconnected(self):
        """Handle disconnection"""
        self.events.emit('disconnected', {})
        self.disconnect()
        
    def _send_packet(self, packet):
        """Queue a packet for sending"""
        packet_data = packet.to_bytes()
        self._send_queue.put(packet_data)
        
    def _send_raw_packet(self, data: bytes):
        """Send raw packet data immediately"""
        if self.first_encrypted_packet:
            # First packet is unencrypted
            encoded = self.codec.encode_packet(data)
            self.connection.send(encoded)
            self.first_encrypted_packet = False
        else:
            self._send_queue.put(data)
            
    def _send_loop(self):
        """Send packets from queue with rate limiting"""
        last_send = 0
        
        while self.running:
            try:
                # Rate limit to 50ms between packets
                now = time.time()
                if now - last_send < 0.05:
                    time.sleep(0.05 - (now - last_send))
                    
                # Get packet
                packet_data = self._send_queue.get(timeout=0.1)
                
                # Encode
                encoded = self.codec.encode_packet(packet_data)
                
                # Encrypt (skip header)
                compression_type = encoded[2]
                encrypted_body = self._encrypt_packet(encoded[3:], compression_type)
                
                # Send
                final_packet = encoded[:3] + encrypted_body
                self.connection.send(final_packet)
                
                last_send = time.time()
                
            except:
                continue
                
    def _encrypt_packet(self, data: bytes, compression_type: int) -> bytes:
        """Encrypt packet data"""
        packet_codec = GraalEncryption(self.encryption_key)
        packet_codec.iterator = self.out_codec.iterator
        packet_codec.limit_from_type(compression_type)
        
        encrypted = packet_codec.encrypt(data)
        self.out_codec.iterator = packet_codec.iterator
        
        return encrypted