#!/usr/bin/env python3
"""
PLO_NPCSERVERADDR (Packet 79) - NPC server address

This packet provides the client with the address and port of the
NPC server for advanced NPC scripting connections.

The packet format is:
- NPC server IP (STRING_GCHAR_LEN) - IP address of NPC server
- NPC server port (GSHORT) - port number for NPC server
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


PLO_NPCSERVERADDR = PacketStructure(
    packet_id=79,
    name="PLO_NPCSERVERADDR",
    fields=[
        string_gchar_len_field("npc_server_ip", "IP address of NPC server"),
        gshort_field("npc_server_port", "Port number for NPC server")
    ],
    description="NPC server address and port",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_NPCSERVERADDR packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_NPCSERVERADDR.packet_id,
        'packet_name': PLO_NPCSERVERADDR.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_NPCSERVERADDR.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
