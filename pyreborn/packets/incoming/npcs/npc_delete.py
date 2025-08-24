#!/usr/bin/env python3
"""
PLO_NPCDEL (Packet 29) - Delete NPC from level

This packet notifies the client that an NPC has been removed from the level
and should no longer be displayed.

The packet format is:
- NPC ID (GSHORT) - unique identifier of the NPC to remove
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


PLO_NPCDEL = PacketStructure(
    packet_id=29,
    name="PLO_NPCDEL",
    fields=[
        gshort_field("npc_id", "NPC unique identifier to remove")
    ],
    description="Delete NPC from level",
    variable_length=False
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_NPCDEL packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_NPCDEL.packet_id,
        'packet_name': PLO_NPCDEL.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_NPCDEL.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
