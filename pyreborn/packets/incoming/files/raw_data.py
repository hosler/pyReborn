#!/usr/bin/env python3
"""
PLO_RAWDATA (Packet 100) - Raw data chunk

This packet contains a chunk of file data for a large file download.
The first 4 bytes are the download ID, followed by the raw data.

Based on C# implementation, the packet format is:
- Download ID (GINT4) - unique identifier for this download
- Data (VARIABLE_DATA) - the actual file data chunk
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gint4_field(name: str, description: str) -> PacketField:
    """Helper to create a GINT4 field"""
    return PacketField(name, PacketFieldType.GINT4, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a VARIABLE_DATA field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_RAWDATA = PacketStructure(
    packet_id=100,
    name="PLO_RAWDATA",
    fields=[
        gint4_field("download_id", "Unique identifier for this download"),
        variable_data_field("data", "Raw file data chunk")
    ],
    description="File data chunk for large file transfer",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_RAWDATA packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_RAWDATA.packet_id,
        'packet_name': PLO_RAWDATA.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_RAWDATA.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
