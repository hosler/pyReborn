#!/usr/bin/env python3
"""
PLO_NPCWEAPONSCRIPT (Packet 140) - NPC weapon script

This packet provides script data for NPC weapons.
Used for complex NPC weapon behaviors and attacks.

The packet format is:
- Weapon name (STRING_GCHAR_LEN) - name of the NPC weapon
- Script data (VARIABLE_DATA) - weapon script and behavior code
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_NPCWEAPONSCRIPT = PacketStructure(
    packet_id=140,
    name="PLO_NPCWEAPONSCRIPT",
    fields=[
        string_gchar_len_field("weapon_name", "Name of NPC weapon"),
        variable_data_field("script_data", "Weapon script and behavior code")
    ],
    description="NPC weapon script data",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_NPCWEAPONSCRIPT packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_NPCWEAPONSCRIPT.packet_id,
        'packet_name': PLO_NPCWEAPONSCRIPT.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_NPCWEAPONSCRIPT.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
