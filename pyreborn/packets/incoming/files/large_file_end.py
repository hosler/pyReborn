#!/usr/bin/env python3
"""
PLO_LARGEFILEEND (Packet 69) - Large file transfer end

This packet signals the completion of a large file transfer.
Indicates that all chunks have been sent successfully.

Based on C# implementation, the packet format is:
- Download ID (GINT4) - unique identifier for this download
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gint4_field(name: str, description: str) -> PacketField:
    """Helper to create a GINT4 field"""
    return PacketField(name, PacketFieldType.GINT4, description=description)


def string_field(name: str, description: str) -> PacketField:
    """Helper to create a STRING_LEN field"""
    return PacketField(name, PacketFieldType.STRING_LEN, description=description)


PLO_LARGEFILEEND = PacketStructure(
    packet_id=69,
    name="PLO_LARGEFILEEND",
    fields=[
        gint4_field("download_id", "Unique identifier for this download"),
        string_field("filename", "Name of the completed file")
    ],
    description="End of large file transfer",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_LARGEFILEEND packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_LARGEFILEEND.packet_id,
        'packet_name': PLO_LARGEFILEEND.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_LARGEFILEEND.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
