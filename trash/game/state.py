"""
Centralized game state management for PyReborn.
"""
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, field
from datetime import datetime

from ..models.player import Player
from ..models.level import Level


@dataclass
class GameState:
    """Central game state object that tracks all game data."""
    
    # Player state
    local_player: Optional[Player] = None
    players: Dict[int, Player] = field(default_factory=dict)
    
    # Level state
    current_level: Optional[Level] = None
    level_cache: Dict[str, Level] = field(default_factory=dict)
    
    # Server state
    flags: Dict[str, str] = field(default_factory=dict)
    server_time: float = 0.0
    connected: bool = False
    
    # Combat state
    bombs: List[Dict[str, Any]] = field(default_factory=list)
    arrows: List[Dict[str, Any]] = field(default_factory=list)
    
    # Chat state
    recent_messages: List[Dict[str, Any]] = field(default_factory=list)
    
    def get_player(self, player_id: int) -> Optional[Player]:
        """Get a player by ID."""
        if player_id == self.local_player.id if self.local_player else None:
            return self.local_player
        return self.players.get(player_id)
    
    def update_player(self, player: Player) -> None:
        """Update a player's state."""
        if self.local_player and player.id == self.local_player.id:
            self.local_player = player
        else:
            self.players[player.id] = player
    
    def remove_player(self, player_id: int) -> None:
        """Remove a player from tracking."""
        self.players.pop(player_id, None)
    
    def get_players_in_level(self, level_name: str) -> List[Player]:
        """Get all players in a specific level."""
        players = []
        if self.local_player and self.local_player.level == level_name:
            players.append(self.local_player)
        players.extend([p for p in self.players.values() if p.level == level_name])
        return players
    
    def add_chat_message(self, player_name: str, message: str) -> None:
        """Add a chat message to recent history."""
        self.recent_messages.append({
            'player': player_name,
            'message': message,
            'timestamp': datetime.now()
        })
        # Keep only last 100 messages
        if len(self.recent_messages) > 100:
            self.recent_messages.pop(0)
    
    def snapshot(self) -> Dict[str, Any]:
        """Create a snapshot of current game state."""
        return {
            'local_player': self.local_player.__dict__ if self.local_player else None,
            'players': {pid: p.__dict__ for pid, p in self.players.items()},
            'current_level': self.current_level.name if self.current_level else None,
            'flags': self.flags.copy(),
            'server_time': self.server_time,
            'connected': self.connected,
            'snapshot_time': datetime.now().isoformat()
        }
    
    def clear(self) -> None:
        """Clear all state data."""
        self.local_player = None
        self.players.clear()
        self.current_level = None
        self.level_cache.clear()
        self.flags.clear()
        self.bombs.clear()
        self.arrows.clear()
        self.recent_messages.clear()
        self.connected = False