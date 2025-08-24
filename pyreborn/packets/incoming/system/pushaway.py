#!/usr/bin/env python3
"""
PLO_PUSHAWAY (Packet 38) - Push away effect

This packet notifies the client that a player or object should be
pushed away from a certain position, typically from explosions or impacts.

The packet format is:
- Target player ID (GSHORT) - ID of player being pushed (0 for self)
- Push source X (GCHAR) - X coordinate of push source
- Push source Y (GCHAR) - Y coordinate of push source
- Push force (GCHAR) - strength of the push effect
- Push direction (GCHAR) - direction of the push
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


PLO_PUSHAWAY = PacketStructure(
    packet_id=38,
    name="PLO_PUSHAWAY",
    fields=[
        gshort_field("target_player_id", "ID of player being pushed (0 for self)"),
        gchar_field("push_source_x", "X coordinate of push source"),
        gchar_field("push_source_y", "Y coordinate of push source"),
        gchar_field("push_force", "Strength of the push effect"),
        gchar_field("push_direction", "Direction of the push")
    ],
    description="Push away effect from explosions/impacts",
    variable_length=False
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_PUSHAWAY packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_PUSHAWAY.packet_id,
        'packet_name': PLO_PUSHAWAY.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_PUSHAWAY.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
