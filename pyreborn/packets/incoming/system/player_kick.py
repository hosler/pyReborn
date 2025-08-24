#!/usr/bin/env python3
"""
PLO_PLAYERKICK (Packet 53) - Kick player from server

This packet kicks a player from the server.
Forces disconnection with optional reason message.

The packet format is:
- Kick reason (STRING_GCHAR_LEN) - reason for the kick
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


PLO_PLAYERKICK = PacketStructure(
    packet_id=53,
    name="PLO_PLAYERKICK",
    fields=[
        string_gchar_len_field("kick_reason", "Reason for kicking player")
    ],
    description="Kick player from server",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_PLAYERKICK packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_PLAYERKICK.packet_id,
        'packet_name': PLO_PLAYERKICK.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_PLAYERKICK.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
