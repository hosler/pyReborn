#!/usr/bin/env python3
"""
PLO_PRIVATEMESSAGE (Packet 37) - Private message

This packet delivers a private message from one player to another.
Private messages are only visible to the sender and recipient.

The packet format is:
- Sender player ID (GSHORT) - ID of player sending the message
- Message text (VARIABLE_DATA) - the private message content
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_PRIVATEMESSAGE = PacketStructure(
    packet_id=37,
    name="PLO_PRIVATEMESSAGE",
    fields=[
        gshort_field("sender_id", "ID of player sending the message"),
        variable_data_field("message_text", "Private message content")
    ],
    description="Private message between players",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_PRIVATEMESSAGE packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_PRIVATEMESSAGE.packet_id,
        'packet_name': PLO_PRIVATEMESSAGE.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_PRIVATEMESSAGE.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
