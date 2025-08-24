"""
PLI_OPENCHEST - Open Chest Packet

This packet is sent when the player opens a chest.
"""

from ...base import PacketFieldType
from .. import OutgoingPacketStructure, OutgoingPacketField


def encode_coord(value: int) -> int:
    """Ensure coordinate is valid"""
    return max(0, min(255, int(value)))


# Define the OpenChest packet structure
PLI_OPENCHEST = OutgoingPacketStructure(
    packet_id=20,
    name="PLI_OPENCHEST",
    description="Open a chest",
    fields=[
        OutgoingPacketField(
            name="x",
            field_type=PacketFieldType.BYTE,
            description="Chest X coordinate in tiles",
            encoder=encode_coord
        ),
        OutgoingPacketField(
            name="y",
            field_type=PacketFieldType.BYTE,
            description="Chest Y coordinate in tiles",
            encoder=encode_coord
        )
    ],
    variable_length=False
)


class OpenChestPacketHelper:
    """Helper class for easier OpenChest packet construction"""
    
    @staticmethod
    def create(x: int, y: int):
        """Create an OpenChest packet
        
        Args:
            x: Chest X coordinate in tiles
            y: Chest Y coordinate in tiles
        """
        return PLI_OPENCHEST.create_packet(x=x, y=y)


# Export the helper for easier imports
OpenChestPacket = OpenChestPacketHelper