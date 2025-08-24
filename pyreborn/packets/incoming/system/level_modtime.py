#!/usr/bin/env python3
"""
PLO_LEVELMODTIME (Packet 39) - Level modification time

This packet notifies the client of a level's last modification timestamp,
used for caching and determining if level files need to be re-downloaded.

The packet format is:
- Level name (STRING_GCHAR_LEN) - name of the level
- Modification time (GINT4) - Unix timestamp of last modification
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


def gint4_field(name: str, description: str) -> PacketField:
    """Helper to create a GINT4 field"""
    return PacketField(name, PacketFieldType.GINT4, description=description)


PLO_LEVELMODTIME = PacketStructure(
    packet_id=39,
    name="PLO_LEVELMODTIME",
    fields=[
        string_gchar_len_field("level_name", "Name of the level"),
        gint4_field("modification_time", "Unix timestamp of last modification")
    ],
    description="Level modification timestamp for caching",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_LEVELMODTIME packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_LEVELMODTIME.packet_id,
        'packet_name': PLO_LEVELMODTIME.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_LEVELMODTIME.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
