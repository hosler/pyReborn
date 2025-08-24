#!/usr/bin/env python3
"""
PLO_UNKNOWN197 (Packet 197) - Unknown packet type 197

This packet's exact purpose is not yet documented.
Reserved for future functionality or special server features.

The packet format is:
- Unknown data (VARIABLE_DATA) - packet data of unknown format
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_UNKNOWN197 = PacketStructure(
    packet_id=197,
    name="PLO_UNKNOWN197",
    fields=[
        variable_data_field("unknown_data", "Packet data of unknown format")
    ],
    description="Unknown packet type 197",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_UNKNOWN197 packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_UNKNOWN197.packet_id,
        'packet_name': PLO_UNKNOWN197.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_UNKNOWN197.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
