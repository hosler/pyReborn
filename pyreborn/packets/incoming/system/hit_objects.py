#!/usr/bin/env python3
"""
PLO_HITOBJECTS (Packet 46) - Hit objects notification

This packet notifies the client about objects that have been hit
by projectiles, swords, or other weapons. Used for damage feedback
and object interaction.

The packet format is:
- Hit X coordinate (GCHAR) - X position of hit
- Hit Y coordinate (GCHAR) - Y position of hit
- Hit type (GCHAR) - type of hit/weapon used
- Hit data (VARIABLE_DATA) - additional hit information
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_HITOBJECTS = PacketStructure(
    packet_id=46,
    name="PLO_HITOBJECTS",
    fields=[
        gchar_field("hit_x", "X position of hit"),
        gchar_field("hit_y", "Y position of hit"),
        gchar_field("hit_type", "Type of hit/weapon used"),
        variable_data_field("hit_data", "Additional hit information")
    ],
    description="Objects hit by weapons/projectiles",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_HITOBJECTS packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_HITOBJECTS.packet_id,
        'packet_name': PLO_HITOBJECTS.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_HITOBJECTS.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
