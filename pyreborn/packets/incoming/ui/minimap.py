#!/usr/bin/env python3
"""
PLO_MINIMAP (Packet 172) - Minimap display

This packet provides data for the minimap display.
Shows a small overview of the current level and nearby areas.

The packet format is:
- Minimap data (VARIABLE_DATA) - encoded minimap information including
  current level layout, player positions, and important objects
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_MINIMAP = PacketStructure(
    packet_id=172,
    name="PLO_MINIMAP",
    fields=[
        variable_data_field("minimap_data", "Encoded minimap information")
    ],
    description="Minimap display data",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_MINIMAP packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_MINIMAP.packet_id,
        'packet_name': PLO_MINIMAP.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_MINIMAP.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
