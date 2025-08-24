#!/usr/bin/env python3
"""
PLO_GHOSTICON (Packet 174) - Ghost icon display

This packet displays an icon in ghost mode.
Used for special visual effects or indicators visible to ghosts.

The packet format is:
- Icon position X (GSHORT) - X coordinate for icon
- Icon position Y (GSHORT) - Y coordinate for icon
- Icon type (GCHAR) - type or ID of icon to display
- Icon data (VARIABLE_DATA) - additional icon configuration
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_GHOSTICON = PacketStructure(
    packet_id=174,
    name="PLO_GHOSTICON",
    fields=[
        gshort_field("icon_x", "X coordinate for icon display"),
        gshort_field("icon_y", "Y coordinate for icon display"),
        gchar_field("icon_type", "Type or ID of icon"),
        variable_data_field("icon_data", "Icon configuration data")
    ],
    description="Ghost mode icon display",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_GHOSTICON packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_GHOSTICON.packet_id,
        'packet_name': PLO_GHOSTICON.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_GHOSTICON.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
