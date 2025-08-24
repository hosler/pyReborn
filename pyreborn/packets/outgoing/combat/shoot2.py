"""
PLI_SHOOT2 - Shoot Projectile (v2) Packet

This packet is sent to shoot a projectile. This is the newer version
with gravity support and better precision.
"""

from ...base import PacketFieldType
from .. import OutgoingPacketStructure, OutgoingPacketField


def encode_coord_short(value: float) -> int:
    """Encode coordinate to short value (pixels)"""
    return int(value * 16)  # Convert tiles to pixels


def encode_angle(angle: float) -> int:
    """Encode angle with higher precision"""
    return min(223, int(angle * 40))


def encode_value(value: int) -> int:
    """Ensure value is in valid byte range"""
    return min(223, max(0, int(value)))


# Define the Shoot2 packet structure
PLI_SHOOT2 = OutgoingPacketStructure(
    packet_id=48,
    name="PLI_SHOOT2",
    description="Shoot a projectile (v2 format with gravity)",
    fields=[
        # Position (2 bytes each for better precision)
        OutgoingPacketField("x", PacketFieldType.GSHORT, "X position in pixels", encoder=encode_coord_short),
        OutgoingPacketField("y", PacketFieldType.GSHORT, "Y position in pixels", encoder=encode_coord_short),
        OutgoingPacketField("z", PacketFieldType.GSHORT, "Z position", default=50),
        
        # Level offsets
        OutgoingPacketField("level_x", PacketFieldType.BYTE, "Level X offset", default=0),
        OutgoingPacketField("level_y", PacketFieldType.BYTE, "Level Y offset", default=0),
        
        # Physics
        OutgoingPacketField("angle", PacketFieldType.BYTE, "Angle", default=0, encoder=encode_angle),
        OutgoingPacketField("z_angle", PacketFieldType.BYTE, "Z angle", default=0),
        OutgoingPacketField("speed", PacketFieldType.BYTE, "Projectile speed", default=20, encoder=encode_value),
        OutgoingPacketField("gravity", PacketFieldType.BYTE, "Gravity effect", default=8, encoder=encode_value),
        
        # Gani (with 2-byte length prefix)
        OutgoingPacketField("gani_length", PacketFieldType.GSHORT, "Gani length", default=0),
        OutgoingPacketField("gani", PacketFieldType.VARIABLE_DATA, "Animation file", default=""),
        
        # Shoot params
        OutgoingPacketField("params", PacketFieldType.STRING_LEN, "Shoot parameters", default="")
    ],
    variable_length=True
)


class Shoot2PacketHelper:
    """Helper class for easier Shoot2 packet construction"""
    
    @staticmethod
    def create(x: float, y: float, angle: float = 0, speed: int = 20,
               gravity: int = 8, gani: str = "", z: float = 50):
        """Create a Shoot2 packet
        
        Args:
            x: X position in tiles
            y: Y position in tiles
            angle: Angle
            speed: Projectile speed
            gravity: Gravity effect (0-223)
            gani: Animation file
            z: Z position
        """
        return PLI_SHOOT2.create_packet(
            x=x, y=y, z=z, angle=angle,
            speed=speed, gravity=gravity,
            gani_length=len(gani), gani=gani
        )


# Export the helper for easier imports
Shoot2Packet = Shoot2PacketHelper