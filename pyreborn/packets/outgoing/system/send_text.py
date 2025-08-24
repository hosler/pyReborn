#!/usr/bin/env python3
"""
PLI_SENDTEXT (Packet 154) - Send text/value to server

This packet sends a text value to the server.
Common uses include setting server flags, player attributes, etc.
"""

from .. import OutgoingPacketStructure, OutgoingPacketField
from ...base import PacketFieldType
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

PLI_SENDTEXT = OutgoingPacketStructure(
    packet_id=154,
    name="PLI_SENDTEXT",
    fields=[
        OutgoingPacketField("key", PacketFieldType.VARIABLE_DATA, "Text key to set"),
        OutgoingPacketField("value", PacketFieldType.VARIABLE_DATA, "Value to set")
    ],
    description="Send text value to server"
)

def create_send_text_packet(key: str, value: str) -> bytes:
    """
    Create a send text packet.
    
    Args:
        key: The key/name of the value to set
        value: The value to set
        
    Returns:
        Encoded packet data
    """
    packet_data = bytearray()
    packet_data.append(PLI_SENDTEXT.packet_id)
    
    # Combine key and value with a separator
    text = f"{key}={value}"
    text_bytes = text.encode('latin-1')
    
    # Add as GSTRING
    packet_data.append(len(text_bytes) + 32)  # GCHAR length
    packet_data.extend(text_bytes)
    
    logger.debug(f"Created send text packet: {key}={value}")
    return bytes(packet_data)

def parse(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse send text packet data.
    
    Args:
        data: Dictionary containing send fields
        
    Returns:
        Parsed send information with business logic
    """
    key = data.get('key', '')
    value = data.get('value', '')
    
    # Determine action type
    action_info = {
        'key': key,
        'value': value,
        'action_type': _determine_action_type(key)
    }
    
    # Validate based on action type
    if action_info['action_type'] == 'server_flag':
        action_info['valid'] = _validate_flag_value(value)
    elif action_info['action_type'] == 'player_attribute':
        action_info['valid'] = _validate_player_attribute(key, value)
    else:
        action_info['valid'] = True
    
    return action_info

def _determine_action_type(key: str) -> str:
    """Determine the type of action based on the key"""
    if key.startswith('flag:'):
        return 'server_flag'
    elif key.startswith('player:'):
        return 'player_attribute'
    elif key.startswith('server:'):
        return 'server_setting'
    elif key.startswith('level:'):
        return 'level_setting'
    else:
        return 'generic'

def _validate_flag_value(value: str) -> bool:
    """Validate a server flag value"""
    # Server flags have certain restrictions
    if len(value) > 223:  # Max flag value length
        return False
    return True

def _validate_player_attribute(key: str, value: str) -> bool:
    """Validate a player attribute"""
    # Check for known player attributes
    valid_attrs = ['nickname', 'head', 'body', 'sword', 'shield', 'colors']
    attr_name = key.split(':', 1)[1] if ':' in key else key
    return attr_name.lower() in valid_attrs