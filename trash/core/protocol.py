"""
Protocol framing and packet handling for PyReborn.
Handles packet framing, compression, and buffering.
"""

import struct
import zlib
import bz2
from typing import List, Tuple, Optional, Callable
from enum import IntEnum

class CompressionType(IntEnum):
    """Compression types for packets"""
    UNCOMPRESSED = 0x02
    ZLIB = 0x04
    BZ2 = 0x06

class ProtocolCodec:
    """Handles protocol-level encoding/decoding"""
    
    def __init__(self):
        self._recv_buffer = bytearray()
        self.on_packet_received: Optional[Callable[[int, bytes], None]] = None
        
    def feed_data(self, data: bytes):
        """Feed received data into the codec"""
        self._recv_buffer.extend(data)
        self._process_buffer()
        
    def _process_buffer(self):
        """Process buffered data for complete packets"""
        while len(self._recv_buffer) >= 3:
            # Read packet header (2 bytes length + 1 byte compression)
            packet_len = struct.unpack('>H', self._recv_buffer[:2])[0]
            
            # Check if we have the full packet
            if len(self._recv_buffer) < packet_len + 2:
                break
                
            # Extract packet
            compression_type = self._recv_buffer[2]
            packet_data = bytes(self._recv_buffer[3:packet_len + 2])
            
            # Remove packet from buffer
            self._recv_buffer = self._recv_buffer[packet_len + 2:]
            
            # Notify handler
            if self.on_packet_received:
                self.on_packet_received(compression_type, packet_data)
                
    def encode_packet(self, data: bytes) -> bytes:
        """Encode a packet with compression"""
        # Determine compression
        if len(data) <= 55:
            compression_type = CompressionType.UNCOMPRESSED
            compressed_data = data
        else:
            compression_type = CompressionType.ZLIB
            compressed_data = zlib.compress(data)
            
        # Build packet: [length][compression][data]
        packet = struct.pack('>H', len(compressed_data) + 1)
        packet += bytes([compression_type])
        packet += compressed_data
        
        return packet
        
    def decode_packet(self, compression_type: int, data: bytes) -> Optional[bytes]:
        """Decode a compressed packet"""
        try:
            if compression_type == CompressionType.ZLIB:
                return zlib.decompress(data)
            elif compression_type == CompressionType.BZ2:
                return bz2.decompress(data)
            elif compression_type == CompressionType.UNCOMPRESSED:
                return data
            else:
                print(f"Unknown compression type: {compression_type}")
                return None
        except Exception as e:
            print(f"Decompression error: {e}")
            return None
            
    def parse_graal_packets(self, data: bytes) -> List[Tuple[int, bytes]]:
        """Parse individual Graal packets from decompressed data"""
        packets = []
        pos = 0
        
        while pos < len(data):
            # Find packet boundary (newline)
            next_newline = data.find(b'\n', pos)
            if next_newline == -1:
                # No more complete packets
                break
                
            # Extract packet
            packet = data[pos:next_newline]
            pos = next_newline + 1
            
            if len(packet) >= 1:
                packet_id = packet[0] - 32  # Graal encoding
                packet_data = packet[1:]
                packets.append((packet_id, packet_data))
                
        return packets