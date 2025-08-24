#!/usr/bin/env python3
"""
PLO_SERVERSTATS (Packet 59) - Server statistics

This packet provides server performance and usage statistics.
Used for monitoring and administrative purposes.

The packet format is:
- Stats data (VARIABLE_DATA) - encoded server statistics
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_SERVERSTATS = PacketStructure(
    packet_id=59,
    name="PLO_SERVERSTATS",
    fields=[
        variable_data_field("stats_data", "Encoded server statistics")
    ],
    description="Server performance and usage statistics",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_SERVERSTATS packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_SERVERSTATS.packet_id,
        'packet_name': PLO_SERVERSTATS.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_SERVERSTATS.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
