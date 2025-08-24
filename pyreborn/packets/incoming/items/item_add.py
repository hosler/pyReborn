#!/usr/bin/env python3
"""
PLO_ITEMADD (Packet 22) - Add item to level

This packet notifies the client that a new item has been placed on the level.
Items can be weapons, consumables, or other interactive objects.

The packet format is:
- Item X coordinate (GCHAR)
- Item Y coordinate (GCHAR) 
- Item type/sprite (STRING_GCHAR_LEN) - identifies the item type
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


PLO_ITEMADD = PacketStructure(
    packet_id=22,
    name="PLO_ITEMADD",
    fields=[
        gchar_field("x_coord", "Item X coordinate"),
        gchar_field("y_coord", "Item Y coordinate"),
        string_gchar_len_field("item_type", "Item type/sprite identifier")
    ],
    description="Add item to level",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_ITEMADD packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_ITEMADD.packet_id,
        'packet_name': PLO_ITEMADD.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_ITEMADD.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
