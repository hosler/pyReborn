#!/usr/bin/env python3
"""
PLO_MOVE2 (Packet 189) - Enhanced movement

This packet provides enhanced player movement functionality.
Extended version of basic movement with additional data.

The packet format is:
- Player ID (GSHORT) - ID of moving player
- Movement data (VARIABLE_DATA) - enhanced movement information
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_MOVE2 = PacketStructure(
    packet_id=189,
    name="PLO_MOVE2",
    fields=[
        gshort_field("player_id", "ID of moving player"),
        variable_data_field("movement_data", "Enhanced movement information")
    ],
    description="Enhanced player movement",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_MOVE2 packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_MOVE2.packet_id,
        'packet_name': PLO_MOVE2.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_MOVE2.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
