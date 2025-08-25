"""
Unified Session Manager

This is the main interface for all session functionality, consolidating:
- Session state and authentication
- Player data and properties
- Chat and messaging
- Login and logout processes
- GMAP level name resolution
"""

import time
import logging
from typing import Optional, Dict, Any, Callable

from .session_state import SessionState, AuthenticationStatus, PlayerStatus
from .player_manager import PlayerManager
from .chat_manager import ChatManager

# Import GMAP functionality (with fallback)
try:
    from ..world.gmap_manager import GMAPManager
    from ..world.coordinate_helpers import CoordinateHelpers, CoordinateSet
    GMAP_AVAILABLE = True
except ImportError:
    # Fallback if coordinate helpers not available
    GMAP_AVAILABLE = False
    CoordinateSet = None
    CoordinateHelpers = None


class SessionManager:
    """Unified session management interface"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Core components
        self.player = PlayerManager()
        self.chat = ChatManager()
        
        # Session state
        self.state = SessionState.DISCONNECTED
        self.auth_status = AuthenticationStatus.NONE
        self.session_start_time: Optional[float] = None
        self.last_heartbeat: float = time.time()
        
        # Session data
        self.session_data: Dict[str, Any] = {}
        self.capabilities: set = set()
        
        # GMAP integration
        self.gmap_manager: Optional['GMAPManager'] = None
        self.current_level_name: Optional[str] = None  # Current level name from server
        self.last_concrete_level: Optional[str] = None  # Last concrete level (not .gmap)
        
        # Event callbacks
        self._state_change_callback: Optional[Callable[[SessionState, SessionState], None]] = None
        
    def set_state_change_callback(self, callback: Callable[[SessionState, SessionState], None]):
        """Set callback for session state changes"""
        self._state_change_callback = callback
        
    def start_session(self, account: str, password: str):
        """Start a new session"""
        self.logger.info(f"Starting session for account: {account}")
        self._change_state(SessionState.CONNECTING)
        
        self.player.set_login_data(account, password)
        self.auth_status = AuthenticationStatus.PENDING
        self.session_start_time = time.time()
        
    def authenticate(self, player_id: int):
        """Complete authentication process"""
        self.logger.info(f"Authentication successful for player ID: {player_id}")
        self.player.set_player_id(player_id)
        self.player.set_status(PlayerStatus.ONLINE)
        
        self.auth_status = AuthenticationStatus.AUTHENTICATED
        self._change_state(SessionState.AUTHENTICATED)
        
    def activate_session(self):
        """Activate the session (ready for gameplay)"""
        if self.auth_status == AuthenticationStatus.AUTHENTICATED:
            self._change_state(SessionState.ACTIVE)
            self.player.set_status(PlayerStatus.ACTIVE)
            self.logger.info("Session activated - ready for gameplay")
        else:
            self.logger.warning("Cannot activate session - not authenticated")
    
    def handle_login_failure(self, reason: str = "Unknown"):
        """Handle login failure"""
        self.logger.warning(f"Login failed: {reason}")
        self.auth_status = AuthenticationStatus.FAILED
        self._change_state(SessionState.LOGIN_FAILED)
        
    def update_heartbeat(self):
        """Update session heartbeat"""
        self.last_heartbeat = time.time()
        
    def is_active(self) -> bool:
        """Check if session is active"""
        return self.state == SessionState.ACTIVE and self.auth_status == AuthenticationStatus.AUTHENTICATED
        
    def is_authenticated(self) -> bool:
        """Check if session is authenticated"""
        return self.auth_status == AuthenticationStatus.AUTHENTICATED
        
    def get_player(self):
        """Get the player data"""
        return self.player.get_player()
    
    def get_all_players(self):
        """Get all players (including other players)"""
        players = []
        
        # Add local player
        local_player = self.get_player()
        if local_player:
            players.append(local_player)
        
        # Add other players if they exist
        if hasattr(self, 'other_players'):
            from ...models.player import Player
            for player_id, props in self.other_players.items():
                # Create a Player object from the properties
                other_player = Player()
                other_player.id = player_id
                
                # Copy properties to the player object
                for prop_name, value in props.items():
                    if hasattr(other_player, prop_name):
                        setattr(other_player, prop_name, value)
                
                players.append(other_player)
        
        return players
        
    def get_session_duration(self) -> float:
        """Get session duration in seconds"""
        if self.session_start_time:
            return time.time() - self.session_start_time
        return 0.0
        
    def add_capability(self, capability: str):
        """Add a session capability"""
        self.capabilities.add(capability)
        self.logger.debug(f"Added capability: {capability}")
        
    def has_capability(self, capability: str) -> bool:
        """Check if session has a capability"""
        return capability in self.capabilities
        
    def set_session_data(self, key: str, value: Any):
        """Set session-specific data"""
        self.session_data[key] = value
        
    def get_session_data(self, key: str, default: Any = None) -> Any:
        """Get session-specific data"""
        return self.session_data.get(key, default)
        
    def end_session(self):
        """End the current session"""
        self.logger.info("Ending session")
        
        # Reset all components
        self.player.reset()
        self.chat.clear_history()
        
        # Reset session state
        self.state = SessionState.DISCONNECTED
        self.auth_status = AuthenticationStatus.NONE
        self.session_start_time = None
        self.session_data.clear()
        self.capabilities.clear()
        
    def get_status_summary(self) -> Dict[str, Any]:
        """Get comprehensive session status"""
        return {
            'session_state': self.state.value,
            'auth_status': self.auth_status.value,
            'player_authenticated': self.player.is_authenticated(),
            'player_id': self.player.player_id,
            'account': self.player.account,
            'session_duration': self.get_session_duration(),
            'capabilities': list(self.capabilities),
            'player_status': self.player.status.value,
            'player_position': {
                'x': self.player.x,
                'y': self.player.y,
                'level': self.player.level
            }
        }
        
    def set_gmap_manager(self, gmap_manager: 'GMAPManager'):
        """Set reference to GMAP manager for level name resolution"""
        self.gmap_manager = gmap_manager
        self.logger.debug("GMAP manager reference set")
        
    def set_current_level(self, level_name: str):
        """Set the current level name (from server level change packets)"""
        old_level = self.current_level_name
        self.current_level_name = level_name
        self.logger.debug(f"Current level set to: {level_name}")
        
        # 🎯 TRACK CONCRETE LEVELS: Store last non-.gmap level for movement/collision
        if not level_name.endswith('.gmap'):
            self.last_concrete_level = level_name
            # Throttle tracked level messages  
            import time
            if not hasattr(self, '_last_tracked_level') or time.time() - getattr(self, '_last_tracked_level_time', 0) > 2.0:
                self.logger.info(f"📍 Tracked concrete level: {level_name}")
                self._last_tracked_level = level_name
                self._last_tracked_level_time = time.time()
            else:
                self.logger.debug(f"📍 Tracked concrete level: {level_name} (throttled)")
        
        # 🎯 CRITICAL: Auto-activate GMAP mode when level ends with .gmap
        if GMAP_AVAILABLE and self.gmap_manager and level_name.endswith('.gmap'):
            is_already_gmap_mode = self.gmap_manager.is_gmap_mode()
            
            if not is_already_gmap_mode:
                self.logger.info(f"🗺️ Auto-activating GMAP mode for: {level_name}")
                
                # 🚀 ENTER GMAP MODE WITH AUTOMATIC FILE DOWNLOAD
                # Get current player position if available
                # 🎯 FIXED: Use world coordinates (x2/y2) instead of local coordinates (x/y) for GMAP mode
                player = self.player.get_player() if self.player else None
                if player:
                    # Prefer world coordinates from GMAP packets (x2/y2)
                    world_x = getattr(player, 'x2', None)
                    world_y = getattr(player, 'y2', None)
                    
                    # Fallback to local coordinates if world coordinates not available
                    if world_x is None:
                        world_x = getattr(player, 'x', None)
                    if world_y is None:
                        world_y = getattr(player, 'y', None)
                        
                else:
                    world_x = None
                    world_y = None
                
                # Call enter_gmap_mode which will automatically request the GMAP file
                resolved_name = self.gmap_manager.enter_gmap_mode(
                    level_name, world_x, world_y
                )
                
                if resolved_name:
                    self.logger.info(f"✅ GMAP mode activated with file requests: {resolved_name}")
                else:
                    self.logger.warning(f"⚠️ GMAP mode activated but could not resolve level: {level_name}")
                
                # Try to load/register GMAP structure if we can
                self._try_register_gmap_structure(level_name)
                
        elif GMAP_AVAILABLE and self.gmap_manager and not level_name.endswith('.gmap'):
            # Concrete level received - might be exiting GMAP mode or just entering a level
            # Don't automatically deactivate GMAP mode here since server sends both .gmap and concrete names
            pass
    
    def _try_register_gmap_structure(self, gmap_name: str):
        """Try to register GMAP structure if possible"""
        # GMAP structures should be loaded from actual files, not hardcoded
        # The system will request the GMAP file and parse it properly
        self.logger.debug(f"GMAP structure will be loaded from file: {gmap_name}")
        
    def get_effective_level_name(self) -> Optional[str]:
        """Get the effective level name (resolves GMAP level names to actual levels).
        
        This method provides the core functionality for resolving GMAP level names
        to actual level names using world coordinates from player properties.
        
        Strategy:
        1. If current level is concrete (not .gmap), return it (server authority)
        2. If current level is .gmap, try to resolve using coordinates
        3. Fallback to GMAP filename if resolution fails
        
        Returns:
            Actual level name if available, otherwise current level name
        """
        if not GMAP_AVAILABLE or not self.gmap_manager:
            return self.current_level_name
        
        # 🎯 NEW STRATEGY: If we're in GMAP mode, use the last concrete level for collision/movement
        if self.gmap_manager.is_gmap_mode() and self.last_concrete_level:
            # Only log this once per level change to avoid spam
            if not hasattr(self, '_last_tracked_level') or self._last_tracked_level != self.last_concrete_level:
                self.logger.debug(f"Using tracked concrete level for GMAP mode: {self.last_concrete_level}")
                self._last_tracked_level = self.last_concrete_level
            return self.last_concrete_level
        
        # 🎯 STRATEGY 1: If we have a concrete level name (not .gmap), use it
        if self.current_level_name and not self.current_level_name.endswith('.gmap'):
            self.logger.debug(f"Using concrete level name: {self.current_level_name}")
            return self.current_level_name
            
        # 🎯 STRATEGY 2: If current level is .gmap, try coordinate-based resolution
        if not self.gmap_manager.is_gmap_mode():
            return self.current_level_name
            
        # Try to get resolved level name from GMAP manager
        resolved_name = self.gmap_manager.get_effective_level_name()
        if resolved_name:
            self.logger.debug(f"Using GMAP resolved level: {resolved_name}")
            return resolved_name
            
        # Try to resolve using current player position
        player = self.player.get_player()
        if player and hasattr(player, 'x2') and player.x2 is not None:
            # Use world coordinates to resolve level name
            gmap_name = self.current_level_name if self.current_level_name and self.current_level_name.endswith('.gmap') else None
            if gmap_name:
                resolved_name = self.gmap_manager.update_world_position(player.x2, player.y2, gmap_name)
                if resolved_name:
                    self.logger.info(f"✅ Session manager resolved GMAP level: {resolved_name}")
                    return resolved_name
                        
        # Final fallback: return raw level name (might be GMAP filename)
        self.logger.debug(f"Using fallback level name: {self.current_level_name}")
        return self.current_level_name
        
    def update_player_coordinates(self, world_x: float, world_y: float, 
                                 segment_x: int = None, segment_y: int = None):
        """Update player coordinates and resolve GMAP level if applicable.
        
        Args:
            world_x: World X coordinate in tiles
            world_y: World Y coordinate in tiles
            segment_x: GMAP segment X (from GMAP packet - authoritative)
            segment_y: GMAP segment Y (from GMAP packet - authoritative)
        """
        if not GMAP_AVAILABLE or not self.gmap_manager:
            return
            
        # Check if we should enter GMAP mode
        # 🎯 FIXED: Use segment data presence to detect GMAP mode instead of level name
        # This fixes race condition where GMAP warp is processed before level name is set
        is_gmap_level = (self.current_level_name and 
                        self.current_level_name.endswith('.gmap'))
        has_segment_data = (segment_x is not None and segment_y is not None)
        
        if has_segment_data:
            # 🎯 Use segment data from GMAP packet to resolve level name
            self.logger.info(f"🗺️ Using GMAP segment data: ({segment_x},{segment_y})")
            
            # Handle case where level name is not set yet (race condition)
            gmap_name = self.current_level_name
            if not gmap_name:
                # Try to infer GMAP name from the context or use a default
                gmap_name = "chicken.gmap"  # Common GMAP for this server
                self.logger.info(f"🔧 Level name not set yet, assuming GMAP: {gmap_name}")
            
            # 🎯 FIX: Ensure GMAP structure is loaded before resolution
            if hasattr(self.gmap_manager, 'check_and_parse_downloaded_gmap_file'):
                self.gmap_manager.check_and_parse_downloaded_gmap_file(gmap_name)
            
            resolved_name = self.gmap_manager.resolver.resolve_level_from_segment(
                gmap_name, segment_x, segment_y
            )
            
            if resolved_name:
                # Store the resolved level as our tracked concrete level
                self.last_concrete_level = resolved_name
                self.logger.info(f"✅ GMAP segment resolution: segment({segment_x},{segment_y}) -> {resolved_name}")
                
                # 🎯 CRITICAL FIX: Activate GMAP mode BEFORE updating coordinates
                if not self.gmap_manager.is_gmap_mode():
                    self.gmap_manager.gmap_mode = True
                    self.gmap_manager.enabled = True
                    self.logger.info(f"🔧 Activated GMAP mode from coordinate update")
                
                # Also update GMAP manager state
                self.gmap_manager.resolved_level_name = resolved_name
                self.gmap_manager.current_world_x = world_x
                self.gmap_manager.current_world_y = world_y
                
            else:
                self.logger.warning(f"❌ Could not resolve GMAP segment ({segment_x},{segment_y})")
        elif is_gmap_level:
            # Update position in existing GMAP mode
            self.gmap_manager.update_world_position(world_x, world_y, self.current_level_name)
        else:
            # Not in GMAP mode, disable if was previously enabled
            if self.gmap_manager.is_gmap_mode():
                self.gmap_manager.disable_gmap()
                self.logger.info("🏠 Exited GMAP mode")
                
    def get_coordinate_info(self) -> Optional[CoordinateSet]:
        """Get comprehensive coordinate information for current player position.
        
        Returns:
            CoordinateSet with current position information
        """
        if not GMAP_AVAILABLE:
            return None
            
        player = self.player.get_player()
        if not player:
            return None
            
        # Check if we have world coordinates (GMAP mode)
        if hasattr(player, 'x2') and player.x2 is not None:
            return CoordinateHelpers.create_coordinate_set(
                world_x=player.x2,
                world_y=player.y2,
                is_gmap=self.gmap_manager.is_gmap_mode() if self.gmap_manager else False,
                level_name=self.get_effective_level_name()
            )
        else:
            # Single level mode
            return CoordinateHelpers.create_coordinate_set(
                world_x=player.x,
                world_y=player.y,
                is_gmap=False,
                level_name=self.current_level_name
            )
            
    def is_gmap_mode(self) -> bool:
        """Check if currently in GMAP mode."""
        return (self.gmap_manager and 
               self.gmap_manager.is_gmap_mode() if GMAP_AVAILABLE else False)
               
    def _change_state(self, new_state: SessionState):
        """Internal method to change session state"""
        if self.state != new_state:
            old_state = self.state
            self.state = new_state
            self.logger.debug(f"Session state changed: {old_state.value} -> {new_state.value}")
            
            if self._state_change_callback:
                self._state_change_callback(old_state, new_state)