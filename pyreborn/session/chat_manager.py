"""
Chat Manager - Consolidated chat and messaging functionality

Handles all forms of communication:
- Public chat messages
- Private messages
- System messages
- Chat history and filtering
"""

import time
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict, deque


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
class SystemMessage:
    """Represents a system message"""
    timestamp: float
    message: str
    message_type: str = "info"  # info, warning, error


class ChatManager:
    """Manages all chat and messaging functionality"""
    
    def __init__(self, max_history: int = 1000):
        self.logger = logging.getLogger(__name__)
        self.max_history = max_history
        
        # Message history
        self.chat_history: deque = deque(maxlen=max_history)
        self.private_messages: deque = deque(maxlen=max_history)
        self.system_messages: deque = deque(maxlen=max_history)
        
        # Active conversations
        self.conversations: Dict[int, List[PrivateMessage]] = defaultdict(list)
        
        # Chat state
        self.chat_enabled = True
        self.blocked_players: set = set()
        
    def add_chat_message(self, player_id: int, message: str, 
                        level: Optional[str] = None, player_name: Optional[str] = None):
        """Add a public chat message"""
        msg = ChatMessage(
            timestamp=time.time(),
            player_id=player_id,
            message=message,
            level=level,
            player_name=player_name
        )
        self.chat_history.append(msg)
        self.logger.debug(f"Chat: {player_name or player_id}: {message}")
    
    def add_private_message(self, from_player_id: int, to_player_id: int, 
                           message: str, from_name: Optional[str] = None, 
                           to_name: Optional[str] = None):
        """Add a private message"""
        msg = PrivateMessage(
            timestamp=time.time(),
            from_player_id=from_player_id,
            to_player_id=to_player_id,
            message=message,
            from_name=from_name,
            to_name=to_name
        )
        self.private_messages.append(msg)
        self.conversations[from_player_id].append(msg)
        self.logger.debug(f"PM from {from_name or from_player_id} to {to_name or to_player_id}: {message}")
    
    def add_system_message(self, message: str, message_type: str = "info"):
        """Add a system message"""
        msg = SystemMessage(
            timestamp=time.time(),
            message=message,
            message_type=message_type
        )
        self.system_messages.append(msg)
        self.logger.info(f"System [{message_type}]: {message}")
    
    def get_chat_history(self, limit: int = 50) -> List[ChatMessage]:
        """Get recent chat history"""
        return list(self.chat_history)[-limit:]
    
    def get_private_messages(self, limit: int = 50) -> List[PrivateMessage]:
        """Get recent private messages"""
        return list(self.private_messages)[-limit:]
    
    def get_conversation(self, player_id: int) -> List[PrivateMessage]:
        """Get conversation with specific player"""
        return self.conversations.get(player_id, [])
    
    def block_player(self, player_id: int):
        """Block a player from sending messages"""
        self.blocked_players.add(player_id)
        
    def unblock_player(self, player_id: int):
        """Unblock a player"""
        self.blocked_players.discard(player_id)
    
    def is_player_blocked(self, player_id: int) -> bool:
        """Check if player is blocked"""
        return player_id in self.blocked_players
    
    def clear_history(self):
        """Clear all chat history"""
        self.chat_history.clear()
        self.private_messages.clear()
        self.system_messages.clear()
        self.conversations.clear()