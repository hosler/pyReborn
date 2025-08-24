#!/usr/bin/env python3
"""
PLO_BOMBADD (Packet 11) - Add bomb to level

This packet notifies the client that a bomb has been placed on the level.
Bombs are explosive weapons that detonate after a timer or when triggered.

The packet format is:
- Bomb X coordinate (GCHAR)
- Bomb Y coordinate (GCHAR)
- Bomb power (GCHAR) - explosive power/radius
- Bomb timer (GCHAR) - time until detonation
- Bomb owner ID (GSHORT) - player who placed the bomb
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


PLO_BOMBADD = PacketStructure(
    packet_id=11,
    name="PLO_BOMBADD",
    fields=[
        gchar_field("x_coord", "Bomb X coordinate"),
        gchar_field("y_coord", "Bomb Y coordinate"),
        gchar_field("bomb_power", "Explosive power/radius"),
        gchar_field("bomb_timer", "Time until detonation"),
        gshort_field("owner_id", "Player ID who placed the bomb")
    ],
    description="Add bomb to level",
    variable_length=False
)

def parse(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse bomb placement data with full business logic.
    
    This function processes bomb placement including:
    - Position calculation (converting to tiles)
    - Danger zone determination
    - Event generation for game mechanics
    
    Args:
        data: Raw packet fields
        
    Returns:
        Processed bomb data with events
    """
    try:
        import logging
        logger = logging.getLogger(__name__)
        
        # Extract fields (already decoded from GCHAR/GSHORT)
        x = data.get('x_coord', 30)  # Half-tiles
        y = data.get('y_coord', 30)
        power = data.get('bomb_power', 1)
        timer = data.get('bomb_timer', 3)
        owner_id = data.get('owner_id', 0)
        
        # Convert to tiles
        x_tiles = x / 2.0
        y_tiles = y / 2.0
        
        # Calculate danger zone (bomb blast radius)
        danger_radius = power + 1  # Typically power + 1 tiles
        danger_zone = {
            'center': (x_tiles, y_tiles),
            'radius': danger_radius,
            'min_x': max(0, x_tiles - danger_radius),
            'max_x': min(63, x_tiles + danger_radius),  # Level bounds
            'min_y': max(0, y_tiles - danger_radius),
            'max_y': min(63, y_tiles + danger_radius)
        }
        
        # Calculate explosion time (typically in 100ms units)
        explosion_time_ms = timer * 100
        
        # Prepare bomb info
        bomb_info = {
            'owner_id': owner_id,
            'position': (x_tiles, y_tiles),
            'power': power,
            'timer': timer,
            'explosion_time_ms': explosion_time_ms,
            'danger_zone': danger_zone,
            'is_super_bomb': power >= 3  # Super bombs have power 3+
        }
        
        # Generate events
        events = []
        events.append({
            'type': 'BOMB_ADDED',
            'data': {
                'owner_id': owner_id,
                'x': x_tiles,
                'y': y_tiles,
                'power': power,
                'timer': timer,
                'explosion_time_ms': explosion_time_ms,
                'danger_zone': danger_zone
            }
        })
        
        logger.debug(f"Bomb placed at ({x_tiles:.1f}, {y_tiles:.1f}) by player {owner_id}, power={power}, timer={timer}")
        
        return {
            'bomb_info': bomb_info,
            'events': events
        }
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error parsing bomb add packet: {e}")
        return {
            'error': str(e),
            'events': []
        }

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_BOMBADD packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_BOMBADD.packet_id,
        'packet_name': PLO_BOMBADD.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_BOMBADD.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    # Apply business logic parsing
    parsed_data = parse(result['fields'])
    if parsed_data:
        result['parsed_data'] = parsed_data
    
    return result
