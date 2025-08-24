#!/usr/bin/env python3
"""
PLO_WEATHERUPDATE (Packet 64) - Weather system update

This packet updates weather conditions in the game world.
Used for environmental effects like rain, snow, storms, etc.

The packet format is:
- Weather type (GCHAR) - type of weather (clear, rain, snow, storm, etc.)
- Weather intensity (GCHAR) - intensity level of the weather
- Weather data (VARIABLE_DATA) - additional weather parameters and effects
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_WEATHERUPDATE = PacketStructure(
    packet_id=64,
    name="PLO_WEATHERUPDATE",
    fields=[
        gchar_field("weather_type", "Type of weather"),
        gchar_field("weather_intensity", "Intensity level of weather"),
        variable_data_field("weather_data", "Additional weather parameters")
    ],
    description="Weather system update",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_WEATHERUPDATE packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_WEATHERUPDATE.packet_id,
        'packet_name': PLO_WEATHERUPDATE.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_WEATHERUPDATE.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
