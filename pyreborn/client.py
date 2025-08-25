#!/usr/bin/env python3
"""
Simple PyReborn Client
======================

This module provides a clean, simple client interface that wraps the complex
ModularRebornClient implementation. Users only need to import this one file.
"""

from typing import Optional, List, Dict, Any, Callable, TYPE_CHECKING
import logging

# Import the real implementation
from .core.reborn_client import RebornClient as _ModularRebornClient
_using_real_client = True
from .models.player import Player
from .models.level import Level
from .protocol.enums import Direction, PlayerProp
from .core.events import EventType

logger = logging.getLogger(__name__)


class Client:
    """
    Simple PyReborn client for connecting to Reborn servers.
    
    This is a simplified wrapper around the complex ModularRebornClient
    that provides an easy-to-use interface for most common operations.
    
    Usage:
        client = Client("localhost", 14900)
        client.connect()
        client.login("username", "password")
        
        # Move player
        client.move(1, 0)  # Move right
        
        # Chat
        client.say("Hello, world!")
        
        # Access player data
        player = client.get_player()
        print(f"Player: {player.account} at ({player.x}, {player.y})")
    """
    
    def __init__(self, host: str = "localhost", port: int = 14900, version: str = "6.037"):
        """
        Initialize client.
        
        Args:
            host: Server hostname or IP address
            port: Server port number  
            version: Protocol version to use
        """
        self.host = host
        self.port = port
        self.version = version
        
        # Internal client (hidden from users)
        self._client: Optional[_ModularRebornClient] = None
        
        # GMAP render API
        self._gmap_render_api = None
        
        # Connection state
        self._connected = False
        self._logged_in = False
        
        logger.info(f"PyReborn Client initialized for {host}:{port}")
    
    @classmethod
    def session(cls, host: str, port: int, username: str, password: str, version: str = "6.037") -> 'Client':
        """
        Create a client with automatic connection and login for use with context manager.
        
        Args:
            host: Server hostname or IP address
            port: Server port number
            username: Account username
            password: Account password
            version: Protocol version to use
            
        Returns:
            Client instance ready for use with 'with' statement
            
        Example:
            with Client.session("localhost", 14900, "user", "pass") as client:
                client.move(1, 0)
                client.say("Hello!")
                # Auto-disconnect on exit
        """
        client = cls(host, port, version)
        if not client.connect():
            raise ConnectionError(f"Failed to connect to {host}:{port}")
        if not client.login(username, password):
            raise ConnectionError(f"Failed to login as {username}")
        return client
    
    # Builder pattern removed for simplicity - use direct Client() constructor
    
    def connect(self) -> bool:
        """
        Connect to the server.
        
        Returns:
            True if connected successfully, False otherwise
        """
        try:
            self._client = _ModularRebornClient(
                host=self.host,
                port=self.port,
                version=self.version
            )
            
            # Initialize GMAP render API
            from .gmap_api.gmap_render_api import GMAPRenderAPI
            self._gmap_render_api = GMAPRenderAPI(self._client)
            
            self._connected = self._client.connect()
            if self._connected:
                logger.info(f"Connected to {self.host}:{self.port}")
            else:
                logger.error(f"Failed to connect to {self.host}:{self.port}")
                
            return self._connected
            
        except Exception as e:
            logger.error(f"Connection error: {e}")
            return False
    
    def login(self, username: str, password: str) -> bool:
        """
        Login to the server.
        
        Args:
            username: Account username
            password: Account password
            
        Returns:
            True if logged in successfully, False otherwise
        """
        if not self._connected or not self._client:
            logger.error("Not connected - call connect() first")
            return False
            
        try:
            self._logged_in = self._client.login(username, password)
            if self._logged_in:
                logger.info(f"Logged in as {username}")
            else:
                logger.error(f"Failed to login as {username}")
                
            return self._logged_in
            
        except Exception as e:
            logger.error(f"Login error: {e}")
            return False
    
    def disconnect(self) -> None:
        """Disconnect from the server."""
        if self._client:
            self._client.disconnect()
            self._connected = False
            self._logged_in = False
            logger.info("Disconnected from server")
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with automatic disconnection"""
        self.disconnect()
        return False  # Don't suppress exceptions
    
    def get_player(self) -> Optional[Player]:
        """
        Get the local player object.
        
        Returns:
            Player object if logged in, None otherwise
        """
        if not self._client:
            return None
        return self._client.get_local_player()
    
    @property
    def player(self) -> Optional[Player]:
        """
        Get the local player object (property access).
        
        Returns:
            Player object if logged in, None otherwise
        """
        return self.get_player()
    
    @property
    def gmap_manager(self):
        """Get GMAP manager (compatibility property)"""
        if self._client and hasattr(self._client, 'gmap_manager'):
            return self._client.gmap_manager
        return None
    
    @property
    def session_manager(self):
        """Get session manager (compatibility property)"""
        if self._client and hasattr(self._client, 'session_manager'):
            return self._client.session_manager
        return None
    
    @property
    def level_manager(self):
        """Get level manager (compatibility property)"""
        if self._client and hasattr(self._client, 'level_manager'):
            return self._client.level_manager
        return None
    
    def move(self, dx: int, dy: int) -> bool:
        """
        Move the player.
        
        Args:
            dx: Change in X direction (-1, 0, or 1)
            dy: Change in Y direction (-1, 0, or 1)
            
        Returns:
            True if move was sent successfully
        """
        if not self._logged_in or not self._client:
            return False
            
        try:
            self._client.move(dx, dy)
            return True
        except Exception as e:
            logger.error(f"Move error: {e}")
            return False
    
    def drop_bomb(self, power: int = 1, timer: int = 55) -> bool:
        """Drop a bomb at current position.
        
        Args:
            power: Bomb power (1-10)
            timer: Bomb timer in ticks
            
        Returns:
            True if bomb was dropped successfully
        """
        if not self._logged_in or not self._client:
            return False
            
        try:
            return self._client.drop_bomb(power, timer)
        except Exception as e:
            logger.error(f"Bomb drop error: {e}")
            return False
    
    def take_item(self, x: float, y: float) -> bool:
        """Take an item at specified coordinates.
        
        Args:
            x: X coordinate of item (in tiles)
            y: Y coordinate of item (in tiles)
            
        Returns:
            True if item take was sent successfully
        """
        if not self._logged_in or not self._client:
            return False
            
        try:
            return self._client.take_item(x, y)
        except Exception as e:
            logger.error(f"Item take error: {e}")
            return False
    
    def attack(self) -> bool:
        """Perform sword attack.
        
        Returns:
            True if attack was sent successfully
        """
        if not self._logged_in or not self._client:
            return False
            
        try:
            return self._client.attack()
        except Exception as e:
            logger.error(f"Attack error: {e}")
            return False
    
    def say(self, message: str) -> bool:
        """
        Send a chat message.
        
        Args:
            message: Message to send
            
        Returns:
            True if message was sent successfully
        """
        if not self._logged_in or not self._client:
            return False
            
        try:
            self._client.say(message)
            return True
        except Exception as e:
            logger.error(f"Chat error: {e}")
            return False
    
    def get_level(self) -> Optional[Level]:
        """
        Get the current level.
        
        Returns:
            Level object if available, None otherwise
        """
        if not self._client:
            return None
        
        level_manager = self._client.get_manager('level')
        if level_manager:
            return level_manager.get_current_level()
        return None
    
    def get_players(self) -> List[Player]:
        """
        Get list of all players on current level.
        
        Returns:
            List of Player objects
        """
        if not self._client:
            return []
        
        session_manager = self._client.get_manager('session')
        if session_manager:
            return session_manager.get_all_players()
        return []
    
    def on_event(self, event_type: EventType, callback: Callable[[Dict[str, Any]], None]) -> None:
        """
        Register an event handler.
        
        Args:
            event_type: Type of event to listen for
            callback: Function to call when event occurs
        """
        if self._client:
            event_manager = self._client.get_manager('event')
            if event_manager:
                event_manager.subscribe(event_type, callback)
    
    def request_file(self, filename: str) -> bool:
        """
        Request a file from the server.
        
        Args:
            filename: Name of file to request
            
        Returns:
            True if request was sent successfully
        """
        if not self._client:
            logger.warning("Cannot request file: not connected")
            return False
        
        # Send file request using packet structure
        from .packets.outgoing.system.want_file import PLI_WANTFILE
        packet = PLI_WANTFILE.create_packet(filename=filename)
        
        if packet:
            # Convert packet to bytes
            packet_bytes = packet.to_bytes()
            success = self._client.send_packet(packet_bytes)
            if success:
                logger.info(f"Requested file: {filename}")
            else:
                logger.warning(f"Failed to request file: {filename}")
            return success
        return False
    
    def update(self) -> None:
        """
        Update the client. Call this regularly in your main loop.
        """
        if self._client:
            self._client.update()
    
    def get_gmap_render_data(self):
        """Get complete GMAP rendering data (clean API for pygame clients)
        
        Returns:
            GMAPRenderData with everything needed for GMAP rendering, or None if not in GMAP mode
        """
        if self._gmap_render_api:
            return self._gmap_render_api.get_gmap_render_data()
        return None
    
    # Properties for easy access
    @property
    def connected(self) -> bool:
        """True if connected to server."""
        return self._connected
    
    @property  
    def logged_in(self) -> bool:
        """True if logged in to server."""
        return self._logged_in
    
    @property
    def player_count(self) -> int:
        """Number of players on current level."""
        return len(self.get_players())
    
    # Advanced API access (for users who need more control)
    def get_advanced_client(self) -> Optional[_ModularRebornClient]:
        """
        Get access to the underlying ModularRebornClient for advanced operations.
        
        Warning: This exposes the complex internal API. Only use if you need
        features not available in the simplified Client interface.
        
        Returns:
            ModularRebornClient instance or None
        """
        return self._client


# Convenience functions for quick usage
def connect_and_login(host: str, port: int = 14900, username: str = "", password: str = "", version: str = "6.037") -> Optional[Client]:
    """
    Connect and login in one step.
    
    Args:
        host: Server hostname or IP
        port: Server port
        username: Account username  
        password: Account password
        version: Protocol version
        
    Returns:
        Connected and logged-in Client, or None if failed
    """
    client = Client(host, port, version)
    
    if not client.connect():
        return None
        
    if username and password:
        if not client.login(username, password):
            client.disconnect()
            return None
            
    return client