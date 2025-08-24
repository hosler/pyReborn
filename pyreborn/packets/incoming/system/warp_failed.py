#!/usr/bin/env python3
"""
PLO_WARPFAILED (Packet 15) - Warp failed

This packet notifies the client that a warp attempt has failed,
usually due to invalid destination or insufficient permissions.

The packet format is:
- Error message (VARIABLE_DATA) - reason why the warp failed
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_WARPFAILED = PacketStructure(
    packet_id=15,
    name="PLO_WARPFAILED",
    fields=[
        variable_data_field("error_message", "Reason why the warp failed")
    ],
    description="Warp attempt failed notification",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_WARPFAILED packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_WARPFAILED.packet_id,
        'packet_name': PLO_WARPFAILED.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_WARPFAILED.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
