#!/usr/bin/env python3
"""
PLO_BADDYHURT (Packet 27) - Baddy hurt notification

This packet notifies the client that a baddy (enemy) has taken damage.
Used for combat feedback and baddy health management.

The packet format is:
- Baddy ID (GSHORT) - ID of baddy that was hurt
- Damage amount (GCHAR) - amount of damage taken
- Damage type (GCHAR) - type of damage (sword, bomb, etc.)
- Remaining health (GCHAR) - baddy's health after damage
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


PLO_BADDYHURT = PacketStructure(
    packet_id=27,
    name="PLO_BADDYHURT",
    fields=[
        gshort_field("baddy_id", "ID of baddy that was hurt"),
        gchar_field("damage_amount", "Amount of damage taken"),
        gchar_field("damage_type", "Type of damage (sword, bomb, etc.)"),
        gchar_field("remaining_health", "Baddy's health after damage")
    ],
    description="Baddy hurt/damage notification",
    variable_length=False
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_BADDYHURT packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_BADDYHURT.packet_id,
        'packet_name': PLO_BADDYHURT.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_BADDYHURT.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
