"""
PLI_BOARDMODIFY - Board Modification Packet

This packet modifies tiles on the game board/level.
Used for actions like digging, placing tiles, or destroying objects.
"""

import logging
from typing import List
from ...base import PacketFieldType
from .. import OutgoingPacketStructure, OutgoingPacketField, OutgoingPacket

logger = logging.getLogger(__name__)


class BoardModifyBuilder:
    """Custom builder for BoardModify packets"""
    
    def build_packet(self, packet: OutgoingPacket) -> bytes:
        """Build BoardModify packet"""
        from pyreborn.protocol.enums import PlayerToServer
        
        data = bytearray()
        data.append(PlayerToServer.PLI_BOARDMODIFY + 32)  # Packet ID + 32
        
        # Get fields
        x = packet.get_field('x') or 0
        y = packet.get_field('y') or 0
        width = packet.get_field('width') or 1
        height = packet.get_field('height') or 1
        tiles = packet.get_field('tiles') or []
        
        # Add location (x, y)
        data.append(x + 32)
        data.append(y + 32)
        
        # Add dimensions (width, height)
        data.append(width + 32)
        data.append(height + 32)
        
        # Add tile data
        # Each tile is 2 bytes in the format used by the server
        for tile in tiles:
            if isinstance(tile, int):
                # Single tile ID - encode as 2 bytes
                data.append((tile >> 8) & 0xFF)
                data.append(tile & 0xFF)
            elif isinstance(tile, tuple) and len(tile) == 2:
                # Already split into 2 bytes
                data.append(tile[0])
                data.append(tile[1])
        
        # End packet with newline
        data.append(10)
        return bytes(data)


def encode_tiles_field(tiles: List[int]) -> List[int]:
    """Encoder function to ensure tiles are properly formatted"""
    # Tiles should be a flat list of tile IDs
    # The dimensions determine how to interpret the list
    return tiles if tiles else []


# Define the BoardModify packet structure
PLI_BOARDMODIFY = OutgoingPacketStructure(
    packet_id=1,
    name="PLI_BOARDMODIFY",
    description="Modify tiles on the game board",
    fields=[
        OutgoingPacketField(
            name="x",
            field_type=PacketFieldType.GCHAR,
            description="X coordinate of modification (0-63)",
            default=0
        ),
        OutgoingPacketField(
            name="y",
            field_type=PacketFieldType.GCHAR,
            description="Y coordinate of modification (0-63)",
            default=0
        ),
        OutgoingPacketField(
            name="width",
            field_type=PacketFieldType.GCHAR,
            description="Width of modification area",
            default=1
        ),
        OutgoingPacketField(
            name="height",
            field_type=PacketFieldType.GCHAR,
            description="Height of modification area",
            default=1
        ),
        OutgoingPacketField(
            name="tiles",
            field_type=PacketFieldType.VARIABLE_DATA,
            description="List of tile IDs to place",
            default=[],
            encoder=encode_tiles_field
        )
    ],
    variable_length=True,
    builder_class=BoardModifyBuilder
)


class BoardModifyPacketHelper:
    """Helper class for easier BoardModify packet construction"""
    
    @staticmethod
    def create(x: int = 0, y: int = 0, width: int = 1, height: int = 1, 
               tiles: List[int] = None) -> OutgoingPacket:
        """Create a new BoardModify packet
        
        Args:
            x: X coordinate (0-63)
            y: Y coordinate (0-63)
            width: Width of area to modify
            height: Height of area to modify
            tiles: List of tile IDs to place
        """
        return PLI_BOARDMODIFY.create_packet(
            x=x, y=y, width=width, height=height, 
            tiles=tiles or []
        )
    
    @staticmethod
    def destroy_tile(x: int, y: int) -> OutgoingPacket:
        """Create packet to destroy a single tile
        
        Args:
            x: X coordinate of tile
            y: Y coordinate of tile
        """
        # Tile ID 0 typically means empty/destroyed
        return BoardModifyPacketHelper.create(x, y, 1, 1, [0])
    
    @staticmethod
    def place_tiles(x: int, y: int, width: int, height: int, 
                    tile_id: int) -> OutgoingPacket:
        """Create packet to place the same tile in a rectangular area
        
        Args:
            x: Starting X coordinate
            y: Starting Y coordinate
            width: Width of area
            height: Height of area
            tile_id: ID of tile to place
        """
        tiles = [tile_id] * (width * height)
        return BoardModifyPacketHelper.create(x, y, width, height, tiles)


# Export the helper
BoardModifyPacket = BoardModifyPacketHelper