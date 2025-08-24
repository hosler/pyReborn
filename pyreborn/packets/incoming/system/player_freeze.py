#!/usr/bin/env python3
"""
PLO_PLAYERFREEZE (Packet 52) - Freeze player movement

This packet freezes a player's movement and actions.
Used for timeouts, admin actions, or game mechanics.

The packet format is:
- Player ID (GSHORT) - ID of player to freeze
- Freeze duration (GSHORT) - freeze time in seconds (0 = permanent)
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


PLO_PLAYERFREEZE = PacketStructure(
    packet_id=52,
    name="PLO_PLAYERFREEZE",
    fields=[
        gshort_field("player_id", "ID of player to freeze"),
        gshort_field("freeze_duration", "Freeze time in seconds")
    ],
    description="Freeze player movement and actions",
    variable_length=False
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_PLAYERFREEZE packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_PLAYERFREEZE.packet_id,
        'packet_name': PLO_PLAYERFREEZE.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_PLAYERFREEZE.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
