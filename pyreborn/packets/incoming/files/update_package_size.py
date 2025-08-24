#!/usr/bin/env python3
"""
PLO_UPDATEPACKAGESIZE (Packet 105) - Update package size

This packet announces the size of an update package.
Used for progress tracking during game updates.

The packet format is:
- Package name (STRING_GCHAR_LEN) - name of the update package
- Package size (GINT5) - size of package in bytes
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


def gint5_field(name: str, description: str) -> PacketField:
    """Helper to create a GINT5 field"""
    return PacketField(name, PacketFieldType.GINT5, description=description)


PLO_UPDATEPACKAGESIZE = PacketStructure(
    packet_id=105,
    name="PLO_UPDATEPACKAGESIZE",
    fields=[
        string_gchar_len_field("package_name", "Name of update package"),
        gint5_field("package_size", "Size of package in bytes")
    ],
    description="Update package size announcement",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_UPDATEPACKAGESIZE packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_UPDATEPACKAGESIZE.packet_id,
        'packet_name': PLO_UPDATEPACKAGESIZE.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_UPDATEPACKAGESIZE.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
