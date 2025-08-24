#!/usr/bin/env python3
"""
PLO_BOARDLAYER (Packet 107) - Board layer data

This packet provides layer data for level boards.
Contains layered board information for complex displays.

The packet format is:
- Layer ID (GCHAR) - identifier for the board layer
- Layer data (VARIABLE_DATA) - encoded layer board content
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_BOARDLAYER = PacketStructure(
    packet_id=107,
    name="PLO_BOARDLAYER",
    fields=[
        gchar_field("layer_id", "Board layer identifier"),
        variable_data_field("layer_data", "Encoded layer board content")
    ],
    description="Board layer data for complex displays",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_BOARDLAYER packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_BOARDLAYER.packet_id,
        'packet_name': PLO_BOARDLAYER.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_BOARDLAYER.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
