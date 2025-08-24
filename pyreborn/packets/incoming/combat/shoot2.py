#!/usr/bin/env python3
"""
PLO_SHOOT2 (Packet 191) - Enhanced shooting

This packet provides enhanced shooting functionality.
Extended version of basic shooting with additional parameters.

The packet format is:
- Shooter ID (GSHORT) - ID of player shooting
- Shoot data (VARIABLE_DATA) - enhanced shooting information
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_SHOOT2 = PacketStructure(
    packet_id=191,
    name="PLO_SHOOT2",
    fields=[
        gshort_field("shooter_id", "ID of player shooting"),
        variable_data_field("shoot_data", "Enhanced shooting information")
    ],
    description="Enhanced player shooting",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_SHOOT2 packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_SHOOT2.packet_id,
        'packet_name': PLO_SHOOT2.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_SHOOT2.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
