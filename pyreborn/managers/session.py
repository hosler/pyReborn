"""
Session manager for tracking game state, conversations, and player context
"""

import time
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from collections import defaultdict
from ..models.player import Player
from ..models.level import Level, Sign, Chest, NPC, Baddy
from ..protocol.enums import PlayerProp

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
        # Keep only last 100 events
        if len(self.events) > 100:
            self.events = self.events[-100:]

class SessionManager:
    """Manages game session state, conversations, and context"""
    
    def __init__(self):
        # Player tracking
        self.local_player: Optional[Player] = None
        self.all_players: Dict[int, Player] = {}
        
        # Level tracking
        self.current_level: Optional[Level] = None
        self.level_sessions: Dict[str, LevelSession] = {}
        self.level_history: List[Tuple[str, float]] = []  # (level_name, enter_time)
        
        # Communication tracking
        self.pm_conversations: Dict[int, List[PrivateMessage]] = defaultdict(list)
        self.global_chat_history: List[ChatMessage] = []
        
        # Session statistics
        self.session_start_time = time.time()
        self.total_packets_received = 0
        self.total_players_seen = set()
        self.levels_visited = set()
        
        # Game state
        self.server_flags: Dict[str, str] = {}
        self.inventory_changes: List[Tuple[float, str, Any]] = []  # (time, property, value)
        
    def set_local_player(self, player: Player):
        """Set the local player"""
        self.local_player = player
        
    def update_player(self, player: Player):
        """Update or add a player"""
        self.all_players[player.id] = player
        self.total_players_seen.add(player.id)
        
        # Add to current level session
        if self.current_level and player.id != getattr(self.local_player, 'id', -1):
            current_session = self.get_or_create_level_session(self.current_level.name)
            current_session.players_seen[player.id] = player
            
    def remove_player(self, player_id: int):
        """Remove a player"""
        if player_id in self.all_players:
            player = self.all_players[player_id]
            del self.all_players[player_id]
            
            # Log to current level
            if self.current_level:
                session = self.get_or_create_level_session(self.current_level.name)
                session.add_event(f"Player left: {player.nickname or f'ID:{player_id}'}")
    
    def enter_level(self, level: Level):
        """Enter a new level"""
        # Record leaving previous level
        if self.current_level:
            self.leave_level()
            
        # Enter new level
        self.current_level = level
        self.levels_visited.add(level.name)
        
        # Track level history
        enter_time = time.time()
        self.level_history.append((level.name, enter_time))
        
        # Get or create level session
        session = self.get_or_create_level_session(level.name)
        session.entered_time = enter_time
        session.add_event(f"Entered level: {level.name}")
        
    def leave_level(self):
        """Leave current level"""
        if self.current_level:
            session = self.get_or_create_level_session(self.current_level.name)
            duration = time.time() - session.entered_time
            session.add_event(f"Left level after {duration:.1f} seconds")
            
    def get_or_create_level_session(self, level_name: str) -> LevelSession:
        """Get or create a level session"""
        if level_name not in self.level_sessions:
            level = Level(level_name)
            self.level_sessions[level_name] = LevelSession(
                level=level,
                entered_time=time.time()
            )
        return self.level_sessions[level_name]
        
    def add_chat_message(self, player_id: int, message: str, level_name: Optional[str] = None):
        """Add a chat message"""
        player_name = None
        if player_id in self.all_players:
            player_name = self.all_players[player_id].nickname
            
        chat_msg = ChatMessage(
            timestamp=time.time(),
            player_id=player_id,
            message=message,
            level=level_name or (self.current_level.name if self.current_level else None),
            player_name=player_name
        )
        
        # Add to global history
        self.global_chat_history.append(chat_msg)
        if len(self.global_chat_history) > 200:
            self.global_chat_history = self.global_chat_history[-200:]
            
        # Add to level session
        if self.current_level:
            session = self.get_or_create_level_session(self.current_level.name)
            session.chat_history.append(chat_msg)
            if len(session.chat_history) > 50:
                session.chat_history = session.chat_history[-50:]
                
    def add_private_message(self, from_player_id: int, to_player_id: int, message: str):
        """Add a private message"""
        from_name = None
        to_name = None
        
        if from_player_id in self.all_players:
            from_name = self.all_players[from_player_id].nickname
        if to_player_id in self.all_players:
            to_name = self.all_players[to_player_id].nickname
            
        pm = PrivateMessage(
            timestamp=time.time(),
            from_player_id=from_player_id,
            to_player_id=to_player_id,
            message=message,
            from_name=from_name,
            to_name=to_name
        )
        
        # Add to both participants' conversation history
        self.pm_conversations[from_player_id].append(pm)
        if from_player_id != to_player_id:
            self.pm_conversations[to_player_id].append(pm)
            
        # Keep only last 50 messages per conversation
        for player_id in [from_player_id, to_player_id]:
            if len(self.pm_conversations[player_id]) > 50:
                self.pm_conversations[player_id] = self.pm_conversations[player_id][-50:]
                
    def track_inventory_change(self, property_name: str, value: Any):
        """Track inventory/stat changes"""
        self.inventory_changes.append((time.time(), property_name, value))
        # Keep only last 100 changes
        if len(self.inventory_changes) > 100:
            self.inventory_changes = self.inventory_changes[-100:]
            
    def increment_packet_count(self):
        """Increment packet counter"""
        self.total_packets_received += 1
        
    # Query methods
    def get_current_level_players(self) -> List[Player]:
        """Get all players in current level"""
        if not self.current_level:
            return []
        return list(self.current_level.players.values())
        
    def get_conversation_with(self, player_id: int) -> List[PrivateMessage]:
        """Get PM conversation with a specific player"""
        return self.pm_conversations.get(player_id, [])
        
    def get_recent_chat(self, level_name: Optional[str] = None, limit: int = 10) -> List[ChatMessage]:
        """Get recent chat messages"""
        if level_name and level_name in self.level_sessions:
            return self.level_sessions[level_name].chat_history[-limit:]
        return self.global_chat_history[-limit:]
        
    def get_level_session_info(self, level_name: str) -> Optional[Dict[str, Any]]:
        """Get information about a level session"""
        if level_name not in self.level_sessions:
            return None
            
        session = self.level_sessions[level_name]
        return {
            "level_name": level_name,
            "total_time": time.time() - session.entered_time,
            "players_seen": len(session.players_seen),
            "chat_messages": len(session.chat_history),
            "events": len(session.events),
            "last_events": session.events[-5:] if session.events else []
        }
        
    def get_session_summary(self) -> Dict[str, Any]:
        """Get overall session summary"""
        session_duration = time.time() - self.session_start_time
        
        return {
            "session_duration": session_duration,
            "total_packets": self.total_packets_received,
            "total_players_seen": len(self.total_players_seen),
            "levels_visited": len(self.levels_visited),
            "current_level": self.current_level.name if self.current_level else None,
            "pm_conversations": len(self.pm_conversations),
            "total_chat_messages": len(self.global_chat_history),
            "current_players": len(self.all_players),
            "inventory_changes": len(self.inventory_changes)
        }
        
    def get_player_stats(self, player_id: int) -> Optional[Dict[str, Any]]:
        """Get stats for a specific player"""
        if player_id not in self.all_players:
            return None
            
        player = self.all_players[player_id]
        
        # Count messages from this player
        chat_count = sum(1 for msg in self.global_chat_history if msg.player_id == player_id)
        pm_count = len(self.pm_conversations.get(player_id, []))
        
        return {
            "player_id": player_id,
            "nickname": player.nickname,
            "account": player.account,
            "position": (player.x, player.y),
            "level": player.level,
            "chat_messages": chat_count,
            "pm_messages": pm_count,
            "stats": {
                "hearts": player.hearts,
                "rupees": player.rupees,
                "arrows": player.arrows,
                "bombs": player.bombs
            }
        }
        
    def find_players_by_name(self, name: str) -> List[Player]:
        """Find players by nickname (fuzzy search)"""
        matches = []
        name_lower = name.lower()
        
        for player in self.all_players.values():
            if player.nickname and name_lower in player.nickname.lower():
                matches.append(player)
                
        return matches
        
    def get_level_visit_history(self) -> List[Tuple[str, float, float]]:
        """Get level visit history with durations"""
        history = []
        
        for i, (level_name, enter_time) in enumerate(self.level_history):
            if i + 1 < len(self.level_history):
                # Use next level's enter time as leave time
                leave_time = self.level_history[i + 1][1]
                duration = leave_time - enter_time
            else:
                # Current level - use current time
                duration = time.time() - enter_time
                
            history.append((level_name, enter_time, duration))
            
        return history
    
    # Level management integration
    def add_level_event(self, level_name: str, event: str):
        """Add an event to a specific level's history"""
        session = self.get_or_create_level_session(level_name)
        session.add_event(event)
    
    def log_tile_update(self, level_name: str, x: int, y: int, width: int, height: int):
        """Log tile update in level session"""
        event = f"Tiles updated at ({x}, {y}) size {width}x{height}"
        self.add_level_event(level_name, event)
    
    def log_level_object_added(self, level_name: str, obj_type: str, x: int, y: int, details: str = ""):
        """Log level object addition (sign, chest, link, etc.)"""
        event = f"{obj_type} added at ({x}, {y})"
        if details:
            event += f": {details[:50]}..."
        self.add_level_event(level_name, event)
    
    def get_level_activity_summary(self, level_name: str) -> Dict[str, Any]:
        """Get activity summary for a specific level"""
        if level_name not in self.level_sessions:
            return {"error": "Level not visited"}
        
        session = self.level_sessions[level_name]
        current_time = time.time()
        
        # Calculate time spent
        time_spent = 0
        if session.entered_time:
            if self.current_level and self.current_level.name == level_name:
                time_spent = current_time - session.entered_time
            else:
                # Find when we left this level
                for i, (hist_level, hist_time) in enumerate(self.level_history):
                    if hist_level == level_name and i + 1 < len(self.level_history):
                        time_spent = self.level_history[i + 1][1] - hist_time
                        break
        
        return {
            "level_name": level_name,
            "time_spent": time_spent,
            "players_seen": len(session.players_seen),
            "chat_messages": len(session.chat_history),
            "events": len(session.events),
            "last_entered": session.entered_time,
            "is_current": self.current_level and self.current_level.name == level_name,
            "recent_events": session.events[-5:] if session.events else []
        }
    
    def get_all_level_summaries(self) -> Dict[str, Dict[str, Any]]:
        """Get activity summaries for all visited levels"""
        summaries = {}
        for level_name in self.level_sessions:
            summaries[level_name] = self.get_level_activity_summary(level_name)
        return summaries