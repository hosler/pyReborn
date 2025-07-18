"""
Packet structure definitions and builders
"""

from typing import List, Union, Optional
from ..protocol.enums import PlayerToServer, ServerToPlayer, PlayerProp


class PacketReader:
    """Utility for reading packet data"""
    
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
    
    def read_byte(self) -> int:
        """Read single byte (with -32 decoding)"""
        if self.pos >= len(self.data):
            return 0
        value = self.data[self.pos] - 32
        self.pos += 1
        return max(0, value)
    
    def read_raw_byte(self) -> int:
        """Read raw byte without decoding"""
        if self.pos >= len(self.data):
            return 0
        value = self.data[self.pos]
        self.pos += 1
        return value
    
    def read_short(self) -> int:
        """Read 2-byte value"""
        low = self.read_byte()
        high = self.read_byte()
        return low | (high << 8)
    
    def read_int(self) -> int:
        """Read 4-byte value"""
        value = 0
        for i in range(4):
            value |= (self.read_byte() << (i * 8))
        return value
    
    def read_string(self, length: Optional[int] = None) -> str:
        """Read string with optional fixed length"""
        if length is None:
            # Read length-prefixed string
            length = self.read_byte()
            if length < 0 or length > 223:  # Sanity check
                return ""
        
        if self.pos + length > len(self.data):
            length = len(self.data) - self.pos
        text = self.data[self.pos:self.pos + length].decode('ascii', errors='replace')
        self.pos += length
        return text
    
    def read_gstring(self) -> str:
        """Read newline-terminated string"""
        text = ""
        while self.pos < len(self.data):
            char = self.read_raw_byte()
            if char == ord('\n'):
                break
            text += chr(char)
        return text
    
    def bytes_available(self) -> int:
        """Get remaining bytes"""
        return len(self.data) - self.pos
    
    def has_more(self) -> bool:
        """Check if more data available"""
        return self.pos < len(self.data)
    
    def peek_byte(self) -> int:
        """Peek at next byte without advancing"""
        if self.pos >= len(self.data):
            return 0
        return self.data[self.pos] - 32

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
        """Add a Reborn string (newline terminated)"""
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


class RebornPacket:
    """Base class for all packets"""
    
    def __init__(self, packet_id: Union[PlayerToServer, ServerToPlayer]):
        self.packet_id = packet_id
    
    def to_bytes(self) -> bytes:
        """Convert packet to bytes for sending"""
        raise NotImplementedError


class PlayerPropsPacket(RebornPacket):
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
                    # Clamp negative values to 0, max to 255
                    clamped_value = max(0, min(255, int(value * 2)))
                    builder.add_byte(clamped_value)
                else:
                    builder.add_byte(value)
            elif prop in [PlayerProp.PLPROP_GMAPLEVELX, PlayerProp.PLPROP_GMAPLEVELY]:
                # GMAP level coordinates are sent as single bytes
                builder.add_byte(max(0, min(255, int(value))))
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


class LoginPacket(RebornPacket):
    """Login packet with configurable version support"""
    
    def __init__(self, account: str, password: str, encryption_key: int, version_config=None):
        super().__init__(None)  # Login has no packet ID
        self.account = account
        self.password = password
        self.encryption_key = encryption_key
        self.version_config = version_config
    
    def to_bytes(self) -> bytes:
        """Create login packet based on version configuration"""
        from ..protocol.versions import ClientType, get_default_version
        
        # Use provided config or default
        config = self.version_config or get_default_version()
        
        packet = bytearray()
        
        # Client type byte
        packet.append(config.client_type.value + 32)
        
        # Encryption key
        packet.append((self.encryption_key + 32) & 0xFF)
        
        # Protocol version string (must be exactly 8 bytes)
        version_bytes = config.protocol_string.encode('ascii')
        if len(version_bytes) != 8:
            raise ValueError(f"Version string must be 8 bytes, got {len(version_bytes)}: {config.protocol_string}")
        packet.extend(version_bytes)
        
        # Account and password
        packet.append(len(self.account) + 32)
        packet.extend(self.account.encode('ascii'))
        packet.append(len(self.password) + 32)
        packet.extend(self.password.encode('ascii'))
        
        # Build string (if version sends it)
        if config.sends_build and config.build_string:
            packet.append(len(config.build_string) + 32)
            packet.extend(config.build_string.encode('ascii'))
        
        # Client info/identity string
        # Format: {platform},{mobile_id},{harddisk_md5},{network_md5},{os_info},{android_id}
        if config.version_id >= 19:  # Linux 6.037
            packet.extend(b'linux,,,,,PyReborn')
        else:
            packet.extend(b'PC,,,,,PyReborn')
        
        # Debug: Log what we're sending
        print(f"DEBUG: Login packet for version {config.name}:")
        print(f"  Client type: {config.client_type.value} (+32 = {config.client_type.value + 32})")
        print(f"  Version string: {config.protocol_string} (hex: {version_bytes.hex()})")
        print(f"  Full packet ({len(packet)} bytes): {packet[:30].hex()}...")
        
        return bytes(packet)


class ToAllPacket(RebornPacket):
    """Send chat message to all players"""
    
    def __init__(self, message: str):
        super().__init__(PlayerToServer.PLI_TOALL)
        self.message = message
    
    def to_bytes(self) -> bytes:
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        builder.add_gstring(self.message)
        return builder.build()


class BombAddPacket(RebornPacket):
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


class ArrowAddPacket(RebornPacket):
    """Shoot an arrow (simple)"""
    
    def __init__(self):
        super().__init__(PlayerToServer.PLI_ARROWADD)
    
    def to_bytes(self) -> bytes:
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        return builder.end_packet().build()


class FireSpyPacket(RebornPacket):
    """Fire effect"""
    
    def __init__(self):
        super().__init__(PlayerToServer.PLI_FIRESPY)
    
    def to_bytes(self) -> bytes:
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        return builder.end_packet().build()


class WeaponAddPacket(RebornPacket):
    """Add a weapon"""
    
    def __init__(self, weapon_id: int):
        super().__init__(PlayerToServer.PLI_WEAPONADD)
        self.weapon_id = weapon_id
    
    def to_bytes(self) -> bytes:
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        builder.add_byte(self.weapon_id)
        return builder.end_packet().build()


class ShootPacket(RebornPacket):
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


class Shoot2Packet(RebornPacket):
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


class WantFilePacket(RebornPacket):
    """Request a file from server"""
    
    def __init__(self, filename: str):
        super().__init__(PlayerToServer.PLI_WANTFILE)
        self.filename = filename
    
    def to_bytes(self) -> bytes:
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        builder.add_gstring(self.filename)
        return builder.build()


class FlagSetPacket(RebornPacket):
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


class PrivateMessagePacket(RebornPacket):
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


class RequestUpdateBoardPacket(RebornPacket):
    """Request board update for specific level region"""
    
    def __init__(self, level: str, mod_time: int, x: int, y: int, width: int, height: int):
        super().__init__(PlayerToServer.PLI_REQUESTUPDATEBOARD)
        self.level = level
        self.mod_time = mod_time
        self.x = x
        self.y = y
        self.width = width
        self.height = height
    
    def to_bytes(self) -> bytes:
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        builder.add_string(self.level)
        
        # Add 5-byte mod time
        for i in range(5):
            builder.add_byte((self.mod_time >> (i * 7)) & 0x7F)
        
        # Add coordinates
        builder.add_short(self.x)
        builder.add_short(self.y)
        builder.add_short(self.width)
        builder.add_short(self.height)
        
        return builder.end_packet().build()


class RequestTextPacket(RebornPacket):
    """Request a text value from server"""
    
    def __init__(self, key: str):
        super().__init__(PlayerToServer.PLI_REQUESTTEXT)
        self.key = key
    
    def to_bytes(self) -> bytes:
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        builder.add_gstring(self.key)
        return builder.build()


class SendTextPacket(RebornPacket):
    """Send a text value to server"""
    
    def __init__(self, key: str, value: str):
        super().__init__(PlayerToServer.PLI_SENDTEXT)
        self.key = key
        self.value = value
    
    def to_bytes(self) -> bytes:
        builder = PacketBuilder()
        builder.add_packet_id(self.packet_id)
        builder.add_string(self.key)
        builder.add_gstring(self.value)
        return builder.build()