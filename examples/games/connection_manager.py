"""
Connection Manager Module - Handles server connections and state transitions
"""

import threading
import time
from typing import Optional, Callable
from pyreborn import RebornClient
from pyreborn.events import EventType


class ConnectionManager:
    """Manages server connections and related state transitions"""
    
    def __init__(self):
        """Initialize connection manager"""
        self.client: Optional[RebornClient] = None
        self.is_connecting = False
        self.connection_thread: Optional[threading.Thread] = None
        
        # Callbacks
        self.on_connected: Optional[Callable] = None
        self.on_disconnected: Optional[Callable] = None
        self.on_connection_failed: Optional[Callable] = None
        self.on_level_received: Optional[Callable] = None
        
    def connect_async(self, host: str, port: int, username: str, password: str):
        """Start asynchronous connection to server
        
        Args:
            host: Server hostname
            port: Server port
            username: Username
            password: Password
        """
        if self.is_connecting:
            return
            
        self.is_connecting = True
        self.connection_thread = threading.Thread(
            target=self._connect_thread,
            args=(host, port, username, password),
            daemon=True
        )
        self.connection_thread.start()
        
    def _connect_thread(self, host: str, port: int, username: str, password: str):
        """Connection thread worker"""
        try:
            # Create client
            self.client = RebornClient(host, port)
            
            # Connect and login
            if self.client.connect() and self.client.login(username, password):
                # Set nickname
                self.client.set_nickname(username)
                
                # Setup event handlers
                self._setup_event_handlers()
                
                # Notify success
                if self.on_connected:
                    self.on_connected(self.client)
                    
                # Check if level is already loaded after a small delay
                # to ensure packets have been processed
                time.sleep(0.5)
                if self.client.level_manager.current_level:
                    print(f"Level already loaded: {self.client.level_manager.current_level.name}")
                    if self.on_level_received:
                        self.on_level_received(self.client.level_manager.current_level)
                        
                # Monitor connection (blocking call)
                self._monitor_connection()
            else:
                # Login failed
                if self.client:
                    self.client.disconnect()
                self.client = None
                
                if self.on_connection_failed:
                    self.on_connection_failed("Login failed")
                    
        except Exception as e:
            print(f"Connection error: {e}")
            if self.on_connection_failed:
                self.on_connection_failed(str(e))
                
        finally:
            self.is_connecting = False
            
    def _setup_event_handlers(self):
        """Setup network event handlers"""
        if not self.client:
            return
            
        events = self.client.events
        
        # Level change handler
        def handle_level_received(**kwargs):
            level = kwargs.get('level')
            if level and self.on_level_received:
                self.on_level_received(level)
                
        events.subscribe(EventType.LEVEL_BOARD_LOADED, handle_level_received)
        events.subscribe(EventType.LEVEL_ENTERED, handle_level_received)
        
    def _monitor_connection(self):
        """Monitor connection status"""
        while self.client and self.is_connected():
            time.sleep(0.1)
            
        # Connection lost
        if self.on_disconnected:
            self.on_disconnected()
            
    def disconnect(self):
        """Disconnect from server"""
        if self.client:
            self.client.disconnect()
            self.client = None
            
    def is_connected(self) -> bool:
        """Check if connected to server
        
        Returns:
            True if connected
        """
        return self.client is not None and self.client.connected
        
    def check_for_level(self) -> Optional[object]:
        """Check if a level is loaded
        
        Returns:
            Current level or None
        """
        if self.client and self.client.level_manager:
            level = self.client.level_manager.current_level
            if level:
                print(f"ConnectionManager: Found level {level.name}")
            return level
        return None