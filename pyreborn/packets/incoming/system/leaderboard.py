#!/usr/bin/env python3
"""
PLO_LEADERBOARD (Packet 73) - Player leaderboard data

This packet provides leaderboard and ranking information.
Used for competitive systems, high scores, and player standings.

The packet format is:
- Leaderboard type (GCHAR) - type of leaderboard (kills, score, level, etc.)
- Player count (GCHAR) - number of players in leaderboard
- Leaderboard data (VARIABLE_DATA) - ranked player data and statistics
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_LEADERBOARD = PacketStructure(
    packet_id=73,
    name="PLO_LEADERBOARD",
    fields=[
        gchar_field("leaderboard_type", "Type of leaderboard"),
        gchar_field("player_count", "Number of players in leaderboard"),
        variable_data_field("leaderboard_data", "Ranked player data and statistics")
    ],
    description="Player leaderboard and ranking data",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_LEADERBOARD packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_LEADERBOARD.packet_id,
        'packet_name': PLO_LEADERBOARD.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_LEADERBOARD.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
