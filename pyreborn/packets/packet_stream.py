"""
Packet stream handler - converts byte stream to packet objects
Handles encryption, framing, and PLO_RAWDATA sequences
"""

import logging
import zlib
import bz2
import time
from typing import List, Optional, Tuple
from dataclasses import dataclass
from collections import deque

from .packet_types import Packet, RawDataPacket, PacketID
from ..core.encryption import RebornEncryption


logger = logging.getLogger(__name__)


@dataclass
class StreamState:
    """Tracks the current state of packet stream processing"""
    # Buffer for incomplete packets
    buffer: bytes = b""
    
    # Raw data mode (after PLO_RAWDATA)
    in_raw_mode: bool = False
    expected_raw_size: int = 0
    raw_buffer: bytes = b""
    raw_context: dict = None
    raw_mode_start_time: float = 0
    raw_last_data_time: float = 0
    
    # Statistics
    packets_processed: int = 0
    bytes_processed: int = 0


class PacketDecoder:
    """Handles ENCRYPT_GEN_5 decryption"""
    
    def __init__(self, key: int):
        self.key = key
        self.iterator = 0x4A80B38  # Initial iterator value
        
    def decrypt(self, data: bytes, limit: int = -1) -> bytes:
        """Decrypt incoming data with optional limit (matches v1 RebornEncryption)"""
        result = bytearray(data)
        
        # Determine how many bytes to decrypt
        if limit < 0:
            bytes_to_decrypt = len(data)
        elif limit == 0:
            return bytes(result)  # No decryption
        else:
            # Decrypt up to limit * 4 bytes (v1 behavior)
            bytes_to_decrypt = min(len(data), limit * 4)
            
        for i in range(bytes_to_decrypt):
            if i % 4 == 0:
                # Update iterator every 4 bytes
                self.iterator = (self.iterator * 0x8088405 + self.key) & 0xFFFFFFFF
                
            # Apply XOR with iterator bytes (little-endian)
            iterator_bytes = self.iterator.to_bytes(4, 'little')
            result[i] ^= iterator_bytes[i % 4]
            
        return bytes(result)
        
    def encrypt(self, data: bytes, limit: int = -1) -> bytes:
        """Encrypt outgoing data"""
        # Same as decrypt for XOR cipher
        return self.decrypt(data, limit)


class PacketFramer:
    """Extracts packets from decrypted byte stream"""
    
    def __init__(self, version: str):
        self.version = version
        self.state = StreamState()
        self.pending_packets = deque()
        
    def process_bytes(self, data: bytes) -> List[Packet]:
        """Process decrypted bytes and extract packets"""
        self.state.buffer += data
        self.state.bytes_processed += len(data)
        
        packets = []
        
        # Check for raw mode timeout even if no new data
        if self.state.in_raw_mode and len(data) == 0:
            current_time = time.time()
            time_since_data = current_time - self.state.raw_last_data_time
            if time_since_data > 0.2 and len(self.state.raw_buffer) > 1000:
                logger.debug(f"Raw mode timeout triggered: {time_since_data:.1f}s since last data, processing {len(self.state.raw_buffer)} bytes")
                # Force exit raw mode and process what we have
                raw_data = self.state.raw_buffer
                self._exit_raw_mode()
                
                # Check if this raw data contains PLO_BOARDPACKET (like v1 does)
                logger.debug(f"Timeout handler - Checking for PLO_BOARDPACKET: len={len(raw_data)}, first_byte={raw_data[0] if len(raw_data) > 0 else 'NONE'}, first_byte-32={raw_data[0]-32 if len(raw_data) > 0 else 'NONE'}")
                if len(raw_data) >= 8193 and (raw_data[0] - 32) == 101:  # PLO_BOARDPACKET = 101
                    logger.debug("Timeout handler - Found PLO_BOARDPACKET in raw data - extracting 8192 bytes of board data")
                    
                    # Extract board data (8192 bytes after PLO_BOARDPACKET marker)
                    board_data = raw_data[1:8193]  # Skip packet ID, take 8192 bytes
                    
                    # Create a BoardPacket with the full board data
                    packet = Packet(
                        packet_id=101,  # PLO_BOARDPACKET
                        raw_data=board_data
                    )
                    packets.append(packet)
                    self.state.packets_processed += 1
                    
                    # Handle any remaining data after board packet
                    remaining_data = raw_data[8193:]
                    if len(remaining_data) > 0:
                        logger.debug(f"Timeout handler - Remaining data after board packet: {len(remaining_data)} bytes")
                        self.state.buffer = remaining_data + self.state.buffer
                else:
                    # Check what we have in raw data
                    logger.debug(f"Timeout handler - Raw data doesn't match board packet")
                    logger.debug(f"  First 100 bytes: {raw_data[:100].hex()}")
                    
                    # Check if it starts with a file packet
                    if len(raw_data) > 0 and (raw_data[0] - 32) == 102:  # PLO_FILE
                        logger.debug("Timeout handler - Found PLO_FILE at start of raw data")
                        logger.debug(f"Timeout handler - Processing entire buffer ({len(raw_data)} bytes) as file packet")
                        
                        # Create a file packet with all the raw data
                        packet = Packet(
                            packet_id=102,  # PLO_FILE
                            raw_data=raw_data[1:]  # Skip the packet ID byte
                        )
                        packets.append(packet)
                        self.state.packets_processed += 1
                        return packets  # Don't put data back in buffer
                    
                    # Normal case - treat as newline-delimited packets
                    self.state.buffer = raw_data + self.state.buffer
        
        # Process buffer until we can't extract more packets
        while True:
            if self.state.in_raw_mode:
                packet = self._process_raw_mode()
                if packet:
                    packets.append(packet)
                    self.state.packets_processed += 1
                else:
                    break
            else:
                packet = self._process_normal_mode()
                if packet:
                    packets.append(packet)
                    self.state.packets_processed += 1
                    
                    # Check if this packet triggers raw mode
                    if isinstance(packet, RawDataPacket):
                        self._enter_raw_mode(packet)
                else:
                    break
                    
        return packets
        
    def _process_normal_mode(self) -> Optional[Packet]:
        """Extract a packet in normal mode (newline delimited)"""
        newline_pos = self.state.buffer.find(b'\n')
        
        if newline_pos == -1:
            # No complete packet yet
            return None
            
        # Extract packet data (not including newline)
        packet_data = self.state.buffer[:newline_pos]
        self.state.buffer = self.state.buffer[newline_pos + 1:]
        
        if len(packet_data) == 0:
            # Empty packet, skip
            return None
            
        # Parse packet ID (first byte - 32)
        packet_id = packet_data[0] - 32
        
        # Create raw packet object
        packet = Packet(
            packet_id=packet_id,
            raw_data=packet_data[1:] if len(packet_data) > 1 else b""
        )
        
        # Special handling for PLO_RAWDATA
        if packet_id == PacketID.PLO_RAWDATA:
            if len(packet_data) >= 4:
                size_bytes = packet_data[1:4]
                size = self._decode_gint3(size_bytes)
                logger.debug(f"PLO_RAWDATA: packet_data length={len(packet_data)}")
                logger.debug(f"  Size bytes: {size_bytes.hex()} -> {[b for b in size_bytes]} -> {[b-32 for b in size_bytes]}")
                logger.debug(f"  Decoded size: {size}")
                logger.debug(f"  Full packet_data: {packet_data.hex()}")
            else:
                size = 0
                logger.warning(f"PLO_RAWDATA packet too short: {len(packet_data)} bytes")
            return RawDataPacket(
                packet_id=packet_id,
                raw_data=packet_data[1:],
                expected_size=size
            )
            
        return packet
        
    def _process_raw_mode(self) -> Optional[Packet]:
        """Process data in raw mode (after PLO_RAWDATA)"""
        # Collect raw data up to expected size
        remaining = self.state.expected_raw_size - len(self.state.raw_buffer)
        
        if remaining <= 0:
            # Shouldn't happen, exit raw mode
            logger.warning("Raw mode with no remaining data expected")
            self._exit_raw_mode()
            return None
            
        # Take what we need from buffer
        chunk = self.state.buffer[:remaining]
        self.state.raw_buffer += chunk
        self.state.buffer = self.state.buffer[len(chunk):]
        
        if len(chunk) > 0:
            self.state.raw_last_data_time = time.time()
            logger.debug(f"Raw mode: collected {len(chunk)} bytes, total {len(self.state.raw_buffer)}/{self.state.expected_raw_size}")
            logger.debug(f"  Raw chunk: {chunk.hex()}")
        
        # Log progress for debugging large transfers
        if len(self.state.raw_buffer) > 0 and len(self.state.raw_buffer) % 1000 == 0:
            logger.debug(f"Raw data progress: {len(self.state.raw_buffer)}/{self.state.expected_raw_size} bytes")
        
        # Check if we have all the raw data OR if we've been stuck for too long
        current_time = time.time()
        time_since_start = current_time - self.state.raw_mode_start_time
        time_since_data = current_time - self.state.raw_last_data_time
        
        should_exit = (len(self.state.raw_buffer) >= self.state.expected_raw_size or
                      (time_since_data > 0.2 and len(self.state.raw_buffer) > 1000))  # Timeout after 0.2s of no data and we have some data
        
        if time_since_data > 0.3:  # Debug logging after 0.3s
            logger.debug(f"Raw mode timeout check: time_since_data={time_since_data:.1f}s, buffer_size={len(self.state.raw_buffer)}, should_exit={should_exit}")
        
        if should_exit:
            # Process the raw data as multiple packets
            logger.debug(f"Processing raw data: {len(self.state.raw_buffer)} bytes (expected {self.state.expected_raw_size})")
            logger.debug(f"  Full raw data: {self.state.raw_buffer.hex()}")
            
            # Exit raw mode
            raw_data = self.state.raw_buffer
            self._exit_raw_mode()
            
            # Check what type of data this is
            logger.debug(f"Processing raw data: len={len(raw_data)}, first_byte={raw_data[0] if len(raw_data) > 0 else 'NONE'}, first_byte-32={raw_data[0]-32 if len(raw_data) > 0 else 'NONE'}")
            
            # Check if this raw data contains PLO_BOARDPACKET
            if len(raw_data) >= 8193 and (raw_data[0] - 32) == 101:  # PLO_BOARDPACKET = 101
                logger.debug("Found PLO_BOARDPACKET in raw data - extracting 8192 bytes of board data")
                
                # Extract board data (8192 bytes after PLO_BOARDPACKET marker)
                board_data = raw_data[1:8193]  # Skip packet ID, take 8192 bytes
                
                # Create a BoardPacket with the full board data
                packet = Packet(
                    packet_id=101,  # PLO_BOARDPACKET
                    raw_data=board_data
                )
                
                # Handle any remaining data after board packet
                remaining_data = raw_data[8193:]
                if len(remaining_data) > 0:
                    logger.debug(f"Remaining data after board packet: {len(remaining_data)} bytes")
                    self.state.buffer = remaining_data + self.state.buffer
                
                return packet
            
            # Check if this contains PLO_FILE packets
            elif len(raw_data) > 0 and (raw_data[0] - 32) == 102:  # PLO_FILE = 102
                logger.debug("Found PLO_FILE in raw data stream")
                logger.debug(f"Raw data contains FILE packets ({len(raw_data)} bytes)")
                
                # Don't create a packet - let the client's raw data handler process this
                # The raw data contains multiple FILE packets that need proper parsing
                self.state.buffer = raw_data + self.state.buffer
                
                # Return None to let normal processing handle it
                return None
            else:
                # Unknown raw data type or multiple packets
                # Put them back in the buffer for normal processing
                logger.debug(f"Unknown raw data type, putting back in buffer")
                self.state.buffer = raw_data + self.state.buffer
                
                # Return None to continue normal packet processing
                return None
            
        # Need more data
        if len(self.state.buffer) == 0 and len(chunk) == 0:
            logger.debug(f"Raw mode stuck: no buffer data, collected {len(self.state.raw_buffer)}/{self.state.expected_raw_size}, time_since_data={time_since_data:.1f}s")
        return None
        
    def _enter_raw_mode(self, packet: RawDataPacket):
        """Enter raw data collection mode"""
        logger.debug(f"Entering raw mode for {packet.expected_size} bytes")
        self.state.in_raw_mode = True
        self.state.expected_raw_size = packet.expected_size
        self.state.raw_buffer = b""
        self.state.raw_mode_start_time = time.time()
        self.state.raw_last_data_time = time.time()
        
    def _exit_raw_mode(self):
        """Exit raw data collection mode"""
        logger.debug(f"Exiting raw mode, collected {len(self.state.raw_buffer)} bytes")
        self.state.in_raw_mode = False
        self.state.expected_raw_size = 0
        self.state.raw_buffer = b""
        
    def _looks_like_complete_raw_data(self) -> bool:
        """Check if raw buffer looks complete even if less than expected size"""
        # For now, always trust the PLO_RAWDATA size
        # Only return true if we've collected the expected amount
        return False
        
    def _decode_gint3(self, data: bytes) -> int:
        """Decode 3-byte GINT value"""
        if len(data) < 3:
            return 0
        return ((data[0] - 32) | 
                ((data[1] - 32) << 6) | 
                ((data[2] - 32) << 12))
    
    def get_stats(self) -> dict:
        """Get stream statistics"""
        return {
            "packets_processed": self.state.packets_processed,
            "bytes_processed": self.state.bytes_processed,
            "buffer_size": len(self.state.buffer),
            "in_raw_mode": self.state.in_raw_mode,
            "raw_buffer_size": len(self.state.raw_buffer) if self.state.in_raw_mode else 0
        }


class PacketStream:
    """Main packet stream processor"""
    
    def __init__(self, encryption_key: int, version: str):
        self.decoder = PacketDecoder(encryption_key)  # For receiving
        self.encoder = PacketDecoder(encryption_key)  # For sending (separate state)
        self.framer = PacketFramer(version)
        self.debug = False
        
    def process_bytes(self, data: bytes) -> List[Packet]:
        """Process raw socket data and return packets"""
        # For ENCRYPT_GEN_5, first byte is compression type
        if not data or len(data) == 0:
            return []
            
        # CompressionType values from encryption.py
        UNCOMPRESSED = 0x02  # 2
        ZLIB = 0x04         # 4
        BZ2 = 0x06          # 6
            
        compression_type = data[0]
        encrypted_data = data[1:]
        
        # Determine decryption limit based on compression type
        if compression_type == UNCOMPRESSED:
            decrypt_limit = 12
        elif compression_type in (ZLIB, BZ2):
            decrypt_limit = 4
        else:
            decrypt_limit = -1  # Decrypt all
        
        # Decrypt with limit
        logger.debug(f"Decrypting: compression_type={compression_type}, limit={decrypt_limit}, data_len={len(encrypted_data)}")
        logger.debug(f"  Decoder state before: key={self.decoder.key}, iterator=0x{self.decoder.iterator:08x}")
        decrypted = self.decoder.decrypt(encrypted_data, decrypt_limit)
        logger.debug(f"  Decoder state after: iterator=0x{self.decoder.iterator:08x}")
        
        try:
            if compression_type == ZLIB:
                decompressed = zlib.decompress(decrypted)
            elif compression_type == BZ2:
                decompressed = bz2.decompress(decrypted)
            elif compression_type == UNCOMPRESSED:
                decompressed = decrypted
            else:
                logger.warning(f"Unknown compression type: {compression_type}")
                return []
        except Exception as e:
            logger.error(f"Decompression error: {e}")
            logger.debug(f"  Compression type: {compression_type}")
            logger.debug(f"  Encrypted length: {len(encrypted_data)}")
            logger.debug(f"  Decrypted length: {len(decrypted)}")
            logger.debug(f"  First 20 decrypted bytes: {decrypted[:20].hex()}")
            return []
        
        if self.debug:
            logger.debug(f"Compression type: {compression_type} (0x{compression_type:02x}), encrypted {len(encrypted_data)} -> decrypted {len(decrypted)} -> decompressed {len(decompressed)} bytes")
            if compression_type in (ZLIB, BZ2):
                logger.debug(f"First 4 encrypted bytes (decrypted): {decrypted[:4].hex()}")
                logger.debug(f"Rest of data (not decrypted): {decrypted[4:20].hex()}...")
            logger.debug(f"First 50 bytes: {decompressed[:50].hex()}")
            # Also show as characters for debugging
            printable = ''.join(chr(b) if 32 <= b < 127 else f'\\x{b:02x}' for b in decompressed[:50])
            logger.debug(f"First 50 chars: {printable}")
        
        # Extract packets
        logger.debug(f"Framer state before: in_raw_mode={self.framer.state.in_raw_mode}, raw_buffer_size={len(self.framer.state.raw_buffer)}, expected={self.framer.state.expected_raw_size}")
        packets = self.framer.process_bytes(decompressed)
        logger.debug(f"Framer state after: in_raw_mode={self.framer.state.in_raw_mode}, raw_buffer_size={len(self.framer.state.raw_buffer)}")
        
        if self.debug and packets:
            logger.debug(f"Extracted {len(packets)} packets:")
            for i, p in enumerate(packets[:5]):  # Show first 5
                logger.debug(f"  [{i}] Packet ID: {p.packet_id}, size: {len(p.raw_data)}")
                
        return packets
        
    @property
    def state(self):
        """Get framer state for debugging"""
        return self.framer.state
        
    def encrypt_packet(self, packet_id: int, data: bytes) -> bytes:
        """Encrypt a packet for sending with ENCRYPT_GEN_5 compression"""
        # Add packet ID (+32 for encoding) and newline
        packet = bytes([packet_id + 32]) + data + b'\n'
        logger.debug(f"Raw packet before compression: ID={packet_id+32}, data={data[:20]}...")
        
        # For ENCRYPT_GEN_5, we need to apply compression
        # Small packets (<=55 bytes) are sent uncompressed (matches v1 and GServer)
        if len(packet) <= 55:
            compression_type = 0x02  # UNCOMPRESSED = 2
            compressed_data = packet
        else:
            compression_type = 0x04  # ZLIB = 4
            compressed_data = zlib.compress(packet)
            
        # Create a new encoder instance with proper limit for this compression type
        packet_encoder = RebornEncryption(self.encoder.key)
        packet_encoder.iterator = self.encoder.iterator  # Copy current state
        packet_encoder.limit_from_type(compression_type)
        
        # Encrypt the compressed data
        encrypted = packet_encoder.encrypt(compressed_data)
        
        # Update main encoder's iterator state
        self.encoder.iterator = packet_encoder.iterator
        
        # Return with compression type byte prepended
        return bytes([compression_type]) + encrypted
        
    def get_stats(self) -> dict:
        """Get stream statistics"""
        return self.framer.get_stats()