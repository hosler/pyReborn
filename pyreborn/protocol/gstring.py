"""
Python implementation of GServer's CString class for Graal packet handling.

This provides similar functionality to CString with Graal-specific encoding methods.
"""

import struct
from typing import Union, Optional


class GString:
    """Graal-compatible string buffer with packet encoding/decoding methods"""
    
    def __init__(self, data: Union[bytes, str, 'GString'] = b''):
        """Initialize with optional data"""
        if isinstance(data, str):
            self._buffer = bytearray(data.encode('latin-1'))
        elif isinstance(data, GString):
            self._buffer = bytearray(data._buffer)
        elif isinstance(data, (bytes, bytearray)):
            self._buffer = bytearray(data)
        else:
            self._buffer = bytearray()
            
        self._read_pos = 0
        
    def __len__(self) -> int:
        """Get buffer length"""
        return len(self._buffer)
        
    def __bytes__(self) -> bytes:
        """Convert to bytes"""
        return bytes(self._buffer)
        
    def __str__(self) -> str:
        """Convert to string"""
        return self._buffer.decode('latin-1', errors='replace')
        
    def clear(self):
        """Clear the buffer"""
        self._buffer.clear()
        self._read_pos = 0
        
    def text(self) -> bytes:
        """Get buffer as bytes (like CString::text())"""
        return bytes(self._buffer)
        
    def length(self) -> int:
        """Get buffer length"""
        return len(self._buffer)
        
    def read_pos(self) -> int:
        """Get current read position"""
        return self._read_pos
        
    def set_read(self, pos: int):
        """Set read position"""
        self._read_pos = max(0, min(pos, len(self._buffer)))
        
    def bytes_left(self) -> int:
        """Get number of bytes left to read"""
        return max(0, len(self._buffer) - self._read_pos)
        
    # Write methods
    def write(self, data: Union[bytes, str]) -> 'GString':
        """Write data to buffer"""
        if isinstance(data, str):
            self._buffer.extend(data.encode('latin-1'))
        else:
            self._buffer.extend(data)
        return self
        
    def write_char(self, value: int) -> 'GString':
        """Write single byte"""
        self._buffer.append(value & 0xFF)
        return self
        
    def write_short(self, value: int) -> 'GString':
        """Write 16-bit value (big-endian)"""
        self._buffer.extend(struct.pack('>H', value & 0xFFFF))
        return self
        
    def write_int(self, value: int) -> 'GString':
        """Write 32-bit value (big-endian)"""
        self._buffer.extend(struct.pack('>I', value & 0xFFFFFFFF))
        return self
        
    # Graal-specific write methods
    def write_gchar(self, value: int) -> 'GString':
        """Write Graal-encoded char (value + 32)"""
        self._buffer.append((value + 32) & 0xFF)
        return self
        
    def write_gshort(self, value: int) -> 'GString':
        """Write Graal-encoded short"""
        if value < 223:
            self.write_gchar(value)
        else:
            self.write_gchar(223 + (value >> 8))
            self.write_char(value & 0xFF)
        return self
        
    def write_gint(self, value: int) -> 'GString':
        """Write Graal-encoded int (variable length)"""
        if value < 223:
            self.write_gchar(value)
        elif value < 0x1FDF:  # 8159
            self.write_gchar(223 + (value >> 8))
            self.write_char(value & 0xFF)
        elif value < 0x3FBFDF:  # 4177887
            self.write_gchar(247 + (value >> 16))
            self.write_short(value & 0xFFFF)
        else:
            self.write_gchar(255)
            self.write_int(value)
        return self
        
    def write_gint4(self, value: int) -> 'GString':
        """Write Graal 4-byte int"""
        self.write_gchar(255)
        self.write_int(value)
        return self
        
    def write_gint5(self, value: int) -> 'GString':
        """Write Graal 5-byte int"""
        self.write_gchar((value >> 32) & 0xFF)
        self.write_int(value & 0xFFFFFFFF)
        return self
        
    def write_gstring(self, text: str) -> 'GString':
        """Write Graal string (length-prefixed)"""
        data = text.encode('latin-1')
        self.write_gchar(len(data))
        self.write(data)
        return self
        
    # Read methods
    def read_char(self) -> int:
        """Read single byte"""
        if self._read_pos >= len(self._buffer):
            return 0
        value = self._buffer[self._read_pos]
        self._read_pos += 1
        return value
        
    def read_short(self) -> int:
        """Read 16-bit value (big-endian)"""
        if self._read_pos + 2 > len(self._buffer):
            return 0
        value = struct.unpack('>H', self._buffer[self._read_pos:self._read_pos+2])[0]
        self._read_pos += 2
        return value
        
    def read_int(self) -> int:
        """Read 32-bit value (big-endian)"""
        if self._read_pos + 4 > len(self._buffer):
            return 0
        value = struct.unpack('>I', self._buffer[self._read_pos:self._read_pos+4])[0]
        self._read_pos += 4
        return value
        
    # Graal-specific read methods
    def read_gchar(self) -> int:
        """Read Graal-encoded char"""
        return max(0, self.read_char() - 32)
        
    def read_gshort(self) -> int:
        """Read Graal-encoded short"""
        value = self.read_gchar()
        if value < 223:
            return value
        return ((value - 223) << 8) + self.read_char()
        
    def read_gint(self) -> int:
        """Read Graal-encoded int"""
        value = self.read_gchar()
        if value < 223:
            return value
        elif value < 247:
            return ((value - 223) << 8) + self.read_char()
        elif value < 255:
            return ((value - 247) << 16) + self.read_short()
        else:
            return self.read_int()
            
    def read_gint5(self) -> int:
        """Read Graal 5-byte int"""
        high = self.read_gchar()
        low = self.read_int()
        return (high << 32) | low
        
    def read_gstring(self) -> str:
        """Read Graal string"""
        length = self.read_gchar()
        if self._read_pos + length > len(self._buffer):
            return ""
        data = self._buffer[self._read_pos:self._read_pos+length]
        self._read_pos += length
        return data.decode('latin-1', errors='replace')
        
    def read_chars(self, length: int) -> bytes:
        """Read specified number of bytes"""
        if self._read_pos + length > len(self._buffer):
            length = len(self._buffer) - self._read_pos
        data = bytes(self._buffer[self._read_pos:self._read_pos+length])
        self._read_pos += length
        return data
        
    def read_string(self, delimiter: bytes = b'\n') -> str:
        """Read until delimiter or end"""
        start = self._read_pos
        try:
            end = self._buffer.index(delimiter[0], start)
            data = self._buffer[start:end]
            self._read_pos = end + 1  # Skip delimiter
        except ValueError:
            data = self._buffer[start:]
            self._read_pos = len(self._buffer)
        return data.decode('latin-1', errors='replace')
        
    # Operators
    def __lshift__(self, other) -> 'GString':
        """Append data using << operator"""
        if isinstance(other, (int, bool)):
            self.write_char(int(other))
        elif isinstance(other, (bytes, bytearray, str, GString)):
            self.write(other)
        return self
        
    def __rshift__(self, other) -> 'GString':
        """Prepend data using >> operator"""
        if isinstance(other, (int, bool)):
            self._buffer.insert(0, int(other) & 0xFF)
        elif isinstance(other, str):
            self._buffer[0:0] = other.encode('latin-1')
        elif isinstance(other, (bytes, bytearray)):
            self._buffer[0:0] = other
        elif isinstance(other, GString):
            self._buffer[0:0] = other._buffer
        return self
        
    def __add__(self, other) -> 'GString':
        """Concatenate GStrings"""
        result = GString(self)
        result.write(other)
        return result
        
    def __iadd__(self, other) -> 'GString':
        """Append to this GString"""
        self.write(other)
        return self


# Convenience functions
def gstring(*args) -> GString:
    """Create a GString from multiple arguments"""
    gs = GString()
    for arg in args:
        gs.write(arg)
    return gs