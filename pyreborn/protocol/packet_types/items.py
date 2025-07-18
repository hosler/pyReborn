"""
Item-related packet implementations
"""

from typing import Optional
from ..packets import RebornPacket, PacketBuilder, PacketReader
from ..enums import PlayerToServer, ServerToPlayer, LevelItemType


class ItemAddPacket(RebornPacket):
    """Client requests to add an item (drop)"""
    
    def __init__(self, x: float, y: float, item_type: int):
        super().__init__(PlayerToServer.PLI_ITEMADD)
        self.x = x
        self.y = y
        self.item_type = item_type
        
    def to_bytes(self) -> bytes:
        """Encode packet: {12}{CHAR x*2}{CHAR y*2}{CHAR item}"""
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        builder.add_byte(int(self.x * 2))
        builder.add_byte(int(self.y * 2))
        builder.add_byte(self.item_type)
        return builder.build()
        

class ItemDeletePacket(RebornPacket):
    """Client requests to delete an item (pickup)"""
    
    def __init__(self, x: float, y: float):
        super().__init__(PlayerToServer.PLI_ITEMDEL)
        self.x = x
        self.y = y
        
    def to_bytes(self) -> bytes:
        """Encode packet: {13}{CHAR x*2}{CHAR y*2}"""
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        builder.add_byte(int(self.x * 2))
        builder.add_byte(int(self.y * 2))
        return builder.build()


class ItemTakePacket(RebornPacket):
    """Client takes an item (v2.31+)"""
    
    def __init__(self, player_id: int, item_id: int):
        super().__init__(PlayerToServer.PLI_ITEMTAKE)
        self.player_id = player_id
        self.item_id = item_id
        
    def to_bytes(self) -> bytes:
        """Encode packet: {32}{SHORT pid}{CHAR item}"""
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        builder.add_short(self.player_id)
        builder.add_byte(self.item_id)
        return builder.build()


class OpenChestPacket(RebornPacket):
    """Client opens a chest"""
    
    def __init__(self, x: int, y: int):
        super().__init__(PlayerToServer.PLI_OPENCHEST)
        self.x = x
        self.y = y
        
    def to_bytes(self) -> bytes:
        """Encode packet: {20}{CHAR x}{CHAR y}"""
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        builder.add_byte(self.x)
        builder.add_byte(self.y)
        return builder.build()


class ThrowCarriedPacket(RebornPacket):
    """Client throws carried object"""
    
    def __init__(self, power: float = 1.0):
        super().__init__(PlayerToServer.PLI_THROWCARRIED)
        self.power = power
        
    def to_bytes(self) -> bytes:
        """Encode packet: {11}{CHAR power}"""
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        builder.add_byte(int(self.power * 10))
        return builder.build()


# Server packets - these are parsed, not sent
class ServerItemAddPacket:
    """Server notifies of item spawn"""
    
    def __init__(self):
        self.x: float = 0
        self.y: float = 0
        self.item_type: int = 0
        self.item_id: Optional[int] = None
        
    @classmethod
    def from_reader(cls, reader: PacketReader, packet_size: int):
        """Decode packet: {22}{CHAR x*2}{CHAR y*2}{CHAR type}[{SHORT id}]"""
        packet = cls()
        packet.x = reader.read_byte() / 2.0
        packet.y = reader.read_byte() / 2.0
        packet.item_type = reader.read_byte()
        
        # Optional item ID for v2.31+
        if reader.pos < packet_size:
            packet.item_id = reader.read_short()
            
        return packet


class ServerItemDeletePacket:
    """Server notifies of item removal"""
    
    def __init__(self):
        self.x: float = 0
        self.y: float = 0
        
    @classmethod
    def from_reader(cls, reader: PacketReader, packet_size: int):
        """Decode packet: {23}{CHAR x*2}{CHAR y*2}"""
        packet = cls()
        packet.x = reader.read_byte() / 2.0
        packet.y = reader.read_byte() / 2.0
        return packet


class ServerThrowCarriedPacket:
    """Server notifies of thrown object"""
    
    def __init__(self):
        self.player_id: int = 0
        self.power: float = 0
        
    @classmethod
    def from_reader(cls, reader: PacketReader, packet_size: int):
        """Decode packet: {20}{SHORT pid}{CHAR power}"""
        packet = cls()
        packet.player_id = reader.read_short()
        packet.power = reader.read_byte() / 10.0
        return packet