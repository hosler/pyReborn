#!/usr/bin/env python3
"""
PLO_LARGEFILESTART (Packet 68) - Large file transfer start

This packet signals the beginning of a large file transfer.
Large files are sent in chunks to avoid overwhelming the connection.

Based on C# implementation, the packet format is:
- Download ID (GINT4) - unique identifier for this download
- File name (STRING) - name of the large file (null-terminated)
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gint4_field(name: str, description: str) -> PacketField:
    """Helper to create a GINT4 field"""
    return PacketField(name, PacketFieldType.GINT4, description=description)


def string_field(name: str, description: str) -> PacketField:
    """Helper to create a STRING_LEN field"""
    return PacketField(name, PacketFieldType.STRING_LEN, description=description)


PLO_LARGEFILESTART = PacketStructure(
    packet_id=68,
    name="PLO_LARGEFILESTART", 
    fields=[
        gint4_field("download_id", "Unique identifier for this download"),
        string_field("file_name", "Name of the large file")
    ],
    description="Start of large file transfer",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_LARGEFILESTART packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_LARGEFILESTART.packet_id,
        'packet_name': PLO_LARGEFILESTART.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_LARGEFILESTART.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
