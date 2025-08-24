"""
PLI_SHOOT - Shoot Projectile (v1) Packet

This packet is sent to shoot a projectile. This is the older version
without gravity support.
"""

from ...base import PacketFieldType
from .. import OutgoingPacketStructure, OutgoingPacketField


def encode_coord(value: float) -> int:
    """Encode coordinate to byte value"""
    return min(223, int(value * 16))  # Pixels, max 223


def encode_angle(angle: float) -> int:
    """Encode angle (0-π radians to 0-220)"""
    return min(220, int(angle * 220 / 3.14159))


def encode_speed(speed: int) -> int:
    """Ensure speed is in valid range"""
    return min(223, max(0, int(speed)))


def encode_z(z: float) -> int:
    """Encode Z coordinate"""
    return min(223, int(z))


# Define the Shoot packet structure
PLI_SHOOT = OutgoingPacketStructure(
    packet_id=40,
    name="PLI_SHOOT",
    description="Shoot a projectile (v1 format)",
    fields=[
        # Unknown ID (4 bytes of 0)
        OutgoingPacketField("unknown_id", PacketFieldType.GINT4, "Unknown ID (always 0)", default=0),
        
        # Position
        OutgoingPacketField("x", PacketFieldType.BYTE, "X position in pixels", encoder=encode_coord),
        OutgoingPacketField("y", PacketFieldType.BYTE, "Y position in pixels", encoder=encode_coord),
        OutgoingPacketField("z", PacketFieldType.BYTE, "Z position", default=50, encoder=encode_z),
        
        # Angles
        OutgoingPacketField("angle", PacketFieldType.BYTE, "Angle (0-220 = 0-π)", default=0, encoder=encode_angle),
        OutgoingPacketField("z_angle", PacketFieldType.BYTE, "Z angle", default=0),
        
        # Speed
        OutgoingPacketField("speed", PacketFieldType.BYTE, "Projectile speed", default=20, encoder=encode_speed),
        
        # Gani
        OutgoingPacketField("gani", PacketFieldType.STRING_LEN, "Animation file", default=""),
        
        # Shoot params (empty)
        OutgoingPacketField("params", PacketFieldType.STRING_LEN, "Shoot parameters", default="")
    ],
    variable_length=True
)


class ShootPacketHelper:
    """Helper class for easier Shoot packet construction"""
    
    @staticmethod
    def create(x: float, y: float, angle: float = 0, speed: int = 20, 
               gani: str = "", z: float = 50):
        """Create a Shoot packet
        
        Args:
            x: X position in tiles
            y: Y position in tiles
            angle: Angle in radians (0-π)
            speed: Projectile speed
            gani: Animation file
            z: Z position
        """
        return PLI_SHOOT.create_packet(
            x=x, y=y, z=z, angle=angle, 
            speed=speed, gani=gani
        )


# Export the helper for easier imports
ShootPacket = ShootPacketHelper