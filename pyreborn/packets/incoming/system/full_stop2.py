#!/usr/bin/env python3
"""
PLO_FULLSTOP2 (Packet 177) - Enhanced full stop command

This packet issues an enhanced full stop command.
Extended version with additional stop parameters.

The packet format is:
- Stop type (GCHAR) - type of stop command
- Stop data (VARIABLE_DATA) - additional stop parameters
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_FULLSTOP2 = PacketStructure(
    packet_id=177,
    name="PLO_FULLSTOP2",
    fields=[
        gchar_field("stop_type", "Type of stop command"),
        variable_data_field("stop_data", "Additional stop parameters")
    ],
    description="Enhanced full stop command with parameters",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_FULLSTOP2 packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_FULLSTOP2.packet_id,
        'packet_name': PLO_FULLSTOP2.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_FULLSTOP2.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
