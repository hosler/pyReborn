#!/usr/bin/env python3
"""
PLO_BOMBDEL (Packet 12) - Bomb deletion

This packet removes a bomb at specific coordinates, typically when
a bomb explodes or is otherwise removed from the game world.
"""

from ...base import PacketStructure, PacketField, PacketFieldType, coordinate_field, PacketReader, parse_field
from typing import Dict, Any


PLO_BOMBDEL = PacketStructure(
    packet_id=12,
    name="PLO_BOMBDEL",
    fields=[
        coordinate_field("x_coord", "X coordinate"),
        coordinate_field("y_coord", "Y coordinate")
    ],
    description="Delete bomb at coordinates"
)


def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_BOMBDEL packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_BOMBDEL.packet_id,
        'packet_name': PLO_BOMBDEL.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_BOMBDEL.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result