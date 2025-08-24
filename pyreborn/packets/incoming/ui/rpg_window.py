#!/usr/bin/env python3
"""
PLO_RPGWINDOW (Packet 179) - RPG window display

This packet controls RPG-style windows and interfaces.
Used for menus, dialogs, inventory, and other UI elements.

The packet format is:
- Window type (GCHAR) - type of RPG window to display
- Window position X (GSHORT) - X coordinate for window
- Window position Y (GSHORT) - Y coordinate for window
- Window data (VARIABLE_DATA) - window content and configuration
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_RPGWINDOW = PacketStructure(
    packet_id=179,
    name="PLO_RPGWINDOW",
    fields=[
        gchar_field("window_type", "Type of RPG window to display"),
        gshort_field("window_x", "X coordinate for window"),
        gshort_field("window_y", "Y coordinate for window"),
        variable_data_field("window_data", "Window content and configuration")
    ],
    description="RPG window/interface display",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_RPGWINDOW packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_RPGWINDOW.packet_id,
        'packet_name': PLO_RPGWINDOW.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_RPGWINDOW.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
