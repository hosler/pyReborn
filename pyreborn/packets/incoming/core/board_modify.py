#!/usr/bin/env python3
"""
PLO_BOARDMODIFY (Packet 7) - Board modification

This packet notifies the client that tiles on the level board have been
modified. Used for real-time level editing and dynamic tile changes.

The packet format is:
- Modification X (GCHAR) - X coordinate of modification
- Modification Y (GCHAR) - Y coordinate of modification  
- New tile data (VARIABLE_DATA) - new tile information
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_BOARDMODIFY = PacketStructure(
    packet_id=7,
    name="PLO_BOARDMODIFY",
    fields=[
        gchar_field("modify_x", "X coordinate of modification"),
        gchar_field("modify_y", "Y coordinate of modification"),
        variable_data_field("tile_data", "New tile information")
    ],
    description="Level board tile modification",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_BOARDMODIFY packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_BOARDMODIFY.packet_id,
        'packet_name': PLO_BOARDMODIFY.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_BOARDMODIFY.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
