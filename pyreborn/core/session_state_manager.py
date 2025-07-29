"""
Session State Manager - Handles login, authentication, and session state
"""

import logging
import time
from typing import Optional, Dict, Any
from enum import Enum

from ..config.client_config import ClientConfig
from ..core.events import EventManager, EventType
from ..core.interfaces import IManager
from ..models.player import Player
from ..protocol.packets import LoginPacket


class SessionState(Enum):
    """Session state enumeration"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    AUTHENTICATING = "authenticating"
    AUTHENTICATED = "authenticated"
    LOGIN_FAILED = "login_failed"
    ACTIVE = "active"


class SessionStateManager(IManager):
    """Manages session state, authentication, and login process"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.config: Optional[ClientConfig] = None
        self.events: Optional[EventManager] = None
        
        # Session state
        self.state = SessionState.DISCONNECTED
        self.local_player: Optional[Player] = None
        self.session_data: Dict[str, Any] = {}
        
        # Authentication
        self.username: Optional[str] = None
        self.password: Optional[str] = None
        self.login_success = False
        self.login_start_time: Optional[float] = None
        
        # Timeouts
        self.login_timeout = 15.0  # Default timeout
        
    def initialize(self, config: ClientConfig, event_manager: EventManager) -> None:
        """Initialize with configuration and event system"""
        self.config = config
        self.events = event_manager
        self.login_timeout = config.login_timeout
        
        # Subscribe to relevant events
        self.events.subscribe(EventType.CONNECTED, self._on_connected)
        self.events.subscribe(EventType.DISCONNECTED, self._on_disconnected)
        self.events.subscribe(EventType.LOGIN_ACCEPTED, self._on_login_accepted)
        
    def cleanup(self) -> None:
        """Clean up resources"""
        if self.events:
            self.events.unsubscribe(EventType.CONNECTED, self._on_connected)
            self.events.unsubscribe(EventType.DISCONNECTED, self._on_disconnected)
            self.events.unsubscribe(EventType.LOGIN_ACCEPTED, self._on_login_accepted)
        
        self.reset_session()
        
    @property
    def name(self) -> str:
        """Manager name"""
        return "session_state_manager"
    
    def set_credentials(self, username: str, password: str) -> None:
        """Set login credentials"""
        self.username = username
        self.password = password
        
    def start_login(self, connection_manager) -> bool:
        """Start the login process"""
        if not self.username or not self.password:
            self.logger.error("Cannot login: no credentials set")
            return False
            
        if self.state != SessionState.CONNECTED:
            self.logger.error(f"Cannot login: invalid state {self.state}")
            return False
        
        try:
            self.logger.info(f"Starting login for user: {self.username}")
            self.state = SessionState.AUTHENTICATING
            self.login_start_time = time.time()
            
            # Create and send login packet
            login_packet = LoginPacket(
                account=self.username,
                password=self.password,
                encryption_key=123  # Default encryption key for testing
            )
            
            packet_data = login_packet.to_bytes()
            
            if connection_manager.send_packet(packet_data):
                self.logger.debug("Login packet sent")
                
                # Emit login attempt event
                if self.events:
                    self.events.emit(EventType.LOGIN_ACCEPTED, username=self.username)
                
                return True
            else:
                self.logger.error("Failed to send login packet")
                self.state = SessionState.LOGIN_FAILED
                return False
                
        except Exception as e:
            self.logger.error(f"Login failed: {e}")
            self.state = SessionState.LOGIN_FAILED
            
            if self.events:
                self.events.emit(EventType.LOGIN_FAILED, error=str(e))
            
            return False
    
    def handle_login_response(self, response_type: str, data: Dict[str, Any] = None) -> None:
        """Handle login response from server"""
        if self.state != SessionState.AUTHENTICATING:
            self.logger.warning(f"Received login response in wrong state: {self.state}")
            return
        
        if response_type == "success":
            self.login_success = True
            self.state = SessionState.AUTHENTICATED
            
            self.logger.info("Login successful")
            
            # Initialize local player
            self.local_player = Player()
            self.local_player.is_local = True
            
            if data:
                # Set any initial player data from login response
                for key, value in data.items():
                    setattr(self.local_player, key, value)
            
            # Store session data
            self.session_data.update({
                'login_time': time.time(),
                'username': self.username,
                'login_duration': time.time() - (self.login_start_time or 0)
            })
            
            if self.events:
                self.events.emit(EventType.LOGIN_SUCCESS, 
                               username=self.username,
                               player=self.local_player,
                               session_data=self.session_data.copy())
            
            # Transition to active state
            self.state = SessionState.ACTIVE
            
        elif response_type == "failed":
            self.login_success = False
            self.state = SessionState.LOGIN_FAILED
            
            error_msg = data.get('error', 'Unknown login error') if data else 'Login failed'
            self.logger.error(f"Login failed: {error_msg}")
            
            if self.events:
                self.events.emit(EventType.LOGIN_FAILED, error=error_msg)
    
    def check_login_timeout(self) -> bool:
        """Check if login has timed out"""
        if (self.state == SessionState.AUTHENTICATING and 
            self.login_start_time and 
            time.time() - self.login_start_time > self.login_timeout):
            
            self.logger.error("Login timed out")
            self.state = SessionState.LOGIN_FAILED
            
            if self.events:
                self.events.emit(EventType.LOGIN_FAILED, error="Login timeout")
            
            return True
        
        return False
    
    def get_player(self) -> Optional[Player]:
        """Get current player object"""
        return self.local_player
    
    def set_player(self, player: Player) -> None:
        """Set current player object"""
        self.local_player = player
        if player:
            player.is_local = True
    
    def is_logged_in(self) -> bool:
        """Check if player is logged in"""
        return self.login_success and self.state in [SessionState.AUTHENTICATED, SessionState.ACTIVE]
    
    def is_active(self) -> bool:
        """Check if session is active"""
        return self.state == SessionState.ACTIVE
    
    def get_session_data(self) -> Dict[str, Any]:
        """Get session data"""
        return self.session_data.copy()
    
    def update_session_data(self, key: str, value: Any) -> None:
        """Update session data"""
        self.session_data[key] = value
    
    def get_state(self) -> SessionState:
        """Get current session state"""
        return self.state
    
    def reset_session(self) -> None:
        """Reset session to initial state"""
        self.state = SessionState.DISCONNECTED
        self.login_success = False
        self.login_start_time = None
        self.local_player = None
        self.session_data.clear()
        
        self.logger.debug("Session reset")
    
    def _on_connected(self, event) -> None:
        """Handle connection established"""
        self.state = SessionState.CONNECTED
        self.logger.debug("Session state: connected")
    
    def _on_disconnected(self, event) -> None:
        """Handle disconnection"""
        old_state = self.state
        self.reset_session()
        
        if old_state != SessionState.DISCONNECTED:
            self.logger.info("Session ended due to disconnection")
    
    def _on_login_accepted(self, event) -> None:
        """Handle login accepted from protocol processor"""
        if self.state == SessionState.AUTHENTICATING:
            self.handle_login_response("success", event.data if hasattr(event, 'data') else {})
    
    def get_login_duration(self) -> Optional[float]:
        """Get time taken for login process"""
        return self.session_data.get('login_duration')
    
    def get_session_duration(self) -> Optional[float]:
        """Get total session duration"""
        login_time = self.session_data.get('login_time')
        if login_time:
            return time.time() - login_time
        return None