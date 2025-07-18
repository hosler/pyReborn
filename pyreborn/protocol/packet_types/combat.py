"""
Combat-related packet implementations  
"""

from typing import List, Optional
from ..packets import RebornPacket, PacketBuilder, PacketReader
from ..enums import PlayerToServer, ServerToPlayer


class HurtPlayerPacket(RebornPacket):
    """Client hurts another player"""
    
    def __init__(self, player_id: int, damage: float, x: Optional[float] = None, y: Optional[float] = None):
        super().__init__(PlayerToServer.PLI_HURTPLAYER)
        self.player_id = player_id
        self.damage = damage
        self.x = x
        self.y = y
        
    def to_bytes(self) -> bytes:
        """Encode packet: {7}{SHORT pid}{CHAR damage*2}[{CHAR x*2}{CHAR y*2}]"""
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        builder.add_short(self.player_id)
        builder.add_byte(int(self.damage * 2))
        
        # Optional hit location
        if self.x is not None and self.y is not None:
            builder.add_byte(int(self.x * 2))
            builder.add_byte(int(self.y * 2))
            
        return builder.build()


class HitObjectsPacket(RebornPacket):
    """Client performs hit check"""
    
    def __init__(self, x: float, y: float, width: float = 2.0, height: float = 2.0, power: float = 1.0):
        super().__init__(PlayerToServer.PLI_HITOBJECTS)
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.power = power
        
    def to_bytes(self) -> bytes:
        """Encode packet: {17}{CHAR x}{CHAR y}[{CHAR w}{CHAR h}{CHAR power}]"""
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        builder.add_byte(int(self.x))
        builder.add_byte(int(self.y))
        builder.add_byte(int(self.width))
        builder.add_byte(int(self.height))
        builder.add_byte(int(self.power * 10))
        return builder.build()


class ExplosionPacket(RebornPacket):
    """Client creates explosion"""
    
    def __init__(self, x: float, y: float, power: float = 1.0, radius: float = 2.0):
        super().__init__(PlayerToServer.PLI_EXPLOSION)
        self.x = x
        self.y = y
        self.power = power
        self.radius = radius
        
    def to_bytes(self) -> bytes:
        """Encode packet: {9}{CHAR x}{CHAR y}{CHAR power}{CHAR radius}"""
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        builder.add_byte(int(self.x))
        builder.add_byte(int(self.y))
        builder.add_byte(int(self.power * 10))
        builder.add_byte(int(self.radius * 2))
        return builder.build()


class BaddyHurtPacket(RebornPacket):
    """Client hurts a baddy/enemy"""
    
    def __init__(self, baddy_id: int, damage: float):
        super().__init__(PlayerToServer.PLI_BADDYHURT)
        self.baddy_id = baddy_id
        self.damage = damage
        
    def to_bytes(self) -> bytes:
        """Encode packet: {14}{CHAR id}{CHAR damage*4}"""
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        builder.add_byte(self.baddy_id)
        builder.add_byte(int(self.damage * 4))
        return builder.build()


# Server packets
class ServerHurtPlayerPacket:
    """Server notifies of player damage"""
    
    def __init__(self):
        self.attacker_id: int = 0
        self.target_id: int = 0
        self.damage: float = 0
        self.new_health: float = 0
        
    @classmethod
    def from_reader(cls, reader: PacketReader, packet_size: int):
        """Decode packet: {17}{SHORT attacker}{SHORT target}{CHAR damage}{CHAR health}"""
        packet = cls()
        packet.attacker_id = reader.read_short()
        packet.target_id = reader.read_short()
        packet.damage = reader.read_byte() / 2.0
        packet.new_health = reader.read_byte() / 2.0
        return packet


class ServerExplosionPacket:
    """Server notifies of explosion"""
    
    def __init__(self):
        self.x: float = 0
        self.y: float = 0
        self.power: float = 0
        self.radius: float = 0
        self.creator_id: int = 0
        
    @classmethod
    def from_reader(cls, reader: PacketReader, packet_size: int):
        """Decode packet: {19}{CHAR x}{CHAR y}{CHAR power}{CHAR radius}{SHORT creator}"""
        packet = cls()
        packet.x = reader.read_byte()
        packet.y = reader.read_byte()
        packet.power = reader.read_byte() / 10.0
        packet.radius = reader.read_byte() / 2.0
        packet.creator_id = reader.read_short()
        return packet


class ServerHitObjectsPacket:
    """Server confirms hit detection"""
    
    def __init__(self):
        self.player_id: int = 0
        self.hit_ids: List[int] = []
        
    @classmethod
    def from_reader(cls, reader: PacketReader, packet_size: int):
        """Decode packet: {46}{SHORT pid}{SHORT count}{SHORT id1}...{SHORT idN}"""
        packet = cls()
        packet.player_id = reader.read_short()
        count = reader.read_short()
        
        packet.hit_ids = []
        for _ in range(count):
            if reader.pos < packet_size:
                packet.hit_ids.append(reader.read_short())
                
        return packet


class ServerPushAwayPacket:
    """Server pushes player away"""
    
    def __init__(self):
        self.player_id: int = 0
        self.delta_x: float = 0
        self.delta_y: float = 0
        
    @classmethod  
    def from_reader(cls, reader: PacketReader, packet_size: int):
        """Decode packet: {28}{SHORT pid}{CHAR dx*4}{CHAR dy*4}"""
        packet = cls()
        packet.player_id = reader.read_short()
        packet.delta_x = (reader.read_byte() - 128) / 4.0
        packet.delta_y = (reader.read_byte() - 128) / 4.0
        return packet