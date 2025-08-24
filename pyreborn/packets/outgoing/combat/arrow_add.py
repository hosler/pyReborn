"""
PLI_ARROWADD - Shoot Arrow Packet

This packet is sent when the player shoots an arrow.
"""

from ...base import PacketFieldType
from .. import OutgoingPacketStructure, OutgoingPacketField


# Define the ArrowAdd packet structure
PLI_ARROWADD = OutgoingPacketStructure(
    packet_id=9,
    name="PLI_ARROWADD",
    description="Shoot an arrow",
    fields=[
        # Arrow shooting has no additional data - just the packet ID
    ],
    variable_length=False
)


class ArrowAddPacketHelper:
    """Helper class for easier ArrowAdd packet construction"""
    
    @staticmethod
    def create():
        """Create an ArrowAdd packet"""
        return PLI_ARROWADD.create_packet()


# Export the helper for easier imports
ArrowAddPacket = ArrowAddPacketHelper