#!/usr/bin/env python3
"""
PLO_MUSICCONTROL (Packet 65) - Music and sound control

This packet controls background music and sound effects.
Used for audio atmosphere and environmental sound management.

The packet format is:
- Music type (GCHAR) - type of music/sound command
- Music file (STRING_GCHAR_LEN) - music/sound file name
- Music settings (VARIABLE_DATA) - volume, loop, and effect settings
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_MUSICCONTROL = PacketStructure(
    packet_id=65,
    name="PLO_MUSICCONTROL",
    fields=[
        gchar_field("music_type", "Type of music/sound command"),
        string_gchar_len_field("music_file", "Music/sound file name"),
        variable_data_field("music_settings", "Volume, loop, and effect settings")
    ],
    description="Music and sound control",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_MUSICCONTROL packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_MUSICCONTROL.packet_id,
        'packet_name': PLO_MUSICCONTROL.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_MUSICCONTROL.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
