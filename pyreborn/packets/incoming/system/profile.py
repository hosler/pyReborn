#!/usr/bin/env python3
"""
PLO_PROFILE (Packet 75) - Player profile data

This packet provides detailed player profile information.
Contains stats, achievements, and other player data.

The packet format is:
- Profile data (VARIABLE_DATA) - encoded player profile information
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_PROFILE = PacketStructure(
    packet_id=75,
    name="PLO_PROFILE",
    fields=[
        variable_data_field("profile_data", "Encoded player profile information")
    ],
    description="Player profile data and statistics",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_PROFILE packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_PROFILE.packet_id,
        'packet_name': PLO_PROFILE.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_PROFILE.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
