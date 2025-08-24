#!/usr/bin/env python3
"""
PLO_CRAFTINGSYSTEM (Packet 81) - Item crafting system

This packet manages item crafting and creation functionality.
Used for manufacturing, alchemy, enchanting, and item creation systems.

The packet format is:
- Crafting type (GCHAR) - type of crafting operation
- Recipe ID (GSHORT) - identifier for the crafting recipe
- Crafting data (VARIABLE_DATA) - materials, results, and crafting parameters
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


PLO_CRAFTINGSYSTEM = PacketStructure(
    packet_id=81,
    name="PLO_CRAFTINGSYSTEM",
    fields=[
        gchar_field("crafting_type", "Type of crafting operation"),
        gshort_field("recipe_id", "Identifier for crafting recipe"),
        variable_data_field("crafting_data", "Materials, results, and parameters")
    ],
    description="Item crafting and creation system",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_CRAFTINGSYSTEM packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_CRAFTINGSYSTEM.packet_id,
        'packet_name': PLO_CRAFTINGSYSTEM.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_CRAFTINGSYSTEM.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
