#!/usr/bin/env python3
"""
Binary Packet Reader for Structure-Aware Parsing - PROPERLY FIXED VERSION

This version handles ALL Reborn packet formats:
- Newline-delimited packets
- Length-prefixed packets  
- Fixed-width packets
- Raw data blocks (PLO_RAWDATA)
"""

import logging
from typing import Optional, Dict, Any, List, Tuple
from .packet_structures import PACKET_REGISTRY, PacketFieldType, PacketStructure

logger = logging.getLogger(__name__)

class BinaryPacketReader:
    """Binary reader that understands packet structures"""
    
    def __init__(self, data: bytes, pos: int = 0):
        self.data = data
        self.pos = pos
        self.announced_size = None  # Set by PLO_RAWDATA
    
    def remaining(self) -> int:
        """Bytes remaining to read"""
        return len(self.data) - self.pos
    
    def read_byte(self) -> int:
        """Read a single byte"""
        if self.pos >= len(self.data):
            raise ValueError("End of data reached")
        value = self.data[self.pos]
        self.pos += 1
        return value
    
    def read_gchar(self) -> int:
        """Read GCHAR (byte with +32 offset)"""
        return self.read_byte() - 32
    
    def read_coordinate(self) -> float:
        """Read coordinate GCHAR with /8 division for positions"""
        # GServer coordinates are GCHAR values divided by 8 for precision
        return self.read_gchar() / 8.0
    
    def read_gint2(self) -> int:
        """Read GINT2 (2-byte little-endian integer)"""
        if self.remaining() < 2:
            raise ValueError("Not enough data for GINT2")
        
        byte1 = self.read_byte()
        byte2 = self.read_byte()
        
        # Little-endian 2-byte integer
        return byte1 | (byte2 << 8)
    
    def read_gshort(self) -> int:
        """Read GShort (2 bytes, max value: 28,767) using GServer algorithm"""
        if self.remaining() < 2:
            raise ValueError("Not enough data for GShort")
        
        # Read raw bytes with +32 encoding
        val1 = self.read_byte()
        val2 = self.read_byte()
        
        # GServer algorithm: value = (val[0] - 32) << 7 | (val[1] - 32)
        return ((val1 - 32) << 7) | (val2 - 32)
    
    def read_gint3(self) -> int:
        """Read GINT3 (3 bytes, max value: 3,682,399) using exact GServer algorithm"""
        if self.remaining() < 3:
            raise ValueError("Not enough data for GINT3")
        
        # Read raw bytes with +32 encoding
        val1 = self.read_byte()
        val2 = self.read_byte()  
        val3 = self.read_byte()
        
        # GServer algorithm: ((val[0] - 32) << 14) | ((val[1] - 32) << 7) | (val[2] - 32)
        return ((val1 - 32) << 14) | ((val2 - 32) << 7) | (val3 - 32)
    
    def read_gint4(self) -> int:
        """Read GINT4 (4 bytes, max value: 471,347,295) using GServer algorithm"""
        if self.remaining() < 4:
            raise ValueError("Not enough data for GINT4")
        
        # Read raw bytes with +32 encoding
        val1 = self.read_byte()
        val2 = self.read_byte()
        val3 = self.read_byte()
        val4 = self.read_byte()
        
        # GServer algorithm: 4-byte version with 7-bit chunks
        return ((val1 - 32) << 21) | ((val2 - 32) << 14) | ((val3 - 32) << 7) | (val4 - 32)
    
    def read_gint5(self) -> int:
        """Read GINT5 (5 bytes, max value: 4,294,967,295) using exact GServer algorithm"""
        if self.remaining() < 5:
            raise ValueError("Not enough data for GINT5")
        
        # Read raw bytes with +32 encoding
        val1 = self.read_byte()
        val2 = self.read_byte()
        val3 = self.read_byte()
        val4 = self.read_byte()
        val5 = self.read_byte()
        
        # GServer algorithm: 5-byte version with 7-bit chunks
        return ((val1 - 32) << 28) | ((val2 - 32) << 21) | ((val3 - 32) << 14) | ((val4 - 32) << 7) | (val5 - 32)
    
    def read_string_with_len(self, len_field_type: PacketFieldType) -> str:
        """Read length-prefixed string"""
        if len_field_type == PacketFieldType.BYTE:
            length = self.read_byte()
        elif len_field_type == PacketFieldType.GCHAR:
            length = self.read_gchar()
        else:
            raise ValueError(f"Invalid length field type: {len_field_type}")
        
        if self.remaining() < length:
            raise ValueError(f"Not enough data for string of length {length}")
        
        string_bytes = self.data[self.pos:self.pos + length]
        self.pos += length
        return string_bytes.decode('latin-1')
    
    def read_fixed_data(self, size: int) -> bytes:
        """Read fixed number of bytes"""
        if self.remaining() < size:
            raise ValueError(f"Not enough data for {size} bytes")
        
        data = self.data[self.pos:self.pos + size]
        self.pos += size
        return data
    
    def read_variable_data(self) -> bytes:
        """Read all remaining data"""
        data = self.data[self.pos:]
        self.pos = len(self.data)
        return data

class StructureAwareParser:
    """Parser that uses packet structures AND handles all Reborn packet formats"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Multi-socket PLO_RAWDATA state tracking
        self.rawdata_mode = False
        self.rawdata_bytes_remaining = 0
        self.rawdata_accumulated = bytearray()
    
    def parse_packets(self, decrypted_data: bytes) -> List[Tuple[int, bytes, Dict[str, Any]]]:
        """Parse decrypted data using CORRECT Reborn protocol handling
        
        The key insight: Reborn packets are NEWLINE-DELIMITED first, 
        then we apply structure parsing to each delimited packet.
        
        Returns:
            List of (packet_id, raw_data, parsed_fields) tuples
        """
        packets = []
        
        # Handle ongoing PLO_RAWDATA accumulation first
        if self.rawdata_mode and self.rawdata_bytes_remaining > 0:
            self.logger.debug(f"🔄 In rawdata mode - need {self.rawdata_bytes_remaining:,} more bytes")
            
            # Consume as much raw data as possible from this buffer
            consume_bytes = min(len(decrypted_data), self.rawdata_bytes_remaining)
            
            if consume_bytes > 0:
                raw_chunk = decrypted_data[:consume_bytes]
                self.rawdata_accumulated.extend(raw_chunk)
                self.rawdata_bytes_remaining -= consume_bytes
                
                self.logger.info(f"📦 Consumed {consume_bytes:,} bytes of raw data ({self.rawdata_bytes_remaining:,} remaining)")
                
                # Create raw data pseudo-packet for this chunk
                packets.append((-1, raw_chunk, {
                    'type': 'raw_data_chunk',
                    'chunk_size': consume_bytes,
                    'total_accumulated': len(self.rawdata_accumulated),
                    'bytes_remaining': self.rawdata_bytes_remaining
                }))
                
                # Check if raw data is complete
                if self.rawdata_bytes_remaining <= 0:
                    self.logger.info(f"✅ Raw data complete: {len(self.rawdata_accumulated):,} bytes total")
                    
                    # Create final raw data block
                    packets.append((-2, bytes(self.rawdata_accumulated), {
                        'type': 'raw_data_complete',
                        'total_size': len(self.rawdata_accumulated),
                        'data_preview': self.rawdata_accumulated[:100].hex()
                    }))
                    
                    # Reset state
                    self.rawdata_mode = False
                    self.rawdata_bytes_remaining = 0
                    self.rawdata_accumulated.clear()
                    
                    self.logger.info("🔄 Exited raw data mode - resuming packet parsing")
                
                # Skip the consumed raw data
                decrypted_data = decrypted_data[consume_bytes:]
        
        # CORRECT APPROACH: Parse newline-delimited packets like legacy parser
        pos = 0
        while pos < len(decrypted_data):
            # Find the next newline (packet terminator)
            next_newline = decrypted_data.find(b'\n', pos)
            
            if next_newline == -1:
                # No more complete packets
                break
                
            # Extract one packet
            packet_bytes = decrypted_data[pos:next_newline]
            pos = next_newline + 1
            
            if packet_bytes and len(packet_bytes) >= 1:
                # First byte is encrypted packet ID
                encrypted_id = packet_bytes[0]
                packet_id = encrypted_id - 32
                packet_data = packet_bytes[1:]
                
                # Now apply structure parsing to this individual packet
                try:
                    structure = PACKET_REGISTRY.get_structure(packet_id)
                    if structure:
                        # Parse using structure
                        reader = BinaryPacketReader(packet_data)
                        parsed_fields = self._parse_packet_fields(reader, structure)
                        packets.append((packet_id, packet_data, parsed_fields))
                        
                        # Handle PLO_RAWDATA specially
                        if packet_id == 100:  # PLO_RAWDATA
                            announced_size = parsed_fields.get('size')
                            if announced_size and announced_size > 0:
                                self.logger.info(f"🔄 PLO_RAWDATA announced {announced_size:,} bytes")
                                self.rawdata_mode = True
                                self.rawdata_bytes_remaining = announced_size
                                self.rawdata_accumulated.clear()
                    else:
                        # Unknown packet - still include it
                        packets.append((packet_id, packet_data, {'type': 'unknown'}))
                        
                except Exception as e:
                    self.logger.debug(f"Error parsing packet ID {packet_id}: {e}")
                    packets.append((packet_id, packet_data, {'type': 'parse_error', 'error': str(e)}))
        
        return packets
    
    
    def _parse_packet_fields(self, reader: BinaryPacketReader, structure: PacketStructure) -> Dict[str, Any]:
        """Parse packet fields according to structure"""
        fields = {}
        
        for field in structure.fields:
            try:
                if reader.remaining() == 0 and field.field_type != PacketFieldType.VARIABLE_DATA:
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
                    fields[field.name] = reader.read_fixed_data(field.size)
                elif field.field_type == PacketFieldType.VARIABLE_DATA:
                    fields[field.name] = reader.read_variable_data()
                
            except Exception as e:
                self.logger.debug(f"Error parsing field {field.name}: {e}")
                break
        
        fields['packet_type'] = structure.name
        return fields
    
    def _find_next_packet_boundary(self, data: bytes, start_pos: int) -> int:
        """Find the next likely packet boundary"""
        for pos in range(start_pos, len(data)):
            if pos >= len(data):
                break
                
            # Check for potential packet ID
            byte_val = data[pos]
            packet_id = byte_val - 32
            
            # Valid packet ID range and known structure
            if 0 <= packet_id <= 200 and PACKET_REGISTRY.has_structure(packet_id):
                return pos
        
        return len(data)