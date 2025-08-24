"""
PLI_WEAPONADD - Add Weapon Packet

This packet is sent to add/select a weapon.
"""

from ...base import PacketFieldType
from .. import OutgoingPacketStructure, OutgoingPacketField


def encode_weapon_id(weapon_id: int) -> int:
    """Ensure weapon ID is valid"""
    return max(0, min(255, int(weapon_id)))


# Define the WeaponAdd packet structure
PLI_WEAPONADD = OutgoingPacketStructure(
    packet_id=33,
    name="PLI_WEAPONADD",
    description="Add/select a weapon",
    fields=[
        OutgoingPacketField(
            name="weapon_id",
            field_type=PacketFieldType.BYTE,
            description="Weapon ID to add/select",
            encoder=encode_weapon_id
        )
    ],
    variable_length=False
)


class WeaponAddPacketHelper:
    """Helper class for easier WeaponAdd packet construction"""
    
    @staticmethod
    def create(weapon_id: int):
        """Create a WeaponAdd packet
        
        Args:
            weapon_id: ID of the weapon to add/select
        """
        return PLI_WEAPONADD.create_packet(weapon_id=weapon_id)


# Export the helper for easier imports
WeaponAddPacket = WeaponAddPacketHelper