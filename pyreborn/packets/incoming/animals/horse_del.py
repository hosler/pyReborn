#!/usr/bin/env python3
"""
PLO_HORSEDEL (Packet 18) - Remove horse from level

This packet notifies the client that a horse has been removed from
the level and should no longer be displayed.

The packet format is:
- Horse X coordinate (GCHAR) - X position where horse was removed
- Horse Y coordinate (GCHAR) - Y position where horse was removed
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


PLO_HORSEDEL = PacketStructure(
    packet_id=18,
    name="PLO_HORSEDEL",
    fields=[
        gchar_field("x_coord", "Horse X coordinate for removal"),
        gchar_field("y_coord", "Horse Y coordinate for removal")
    ],
    description="Remove horse from level",
    variable_length=False
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_HORSEDEL packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_HORSEDEL.packet_id,
        'packet_name': PLO_HORSEDEL.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_HORSEDEL.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
