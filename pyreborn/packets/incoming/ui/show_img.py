#!/usr/bin/env python3
"""
PLO_SHOWIMG (Packet 32) - Show image

This packet instructs the client to display an image on screen.
Used for GUI elements, cutscenes, and visual effects.

The packet format is:
- Image name (STRING_GCHAR_LEN) - name/path of image to display
- Display X position (GSHORT) - X coordinate for image display
- Display Y position (GSHORT) - Y coordinate for image display
- Display options (VARIABLE_DATA) - additional display parameters
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_SHOWIMG = PacketStructure(
    packet_id=32,
    name="PLO_SHOWIMG",
    fields=[
        string_gchar_len_field("image_name", "Name/path of image to display"),
        gshort_field("display_x", "X coordinate for image display"),
        gshort_field("display_y", "Y coordinate for image display"),
        variable_data_field("display_options", "Additional display parameters")
    ],
    description="Display image on client screen",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_SHOWIMG packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_SHOWIMG.packet_id,
        'packet_name': PLO_SHOWIMG.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_SHOWIMG.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
