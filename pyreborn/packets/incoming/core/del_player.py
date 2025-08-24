#!/usr/bin/env python3
"""
PLO_DELPLAYER (Packet 56) - Remove player from level

This packet notifies the client that a player has left the level
and should be removed from display.

The packet format is:
- Player ID (GSHORT) - unique identifier of the player to remove
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


PLO_DELPLAYER = PacketStructure(
    packet_id=56,
    name="PLO_DELPLAYER",
    fields=[
        gshort_field("player_id", "ID of player to remove from level")
    ],
    description="Remove player from level",
    variable_length=False
)

def parse(data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse PLO_DELPLAYER packet data"""
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        player_id = data.get('player_id', 0)
        
        logger.info(f"📦 PLO_DELPLAYER: Player ID:{player_id} leaving")
        
        # Build event data
        events = [{
            'type': 'PLAYER_LEFT',
            'data': {
                'player_id': player_id
            }
        }]
        
        return {
            'player_id': player_id,
            'events': events
        }
        
    except Exception as e:
        logger.error(f"Error parsing PLO_DELPLAYER: {e}")
        return {'error': str(e)}

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_DELPLAYER packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_DELPLAYER.packet_id,
        'packet_name': PLO_DELPLAYER.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_DELPLAYER.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    # Apply business logic parsing
    parsed_data = parse(result['fields'])
    if parsed_data:
        result['parsed_data'] = parsed_data
    
    return result
