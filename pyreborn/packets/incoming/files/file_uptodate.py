#!/usr/bin/env python3
"""
PLO_FILEUPTODATE (Packet 45) - File up to date

This packet notifies the client that a requested file is already
up to date and doesn't need to be re-downloaded.

The packet format is:
- File name (STRING_GCHAR_LEN) - name of the file that's up to date
- File modification time (GINT4) - timestamp of current file version
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


def gint4_field(name: str, description: str) -> PacketField:
    """Helper to create a GINT4 field"""
    return PacketField(name, PacketFieldType.GINT4, description=description)


PLO_FILEUPTODATE = PacketStructure(
    packet_id=45,
    name="PLO_FILEUPTODATE",
    fields=[
        string_gchar_len_field("file_name", "Name of file that's up to date"),
        gint4_field("modification_time", "Timestamp of current file version")
    ],
    description="File is up to date, no download needed",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_FILEUPTODATE packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_FILEUPTODATE.packet_id,
        'packet_name': PLO_FILEUPTODATE.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_FILEUPTODATE.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    return result
