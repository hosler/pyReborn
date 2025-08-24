#!/usr/bin/env python3
"""
PLO_LEVELLINK (Packet 1) - Level connection links

This packet defines connections between levels, containing information about
where players can transition from one level to another.
"""

from ...base import PacketStructure, PacketField, PacketFieldType, gstring_field, PacketReader, parse_field
from typing import Dict, Any


PLO_LEVELLINK = PacketStructure(
    packet_id=1,
    name="PLO_LEVELLINK",
    fields=[
        PacketField("link_data", PacketFieldType.VARIABLE_DATA, "Level link string (destlevel x y width height destx desty)")
    ],
    description="Level connection data for transitions",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_LEVELLINK packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_LEVELLINK.packet_id,
        'packet_name': PLO_LEVELLINK.name,
        'fields': {}
    }
    
    # For VARIABLE_DATA, the entire remaining data is the field value
    # Convert bytes to string
    try:
        link_data = data.decode('utf-8').strip()
    except UnicodeDecodeError:
        # Fallback to latin-1 if UTF-8 fails
        link_data = data.decode('latin-1').strip()
    
    result['fields']['link_data'] = link_data
    
    return result
