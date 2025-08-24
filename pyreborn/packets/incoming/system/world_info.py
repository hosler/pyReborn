#!/usr/bin/env python3
"""
PLO_WORLDINFO (Packet 63) - World information

This packet provides world/server information and settings.
Contains world name, description, and configuration data.

The packet format is:
- World name (STRING_GCHAR_LEN) - name of the world/server
- World data (VARIABLE_DATA) - world settings, description, and info
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_WORLDINFO = PacketStructure(
    packet_id=63,
    name="PLO_WORLDINFO",
    fields=[
        string_gchar_len_field("world_name", "Name of the world/server"),
        variable_data_field("world_data", "World settings, description, and info")
    ],
    description="World/server information and settings",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_WORLDINFO packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_WORLDINFO.packet_id,
        'packet_name': PLO_WORLDINFO.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_WORLDINFO.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
