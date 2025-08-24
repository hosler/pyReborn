#!/usr/bin/env python3
"""
PLO_OTHERPLPROPS (Packet 8) - Other player properties update

This packet contains property updates for other players (not self).
Unlike PLO_PLAYERPROPS, this includes a player ID prefix to identify
which player the properties belong to.

The packet format is:
- Player ID (GSHORT) - identifies which player
- Property ID (GCHAR) 
- Property data (variable format depending on property type)
- Repeat for multiple properties
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_OTHERPLPROPS = PacketStructure(
    packet_id=8,
    name="PLO_OTHERPLPROPS",
    fields=[
        gshort_field("player_id", "ID of the player these properties belong to"),
        variable_data_field("properties_data", "Encoded player properties")
    ],
    description="Other player properties update",
    variable_length=True
)

def parse(data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse other player properties - reuse PLO_PLAYERPROPS parser"""
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        player_id = data.get('player_id', 0)
        prop_data = data.get('properties_data', b'')
        
        # Import the player props parser
        from .player_props import parse as parse_player_props
        
        # Parse the properties using the same logic as PLO_PLAYERPROPS
        parsed = parse_player_props({'properties': prop_data})
        
        # Add player ID to the result
        parsed['player_id'] = player_id
        
        logger.info(f"📦 Parsed OTHER_PLAYER props for player {player_id}: {len(parsed.get('properties', {}))} properties")
        
        # Check if we got position data
        props = parsed.get('properties', {})
        if 'pixelx' in props or 'x' in props:
            x = props.get('pixelx', props.get('x', 0))
            y = props.get('pixely', props.get('y', 0))
            logger.info(f"   Other player {player_id} position: ({x:.2f}, {y:.2f})")
        
        return parsed
        
    except Exception as e:
        logger.error(f"Error parsing other player props: {e}")
        import traceback
        traceback.print_exc()
        return {'error': str(e), 'player_id': data.get('player_id', 0), 'properties': {}, 'events': []}

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_OTHERPLPROPS packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_OTHERPLPROPS.packet_id,
        'packet_name': PLO_OTHERPLPROPS.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_OTHERPLPROPS.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    # Apply business logic parsing
    parsed_data = parse(result['fields'])
    if parsed_data:
        result['parsed_data'] = parsed_data
    
    return result
