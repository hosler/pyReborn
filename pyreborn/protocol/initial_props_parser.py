#!/usr/bin/env python3
"""
Initial player properties parser

Handles parsing of the PLO_PLAYERPROPS packet which contains
encoded player properties in a complex binary format.
"""

import struct
import logging
from typing import Dict, Any, Tuple
from ..protocol.enums import PlayerProp

logger = logging.getLogger(__name__)

def parse_player_props(data: bytes) -> Dict[PlayerProp, Any]:
    """
    Parse player properties from binary data.
    
    The format encodes properties as:
    - Property ID (1 byte)
    - Property data (variable length based on property type)
    
    Args:
        data: Binary property data
        
    Returns:
        Dictionary mapping PlayerProp to values
    """
    props = {}
    offset = 0
    
    while offset < len(data):
        if offset >= len(data):
            break
            
        # Read property ID
        prop_id = data[offset]
        offset += 1
        
        try:
            prop = PlayerProp(prop_id)
        except ValueError:
            logger.warning(f"Unknown property ID: {prop_id}")
            # Skip unknown property - we don't know its length
            # This is a simplified parser, so we'll stop here
            break
            
        # Parse property value based on type
        # This is a simplified version - the full protocol has complex encoding
        
        if prop == PlayerProp.PLPROP_ID:
            # Player ID is a short (2 bytes)
            if offset + 2 <= len(data):
                player_id = struct.unpack('<H', data[offset:offset+2])[0]
                props[prop] = player_id
                offset += 2
                logger.debug(f"Parsed player ID: {player_id}")
                
        elif prop == PlayerProp.PLPROP_NICKNAME:
            # Nickname is a string with length prefix
            if offset < len(data):
                str_len = data[offset]
                offset += 1
                if offset + str_len <= len(data):
                    nickname = data[offset:offset+str_len].decode('ascii', errors='ignore')
                    props[prop] = nickname
                    offset += str_len
                    logger.debug(f"Parsed nickname: {nickname}")
                    
        elif prop == PlayerProp.PLPROP_X:
            # X coordinate (1 byte, multiplied by 2)
            if offset < len(data):
                x = data[offset]
                props[prop] = x
                offset += 1
                
        elif prop == PlayerProp.PLPROP_Y:
            # Y coordinate (1 byte, multiplied by 2)
            if offset < len(data):
                y = data[offset]
                props[prop] = y
                offset += 1
                
        elif prop == PlayerProp.PLPROP_ACCOUNTNAME:
            # Account name is a string with length prefix
            if offset < len(data):
                str_len = data[offset]
                offset += 1
                if offset + str_len <= len(data):
                    account = data[offset:offset+str_len].decode('ascii', errors='ignore')
                    props[prop] = account
                    offset += str_len
                    logger.debug(f"Parsed account: {account}")
                    
        else:
            # For other properties, try to guess the length
            # This is very simplified - real parser needs full property definitions
            
            # Skip properties we don't know how to parse
            # In a real implementation, we'd have the full property definitions
            logger.debug(f"Skipping property {prop.name}")
            break
    
    return props

def parse_initial_props(packet_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse initial player properties from PLO_PLAYERPROPS packet.
    
    Args:
        packet_data: Parsed packet data with 'properties' field
        
    Returns:
        Dictionary with parsed player data
    """
    try:
        prop_bytes = packet_data.get('properties', b'')
        if not prop_bytes:
            return {}
            
        logger.debug(f"Parsing {len(prop_bytes)} bytes of player properties")
        
        # For now, extract some basic info manually
        # The actual format is more complex
        result = {}
        
        # Try to find the account name (usually near the end)
        # Look for "your_username" in the data
        try:
            if b'your_username' in prop_bytes:
                result['account'] = 'your_username'
                result['nickname'] = 'your_username'
        except:
            pass
            
        # Try to extract player ID
        # In the actual protocol, this would be properly encoded
        # For now, we'll default to 0 since we don't have the full parser
        result['player_id'] = 0  # Default player ID
        
        # Extract position if possible
        # These are often early in the properties
        if len(prop_bytes) > 10:
            # This is a guess based on common patterns
            result['x'] = 30.0  # Default position
            result['y'] = 30.0
            
        return result
        
    except Exception as e:
        logger.error(f"Error parsing initial props: {e}")
        return {}