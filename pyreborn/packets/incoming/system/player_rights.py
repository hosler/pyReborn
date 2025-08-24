#!/usr/bin/env python3
"""
PLO_PLAYERRIGHTS (Packet 60) - Player rights and permissions

This packet sets or updates player rights and permissions.
Used for admin levels, special abilities, and access control.

The packet format is:
- Rights level (GCHAR) - player rights/admin level
- Rights data (VARIABLE_DATA) - specific permissions and capabilities
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_PLAYERRIGHTS = PacketStructure(
    packet_id=60,
    name="PLO_PLAYERRIGHTS",
    fields=[
        gchar_field("rights_level", "Player rights/admin level"),
        variable_data_field("rights_data", "Specific permissions and capabilities")
    ],
    description="Player rights and permissions",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_PLAYERRIGHTS packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_PLAYERRIGHTS.packet_id,
        'packet_name': PLO_PLAYERRIGHTS.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_PLAYERRIGHTS.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
