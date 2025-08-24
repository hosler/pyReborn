#!/usr/bin/env python3
"""
PLO_ARROWADD (Packet 19) - Add arrow projectile to level

This packet notifies the client that an arrow has been fired and should
be displayed as a moving projectile.

The packet format is:
- Arrow X coordinate (GCHAR) - starting X position
- Arrow Y coordinate (GCHAR) - starting Y position  
- Arrow direction (GCHAR) - direction of travel (0-3: down, left, up, right)
- Arrow speed (GCHAR) - arrow velocity
- Arrow owner ID (GSHORT) - player who fired the arrow
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


PLO_ARROWADD = PacketStructure(
    packet_id=19,
    name="PLO_ARROWADD",
    fields=[
        gchar_field("x_coord", "Arrow starting X coordinate"),
        gchar_field("y_coord", "Arrow starting Y coordinate"),
        gchar_field("direction", "Arrow direction (0-3: down,left,up,right)"),
        gchar_field("speed", "Arrow velocity"),
        gshort_field("owner_id", "Player ID who fired the arrow")
    ],
    description="Add arrow projectile to level",
    variable_length=False
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_ARROWADD packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_ARROWADD.packet_id,
        'packet_name': PLO_ARROWADD.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_ARROWADD.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
