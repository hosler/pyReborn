"""
PLI_BOMBADD - Drop a Bomb

Packet for dropping bombs at specified coordinates with power and timer.
"""

from ...base import PacketFieldType
from .. import OutgoingPacketStructure, OutgoingPacketField


def encode_coordinate(coord: float) -> int:
    """Encoder for bomb coordinates - converts float to wire format"""
    return min(255, int(coord * 2))


def encode_power(power: int) -> int:
    """Encoder for bomb power - ensures valid range"""
    return max(1, min(10, int(power)))


def encode_timer(timer: int) -> int:
    """Encoder for bomb timer - ensures valid range"""
    return max(1, min(255, int(timer)))


# Define the BombAdd packet structure
PLI_BOMBADD = OutgoingPacketStructure(
    packet_id=4,
    name="PLI_BOMBADD",
    description="Drop a bomb at specified position",
    fields=[
        OutgoingPacketField(
            name="x",
            field_type=PacketFieldType.GCHAR,
            description="X coordinate where to drop bomb",
            encoder=encode_coordinate
        ),
        OutgoingPacketField(
            name="y", 
            field_type=PacketFieldType.GCHAR,
            description="Y coordinate where to drop bomb",
            encoder=encode_coordinate
        ),
        OutgoingPacketField(
            name="power",
            field_type=PacketFieldType.GCHAR,
            description="Bomb power (1-10)",
            default=1,
            encoder=encode_power
        ),
        OutgoingPacketField(
            name="timer",
            field_type=PacketFieldType.GCHAR,
            description="Bomb timer in ticks",
            default=55,
            encoder=encode_timer
        )
    ],
    variable_length=False
)


class BombAddPacketHelper:
    """Helper class for easier BombAdd packet construction"""
    
    @staticmethod
    def create(x: float, y: float, power: int = 1, timer: int = 55):
        """Create a BombAdd packet"""
        return PLI_BOMBADD.create_packet(x=x, y=y, power=power, timer=timer)


# Export the helper for easier imports
BombAddPacket = BombAddPacketHelper