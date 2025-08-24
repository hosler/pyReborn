#!/usr/bin/env python3
"""
PLI_REQUESTTEXT (Packet 152) - Request text/value from server

This packet requests a text value from the server.
Common uses include server flags, player attributes, etc.
"""

from .. import OutgoingPacketStructure, OutgoingPacketField
from ...base import PacketFieldType
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

PLI_REQUESTTEXT = OutgoingPacketStructure(
    packet_id=152,
    name="PLI_REQUESTTEXT",
    fields=[
        OutgoingPacketField("key", PacketFieldType.VARIABLE_DATA, "Text key to request")
    ],
    description="Request text value from server"
)

def create_request_text_packet(key: str) -> bytes:
    """
    Create a request text packet.
    
    Args:
        key: The key/name of the value to request
        
    Returns:
        Encoded packet data
    """
    packet_data = bytearray()
    packet_data.append(PLI_REQUESTTEXT.packet_id)
    
    # Add key as GSTRING
    key_bytes = key.encode('latin-1')
    packet_data.append(len(key_bytes) + 32)  # GCHAR length
    packet_data.extend(key_bytes)
    
    logger.debug(f"Created request text packet for key '{key}'")
    return bytes(packet_data)

def parse(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse request text packet data.
    
    Args:
        data: Dictionary containing request fields
        
    Returns:
        Parsed request information
    """
    key = data.get('key', '')
    
    return {
        'key': key,
        'request_type': _determine_request_type(key)
    }

def _determine_request_type(key: str) -> str:
    """Determine the type of request based on the key"""
    if key.startswith('flag:'):
        return 'server_flag'
    elif key.startswith('player:'):
        return 'player_attribute'
    elif key.startswith('server:'):
        return 'server_info'
    elif key.startswith('level:'):
        return 'level_info'
    else:
        return 'generic'