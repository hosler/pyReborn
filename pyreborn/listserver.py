"""
pyreborn - ListServer Client
Handles authentication and server list retrieval from listserver.
"""

import sys
import struct
import zlib
import random
import json
from dataclasses import dataclass
from typing import Optional, List, Tuple

# Browser detection
IS_BROWSER = sys.platform == "emscripten"

# Conditional imports for native socket support
if not IS_BROWSER:
    import socket
    import select


# =============================================================================
# Listserver Packet IDs
# =============================================================================

class LSPacketID:
    """Listserver packet IDs."""
    # Client -> Listserver
    PLI_V1VER = 0
    PLI_SERVERLIST = 1
    PLI_V2VER = 4
    PLI_V2SERVERLISTRC = 5
    PLI_V2ENCRYPTKEYCL = 7

    # Listserver -> Client
    PLO_SVRLIST = 0
    PLO_STATUS = 2
    PLO_SITEURL = 3
    PLO_ERROR = 4
    PLO_UPGURL = 5


# =============================================================================
# Compression Types (same as game client)
# =============================================================================

class CompressionType:
    UNCOMPRESSED = 0x02
    ZLIB = 0x04
    BZ2 = 0x06


# =============================================================================
# Encryption (ENCRYPT_GEN_5)
# =============================================================================

class RebornEncryption:
    """ENCRYPT_GEN_5 implementation."""

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
# Gen5 Codec for Listserver
# =============================================================================

class Gen5Codec:
    """ENCRYPT_GEN_5: Partial encryption, dynamic compression."""

    def __init__(self, encryption_key: int = 0):
        self.encryption_key = encryption_key
        self.in_codec = RebornEncryption(encryption_key)
        self.out_codec = RebornEncryption(encryption_key)

    def send_packet(self, data: bytes) -> bytes:
        """Encode packet for sending (returns with length prefix)."""
        # Choose compression based on size
        if len(data) <= 55:
            compression_type = CompressionType.UNCOMPRESSED
            compressed_data = data
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
        """Decode received packet."""
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
                import bz2
                return bz2.decompress(decrypted)
            else:  # UNCOMPRESSED
                return decrypted
        except:
            return None


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class ServerEntry:
    """A server entry from the listserver."""
    name: str
    type_prefix: str  # "", "H ", "P ", "3 ", "U " (Bronze, Gold, G3D, Hidden)
    language: str
    description: str
    url: str
    version: str
    player_count: int
    ip: str
    port: int

    @property
    def display_name(self) -> str:
        """Server name with type prefix."""
        return f"{self.type_prefix}{self.name}"

    @property
    def address(self) -> Tuple[str, int]:
        """Server address as (ip, port) tuple."""
        return (self.ip, self.port)


@dataclass
class ListServerResponse:
    """Response from listserver login."""
    success: bool
    error: str = ""
    status: str = ""
    site_url: str = ""
    donate_url: str = ""
    servers: List[ServerEntry] = None

    def __post_init__(self):
        if self.servers is None:
            self.servers = []


# =============================================================================
# Packet Parser Helper
# =============================================================================

class PacketReader:
    """Helper for reading packet data."""

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def read_guchar(self) -> int:
        """Read GUChar (byte - 32)."""
        if self.pos >= len(self.data):
            return 0
        val = self.data[self.pos] - 32
        self.pos += 1
        return val

    def read_gchar(self) -> int:
        """Read GChar (signed byte - 32)."""
        val = self.read_guchar()
        if val >= 128:
            val -= 256
        return val

    def read_chars(self, length: int) -> str:
        """Read N bytes as string."""
        if self.pos + length > len(self.data):
            length = len(self.data) - self.pos
        result = self.data[self.pos:self.pos + length].decode('latin-1', errors='replace')
        self.pos += length
        return result

    def read_string(self) -> str:
        """Read length-prefixed string (GUChar length + chars)."""
        length = self.read_guchar()
        return self.read_chars(length)

    def bytes_left(self) -> int:
        """Remaining bytes to read."""
        return len(self.data) - self.pos


# =============================================================================
# ListServer Client
# =============================================================================

class ListServerClient:
    """
    Client for connecting to Reborn listserver.

    Usage:
        ls = ListServerClient("listserver.example.com", 14922)
        response = ls.login("username", "password")

        if response.success:
            for server in response.servers:
                print(f"{server.display_name}: {server.ip}:{server.port}")
        else:
            print(f"Error: {response.error}")
    """

    DEFAULT_PORT = 14922

    def __init__(self, host: str = "localhost", port: int = DEFAULT_PORT,
                 version: str = "G3D0311C"):
        """
        Create a new listserver client.

        Args:
            host: Listserver hostname or IP
            port: Listserver port (default 14922)
            version: Protocol version string (8 chars)
        """
        self.host = host
        self.port = port
        self.version = version

        self._socket: Optional[socket.socket] = None
        self._connected = False
        self._encryption_key = random.randint(0, 127)
        self._codec = Gen5Codec(self._encryption_key)
        self._first_packet = True
        self._recv_buffer = b""

    @property
    def connected(self) -> bool:
        """Check if connected to listserver."""
        return self._connected

    def connect(self) -> bool:
        """Connect to listserver. Returns True if successful."""
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(10.0)
            self._socket.connect((self.host, self.port))
            self._connected = True
            return True
        except Exception as e:
            print(f"ListServer connection failed: {e}")
            return False

    def disconnect(self):
        """Disconnect from listserver."""
        self._connected = False
        if self._socket:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
                self._socket.close()
            except:
                pass
            self._socket = None

    def _send_init_packet(self) -> bool:
        """Send PLI_V2ENCRYPTKEYCL to initialize encryption."""
        if not self._socket:
            return False

        try:
            # Build packet: PLI_V2ENCRYPTKEYCL + key + version (8 chars) + "newmain"
            packet = bytearray()
            packet.append(LSPacketID.PLI_V2ENCRYPTKEYCL + 32)  # Packet ID
            packet.append((self._encryption_key + 32) & 0xFF)  # Key
            packet.extend(self.version[:8].ljust(8).encode('ascii'))  # Version (8 bytes)
            packet.extend(b'newmain')  # Client type
            packet.append(ord('\n'))

            # Compress and send (Gen2 style - just zlib)
            compressed = zlib.compress(bytes(packet))
            length = struct.pack('>H', len(compressed))
            self._socket.send(length + compressed)
            return True
        except Exception as e:
            print(f"Failed to send init packet: {e}")
            return False

    def _send_login_packet(self, username: str, password: str) -> bool:
        """Send PLI_SERVERLIST with credentials."""
        if not self._socket:
            return False

        try:
            # Build packet: PLI_SERVERLIST + account_len + account + password_len + password
            packet = bytearray()
            packet.append(LSPacketID.PLI_SERVERLIST + 32)  # Packet ID
            packet.append((len(username) + 32) & 0xFF)  # Account length
            packet.extend(username.encode('ascii'))
            packet.append((len(password) + 32) & 0xFF)  # Password length
            packet.extend(password.encode('ascii'))
            packet.append(ord('\n'))

            # Send using Gen5 codec
            encrypted = self._codec.send_packet(bytes(packet))
            self._socket.send(encrypted)
            return True
        except Exception as e:
            print(f"Failed to send login packet: {e}")
            return False

    def _recv_packets(self, timeout: float = 5.0) -> List[Tuple[int, bytes]]:
        """Receive packets from listserver."""
        if not self._socket or not self._connected:
            return []

        packets = []
        end_time = timeout

        try:
            self._socket.settimeout(timeout)

            while True:
                # Receive data
                try:
                    ready, _, _ = select.select([self._socket], [], [], 0.1)
                    if not ready:
                        if packets:  # We have packets, return them
                            break
                        end_time -= 0.1
                        if end_time <= 0:
                            break
                        continue

                    chunk = self._socket.recv(65536)
                    if not chunk:
                        self._connected = False
                        break
                    self._recv_buffer += chunk
                except socket.timeout:
                    break
                except BlockingIOError:
                    break

                # Process complete packets
                while len(self._recv_buffer) >= 2:
                    length = struct.unpack('>H', self._recv_buffer[:2])[0]

                    if len(self._recv_buffer) < 2 + length:
                        break  # Incomplete packet

                    packet_data = self._recv_buffer[2:2 + length]
                    self._recv_buffer = self._recv_buffer[2 + length:]

                    # Decrypt/decompress
                    if self._first_packet:
                        try:
                            decrypted = zlib.decompress(packet_data)
                            self._first_packet = False
                        except:
                            decrypted = self._codec.recv_packet(packet_data)
                    else:
                        decrypted = self._codec.recv_packet(packet_data)

                    if not decrypted:
                        continue

                    # Parse packets from decompressed data
                    pos = 0
                    while pos < len(decrypted):
                        newline = decrypted.find(b'\n', pos)
                        if newline == -1:
                            break

                        packet_bytes = decrypted[pos:newline]
                        pos = newline + 1

                        if packet_bytes and len(packet_bytes) >= 1:
                            packet_id = packet_bytes[0] - 32
                            packet_body = packet_bytes[1:] if len(packet_bytes) > 1 else b""
                            packets.append((packet_id, packet_body))

        except Exception as e:
            print(f"Recv error: {e}")

        return packets

    def _parse_server_list(self, data: bytes) -> List[ServerEntry]:
        """Parse PLO_SVRLIST packet data."""
        servers = []
        reader = PacketReader(data)

        # First byte is server count
        server_count = reader.read_guchar()

        for _ in range(server_count):
            if reader.bytes_left() < 2:
                break

            # Read field count marker (should be 8)
            _ = reader.read_guchar()  # Field count

            # Server name (with type prefix)
            full_name = reader.read_string()

            # Extract type prefix (e.g., "H ", "P ", "3 ", "U ")
            type_prefix = ""
            name = full_name
            if len(full_name) >= 2 and full_name[1] == ' ':
                type_prefix = full_name[:2]
                name = full_name[2:]

            language = reader.read_string()
            description = reader.read_string()
            url = reader.read_string()
            version = reader.read_string()
            player_count_str = reader.read_string()
            ip = reader.read_string()
            port_str = reader.read_string()

            # Parse numeric values
            try:
                player_count = int(player_count_str) if player_count_str else 0
            except ValueError:
                player_count = 0

            try:
                port = int(port_str) if port_str else 14900
            except ValueError:
                port = 14900

            server = ServerEntry(
                name=name,
                type_prefix=type_prefix,
                language=language,
                description=description,
                url=url,
                version=version,
                player_count=player_count,
                ip=ip,
                port=port
            )
            servers.append(server)

        return servers

    def login(self, username: str, password: str, timeout: float = 10.0) -> ListServerResponse:
        """
        Login to listserver and retrieve server list.

        Args:
            username: Account name
            password: Account password
            timeout: Maximum time to wait for response (seconds)

        Returns:
            ListServerResponse with success status, servers, and messages
        """
        # Connect if not already connected
        if not self._connected:
            if not self.connect():
                return ListServerResponse(success=False, error="Failed to connect to listserver")

        # Send init packet (PLI_V2ENCRYPTKEYCL)
        if not self._send_init_packet():
            self.disconnect()
            return ListServerResponse(success=False, error="Failed to send init packet")

        # Send login packet (PLI_SERVERLIST)
        if not self._send_login_packet(username, password):
            self.disconnect()
            return ListServerResponse(success=False, error="Failed to send login packet")

        # Receive response packets
        packets = self._recv_packets(timeout)

        response = ListServerResponse(success=False)

        for packet_id, data in packets:
            if packet_id == LSPacketID.PLO_SVRLIST:
                response.servers = self._parse_server_list(data)
                response.success = True

            elif packet_id == LSPacketID.PLO_STATUS:
                response.status = data.decode('latin-1', errors='replace')

            elif packet_id == LSPacketID.PLO_SITEURL:
                response.site_url = data.decode('latin-1', errors='replace')

            elif packet_id == LSPacketID.PLO_UPGURL:
                response.donate_url = data.decode('latin-1', errors='replace')

            elif packet_id == LSPacketID.PLO_ERROR:
                response.error = data.decode('latin-1', errors='replace')
                response.success = False

        return response

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False


# =============================================================================
# WebSocket ListServer Client (for browser)
# =============================================================================

if IS_BROWSER:
    try:
        from pyscript import window
    except ImportError:
        from js import window

    class WebSocketListServerClient:
        """
        WebSocket-based listserver client for browser environments.
        Connects to game server through a WebSocket proxy.
        """

        DEFAULT_PORT = 14922

        def __init__(self, host: str = "localhost", port: int = DEFAULT_PORT,
                     version: str = "G3D0311C", proxy_url: str = None):
            """
            Create a new WebSocket listserver client.

            Args:
                host: Listserver hostname (target through proxy)
                port: Listserver port (default 14922)
                version: Protocol version string (8 chars)
                proxy_url: WebSocket proxy URL (e.g., "ws://localhost:14901")
            """
            self.host = host
            self.port = port
            self.version = version
            self.proxy_url = proxy_url

            self._ws = None
            self._connected = False
            self._tcp_connected = False
            self._encryption_key = random.randint(0, 127)
            self._codec = Gen5Codec(self._encryption_key)
            self._first_packet = True
            self._recv_buffer = b""
            self._received_packets = []

        @property
        def connected(self) -> bool:
            """Check if connected to listserver."""
            return self._connected and self._tcp_connected

        def connect(self) -> bool:
            """Connect to listserver via WebSocket proxy."""
            if not self.proxy_url:
                print("WebSocketListServerClient requires proxy_url")
                return False

            try:
                print(f"Creating WebSocket to: {self.proxy_url}")
                self._ws = window.WebSocket.new(self.proxy_url)
                self._ws.binaryType = "arraybuffer"
                print(f"WebSocket object created, readyState: {self._ws.readyState}")

                def on_open(event):
                    print("ListServer WebSocket connected!")
                    self._connected = True
                    # Send connection request to proxy
                    import json as json_mod
                    connect_msg = json_mod.dumps({"host": self.host, "port": self.port})
                    print(f"Sending connect message: {connect_msg}")
                    self._ws.send(connect_msg)

                def on_message(event):
                    # Check for proxy status messages
                    try:
                        if hasattr(event.data, 'byteLength'):
                            # Binary data from server
                            arr = window.Uint8Array.new(event.data)
                            data = bytes(arr)
                            self._recv_buffer += data
                            self._process_recv_buffer()
                        else:
                            # Text message (proxy status)
                            msg = str(event.data)
                            print(f"ListServer received text message: {msg}")
                            if msg.startswith('{'):
                                import json as json_mod
                                status = json_mod.loads(msg)
                                # Check for "type": "connected" (proxy format)
                                if status.get("type") == "connected":
                                    self._tcp_connected = True
                                    print("ListServer TCP connected through proxy")
                    except Exception as e:
                        print(f"ListServer WS message error: {e}")

                def on_close(event):
                    print("ListServer WebSocket closed")
                    self._connected = False
                    self._tcp_connected = False

                def on_error(event):
                    print(f"ListServer WebSocket error!")
                    self._connected = False

                self._ws.onopen = on_open
                self._ws.onmessage = on_message
                self._ws.onclose = on_close
                self._ws.onerror = on_error

                print("WebSocket callbacks set, returning True")
                return True
            except Exception as e:
                print(f"ListServer WebSocket connection failed: {e}")
                import traceback
                traceback.print_exc()
                return False

        def disconnect(self):
            """Disconnect from listserver."""
            self._connected = False
            self._tcp_connected = False
            if self._ws:
                try:
                    self._ws.close()
                except:
                    pass
                self._ws = None

        def _send_raw(self, data: bytes) -> bool:
            """Send raw bytes over WebSocket."""
            if not self._ws or not self._tcp_connected:
                return False
            try:
                arr = window.Uint8Array.new(len(data))
                for i, b in enumerate(data):
                    arr[i] = b
                self._ws.send(arr.buffer)
                return True
            except Exception as e:
                print(f"ListServer send error: {e}")
                return False

        def _send_init_packet(self) -> bool:
            """Send PLI_V2ENCRYPTKEYCL to initialize encryption."""
            try:
                # Build packet: PLI_V2ENCRYPTKEYCL + key + version (8 chars) + "newmain"
                packet = bytearray()
                packet.append(LSPacketID.PLI_V2ENCRYPTKEYCL + 32)
                packet.append((self._encryption_key + 32) & 0xFF)
                packet.extend(self.version[:8].ljust(8).encode('ascii'))
                packet.extend(b'newmain')
                packet.append(ord('\n'))

                # Compress and send (Gen2 style - just zlib)
                compressed = zlib.compress(bytes(packet))
                length = struct.pack('>H', len(compressed))
                return self._send_raw(length + compressed)
            except Exception as e:
                print(f"Failed to send init packet: {e}")
                return False

        def _send_login_packet(self, username: str, password: str) -> bool:
            """Send PLI_SERVERLIST with credentials."""
            try:
                # Build packet: PLI_SERVERLIST + account_len + account + password_len + password
                packet = bytearray()
                packet.append(LSPacketID.PLI_SERVERLIST + 32)
                packet.append((len(username) + 32) & 0xFF)
                packet.extend(username.encode('ascii'))
                packet.append((len(password) + 32) & 0xFF)
                packet.extend(password.encode('ascii'))
                packet.append(ord('\n'))

                # Send using Gen5 codec
                encrypted = self._codec.send_packet(bytes(packet))
                return self._send_raw(encrypted)
            except Exception as e:
                print(f"Failed to send login packet: {e}")
                return False

        def _process_recv_buffer(self):
            """Process received data and extract packets."""
            while len(self._recv_buffer) >= 2:
                length = struct.unpack('>H', self._recv_buffer[:2])[0]

                if len(self._recv_buffer) < 2 + length:
                    break  # Incomplete packet

                packet_data = self._recv_buffer[2:2 + length]
                self._recv_buffer = self._recv_buffer[2 + length:]

                # Decrypt/decompress
                if self._first_packet:
                    try:
                        decrypted = zlib.decompress(packet_data)
                        self._first_packet = False
                    except:
                        decrypted = self._codec.recv_packet(packet_data)
                else:
                    decrypted = self._codec.recv_packet(packet_data)

                if not decrypted:
                    continue

                # Parse packets from decompressed data
                pos = 0
                while pos < len(decrypted):
                    newline = decrypted.find(b'\n', pos)
                    if newline == -1:
                        break

                    packet_bytes = decrypted[pos:newline]
                    pos = newline + 1

                    if packet_bytes and len(packet_bytes) >= 1:
                        packet_id = packet_bytes[0] - 32
                        packet_body = packet_bytes[1:] if len(packet_bytes) > 1 else b""
                        self._received_packets.append((packet_id, packet_body))

        def _parse_server_list(self, data: bytes) -> List[ServerEntry]:
            """Parse PLO_SVRLIST packet data."""
            servers = []
            reader = PacketReader(data)

            # First byte is server count
            server_count = reader.read_guchar()

            for _ in range(server_count):
                if reader.bytes_left() < 2:
                    break

                # Read field count marker (should be 8)
                _ = reader.read_guchar()

                # Server name (with type prefix)
                full_name = reader.read_string()

                # Extract type prefix
                type_prefix = ""
                name = full_name
                if len(full_name) >= 2 and full_name[1] == ' ':
                    type_prefix = full_name[:2]
                    name = full_name[2:]

                language = reader.read_string()
                description = reader.read_string()
                url = reader.read_string()
                version = reader.read_string()
                player_count_str = reader.read_string()
                ip = reader.read_string()
                port_str = reader.read_string()

                try:
                    player_count = int(player_count_str) if player_count_str else 0
                except ValueError:
                    player_count = 0

                try:
                    port = int(port_str) if port_str else 14900
                except ValueError:
                    port = 14900

                server = ServerEntry(
                    name=name,
                    type_prefix=type_prefix,
                    language=language,
                    description=description,
                    url=url,
                    version=version,
                    player_count=player_count,
                    ip=ip,
                    port=port
                )
                servers.append(server)

            return servers

        def get_received_packets(self) -> List[Tuple[int, bytes]]:
            """Get and clear received packets."""
            packets = self._received_packets
            self._received_packets = []
            return packets

        def login(self, username: str, password: str, timeout: float = 10.0) -> ListServerResponse:
            """
            Login to listserver and retrieve server list.
            Note: In browser, this is non-blocking - use login_async() instead.
            """
            # For browser, we need to handle this differently
            # This is a simplified sync-ish version that may not work well
            response = ListServerResponse(success=False, error="Use login flow in async context")
            return response

        def __enter__(self):
            self.connect()
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.disconnect()
            return False


# =============================================================================
# Convenience Functions
# =============================================================================

def get_server_list(host: str, port: int, username: str, password: str,
                    version: str = "G3D0311C", proxy_url: str = None) -> ListServerResponse:
    """
    Quick helper to get server list from listserver.

    Args:
        host: Listserver hostname
        port: Listserver port
        username: Account name
        password: Account password
        version: Protocol version string
        proxy_url: WebSocket proxy URL (required in browser)

    Returns:
        ListServerResponse with success status and server list

    Usage:
        response = get_server_list("listserver.example.com", 14922, "user", "pass")
        if response.success:
            for server in response.servers:
                print(f"{server.name}: {server.ip}:{server.port}")
    """
    if IS_BROWSER:
        # In browser, need to use WebSocketListServerClient
        # But sync login doesn't work well - caller should use async flow
        with WebSocketListServerClient(host, port, version, proxy_url) as ls:
            return ls.login(username, password)
    else:
        with ListServerClient(host, port, version) as ls:
            return ls.login(username, password)


def connect_via_listserver(listserver_host: str, listserver_port: int,
                           username: str, password: str,
                           server_name: str = None,
                           version: str = "G3D0311C") -> Optional['Client']:
    """
    Connect to a game server via listserver authentication.

    Args:
        listserver_host: Listserver hostname
        listserver_port: Listserver port
        username: Account name
        password: Account password
        server_name: Name of server to connect to (or None for first available)
        version: Protocol version string

    Returns:
        Connected and authenticated Client, or None if failed

    Usage:
        client = connect_via_listserver(
            "listserver.example.com", 14922,
            "user", "pass",
            server_name="My Server"
        )
        if client:
            client.move(1, 0)
            client.disconnect()
    """
    from .client import Client

    # Get server list from listserver
    response = get_server_list(listserver_host, listserver_port, username, password, version)

    if not response.success:
        print(f"Listserver login failed: {response.error}")
        return None

    if not response.servers:
        print("No servers available")
        return None

    # Find the requested server
    target_server = None
    if server_name:
        for server in response.servers:
            if server.name.lower() == server_name.lower():
                target_server = server
                break
        if not target_server:
            print(f"Server '{server_name}' not found")
            return None
    else:
        # Use first available server
        target_server = response.servers[0]

    print(f"Connecting to {target_server.display_name} at {target_server.ip}:{target_server.port}")

    # Connect to game server
    # Map version string to client version
    client_version = "6.037"  # Default
    if version.startswith("GNW"):
        client_version = "2.22"
    elif version.startswith("G3D"):
        client_version = "6.037"

    client = Client(target_server.ip, target_server.port, client_version)

    if not client.connect():
        print(f"Failed to connect to game server")
        return None

    if not client.login(username, password):
        print(f"Failed to login to game server")
        client.disconnect()
        return None

    return client
