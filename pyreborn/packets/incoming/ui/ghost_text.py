#!/usr/bin/env python3
"""
PLO_GHOSTTEXT (Packet 173) - Ghost text display

This packet displays text in ghost mode.
Used for special text effects or messages visible to ghosts.

The packet format is:
- Text position X (GSHORT) - X coordinate for text
- Text position Y (GSHORT) - Y coordinate for text
- Text content (STRING_GCHAR_LEN) - the ghost text to display
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


PLO_GHOSTTEXT = PacketStructure(
    packet_id=173,
    name="PLO_GHOSTTEXT",
    fields=[
        gshort_field("text_x", "X coordinate for text display"),
        gshort_field("text_y", "Y coordinate for text display"),
        string_gchar_len_field("text_content", "Ghost text content")
    ],
    description="Ghost mode text display",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_GHOSTTEXT packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_GHOSTTEXT.packet_id,
        'packet_name': PLO_GHOSTTEXT.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_GHOSTTEXT.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
