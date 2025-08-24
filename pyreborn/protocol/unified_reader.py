"""
Unified Protocol Reader for pyReborn

Consolidates all packet reading functionality into a single, comprehensive system
that handles all Reborn protocol formats with consistent error handling and validation.
"""

import logging
from typing import Optional, Dict, Any, List, Tuple, Union
from enum import Enum
from .packet_structures import PACKET_REGISTRY, PacketFieldType, PacketStructure

logger = logging.getLogger(__name__)


class ProtocolError(Exception):
    """Base exception for protocol-related errors"""
    pass


class PacketParsingError(ProtocolError):
    """Raised when packet parsing fails"""
    pass


class InsufficientDataError(ProtocolError):
    """Raised when not enough data is available for reading"""
    pass


class PacketFormat(Enum):
    """Supported packet formats"""
    NEWLINE_DELIMITED = "newline_delimited"  # Standard Reborn packets ending with \n
    LENGTH_PREFIXED = "length_prefixed"      # Packets with length prefix
    FIXED_WIDTH = "fixed_width"              # Fixed-size packets
    RAW_DATA = "raw_data"                    # Raw data blocks (PLO_RAWDATA)


class UnifiedProtocolReader:
    """Unified protocol reader with comprehensive error handling and validation
    
    This class consolidates all packet reading functionality from the various
    binary readers in the codebase into a single, consistent interface.
    """
    
    def __init__(self, data: bytes, pos: int = 0, validate: bool = True):
        """Initialize the protocol reader
        
        Args:
            data: Raw packet data to read from
            pos: Starting position in the data
            validate: Whether to perform validation during reads
        """
        self.data = data
        self.pos = pos
        self.validate = validate
        self.announced_size = None  # Set by PLO_RAWDATA
        self._packet_format = PacketFormat.NEWLINE_DELIMITED
        
    def remaining(self) -> int:
        """Get number of bytes remaining to read"""
        return len(self.data) - self.pos
    
    def has_data(self, num_bytes: int = 1) -> bool:
        """Check if specified number of bytes are available"""
        return self.remaining() >= num_bytes
    
    def peek_byte(self, offset: int = 0) -> Optional[int]:
        """Peek at a byte without advancing position"""
        peek_pos = self.pos + offset
        if peek_pos >= len(self.data):
            return None
        return self.data[peek_pos]
    
    def read_byte(self) -> int:
        """Read a single byte"""
        if not self.has_data(1):
            raise InsufficientDataError("Cannot read byte: end of data reached")
        
        value = self.data[self.pos]
        self.pos += 1
        
        if self.validate and value > 255:
            raise PacketParsingError(f"Invalid byte value: {value}")
        
        return value
    
    def read_raw_byte(self) -> int:
        """Read raw byte without any decoding"""
        return self.read_byte()
    
    def read_gchar(self) -> int:
        """Read GCHAR (byte with +32 offset removed)"""
        raw_value = self.read_byte()
        value = raw_value - 32
        
        if self.validate and (raw_value < 32 or raw_value > 255):
            logger.warning(f"Unusual GCHAR value: {raw_value} (decoded: {value})")
            
        return max(0, value)  # Ensure non-negative
    
    def read_coordinate(self) -> float:
        """Read coordinate GCHAR with /8 division for position precision"""
        gchar_value = self.read_gchar()
        return gchar_value / 8.0
    
    def read_gint2(self) -> int:
        """Read GINT2 (2-byte little-endian integer)"""
        if not self.has_data(2):
            raise InsufficientDataError("Cannot read GINT2: need 2 bytes")
        
        byte1 = self.read_byte()
        byte2 = self.read_byte()
        
        # Little-endian 2-byte integer
        return byte1 | (byte2 << 8)
    
    def read_gshort(self) -> int:
        """Read GShort using exact GServer algorithm"""
        if not self.has_data(2):
            raise InsufficientDataError("Cannot read GShort: need 2 bytes")
        
        val1 = self.read_byte()
        val2 = self.read_byte()
        
        # GServer algorithm: value = (val[0] - 32) << 7 | (val[1] - 32)
        result = ((val1 - 32) << 7) | (val2 - 32)
        
        if self.validate and (val1 < 32 or val2 < 32):
            logger.warning(f"Invalid GShort bytes: {val1}, {val2}")
        
        return result
    
    def read_gint3(self) -> int:
        """Read GINT3 using exact GServer algorithm"""
        if not self.has_data(3):
            raise InsufficientDataError("Cannot read GINT3: need 3 bytes")
        
        val1 = self.read_byte()
        val2 = self.read_byte()
        val3 = self.read_byte()
        
        # GServer algorithm: ((val[0] - 32) << 14) | ((val[1] - 32) << 7) | (val[2] - 32)
        result = ((val1 - 32) << 14) | ((val2 - 32) << 7) | (val3 - 32)
        
        if self.validate and any(v < 32 for v in [val1, val2, val3]):
            logger.warning(f"Invalid GINT3 bytes: {val1}, {val2}, {val3}")
        
        return result
    
    def read_gint4(self) -> int:
        """Read GINT4 using exact GServer algorithm"""
        if not self.has_data(4):
            raise InsufficientDataError("Cannot read GINT4: need 4 bytes")
        
        val1 = self.read_byte()
        val2 = self.read_byte()
        val3 = self.read_byte()
        val4 = self.read_byte()
        
        # GServer algorithm: 4-byte version with 7-bit chunks
        result = ((val1 - 32) << 21) | ((val2 - 32) << 14) | ((val3 - 32) << 7) | (val4 - 32)
        
        if self.validate and any(v < 32 for v in [val1, val2, val3, val4]):
            logger.warning(f"Invalid GINT4 bytes: {val1}, {val2}, {val3}, {val4}")
        
        return result
    
    def read_gint5(self) -> int:
        """Read GINT5 using exact GServer algorithm"""
        if not self.has_data(5):
            raise InsufficientDataError("Cannot read GINT5: need 5 bytes")
        
        val1 = self.read_byte()
        val2 = self.read_byte()
        val3 = self.read_byte()
        val4 = self.read_byte()
        val5 = self.read_byte()
        
        # GServer algorithm: 5-byte version with 7-bit chunks
        result = ((val1 - 32) << 28) | ((val2 - 32) << 21) | ((val3 - 32) << 14) | ((val4 - 32) << 7) | (val5 - 32)
        
        if self.validate and any(v < 32 for v in [val1, val2, val3, val4, val5]):
            logger.warning(f"Invalid GINT5 bytes: {val1}, {val2}, {val3}, {val4}, {val5}")
        
        return result
    
    def read_string_with_len(self, len_field_type: PacketFieldType) -> str:
        """Read length-prefixed string"""
        if len_field_type == PacketFieldType.BYTE:
            length = self.read_byte()
        elif len_field_type == PacketFieldType.GCHAR:
            length = self.read_gchar()
        else:
            raise PacketParsingError(f"Invalid length field type for string: {len_field_type}")
        
        if not self.has_data(length):
            raise InsufficientDataError(f"Cannot read string: need {length} bytes, have {self.remaining()}")
        
        string_bytes = self.data[self.pos:self.pos + length]
        self.pos += length
        
        try:
            return string_bytes.decode('latin-1')
        except UnicodeDecodeError as e:
            if self.validate:
                raise PacketParsingError(f"String decode error: {e}")
            return string_bytes.decode('latin-1', errors='replace')
    
    def read_fixed_string(self, length: int, encoding: str = 'ascii') -> str:
        """Read fixed-length string"""
        if not self.has_data(length):
            raise InsufficientDataError(f"Cannot read fixed string: need {length} bytes")
        
        text_bytes = self.data[self.pos:self.pos + length]
        self.pos += length
        
        try:
            return text_bytes.decode(encoding, errors='replace')
        except UnicodeDecodeError as e:
            if self.validate:
                raise PacketParsingError(f"Fixed string decode error: {e}")
            return text_bytes.decode(encoding, errors='replace')
    
    def read_gstring(self) -> str:
        """Read newline-terminated string (plain text, not encoded)"""
        text = ""
        while self.has_data():
            char = self.read_raw_byte()
            if char == ord('\n'):
                break
            text += chr(char)
        return text
    
    def read_string_with_length(self) -> str:
        """Read string with GCHAR length prefix (legacy format)"""
        length = self.read_gchar()
        
        if self.validate and (length < 0 or length > 223):
            logger.warning(f"Unusual string length: {length}")
            if length < 0:
                return ""
        
        return self.read_fixed_string(length)
    
    def read_fixed_data(self, size: int) -> bytes:
        """Read fixed number of bytes"""
        if not self.has_data(size):
            raise InsufficientDataError(f"Cannot read fixed data: need {size} bytes")
        
        data = self.data[self.pos:self.pos + size]
        self.pos += size
        return data
    
    def read_variable_data(self) -> bytes:
        """Read all remaining data"""
        data = self.data[self.pos:]
        self.pos = len(self.data)
        return data
    
    def skip_bytes(self, count: int) -> None:
        """Skip specified number of bytes"""
        if not self.has_data(count):
            raise InsufficientDataError(f"Cannot skip {count} bytes: only {self.remaining()} available")
        
        self.pos += count
    
    def seek(self, position: int) -> None:
        """Seek to absolute position"""
        if position < 0 or position > len(self.data):
            raise PacketParsingError(f"Invalid seek position: {position}")
        
        self.pos = position
    
    def reset(self) -> None:
        """Reset to beginning of data"""
        self.pos = 0


class StructureAwarePacketParser:
    """Parser that uses packet structures with the unified reader"""
    
    def __init__(self, enable_validation: bool = True):
        self.logger = logging.getLogger(__name__)
        self.enable_validation = enable_validation
        
        # Multi-packet PLO_RAWDATA state tracking
        self.rawdata_mode = False
        self.rawdata_bytes_remaining = 0
        self.rawdata_accumulated = bytearray()
    
    def parse_packets(self, decrypted_data: bytes) -> List[Tuple[int, bytes, Dict[str, Any]]]:
        """Parse decrypted data using unified protocol handling
        
        Returns:
            List of (packet_id, raw_data, parsed_fields) tuples
        """
        packets = []
        
        # Simple logging for debugging
        self.logger.debug(f"PARSE_PACKETS: Processing {len(decrypted_data)} bytes")
        if b'\x85' in decrypted_data:  # 101+32 = 133 = 0x85 (PLO_BOARDPACKET)
            self.logger.info(f"PARSE_PACKETS: Contains PLO_BOARDPACKET data")
        
        # Handle ongoing PLO_RAWDATA accumulation first
        if self.rawdata_mode and self.rawdata_bytes_remaining > 0:
            self.logger.info(f"RAWDATA_ACCUMULATION: About to consume up to {self.rawdata_bytes_remaining} bytes from {len(decrypted_data)} byte chunk")
            consumed, raw_packets = self._handle_rawdata_accumulation(decrypted_data)
            self.logger.info(f"RAWDATA_ACCUMULATION: Consumed {consumed} bytes, {len(decrypted_data)-consumed} bytes remaining")
            packets.extend(raw_packets)
            decrypted_data = decrypted_data[consumed:]
            
            # If still in rawdata mode and no remaining data, return early
            if self.rawdata_mode and len(decrypted_data) == 0:
                self.logger.info(f"RAWDATA_ACCUMULATION: Still in rawdata mode ({self.rawdata_bytes_remaining} bytes remaining), no remaining data to process")
                return packets
        
        # Priority-based parsing: structured packets take precedence over rawdata accumulation
        pos = 0
        packet_count = 0
        while pos < len(decrypted_data):
            try:
                # First priority: Check for structured packets (like PLO_BOARDPACKET)
                packet_id, packet_data, parsed_fields, bytes_consumed = self._parse_structured_packet_at_position(decrypted_data, pos)
                
                if packet_id is not None:
                    # Successfully parsed a structured packet
                    pos += bytes_consumed
                    packets.append((packet_id, packet_data, parsed_fields))
                    
                    # If in rawdata mode, adjust the remaining count since we consumed structured packet bytes
                    if self.rawdata_mode and self.rawdata_bytes_remaining > 0:
                        consumed_from_rawdata = min(bytes_consumed, self.rawdata_bytes_remaining)
                        self.rawdata_bytes_remaining -= consumed_from_rawdata
                        self.logger.info(f"PRIORITY PARSING: Extracted structured packet {packet_id} ({bytes_consumed} bytes) during rawdata mode, {self.rawdata_bytes_remaining} bytes remaining")
                        
                        # Check if rawdata accumulation is now complete
                        if self.rawdata_bytes_remaining <= 0:
                            self.logger.info(f"PRIORITY PARSING: Rawdata accumulation completed via structured packet extraction")
                            self.rawdata_mode = False
                            self.rawdata_bytes_remaining = 0
                            self.rawdata_accumulated.clear()
                    
                    # Debug logging for PLO_BOARDPACKET
                    if packet_id == 101:
                        packet_count += 1
                        self.logger.debug(f"PARSING PLO_BOARDPACKET #{packet_count}: {len(packet_data)} bytes (structured)")
                    
                    # Handle PLO_RAWDATA announcements (for file transfers, etc.)
                    if packet_id == 100:  # PLO_RAWDATA
                        self._handle_rawdata_announcement(parsed_fields)
                        
                    continue
                
                # Second priority: If in rawdata mode, try accumulation
                if self.rawdata_mode and self.rawdata_bytes_remaining > 0:
                    # Consume remaining data for rawdata accumulation
                    remaining_data = decrypted_data[pos:]
                    consumed, raw_packets = self._handle_rawdata_accumulation(remaining_data)
                    packets.extend(raw_packets)
                    pos += consumed
                    
                    # If still in rawdata mode, we've consumed all available data
                    if self.rawdata_mode:
                        break
                    
                    continue
                
                # Third priority: Fall back to newline-delimited parsing
                next_newline = decrypted_data.find(b'\n', pos)
                
                if next_newline == -1:
                    break
                
                packet_bytes = decrypted_data[pos:next_newline]
                pos = next_newline + 1
                
                if packet_bytes and len(packet_bytes) >= 1:
                    packet_id = packet_bytes[0] - 32
                    packet_data = packet_bytes[1:]
                    
                    # Debug: Log packet parsing progress  
                    if pos % 10 == 0 or packet_id in [100, 101]:
                        self.logger.debug(f"PACKET_PARSING: pos={pos}, packet_id={packet_id}, size={len(packet_data)} bytes")
                    
                    parsed_fields = self._parse_packet_with_structure(packet_id, packet_data)
                    packets.append((packet_id, packet_data, parsed_fields))
                    
                    # Handle PLO_RAWDATA announcements
                    if packet_id == 100:  # PLO_RAWDATA
                        self._handle_rawdata_announcement(parsed_fields)
                        
            except Exception as e:
                self.logger.error(f"Error parsing packet at position {pos}: {e}")
                if self.enable_validation:
                    raise PacketParsingError(f"Packet parsing failed: {e}")
                break
        
        return packets
    
    def _parse_structured_packet_at_position(self, data: bytes, pos: int) -> Tuple[Optional[int], Optional[bytes], Optional[Dict[str, Any]], int]:
        """Try to parse a structured packet at the given position
        
        Returns:
            (packet_id, packet_data, parsed_fields, bytes_consumed) or (None, None, None, 0) if not a structured packet
        """
        if pos >= len(data):
            return None, None, None, 0
            
        try:
            # Get packet ID
            packet_id = data[pos] - 32
            
            # Check if this packet has a structured definition
            structure = PACKET_REGISTRY.get_structure(packet_id)
            if not structure:
                return None, None, None, 0
            
            # Check if this packet has FIXED_DATA fields (like PLO_BOARDPACKET)
            has_fixed_data = any(field.field_type == PacketFieldType.FIXED_DATA for field in structure.fields)
            
            if has_fixed_data:
                # Calculate total size needed for this structured packet
                total_size = 1  # packet ID byte
                for field in structure.fields:
                    if field.field_type == PacketFieldType.FIXED_DATA:
                        total_size += field.size or 0
                total_size += 1  # newline byte
                
                # Check if we have enough data
                if pos + total_size <= len(data):
                    # Extract packet data (excluding packet ID and newline)
                    packet_data = data[pos + 1:pos + total_size - 1]
                    
                    # Parse using structured reader
                    reader = UnifiedProtocolReader(packet_data, validate=self.enable_validation)
                    parsed_fields = self._parse_packet_fields(reader, structure, packet_id)
                    
                    self.logger.debug(f"Parsed structured packet {packet_id} with {len(packet_data)} bytes")
                    return packet_id, packet_data, parsed_fields, total_size
                else:
                    # Not enough data for complete structured packet
                    return None, None, None, 0
            
            # Not a fixed-data packet, use normal parsing
            return None, None, None, 0
            
        except Exception as e:
            self.logger.debug(f"Error parsing structured packet at pos {pos}: {e}")
            return None, None, None, 0

    def _parse_packet_with_structure(self, packet_id: int, packet_data: bytes) -> Dict[str, Any]:
        """Parse packet using structure definition"""
        try:
            structure = PACKET_REGISTRY.get_structure(packet_id)
            if structure:
                reader = UnifiedProtocolReader(packet_data, validate=self.enable_validation)
                return self._parse_packet_fields(reader, structure, packet_id)
            else:
                return {'type': 'unknown', 'packet_id': packet_id}
        except Exception as e:
            self.logger.debug(f"Error parsing packet ID {packet_id}: {e}")
            return {'type': 'parse_error', 'error': str(e), 'packet_id': packet_id}
    
    def _parse_packet_fields(self, reader: UnifiedProtocolReader, structure: PacketStructure, packet_id: int = None) -> Dict[str, Any]:
        """Parse packet fields according to structure"""
        fields = {'packet_type': structure.name}
        
        for field in structure.fields:
            try:
                if not reader.has_data() and field.field_type != PacketFieldType.VARIABLE_DATA:
                    break
                
                if field.field_type == PacketFieldType.BYTE:
                    fields[field.name] = reader.read_byte()
                elif field.field_type == PacketFieldType.GCHAR:
                    fields[field.name] = reader.read_gchar()
                elif field.field_type == PacketFieldType.GSHORT:
                    fields[field.name] = reader.read_gshort()
                elif field.field_type == PacketFieldType.GINT3:
                    fields[field.name] = reader.read_gint3()
                elif field.field_type == PacketFieldType.GINT4:
                    fields[field.name] = reader.read_gint4()
                elif field.field_type == PacketFieldType.GINT5:
                    fields[field.name] = reader.read_gint5()
                elif field.field_type == PacketFieldType.COORDINATE:
                    fields[field.name] = reader.read_coordinate()
                elif field.field_type == PacketFieldType.STRING_LEN:
                    fields[field.name] = reader.read_string_with_len(PacketFieldType.BYTE)
                elif field.field_type == PacketFieldType.STRING_GCHAR_LEN:
                    fields[field.name] = reader.read_string_with_len(PacketFieldType.GCHAR)
                elif field.field_type == PacketFieldType.FIXED_DATA:
                    fields[field.name] = reader.read_fixed_data(field.size or 0)
                elif field.field_type == PacketFieldType.VARIABLE_DATA:
                    fields[field.name] = reader.read_variable_data()
                elif field.field_type == PacketFieldType.ANNOUNCED_DATA:
                    # For ANNOUNCED_DATA, read all remaining data
                    # The size was announced by a previous PLO_RAWDATA packet
                    if packet_id == 101:  # PLO_BOARDPACKET
                        # PLO_BOARDPACKET now gets full 8192 bytes via special parsing
                        # Just read all the remaining data from the packet
                        remaining_data = reader.read_variable_data()
                        fields[field.name] = remaining_data
                        self.logger.debug(f"PLO_BOARDPACKET: Got {len(remaining_data)} bytes of board data")
                    else:
                        # Other ANNOUNCED_DATA types (files, etc.)
                        if self.rawdata_mode and len(self.rawdata_accumulated) > 1:
                            # Use the accumulated raw data minus the packet ID byte and newline
                            # The announced size includes: packet_id(1) + data + newline(1)
                            data_size = len(self.rawdata_accumulated) - 2  # Remove packet ID and newline
                            if data_size > 0:
                                fields[field.name] = bytes(self.rawdata_accumulated[1:1+data_size])
                            else:
                                fields[field.name] = b''
                        else:
                            # Fallback to reading remaining packet data
                            fields[field.name] = reader.read_variable_data()
                
            except Exception as e:
                self.logger.debug(f"Error parsing field {field.name}: {e}")
                if self.enable_validation:
                    raise
                break
        
        return fields
    
    def _handle_rawdata_accumulation(self, data: bytes) -> Tuple[int, List[Tuple[int, bytes, Dict[str, Any]]]]:
        """Handle ongoing PLO_RAWDATA accumulation"""
        packets = []
        consume_bytes = min(len(data), self.rawdata_bytes_remaining)
        
        if consume_bytes > 0:
            raw_chunk = data[:consume_bytes]
            self.rawdata_accumulated.extend(raw_chunk)
            self.rawdata_bytes_remaining -= consume_bytes
            
            # Create chunk packet
            packets.append((-1, raw_chunk, {
                'type': 'raw_data_chunk',
                'chunk_size': consume_bytes,
                'total_accumulated': len(self.rawdata_accumulated),
                'bytes_remaining': self.rawdata_bytes_remaining
            }))
            
            # Check if complete
            if self.rawdata_bytes_remaining <= 0:
                # Parse accumulated bytes as a regular packet
                accumulated_bytes = bytes(self.rawdata_accumulated)
                self.logger.info(f"PLO_RAWDATA accumulation complete: {len(accumulated_bytes)} bytes")
                
                if len(accumulated_bytes) >= 2:
                    # Extract packet ID and data from accumulated bytes
                    # Format: PACKET_ID(1) + DATA + NEWLINE(1)
                    packet_id = accumulated_bytes[0] - 32
                    packet_data = accumulated_bytes[1:-1] if accumulated_bytes[-1] == ord('\n') else accumulated_bytes[1:]
                    
                    self.logger.info(f"PLO_RAWDATA parsed as packet ID {packet_id} with {len(packet_data)} bytes of data")
                    
                    # Add as regular packet for normal processing
                    packets.append((packet_id, packet_data, {
                        'type': 'rawdata_completed',
                        'total_size': len(accumulated_bytes),
                        'packet_id': packet_id
                    }))
                else:
                    self.logger.warning(f"PLO_RAWDATA accumulation too small: {len(accumulated_bytes)} bytes")
                
                # Reset state
                self.rawdata_mode = False
                self.rawdata_bytes_remaining = 0
                self.rawdata_accumulated.clear()
        
        return consume_bytes, packets
    
    def _handle_rawdata_announcement(self, parsed_fields: Dict[str, Any]) -> None:
        """Handle PLO_RAWDATA size announcement"""
        announced_size = parsed_fields.get('size')
        if announced_size and announced_size > 0:
            self.logger.info(f"PLO_RAWDATA announced {announced_size:,} bytes - starting accumulation")
            self.rawdata_mode = True
            self.rawdata_bytes_remaining = announced_size
            self.rawdata_accumulated.clear()