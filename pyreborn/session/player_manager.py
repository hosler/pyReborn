"""
Player Manager - Player data and state management

Handles all player-related data:
- Local player state
- Player properties and attributes
- Player authentication data
- Player status and presence
"""

import time
import logging
from typing import Optional, Dict, Any

from .session_state import PlayerStatus


class PlayerManager:
    """Manages player data and state"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Player identification
        self.player_id: Optional[int] = None
        self.account: Optional[str] = None
        self.nickname: Optional[str] = None
        
        # Authentication data
        self.password: Optional[str] = None
        self.session_token: Optional[str] = None
        self.login_time: Optional[float] = None
        
        # Player state
        self.status = PlayerStatus.OFFLINE
        self.last_activity: float = time.time()
        
        # Game properties
        self.properties: Dict[str, Any] = {}
        self.flags: Dict[str, str] = {}
        
        # Position and movement
        self.x: float = 0.0
        self.y: float = 0.0
        self.level: Optional[str] = None
        self.direction: int = 0
        
        # Stats and attributes
        self.health: int = 100
        self.hearts: float = 3.0
        self.ap: int = 50
        self.alignment: int = 0
        
        # Equipment and inventory
        self.head: Optional[str] = None
        self.body: Optional[str] = None
        self.sword: Optional[str] = None
        self.shield: Optional[str] = None
        
        # Administrative
        self.rights: int = 0
        self.is_staff: bool = False
        self.guild: Optional[str] = None
        
    def set_login_data(self, account: str, password: str):
        """Set login credentials"""
        self.account = account
        self.password = password
        self.login_time = time.time()
        
    def set_player_id(self, player_id: int):
        """Set player ID after successful login"""
        self.player_id = player_id
        self.logger.info(f"Player ID set to: {player_id}")
    
    def get_player(self):
        """Get player data as a simple object"""
        from ..models import Player
        player = Player(player_id=self.player_id or -1)
        
        # Set the properties individually
        player.account = self.account or ""
        player.nickname = self.nickname or ""
        player._x = self.x
        player._y = self.y
        player.level = self.level or ""
        player.status = self.status.value if hasattr(self.status, 'value') else self.status
        
        # Set other properties we track
        player.hearts = self.hearts
        player.ap = self.ap
        player.apcount = self.ap  # Set both ap and apcount
        player.head = self.head
        player.body = self.body
        player.sword = self.sword
        player.shield = self.shield
        
        return player
        
    def update_position(self, x: float, y: float, level: Optional[str] = None):
        """Update player position"""
        self.x = x
        self.y = y
        if level is not None:
            self.level = level
        self.last_activity = time.time()
        
    def update_property(self, prop_name: str, value: Any):
        """Update a player property"""
        self.properties[prop_name] = value
        self.last_activity = time.time()
        
        # Update specific attributes for common properties
        prop_name_lower = prop_name.lower()
        if prop_name_lower == 'nickname':
            self.nickname = str(value)
        elif prop_name_lower == 'account':
            self.account = str(value)
        elif prop_name_lower == 'health':
            self.health = int(value)
        elif prop_name_lower == 'hearts':
            self.hearts = float(value)
        elif prop_name_lower in ['ap', 'apcount']:
            self.ap = int(value)
        elif prop_name_lower == 'head':
            self.head = str(value) if value else None
        elif prop_name_lower == 'body':
            self.body = str(value) if value else None
        elif prop_name_lower == 'sword':
            self.sword = str(value) if value else None
        elif prop_name_lower == 'shield':
            self.shield = str(value) if value else None
            
    def set_flag(self, name: str, value: str):
        """Set a player flag"""
        self.flags[name] = value
        self.last_activity = time.time()
        
    def get_flag(self, name: str, default: str = "") -> str:
        """Get a player flag value"""
        return self.flags.get(name, default)
        
    def set_status(self, status: PlayerStatus):
        """Update player status"""
        if self.status != status:
            self.logger.debug(f"Player status changed: {self.status} -> {status}")
            self.status = status
            self.last_activity = time.time()
    
    def is_authenticated(self) -> bool:
        """Check if player is authenticated"""
        return self.player_id is not None and self.account is not None
    
    def get_display_name(self) -> str:
        """Get the display name for the player"""
        return self.nickname or self.account or f"Player#{self.player_id}"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert player data to dictionary"""
        return {
            'player_id': self.player_id,
            'account': self.account,
            'nickname': self.nickname,
            'status': self.status.value,
            'x': self.x,
            'y': self.y,
            'level': self.level,
            'health': self.health,
            'hearts': self.hearts,
            'ap': self.ap,
            'properties': self.properties.copy(),
            'flags': self.flags.copy(),
        }
    
    def reset(self):
        """Reset all player data (for logout)"""
        self.player_id = None
        self.account = None
        self.nickname = None
        self.password = None
        self.session_token = None
        self.login_time = None
        self.status = PlayerStatus.OFFLINE
        self.properties.clear()
        self.flags.clear()
        self.x = 0.0
        self.y = 0.0
        self.level = None
        self.health = 100
        self.hearts = 3.0
        self.ap = 50