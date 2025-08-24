"""
Unified Connection Manager

This is the main interface for all connection functionality, consolidating:
- Socket management and networking
- Encryption handling
- Version management and protocol negotiation
- Connection resilience and recovery
"""

import logging
from typing import Optional, Callable

from .socket_manager import ConnectionManager as SocketManager
from .resilience_manager import ConnectionState, ReconnectStrategy
from .version_manager import VersionManager
from .encryption import RebornEncryption

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Unified connection management interface"""
    
    def __init__(self, host: str, port: int, version: str = "6.037"):
        self.host = host
        self.port = port
        
        # Core components
        self.version_manager = VersionManager(version)
        self.socket_manager = SocketManager()
        self.encryption = RebornEncryption()
        
        # State
        self.connected = False
        self._packet_callback: Optional[Callable[[bytes], None]] = None
        
    def set_packet_callback(self, callback: Callable[[bytes], None]):
        """Set callback for received packets"""
        self._packet_callback = callback
        self.socket_manager.set_packet_callback(callback)
    
    def connect(self) -> bool:
        """Establish connection to server"""
        try:
            # Initialize socket manager with config
            from ..config.client_config import ClientConfig
            from ..session.events import EventManager
            
            config = ClientConfig(host=self.host, port=self.port, version=self.version_manager.version)
            events = EventManager()
            
            self.socket_manager.initialize(config, events)
            
            # Connect to server
            success = self.socket_manager.connect(self.host, self.port)
            if success:
                self.connected = True
                logger.info(f"Connected to {self.host}:{self.port} using version {self.version_manager.version}")
            return success
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False
    
    def login(self, account: str, password: str) -> bool:
        """Send login packet and establish session"""
        if not self.connected:
            return False
            
        try:
            login_packet = self.version_manager.create_login_packet(
                account, password, self.socket_manager.encryption_key
            )
            # Login packet must be sent unencrypted
            self.socket_manager.send_unencrypted_packet(login_packet)
            return True
        except Exception as e:
            logger.error(f"Login failed: {e}")
            return False
    
    def send_packet(self, data: bytes):
        """Send packet through socket manager"""
        if self.socket_manager:
            self.socket_manager.send_packet(data)
    
    def disconnect(self):
        """Close connection"""
        if self.socket_manager:
            self.socket_manager.disconnect()
        self.connected = False
        
    def is_connected(self) -> bool:
        """Check if connected"""
        return self.connected and (self.socket_manager.connected if self.socket_manager else False)