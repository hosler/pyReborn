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
        
    def connect_async(self, host: str, port: int, username: str, password: str, version: str = "2.22"):
        """Start asynchronous connection to server
        
        Args:
            host: Server hostname
            port: Server port
            username: Account username
            password: Account password
            version: Client version to use
        """
        if self.is_connecting:
            return
            
        self.is_connecting = True
        self.connection_thread = threading.Thread(
            target=self._connect_thread,
            args=(host, port, username, password, version),
            daemon=True
        )
        self.connection_thread.start()
        
    def _connect_thread(self, host: str, port: int, username: str, password: str, version: str):
        """Connection thread worker"""
        try:
            # Create client with specified version
            # For Zelda server, always use 6.037
            if host == "hastur.eevul.net" and port == 14912:
                version = "6.037"
            self.client = RebornClient(host, port, version)
            
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
                
                # Look for a playable level with board data
                playable_level = None
                # Check level_manager.levels first
                for level_name, level in self.client.level_manager.levels.items():
                    if (not level_name.endswith('.gmap') and 
                        hasattr(level, 'board_tiles_64x64') and 
                        level.board_tiles_64x64):
                        playable_level = level
                        break
                
                # If not found, check client.levels
                if not playable_level:
                    for level_name, level in self.client.levels.items():
                        if (not level_name.endswith('.gmap') and 
                            hasattr(level, 'board_tiles_64x64') and 
                            level.board_tiles_64x64):
                            playable_level = level
                            break
                
                if playable_level:
                    print(f"Level already loaded: {playable_level.name} (playable with board data)")
                    if self.on_level_received:
                        self.on_level_received(playable_level)
                elif self.client.level_manager.current_level:
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
        
        # Player warp handler for GMAP transitions
        def handle_player_warp(**kwargs):
            x = kwargs.get('x', 0)
            y = kwargs.get('y', 0)
            level_name = kwargs.get('level', '')
            
            print(f"[ConnectionManager] Player warp: ({x}, {y}) level='{level_name}'")
            
            # Check if this is a GMAP edge warp (position at edge)
            if x <= 1 or x >= 62 or y <= 1 or y >= 62:
                print(f"[ConnectionManager] Edge warp detected: ({x}, {y}) level='{level_name}'")
                
                # For GMAP edge warps, the level name might be empty
                # In that case, we need to figure out which segment we're now in
                if not level_name and self.client and self.client.level_manager:
                    # Request the level based on current GMAP segment
                    current_level = self.client.level_manager.current_level
                    if current_level and current_level.name:
                        print(f"[ConnectionManager] Handling GMAP segment transition from {current_level.name}")
                        # The warp position tells us which direction we moved
                        # This will trigger the proper level change handling
                else:
                    # If we have a level name, this might be a proper level change
                    if level_name and self.client and self.client.level_manager:
                        print(f"[ConnectionManager] Warp to level: {level_name}")
                        
        events.subscribe('player_warp', handle_player_warp)
        
        # Handle GMAP level property changes
        def handle_player_properties(**kwargs):
            properties = kwargs.get('properties', {})
            
            # Check for GMAP level coordinate changes
            if 'gmaplevelx' in properties or 'gmaplevely' in properties:
                gmap_x = properties.get('gmaplevelx', 0)
                gmap_y = properties.get('gmaplevely', 0)
                print(f"[ConnectionManager] GMAP coordinates updated: ({gmap_x}, {gmap_y})")
                
                # If we have a current level that's a GMAP segment, we might need to update it
                if (self.client and self.client.level_manager and 
                    self.client.level_manager.current_level and 
                    '-' in self.client.level_manager.current_level.name):
                    current_name = self.client.level_manager.current_level.name
                    print(f"[ConnectionManager] Current level: {current_name}, may need segment update")
                    
        events.subscribe('player_properties', handle_player_properties)
        
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
        if self.client:
            # First try to find a level with board data (not gmaps)
            # Check level_manager.levels
            if self.client.level_manager:
                for level_name, level in self.client.level_manager.levels.items():
                    if (not level_name.endswith('.gmap') and 
                        hasattr(level, 'board_tiles_64x64') and 
                        level.board_tiles_64x64):
                        print(f"ConnectionManager: Found playable level {level.name} with board data (from level_manager)")
                        return level
            
            # Check client.levels
            for level_name, level in self.client.levels.items():
                if (not level_name.endswith('.gmap') and 
                    hasattr(level, 'board_tiles_64x64') and 
                    level.board_tiles_64x64):
                    print(f"ConnectionManager: Found playable level {level.name} with board data (from client.levels)")
                    return level
            
            # Fall back to current level
            if self.client.level_manager:
                level = self.client.level_manager.current_level
                if level:
                    print(f"ConnectionManager: Found level {level.name}")
                return level
        return None