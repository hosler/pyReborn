"""
PLI_PRIVATEMESSAGE - Send Private Message Packet

This packet is sent to send a private message to another player.
"""

from ...base import PacketFieldType
from .. import OutgoingPacketStructure, OutgoingPacketField


def encode_player_id(player_id: int) -> int:
    """Ensure player ID is valid"""
    return max(0, min(65535, int(player_id)))


def encode_message(message: str) -> str:
    """Ensure message is valid"""
    # Limit length and convert to string
    return str(message)[:200]


# Define the PrivateMessage packet structure
PLI_PRIVATEMESSAGE = OutgoingPacketStructure(
    packet_id=28,
    name="PLI_PRIVATEMESSAGE",
    description="Send a private message to another player",
    fields=[
        OutgoingPacketField(
            name="player_id",
            field_type=PacketFieldType.GSHORT,
            description="Target player ID",
            encoder=encode_player_id
        ),
        OutgoingPacketField(
            name="message",
            field_type=PacketFieldType.VARIABLE_DATA,
            description="Message to send",
            encoder=encode_message
        )
    ],
    variable_length=True
)


class PrivateMessagePacketHelper:
    """Helper class for easier PrivateMessage packet construction"""
    
    @staticmethod
    def create(player_id: int, message: str):
        """Create a PrivateMessage packet
        
        Args:
            player_id: ID of the player to send message to
            message: Message text to send
        """
        return PLI_PRIVATEMESSAGE.create_packet(player_id=player_id, message=message)


# Export the helper for easier imports
PrivateMessagePacket = PrivateMessagePacketHelper