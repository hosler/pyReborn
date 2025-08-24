#!/usr/bin/env python3
"""
PLO_SETACTIVELEVEL (Packet 156) - Set active level

This packet sets the active level for processing.
Used for level management and focus control.

The packet format is:
- Level name (STRING_GCHAR_LEN) - name of level to set as active
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


PLO_SETACTIVELEVEL = PacketStructure(
    packet_id=156,
    name="PLO_SETACTIVELEVEL",
    fields=[
        string_gchar_len_field("level_name", "Name of level to set as active")
    ],
    description="Set active level for processing",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_SETACTIVELEVEL packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_SETACTIVELEVEL.packet_id,
        'packet_name': PLO_SETACTIVELEVEL.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_SETACTIVELEVEL.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
