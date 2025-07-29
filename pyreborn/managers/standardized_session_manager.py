"""
Standardized Session Manager - Implements ISessionManager interface
"""

import time
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from ..core.interfaces import ISessionManager
from ..config.client_config import ClientConfig
from ..core.events import EventManager, EventType
from ..models.player import Player
from ..models.level import Level


@dataclass
class PrivateMessage:
    """Represents a private message"""
    timestamp: float
    from_player_id: int
    to_player_id: int
    message: str
    from_name: Optional[str] = None
    to_name: Optional[str] = None


@dataclass
class ChatMessage:
    """Represents a public chat message"""
    timestamp: float
    player_id: int
    message: str
    level: Optional[str] = None
    player_name: Optional[str] = None


@dataclass
class LevelSession:
    """Tracks state for a specific level"""
    level: Level
    entered_time: float
    players_seen: Dict[int, Player] = field(default_factory=dict)
    chat_history: List[ChatMessage] = field(default_factory=list)
    events: List[str] = field(default_factory=list)
    
    def add_event(self, event: str):
        """Add an event to the level history"""
        self.events.append(f"[{time.strftime('%H:%M:%S')}] {event}")
        if len(self.events) > 100:
            self.events = self.events[-100:]


class StandardizedSessionManager(ISessionManager):
    """Standardized session manager implementing ISessionManager interface"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.config: Optional[ClientConfig] = None
        self.events: Optional[EventManager] = None
        
        # Core session state
        self._local_player: Optional[Player] = None
        self._logged_in = False
        
        # Session tracking
        self._session_start_time: Optional[float] = None
        self._players: Dict[int, Player] = {}
        self._level_sessions: Dict[str, LevelSession] = {}
        self._current_level_name: Optional[str] = None
        
        # Communication history
        self._private_messages: List[PrivateMessage] = []
        self._chat_history: List[ChatMessage] = []
        
        # Session statistics
        self._stats = {
            'levels_visited': 0,
            'messages_sent': 0,
            'messages_received': 0,
            'players_encountered': 0
        }
        
    def initialize(self, config: ClientConfig, event_manager: EventManager) -> None:
        """Initialize the session manager"""
        self.config = config
        self.events = event_manager
        
        # Subscribe to relevant events
        self.events.subscribe(EventType.LOGIN_SUCCESS, self._on_login_success)
        self.events.subscribe(EventType.DISCONNECTED, self._on_disconnected)
        self.events.subscribe(EventType.LEVEL_ENTERED, self._on_level_entered)
        self.events.subscribe(EventType.CHAT_MESSAGE, self._on_chat_message)
        self.events.subscribe(EventType.PRIVATE_MESSAGE, self._on_private_message)
        self.events.subscribe(EventType.PLAYER_ADDED, self._on_player_added)
        
        self.logger.debug("Session manager initialized")
        
    def cleanup(self) -> None:
        """Clean up session resources"""
        if self.events:
            self.events.unsubscribe(EventType.LOGIN_SUCCESS, self._on_login_success)
            self.events.unsubscribe(EventType.DISCONNECTED, self._on_disconnected)
            self.events.unsubscribe(EventType.LEVEL_ENTERED, self._on_level_entered)
            self.events.unsubscribe(EventType.CHAT_MESSAGE, self._on_chat_message)
            self.events.unsubscribe(EventType.PRIVATE_MESSAGE, self._on_private_message)
            self.events.unsubscribe(EventType.PLAYER_ADDED, self._on_player_added)
        
        self._reset_session()
        
    @property
    def name(self) -> str:
        """Manager name"""
        return "standardized_session_manager"
    
    def get_player(self) -> Optional[Player]:
        """Get current player object"""
        return self._local_player
    
    def set_player(self, player: Player) -> None:
        """Set current player object"""
        self._local_player = player
        if player:
            player.is_local = True
        self.logger.debug(f"Local player set: {getattr(player, 'nickname', None) if player else None}")
    
    def is_logged_in(self) -> bool:
        """Check if player is logged in"""
        return self._logged_in and self._local_player is not None
    
    # Extended session management methods
    def start_session(self) -> None:
        """Start a new session"""
        self._session_start_time = time.time()
        self._reset_session_data()
        self.logger.info("Session started")
    
    def end_session(self) -> None:
        """End current session"""
        if self._session_start_time:
            duration = time.time() - self._session_start_time
            self.logger.info(f"Session ended. Duration: {duration:.1f}s")
        
        self._reset_session()
    
    def get_session_duration(self) -> Optional[float]:
        """Get current session duration in seconds"""
        if self._session_start_time:
            return time.time() - self._session_start_time
        return None
    
    def get_player_by_id(self, player_id: int) -> Optional[Player]:
        """Get player by ID"""
        return self._players.get(player_id)
    
    def add_player(self, player: Player) -> None:
        """Add a player to the session"""
        if player.player_id not in self._players:
            self._stats['players_encountered'] += 1
        
        self._players[player.player_id] = player
        
        # Add to current level session if available
        if self._current_level_name and self._current_level_name in self._level_sessions:
            self._level_sessions[self._current_level_name].players_seen[player.player_id] = player
    
    def remove_player(self, player_id: int) -> Optional[Player]:
        """Remove a player from the session"""
        return self._players.pop(player_id, None)
    
    def get_all_players(self) -> Dict[int, Player]:
        """Get all players in session"""
        return self._players.copy()
    
    def get_current_level_session(self) -> Optional[LevelSession]:
        """Get current level session"""
        if self._current_level_name:
            return self._level_sessions.get(self._current_level_name)
        return None
    
    def get_level_session(self, level_name: str) -> Optional[LevelSession]:
        """Get specific level session"""
        return self._level_sessions.get(level_name)
    
    def get_all_level_sessions(self) -> Dict[str, LevelSession]:
        """Get all level sessions"""
        return self._level_sessions.copy()
    
    def add_private_message(self, from_id: int, to_id: int, message: str,
                           from_name: str = None, to_name: str = None) -> None:
        """Add a private message to history"""
        pm = PrivateMessage(
            timestamp=time.time(),
            from_player_id=from_id,
            to_player_id=to_id,
            message=message,
            from_name=from_name,
            to_name=to_name
        )
        
        self._private_messages.append(pm)
        self._stats['messages_received'] += 1
        
        # Keep only last 1000 messages
        if len(self._private_messages) > 1000:
            self._private_messages = self._private_messages[-1000:]
    
    def add_chat_message(self, player_id: int, message: str, 
                        level: str = None, player_name: str = None) -> None:
        """Add a chat message to history"""
        chat_msg = ChatMessage(
            timestamp=time.time(),
            player_id=player_id,
            message=message,
            level=level or self._current_level_name,
            player_name=player_name
        )
        
        self._chat_history.append(chat_msg)
        
        # Add to level session
        if chat_msg.level and chat_msg.level in self._level_sessions:
            self._level_sessions[chat_msg.level].chat_history.append(chat_msg)
        
        # Keep only last 1000 messages
        if len(self._chat_history) > 1000:
            self._chat_history = self._chat_history[-1000:]
    
    def get_private_messages(self, limit: int = None) -> List[PrivateMessage]:
        """Get private message history"""
        if limit:
            return self._private_messages[-limit:]
        return self._private_messages.copy()
    
    def get_chat_history(self, level: str = None, limit: int = None) -> List[ChatMessage]:
        """Get chat message history"""
        if level:
            level_session = self._level_sessions.get(level)
            if level_session:
                history = level_session.chat_history
                if limit:
                    return history[-limit:]
                return history.copy()
            return []
        else:
            if limit:
                return self._chat_history[-limit:]
            return self._chat_history.copy()
    
    def get_session_stats(self) -> Dict[str, Any]:
        """Get session statistics"""
        stats = self._stats.copy()
        stats.update({
            'session_duration': self.get_session_duration(),
            'total_players': len(self._players),
            'levels_in_session': len(self._level_sessions),
            'total_private_messages': len(self._private_messages),
            'total_chat_messages': len(self._chat_history),
            'current_level': self._current_level_name
        })
        return stats
    
    def _reset_session(self) -> None:
        """Reset all session data"""
        self._local_player = None
        self._logged_in = False
        self._session_start_time = None
        self._reset_session_data()
    
    def _reset_session_data(self) -> None:
        """Reset session data but keep login state"""
        self._players.clear()
        self._level_sessions.clear()
        self._current_level_name = None
        self._private_messages.clear()
        self._chat_history.clear()
        self._stats = {
            'levels_visited': 0,
            'messages_sent': 0,
            'messages_received': 0,
            'players_encountered': 0
        }
    
    # Event handlers
    def _on_login_success(self, event) -> None:
        """Handle successful login"""
        self._logged_in = True
        self.start_session()
        
        player = event.data.get('player')
        if player:
            self.set_player(player)
    
    def _on_disconnected(self, event) -> None:
        """Handle disconnection"""
        self.end_session()
    
    def _on_level_entered(self, event) -> None:
        """Handle level entry"""
        level_name = event.data.get('level_name')
        level_obj = event.data.get('level')
        
        if level_name:
            self._current_level_name = level_name
            
            if level_name not in self._level_sessions and level_obj:
                self._level_sessions[level_name] = LevelSession(
                    level=level_obj,
                    entered_time=time.time()
                )
                self._stats['levels_visited'] += 1
                
                self.logger.debug(f"Entered level: {level_name}")
    
    def _on_chat_message(self, event) -> None:
        """Handle chat message"""
        player_id = event.data.get('player_id', 0)
        message = event.data.get('message', '')
        player_name = event.data.get('player_name')
        
        self.add_chat_message(player_id, message, player_name=player_name)
    
    def _on_private_message(self, event) -> None:
        """Handle private message"""
        from_id = event.data.get('from_id', 0)
        to_id = event.data.get('to_id', 0)
        message = event.data.get('message', '')
        from_name = event.data.get('from_name')
        to_name = event.data.get('to_name')
        
        self.add_private_message(from_id, to_id, message, from_name, to_name)
    
    def _on_player_added(self, event) -> None:
        """Handle player added to level"""
        player = event.data.get('player')
        if player:
            self.add_player(player)