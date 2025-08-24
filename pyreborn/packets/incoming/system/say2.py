#!/usr/bin/env python3
"""
PLO_SAY2 (Packet 153) - Enhanced say message

This packet provides enhanced say/chat functionality.
Extended version of basic say with additional features.

The packet format is:
- Player ID (GSHORT) - ID of player speaking
- Message data (VARIABLE_DATA) - enhanced message with formatting/metadata
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_SAY2 = PacketStructure(
    packet_id=153,
    name="PLO_SAY2",
    fields=[
        gshort_field("player_id", "ID of player speaking"),
        variable_data_field("message_data", "Enhanced message with formatting")
    ],
    description="Enhanced say/chat message",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_SAY2 packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_SAY2.packet_id,
        'packet_name': PLO_SAY2.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_SAY2.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
