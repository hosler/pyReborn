#!/usr/bin/env python3
"""
PLO_NC_CLASSADD (Packet 163) - NPC-Control class addition

This packet adds a new class for NPC-Control scripting.
Used for server-side NPC class definitions and behaviors.

The packet format is:
- Class name (STRING_GCHAR_LEN) - name of the NPC class
- Class data (VARIABLE_DATA) - class definition and methods
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_NC_CLASSADD = PacketStructure(
    packet_id=163,
    name="PLO_NC_CLASSADD",
    fields=[
        string_gchar_len_field("class_name", "Name of NPC class"),
        variable_data_field("class_data", "Class definition and methods")
    ],
    description="NPC-Control class addition",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_NC_CLASSADD packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_NC_CLASSADD.packet_id,
        'packet_name': PLO_NC_CLASSADD.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_NC_CLASSADD.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
