#!/usr/bin/env python3
"""
PLO_UPDATEPACKAGEDONE (Packet 106) - Update package complete

This packet signals completion of an update package download.
Indicates the package has been fully received and verified.

The packet format is:
- Package name (STRING_GCHAR_LEN) - name of completed package
- Completion status (GCHAR) - success/failure status
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


PLO_UPDATEPACKAGEDONE = PacketStructure(
    packet_id=106,
    name="PLO_UPDATEPACKAGEDONE",
    fields=[
        string_gchar_len_field("package_name", "Name of completed package"),
        gchar_field("completion_status", "Success/failure status")
    ],
    description="Update package download complete",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_UPDATEPACKAGEDONE packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_UPDATEPACKAGEDONE.packet_id,
        'packet_name': PLO_UPDATEPACKAGEDONE.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_UPDATEPACKAGEDONE.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
