#!/usr/bin/env python3
"""
PLO_NPCDEL2 (Packet 150) - Enhanced NPC deletion

This packet removes an NPC with enhanced options.
Extended version of NPC deletion with additional parameters.

The packet format is:
- NPC ID (GSHORT) - unique identifier of NPC to remove
- Delete options (VARIABLE_DATA) - enhanced deletion parameters
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_NPCDEL2 = PacketStructure(
    packet_id=150,
    name="PLO_NPCDEL2",
    fields=[
        gshort_field("npc_id", "NPC ID to remove"),
        variable_data_field("delete_options", "Enhanced deletion parameters")
    ],
    description="Enhanced NPC deletion with options",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_NPCDEL2 packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_NPCDEL2.packet_id,
        'packet_name': PLO_NPCDEL2.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_NPCDEL2.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
