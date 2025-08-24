#!/usr/bin/env python3
"""
PLO_BIGMAP (Packet 171) - Big map display

This packet provides data for the big map (full world map) display.
Shows the complete world layout with level connections.

The packet format is:
- Map data (VARIABLE_DATA) - encoded big map information including
  level positions, connections, and visual representation
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_BIGMAP = PacketStructure(
    packet_id=171,
    name="PLO_BIGMAP",
    fields=[
        variable_data_field("map_data", "Encoded big map information")
    ],
    description="Big map (world overview) display data",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_BIGMAP packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_BIGMAP.packet_id,
        'packet_name': PLO_BIGMAP.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_BIGMAP.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
