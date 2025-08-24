#!/usr/bin/env python3
"""
PLO_FLAGSET (Packet 28) - Set server flag

This packet notifies the client that a server flag has been set.
Server flags are used for global game state and scripting variables.

The packet format is:
- Flag name (STRING_GCHAR_LEN) - name of the flag being set
- Flag value (VARIABLE_DATA) - value assigned to the flag
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_FLAGSET = PacketStructure(
    packet_id=28,
    name="PLO_FLAGSET",
    fields=[
        string_gchar_len_field("flag_name", "Name of the flag being set"),
        variable_data_field("flag_value", "Value assigned to the flag")
    ],
    description="Set server flag for global state",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_FLAGSET packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_FLAGSET.packet_id,
        'packet_name': PLO_FLAGSET.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_FLAGSET.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
