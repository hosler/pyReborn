#!/usr/bin/env python3
"""
PLO_FULLSTOP (Packet 176) - Full stop command

This packet issues a full stop command to halt player movement.
Used for emergency stops or specific game mechanics.

The packet format is:
- Stop type (GCHAR) - type of stop command
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


PLO_FULLSTOP = PacketStructure(
    packet_id=176,
    name="PLO_FULLSTOP",
    fields=[
        gchar_field("stop_type", "Type of stop command")
    ],
    description="Full stop command for player movement",
    variable_length=False
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_FULLSTOP packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_FULLSTOP.packet_id,
        'packet_name': PLO_FULLSTOP.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_FULLSTOP.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
