#!/usr/bin/env python3
"""
PLO_LEVELSIGN (Packet 5) - Level sign data

This packet defines sign placement and text content on a level.
"""

from ...base import PacketStructure, PacketField, PacketFieldType, byte_field, gstring_field, PacketReader, parse_field
from typing import Dict, Any


PLO_LEVELSIGN = PacketStructure(
    packet_id=5,
    name="PLO_LEVELSIGN",
    fields=[
        byte_field("x_coord", "X coordinate"),
        byte_field("y_coord", "Y coordinate"),
        gstring_field("sign_text", "Sign text content")
    ],
    description="Sign placement and text content",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_LEVELSIGN packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_LEVELSIGN.packet_id,
        'packet_name': PLO_LEVELSIGN.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_LEVELSIGN.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
