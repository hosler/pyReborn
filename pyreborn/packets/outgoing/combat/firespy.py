"""
PLI_FIRESPY - Fire Effect Packet

This packet is sent to create a fire effect.
"""

from ...base import PacketFieldType
from .. import OutgoingPacketStructure, OutgoingPacketField


# Define the FireSpy packet structure
PLI_FIRESPY = OutgoingPacketStructure(
    packet_id=10,
    name="PLI_FIRESPY",
    description="Create fire effect",
    fields=[
        # Fire effect has no additional data - just the packet ID
    ],
    variable_length=False
)


class FireSpyPacketHelper:
    """Helper class for easier FireSpy packet construction"""
    
    @staticmethod
    def create():
        """Create a FireSpy packet"""
        return PLI_FIRESPY.create_packet()


# Export the helper for easier imports
FireSpyPacket = FireSpyPacketHelper