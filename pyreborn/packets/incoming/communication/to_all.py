#!/usr/bin/env python3
"""
PLO_TOALL (Packet 13) - Public chat message

This packet delivers a public chat message that is visible to all
players in the current level or area.

The packet format is:
- Sender player ID (GSHORT) - ID of player sending the message
- Message text (VARIABLE_DATA) - the public chat message content
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_TOALL = PacketStructure(
    packet_id=13,
    name="PLO_TOALL",
    fields=[
        gshort_field("sender_id", "ID of player sending the message"),
        variable_data_field("message_text", "Public chat message content")
    ],
    description="Public chat message to all players",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_TOALL packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_TOALL.packet_id,
        'packet_name': PLO_TOALL.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_TOALL.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
