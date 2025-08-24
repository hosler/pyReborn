#!/usr/bin/env python3
"""
PLO_ITEMDEL (Packet 23) - Remove item from level

This packet notifies the client that an item has been removed from the level,
typically because a player picked it up or it expired.

The packet format is:
- Item X coordinate (GCHAR)
- Item Y coordinate (GCHAR)
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


PLO_ITEMDEL = PacketStructure(
    packet_id=23,
    name="PLO_ITEMDEL",
    fields=[
        gchar_field("x_coord", "Item X coordinate"),
        gchar_field("y_coord", "Item Y coordinate")
    ],
    description="Remove item from level",
    variable_length=False
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_ITEMDEL packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_ITEMDEL.packet_id,
        'packet_name': PLO_ITEMDEL.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_ITEMDEL.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
