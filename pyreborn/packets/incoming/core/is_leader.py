#!/usr/bin/env python3
"""
PLO_ISLEADER (Packet 10) - Player is leader

This packet notifies the client about player leadership status,
used for guild leadership, party leadership, or other group roles.

The packet format is:
- Player ID (GSHORT) - ID of the player
- Leader status (GCHAR) - 1 if player is leader, 0 if not
- Leadership type (GCHAR) - type of leadership (guild, party, etc.)
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


PLO_ISLEADER = PacketStructure(
    packet_id=10,
    name="PLO_ISLEADER",
    fields=[
        gshort_field("player_id", "ID of the player"),
        gchar_field("leader_status", "1 if player is leader, 0 if not"),
        gchar_field("leadership_type", "Type of leadership (guild, party, etc.)")
    ],
    description="Player leadership status notification",
    variable_length=False
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_ISLEADER packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_ISLEADER.packet_id,
        'packet_name': PLO_ISLEADER.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_ISLEADER.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
