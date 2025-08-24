#!/usr/bin/env python3
"""
PLO_NPCWEAPONADD (Packet 33) - Add weapon to NPC

This packet notifies the client that an NPC has equipped or created a weapon.
NPCs can have custom weapons with special behaviors and appearances.

The packet format is:
- NPC ID (GSHORT) - NPC that owns the weapon
- Weapon name (STRING_GCHAR_LEN) - weapon identifier/script name
- Weapon image (STRING_GCHAR_LEN) - weapon sprite/appearance
- Weapon script (VARIABLE_DATA) - weapon behavior script
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_NPCWEAPONADD = PacketStructure(
    packet_id=33,
    name="PLO_NPCWEAPONADD",
    fields=[
        gshort_field("npc_id", "NPC that owns the weapon"),
        string_gchar_len_field("weapon_name", "Weapon identifier/script name"),
        string_gchar_len_field("weapon_image", "Weapon sprite/appearance"),
        variable_data_field("weapon_script", "Weapon behavior script")
    ],
    description="Add weapon to NPC",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_NPCWEAPONADD packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_NPCWEAPONADD.packet_id,
        'packet_name': PLO_NPCWEAPONADD.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_NPCWEAPONADD.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
