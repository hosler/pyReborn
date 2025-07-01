"""
Player-related packet handlers.
"""
import logging
from typing import Dict, Any

from ..protocol.enums import ServerToPlayer
from ..protocol.packets import PacketReader
from ..game.state import GameState
from ..events import EventManager, EventType
from ..models.player import Player
from .registry import PacketHandlerRegistry

logger = logging.getLogger(__name__)


def register_player_handlers(registry: PacketHandlerRegistry, state: GameState, events: EventManager):
    """Register all player-related packet handlers."""
    
    def handle_player_props(reader: PacketReader, state: GameState):
        """Handle player property updates."""
        if reader.bytes_available() < 1:
            return
            
        player_id = reader.read_byte()
        
        # Get or create player
        player = state.get_player(player_id)
        if not player:
            player = Player()
            player.id = player_id
            
        # Read properties based on available data
        while reader.bytes_available() > 0:
            prop_id = reader.read_byte()
            
            if prop_id == 0:  # X position
                player.x = reader.read_byte() / 2.0
            elif prop_id == 1:  # Y position  
                player.y = reader.read_byte() / 2.0
            elif prop_id == 2:  # Direction
                player.dir = reader.read_byte()
            elif prop_id == 3:  # Nickname
                player.nickname = reader.read_string()
            elif prop_id == 4:  # Head image
                player.head_img = reader.read_string()
            elif prop_id == 5:  # Body image
                player.body_img = reader.read_string()
            elif prop_id == 6:  # Shield image
                player.shield_img = reader.read_string()
            elif prop_id == 7:  # Sword image
                player.sword_img = reader.read_string()
            elif prop_id == 8:  # Level
                player.level = reader.read_string()
            elif prop_id == 9:  # Hearts
                player.hearts = reader.read_byte() / 2.0
            elif prop_id == 10:  # Max hearts
                player.max_hearts = reader.read_byte() / 2.0
            elif prop_id == 11:  # Bombs
                player.bombs = reader.read_byte()
            elif prop_id == 12:  # Arrows
                player.arrows = reader.read_byte()
            elif prop_id == 13:  # Rupees
                player.rupees = reader.read_short()
            elif prop_id == 14:  # Guild name
                player.guild_name = reader.read_string()
            else:
                # Skip unknown property
                if reader.bytes_available() > 0:
                    reader.read_byte()
                    
        # Update state
        state.update_player(player)
        
        # Emit event
        events.emit(EventType.PLAYER_UPDATE,
            player=player,
            player_id=player_id,
            is_local=player_id == (state.local_player.id if state.local_player else None)
        )
        
        return player
        
    def handle_player_joined(reader: PacketReader, state: GameState):
        """Handle player joining the level."""
        player = Player()
        player.id = reader.read_byte()
        player.nickname = reader.read_string()
        player.level = state.current_level.name if state.current_level else ""
        
        state.update_player(player)
        
        events.emit(EventType.PLAYER_JOINED,
            player=player,
            player_id=player.id
        )
        
        logger.info(f"Player joined: {player.nickname} (ID: {player.id})")
        return player
        
    def handle_player_left(reader: PacketReader, state: GameState):
        """Handle player leaving the level."""
        player_id = reader.read_byte()
        
        player = state.get_player(player_id)
        if player:
            state.remove_player(player_id)
            
            events.emit(EventType.PLAYER_LEFT,
                player=player,
                player_id=player_id
            )
            
            logger.info(f"Player left: {player.nickname} (ID: {player_id})")
            
        return player_id
        
    def handle_self_props(reader: PacketReader, state: GameState):
        """Handle local player property updates."""
        if not state.local_player:
            state.local_player = Player()
            state.local_player.id = 0  # Local player always has ID 0
            
        player = state.local_player
        
        # Read all properties
        while reader.bytes_available() > 0:
            prop_id = reader.read_byte()
            
            if prop_id == 0:  # X position
                player.x = reader.read_short() / 8.0
            elif prop_id == 1:  # Y position
                player.y = reader.read_short() / 8.0
            elif prop_id == 2:  # Hearts
                player.hearts = reader.read_byte() / 2.0
            elif prop_id == 3:  # Max hearts
                player.max_hearts = reader.read_byte() / 2.0
            elif prop_id == 4:  # Bombs
                player.bombs = reader.read_byte()
            elif prop_id == 5:  # Arrows  
                player.arrows = reader.read_byte()
            elif prop_id == 6:  # Rupees
                player.rupees = reader.read_short()
            elif prop_id == 7:  # Deaths
                player.deaths = reader.read_short()
            elif prop_id == 8:  # Kills
                player.kills = reader.read_short()
            elif prop_id == 9:  # Online time
                player.online_time = reader.read_int()
            else:
                # Skip unknown
                if reader.bytes_available() > 0:
                    reader.read_byte()
                    
        events.emit(EventType.SELF_UPDATE,
            player=player
        )
        
        return player
        
    def handle_player_stats(reader: PacketReader, state: GameState):
        """Handle player statistics update."""
        stats = {}
        
        # Read stat pairs
        while reader.bytes_available() >= 2:
            stat_type = reader.read_byte()
            value = reader.read_short()
            
            if stat_type == 0:
                stats['kills'] = value
            elif stat_type == 1:
                stats['deaths'] = value
            elif stat_type == 2:
                stats['online_time'] = value
            elif stat_type == 3:
                stats['ap'] = value
                
        # Update local player stats
        if state.local_player and stats:
            for key, value in stats.items():
                setattr(state.local_player, key, value)
                
        events.emit(EventType.STATS_UPDATE, **stats)
        
        return stats
    
    # Register all handlers
    registry.register(ServerToPlayer.PLO_PLAYERPROPS, handle_player_props, priority=10)
    registry.register(ServerToPlayer.PLO_OTHERPLPROPS, handle_player_joined)
    registry.register(ServerToPlayer.PLO_NPCDEL, handle_player_left)
    registry.register(ServerToPlayer.PLO_PLAYERPROPS, handle_self_props, name="handle_self_props")
    registry.register(ServerToPlayer.PLO_PLAYERPROPS, handle_player_stats, name="handle_player_stats", priority=5)