"""
Core networking client for PyReborn.
Handles only connection, login, and packet sending/receiving.
"""
import socket
import threading
import queue
import time
import logging
from typing import Optional, Callable

from ..protocol.packets import PacketBuilder, PacketReader
from ..protocol.enums import PlayerToServer, ServerToPlayer
from ..encryption import GraalEncryption
from ..events import EventManager, EventType
from ..game.state import GameState
from ..handlers.registry import PacketHandlerRegistry

logger = logging.getLogger(__name__)


class CoreClient:
    """
    Core networking client that handles low-level communication.
    """
    
    def __init__(self):
        # Networking
        self.socket: Optional[socket.socket] = None
        self.host: str = ""
        self.port: int = 0
        self.connected: bool = False
        
        # Encryption
        self.in_codec = GraalEncryption()
        self.out_codec = GraalEncryption()
        
        # Threading
        self._receive_thread: Optional[threading.Thread] = None
        self._send_thread: Optional[threading.Thread] = None
        self._packet_queue: queue.Queue = queue.Queue()
        self._send_queue: queue.Queue = queue.Queue()
        self._running: bool = False
        
        # Components
        self.state = GameState()
        self.events = EventManager()
        self.handlers = PacketHandlerRegistry()
        
        # Subscribe to board stream event
        self.events.subscribe(EventType.LEVEL_BOARD_UPDATE, self._on_level_board)
        
        # Connection state
        self._login_complete = False
        self._got_signature = False  # Track if we got PLO_SIGNATURE
        self._downloading_board = False
        self._expecting_raw_board = False  # After PLO_LEVELBOARD, expect raw data
        self._board_buffer = bytearray()
        self._partial_packet = bytearray()  # For incomplete packets
        self._raw_data_expected = 0  # Expected raw data bytes after PLO_RAWDATA
        
        # Callbacks
        self._on_connected: Optional[Callable] = None
        self._on_disconnected: Optional[Callable] = None
        
    def connect(self, host: str, port: int, timeout: float = 10.0) -> bool:
        """
        Connect to a Graal server.
        
        Args:
            host: Server hostname
            port: Server port
            timeout: Connection timeout in seconds
            
        Returns:
            True if connected successfully
        """
        if self.connected:
            logger.warning("Already connected")
            return True
            
        try:
            self.host = host
            self.port = port
            
            # Create socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(timeout)
            self.socket.connect((host, port))
            self.socket.settimeout(None)  # Non-blocking after connect
            
            # Reset encryption
            self.in_codec = GraalEncryption()
            self.out_codec = GraalEncryption()
            
            # Start threads
            self._running = True
            self._receive_thread = threading.Thread(target=self._receive_loop)
            self._receive_thread.daemon = True
            self._receive_thread.start()
            
            self._send_thread = threading.Thread(target=self._send_loop)
            self._send_thread.daemon = True
            self._send_thread.start()
            
            self.connected = True
            self.state.connected = True
            
            # Emit event
            self.events.emit(EventType.CONNECTED, host=host, port=port)
            
            if self._on_connected:
                self._on_connected()
                
            logger.info(f"Connected to {host}:{port}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            self.disconnect()
            return False
            
    def disconnect(self) -> None:
        """Disconnect from the server."""
        if not self.connected and not self.socket:
            return
            
        logger.info("Disconnecting...")
        
        self._running = False
        self.connected = False
        self.state.connected = False
        
        # Close socket
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
            
        # Wait for threads
        if self._receive_thread and self._receive_thread.is_alive():
            self._receive_thread.join(timeout=1.0)
        if self._send_thread and self._send_thread.is_alive():
            self._send_thread.join(timeout=1.0)
            
        # Clear queues
        while not self._packet_queue.empty():
            self._packet_queue.get()
        while not self._send_queue.empty():
            self._send_queue.get()
            
        # Emit event
        self.events.emit(EventType.DISCONNECTED)
        
        if self._on_disconnected:
            self._on_disconnected()
            
        logger.info("Disconnected")
        
    def login(self, account: str, password: str) -> None:
        """
        Send login credentials to the server.
        
        Args:
            account: Account name
            password: Account password
        """
        if not self.connected:
            raise RuntimeError("Not connected")
            
        # Use LoginPacket from packets module
        from ..protocol.packets import LoginPacket
        import zlib
        import random
        
        # Generate encryption key
        encryption_key = random.randint(0, 255)
        
        # Create and send login packet
        login_packet = LoginPacket(account, password, encryption_key)
        raw_data = login_packet.to_bytes()
        
        # Compress and send
        compressed = zlib.compress(raw_data)
        self._send_raw(compressed)
        
        # Setup encryption with the key
        self.in_codec.reset(encryption_key)
        self.out_codec.reset(encryption_key)
        
        # Don't mark login complete yet - wait for server response
        # self._login_complete = True
        
        logger.info(f"Sent login request for account: {account}")
        
    def send_packet(self, packet: PacketBuilder) -> None:
        """
        Send a packet to the server.
        
        Args:
            packet: The packet to send
        """
        if not self.connected:
            logger.warning("Cannot send packet: not connected")
            return
        
        # Allow sending packets after login is sent
        # The server seems to accept packets immediately
            
        self._send_queue.put(packet.build())
        
    def _send_raw(self, data: bytes) -> None:
        """Send raw data immediately without encryption."""
        if not self.socket:
            return
            
        # Add header (big-endian 2-byte length)
        import struct
        header = struct.pack('>H', len(data))
        
        try:
            self.socket.sendall(header + data)
        except Exception as e:
            logger.error(f"Failed to send raw data: {e}")
        
    def process_packets(self, max_packets: int = 10) -> int:
        """
        Process received packets.
        
        Args:
            max_packets: Maximum number of packets to process
            
        Returns:
            Number of packets processed
        """
        processed = 0
        
        while processed < max_packets and not self._packet_queue.empty():
            try:
                data = self._packet_queue.get_nowait()
                reader = PacketReader(data)
                
                if len(data) > 0:
                    # Packet ID is first byte minus 32
                    packet_id = data[0] - 32
                    packet_data = data[1:]
                    
                    # Board packet should have been handled in receive phase
                    # Just log if we see it here
                    if packet_id == ServerToPlayer.PLO_BOARDPACKET:
                        logger.debug("Processing board packet")
                    
                    # Create reader for the packet data (without ID)
                    reader = PacketReader(packet_data)
                    
                    # Let handlers process the packet
                    result = self.handlers.handle_packet(packet_id, reader, self.state)
                    
                    # Emit packet event
                    self.events.emit(EventType.PACKET_RECEIVED,
                        packet_id=packet_id,
                        data=data,
                        result=result
                    )
                    
                processed += 1
                
            except queue.Empty:
                break
            except Exception as e:
                logger.error(f"Error processing packet: {e}")
                
        return processed
        
    def _receive_loop(self) -> None:
        """Background thread for receiving packets."""
        buffer = bytearray()
        
        while self._running and self.socket:
            try:
                # Receive data
                data = self.socket.recv(4096)
                if not data:
                    logger.warning("Server closed connection")
                    break
                    
                buffer.extend(data)
                
                # Process complete packets
                while len(buffer) >= 3:
                    # Read packet header
                    packet_len = (buffer[0] << 8) | buffer[1]
                    
                    if len(buffer) < packet_len + 2:
                        break  # Incomplete packet
                        
                    # Extract packet
                    packet_data = buffer[2:packet_len + 2]
                    buffer = buffer[packet_len + 2:]
                    
                    # Check if we're expecting raw board data
                    if self._expecting_raw_board:
                        # ALL data after PLO_LEVELBOARD is raw board data until we have 8192 bytes
                        logger.info(f"Raw board data fragment: {packet_len} bytes")
                        self._board_buffer.extend(packet_data)
                        logger.info(f"Board buffer now: {len(self._board_buffer)} bytes of 8192")
                        
                        # Check if we have full board data (8192 bytes = 64x64 tiles * 2 bytes)
                        if len(self._board_buffer) >= 8192:
                            logger.info("✓ Complete board data received!")
                            
                            # Create board packet
                            board_packet = bytearray()
                            board_packet.append(ServerToPlayer.PLO_BOARDPACKET + 32)
                            board_packet.extend(self._board_buffer[:8192])
                            
                            # Queue for processing
                            self._packet_queue.put(bytes(board_packet))
                            
                            # Reset state and process any remaining data normally
                            self._expecting_raw_board = False
                            remaining = self._board_buffer[8192:]
                            self._board_buffer.clear()
                            
                            if remaining:
                                # Put remaining data back in buffer to process normally
                                buffer = remaining + buffer
                        continue
                    
                    # Handle based on connection phase
                    if not self._login_complete:
                        # First large packet after login contains encrypted packets including signature
                        if packet_len > 3000:
                            logger.info(f"Large initial packet: {packet_len} bytes")
                            # This is encrypted, not compressed
                            try:
                                decrypted = self.in_codec.decrypt(packet_data)
                                logger.info(f"Decrypted large packet: {packet_len} -> {len(decrypted)} bytes")
                                
                                # Check for signature in decrypted data
                                if 57 in decrypted:  # PLO_SIGNATURE + 32 = 25 + 32 = 57
                                    logger.info("Found PLO_SIGNATURE in decrypted data!")
                                    self._got_signature = True
                                    self._login_complete = True
                                    self.events.emit(EventType.LOGIN_SUCCESS)
                                
                                # Check for board packet
                                if 133 in decrypted:  # PLO_BOARDPACKET + 32
                                    board_pos = decrypted.find(bytes([133]))
                                    logger.info(f"Found PLO_BOARDPACKET at position {board_pos}")
                                
                                # Process the decrypted stream normally
                                self._handle_encrypted_stream(decrypted)
                                continue
                            except Exception as e:
                                logger.error(f"Failed to process large initial packet: {e}")
                        else:
                            # Small packets during login - skip
                            logger.debug(f"Small login packet: {packet_len} bytes")
                            continue
                    elif self._raw_data_expected > 0:
                        # We're expecting raw data after PLO_RAWDATA
                        logger.info(f"Receiving raw data: {len(packet_data)} bytes (expected {self._raw_data_expected})")
                        # This is raw, unencrypted data!
                        if packet_data[0] == 133:  # PLO_BOARDPACKET + 32
                            logger.info("🎯 Raw data is board packet!")
                        else:
                            logger.debug(f"Raw data first byte: {packet_data[0]} (hex: {packet_data[0]:02x})")
                        
                        # Queue the raw data directly - DO NOT DECRYPT
                        self._packet_queue.put(packet_data)
                        self._raw_data_expected = 0
                        continue
                    elif self._downloading_board:
                        # Board download phase - collect raw data
                        self._handle_board_download(packet_data)
                    else:
                        # Check for board packet - it should come unencrypted after login
                        # Board packet: PLO_BOARDPACKET(133) + 8192 bytes + newline = 8194 bytes total
                        if len(packet_data) >= 8000 and packet_data[0] == 133:  # PLO_BOARDPACKET + 32
                            logger.info(f"🎯 Board packet detected: {len(packet_data)} bytes")
                            logger.debug(f"   First 20 bytes: {packet_data[:20].hex()}")
                            
                            # Board packet is NOT encrypted - just queue it
                            self._packet_queue.put(packet_data)
                            continue
                        
                        # Check if this is an unencrypted board packet
                        # Board packets are: PLO_BOARDPACKET (133) + 8192 bytes + newline
                        if len(packet_data) >= 8000 and packet_data[0] == 133:
                            logger.info(f"🎯 Found unencrypted board packet: {len(packet_data)} bytes")
                            # This is raw board data - don't decrypt!
                            # Find the newline terminator
                            newline_pos = packet_data.find(b'\n')
                            if newline_pos > 0:
                                board_packet = packet_data[:newline_pos]
                            else:
                                board_packet = packet_data
                            self._packet_queue.put(board_packet)
                            continue
                        else:
                            # Normal encrypted packets
                            # Decrypt
                            decrypted = self.in_codec.decrypt(bytes(packet_data))
                            
                            # Log packet info
                            logger.debug(f"Received packet: len={len(packet_data)} -> decrypted len={len(decrypted)}")
                            if len(decrypted) > 0:
                                logger.debug(f"First few bytes: {decrypted[:min(20, len(decrypted))].hex()}")
                                logger.debug(f"First few bytes as ASCII: {decrypted[:min(20, len(decrypted))].decode('ascii', errors='replace')}")
                            
                            # Board data should have been caught before decryption
                            # If we still see large decrypted packets, log for debugging
                            if len(decrypted) > 1900:
                                logger.warning(f"Large decrypted packet: {len(decrypted)} bytes")
                                # Check for board marker in decrypted data
                                board_marker = bytes([ServerToPlayer.PLO_BOARDPACKET + 32])
                                board_pos = decrypted.find(board_marker)
                                if board_pos >= 0:
                                    logger.info(f"🎯 Found PLO_BOARDPACKET at position {board_pos} in decrypted data!")
                                    # Check how much data follows
                                    remaining = len(decrypted) - board_pos
                                    logger.info(f"   Remaining bytes after marker: {remaining}")
                                    
                                    # Extract board packet even if it's not full size
                                    # Find the newline terminator
                                    board_start = board_pos
                                    newline_pos = decrypted.find(b'\n', board_start)
                                    # Look for the full board data stream
                                    # Board packet might contain tiles + NPCs + other data
                                    # Let's look for patterns after the board marker
                                    
                                    # First, let's see what comes after PLO_BOARDPACKET
                                    logger.debug(f"   Data after board marker: {decrypted[board_pos+1:board_pos+20].hex()}")
                                    # Also check what's before
                                    logger.debug(f"   Data before board marker: {decrypted[max(0, board_pos-10):board_pos].hex()}")
                                    # Look for newlines
                                    next_newline = decrypted.find(b'\n', board_pos)
                                    logger.debug(f"   Next newline at position: {next_newline} ({next_newline - board_pos} bytes after marker)")
                                    
                                    # Find the end of this packet (newline)
                                    newline_pos = decrypted.find(b'\n', board_start)
                                    if newline_pos > board_start:
                                        board_packet = decrypted[board_start:newline_pos]
                                        logger.info(f"   Board packet size: {len(board_packet)} bytes")
                                        # Queue it for processing
                                        self._packet_queue.put(board_packet)
                                        
                                        # Continue processing the rest of the stream normally
                                        # Remove the board packet from the stream
                                        decrypted = decrypted[:board_start] + decrypted[newline_pos:]
                                else:
                                    # Maybe the packet ID is without the +32 offset?
                                    board_marker2 = bytes([ServerToPlayer.PLO_BOARDPACKET])
                                    board_pos2 = decrypted.find(board_marker2)
                                    if board_pos2 >= 0:
                                        logger.info(f"🎯 Found raw PLO_BOARDPACKET (no +32) at position {board_pos2}!")
                                        remaining2 = len(decrypted) - board_pos2
                                        logger.info(f"   Remaining bytes: {remaining2}")
                            
                            # Try to parse packets from the decrypted stream
                            # First check if this looks like newline-terminated packets
                            has_newlines = b'\n' in decrypted
                            logger.debug(f"Stream has newlines: {has_newlines}")
                            
                            if not has_newlines and len(decrypted) > 10:
                                # Normal parsing
                                logger.debug("Trying to parse as length-prefixed packets...")
                                pos = 0
                                packets_found = 0
                                while pos < len(decrypted) - 2:
                                    # Try to read packet with length prefix (2 bytes)
                                    try:
                                        import struct
                                        packet_len = struct.unpack('>H', decrypted[pos:pos+2])[0]
                                        if packet_len > 0 and packet_len < 1000 and pos + 2 + packet_len <= len(decrypted):
                                            packet_data = decrypted[pos+2:pos+2+packet_len]
                                            self._packet_queue.put(packet_data)
                                            pos += 2 + packet_len
                                            packets_found += 1
                                        else:
                                            # Not a valid length prefix, treat as raw packet
                                            break
                                    except:
                                        break
                                
                                if packets_found > 0:
                                    logger.debug(f"Found {packets_found} length-prefixed packets")
                                else:
                                    # Just queue the whole thing as one packet
                                    logger.debug("Queueing entire stream as single packet")
                                    self._packet_queue.put(decrypted)
                            else:
                                # Split by newlines (packets are newline-terminated)
                                # But first handle any partial packet from before
                                if self._partial_packet:
                                    decrypted = self._partial_packet + decrypted
                                    self._partial_packet = bytearray()
                                
                                pos = 0
                                while pos < len(decrypted):
                                    # Find next newline
                                    next_newline = decrypted.find(b'\n', pos)
                                    
                                    if next_newline == -1:
                                        # Save partial packet for next time
                                        self._partial_packet = decrypted[pos:]
                                        break
                                        
                                    # Extract packet (not including newline)
                                    packet = decrypted[pos:next_newline]
                                    pos = next_newline + 1
                                    
                                    if packet:
                                        # Log packet ID
                                        packet_id = packet[0] - 32 if packet else -1
                                        if packet_id == 100:  # PLO_RAWDATA
                                            logger.info(f"Found PLO_RAWDATA! Packet length: {len(packet)} bytes, hex: {packet[:10].hex()}")
                                        
                                        # Check for PLO_RAWDATA packet
                                        if len(packet) >= 5 and packet_id == ServerToPlayer.PLO_RAWDATA:
                                            # PLO_RAWDATA packet - next packet will be raw data
                                            import struct
                                            logger.debug(f"PLO_RAWDATA packet bytes: {packet[:10].hex()}")
                                            # GServer sends size as 4-byte int (network byte order)
                                            size_bytes = packet[1:5]
                                            size = struct.unpack('>I', size_bytes)[0]  # 4-byte big-endian size
                                            logger.debug(f"Size bytes: {size_bytes.hex()} = {size}")
                                            
                                            # Sanity check
                                            if size == 8194:
                                                logger.info("✓ PLO_RAWDATA size matches expected board packet size!")
                                            elif size > 100000:
                                                logger.warning(f"Unexpected large size: {size} - might be wrong byte order")
                                                
                                            self._raw_data_expected = size
                                            logger.info(f"PLO_RAWDATA packet: expecting {size} bytes of raw data")
                                            # Don't queue this packet - it's just a header
                                        else:
                                            # Queue for processing
                                            self._packet_queue.put(packet)
                                    
                    
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    logger.error(f"Receive error: {e}")
                break
                
        # Trigger disconnect
        if self._running:
            self.disconnect()
            
    def _send_loop(self) -> None:
        """Background thread for sending packets with rate limiting."""
        last_send_time = 0
        send_interval = 0.05  # 50ms between packets
        
        while self._running:
            try:
                # Get packet with timeout
                packet_data = self._send_queue.get(timeout=0.1)
                
                # Rate limiting
                current_time = time.time()
                time_since_last = current_time - last_send_time
                if time_since_last < send_interval:
                    time.sleep(send_interval - time_since_last)
                    
                # Determine compression type
                if len(packet_data) <= 55:
                    compression_type = 0x02  # UNCOMPRESSED
                    compressed_data = packet_data
                else:
                    import zlib
                    compression_type = 0x04  # ZLIB
                    compressed_data = zlib.compress(packet_data)
                
                # Create a new codec for this packet with the appropriate limit
                from ..encryption import GraalEncryption
                packet_codec = GraalEncryption(self.out_codec.key)
                packet_codec.iterator = self.out_codec.iterator  # Copy current iterator state
                packet_codec.limit_from_type(compression_type)
                
                # Encrypt data
                encrypted_data = packet_codec.encrypt(compressed_data)
                
                # Update our main codec's iterator to maintain state
                self.out_codec.iterator = packet_codec.iterator
                
                # Build final packet
                packet = bytes([compression_type]) + encrypted_data
                packet_len = len(packet)
                header = bytes([(packet_len >> 8) & 0xFF, packet_len & 0xFF])
                
                # Send
                if self.socket and self._running:
                    self.socket.sendall(header + packet)
                    last_send_time = time.time()
                    
            except queue.Empty:
                continue
            except Exception as e:
                if self._running:
                    logger.error(f"Send error: {e}")
                    
    def set_connected_callback(self, callback: Callable) -> None:
        """Set callback for when connected."""
        self._on_connected = callback
        
    def set_disconnected_callback(self, callback: Callable) -> None:
        """Set callback for when disconnected."""
        self._on_disconnected = callback
        
    def _on_level_board(self, **kwargs):
        """Handle level board event - raw board data will follow."""
        status = kwargs.get('status')
        if status == 'board_stream_starting':
            logger.info("PLO_LEVELBOARD received - expecting raw board data packets")
            self._expecting_raw_board = True
            self._board_buffer.clear()
        
    def _handle_encrypted_stream(self, decrypted: bytes) -> None:
        """Handle decrypted packet stream."""
        # Handle partial packets
        if self._partial_packet:
            decrypted = self._partial_packet + decrypted
            self._partial_packet = bytearray()
        
        # Split by newlines
        pos = 0
        while pos < len(decrypted):
            next_newline = decrypted.find(b'\n', pos)
            if next_newline == -1:
                # Save partial packet for next time
                self._partial_packet = decrypted[pos:]
                break
                
            packet = decrypted[pos:next_newline]
            pos = next_newline + 1
            
            if packet:
                # Queue for processing
                self._packet_queue.put(packet)
    
    def _handle_login_packet(self, data: bytes) -> None:
        """Handle packets during login phase."""
        import zlib
        
        # Large initial packet is likely compressed login response + initial data
        if not self._got_signature and len(data) > 3000:
            logger.info(f"Large initial packet: {len(data)} bytes - likely compressed login response")
            original_len = len(data)
            try:
                # Try to decompress
                decompressed = zlib.decompress(data)
                data = decompressed
                logger.info(f"Decompressed login response: {original_len} -> {len(data)} bytes")
                
                # Check if decompressed data contains signature
                # Packets are newline-separated, so split and check each
                packets = data.split(b'\n')
                for packet in packets:
                    if packet and len(packet) > 0:
                        packet_id = packet[0] - 32
                        if packet_id == ServerToPlayer.PLO_SIGNATURE:
                            logger.info("Found PLO_SIGNATURE in decompressed data!")
                            self._got_signature = True
                            self._login_complete = True
                            self.events.emit(EventType.LOGIN_SUCCESS)
                            break
            except:
                # Not compressed - this shouldn't happen for large initial packet
                logger.warning(f"Large initial packet not compressed - unusual")
        
        # Check if this is already board data (unencrypted)
        if len(data) > 8000 and data[0] == 133:  # PLO_BOARDPACKET + 32
            logger.info("Unencrypted board packet received!")
            self._packet_queue.put(data)
            self._login_complete = True
            if not self._got_signature:
                self.events.emit(EventType.LOGIN_SUCCESS)
            return
        
        # Small packets during login are usually encrypted heartbeats
        # Large packet should have been handled above
        if len(data) < 100:
            logger.debug(f"Small login packet: {len(data)} bytes - likely heartbeat")
            return
            
        # During login phase, we expect compressed packets
        # Split by newlines since even compressed packets are newline-terminated
        pos = 0
        while pos < len(data):
            next_newline = data.find(b'\n', pos)
            
            if next_newline == -1:
                # Save partial packet
                break
                
            packet = data[pos:next_newline]
            pos = next_newline + 1
            
            if packet and len(packet) > 0:
                packet_id = packet[0] - 32
                
                logger.debug(f"Login phase packet: ID={packet_id}")
                
                if packet_id == ServerToPlayer.PLO_SIGNATURE:
                    logger.info("Received signature packet - login handshake done")
                    self._got_signature = True
                    # Emit login success event
                    self.events.emit(EventType.LOGIN_SUCCESS)
                    # Next large packet should be board data
                    
                # Queue packet for processing
                self._packet_queue.put(packet)
    def _decode_truncated_hex(self, truncated_hex: bytes) -> bytes:
        """Decode truncated hex board data to binary format."""
        logger.info(f"Decoding {len(truncated_hex)} characters of truncated hex")
        
        # Base64 character set for truncated hex  
        base64_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
        
        board_data = bytearray(8192)  # 4096 tiles * 2 bytes each
        
        tile_count = 0
        hex_str = truncated_hex.decode('ascii', errors='ignore')
        
        for i in range(0, len(hex_str), 2):
            if i + 1 < len(hex_str) and tile_count < 4096:
                char1 = hex_str[i]
                char2 = hex_str[i + 1]
                
                if char1 in base64_chars and char2 in base64_chars:
                    # Convert two chars to tile ID
                    tile_id = base64_chars.index(char1) * 64 + base64_chars.index(char2)
                    
                    # Store as little-endian 2-byte value
                    import struct
                    struct.pack_into('<H', board_data, tile_count * 2, tile_id)
                    tile_count += 1
                else:
                    # Invalid character, use tile ID 0
                    import struct
                    struct.pack_into('<H', board_data, tile_count * 2, 0)
                    tile_count += 1
        
        logger.info(f"Decoded {tile_count} tiles from truncated hex")
        
        # Show first few tile IDs for verification
        first_tiles = []
        import struct
        for i in range(min(10, tile_count)):
            tile_id = struct.unpack('<H', board_data[i*2:i*2+2])[0]
            first_tiles.append(tile_id)
        logger.debug(f"First 10 tile IDs: {first_tiles}")
        
        return bytes(board_data)
    
    def _handle_board_download(self, data: bytes) -> None:
        """Handle packets during board download phase."""
        # During board download, we collect raw data between two PLO_BOARDPACKET markers
        
        # Check if this is the end marker
        if len(data) > 0 and data[0] - 32 == ServerToPlayer.PLO_BOARDPACKET:
            logger.info(f"Board download complete - collected {len(self._board_buffer)} bytes")
            self._downloading_board = False
            
            # Process the collected board data
            if len(self._board_buffer) >= 8192:  # Should have at least 4096 shorts
                # Create a fake packet with PLO_BOARDPACKET header + data
                board_packet = bytearray()
                board_packet.append(ServerToPlayer.PLO_BOARDPACKET + 32)  # Encoded packet ID
                board_packet.extend(self._board_buffer[:8192])  # Just the tile data
                
                # Queue for processing
                self._packet_queue.put(bytes(board_packet))
            else:
                logger.error(f"Board data too small: {len(self._board_buffer)} bytes")
                
            self._board_buffer.clear()
        else:
            # Accumulate raw data
            self._board_buffer.extend(data)
            logger.debug(f"Board download progress: {len(self._board_buffer)} bytes")
            
