#!/usr/bin/env python3
"""
PLO_ADDPLAYER (Packet 55) - Add player to level

This packet notifies the client that a new player has entered the level.
It contains the basic player information needed to display the player.

The packet format is:
- Player ID (GSHORT) - unique identifier for this player
- Player account name (STRING_GCHAR_LEN) - the player's account name
- Player nickname (STRING_GCHAR_LEN) - the player's display name
- Player level (STRING_GCHAR_LEN) - current level name
- Player X coordinate (GCHAR) 
- Player Y coordinate (GCHAR)
- Player appearance data (VARIABLE_DATA) - sprite, colors, etc.
"""

from ...base import PacketStructure, PacketField, PacketFieldType, PacketReader, parse_field
from typing import Dict, Any


def gshort_field(name: str, description: str) -> PacketField:
    """Helper to create a GSHORT field"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def gchar_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR field"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def string_gchar_len_field(name: str, description: str) -> PacketField:
    """Helper to create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


def variable_data_field(name: str, description: str) -> PacketField:
    """Helper to create a variable data field"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


PLO_ADDPLAYER = PacketStructure(
    packet_id=55,
    name="PLO_ADDPLAYER",
    fields=[
        gshort_field("player_id", "Unique player identifier"),
        string_gchar_len_field("account_name", "Player account name"),
        string_gchar_len_field("nickname", "Player display nickname"),
        string_gchar_len_field("level_name", "Player's current level"),
        gchar_field("x_coord", "Player X coordinate"),
        gchar_field("y_coord", "Player Y coordinate"),
        variable_data_field("appearance_data", "Player appearance and properties")
    ],
    description="Add new player to level",
    variable_length=True
)

def parse(data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse PLO_ADDPLAYER packet data"""
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        player_id = data.get('player_id', 0)
        account_name = data.get('account_name', '')
        nickname = data.get('nickname', f'Player{player_id}')
        level_name = data.get('level_name', '')
        x_coord = data.get('x_coord', 30)
        y_coord = data.get('y_coord', 30)
        appearance_data = data.get('appearance_data', b'')
        
        logger.info(f"📦 PLO_ADDPLAYER: Player {nickname} (ID:{player_id}) joining at ({x_coord/2:.1f}, {y_coord/2:.1f}) in {level_name}")
        
        # Build event data
        events = [{
            'type': 'PLAYER_JOINED',
            'data': {
                'player_id': player_id,
                'account': account_name,
                'nickname': nickname,
                'level': level_name,
                'x': x_coord / 2.0,  # Convert to tiles
                'y': y_coord / 2.0   # Convert to tiles
            }
        }]
        
        return {
            'player_id': player_id,
            'account': account_name,
            'nickname': nickname,
            'level': level_name,
            'x': x_coord / 2.0,
            'y': y_coord / 2.0,
            'appearance_data': appearance_data,
            'events': events
        }
        
    except Exception as e:
        logger.error(f"Error parsing PLO_ADDPLAYER: {e}")
        import traceback
        traceback.print_exc()
        return {'error': str(e)}

def parse_packet(data: bytes, announced_size: int = 0) -> Dict[str, Any]:
    """Parse PLO_ADDPLAYER packet from raw bytes"""
    reader = PacketReader(data)
    result = {
        'packet_id': PLO_ADDPLAYER.packet_id,
        'packet_name': PLO_ADDPLAYER.name,
        'fields': {}
    }
    
    # Parse each field using the structure definition
    for field in PLO_ADDPLAYER.fields:
        result['fields'][field.name] = parse_field(reader, field, announced_size)
    
    # Apply business logic parsing
    parsed_data = parse(result['fields'])
    if parsed_data:
        result['parsed_data'] = parsed_data
    
    return result
