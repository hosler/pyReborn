"""
pyreborn - Protocol layer
Handles socket connection, encryption, and packet framing.

Supports both TCP sockets (native Python) and WebSocket (browser via Pyodide).
Uses the shared reborn_protocol library for core encryption and codec.
"""

import sys
import struct
import zlib
import random
import json
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Tuple, Callable, Dict

# Import shared protocol components
from reborn_protocol import (
    Gen5Codec,
    Gen4Codec,
    Gen3Codec,
    Gen2Codec,
)

# Detect browser environment
IS_BROWSER = sys.platform == "emscripten"

MAX_DECOMPRESSED_SIZE = 8 * 1024 * 1024


class DecompressionLimitError(Exception):
    """Raised when an inbound compressed frame exceeds the size limit."""


def _decompress_bounded(data: bytes) -> bytes:
    decompressor = zlib.decompressobj()
    result = decompressor.decompress(data, max_length=MAX_DECOMPRESSED_SIZE)
    if decompressor.unconsumed_tail:
        raise DecompressionLimitError(
            f"decompressed frame exceeds {MAX_DECOMPRESSED_SIZE} bytes")
    if not decompressor.eof:
        raise zlib.error("incomplete or truncated compressed frame")
    return result

# Only import socket/select for non-browser
if not IS_BROWSER:
    import socket
    import select


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
    # Encryption generation this client-type/version pair negotiates.
    # Authoritative mapping (GServer PlayerClient.cpp handleLogin):
    #   TYPE_CLIENT  + known version, no key  -> GEN_2
    #   TYPE_CLIENT  + enc key (1.41 - 2.18)  -> GEN_3
    #   TYPE_CLIENT2 (2.19 - 2.21, 3.x)       -> GEN_4
    #   TYPE_CLIENT3 (2.22+)                  -> GEN_5
    encryption_gen: int = 5


VERSIONS = {
    "1.411": VersionConfig(
        name="1.411",
        protocol_string="GNW13110",
        build_string=None,
        client_type=ClientType.TYPE_CLIENT,
        sends_build=False,
        encryption_gen=3,   # "1.41 registers itself as PLTYPE_CLIENT, but does
                            # include an encryption key" -> server flips to GEN_3
    ),
    "2.17": VersionConfig(
        name="2.17",
        protocol_string="GNW22122",
        build_string=None,
        client_type=ClientType.TYPE_CLIENT,
        sends_build=False,
        encryption_gen=3,   # 1.41 - 2.18 client encryption era
    ),
    "2.21": VersionConfig(
        name="2.21",
        protocol_string="GNW01113",
        build_string=None,
        client_type=ClientType.TYPE_CLIENT2,
        sends_build=False,
        encryption_gen=4,   # PLTYPE_CLIENT2 -> ENCRYPT_GEN_4 (bz2 only)
    ),
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
        self.connect_timeout = 30.0

        # Version config
        self.version = VERSIONS.get(version, VERSIONS["2.22"])

        # Encryption
        self.encryption_key = random.randint(0, 127)
        # Encryption generation, from the version entry. GEN_5 is the modern
        # client/RC codec; GEN_4 = 2.19-2.21/3.x (bz2-only), GEN_3 = 1.41-2.18
        # (client-side byte insertion + zlib). NC connections use GEN_2 (zlib
        # framing, no per-packet encryption and no encryption-key byte in the
        # login packet) - see use_gen2().
        self.gen = self.version.encryption_gen
        # Set only when send_login() constructs this connection's handshake.
        # Probe reporting reads this instead of the mutable codec setting.
        self.last_handshake_gen: Optional[int] = None
        if self.gen == 3:
            self.codec = Gen3Codec(self.encryption_key)
        elif self.gen == 4:
            self.codec = Gen4Codec(self.encryption_key)
        else:
            self.codec = Gen5Codec(self.encryption_key)
        self.first_packet = True  # First response is just zlib compressed

        # Client type override (for RC/NC connections)
        self.client_type_override: Optional[ClientType] = None

        # Receive buffer
        self.recv_buffer = b""

        # Raw data mode (for level boards)
        self.raw_data_expected = 0
        self.raw_data_buffer = b""

        # Optional outgoing-packet recorder for the coverage harness:
        # packet_id -> list of payloads sent (after the id byte, before newline).
        self.sent_payloads: Optional[Dict[int, List[bytes]]] = None

        # Serializes the outbound critical section (codec encrypt + sendall).
        # The GEN_3/4/5 codecs carry a STATEFUL cipher iterator whose byte order
        # must match the order bytes hit the wire. Two threads each doing
        # "encrypt (advance iterator) ... sendall" can interleave so the wire
        # order != encrypt order, which desyncs the server's decrypt stream. The
        # server then reads garbage packet/prop ids; a player-prop id the server
        # can't map (>=83) makes GServer-v2's constructPropFor throw and the
        # whole process SIGABRTs (remote DoS). One lock => sends are atomic and
        # can never corrupt the stream, no matter how many threads call in.
        self._send_lock = threading.Lock()

    def connect(self) -> bool:
        """Connect to server"""
        try:
            # create_connection resolves the host via getaddrinfo, so IPv6
            # literals/hosts work as well as legacy IPv4.
            self.socket = socket.create_connection(
                (self.host, self.port), timeout=self.connect_timeout)
            self.socket.setblocking(False)
            self.connected = True

            # Reset per-session decode state. Without this, reconnecting on
            # the same Protocol instance (e.g. after disconnect()) resumes
            # decrypting with a stale codec/iterator, leftover framed bytes
            # in recv_buffer, and a leftover raw-data deficit from the
            # previous connection.
            self.encryption_key = random.randint(0, 127)
            if self.gen == 2:
                self.codec = Gen2Codec()
            elif self.gen == 3:
                self.codec = Gen3Codec(self.encryption_key)
            elif self.gen == 4:
                self.codec = Gen4Codec(self.encryption_key)
            else:
                self.codec = Gen5Codec(self.encryption_key)
            self.first_packet = True
            self.recv_buffer = b""
            self.raw_data_expected = 0
            self.raw_data_buffer = b""
            self.last_handshake_gen = None

            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            if self.socket:
                try:
                    self.socket.close()
                except Exception:
                    pass
            self.socket = None
            return False

    def use_gen2(self):
        """
        Switch this connection to ENCRYPT_GEN_2 framing (used by NC clients).

        GEN_2 bundles are zlib-compressed with a 2-byte length prefix and carry
        no per-packet encryption or compression-type byte. The login packet also
        omits the encryption-key byte (the server only reads it for gen > 3).
        Call before send_login().
        """
        self.gen = 2
        self.codec = Gen2Codec()

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
            self.last_handshake_gen = self.gen
            packet = bytearray()

            # Client type + 32 (use override if set, for RC/NC connections)
            client_type = self.client_type_override or self.version.client_type
            packet.append((client_type.value + 32) & 0xFF)

            # Encryption key + 32. GEN_2 (NC) logins do not include this byte.
            # GEN_3 clients DO send it: "1.41 registers itself as PLTYPE_CLIENT,
            # but does include an encryption key" - the key byte at the version
            # position is exactly how the server detects GEN_3 (handleLogin:
            # unknown 8-char string -> setGen(GEN_3) -> re-read key + version).
            if self.gen >= 3:
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
            with self._send_lock:
                self.socket.setblocking(True)
                self.socket.sendall(length + compressed)
                self.socket.setblocking(False)
            return True

        except Exception as e:
            print(f"Login send failed: {e}")
            return False

    def send_packet(self, packet_id: int, data: bytes = b"",
                    append_newline: bool = True) -> bool:
        """Send encrypted packet to server.

        append_newline=False is for packets sent inside PLI_RAWDATA framing
        (the server reads exactly the declared byte count instead of scanning
        for '\\n', and never strips a trailing newline from raw blocks -
        RemoveNewlinesFromRawPacket is unset in GServer - so including one
        would corrupt the payload, e.g. append a stray byte to file uploads).
        """
        if not self.socket or not self.connected:
            return False

        try:
            # Build packet: packet_id + 32, then data, then newline
            packet = bytes([packet_id + 32]) + data + (b'\n' if append_newline else b'')

            # Record the outgoing payload (coverage harness compares this to the
            # server's logged view of what it received - a true wire round-trip).
            if self.sent_payloads is not None:
                self.sent_payloads.setdefault(packet_id, []).append(data)

            # Encrypt + frame + send as one atomic unit: the codec mutates a
            # stateful cipher iterator, so a concurrent send must not slip
            # between encrypt and sendall (that reorders the wire vs the cipher
            # stream and desyncs the server - see _send_lock).
            with self._send_lock:
                encrypted = self.codec.send_packet(packet)
                self.socket.setblocking(True)
                self.socket.sendall(encrypted)
                self.socket.setblocking(False)
            return True

        except Exception as e:
            print(f"Send failed: {e}")
            self.connected = False
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

            # NOTE: raw-data (PLO_RAWDATA) continuation is handled entirely
            # inside the decrypted-bundle loop below, not here. self.recv_buffer
            # at this point still holds length-prefixed, encrypted/compressed
            # frames - satisfying a raw-data deficit from it (as a previous
            # version of this method did) would eat frame headers and ciphertext
            # as if they were the raw payload, desyncing the whole session the
            # moment a raw block doesn't fit in one bundle. The deficit
            # (self.raw_data_expected/self.raw_data_buffer) is only ever
            # satisfied from DECRYPTED bundles, carrying over across
            # recv_packets() calls if needed.

            # Process complete packets from buffer
            while len(self.recv_buffer) >= 2:
                # Read length prefix
                length = struct.unpack('>H', self.recv_buffer[:2])[0]

                if len(self.recv_buffer) < 2 + length:
                    break  # Incomplete packet

                # Extract packet data
                packet_data = self.recv_buffer[2:2 + length]
                self.recv_buffer = self.recv_buffer[2 + length:]

                # Decrypt/decompress. first_packet is cleared unconditionally
                # after this first attempt (even if zlib fails and we fall
                # back to the codec) - otherwise a non-zlib first bundle would
                # make every later packet pay a zlib.decompress exception.
                if self.first_packet:
                    self.first_packet = False
                    try:
                        decrypted = _decompress_bounded(packet_data)
                    except DecompressionLimitError as e:
                        print(f"Dropping oversized first packet: {e}")
                        continue
                    except Exception:
                        decrypted = self.codec.recv_packet(packet_data)
                else:
                    decrypted = self.codec.recv_packet(packet_data)

                if not decrypted:
                    continue

                # Parse packets from decompressed data
                # Handle PLO_RAWDATA specially - the next N bytes are a raw packet
                pos = 0
                while pos < len(decrypted):
                    # Check if we're expecting (more) raw data from a previous
                    # PLO_RAWDATA header, possibly carried over from an earlier
                    # decrypted bundle (self.raw_data_buffer holds what we've
                    # collected so far; self.raw_data_expected is the total
                    # size the header declared).
                    if self.raw_data_expected > 0:
                        needed = self.raw_data_expected - len(self.raw_data_buffer)
                        take = min(needed, len(decrypted) - pos)
                        self.raw_data_buffer += decrypted[pos:pos + take]
                        pos += take

                        if len(self.raw_data_buffer) < self.raw_data_expected:
                            # Still short - wait for the next decrypted bundle.
                            break

                        raw_packet = self.raw_data_buffer
                        self.raw_data_buffer = b""
                        self.raw_data_expected = 0

                        # Raw data format: [packet_id+32][data...][newline]
                        # Extract packet_id and strip header/trailer
                        if len(raw_packet) >= 2:
                            packet_id = raw_packet[0] - 32
                            # Strip packet ID byte and trailing newline
                            packet_body = raw_packet[1:]
                            if packet_body and packet_body[-1:] == b'\n':
                                packet_body = packet_body[:-1]
                            packets.append((packet_id, packet_body))
                        else:
                            # Emit as PLO_BOARDPACKET (101) with raw tile data
                            packets.append((101, raw_packet))
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
                            raw_size = max(0, raw_size)
                            self.raw_data_expected = raw_size
                            self.raw_data_buffer = b""

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
        self.last_handshake_gen: Optional[int] = None

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

        # Reset per-session decode state (see Protocol.connect) so a
        # reconnect on the same instance doesn't resume decrypting with a
        # stale codec/iterator, leftover buffered bytes, or a leftover
        # raw-data deficit from the previous connection.
        self.encryption_key = random.randint(0, 127)
        self.codec = Gen5Codec(self.encryption_key)
        self.first_packet = True
        self.recv_buffer = b""
        self.raw_data_expected = 0
        self.raw_data_buffer = b""
        self.pending_packets = []
        self._tcp_connected = False
        self.last_handshake_gen = None

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
        # NOTE: raw-data (PLO_RAWDATA) continuation is handled entirely
        # inside _parse_packets on DECRYPTED bundles, not here - self.recv_buffer
        # at this point still holds length-prefixed, encrypted/compressed
        # frames (mirrors the fix in Protocol.recv_packets; see that method's
        # comment for why consuming from the pre-decryption buffer desyncs
        # the session).

        # Process framed packets
        while len(self.recv_buffer) >= 2:
            length = struct.unpack('>H', self.recv_buffer[:2])[0]

            if len(self.recv_buffer) < 2 + length:
                break

            packet_data = self.recv_buffer[2:2 + length]
            self.recv_buffer = self.recv_buffer[2 + length:]

            # Decrypt/decompress. first_packet is cleared unconditionally
            # after this first attempt - see Protocol.recv_packets.
            if self.first_packet:
                self.first_packet = False
                try:
                    decrypted = _decompress_bounded(packet_data)
                except DecompressionLimitError as e:
                    print(f"Dropping oversized first packet: {e}")
                    continue
                except Exception:
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
            # Check if we're expecting (more) raw data from a previous
            # PLO_RAWDATA header, possibly carried over from an earlier
            # decrypted bundle (self.raw_data_buffer holds what we've
            # collected so far; self.raw_data_expected is the declared total).
            if self.raw_data_expected > 0:
                needed = self.raw_data_expected - len(self.raw_data_buffer)
                take = min(needed, len(decrypted) - pos)
                self.raw_data_buffer += decrypted[pos:pos + take]
                pos += take

                if len(self.raw_data_buffer) < self.raw_data_expected:
                    # Still short - wait for the next decrypted bundle.
                    break

                raw_packet = self.raw_data_buffer
                self.raw_data_buffer = b""
                self.raw_data_expected = 0

                # Raw data format: [packet_id+32][data...][newline] - strip
                # the id byte and trailing newline like the normal-packet
                # path below, instead of emitting the whole blob as id 101.
                if len(raw_packet) >= 2:
                    raw_id = raw_packet[0] - 32
                    raw_body = raw_packet[1:]
                    if raw_body and raw_body[-1:] == b'\n':
                        raw_body = raw_body[:-1]
                    self.pending_packets.append((raw_id, raw_body))
                else:
                    self.pending_packets.append((101, raw_packet))
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
                    raw_size = (b1 << 14) | (b2 << 7) | b3
                    raw_size = max(0, raw_size)
                    self.raw_data_expected = raw_size
                    self.raw_data_buffer = b""

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
            self.last_handshake_gen = 5
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

    def send_packet(self, packet_id: int, data: bytes = b"",
                    append_newline: bool = True) -> bool:
        """Send encrypted packet."""
        if not self.ws or not self._tcp_connected:
            return False

        try:
            packet = bytes([packet_id + 32]) + data + (b'\n' if append_newline else b'')
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
