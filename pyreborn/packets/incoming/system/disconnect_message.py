#!/usr/bin/env python3
"""
PLO_DISCMESSAGE (Packet 16) - Disconnect message

This packet contains a message explaining why the client is being
disconnected from the server.

The packet format is:
- Disconnect reason (VARIABLE_DATA) - message explaining the disconnection
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_DISCMESSAGE = PacketStructure(
    packet_id=16,
    name="PLO_DISCMESSAGE",
    fields=[
        variable_data_field("disconnect_reason", "Message explaining disconnection")
    ],
    description="Disconnect notification with reason",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_DISCMESSAGE packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_DISCMESSAGE.packet_id,
        'packet_name': PLO_DISCMESSAGE.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_DISCMESSAGE.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
