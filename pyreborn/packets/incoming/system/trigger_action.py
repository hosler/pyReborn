#!/usr/bin/env python3
"""
PLO_TRIGGERACTION (Packet 48) - Trigger action

This packet notifies the client that a trigger or action has been
activated, such as stepping on a trigger tile or activating a switch.

The packet format is:
- Trigger X coordinate (GCHAR) - X position of trigger
- Trigger Y coordinate (GCHAR) - Y position of trigger  
- Action type (GCHAR) - type of action triggered
- Action data (VARIABLE_DATA) - action parameters
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_TRIGGERACTION = PacketStructure(
    packet_id=48,
    name="PLO_TRIGGERACTION",
    fields=[
        gchar_field("trigger_x", "X position of trigger"),
        gchar_field("trigger_y", "Y position of trigger"),
        gchar_field("action_type", "Type of action triggered"),
        variable_data_field("action_data", "Action parameters and data")
    ],
    description="Trigger activation notification",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_TRIGGERACTION packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_TRIGGERACTION.packet_id,
        'packet_name': PLO_TRIGGERACTION.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_TRIGGERACTION.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
