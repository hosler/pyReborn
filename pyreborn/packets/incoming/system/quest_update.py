#!/usr/bin/env python3
"""
PLO_QUESTUPDATE (Packet 77) - Quest system update

This packet updates quest progress and status.
Used for mission systems, objectives, and storyline progression.

The packet format is:
- Quest ID (GSHORT) - unique identifier for the quest
- Quest status (GCHAR) - current status (active, completed, failed, etc.)
- Quest progress (GCHAR) - progress percentage or step number
- Quest data (VARIABLE_DATA) - objectives, rewards, and description
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


PLO_QUESTUPDATE = PacketStructure(
    packet_id=77,
    name="PLO_QUESTUPDATE",
    fields=[
        gshort_field("quest_id", "Unique identifier for the quest"),
        gchar_field("quest_status", "Current quest status"),
        gchar_field("quest_progress", "Progress percentage or step"),
        variable_data_field("quest_data", "Objectives, rewards, and description")
    ],
    description="Quest system update and progress",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_QUESTUPDATE packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_QUESTUPDATE.packet_id,
        'packet_name': PLO_QUESTUPDATE.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_QUESTUPDATE.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
