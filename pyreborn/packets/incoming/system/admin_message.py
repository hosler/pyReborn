#!/usr/bin/env python3
"""
PLO_ADMINMESSAGE (Packet 57) - Admin message

This packet delivers administrative messages to players.
Used for server announcements and admin communications.

The packet format is:
- Admin name (STRING_GCHAR_LEN) - name of the admin
- Message content (STRING_GCHAR_LEN) - the admin message text
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


PLO_ADMINMESSAGE = PacketStructure(
    packet_id=57,
    name="PLO_ADMINMESSAGE",
    fields=[
        string_gchar_len_field("admin_name", "Name of the admin"),
        string_gchar_len_field("message_content", "Admin message text")
    ],
    description="Administrative message to players",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_ADMINMESSAGE packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_ADMINMESSAGE.packet_id,
        'packet_name': PLO_ADMINMESSAGE.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_ADMINMESSAGE.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
