"""
pyreborn - Protocol layer
Handles socket connection, encryption, and packet framing.

Supports both TCP sockets (native Python) and WebSocket (browser via Pyodide).
"""

import sys
import struct
import zlib
import bz2
import random
import json
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Tuple, Callable

# Detect browser environment
IS_BROWSER = sys.platform == "emscripten"

# Only import socket/select for non-browser
if not IS_BROWSER:
    import socket
    import select


# =============================================================================
# Compression Types
# =============================================================================

class CompressionType:
    UNCOMPRESSED = 0x02
    ZLIB = 0x04
    BZ2 = 0x06


# =============================================================================
# Encryption (ENCRYPT_GEN_5)
# =============================================================================

class RebornEncryption:
    """ENCRYPT_GEN_5 implementation"""

    def __init__(self, key: int = 0):
        self.key = key
        self.iterator = 0x4A80B38
        self.limit = -1
        self.multiplier = 0x8088405

    def reset(self, key: int):
        self.key = key
        self.iterator = 0x4A80B38
        self.limit = -1

    def limit_from_type(self, compression_type: int):
        if compression_type == CompressionType.UNCOMPRESSED:
            self.limit = 0x0C
        elif compression_type == CompressionType.ZLIB:
            self.limit = 0x04
        elif compression_type == CompressionType.BZ2:
            self.limit = 0x04

    def encrypt(self, data: bytes) -> bytes:
        result = bytearray(data)

        if self.limit < 0:
            bytes_to_encrypt = len(data)
        elif self.limit == 0:
            return bytes(result)
        else:
            bytes_to_encrypt = min(len(data), self.limit * 4)

        for i in range(bytes_to_encrypt):
            if i % 4 == 0:
                if self.limit == 0:
                    break
                self.iterator = (self.iterator * self.multiplier + self.key) & 0xFFFFFFFF
                if self.limit > 0:
                    self.limit -= 1

            iterator_bytes = struct.pack('<I', self.iterator)
            result[i] ^= iterator_bytes[i % 4]

        return bytes(result)

    def decrypt(self, data: bytes) -> bytes:
        return self.encrypt(data)


# =============================================================================
# Gen5 Codec
# =============================================================================

class Gen5Codec:
    """ENCRYPT_GEN_5: Partial encryption, dynamic compression (2.22+)"""

    def __init__(self, encryption_key: int = 0):
        self.encryption_key = encryption_key
        self.in_codec = RebornEncryption(encryption_key)
        self.out_codec = RebornEncryption(encryption_key)

    def send_packet(self, data: bytes) -> bytes:
        """Encode packet for sending (returns with length prefix)"""
        # Choose compression based on size
        if len(data) <= 55:
            compression_type = CompressionType.UNCOMPRESSED
            compressed_data = data
        elif len(data) > 0x2000:
            compression_type = CompressionType.BZ2
            compressed_data = bz2.compress(data)
        else:
            compression_type = CompressionType.ZLIB
            compressed_data = zlib.compress(data)

        # Encrypt
        packet_codec = RebornEncryption(self.encryption_key)
        packet_codec.iterator = self.out_codec.iterator
        packet_codec.limit_from_type(compression_type)
        encrypted = packet_codec.encrypt(compressed_data)
        self.out_codec.iterator = packet_codec.iterator

        # Build packet with compression type
        packet = bytes([compression_type]) + encrypted
        return struct.pack('>H', len(packet)) + packet

    def recv_packet(self, data: bytes) -> Optional[bytes]:
        """Decode received packet"""
        if not data or len(data) == 0:
            return None

        compression_type = data[0]

        # Check for plain zlib (first response from server)
        if compression_type == 0x78:
            try:
                return zlib.decompress(data)
            except:
                return None

        encrypted_data = data[1:]

        if compression_type not in [CompressionType.UNCOMPRESSED,
                                   CompressionType.ZLIB,
                                   CompressionType.BZ2]:
            return None

        # Decrypt
        packet_codec = RebornEncryption(self.encryption_key)
        packet_codec.iterator = self.in_codec.iterator
        packet_codec.limit_from_type(compression_type)
        decrypted = packet_codec.decrypt(encrypted_data)
        self.in_codec.iterator = packet_codec.iterator

        # Decompress
        try:
            if compression_type == CompressionType.ZLIB:
                return zlib.decompress(decrypted)
            elif compression_type == CompressionType.BZ2:
                return bz2.decompress(decrypted)
            else:  # UNCOMPRESSED
                return decrypted
        except:
            return None


# =============================================================================
# Version Configuration
# =============================================================================

class ClientType(Enum):
    TYPE_CLIENT = 0
    TYPE_RC = 1       # Remote Control
    TYPE_NC = 3       # NPC Control
    TYPE_CLIENT2 = 4
    TYPE_CLIENT3 = 5
    TYPE_RC2 = 6      # Alt RC version


@dataclass
class VersionConfig:
    name: str
    protocol_string: str  # 8-byte protocol version
    build_string: Optional[str]
    client_type: ClientType
    sends_build: bool = False


VERSIONS = {
    "2.22": VersionConfig(
        name="2.22",
        protocol_string="GNW03014",
        build_string="356",
        client_type=ClientType.TYPE_CLIENT3,
        sends_build=True
    ),
    "6.037": VersionConfig(
        name="6.037",
        protocol_string="G3D0311C",
        build_string=None,
        client_type=ClientType.TYPE_CLIENT3,
        sends_build=False
    ),
    "6.037_linux": VersionConfig(
        name="6.037 (Linux)",
        protocol_string="G3D0511C",
        build_string=None,
        client_type=ClientType.TYPE_CLIENT3,
        sends_build=False
    )
}


# =============================================================================
# Protocol - Main Connection Handler
# =============================================================================

class Protocol:
    """Low-level protocol: socket + encryption + framing"""

    def __init__(self, host: str, port: int, version: str = "2.22"):
        self.host = host
        self.port = port
        self.socket: Optional[socket.socket] = None
        self.connected = False

        # Encryption
        self.encryption_key = random.randint(0, 127)
        self.codec = Gen5Codec(self.encryption_key)
        self.first_packet = True  # First response is just zlib compressed

        # Version config
        self.version = VERSIONS.get(version, VERSIONS["2.22"])

        # Client type override (for RC/NC connections)
        self.client_type_override: Optional[ClientType] = None

        # Receive buffer
        self.recv_buffer = b""

        # Raw data mode (for level boards)
        self.raw_data_expected = 0
        self.raw_data_buffer = b""

    def connect(self) -> bool:
        """Connect to server"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(10.0)
            self.socket.connect((self.host, self.port))
            self.socket.setblocking(False)
            self.connected = True
            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            return False

    def disconnect(self):
        """Disconnect from server"""
        self.connected = False
        if self.socket:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
                self.socket.close()
            except:
                pass
            self.socket = None

    def send_login(self, username: str, password: str) -> bool:
        """Send login packet (special: zlib compressed, not encrypted)"""
        if not self.socket:
            return False

        try:
            packet = bytearray()

            # Client type + 32 (use override if set, for RC/NC connections)
            client_type = self.client_type_override or self.version.client_type
            packet.append((client_type.value + 32) & 0xFF)

            # Encryption key + 32
            packet.append((self.encryption_key + 32) & 0xFF)

            # Protocol version (8 bytes)
            packet.extend(self.version.protocol_string.encode('ascii'))

            # Account length + account
            packet.append((len(username) + 32) & 0xFF)
            packet.extend(username.encode('ascii'))

            # Password length + password
            packet.append((len(password) + 32) & 0xFF)
            packet.extend(password.encode('ascii'))

            # Build string (if version sends it)
            if self.version.sends_build and self.version.build_string:
                packet.append((len(self.version.build_string) + 32) & 0xFF)
                packet.extend(self.version.build_string.encode('ascii'))

            # Client info
            packet.extend(b'linux,,,,,pyreborn')

            # Compress with zlib and send with length prefix
            compressed = zlib.compress(bytes(packet))
            length = struct.pack('>H', len(compressed))
            self.socket.setblocking(True)
            self.socket.send(length + compressed)
            self.socket.setblocking(False)
            return True

        except Exception as e:
            print(f"Login send failed: {e}")
            return False

    def send_packet(self, packet_id: int, data: bytes = b"") -> bool:
        """Send encrypted packet to server"""
        if not self.socket or not self.connected:
            return False

        try:
            # Build packet: packet_id + 32, then data, then newline
            packet = bytes([packet_id + 32]) + data + b'\n'

            # Encrypt and get length-prefixed result
            encrypted = self.codec.send_packet(packet)

            self.socket.setblocking(True)
            self.socket.send(encrypted)
            self.socket.setblocking(False)
            return True

        except Exception as e:
            print(f"Send failed: {e}")
            return False

    def recv_packets(self, timeout: float = 0.01) -> List[Tuple[int, bytes]]:
        """
        Receive and decode packets (non-blocking).
        Returns list of (packet_id, data) tuples.
        """
        if not self.socket or not self.connected:
            return []

        packets = []

        try:
            # Check if data available
            ready, _, _ = select.select([self.socket], [], [], timeout)
            if not ready:
                return []

            # Receive available data
            self.socket.setblocking(False)
            try:
                chunk = self.socket.recv(65536)
                if not chunk:
                    self.connected = False
                    return []
                self.recv_buffer += chunk
            except BlockingIOError:
                pass
            except Exception as e:
                self.connected = False
                return []

            # Handle raw data mode (after PLO_RAWDATA)
            if self.raw_data_expected > 0:
                bytes_needed = self.raw_data_expected - len(self.raw_data_buffer)
                bytes_available = min(bytes_needed, len(self.recv_buffer))
                if bytes_available > 0:
                    self.raw_data_buffer += self.recv_buffer[:bytes_available]
                    self.recv_buffer = self.recv_buffer[bytes_available:]

                # Check if we have all raw data
                if len(self.raw_data_buffer) >= self.raw_data_expected:
                    # Emit as PLO_BOARDPACKET (101)
                    packets.append((101, self.raw_data_buffer[:self.raw_data_expected]))
                    self.raw_data_buffer = b""
                    self.raw_data_expected = 0

            # Process complete packets from buffer
            while len(self.recv_buffer) >= 2:
                # Read length prefix
                length = struct.unpack('>H', self.recv_buffer[:2])[0]

                if len(self.recv_buffer) < 2 + length:
                    break  # Incomplete packet

                # Extract packet data
                packet_data = self.recv_buffer[2:2 + length]
                self.recv_buffer = self.recv_buffer[2 + length:]

                # Decrypt/decompress
                if self.first_packet:
                    # First packet is just zlib compressed
                    try:
                        decrypted = zlib.decompress(packet_data)
                        self.first_packet = False
                    except:
                        decrypted = self.codec.recv_packet(packet_data)
                else:
                    decrypted = self.codec.recv_packet(packet_data)

                if not decrypted:
                    continue

                # Parse packets from decompressed data
                # Handle PLO_RAWDATA specially - the next N bytes are a raw packet
                pos = 0
                while pos < len(decrypted):
                    if pos >= len(decrypted):
                        break

                    # Check if we're expecting raw data from previous PLO_RAWDATA
                    if self.raw_data_expected > 0:
                        # Read exactly raw_data_expected bytes
                        if pos + self.raw_data_expected <= len(decrypted):
                            raw_packet = decrypted[pos:pos + self.raw_data_expected]
                            pos += self.raw_data_expected
                            self.raw_data_expected = 0

                            # Parse the raw packet (first byte is packet ID)
                            if len(raw_packet) >= 1:
                                raw_id = raw_packet[0] - 32
                                raw_body = raw_packet[1:] if len(raw_packet) > 1 else b""
                                # Strip trailing newline if present
                                if raw_body and raw_body[-1:] == b'\n':
                                    raw_body = raw_body[:-1]
                                packets.append((raw_id, raw_body))
                        else:
                            # Not enough data yet, save remainder
                            self.raw_data_buffer = decrypted[pos:]
                            break
                        continue

                    # Normal packet: read to newline
                    newline = decrypted.find(b'\n', pos)
                    if newline == -1:
                        break

                    packet_bytes = decrypted[pos:newline]
                    pos = newline + 1

                    if packet_bytes and len(packet_bytes) >= 1:
                        packet_id = packet_bytes[0] - 32
                        packet_body = packet_bytes[1:] if len(packet_bytes) > 1 else b""

                        # Check for PLO_RAWDATA (100) - next packet is raw bytes
                        if packet_id == 100 and len(packet_body) >= 3:
                            b1 = packet_body[0] - 32
                            b2 = packet_body[1] - 32
                            b3 = packet_body[2] - 32
                            raw_size = (b1 << 14) | (b2 << 7) | b3
                            self.raw_data_expected = raw_size

                        packets.append((packet_id, packet_body))

        except Exception as e:
            print(f"Recv error: {e}")

        return packets


# =============================================================================
# WebSocket Protocol (for browser/Pyodide)
# =============================================================================

class WebSocketProtocol:
    """
    WebSocket-based protocol for browser environments.

    Connects to a WebSocket proxy that bridges to the Reborn TCP server.
    Has the same interface as Protocol for drop-in replacement.

    Usage:
        # In browser, connect via proxy:
        protocol = WebSocketProtocol("ws://localhost:14901", "reborn.server.com", 14900)
        protocol.connect()  # Connects to proxy, which connects to Reborn server
        protocol.send_login(username, password)
        packets = protocol.recv_packets()
    """

    def __init__(self, proxy_url: str, host: str, port: int, version: str = "6.037"):
        """
        Create a WebSocket protocol.

        Args:
            proxy_url: WebSocket URL of the proxy (e.g., ws://localhost:14901)
            host: Reborn server hostname (proxy will connect to this)
            port: Reborn server port
            version: Protocol version
        """
        self.proxy_url = proxy_url
        self.host = host
        self.port = port

        self.ws = None
        self.connected = False
        self._tcp_connected = False

        # Encryption (same as TCP Protocol)
        self.encryption_key = random.randint(0, 127)
        self.codec = Gen5Codec(self.encryption_key)
        self.first_packet = True

        # Version config
        self.version = VERSIONS.get(version, VERSIONS["6.037"])
        self.client_type_override: Optional[ClientType] = None

        # Receive buffer and packet queue
        self.recv_buffer = b""
        self.raw_data_expected = 0
        self.raw_data_buffer = b""
        self.pending_packets: List[Tuple[int, bytes]] = []

        # Callbacks
        self.on_connect: Optional[Callable] = None
        self.on_disconnect: Optional[Callable] = None

    def connect(self) -> bool:
        """Connect to the WebSocket proxy."""
        if not IS_BROWSER:
            print("WebSocketProtocol requires browser environment")
            return False

        try:
            from pyscript import window
        except ImportError:
            try:
                from js import window
            except ImportError:
                print("Cannot import browser APIs")
                return False

        try:
            self.ws = window.WebSocket.new(self.proxy_url)
            self.ws.binaryType = "arraybuffer"

            self.ws.onopen = self._on_open
            self.ws.onclose = self._on_close
            self.ws.onerror = self._on_error
            self.ws.onmessage = self._on_message

            return True
        except Exception as e:
            print(f"WebSocket connection failed: {e}")
            return False

    def _on_open(self, event):
        """Handle WebSocket open."""
        print(f"Connected to proxy: {self.proxy_url}")
        self.connected = True

        # Tell proxy which Reborn server to connect to
        connect_msg = json.dumps({
            "host": self.host,
            "port": self.port
        })
        self.ws.send(connect_msg)

        if self.on_connect:
            self.on_connect()

    def _on_close(self, event):
        """Handle WebSocket close."""
        print("WebSocket closed")
        self.connected = False
        self._tcp_connected = False
        if self.on_disconnect:
            self.on_disconnect()

    def _on_error(self, event):
        """Handle WebSocket error."""
        print("WebSocket error")

    def _on_message(self, event):
        """Handle incoming WebSocket message."""
        try:
            try:
                from pyscript import window
            except ImportError:
                from js import window
            arr = window.Uint8Array.new(event.data)
            data = bytes(arr)

            # Check for JSON message from proxy
            if not self._tcp_connected:
                try:
                    msg = json.loads(data.decode('utf-8'))
                    if msg.get("type") == "connected":
                        print(f"Proxy connected to {msg.get('host')}:{msg.get('port')}")
                        self._tcp_connected = True
                        return
                    elif msg.get("type") == "error":
                        print(f"Proxy error: {msg.get('message')}")
                        return
                    elif msg.get("type") == "disconnected":
                        self._tcp_connected = False
                        return
                except (json.JSONDecodeError, UnicodeDecodeError):
                    self._tcp_connected = True

            # Add to receive buffer
            self.recv_buffer += data
            self._process_buffer()

        except Exception as e:
            print(f"Message error: {e}")
            import traceback
            traceback.print_exc()

    def _process_buffer(self):
        """Process received data and extract packets."""
        # Handle raw data mode
        if self.raw_data_expected > 0:
            bytes_needed = self.raw_data_expected - len(self.raw_data_buffer)
            bytes_available = min(bytes_needed, len(self.recv_buffer))
            if bytes_available > 0:
                self.raw_data_buffer += self.recv_buffer[:bytes_available]
                self.recv_buffer = self.recv_buffer[bytes_available:]

            if len(self.raw_data_buffer) >= self.raw_data_expected:
                self.pending_packets.append((101, self.raw_data_buffer[:self.raw_data_expected]))
                self.raw_data_buffer = b""
                self.raw_data_expected = 0

        # Process framed packets
        while len(self.recv_buffer) >= 2:
            length = struct.unpack('>H', self.recv_buffer[:2])[0]

            if len(self.recv_buffer) < 2 + length:
                break

            packet_data = self.recv_buffer[2:2 + length]
            self.recv_buffer = self.recv_buffer[2 + length:]

            # Decrypt/decompress
            if self.first_packet:
                try:
                    decrypted = zlib.decompress(packet_data)
                    self.first_packet = False
                except:
                    decrypted = self.codec.recv_packet(packet_data)
            else:
                decrypted = self.codec.recv_packet(packet_data)

            if not decrypted:
                continue

            self._parse_packets(decrypted)

    def _parse_packets(self, decrypted: bytes):
        """Parse packets from decrypted data."""
        pos = 0
        while pos < len(decrypted):
            if self.raw_data_expected > 0:
                if pos + self.raw_data_expected <= len(decrypted):
                    raw_packet = decrypted[pos:pos + self.raw_data_expected]
                    pos += self.raw_data_expected
                    self.raw_data_expected = 0

                    if len(raw_packet) >= 1:
                        raw_id = raw_packet[0] - 32
                        raw_body = raw_packet[1:] if len(raw_packet) > 1 else b""
                        if raw_body and raw_body[-1:] == b'\n':
                            raw_body = raw_body[:-1]
                        self.pending_packets.append((raw_id, raw_body))
                else:
                    self.raw_data_buffer = decrypted[pos:]
                    break
                continue

            newline = decrypted.find(b'\n', pos)
            if newline == -1:
                break

            packet_bytes = decrypted[pos:newline]
            pos = newline + 1

            if packet_bytes and len(packet_bytes) >= 1:
                packet_id = packet_bytes[0] - 32
                packet_body = packet_bytes[1:] if len(packet_bytes) > 1 else b""

                if packet_id == 100 and len(packet_body) >= 3:
                    b1 = packet_body[0] - 32
                    b2 = packet_body[1] - 32
                    b3 = packet_body[2] - 32
                    self.raw_data_expected = (b1 << 14) | (b2 << 7) | b3

                self.pending_packets.append((packet_id, packet_body))

    def disconnect(self):
        """Disconnect from proxy."""
        self.connected = False
        self._tcp_connected = False
        if self.ws:
            try:
                self.ws.close()
            except:
                pass
            self.ws = None

    def send_login(self, username: str, password: str) -> bool:
        """Send login packet."""
        if not self.ws or not self._tcp_connected:
            return False

        try:
            packet = bytearray()

            client_type = self.client_type_override or self.version.client_type
            packet.append((client_type.value + 32) & 0xFF)
            packet.append((self.encryption_key + 32) & 0xFF)
            packet.extend(self.version.protocol_string.encode('ascii'))
            packet.append((len(username) + 32) & 0xFF)
            packet.extend(username.encode('ascii'))
            packet.append((len(password) + 32) & 0xFF)
            packet.extend(password.encode('ascii'))

            if self.version.sends_build and self.version.build_string:
                packet.append((len(self.version.build_string) + 32) & 0xFF)
                packet.extend(self.version.build_string.encode('ascii'))

            packet.extend(b'emscripten,,,,,pyreborn')

            compressed = zlib.compress(bytes(packet))
            length = struct.pack('>H', len(compressed))
            self._send_bytes(length + compressed)
            return True

        except Exception as e:
            print(f"Login failed: {e}")
            return False

    def send_packet(self, packet_id: int, data: bytes = b"") -> bool:
        """Send encrypted packet."""
        if not self.ws or not self._tcp_connected:
            return False

        try:
            packet = bytes([packet_id + 32]) + data + b'\n'
            encrypted = self.codec.send_packet(packet)
            self._send_bytes(encrypted)
            return True
        except Exception as e:
            print(f"Send failed: {e}")
            return False

    def _send_bytes(self, data: bytes):
        """Send bytes over WebSocket."""
        try:
            from pyscript import window
        except ImportError:
            from js import window
        arr = window.Uint8Array.new(len(data))
        for i, b in enumerate(data):
            arr[i] = b
        self.ws.send(arr.buffer)

    def recv_packets(self, timeout: float = 0.0) -> List[Tuple[int, bytes]]:
        """Get received packets (async - just returns pending packets)."""
        packets = self.pending_packets[:]
        self.pending_packets.clear()
        return packets
