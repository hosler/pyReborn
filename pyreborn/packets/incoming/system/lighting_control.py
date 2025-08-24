#!/usr/bin/env python3
"""
PLO_LIGHTINGCONTROL (Packet 66) - Lighting and visual effects

This packet controls lighting effects and visual atmosphere.
Used for day/night cycles, special effects, and environmental lighting.

The packet format is:
- Lighting type (GCHAR) - type of lighting effect
- Light intensity (GCHAR) - brightness/intensity level
- Lighting data (VARIABLE_DATA) - color, position, and effect parameters
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_LIGHTINGCONTROL = PacketStructure(
    packet_id=66,
    name="PLO_LIGHTINGCONTROL",
    fields=[
        gchar_field("lighting_type", "Type of lighting effect"),
        gchar_field("light_intensity", "Brightness/intensity level"),
        variable_data_field("lighting_data", "Color, position, and effect parameters")
    ],
    description="Lighting and visual effects control",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_LIGHTINGCONTROL packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_LIGHTINGCONTROL.packet_id,
        'packet_name': PLO_LIGHTINGCONTROL.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_LIGHTINGCONTROL.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
