#!/usr/bin/env python3
"""
PLI_MOVE (Packet 35) - Player movement

This packet is sent when the player moves their character.
It includes position, direction, and animation state.
"""

from ...base import PacketStructure, PacketField, PacketFieldType
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

PLI_MOVE = PacketStructure(
    packet_id=35,
    name="PLI_MOVE",
    fields=[
        PacketField("x", PacketFieldType.GCHAR, "X position in half-tiles"),
        PacketField("y", PacketFieldType.GCHAR, "Y position in half-tiles"),
        PacketField("direction", PacketFieldType.GCHAR, "Direction (0-3)"),
        PacketField("animation", PacketFieldType.GCHAR, "Animation frame")
    ],
    description="Player movement update"
)

def create_move_packet(x: float, y: float, direction: int = 2, animation: int = 0) -> bytes:
    """
    Create a movement packet.
    
    Args:
        x: X position in tiles
        y: Y position in tiles
        direction: Direction (0=up, 1=left, 2=down, 3=right)
        animation: Animation frame
        
    Returns:
        Encoded packet data
    """
    # Convert tiles to half-tiles
    half_x = int(x * 2)
    half_y = int(y * 2)
    
    # Ensure values are in valid range
    half_x = max(0, min(127, half_x))
    half_y = max(0, min(127, half_y))
    direction = max(0, min(3, direction))
    animation = max(0, min(255, animation))
    
    # Build packet
    packet_data = bytearray()
    packet_data.append(PLI_MOVE.packet_id)
    packet_data.append(half_x + 32)  # GCHAR encoding
    packet_data.append(half_y + 32)  # GCHAR encoding
    packet_data.append(direction + 32)  # GCHAR encoding
    packet_data.append(animation + 32)  # GCHAR encoding
    
    logger.debug(f"Created move packet: pos({x:.1f},{y:.1f}) dir={direction}")
    return bytes(packet_data)

def parse(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse movement packet data.
    
    Args:
        data: Dictionary containing movement fields
        
    Returns:
        Parsed movement information with business logic applied
    """
    # Extract raw values
    x = data.get('x', 30)  # Already decoded from GCHAR
    y = data.get('y', 30)
    direction = data.get('direction', 2)
    animation = data.get('animation', 0)
    
    # Convert half-tiles to tiles
    x_tiles = x / 2.0
    y_tiles = y / 2.0
    
    # Determine movement type
    movement_info = {
        'position': (x_tiles, y_tiles),
        'direction': direction,
        'animation': animation,
        'is_moving': animation > 0,
        'direction_name': ['up', 'left', 'down', 'right'][direction] if 0 <= direction <= 3 else 'unknown'
    }
    
    # Determine events to emit
    events = []
    events.append({
        'type': 'PLAYER_MOVED',
        'data': {
            'x': x_tiles,
            'y': y_tiles,
            'direction': direction,
            'animation': animation
        }
    })
    
    return {
        'movement_info': movement_info,
        'events': events
    }