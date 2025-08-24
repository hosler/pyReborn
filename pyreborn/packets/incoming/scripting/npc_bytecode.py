#!/usr/bin/env python3
"""
PLO_NPCBYTECODE (Packet 131) - NPC bytecode

This packet provides compiled bytecode for NPC scripts.
Used for server-side NPC scripting and behavior.

The packet format is:
- NPC ID (GSHORT) - unique NPC identifier
- Bytecode data (VARIABLE_DATA) - compiled NPC script bytecode
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_NPCBYTECODE = PacketStructure(
    packet_id=131,
    name="PLO_NPCBYTECODE",
    fields=[
        gshort_field("npc_id", "Unique NPC identifier"),
        variable_data_field("bytecode_data", "Compiled NPC script bytecode")
    ],
    description="NPC compiled bytecode for scripting",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_NPCBYTECODE packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_NPCBYTECODE.packet_id,
        'packet_name': PLO_NPCBYTECODE.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_NPCBYTECODE.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
