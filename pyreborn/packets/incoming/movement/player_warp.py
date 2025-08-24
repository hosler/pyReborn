#!/usr/bin/env python3
"""
PLO_PLAYERWARP (Packet 14) - Player warp/teleport

This packet notifies the client that a player has warped/teleported
to a new position, either within the same level or to a different level.

The packet format is:
- Player ID (GSHORT) - ID of player who warped (or 0 for self)
- New level name (STRING_GCHAR_LEN) - destination level
- New X coordinate (GCHAR)
- New Y coordinate (GCHAR)
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


PLO_PLAYERWARP = PacketStructure(
    packet_id=14,
    name="PLO_PLAYERWARP",
    fields=[
        gshort_field("player_id", "ID of player who warped (0 for self)"),
        string_gchar_len_field("level_name", "Destination level name"),
        gchar_field("x_coord", "New X coordinate"),
        gchar_field("y_coord", "New Y coordinate")
    ],
    description="Player warp/teleport to new position",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_PLAYERWARP packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_PLAYERWARP.packet_id,
        'packet_name': PLO_PLAYERWARP.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_PLAYERWARP.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
