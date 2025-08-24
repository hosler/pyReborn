#!/usr/bin/env python3
"""
PLO_SERVERWARP (Packet 178) - Server-initiated warp

This packet forces the player to warp to a specific location.
Server can override player position for teleportation, respawn, etc.

The packet format is:
- Level name (STRING_GCHAR_LEN) - destination level name
- X position (GSHORT) - destination X coordinate
- Y position (GSHORT) - destination Y coordinate
- Z position (GCHAR) - destination Z layer (height)
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


PLO_SERVERWARP = PacketStructure(
    packet_id=178,
    name="PLO_SERVERWARP",
    fields=[
        string_gchar_len_field("level_name", "Destination level name"),
        gshort_field("x_position", "Destination X coordinate"),
        gshort_field("y_position", "Destination Y coordinate"),
        gchar_field("z_position", "Destination Z layer")
    ],
    description="Server-initiated player warp/teleportation",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_SERVERWARP packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_SERVERWARP.packet_id,
        'packet_name': PLO_SERVERWARP.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_SERVERWARP.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
