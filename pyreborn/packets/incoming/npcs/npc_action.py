#!/usr/bin/env python3
"""
PLO_NPCACTION (Packet 26) - NPC action/animation

This packet notifies the client that an NPC is performing an action
or animation, such as attacking, moving, or displaying special effects.

The packet format is:
- NPC ID (GSHORT) - unique identifier for the NPC
- Action type (GCHAR) - type of action being performed
- Action data (VARIABLE_DATA) - additional action parameters
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_NPCACTION = PacketStructure(
    packet_id=26,
    name="PLO_NPCACTION",
    fields=[
        gshort_field("npc_id", "NPC unique identifier"),
        gchar_field("action_type", "Type of action being performed"),
        variable_data_field("action_data", "Additional action parameters")
    ],
    description="NPC action/animation",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_NPCACTION packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_NPCACTION.packet_id,
        'packet_name': PLO_NPCACTION.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_NPCACTION.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
