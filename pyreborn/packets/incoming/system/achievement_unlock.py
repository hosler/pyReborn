#!/usr/bin/env python3
"""
PLO_ACHIEVEMENTUNLOCK (Packet 72) - Achievement unlock notification

This packet notifies when a player unlocks an achievement.
Used for progression systems, rewards, and player recognition.

The packet format is:
- Achievement ID (GSHORT) - unique identifier for the achievement
- Achievement name (STRING_GCHAR_LEN) - display name of achievement
- Achievement data (VARIABLE_DATA) - description, rewards, and metadata
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


PLO_ACHIEVEMENTUNLOCK = PacketStructure(
    packet_id=72,
    name="PLO_ACHIEVEMENTUNLOCK",
    fields=[
        gshort_field("achievement_id", "Unique achievement identifier"),
        string_gchar_len_field("achievement_name", "Display name of achievement"),
        variable_data_field("achievement_data", "Description, rewards, and metadata")
    ],
    description="Achievement unlock notification",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_ACHIEVEMENTUNLOCK packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_ACHIEVEMENTUNLOCK.packet_id,
        'packet_name': PLO_ACHIEVEMENTUNLOCK.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_ACHIEVEMENTUNLOCK.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
