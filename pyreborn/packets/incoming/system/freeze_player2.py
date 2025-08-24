#!/usr/bin/env python3
"""
PLO_FREEZEPLAYER2 (Packet 154) - Enhanced freeze player

This packet freezes a player with enhanced options.
Extended version of freeze with additional parameters.

The packet format is:
- Player ID (GSHORT) - ID of player to freeze
- Freeze options (VARIABLE_DATA) - freeze type and duration settings
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_FREEZEPLAYER2 = PacketStructure(
    packet_id=154,
    name="PLO_FREEZEPLAYER2",
    fields=[
        gshort_field("player_id", "ID of player to freeze"),
        variable_data_field("freeze_options", "Freeze type and duration settings")
    ],
    description="Enhanced freeze player with options",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_FREEZEPLAYER2 packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_FREEZEPLAYER2.packet_id,
        'packet_name': PLO_FREEZEPLAYER2.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_FREEZEPLAYER2.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
