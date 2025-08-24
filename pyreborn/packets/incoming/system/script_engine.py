#!/usr/bin/env python3
"""
PLO_SCRIPTENGINE (Packet 71) - Script engine control

This packet controls server-side script execution and management.
Used for dynamic scripting, event handling, and advanced game logic.

The packet format is:
- Script command (GCHAR) - type of script operation
- Script name (STRING_GCHAR_LEN) - name/identifier of the script
- Script data (VARIABLE_DATA) - script code, parameters, and execution context
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


PLO_SCRIPTENGINE = PacketStructure(
    packet_id=71,
    name="PLO_SCRIPTENGINE",
    fields=[
        gchar_field("script_command", "Type of script operation"),
        string_gchar_len_field("script_name", "Name/identifier of script"),
        variable_data_field("script_data", "Script code, parameters, and context")
    ],
    description="Script engine control and management",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_SCRIPTENGINE packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_SCRIPTENGINE.packet_id,
        'packet_name': PLO_SCRIPTENGINE.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_SCRIPTENGINE.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
