#!/usr/bin/env python3
"""
PLO_SERVERTEXT (Packet 82) - Server text message

This packet delivers a server-wide text message.
Used for announcements, system messages, and broadcasts.

The packet format is:
- Message type (GCHAR) - type of server message
- Message content (STRING_GCHAR_LEN) - the server message text
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


PLO_SERVERTEXT = PacketStructure(
    packet_id=82,
    name="PLO_SERVERTEXT",
    fields=[
        gchar_field("message_type", "Type of server message"),
        string_gchar_len_field("message_content", "Server message text")
    ],
    description="Server text message/announcement",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_SERVERTEXT packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_SERVERTEXT.packet_id,
        'packet_name': PLO_SERVERTEXT.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_SERVERTEXT.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
