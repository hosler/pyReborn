#!/usr/bin/env python3
"""
PLO_PLAYERSTATUS (Packet 62) - Player status update

This packet updates player status information.
Used for away status, busy flags, and player states.

The packet format is:
- Player ID (GSHORT) - ID of the player
- Status flags (GCHAR) - status flags and indicators
- Status message (STRING_GCHAR_LEN) - custom status message
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


PLO_PLAYERSTATUS = PacketStructure(
    packet_id=62,
    name="PLO_PLAYERSTATUS",
    fields=[
        gshort_field("player_id", "ID of the player"),
        gchar_field("status_flags", "Status flags and indicators"),
        string_gchar_len_field("status_message", "Custom status message")
    ],
    description="Player status update",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_PLAYERSTATUS packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_PLAYERSTATUS.packet_id,
        'packet_name': PLO_PLAYERSTATUS.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_PLAYERSTATUS.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
