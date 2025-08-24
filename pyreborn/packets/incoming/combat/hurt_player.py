#!/usr/bin/env python3
"""
PLO_HURTPLAYER (Packet 40) - Player hurt/damage

This packet notifies the client that a player has taken damage.
It's used for combat feedback and health management.

The packet format is:
- Player ID (GSHORT) - ID of player who was hurt (0 for self)
- Damage amount (GCHAR) - amount of damage taken
- Damage type (GCHAR) - type of damage (sword, bomb, etc.)
- Damage source X (GCHAR) - X coordinate of damage source
- Damage source Y (GCHAR) - Y coordinate of damage source
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


PLO_HURTPLAYER = PacketStructure(
    packet_id=40,
    name="PLO_HURTPLAYER",
    fields=[
        gshort_field("player_id", "ID of player who was hurt (0 for self)"),
        gchar_field("damage_amount", "Amount of damage taken"),
        gchar_field("damage_type", "Type of damage (sword, bomb, etc.)"),
        gchar_field("source_x", "X coordinate of damage source"),
        gchar_field("source_y", "Y coordinate of damage source")
    ],
    description="Player hurt/damage notification",
    variable_length=False
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_HURTPLAYER packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_HURTPLAYER.packet_id,
        'packet_name': PLO_HURTPLAYER.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_HURTPLAYER.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
