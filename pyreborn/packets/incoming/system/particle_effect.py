#!/usr/bin/env python3
"""
PLO_PARTICLEEFFECT (Packet 67) - Particle effects system

This packet creates and controls particle effects.
Used for visual enhancement, magic effects, and environmental particles.

The packet format is:
- Effect type (GCHAR) - type of particle effect
- Effect position X (GSHORT) - X coordinate for effect
- Effect position Y (GSHORT) - Y coordinate for effect
- Effect data (VARIABLE_DATA) - particle parameters, duration, and settings
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_PARTICLEEFFECT = PacketStructure(
    packet_id=67,
    name="PLO_PARTICLEEFFECT",
    fields=[
        gchar_field("effect_type", "Type of particle effect"),
        gshort_field("effect_x", "X coordinate for effect"),
        gshort_field("effect_y", "Y coordinate for effect"),
        variable_data_field("effect_data", "Particle parameters and settings")
    ],
    description="Particle effects system",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_PARTICLEEFFECT packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_PARTICLEEFFECT.packet_id,
        'packet_name': PLO_PARTICLEEFFECT.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_PARTICLEEFFECT.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
