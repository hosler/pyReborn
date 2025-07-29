"""
Connection Manager - Handles network connections, encryption, and low-level communication
"""

import socket
import threading
import time
import random
import logging
from typing import Optional, Callable
from queue import Queue, Empty

from ..core.interfaces import IConnectionManager
from ..config.client_config import ClientConfig
from ..core.events import EventManager, EventType
from .encryption import RebornEncryption


class ConnectionManager(IConnectionManager):
    """Manages network connection, encryption, and packet transmission"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.config: Optional[ClientConfig] = None
        self.events: Optional[EventManager] = None
        
        # Network state
        self.socket: Optional[socket.socket] = None
        self.connected = False
        self.running = False
        
        # Threading
        self.send_queue = Queue()
        self.send_thread: Optional[threading.Thread] = None
        self.receive_thread: Optional[threading.Thread] = None
        
        # Encryption
        self.encryption_key = random.randint(0, 255)
        self.in_codec = RebornEncryption()
        self.out_codec = RebornEncryption()
        self.first_encrypted_packet = True
        
        # Callbacks
        self._packet_received_callback: Optional[Callable[[bytes], None]] = None
        
    def initialize(self, config: ClientConfig, event_manager: EventManager) -> None:
        """Initialize with configuration and event system"""
        self.config = config
        self.events = event_manager
        
    def cleanup(self) -> None:
        """Clean up resources"""
        self.disconnect()
        
    @property
    def name(self) -> str:
        """Manager name"""
        return "connection_manager"
    
    def set_packet_callback(self, callback: Callable[[bytes], None]) -> None:
        """Set callback for received packets"""
        self._packet_received_callback = callback
    
    def connect(self, host: str, port: int) -> bool:
        """Establish connection to server"""
        try:
            self.logger.info(f"Connecting to {host}:{port}")
            
            # Create socket with timeout
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(self.config.connect_timeout if self.config else 10.0)
            
            # Connect
            self.socket.connect((host, port))
            self.socket.settimeout(None)  # Remove timeout after connection
            
            self.connected = True
            self.running = True
            
            # Start networking threads
            self._start_threads()
            
            # Emit connection event
            if self.events:
                self.events.emit(EventType.CONNECTED, host=host, port=port)
            
            self.logger.info("Connection established")
            return True
            
        except Exception as e:
            self.logger.error(f"Connection failed: {e}")
            if self.events:
                self.events.emit(EventType.CONNECTION_FAILED, error=str(e))
            return False
    
    def disconnect(self) -> None:
        """Close connection to server"""
        if not self.connected:
            return
            
        self.logger.info("Disconnecting...")
        
        # Stop threads
        self.running = False
        self.connected = False
        
        # Close socket
        if self.socket:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
                self.socket.close()
            except:
                pass
            self.socket = None
        
        # Wait for threads to finish
        if self.send_thread and self.send_thread.is_alive():
            self.send_thread.join(timeout=1.0)
        if self.receive_thread and self.receive_thread.is_alive():
            self.receive_thread.join(timeout=1.0)
        
        # Clear queues
        while not self.send_queue.empty():
            try:
                self.send_queue.get_nowait()
            except Empty:
                break
        
        # Emit disconnection event
        if self.events:
            self.events.emit(EventType.DISCONNECTED)
        
        self.logger.info("Disconnected")
    
    def is_connected(self) -> bool:
        """Check if connected to server"""
        return self.connected and self.socket is not None
    
    def send_packet(self, packet_data: bytes) -> bool:
        """Send packet to server"""
        if not self.is_connected():
            self.logger.warning("Cannot send packet: not connected")
            return False
        
        try:
            self.send_queue.put(packet_data, timeout=1.0)
            return True
        except Exception as e:
            self.logger.error(f"Failed to queue packet: {e}")
            return False
    
    def send_raw_packet(self, packet_data: bytes) -> bool:
        """Send raw packet immediately (bypasses queue)"""
        if not self.is_connected():
            return False
        
        try:
            # Encrypt and send
            encrypted_data = self._encrypt_outgoing(packet_data)
            self.socket.send(encrypted_data)
            return True
        except Exception as e:
            self.logger.error(f"Failed to send raw packet: {e}")
            return False
    
    def _start_threads(self) -> None:
        """Start networking threads"""
        self.send_thread = threading.Thread(target=self._send_worker, daemon=True)
        self.receive_thread = threading.Thread(target=self._receive_worker, daemon=True)
        
        self.send_thread.start()
        self.receive_thread.start()
    
    def _send_worker(self) -> None:
        """Send thread worker function"""
        packet_send_rate = 0.05  # 50ms between packets
        
        while self.running and self.connected:
            try:
                # Get packet from queue
                packet_data = self.send_queue.get(timeout=0.1)
                
                if packet_data and self.socket:
                    # Encrypt and send
                    encrypted_data = self._encrypt_outgoing(packet_data)
                    self.socket.send(encrypted_data)
                    
                    # Rate limiting
                    time.sleep(packet_send_rate)
                    
            except Empty:
                continue
            except Exception as e:
                if self.running:  # Only log if we're supposed to be running
                    self.logger.error(f"Send worker error: {e}")
                break
    
    def _receive_worker(self) -> None:
        """Receive thread worker function"""
        while self.running and self.connected:
            try:
                if not self.socket:
                    break
                
                # Receive data
                data = self.socket.recv(8192)
                if not data:
                    break
                
                # Decrypt data
                decrypted_data = self._decrypt_incoming(data)
                
                # Call packet callback
                if self._packet_received_callback and decrypted_data:
                    self._packet_received_callback(decrypted_data)
                    
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:  # Only log if we're supposed to be running
                    self.logger.error(f"Receive worker error: {e}")
                break
        
        # Connection lost
        if self.running:
            self.logger.warning("Connection lost")
            self.connected = False
            if self.events:
                self.events.emit(EventType.DISCONNECTED)
    
    def _encrypt_outgoing(self, data: bytes) -> bytes:
        """Encrypt outgoing packet data"""
        try:
            return self.out_codec.encrypt(data, self.encryption_key)
        except Exception as e:
            self.logger.error(f"Encryption error: {e}")
            return data
    
    def _decrypt_incoming(self, data: bytes) -> bytes:
        """Decrypt incoming packet data"""
        try:
            # Handle first encrypted packet special case
            if self.first_encrypted_packet:
                # First packet uses a different key calculation
                result = self.in_codec.decrypt(data, 255 - self.encryption_key)
                self.first_encrypted_packet = False
                return result
            else:
                return self.in_codec.decrypt(data, self.encryption_key)
        except Exception as e:
            self.logger.error(f"Decryption error: {e}")
            return data
    
    def get_encryption_key(self) -> int:
        """Get current encryption key"""
        return self.encryption_key
    
    def set_encryption_key(self, key: int) -> None:
        """Set encryption key"""
        self.encryption_key = key