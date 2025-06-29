"""
Packet structure definitions and builders
"""

from typing import List, Union, Optional
from ..protocol.enums import PlayerToServer, ServerToPlayer, PlayerProp

class PacketBuilder:
    """Utility class for building packets"""
    
    def __init__(self):
        self.data = bytearray()
    
    def add_byte(self, value: int) -> 'PacketBuilder':
        """Add a single byte (with +32 encoding)"""
        self.data.append(min(223, value) + 32)
        return self
    
    def add_raw_byte(self, value: int) -> 'PacketBuilder':
        """Add a raw byte without encoding"""
        self.data.append(value)
        return self
    
    def add_string(self, text: str, length_byte: bool = True) -> 'PacketBuilder':
        """Add a string with optional length prefix"""
        if length_byte:
            self.add_byte(len(text))
        self.data.extend(text.encode('ascii', errors='replace'))
        return self
    
    def add_gstring(self, text: str) -> 'PacketBuilder':
        """Add a Graal string (newline terminated)"""
        self.data.extend(text.encode('ascii', errors='replace'))
        self.add_raw_byte(ord('\n'))
        return self
    
    def add_short(self, value: int) -> 'PacketBuilder':
        """Add a 2-byte value (little endian)"""
        self.add_byte(value & 0xFF)
        self.add_byte((value >> 8) & 0xFF)
        return self
    
    def add_int(self, value: int) -> 'PacketBuilder':
        """Add a 4-byte value"""
        for i in range(4):
            self.add_byte((value >> (i * 8)) & 0xFF)
        return self
    
    def add_packet_id(self, packet_id: Union[PlayerToServer, int]) -> 'PacketBuilder':
        """Add a packet ID"""
        self.add_byte(int(packet_id))
        return self
    
    def end_packet(self) -> 'PacketBuilder':
        """Add packet terminator"""
        self.add_raw_byte(ord('\n'))
        return self
    
    def build(self) -> bytes:
        """Return the final packet bytes"""
        return bytes(self.data)


class GraalPacket:
    """Base class for all packets"""
    
    def __init__(self, packet_id: Union[PlayerToServer, ServerToPlayer]):
        self.packet_id = packet_id
    
    def to_bytes(self) -> bytes:
        """Convert packet to bytes for sending"""
        raise NotImplementedError


class PlayerPropsPacket(GraalPacket):
    """Set player properties"""
    
    def __init__(self):
        super().__init__(PlayerToServer.PLI_PLAYERPROPS)
        self.properties = []
    
    def add_property(self, prop: PlayerProp, value: Union[int, str]) -> 'PlayerPropsPacket':
        """Add a property to set"""
        self.properties.append((prop, value))
        return self
    
    def to_bytes(self) -> bytes:
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        
        for prop, value in self.properties:
            builder.add_byte(int(prop))
            
            # Handle different property types
            if prop in [PlayerProp.PLPROP_X, PlayerProp.PLPROP_Y, PlayerProp.PLPROP_SPRITE]:
                # Fixed-size properties - NO length field
                if prop in [PlayerProp.PLPROP_X, PlayerProp.PLPROP_Y]:
                    builder.add_byte(min(255, int(value * 2)))
                else:
                    builder.add_byte(value)
            elif prop == PlayerProp.PLPROP_HEADGIF:
                # Head image uses length + 100
                builder.add_byte(len(str(value)) + 100)
                builder.add_string(str(value), length_byte=False)
            elif prop == PlayerProp.PLPROP_SWORDPOWER:
                # Sword power special encoding
                if isinstance(value, tuple):
                    sword_id, sword_image = value
                    builder.add_byte(len(sword_image))
                    builder.add_byte(sword_id + 30)  # +30 offset for sword power
                    builder.add_string(sword_image, length_byte=False)
                else:
                    builder.add_byte(1)
                    builder.add_byte(value + 30)
                    builder.add_string(str(value), length_byte=False)
            elif isinstance(value, str):
                # String properties with length
                builder.add_string(value)
            else:
                # Numeric properties (single byte)
                builder.add_byte(value)
        
        return builder.end_packet().build()


class LoginPacket(GraalPacket):
    """Login packet with PLTYPE_CLIENT3 format (fixed from working client)"""
    
    def __init__(self, account: str, password: str, encryption_key: int):
        super().__init__(None)  # Login has no packet ID
        self.account = account
        self.password = password
        self.encryption_key = encryption_key
    
    def to_bytes(self) -> bytes:
        """Create PLTYPE_CLIENT3 login packet (matches working format)"""
        packet = bytearray()
        packet.append(37)  # PLTYPE_CLIENT3
        packet.append((self.encryption_key + 32) & 0xFF)
        packet.extend(b'GNW03014')
        packet.append(len(self.account) + 32)
        packet.extend(self.account.encode('ascii'))
        packet.append(len(self.password) + 32)
        packet.extend(self.password.encode('ascii'))
        packet.extend(b'PC,,,,,Python')
        
        return bytes(packet)


class ToAllPacket(GraalPacket):
    """Send chat message to all players"""
    
    def __init__(self, message: str):
        super().__init__(PlayerToServer.PLI_TOALL)
        self.message = message
    
    def to_bytes(self) -> bytes:
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        builder.add_gstring(self.message)
        return builder.build()


class BombAddPacket(GraalPacket):
    """Drop a bomb"""
    
    def __init__(self, x: float, y: float, power: int = 1, timer: int = 55):
        super().__init__(PlayerToServer.PLI_BOMBADD)
        self.x = x
        self.y = y
        self.power = power
        self.timer = timer
    
    def to_bytes(self) -> bytes:
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        builder.add_byte(min(255, int(self.x * 2)))
        builder.add_byte(min(255, int(self.y * 2)))
        builder.add_byte(self.power)
        builder.add_byte(self.timer)
        return builder.end_packet().build()


class ArrowAddPacket(GraalPacket):
    """Shoot an arrow (simple)"""
    
    def __init__(self):
        super().__init__(PlayerToServer.PLI_ARROWADD)
    
    def to_bytes(self) -> bytes:
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        return builder.end_packet().build()


class FireSpyPacket(GraalPacket):
    """Fire effect"""
    
    def __init__(self):
        super().__init__(PlayerToServer.PLI_FIRESPY)
    
    def to_bytes(self) -> bytes:
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        return builder.end_packet().build()


class WeaponAddPacket(GraalPacket):
    """Add a weapon"""
    
    def __init__(self, weapon_id: int):
        super().__init__(PlayerToServer.PLI_WEAPONADD)
        self.weapon_id = weapon_id
    
    def to_bytes(self) -> bytes:
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        builder.add_byte(self.weapon_id)
        return builder.end_packet().build()


class ShootPacket(GraalPacket):
    """Shoot projectile (v1 format)"""
    
    def __init__(self, x: float, y: float, angle: float = 0, speed: int = 20, 
                 gani: str = "", z: float = 50):
        super().__init__(PlayerToServer.PLI_SHOOT)
        self.x = x
        self.y = y
        self.z = z
        self.angle = angle
        self.speed = speed
        self.gani = gani
    
    def to_bytes(self) -> bytes:
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        
        # Unknown ID (4 bytes of 0)
        for _ in range(4):
            builder.add_byte(0)
        
        # Position (pixels)
        builder.add_byte(min(223, int(self.x * 16)))
        builder.add_byte(min(223, int(self.y * 16)))
        builder.add_byte(min(223, int(self.z)))
        
        # Angles (0-220 represents 0-π)
        builder.add_byte(min(220, int(self.angle * 220 / 3.14159)))
        builder.add_byte(0)  # Z-angle
        
        # Speed
        builder.add_byte(min(223, self.speed))
        
        # Gani
        builder.add_string(self.gani)
        
        # Shoot params (empty)
        builder.add_byte(0)
        
        return builder.end_packet().build()


class Shoot2Packet(GraalPacket):
    """Shoot projectile (v2 format with gravity)"""
    
    def __init__(self, x: float, y: float, angle: float = 0, speed: int = 20,
                 gravity: int = 8, gani: str = "", z: float = 50):
        super().__init__(PlayerToServer.PLI_SHOOT2)
        self.x = x
        self.y = y
        self.z = z
        self.angle = angle
        self.speed = speed
        self.gravity = gravity
        self.gani = gani
    
    def to_bytes(self) -> bytes:
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        
        # Position (2 bytes each)
        builder.add_short(int(self.x * 16))
        builder.add_short(int(self.y * 16))
        builder.add_short(int(self.z))
        
        # Level offsets
        builder.add_byte(0)
        builder.add_byte(0)
        
        # Physics
        builder.add_byte(min(223, int(self.angle * 40)))
        builder.add_byte(0)  # Z-angle
        builder.add_byte(min(223, self.speed))
        builder.add_byte(min(223, self.gravity))
        
        # Gani (2-byte length)
        builder.add_short(len(self.gani))
        builder.add_string(self.gani, length_byte=False)
        
        # Shoot params
        builder.add_byte(0)
        
        return builder.end_packet().build()


class WantFilePacket(GraalPacket):
    """Request a file from server"""
    
    def __init__(self, filename: str):
        super().__init__(PlayerToServer.PLI_WANTFILE)
        self.filename = filename
    
    def to_bytes(self) -> bytes:
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        builder.add_gstring(self.filename)
        return builder.build()


class FlagSetPacket(GraalPacket):
    """Set a server flag"""
    
    def __init__(self, flag_name: str, value: str = ""):
        super().__init__(PlayerToServer.PLI_FLAGSET)
        self.flag_name = flag_name
        self.value = value
    
    def to_bytes(self) -> bytes:
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        builder.add_string(self.flag_name)
        builder.add_gstring(self.value)
        return builder.build()


class PrivateMessagePacket(GraalPacket):
    """Send private message to player"""
    
    def __init__(self, player_id: int, message: str):
        super().__init__(PlayerToServer.PLI_PRIVATEMESSAGE)
        self.player_id = player_id
        self.message = message
    
    def to_bytes(self) -> bytes:
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        builder.add_short(self.player_id)
        builder.add_gstring(self.message)
        return builder.build()