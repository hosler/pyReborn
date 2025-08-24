"""
PLI_HORSEADD - Horse Add Packet

This packet notifies the server that the player has mounted a horse.
"""

import logging
from ...base import PacketFieldType
from .. import OutgoingPacketStructure, OutgoingPacketField, OutgoingPacket

logger = logging.getLogger(__name__)


class HorseAddBuilder:
    """Custom builder for HorseAdd packets"""
    
    def build_packet(self, packet: OutgoingPacket) -> bytes:
        """Build HorseAdd packet"""
        from pyreborn.protocol.enums import PlayerToServer
        
        data = bytearray()
        data.append(PlayerToServer.PLI_HORSEADD + 32)  # Packet ID + 32
        
        # Get fields
        x = packet.get_field('x') or 0
        y = packet.get_field('y') or 0
        sprite = packet.get_field('sprite') or 0
        image = packet.get_field('image') or "horse1.gif"
        bushes = packet.get_field('bushes') or 0
        
        # Add horse position (in half-tiles)
        data.append(int(x * 2) + 32)
        data.append(int(y * 2) + 32)
        
        # Add sprite direction (0-3)
        data.append((sprite & 0x03) + 32)
        
        # Add bushes level (0-2)
        data.append((bushes & 0x03) + 32)
        
        # Add horse image
        data.append(len(image) + 32)
        data.extend(image.encode('ascii', errors='replace'))
        
        # End packet with newline
        data.append(10)
        return bytes(data)


# Define the HorseAdd packet structure
PLI_HORSEADD = OutgoingPacketStructure(
    packet_id=7,
    name="PLI_HORSEADD",
    description="Mount a horse",
    fields=[
        OutgoingPacketField(
            name="x",
            field_type=PacketFieldType.GCHAR,
            description="X coordinate (in tiles)",
            default=0
        ),
        OutgoingPacketField(
            name="y",
            field_type=PacketFieldType.GCHAR,
            description="Y coordinate (in tiles)",
            default=0
        ),
        OutgoingPacketField(
            name="sprite",
            field_type=PacketFieldType.GCHAR,
            description="Direction sprite (0=up, 1=left, 2=down, 3=right)",
            default=2
        ),
        OutgoingPacketField(
            name="bushes",
            field_type=PacketFieldType.GCHAR,
            description="Bushes level (0-2)",
            default=0
        ),
        OutgoingPacketField(
            name="image",
            field_type=PacketFieldType.STRING_GCHAR_LEN,
            description="Horse image filename",
            default="horse1.gif"
        )
    ],
    variable_length=True,
    builder_class=HorseAddBuilder
)


class HorseAddPacketHelper:
    """Helper class for easier HorseAdd packet construction"""
    
    @staticmethod
    def create(x: float = 0, y: float = 0, sprite: int = 2, 
               image: str = "horse1.gif", bushes: int = 0) -> OutgoingPacket:
        """Create a new HorseAdd packet
        
        Args:
            x: X coordinate (in tiles)
            y: Y coordinate (in tiles)
            sprite: Direction (0=up, 1=left, 2=down, 3=right)
            image: Horse image filename
            bushes: Bushes level (0-2)
        """
        return PLI_HORSEADD.create_packet(
            x=x, y=y, sprite=sprite, image=image, bushes=bushes
        )


# Export the helper
HorseAddPacket = HorseAddPacketHelper