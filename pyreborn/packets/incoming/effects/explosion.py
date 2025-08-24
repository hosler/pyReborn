#!/usr/bin/env python3
"""
PLO_EXPLOSION (Packet 36) - Explosion effect

This packet creates an explosion visual effect on the level.
Used for bombs, weapons, or other destructive events.

The packet format is:
- Explosion X (GSHORT) - X coordinate of explosion center
- Explosion Y (GSHORT) - Y coordinate of explosion center
- Explosion type (GCHAR) - type/power of explosion
- Explosion data (VARIABLE_DATA) - additional explosion parameters
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


PLO_EXPLOSION = PacketStructure(
    packet_id=36,
    name="PLO_EXPLOSION",
    fields=[
        gshort_field("explosion_x", "X coordinate of explosion center"),
        gshort_field("explosion_y", "Y coordinate of explosion center"),
        gchar_field("explosion_type", "Type/power of explosion"),
        variable_data_field("explosion_data", "Additional explosion parameters")
    ],
    description="Explosion visual effect",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_EXPLOSION packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_EXPLOSION.packet_id,
        'packet_name': PLO_EXPLOSION.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_EXPLOSION.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
