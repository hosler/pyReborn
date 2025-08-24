#!/usr/bin/env python3
"""
PLO_THROWCARRIED (Packet 21) - Throw carried object

This packet notifies the client that a player has thrown a carried
object (like a pot, bush, or other throwable item).

The packet format is:
- Throw X coordinate (GCHAR) - starting X position
- Throw Y coordinate (GCHAR) - starting Y position
- Throw direction (GCHAR) - direction of throw
- Object type (GCHAR) - type of object being thrown
- Thrower player ID (GSHORT) - player who threw the object
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


PLO_THROWCARRIED = PacketStructure(
    packet_id=21,
    name="PLO_THROWCARRIED",
    fields=[
        gchar_field("x_coord", "Throw starting X coordinate"),
        gchar_field("y_coord", "Throw starting Y coordinate"),
        gchar_field("direction", "Direction of throw"),
        gchar_field("object_type", "Type of object being thrown"),
        gshort_field("thrower_id", "Player ID who threw the object")
    ],
    description="Throw carried object projectile",
    variable_length=False
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_THROWCARRIED packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_THROWCARRIED.packet_id,
        'packet_name': PLO_THROWCARRIED.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_THROWCARRIED.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
