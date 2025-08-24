#!/usr/bin/env python3
"""
PLO_UNFREEZEPLAYER (Packet 155) - Unfreeze player

This packet unfreezes a previously frozen player.
Restores player movement and interaction.

The packet format is:
- Player ID (GSHORT) - ID of player to unfreeze
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


PLO_UNFREEZEPLAYER = PacketStructure(
    packet_id=155,
    name="PLO_UNFREEZEPLAYER",
    fields=[
        gshort_field("player_id", "ID of player to unfreeze")
    ],
    description="Unfreeze a previously frozen player",
    variable_length=False
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_UNFREEZEPLAYER packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_UNFREEZEPLAYER.packet_id,
        'packet_name': PLO_UNFREEZEPLAYER.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_UNFREEZEPLAYER.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
