#!/usr/bin/env python3
"""
PLO_GUILDINFO (Packet 61) - Guild information

This packet provides guild information and member data.
Used for guild systems and player associations.

The packet format is:
- Guild name (STRING_GCHAR_LEN) - name of the guild
- Guild data (VARIABLE_DATA) - guild members, settings, and information
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_GUILDINFO = PacketStructure(
    packet_id=61,
    name="PLO_GUILDINFO",
    fields=[
        string_gchar_len_field("guild_name", "Name of the guild"),
        variable_data_field("guild_data", "Guild members, settings, and information")
    ],
    description="Guild information and member data",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_GUILDINFO packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_GUILDINFO.packet_id,
        'packet_name': PLO_GUILDINFO.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_GUILDINFO.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
