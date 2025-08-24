#!/usr/bin/env python3
"""
PLO_STARTMESSAGE (Packet 41) - Server start message

This packet provides the server's startup/welcome message.
Displayed when the player first connects to the server.

The packet format is:
- Message content (STRING_GCHAR_LEN) - the startup message text
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


PLO_STARTMESSAGE = PacketStructure(
    packet_id=41,
    name="PLO_STARTMESSAGE",
    fields=[
        string_gchar_len_field("message_content", "Server startup message")
    ],
    description="Server startup/welcome message",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_STARTMESSAGE packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_STARTMESSAGE.packet_id,
        'packet_name': PLO_STARTMESSAGE.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_STARTMESSAGE.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
