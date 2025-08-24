#!/usr/bin/env python3
"""
PLO_NPCMOVED (Packet 24) - NPC movement

This packet notifies when an NPC moves to a new position.
"""

from ...base import PacketStructure, PacketField, PacketFieldType, gchar_field, PacketReader, parse_field
from typing import Dict, Any


PLO_NPCMOVED = PacketStructure(
    packet_id=24,
    name="PLO_NPCMOVED",
    fields=[
        gchar_field("npc_id", "NPC identifier"),
        gchar_field("x", "X coordinate"),
        gchar_field("y", "Y coordinate"),
        gchar_field("direction", "Movement direction"),
        gchar_field("sprite", "Sprite/animation frame")
    ],
    description="NPC movement update"
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_NPCMOVED packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_NPCMOVED.packet_id,
        'packet_name': PLO_NPCMOVED.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_NPCMOVED.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
