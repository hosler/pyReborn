#!/usr/bin/env python3
"""
PLO_HIDENPCS (Packet 151) - Hide NPCs

This packet hides NPCs from view.
Used for conditional NPC visibility and special effects.

The packet format is:
- Hide options (VARIABLE_DATA) - NPC hiding configuration and filters
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_HIDENPCS = PacketStructure(
    packet_id=151,
    name="PLO_HIDENPCS",
    fields=[
        variable_data_field("hide_options", "NPC hiding configuration and filters")
    ],
    description="Hide NPCs from view",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_HIDENPCS packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_HIDENPCS.packet_id,
        'packet_name': PLO_HIDENPCS.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_HIDENPCS.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
