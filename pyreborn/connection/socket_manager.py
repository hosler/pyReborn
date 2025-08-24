"""
Connection Manager - Handles network connections, encryption, and low-level communication
"""

import socket
import threading
import time
import random
import logging
from typing import Optional, Callable
from queue import Queue, Empty

from ..protocol.interfaces import IConnectionManager
from ..config.client_config import ClientConfig
from ..session.events import EventManager, EventType
from .encryption import RebornEncryption
from .version_codecs import create_codec
from .versions import get_version_config


class ConnectionManager(IConnectionManager):
    """Manages network connection, encryption, and packet transmission"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.config: Optional[ClientConfig] = None
        self.events: Optional[EventManager] = None
        
        # Network state
        self.socket: Optional[socket.socket] = None
        self.connected = False
        self.running = False
        
        # Threading
        self.send_queue = Queue()
        self.send_thread: Optional[threading.Thread] = None
        self.receive_thread: Optional[threading.Thread] = None
        
        # Encryption
        self.encryption_key = random.randint(0, 255)
        self.in_codec = RebornEncryption()
        self.out_codec = RebornEncryption()
        self.first_encrypted_packet = True
        
        # Version codec (like old client)
        self.version_codec = None
        self.version_config = None
        
        # Callbacks
        self._packet_received_callback: Optional[Callable[[bytes], None]] = None
        
        # PLO_RAWDATA handling
        self.raw_mode = False
        self.raw_bytes_expected = 0
        self.raw_buffer = b""
        
    def initialize(self, config: ClientConfig, event_manager: EventManager) -> None:
        """Initialize with configuration and event system"""
        self.config = config
        self.events = event_manager
        
        # Get version configuration for protocol handling
        self.version_config = get_version_config(config.version)
        if not self.version_config:
            self.logger.warning(f"No version config found for {config.version}, using default")
            from .versions import get_default_version
            self.version_config = get_default_version()
        
        # Initialize version codec for the protocol
        if self.version_config:
            self.version_codec = create_codec(self.version_config, self.encryption_key)
            self.logger.debug(f"Initialized version codec for {config.version} with encryption: {self.version_config.encryption}")
        
    def cleanup(self) -> None:
        """Clean up resources"""
        self.disconnect()
        
    @property
    def name(self) -> str:
        """Manager name"""
        return "connection_manager"
    
    def set_packet_callback(self, callback: Callable[[bytes], None]) -> None:
        """Set callback for received packets"""
        self._packet_received_callback = callback
    
    def connect(self, host: str, port: int) -> bool:
        """Establish connection to server"""
        try:
            self.logger.info(f"Connecting to {host}:{port}")
            
            # Create socket with timeout
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(self.config.connect_timeout if self.config else 10.0)
            
            # Connect
            self.socket.connect((host, port))
            self.socket.settimeout(None)  # Remove timeout after connection
            
            self.connected = True
            self.running = True
            
            # Start networking threads
            self._start_threads()
            
            # Emit connection event
            if self.events:
                self.events.emit(EventType.CONNECTED, {"host": host, "port": port})
            
            self.logger.info("Connection established")
            return True
            
        except Exception as e:
            self.logger.error(f"Connection failed: {e}")
            if self.events:
                self.events.emit(EventType.CONNECTION_FAILED, {"error": str(e)})
            return False
    
    def disconnect(self) -> None:
        """Close connection to server"""
        if not self.connected:
            return
            
        self.logger.info("Disconnecting...")
        
        # Stop threads
        self.running = False
        self.connected = False
        
        # Close socket
        if self.socket:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
                self.socket.close()
            except:
                pass
            self.socket = None
        
        # Wait for threads to finish
        if self.send_thread and self.send_thread.is_alive():
            self.send_thread.join(timeout=1.0)
        if self.receive_thread and self.receive_thread.is_alive():
            self.receive_thread.join(timeout=1.0)
        
        # Clear queues
        while not self.send_queue.empty():
            try:
                self.send_queue.get_nowait()
            except Empty:
                break
        
        # Emit disconnection event
        if self.events:
            self.events.emit(EventType.DISCONNECTED)
        
        self.logger.info("Disconnected")
    
    def is_connected(self) -> bool:
        """Check if connected to server"""
        return self.connected and self.socket is not None
    
    def send_packet(self, packet_data: bytes) -> bool:
        """Send packet to server"""
        if not self.is_connected():
            self.logger.warning("Cannot send packet: not connected")
            return False
        
        try:
            self.send_queue.put(packet_data, timeout=1.0)
            return True
        except Exception as e:
            self.logger.error(f"Failed to queue packet: {e}")
            return False
    
    def send_raw_packet(self, packet_data: bytes) -> bool:
        """Send raw packet immediately (bypasses queue)"""
        if not self.is_connected():
            return False
        
        try:
            # Encrypt and send
            encrypted_data = self._encrypt_outgoing(packet_data)
            
            # Add length prefix for encrypted packets (like old client)
            import struct
            length = struct.pack('>H', len(encrypted_data))
            full_packet = length + encrypted_data
            self.socket.send(full_packet)
            return True
        except Exception as e:
            self.logger.error(f"Failed to send raw packet: {e}")
            return False
    
    def send_unencrypted_packet(self, packet_data: bytes) -> bool:
        """Send packet without encryption (for login) - compressed with zlib WITH length prefix"""
        if not self.is_connected():
            return False
        
        try:
            # Login packet is compressed with zlib
            import zlib
            import struct
            compressed_data = zlib.compress(packet_data)
            
            # Send compressed data WITH 2-byte length prefix (as per old working code)
            length = struct.pack('>H', len(compressed_data))
            full_packet = length + compressed_data
            self.socket.send(full_packet)
            self.logger.debug(f"Sent compressed login packet WITH length prefix: {len(packet_data)} -> {len(compressed_data)} bytes (total: {len(full_packet)})")
            self.logger.debug(f"First few bytes: {full_packet[:20].hex()}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to send unencrypted packet: {e}")
            return False
    
    def _start_threads(self) -> None:
        """Start networking threads"""
        self.send_thread = threading.Thread(target=self._send_worker, daemon=True)
        self.receive_thread = threading.Thread(target=self._receive_worker, daemon=True)
        
        self.send_thread.start()
        self.receive_thread.start()
    
    def _send_worker(self) -> None:
        """Send thread worker function"""
        packet_send_rate = 0.05  # 50ms between packets
        
        while self.running and self.connected:
            try:
                # Get packet from queue
                packet_data = self.send_queue.get(timeout=0.1)
                
                if packet_data and self.socket:
                    # Encrypt and send
                    encrypted_data = self._encrypt_outgoing(packet_data)
                    
                    # Add length prefix for encrypted packets (like old client)
                    import struct
                    length = struct.pack('>H', len(encrypted_data))
                    full_packet = length + encrypted_data
                    self.socket.send(full_packet)
                    
                    # Emit RAW_PACKET_SENT event with packet details
                    if self.events:
                        # Extract packet ID from the data (first byte - 32)
                        packet_id = packet_data[0] - 32 if packet_data else 0
                        self.events.emit(EventType.RAW_PACKET_SENT, {
                            'packet_id': packet_id,
                            'data': packet_data,
                            'size': len(packet_data)
                        })
                    
                    # Rate limiting
                    time.sleep(packet_send_rate)
                    
            except Empty:
                continue
            except Exception as e:
                if self.running:  # Only log if we're supposed to be running
                    self.logger.error(f"Send worker error: {e}")
                break
    
    def _receive_worker(self) -> None:
        """Receive thread worker function"""
        while self.running and self.connected:
            try:
                if not self.socket:
                    break
                
                # Receive packet using length-prefixed protocol (like old client)
                packet_data = self._recv_packet()
                if not packet_data:
                    continue
                
                self.logger.debug(f"Received packet: {len(packet_data)} bytes, first byte: {packet_data[0] if packet_data else 'N/A'}")
                
                # Decrypt packet data
                decrypted_data = self._decrypt_incoming(packet_data)
                self.logger.debug(f"Decrypted packet: {len(decrypted_data)} bytes")
                
                # Process using existing newline separation architecture
                if self._packet_received_callback and decrypted_data:
                    self.logger.debug(f"Processing {len(decrypted_data)} bytes of decrypted data")
                    
                    # Use existing packet separation logic (like binary_reader.py)
                    self._separate_and_process_packets(decrypted_data)
                else:
                    self.logger.warning(f"No callback or empty data - callback: {self._packet_received_callback is not None}, data: {len(decrypted_data) if decrypted_data else 0}")
                    
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:  # Only log if we're supposed to be running
                    self.logger.error(f"Receive worker error: {e}")
                break
        
        # Connection lost
        if self.running:
            self.logger.warning("Connection lost")
            self.connected = False
            if self.events:
                self.events.emit(EventType.DISCONNECTED)
    
    def _recv_packet(self) -> Optional[bytes]:
        """Receive a packet with length prefix (like old client)"""
        try:
            # Read 2-byte length header
            length_data = self._recv_exact(2)
            if not length_data:
                self.logger.debug("No length data received")
                return None
            
            # Unpack length as big-endian unsigned short
            import struct
            length = struct.unpack('>H', length_data)[0]
            self.logger.debug(f"Received length prefix: {length}")
            
            # Read exact packet data
            return self._recv_exact(length)
            
        except socket.timeout:
            return None
        except Exception as e:
            if self.running:
                self.logger.debug(f"Error receiving packet: {e}")
            return None
    
    def _recv_exact(self, size: int) -> Optional[bytes]:
        """Receive exact number of bytes"""
        data = b''
        while len(data) < size:
            try:
                chunk = self.socket.recv(size - len(data))
                if not chunk:
                    if self.connected:  # Only log once
                        self.logger.error("Connection closed by remote")
                        self.connected = False
                    return None
                data += chunk
            except socket.timeout:
                if data:
                    continue  # Partial data, keep trying
                return None
            except Exception as e:
                if self.running:
                    self.logger.error(f"Error in _recv_exact: {e}")
                return None
        return data
    
    def _encrypt_outgoing(self, data: bytes) -> bytes:
        """Encrypt outgoing packet data using version codec (like old client)"""
        try:
            # Use version codec if available (like old client)
            if self.version_codec:
                encrypted_data = self.version_codec.send_packet(data)
                # Version codec includes length prefix, so remove it for our send queue
                if len(encrypted_data) >= 2:
                    import struct
                    length = struct.unpack('>H', encrypted_data[:2])[0]
                    if length == len(encrypted_data) - 2:
                        return encrypted_data[2:]  # Remove length prefix
                return encrypted_data
            
            # Fallback to basic encryption (for compatibility)
            self.logger.debug("Using fallback encryption (no version codec)")
            return self.out_codec.encrypt(data)
            
        except Exception as e:
            self.logger.error(f"Encryption error: {e}")
            return data
    
    def _decrypt_incoming(self, data: bytes) -> bytes:
        """Decrypt incoming packet data using version codec (like old client)"""
        try:
            if not data or len(data) == 0:
                return b''
            
            self.logger.debug(f"_decrypt_incoming: {len(data)} bytes, first_encrypted_packet={self.first_encrypted_packet}")
            
            # First packet after login is just zlib compressed, not encrypted
            if self.first_encrypted_packet:
                try:
                    import zlib
                    decompressed = zlib.decompress(data)
                    self.logger.debug(f"Successfully decompressed first packet: {len(data)} -> {len(decompressed)} bytes")
                    self.logger.debug(f"First packet ID: {decompressed[0] if decompressed else 'N/A'}")
                    self.first_encrypted_packet = False
                    
                    # Return decompressed data as-is - let existing packet separation handle it
                    return decompressed
                except zlib.error as e:
                    # Not zlib compressed, try version codec
                    self.logger.debug(f"First packet not zlib compressed: {e}")
                    pass
            
            # Use version codec if available (like old client)
            if self.version_codec:
                decrypted_data = self.version_codec.recv_packet(data)
                if decrypted_data:
                    return decrypted_data
                else:
                    # Enhanced debugging for decryption failures
                    self.logger.warning(f"🔍 DECRYPTION FAILURE: Version codec failed")
                    self.logger.warning(f"   Data length: {len(data)} bytes")
                    self.logger.warning(f"   First byte: 0x{data[0]:02x} ({data[0]})")
                    self.logger.warning(f"   First 10 bytes: {data[:10].hex() if len(data) >= 10 else data.hex()}")
                    
                    # Check if this might be a file transfer packet
                    if len(data) > 100:  # Large packets are often files
                        self.logger.warning(f"   🚨 LARGE PACKET FAILED - Possibly file transfer!")
                        
                        # Look for file-like patterns
                        if b'.gmap' in data:
                            self.logger.error(f"   🚨 CONTAINS '.gmap' - This is likely the chicken.gmap file!")
                        if b'.nw' in data:
                            self.logger.warning(f"   🚨 CONTAINS '.nw' - This is likely a level file!")
                    
                    return b''
            
            # Fallback to basic decryption (for compatibility)
            self.logger.debug("Using fallback decryption (no version codec)")
            
            # First byte is compression type
            compression_type = data[0]
            encrypted_data = data[1:] if len(data) > 1 else b''
            
            # Set codec limit based on compression type
            from .encryption import CompressionType
            self.in_codec.limit_from_type(compression_type)
            
            # Decrypt the data
            decrypted_data = self.in_codec.decrypt(encrypted_data)
            
            # Decompress based on type
            if compression_type == CompressionType.UNCOMPRESSED:
                return decrypted_data
            elif compression_type == CompressionType.ZLIB:
                import zlib
                return zlib.decompress(decrypted_data)
            elif compression_type == CompressionType.BZ2:
                import bz2
                return bz2.decompress(decrypted_data)
            else:
                self.logger.warning(f"Unknown compression type: {compression_type}")
                return decrypted_data
                
        except Exception as e:
            self.logger.error(f"Decryption error: {e}")
            return data
    
    
    def _separate_and_process_packets(self, data: bytes) -> None:
        """Separate newline-delimited packets and process each one individually (like binary_reader.py)"""
        try:
            # Handle raw mode first (after PLO_RAWDATA)
            if self.raw_mode and self.raw_bytes_expected > 0:
                # We're in raw mode, accumulate bytes
                bytes_to_take = min(len(data), self.raw_bytes_expected - len(self.raw_buffer))
                self.raw_buffer += data[:bytes_to_take]
                remaining_data = data[bytes_to_take:]
                
                self.logger.info(f"[RAW MODE] Accumulated {len(self.raw_buffer)}/{self.raw_bytes_expected} bytes")
                
                # Check if we have all the raw data
                if len(self.raw_buffer) >= self.raw_bytes_expected:
                    # We have all the raw data, parse it as individual packets
                    self.logger.info(f"[RAW MODE] Complete! Processing {len(self.raw_buffer)} bytes as raw packet data")
                    
                    # Log first few bytes to debug
                    raw_data = self.raw_buffer[:self.raw_bytes_expected]
                    if len(raw_data) >= 10:
                        preview = ' '.join(f'{b:02x}' for b in raw_data[:10])
                        self.logger.info(f"[RAW MODE] First bytes of raw data: {preview}")
                    
                    # FIXED: Check if raw data is PLO_FILE or board data
                    if len(raw_data) >= 1:
                        first_byte = raw_data[0]
                        
                        # Check if this is PLO_FILE packet (102 + 32 = 134)
                        if first_byte == 134:  # PLO_FILE packet
                            self.logger.info(f"[RAW ANALYSIS] Raw data is PLO_FILE packet ({len(raw_data)} bytes)")
                            
                            # Process as PLO_FILE packet - pass through to packet processor
                            if self._packet_received_callback:
                                # Convert to proper packet format (subtract 32 offset)
                                file_packet = bytes([102]) + raw_data[1:]  # 102 + file data
                                self.logger.info(f"[RAW ANALYSIS] Processing PLO_FILE packet")
                                self._packet_received_callback(file_packet)
                                
                        elif len(raw_data) >= 8193 and first_byte == 133:  # Board data (133 = 101 + 32)
                            # This is board data - use existing logic
                            pure_tile_data = raw_data[1:8193]  # Bytes 1-8192
                            
                            self.logger.info(f"[RAW ANALYSIS] Extracted {len(pure_tile_data)} bytes of pure tile data (skipped header byte {raw_data[0]})")
                            
                            # Create proper PLO_BOARDPACKET with extracted tile data
                            board_packet = bytes([101]) + pure_tile_data + b'\n'  # 101 + tiles + newline
                            
                            if self._packet_received_callback:
                                self.logger.info(f"[RAW ANALYSIS] Created PLO_BOARDPACKET with pure tile data ({len(board_packet)} bytes)")
                                self._packet_received_callback(board_packet)
                        else:
                            # Unknown raw data type
                            self.logger.warning(f"[RAW ANALYSIS] Unknown raw data type: first byte {first_byte} ({first_byte-32} without offset)")
                            self.logger.info(f"[RAW ANALYSIS] Data preview: {raw_data[:50].hex()}")
                            
                            # Try to process as individual packets
                            if self._packet_received_callback:
                                self.logger.info(f"[RAW ANALYSIS] Attempting to process as regular packet data")
                                self._separate_and_process_packets(raw_data)
                    else:
                        self.logger.warning(f"[RAW ANALYSIS] Raw data too small: {len(raw_data)} bytes")
                    
                    # Process the board packet
                    # if self._packet_received_callback:
                    #     self._packet_received_callback(board_packet)
                    
                    # Exit raw mode
                    self.raw_mode = False
                    self.raw_bytes_expected = 0
                    self.raw_buffer = b""
                    
                    # Process any remaining data normally
                    if remaining_data:
                        self._separate_and_process_packets(remaining_data)
                
                return
            
            # Normal packet processing
            pos = 0
            while pos < len(data):
                # Find the next newline (packet terminator)
                next_newline = data.find(b'\n', pos)
                
                if next_newline == -1:
                    # No more complete packets
                    break
                    
                # Extract one packet
                packet_bytes = data[pos:next_newline]
                pos = next_newline + 1
                
                if packet_bytes and len(packet_bytes) >= 1:
                    # First byte is encrypted packet ID
                    encrypted_id = packet_bytes[0]
                    packet_id = encrypted_id - 32
                    
                    # Handle negative packet IDs (when encrypted_id < 32)
                    if packet_id < 0:
                        packet_id = encrypted_id  # Use raw value if decryption gives negative
                    
                    self.logger.debug(f"Separated packet: ID={packet_id}, length={len(packet_bytes)}")
                    
                    # 🔍 ENHANCED FILE TRANSFER MONITORING
                    if packet_id == 102:  # PLO_FILE
                        self.logger.info(f"🔍 FILE TRANSFER: PLO_FILE packet detected ({len(packet_bytes)} bytes)")
                        if b'.gmap' in packet_bytes:
                            self.logger.info(f"   🎯 CONTAINS .gmap - This is the chicken.gmap file!")
                        if b'.nw' in packet_bytes:
                            self.logger.info(f"   📄 CONTAINS .nw - This is a level file")
                    elif packet_id == 30:  # PLO_FILESENDFAILED
                        self.logger.error(f"🚨 FILE TRANSFER FAILED: PLO_FILESENDFAILED packet detected ({len(packet_bytes)} bytes)")
                        if b'.gmap' in packet_bytes:
                            self.logger.error(f"   🎯 SERVER REJECTED chicken.gmap FILE!")
                        if b'chicken' in packet_bytes:
                            self.logger.error(f"   🐔 Server rejected chicken-related file!")
                        # Log the raw packet for debugging
                        self.logger.error(f"   Raw packet: {packet_bytes.hex()}")
                    elif packet_id == 45:  # PLO_FILEUPTODATE  
                        self.logger.info(f"🔍 FILE TRANSFER: PLO_FILEUPTODATE packet detected ({len(packet_bytes)} bytes)")
                        if b'.gmap' in packet_bytes:
                            self.logger.info(f"   🎯 chicken.gmap is up to date on server")
                    elif packet_id == 100:  # PLO_RAWDATA - often used for large files
                        self.logger.info(f"🔍 FILE TRANSFER: PLO_RAWDATA packet detected ({len(packet_bytes)} bytes)")
                    
                    # Check for PLO_RAWDATA (packet ID 100)
                    if packet_id == 100:
                        # This is PLO_RAWDATA, parse the size announcement
                        if len(packet_bytes) >= 4:
                            # GINT3 size is in bytes 1-3
                            b1 = packet_bytes[1] - 32
                            b2 = packet_bytes[2] - 32
                            b3 = packet_bytes[3] - 32
                            announced_size = (b1 << 14) | (b2 << 7) | b3
                            
                            self.logger.info(f"[PLO_RAWDATA] Announced {announced_size} bytes of raw data")
                            
                            # Enter raw mode
                            self.raw_mode = True
                            self.raw_bytes_expected = announced_size
                            self.raw_buffer = b""
                            
                            # Don't process PLO_RAWDATA packet itself, just the announcement
                            # Continue processing remaining data in raw mode
                            if pos < len(data):
                                self._separate_and_process_packets(data[pos:])
                            return
                    
                    # Create corrected packet with the actual packet ID as first byte
                    corrected_packet = bytes([packet_id]) + packet_bytes[1:]
                    
                    # Process this individual packet through callback
                    if self._packet_received_callback:
                        self._packet_received_callback(corrected_packet)
                        
        except Exception as e:
            self.logger.error(f"Error separating packets: {e}")
            # Fallback - send the original data as-is
            if self._packet_received_callback:
                self._packet_received_callback(data)
    
    def get_encryption_key(self) -> int:
        """Get current encryption key"""
        return self.encryption_key
    
    def set_encryption_key(self, key: int) -> None:
        """Set encryption key and initialize version codec (like old client)"""
        self.encryption_key = key
        
        # Initialize version codec with encryption key (like old client after login)
        if self.version_config:
            self.version_codec = create_codec(self.version_config.encryption, key)
            self.logger.debug(f"Created version codec: {self.version_config.encryption} with key: {key}")
        
        # Also reset basic codecs for compatibility
        self.in_codec.reset(key)
        self.out_codec.reset(key)
        self.first_encrypted_packet = True
        self.logger.debug(f"Initialized encryption with key: {key}")