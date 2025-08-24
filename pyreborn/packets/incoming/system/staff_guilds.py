#!/usr/bin/env python3
"""
PLO_STAFFGUILDS (Packet 47) - Staff guilds information

This packet provides information about staff guilds and their members,
used for displaying staff status and permissions.

The packet format is:
- Guild data (VARIABLE_DATA) - encoded guild information including
  guild names, member lists, and permission levels
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_STAFFGUILDS = PacketStructure(
    packet_id=47,
    name="PLO_STAFFGUILDS",
    fields=[
        variable_data_field("guild_data", "Encoded staff guild information")
    ],
    description="Staff guilds and member information",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_STAFFGUILDS packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_STAFFGUILDS.packet_id,
        'packet_name': PLO_STAFFGUILDS.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_STAFFGUILDS.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
