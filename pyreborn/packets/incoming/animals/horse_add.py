#!/usr/bin/env python3
"""
PLO_HORSEADD (Packet 17) - Add horse to level

This packet notifies the client that a horse has been placed on the level.
Horses are rideable animals that provide faster movement.

The packet format is:
- Horse X coordinate (GCHAR) - X position of horse
- Horse Y coordinate (GCHAR) - Y position of horse
- Horse type (GCHAR) - type/color of horse
- Horse direction (GCHAR) - direction horse is facing
- Horse owner ID (GSHORT) - player who owns the horse (optional)
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


PLO_HORSEADD = PacketStructure(
    packet_id=17,
    name="PLO_HORSEADD",
    fields=[
        gchar_field("x_coord", "Horse X coordinate"),
        gchar_field("y_coord", "Horse Y coordinate"),
        gchar_field("horse_type", "Type/color of horse"),
        gchar_field("direction", "Direction horse is facing"),
        gshort_field("owner_id", "Player who owns the horse")
    ],
    description="Add horse to level",
    variable_length=False
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_HORSEADD packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_HORSEADD.packet_id,
        'packet_name': PLO_HORSEADD.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_HORSEADD.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
