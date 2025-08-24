"""
PLI_ITEMDEL - Item Delete Packet

This packet notifies the server that an item has been picked up.
"""

import logging
from ...base import PacketFieldType
from .. import OutgoingPacketStructure, OutgoingPacketField, OutgoingPacket

logger = logging.getLogger(__name__)


class ItemDelBuilder:
    """Custom builder for ItemDel packets"""
    
    def build_packet(self, packet: OutgoingPacket) -> bytes:
        """Build ItemDel packet"""
        from pyreborn.protocol.enums import PlayerToServer
        
        data = bytearray()
        data.append(PlayerToServer.PLI_ITEMDEL + 32)  # Packet ID + 32
        
        # Get fields
        x = packet.get_field('x') or 0
        y = packet.get_field('y') or 0
        
        # Add item location (in half-tiles)
        data.append(int(x * 2) + 32)
        data.append(int(y * 2) + 32)
        
        # End packet with newline
        data.append(10)
        return bytes(data)


# Define the ItemDel packet structure
PLI_ITEMDEL = OutgoingPacketStructure(
    packet_id=13,
    name="PLI_ITEMDEL",
    description="Pick up an item",
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
    builder_class=ItemDelBuilder
)


class ItemDelPacketHelper:
    """Helper class for easier ItemDel packet construction"""
    
    @staticmethod
    def create(x: float, y: float) -> OutgoingPacket:
        """Create a new ItemDel packet
        
        Args:
            x: X coordinate of item (in tiles)
            y: Y coordinate of item (in tiles)
        """
        return PLI_ITEMDEL.create_packet(x=x, y=y)


# Export the helper
ItemDelPacket = ItemDelPacketHelper