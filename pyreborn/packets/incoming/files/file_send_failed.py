#!/usr/bin/env python3
"""
PLO_FILESENDFAILED (Packet 30) - File send failed

This packet notifies the client that a file transfer has failed.
Contains information about why the transfer couldn't complete.

The packet format is:
- File name (STRING_GCHAR_LEN) - name of file that failed to send
- Error message (VARIABLE_DATA) - reason for the failure
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_FILESENDFAILED = PacketStructure(
    packet_id=30,
    name="PLO_FILESENDFAILED",
    fields=[
        string_gchar_len_field("file_name", "Name of file that failed to send"),
        variable_data_field("error_message", "Reason for the failure")
    ],
    description="File transfer failed notification",
    variable_length=True
)

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_FILESENDFAILED packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_FILESENDFAILED.packet_id,
        'packet_name': PLO_FILESENDFAILED.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_FILESENDFAILED.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    # Enhanced logging for file send failures
    import logging
    logger = logging.getLogger(__name__)
    
    file_name = result['fields'].get('file_name', 'unknown')
    error_message = result['fields'].get('error_message', 'no error message')
    
    logger.error(f"🚨 FILE SEND FAILED: {file_name}")
    logger.error(f"   Error: {error_message}")
    
    # Special handling for GMAP files
    if isinstance(file_name, (str, bytes)) and 'gmap' in str(file_name).lower():
        logger.error(f"   🎯 GMAP FILE REJECTED BY SERVER!")
        logger.error(f"   This confirms server received request but cannot send file")
        logger.error(f"   Check server file system configuration")
    
    return result
