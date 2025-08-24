"""
PLI_BOMBDEL - Bomb Delete Packet

This packet notifies the server that a bomb has exploded or been removed.
"""

import logging
from ...base import PacketFieldType
from .. import OutgoingPacketStructure, OutgoingPacketField, OutgoingPacket

logger = logging.getLogger(__name__)


class BombDelBuilder:
    """Custom builder for BombDel packets"""
    
    def build_packet(self, packet: OutgoingPacket) -> bytes:
        """Build BombDel packet"""
        from pyreborn.protocol.enums import PlayerToServer
        
        data = bytearray()
        data.append(PlayerToServer.PLI_BOMBDEL + 32)  # Packet ID + 32
        
        # Get fields
        x = packet.get_field('x') or 0
        y = packet.get_field('y') or 0
        
        # Add bomb location (in half-tiles)
        data.append(int(x * 2) + 32)
        data.append(int(y * 2) + 32)
        
        # End packet with newline
        data.append(10)
        return bytes(data)


# Define the BombDel packet structure
PLI_BOMBDEL = OutgoingPacketStructure(
    packet_id=5,
    name="PLI_BOMBDEL",
    description="Delete/explode a bomb",
    fields=[
        OutgoingPacketField(
            name="x",
            field_type=PacketFieldType.GCHAR,
            description="X coordinate of bomb (in tiles)",
            default=0
        ),
        OutgoingPacketField(
            name="y",
            field_type=PacketFieldType.GCHAR,
            description="Y coordinate of bomb (in tiles)",
            default=0
        )
    ],
    variable_length=False,
    builder_class=BombDelBuilder
)


class BombDelPacketHelper:
    """Helper class for easier BombDel packet construction"""
    
    @staticmethod
    def create(x: float, y: float) -> OutgoingPacket:
        """Create a new BombDel packet
        
        Args:
            x: X coordinate of bomb (in tiles)
            y: Y coordinate of bomb (in tiles)
        """
        return PLI_BOMBDEL.create_packet(x=x, y=y)


# Export the helper
BombDelPacket = BombDelPacketHelper