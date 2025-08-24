#!/usr/bin/env python3
"""
PLO_SERVERMESSAGE (Packet 92) - Server message

This packet contains messages from the server to the client,
such as announcements or system notifications.
"""

from ...base import PacketStructure, PacketField, PacketFieldType, variable_data_field, PacketReader, parse_field
from typing import Dict, Any


PLO_SERVERMESSAGE = PacketStructure(
    packet_id=92,
    name="PLO_SERVERMESSAGE",
    fields=[
        variable_data_field("message", "Server message text")
    ],
    description="Server message/notification",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_SERVERMESSAGE packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_SERVERMESSAGE.packet_id,
        'packet_name': PLO_SERVERMESSAGE.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_SERVERMESSAGE.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
