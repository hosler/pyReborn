#!/usr/bin/env python3
"""
PLO_HASNPCSERVER (Packet 44) - Has NPC server status

This packet notifies the client whether the server has an NPC server
running for advanced NPC scripting capabilities.

The packet format is:
- Has NPC server (GCHAR) - 1 if NPC server is available, 0 if not
- NPC server version (GCHAR) - version of the NPC server (optional)
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


PLO_HASNPCSERVER = PacketStructure(
    packet_id=44,
    name="PLO_HASNPCSERVER",
    fields=[
        gchar_field("has_npc_server", "1 if NPC server available, 0 if not"),
        gchar_field("npc_server_version", "Version of the NPC server")
    ],
    description="NPC server availability status",
    variable_length=False
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_HASNPCSERVER packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_HASNPCSERVER.packet_id,
        'packet_name': PLO_HASNPCSERVER.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_HASNPCSERVER.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
