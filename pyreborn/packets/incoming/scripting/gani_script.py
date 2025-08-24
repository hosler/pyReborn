#!/usr/bin/env python3
"""
PLO_GANISCRIPT (Packet 134) - Gani animation script

This packet provides animation scripts for GANIs.
Used for complex character animations and effects.

The packet format is:
- Gani name (STRING_GCHAR_LEN) - name of the GANI animation
- Script data (VARIABLE_DATA) - animation script and timing data
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_GANISCRIPT = PacketStructure(
    packet_id=134,
    name="PLO_GANISCRIPT",
    fields=[
        string_gchar_len_field("gani_name", "Name of GANI animation"),
        variable_data_field("script_data", "Animation script and timing data")
    ],
    description="GANI animation script data",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_GANISCRIPT packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_GANISCRIPT.packet_id,
        'packet_name': PLO_GANISCRIPT.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_GANISCRIPT.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
