#!/usr/bin/env python3
"""
PLO_LARGEFILESIZE (Packet 84) - Large file size announcement

This packet announces the size of a large file before transfer begins.
Used for progress tracking and memory allocation.

Based on C# implementation, the packet format is:
- Download ID (GINT4) - unique identifier for this download
- File size (GINT4) - size of the file in bytes
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gint4_field(name: str, description: str) -> PacketField:
    """Helper to create a GINT4 field"""
    return PacketField(name, PacketFieldType.GINT4, description=description)


PLO_LARGEFILESIZE = PacketStructure(
    packet_id=84,
    name="PLO_LARGEFILESIZE",
    fields=[
        gint4_field("download_id", "Unique identifier for this download"),
        gint4_field("file_size", "Size of file in bytes")
    ],
    description="Large file size announcement",
    variable_length=False
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_LARGEFILESIZE packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_LARGEFILESIZE.packet_id,
        'packet_name': PLO_LARGEFILESIZE.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_LARGEFILESIZE.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
