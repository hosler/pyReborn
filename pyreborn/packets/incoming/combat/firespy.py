#!/usr/bin/env python3
"""
PLO_FIRESPY (Packet 20) - Fire spy projectile

This packet notifies the client that a firespy projectile has been
fired. Firespy is a special weapon that creates fire effects.

The packet format is:
- Firespy X coordinate (GCHAR) - starting X position
- Firespy Y coordinate (GCHAR) - starting Y position
- Firespy direction (GCHAR) - direction of travel
- Firespy power (GCHAR) - fire power/intensity
- Owner player ID (GSHORT) - player who fired the firespy
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


PLO_FIRESPY = PacketStructure(
    packet_id=20,
    name="PLO_FIRESPY",
    fields=[
        gchar_field("x_coord", "Firespy starting X coordinate"),
        gchar_field("y_coord", "Firespy starting Y coordinate"),
        gchar_field("direction", "Direction of travel"),
        gchar_field("fire_power", "Fire power/intensity"),
        gshort_field("owner_id", "Player ID who fired the firespy")
    ],
    description="Fire spy projectile",
    variable_length=False
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_FIRESPY packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_FIRESPY.packet_id,
        'packet_name': PLO_FIRESPY.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_FIRESPY.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
