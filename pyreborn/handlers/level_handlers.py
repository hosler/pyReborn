"""
Level-related packet handlers.
"""
import logging
from typing import Dict, Any

from ..protocol.enums import ServerToPlayer
from ..protocol.packets import PacketReader
from ..game.state import GameState
from ..events import EventManager, EventType
from ..models.level import Level
from .registry import PacketHandlerRegistry

logger = logging.getLogger(__name__)


def register_level_handlers(registry: PacketHandlerRegistry, state: GameState, events: EventManager):
    """Register all level-related packet handlers."""
    
    def handle_level_name(reader: PacketReader, state: GameState):
        """Handle level name/change."""
        level_name = reader.read_string()
        logger.info(f"LEVEL NAME PACKET: '{level_name}'")
        
        # Create or get level
        if level_name not in state.level_cache:
            level = Level(level_name)
            state.level_cache[level_name] = level
        else:
            level = state.level_cache[level_name]
            
        # Update current level
        old_level = state.current_level
        state.current_level = level
        
        # Update local player level
        if state.local_player:
            state.local_player.level = level_name
            
        events.emit(EventType.LEVEL_CHANGE,
            level_name=level_name,
            old_level=old_level.name if old_level else None,
            level=level
        )
        
        logger.info(f"Entered level: {level_name}")
        return level_name
        
    def handle_level_board(reader: PacketReader, state: GameState):
        """Handle level board packet (PLO_LEVELBOARD)."""
        # This packet might signal that board data follows
        logger.info("PLO_LEVELBOARD packet received - board stream may follow")
        
        # The actual board data comes later as truncated hex in large packets
        # This packet might just be a marker
        
        events.emit(EventType.LEVEL_BOARD_UPDATE,
            level=state.current_level,
            status="board_stream_starting"
        )
        
        return {"status": "board_stream_starting"}
        
    def handle_level_npcs(reader: PacketReader, state: GameState):
        """Handle NPC list for current level."""
        if not state.current_level:
            return
            
        npcs = []
        
        # Read NPC data
        while reader.bytes_available() > 4:
            npc_id = reader.read_short()
            x = reader.read_byte() / 2.0
            y = reader.read_byte() / 2.0
            image = reader.read_string()
            
            npcs.append({
                'id': npc_id,
                'x': x,
                'y': y,
                'image': image
            })
            
        # Store in level
        state.current_level.npcs = npcs
        
        events.emit(EventType.NPCS_UPDATE,
            level=state.current_level,
            npcs=npcs
        )
        
        logger.debug(f"Loaded {len(npcs)} NPCs in {state.current_level.name}")
        return npcs
        
    def handle_level_signs(reader: PacketReader, state: GameState):
        """Handle sign list for current level."""
        if not state.current_level:
            return
            
        signs = []
        
        # Read sign data
        while reader.bytes_available() > 2:
            x = reader.read_byte()
            y = reader.read_byte()
            text = reader.read_string()
            
            signs.append({
                'x': x,
                'y': y,
                'text': text
            })
            
        # Store in level
        state.current_level.signs = signs
        
        events.emit(EventType.SIGNS_UPDATE,
            level=state.current_level,
            signs=signs
        )
        
        logger.debug(f"Loaded {len(signs)} signs in {state.current_level.name}")
        return signs
        
    def handle_level_links(reader: PacketReader, state: GameState):
        """Handle level links/warps."""
        if not state.current_level:
            return
            
        links = []
        
        # Read link data
        while reader.bytes_available() > 7:
            x = reader.read_byte()
            y = reader.read_byte()
            width = reader.read_byte()
            height = reader.read_byte()
            dest_level = reader.read_string()
            dest_x = reader.read_byte()
            dest_y = reader.read_byte()
            
            links.append({
                'x': x,
                'y': y,
                'width': width,
                'height': height,
                'destination': dest_level,
                'dest_x': dest_x,
                'dest_y': dest_y
            })
            
        # Store in level
        state.current_level.links = links
        
        events.emit(EventType.LINKS_UPDATE,
            level=state.current_level,
            links=links
        )
        
        logger.debug(f"Loaded {len(links)} links in {state.current_level.name}")
        return links
    
    # Register all handlers
    registry.register(ServerToPlayer.PLO_LEVELNAME, handle_level_name)
    registry.register(ServerToPlayer.PLO_LEVELBOARD, handle_level_board)
    registry.register(ServerToPlayer.PLO_NPCPROPS, handle_level_npcs)
    registry.register(ServerToPlayer.PLO_LEVELSIGN, handle_level_signs)
    registry.register(ServerToPlayer.PLO_LEVELLINK, handle_level_links)