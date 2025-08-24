#!/usr/bin/env python3
"""
PLO_PLAYERBAN (Packet 58) - Ban player from server

This packet bans a player from the server.
Prevents the player from reconnecting.

The packet format is:
- Ban duration (GINT4) - ban duration in seconds (0 = permanent)
- Ban reason (STRING_GCHAR_LEN) - reason for the ban
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gint4_field(name: str, description: str) -> PacketField:
    """Helper to create a GINT4 field"""
    return PacketField(name, PacketFieldType.GINT4, description=description)


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


PLO_PLAYERBAN = PacketStructure(
    packet_id=58,
    name="PLO_PLAYERBAN",
    fields=[
        gint4_field("ban_duration", "Ban duration in seconds"),
        string_gchar_len_field("ban_reason", "Reason for the ban")
    ],
    description="Ban player from server",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_PLAYERBAN packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_PLAYERBAN.packet_id,
        'packet_name': PLO_PLAYERBAN.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_PLAYERBAN.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
