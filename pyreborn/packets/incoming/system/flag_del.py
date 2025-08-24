#!/usr/bin/env python3
"""
PLO_FLAGDEL (Packet 31) - Delete server flag

This packet notifies the client that a server flag has been deleted.
Used to remove global game state variables.

The packet format is:
- Flag name (STRING_GCHAR_LEN) - name of the flag being deleted
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


PLO_FLAGDEL = PacketStructure(
    packet_id=31,
    name="PLO_FLAGDEL",
    fields=[
        string_gchar_len_field("flag_name", "Name of the flag being deleted")
    ],
    description="Delete server flag",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_FLAGDEL packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_FLAGDEL.packet_id,
        'packet_name': PLO_FLAGDEL.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_FLAGDEL.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
