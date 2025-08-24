#!/usr/bin/env python3
"""
PLO_LISTPROCESSES (Packet 182) - List running processes

This packet provides a list of running server processes.
Used for server monitoring and administration.

The packet format is:
- Process data (VARIABLE_DATA) - encoded list of running processes
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_LISTPROCESSES = PacketStructure(
    packet_id=182,
    name="PLO_LISTPROCESSES",
    fields=[
        variable_data_field("process_data", "Encoded list of running processes")
    ],
    description="List of running server processes",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_LISTPROCESSES packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_LISTPROCESSES.packet_id,
        'packet_name': PLO_LISTPROCESSES.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_LISTPROCESSES.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
