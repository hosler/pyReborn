#!/usr/bin/env python3
"""
PLO_STATUSLIST (Packet 180) - Status list display

This packet provides a list of player statuses or status messages.
Used for showing online players, rankings, or other status information.

The packet format is:
- Status type (GCHAR) - type of status list (players, scores, etc.)
- Status data (VARIABLE_DATA) - encoded status information
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_STATUSLIST = PacketStructure(
    packet_id=180,
    name="PLO_STATUSLIST",
    fields=[
        gchar_field("status_type", "Type of status list"),
        variable_data_field("status_data", "Encoded status information")
    ],
    description="Status list display (players, scores, etc.)",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_STATUSLIST packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_STATUSLIST.packet_id,
        'packet_name': PLO_STATUSLIST.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_STATUSLIST.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
