#!/usr/bin/env python3
"""
PLO_TIMEOUTWARNING (Packet 54) - Timeout warning

This packet warns the player about an impending timeout.
Used to notify players of inactivity timeouts.

The packet format is:
- Warning message (STRING_GCHAR_LEN) - timeout warning text
- Timeout seconds (GSHORT) - seconds until timeout
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


PLO_TIMEOUTWARNING = PacketStructure(
    packet_id=54,
    name="PLO_TIMEOUTWARNING",
    fields=[
        string_gchar_len_field("warning_message", "Timeout warning text"),
        gshort_field("timeout_seconds", "Seconds until timeout")
    ],
    description="Player timeout warning",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_TIMEOUTWARNING packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_TIMEOUTWARNING.packet_id,
        'packet_name': PLO_TIMEOUTWARNING.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_TIMEOUTWARNING.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
