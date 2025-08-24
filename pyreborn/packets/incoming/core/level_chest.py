#!/usr/bin/env python3
"""
PLO_LEVELCHEST (Packet 4) - Level chest data

This packet defines chest placement and contents on a level.
"""

from ...base import PacketStructure, PacketField, PacketFieldType, byte_field, gstring_field, PacketReader, parse_field
from typing import Dict, Any


PLO_LEVELCHEST = PacketStructure(
    packet_id=4,
    name="PLO_LEVELCHEST",
    fields=[
        byte_field("x_coord", "X coordinate (pixels/2)"),
        byte_field("y_coord", "Y coordinate (pixels/2)"),
        byte_field("item", "Item/chest type"),
        gstring_field("sign_text", "Sign text for chest")
    ],
    description="Chest placement and contents",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_LEVELCHEST packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_LEVELCHEST.packet_id,
        'packet_name': PLO_LEVELCHEST.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_LEVELCHEST.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
