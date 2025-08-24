#!/usr/bin/env python3
"""
PLO_PLAYERMOVED (Packet 2) - Player movement

This packet notifies when a player moves to a new position.
"""

from ...base import PacketStructure, PacketField, PacketFieldType, gchar_field, PacketReader, parse_field
from typing import Dict, Any


PLO_PLAYERMOVED = PacketStructure(
    packet_id=165,  # Correct packet ID from GServer audit: PLO_MOVE
    name="PLO_PLAYERMOVED",
    fields=[
        gchar_field("player_id", "Player identifier"),
        gchar_field("x", "X coordinate"),  
        gchar_field("y", "Y coordinate"),
        gchar_field("direction", "Movement direction"),
        gchar_field("sprite", "Sprite/animation frame")
    ],
    description="Player movement update"
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_PLAYERMOVED packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_PLAYERMOVED.packet_id,
        'packet_name': PLO_PLAYERMOVED.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_PLAYERMOVED.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
