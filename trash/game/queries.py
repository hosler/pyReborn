"""
Query methods for accessing game state in convenient ways.
"""
from typing import List, Optional, Dict, Any, Tuple
import math

from ..models.player import Player
from .state import GameState


class GameQueries:
    """
    Convenient query methods for game state.
    """
    
    def __init__(self, state: GameState):
        self.state = state
        
    def find_players_by_name(self, name: str, exact: bool = False) -> List[Player]:
        """
        Find players by nickname.
        
        Args:
            name: Name to search for
            exact: If True, only exact matches. If False, partial matches.
            
        Returns:
            List of matching players
        """
        players = []
        search_name = name.lower()
        
        # Check local player
        if self.state.local_player:
            player_name = self.state.local_player.nickname.lower()
            if exact and player_name == search_name:
                players.append(self.state.local_player)
            elif not exact and search_name in player_name:
                players.append(self.state.local_player)
                
        # Check other players
        for player in self.state.players.values():
            player_name = player.nickname.lower()
            if exact and player_name == search_name:
                players.append(player)
            elif not exact and search_name in player_name:
                players.append(player)
                
        return players
        
    def get_nearby_players(self, radius: float = 10.0, 
                          include_self: bool = False) -> List[Player]:
        """
        Get players within a certain radius of local player.
        
        Args:
            radius: Distance in tiles
            include_self: Whether to include local player
            
        Returns:
            List of nearby players
        """
        if not self.state.local_player:
            return []
            
        local_x = self.state.local_player.x
        local_y = self.state.local_player.y
        local_level = self.state.local_player.level
        
        nearby = []
        
        if include_self:
            nearby.append(self.state.local_player)
            
        for player in self.state.players.values():
            # Must be in same level
            if player.level != local_level:
                continue
                
            # Calculate distance
            dx = player.x - local_x
            dy = player.y - local_y
            distance = math.sqrt(dx * dx + dy * dy)
            
            if distance <= radius:
                nearby.append(player)
                
        return nearby
        
    def get_player_at_position(self, x: float, y: float, 
                               tolerance: float = 0.5) -> Optional[Player]:
        """
        Get player at or near a specific position.
        
        Args:
            x: X coordinate
            y: Y coordinate
            tolerance: How close the player needs to be
            
        Returns:
            Player at position or None
        """
        if not self.state.current_level:
            return None
            
        # Check local player
        if self.state.local_player:
            dx = abs(self.state.local_player.x - x)
            dy = abs(self.state.local_player.y - y)
            if dx <= tolerance and dy <= tolerance:
                return self.state.local_player
                
        # Check other players
        for player in self.state.players.values():
            if player.level != self.state.current_level.name:
                continue
            dx = abs(player.x - x)
            dy = abs(player.y - y)
            if dx <= tolerance and dy <= tolerance:
                return player
                
        return None
        
    def get_player_stats(self, player_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Get stats for a player.
        
        Args:
            player_id: Player ID or None for local player
            
        Returns:
            Dict of player stats
        """
        if player_id is None:
            player = self.state.local_player
        else:
            player = self.state.get_player(player_id)
            
        if not player:
            return {}
            
        return {
            'id': player.id,
            'nickname': player.nickname,
            'level': player.level,
            'position': (player.x, player.y),
            'hearts': player.hearts,
            'max_hearts': player.max_hearts,
            'bombs': player.bombs,
            'arrows': player.arrows,
            'rupees': player.rupees,
            'kills': player.kills,
            'deaths': player.deaths,
            'online_time': player.online_time,
            'guild': player.guild_name,
        }
        
    def get_level_info(self, level_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Get information about a level.
        
        Args:
            level_name: Level name or None for current level
            
        Returns:
            Dict of level information
        """
        if level_name is None:
            level = self.state.current_level
        else:
            level = self.state.level_cache.get(level_name)
            
        if not level:
            return {}
            
        # Count players in level
        player_count = len(self.get_players_in_level(level.name))
        
        return {
            'name': level.name,
            'width': level.width,
            'height': level.height,
            'player_count': player_count,
            'has_tiles': bool(level.tiles),
            'npc_count': len(level.npcs) if hasattr(level, 'npcs') else 0,
            'sign_count': len(level.signs) if hasattr(level, 'signs') else 0,
        }
        
    def get_players_in_level(self, level_name: Optional[str] = None) -> List[Player]:
        """
        Get all players in a level.
        
        Args:
            level_name: Level name or None for current level
            
        Returns:
            List of players in the level
        """
        if level_name is None:
            if not self.state.current_level:
                return []
            level_name = self.state.current_level.name
            
        return self.state.get_players_in_level(level_name)
        
    def calculate_distance(self, player1: Player, player2: Player) -> float:
        """Calculate distance between two players."""
        if player1.level != player2.level:
            return float('inf')  # Different levels
            
        dx = player2.x - player1.x
        dy = player2.y - player1.y
        return math.sqrt(dx * dx + dy * dy)
        
    def get_direction_to_player(self, target: Player) -> Optional[int]:
        """
        Get direction from local player to target player.
        
        Returns:
            Direction (0=up, 1=left, 2=down, 3=right) or None
        """
        if not self.state.local_player:
            return None
            
        if self.state.local_player.level != target.level:
            return None
            
        dx = target.x - self.state.local_player.x
        dy = target.y - self.state.local_player.y
        
        # Determine primary direction
        if abs(dx) > abs(dy):
            return 3 if dx > 0 else 1  # Right or Left
        else:
            return 2 if dy > 0 else 0  # Down or Up