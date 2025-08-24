"""
PLI_ITEMTAKE - Item Take Packet

This packet notifies the server that the player wants to take an item.
Used for newer protocol versions (2.1+).
"""

import logging
from ...base import PacketFieldType
from .. import OutgoingPacketStructure, OutgoingPacketField, OutgoingPacket

logger = logging.getLogger(__name__)


class ItemTakeBuilder:
    """Custom builder for ItemTake packets"""
    
    def build_packet(self, packet: OutgoingPacket) -> bytes:
        """Build ItemTake packet"""
        from pyreborn.protocol.enums import PlayerToServer
        
        data = bytearray()
        data.append(PlayerToServer.PLI_ITEMTAKE + 32)  # Packet ID + 32
        
        # Get fields
        x = packet.get_field('x') or 0
        y = packet.get_field('y') or 0
        
        # Add item location (in half-tiles)
        data.append(int(x * 2) + 32)
        data.append(int(y * 2) + 32)
        
        # End packet with newline
        data.append(10)
        return bytes(data)


# Define the ItemTake packet structure
PLI_ITEMTAKE = OutgoingPacketStructure(
    packet_id=32,
    name="PLI_ITEMTAKE",
    description="Take an item (v2.1+)",
    fields=[
        OutgoingPacketField(
            name="x",
            field_type=PacketFieldType.GCHAR,
            description="X coordinate of item (in tiles)",
            default=0
        ),
        OutgoingPacketField(
            name="y",
            field_type=PacketFieldType.GCHAR,
            description="Y coordinate of item (in tiles)",
            default=0
        )
    ],
    variable_length=False,
    builder_class=ItemTakeBuilder
)


class ItemTakePacketHelper:
    """Helper class for easier ItemTake packet construction"""
    
    @staticmethod
    def create(x: float, y: float) -> OutgoingPacket:
        """Create a new ItemTake packet
        
        Args:
            x: X coordinate of item (in tiles)
            y: Y coordinate of item (in tiles)
        """
        return PLI_ITEMTAKE.create_packet(x=x, y=y)


# Export the helper
ItemTakePacket = ItemTakePacketHelper