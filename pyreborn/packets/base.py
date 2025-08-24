#!/usr/bin/env python3
"""
Base classes for packet structure definitions

These classes are used by all packet definition files to maintain consistency
and provide a unified interface for packet parsing and validation.
"""

from enum import IntEnum
from dataclasses import dataclass
from typing import List, Optional, Union, Dict, Any


class PacketFieldType(IntEnum):
    """Field types in packet structures"""
    BYTE = 1           # 1 byte
    GCHAR = 2          # 1 byte with +32 offset  
    GSHORT = 3         # 2 bytes with GServer encoding (GShort)
    GINT3 = 4          # 3 bytes with GServer encoding
    GINT4 = 5          # 4 bytes with GServer encoding  
    GINT5 = 6          # 5 bytes with GServer encoding
    STRING_LEN = 7     # Length-prefixed string (1 byte len + string)
    STRING_GCHAR_LEN = 8  # GCHAR length + string
    FIXED_DATA = 9     # Fixed number of bytes
    VARIABLE_DATA = 10  # Variable data (rest of packet)
    ANNOUNCED_DATA = 11 # Data size announced by previous PLO_RAWDATA
    COORDINATE = 12     # GCHAR coordinate with /8 division for positions


@dataclass
class PacketField:
    """Definition of a field within a packet"""
    name: str
    field_type: PacketFieldType
    size: Optional[int] = None  # For FIXED_DATA
    description: str = ""
    
    def __post_init__(self):
        """Validate field definition"""
        if self.field_type == PacketFieldType.FIXED_DATA and self.size is None:
            raise ValueError(f"FIXED_DATA field '{self.name}' must specify size")


@dataclass
class PacketStructure:
    """Complete structure definition for a packet type"""
    packet_id: int
    name: str
    fields: List[PacketField]
    description: str = ""
    variable_length: bool = False  # True if packet has variable length
    version_min: Optional[str] = None  # Minimum protocol version
    version_max: Optional[str] = None  # Maximum protocol version
    context: str = "client"  # Context for packet: "client" (default) or "rc" (remote control)
    category: str = "unknown"  # Category for packet organization
    
    def __post_init__(self):
        """Validate packet structure"""
        # Allow both PLO_ (incoming) and PLI_ (outgoing) packet names
        if not (self.name.startswith("PLO_") or self.name.startswith("PLI_")):
            raise ValueError(f"Packet name '{self.name}' should start with PLO_ (incoming) or PLI_ (outgoing)")
        
        if self.packet_id < 0 or self.packet_id > 255:
            raise ValueError(f"Packet ID {self.packet_id} must be 0-255")
        
        # Auto-detect variable length if VARIABLE_DATA is present
        for field in self.fields:
            if field.field_type in [PacketFieldType.VARIABLE_DATA, 
                                   PacketFieldType.STRING_GCHAR_LEN, 
                                   PacketFieldType.STRING_LEN]:
                self.variable_length = True
                break
    
    def get_expected_size(self) -> Optional[int]:
        """Get expected packet size if fixed, None if variable"""
        if self.variable_length:
            return None
        
        total_size = 0
        for field in self.fields:
            if field.field_type == PacketFieldType.BYTE:
                total_size += 1
            elif field.field_type == PacketFieldType.GCHAR:
                total_size += 1
            elif field.field_type == PacketFieldType.GSHORT:
                total_size += 2
            elif field.field_type == PacketFieldType.GINT3:
                total_size += 3
            elif field.field_type == PacketFieldType.GINT4:
                total_size += 4
            elif field.field_type == PacketFieldType.GINT5:
                total_size += 5
            elif field.field_type == PacketFieldType.COORDINATE:
                total_size += 1
            elif field.field_type == PacketFieldType.FIXED_DATA:
                total_size += field.size or 0
            else:
                # Variable size field - packet is variable length
                return None
        
        return total_size
    
    def supports_version(self, version: str) -> bool:
        """Check if this packet is supported in the given protocol version"""
        if self.version_min and version < self.version_min:
            return False
        if self.version_max and version > self.version_max:
            return False
        return True


class PacketCategory:
    """Base class for packet category modules"""
    
    @classmethod
    def get_packet_structures(cls) -> Dict[int, PacketStructure]:
        """Get all packet structures defined in this category
        
        Should be implemented by each category module to return
        a dictionary mapping packet_id -> PacketStructure
        """
        raise NotImplementedError("Category must implement get_packet_structures()")
    
    @classmethod
    def get_category_name(cls) -> str:
        """Get the name of this packet category"""
        return cls.__name__.replace("Packets", "").lower()


# Common field factory functions for consistency
def byte_field(name: str, description: str = "") -> PacketField:
    """Create a standard byte field"""
    return PacketField(name, PacketFieldType.BYTE, description=description)


def gchar_field(name: str, description: str = "") -> PacketField:
    """Create a GCHAR field (byte with +32 offset)"""
    return PacketField(name, PacketFieldType.GCHAR, description=description)


def gshort_field(name: str, description: str = "") -> PacketField:
    """Create a GServer short field (2 bytes)"""
    return PacketField(name, PacketFieldType.GSHORT, description=description)


def gint3_field(name: str, description: str = "") -> PacketField:
    """Create a GServer 3-byte integer field"""
    return PacketField(name, PacketFieldType.GINT3, description=description)


def gint4_field(name: str, description: str = "") -> PacketField:
    """Create a GServer 4-byte integer field"""
    return PacketField(name, PacketFieldType.GINT4, description=description)


def gint5_field(name: str, description: str = "") -> PacketField:
    """Create a GServer 5-byte integer field"""
    return PacketField(name, PacketFieldType.GINT5, description=description)


def coordinate_field(name: str, description: str = "") -> PacketField:
    """Create a coordinate field (GCHAR with /8 division)"""
    return PacketField(name, PacketFieldType.COORDINATE, description=description)


def string_field(name: str, description: str = "") -> PacketField:
    """Create a length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_LEN, description=description)


def gstring_field(name: str, description: str = "") -> PacketField:
    """Create a GCHAR length-prefixed string field"""
    return PacketField(name, PacketFieldType.STRING_GCHAR_LEN, description=description)


def fixed_data_field(name: str, size: int, description: str = "") -> PacketField:
    """Create a fixed-size data field"""
    return PacketField(name, PacketFieldType.FIXED_DATA, size=size, description=description)


def variable_data_field(name: str, description: str = "") -> PacketField:
    """Create a variable-size data field (rest of packet)"""
    return PacketField(name, PacketFieldType.VARIABLE_DATA, description=description)


def announced_data_field(name: str, description: str = "") -> PacketField:
    """Create a data field whose size was announced by PLO_RAWDATA"""
    return PacketField(name, PacketFieldType.ANNOUNCED_DATA, description=description)


class PacketReader:
    """Utility class for reading packet data with protocol-specific encodings"""
    
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
    
    def read_raw_byte(self) -> int:
        """Read a raw byte"""
        if self.pos >= len(self.data):
            return 0
        value = self.data[self.pos]
        self.pos += 1
        return value
    
    def read_byte(self) -> int:
        """Read a raw byte (alias for read_raw_byte)"""
        return self.read_raw_byte()
    
    def read_gchar(self) -> int:
        """Read a GCHAR (byte - 32)"""
        value = self.read_raw_byte()
        return max(0, value - 32)
    
    def read_gshort(self) -> int:
        """Read a protocol-encoded short (2 bytes)"""
        if self.pos + 1 >= len(self.data):
            return 0
        b1 = self.data[self.pos] - 32
        b2 = self.data[self.pos + 1] - 32
        self.pos += 2
        
        # Reconstruct the value
        value = (b1 << 7) + b2
        
        # Handle signed values
        if value > 16383:
            value = value - 32768
            
        return value
    
    def read_gint(self, num_bytes: int) -> int:
        """Read a protocol-encoded integer of specified bytes"""
        if self.pos + num_bytes - 1 >= len(self.data):
            return 0
        
        value = 0
        for i in range(num_bytes):
            byte_val = self.data[self.pos + i] - 32
            value = (value << 7) | byte_val
        
        self.pos += num_bytes
        return value
    
    def read_gint3(self) -> int:
        """Read a 3-byte protocol integer"""
        return self.read_gint(3)
    
    def read_gint4(self) -> int:
        """Read a 4-byte protocol integer"""
        return self.read_gint(4)
    
    def read_gint5(self) -> int:
        """Read a 5-byte protocol integer"""
        return self.read_gint(5)
    
    def read_string(self) -> str:
        """Read a length-prefixed string (1 byte length)"""
        length = self.read_raw_byte()
        if self.pos + length > len(self.data):
            return ""
        string_data = self.data[self.pos:self.pos + length]
        self.pos += length
        return string_data.decode('utf-8', errors='replace')
    
    def read_gstring(self) -> str:
        """Read a GCHAR length-prefixed string"""
        length = self.read_gchar()
        if self.pos + length > len(self.data):
            return ""
        string_data = self.data[self.pos:self.pos + length]
        self.pos += length
        return string_data.decode('utf-8', errors='replace')
    
    def read_bytes(self, count: int) -> bytes:
        """Read a fixed number of bytes"""
        if self.pos + count > len(self.data):
            count = len(self.data) - self.pos
        data = self.data[self.pos:self.pos + count]
        self.pos += count
        return data
    
    def bytes_left(self) -> int:
        """Get number of bytes remaining"""
        return len(self.data) - self.pos
    
    def read_remaining(self) -> bytes:
        """Read all remaining bytes"""
        data = self.data[self.pos:]
        self.pos = len(self.data)
        return data
    
    def has_data(self) -> bool:
        """Check if there's more data to read"""
        return self.pos < len(self.data)


def parse_field(reader: PacketReader, field: PacketField, announced_size: int = 0) -> Any:
    """Parse a single field using the appropriate method"""
    if field.field_type == PacketFieldType.BYTE:
        return reader.read_raw_byte()
    elif field.field_type == PacketFieldType.GCHAR:
        return reader.read_gchar()
    elif field.field_type == PacketFieldType.GSHORT:
        return reader.read_gshort()
    elif field.field_type == PacketFieldType.GINT3:
        return reader.read_gint3()
    elif field.field_type == PacketFieldType.GINT4:
        return reader.read_gint4()
    elif field.field_type == PacketFieldType.GINT5:
        return reader.read_gint5()
    elif field.field_type == PacketFieldType.STRING_LEN:
        return reader.read_string()
    elif field.field_type == PacketFieldType.STRING_GCHAR_LEN:
        return reader.read_gstring()
    elif field.field_type == PacketFieldType.FIXED_DATA:
        return reader.read_bytes(field.size or 0)
    elif field.field_type == PacketFieldType.VARIABLE_DATA:
        return reader.read_remaining()
    elif field.field_type == PacketFieldType.ANNOUNCED_DATA:
        return reader.read_bytes(announced_size)
    elif field.field_type == PacketFieldType.COORDINATE:
        return reader.read_gchar() / 8.0
    else:
        raise ValueError(f"Unknown field type: {field.field_type}")