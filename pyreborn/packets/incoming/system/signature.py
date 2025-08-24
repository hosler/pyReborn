#!/usr/bin/env python3
"""
PLO_SIGNATURE (Packet 25) - Login signature

This packet is sent by the server to confirm successful login and
provide session authentication data.
"""

from ...base import PacketStructure, PacketField, PacketFieldType, variable_data_field, PacketReader, parse_field
from typing import Dict, Any


PLO_SIGNATURE = PacketStructure(
    packet_id=25,
    name="PLO_SIGNATURE",
    fields=[
        variable_data_field("signature", "Login signature data")
    ],
    description="Login signature confirmation",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_SIGNATURE packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_SIGNATURE.packet_id,
        'packet_name': PLO_SIGNATURE.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_SIGNATURE.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
