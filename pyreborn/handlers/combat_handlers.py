"""
Combat and action packet handlers.
"""
import logging
from typing import Dict, Any

from ..protocol.enums import ServerToPlayer
from ..protocol.packets import PacketReader
from ..game.state import GameState
from ..events import EventManager, EventType
from .registry import PacketHandlerRegistry

logger = logging.getLogger(__name__)


def register_combat_handlers(registry: PacketHandlerRegistry, state: GameState, events: EventManager):
    """Register all combat-related packet handlers."""
    
    def handle_bomb_placed(reader: PacketReader, state: GameState):
        """Handle bomb placement."""
        player_id = reader.read_byte()
        x = reader.read_byte() / 2.0
        y = reader.read_byte() / 2.0
        
        bomb = {
            'player_id': player_id,
            'x': x,
            'y': y,
            'time': 0  # Will explode in ~3 seconds
        }
        
        state.bombs.append(bomb)
        
        events.emit(EventType.BOMB_PLACED, **bomb)
        
        logger.debug(f"Bomb placed by player {player_id} at ({x}, {y})")
        return bomb
        
    def handle_bomb_exploded(reader: PacketReader, state: GameState):
        """Handle bomb explosion."""
        player_id = reader.read_byte()
        x = reader.read_byte() / 2.0
        y = reader.read_byte() / 2.0
        
        # Remove bomb from state
        state.bombs = [b for b in state.bombs 
                      if not (b['player_id'] == player_id and 
                             abs(b['x'] - x) < 0.5 and 
                             abs(b['y'] - y) < 0.5)]
        
        explosion = {
            'player_id': player_id,
            'x': x,
            'y': y
        }
        
        events.emit(EventType.BOMB_EXPLODED, **explosion)
        
        logger.debug(f"Bomb exploded at ({x}, {y})")
        return explosion
        
    def handle_arrow_shot(reader: PacketReader, state: GameState):
        """Handle arrow being shot."""
        player_id = reader.read_byte()
        x = reader.read_byte() / 2.0
        y = reader.read_byte() / 2.0
        direction = reader.read_byte()
        
        arrow = {
            'player_id': player_id,
            'x': x,
            'y': y,
            'direction': direction
        }
        
        state.arrows.append(arrow)
        
        events.emit(EventType.ARROW_SHOT, **arrow)
        
        logger.debug(f"Arrow shot by player {player_id} from ({x}, {y}) dir {direction}")
        return arrow
        
    def handle_player_hurt(reader: PacketReader, state: GameState):
        """Handle player taking damage."""
        player_id = reader.read_byte()
        hearts = reader.read_byte() / 2.0
        
        # Update player hearts
        player = state.get_player(player_id)
        if player:
            old_hearts = player.hearts
            player.hearts = hearts
            
            damage = {
                'player_id': player_id,
                'player': player,
                'hearts': hearts,
                'damage': old_hearts - hearts if old_hearts else 0
            }
            
            events.emit(EventType.PLAYER_HURT, **damage)
            
            logger.debug(f"Player {player_id} hurt, hearts: {hearts}")
            return damage
            
        return None
        
    def handle_player_killed(reader: PacketReader, state: GameState):
        """Handle player death."""
        victim_id = reader.read_byte()
        killer_id = reader.read_byte()
        
        victim = state.get_player(victim_id)
        killer = state.get_player(killer_id)
        
        death = {
            'victim_id': victim_id,
            'killer_id': killer_id,
            'victim': victim,
            'killer': killer
        }
        
        # Update stats if available
        if victim:
            victim.deaths += 1
            victim.hearts = 0
        if killer:
            killer.kills += 1
            
        events.emit(EventType.PLAYER_KILLED, **death)
        
        logger.info(f"Player {victim_id} killed by player {killer_id}")
        return death
        
    def handle_item_taken(reader: PacketReader, state: GameState):
        """Handle item pickup."""
        item_type = reader.read_byte()
        amount = reader.read_byte()
        
        # Update local player inventory
        if state.local_player:
            if item_type == 0:  # Rupees
                state.local_player.rupees += amount
            elif item_type == 1:  # Bombs
                state.local_player.bombs += amount
            elif item_type == 2:  # Arrows
                state.local_player.arrows += amount
                
        pickup = {
            'item_type': item_type,
            'amount': amount
        }
        
        events.emit(EventType.ITEM_TAKEN, **pickup)
        
        logger.debug(f"Picked up {amount} of item type {item_type}")
        return pickup
    
    # Register all handlers
    registry.register(ServerToPlayer.PLO_BOMBADD, handle_bomb_placed)
    registry.register(ServerToPlayer.PLO_BOMBDEL, handle_bomb_exploded)
    registry.register(ServerToPlayer.PLO_ARROWADD, handle_arrow_shot)
    registry.register(ServerToPlayer.PLO_HURTPLAYER, handle_player_hurt)
    registry.register(ServerToPlayer.PLO_HURTPLAYER, handle_player_killed, name="handle_player_killed", priority=5)
    registry.register(ServerToPlayer.PLO_ITEMADD, handle_item_taken)