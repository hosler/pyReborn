#!/usr/bin/env python3
"""
PLO_DEFAULTWEAPON (Packet 43) - Default weapon assignment

This packet assigns a default weapon to the player.
Used for basic weapon setup when joining the server.

The packet format is:
- Weapon name (STRING_GCHAR_LEN) - name of the default weapon
- Weapon script (VARIABLE_DATA) - default weapon code/script
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_DEFAULTWEAPON = PacketStructure(
    packet_id=43,
    name="PLO_DEFAULTWEAPON",
    fields=[
        string_gchar_len_field("weapon_name", "Name of default weapon"),
        variable_data_field("weapon_script", "Default weapon code/script")
    ],
    description="Default weapon assignment for player",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_DEFAULTWEAPON packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_DEFAULTWEAPON.packet_id,
        'packet_name': PLO_DEFAULTWEAPON.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_DEFAULTWEAPON.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
