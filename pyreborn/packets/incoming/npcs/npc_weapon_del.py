#!/usr/bin/env python3
"""
PLO_NPCWEAPONDEL (Packet 34) - Remove weapon from NPC

This packet notifies the client that an NPC's weapon has been removed
or destroyed and should no longer be displayed.

The packet format is:
- NPC ID (GSHORT) - NPC that owned the weapon
- Weapon name (STRING_GCHAR_LEN) - weapon identifier to remove
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


PLO_NPCWEAPONDEL = PacketStructure(
    packet_id=34,
    name="PLO_NPCWEAPONDEL",
    fields=[
        gshort_field("npc_id", "NPC that owned the weapon"),
        string_gchar_len_field("weapon_name", "Weapon identifier to remove")
    ],
    description="Remove weapon from NPC",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_NPCWEAPONDEL packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_NPCWEAPONDEL.packet_id,
        'packet_name': PLO_NPCWEAPONDEL.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_NPCWEAPONDEL.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
