#!/usr/bin/env python3
"""
PLO_GHOSTMODE (Packet 170) - Ghost mode notification

This packet controls or indicates ghost mode status.
In ghost mode, players may be invisible or have special properties.

The packet format is:
- Ghost state (GCHAR) - ghost mode on/off or type
- Ghost data (VARIABLE_DATA) - additional ghost mode configuration
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_GHOSTMODE = PacketStructure(
    packet_id=170,
    name="PLO_GHOSTMODE",
    fields=[
        gchar_field("ghost_state", "Ghost mode state or type"),
        variable_data_field("ghost_data", "Ghost mode configuration")
    ],
    description="Ghost mode notification and configuration",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_GHOSTMODE packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_GHOSTMODE.packet_id,
        'packet_name': PLO_GHOSTMODE.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_GHOSTMODE.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
