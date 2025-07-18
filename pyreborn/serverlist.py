"""Server list client for connecting to Graal listserver."""

import socket
import struct
import zlib
import re
import logging
from typing import List, Optional, Tuple
from enum import IntEnum

from .server_info import ServerInfo


logger = logging.getLogger(__name__)


class PLI(IntEnum):
    """Player List Input - Client to Server packets."""
    V1VER = 0
    SERVERLIST = 1
    V2VER = 4
    V2ENCRYPTKEYCL = 7


class PLO(IntEnum):
    """Player List Output - Server to Client packets."""
    SVRLIST = 0
    STATUS = 2
    SITEURL = 3
    ERROR = 4
    UPGURL = 5


class ServerListClient:
    """Client for retrieving server list from Graal listserver.
    
    This implements the direct client protocol (not RC protocol) for
    retrieving the list of available game servers.
    """
    
    DEFAULT_HOST = "listserver.graal.in"
    DEFAULT_PORT = 14922
    DEFAULT_TIMEOUT = 10.0
    QUICK_TIMEOUT = 0.5  # Quick timeout after receiving server list
    
    def __init__(self, host: str = None, port: int = None, timeout: float = None):
        """Initialize server list client.
        
        Args:
            host: Listserver hostname (default: listserver.graal.in)
            port: Listserver port (default: 14922)
            timeout: Socket timeout in seconds (default: 10.0)
        """
        self.host = host or self.DEFAULT_HOST
        self.port = port or self.DEFAULT_PORT
        self.timeout = timeout or self.DEFAULT_TIMEOUT
        self._socket: Optional[socket.socket] = None
        self._connected = False
        
    def connect(self) -> bool:
        """Connect to the listserver.
        
        Returns:
            True if connected successfully, False otherwise
        """
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(self.timeout)
            self._socket.connect((self.host, self.port))
            self._connected = True
            logger.info(f"Connected to listserver at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to listserver: {e}")
            self._connected = False
            return False
    
    def disconnect(self):
        """Disconnect from the listserver."""
        if self._socket:
            try:
                self._socket.close()
            except:
                pass
            self._socket = None
        self._connected = False
        logger.info("Disconnected from listserver")
    
    def get_servers(self, account: str, password: str) -> Tuple[List[ServerInfo], dict]:
        """Get list of servers from the listserver.
        
        Args:
            account: Account name for authentication
            password: Account password
            
        Returns:
            Tuple of (list of ServerInfo objects, dict with status/urls)
        """
        if not self._connected:
            if not self.connect():
                return [], {}
        
        servers = []
        status_info = {}
        received_server_list = False
        received_status = False
        
        try:
            # Send version packet (uncompressed)
            self._send_version_packet()
            
            # Send authentication packet (compressed)
            self._send_auth_packet(account, password)
            
            # Receive response packets
            while True:
                packet = self._receive_packet()
                if not packet:
                    break
                
                # Process packet (packet IDs are Graal-encoded!)
                packet_type = packet[0] - 32  # Decode the Graal encoding
                
                if packet_type == PLO.SVRLIST:
                    servers = self._parse_server_list(packet[1:])
                    logger.info(f"Received {len(servers)} servers")
                    received_server_list = True
                    # Check if we have all essential data
                    if received_server_list and received_status:
                        logger.debug("Received all essential data, exiting")
                        break
                elif packet_type == PLO.STATUS:
                    if len(packet) > 1:
                        msg_len = packet[1] - 32
                        status = packet[2:2+msg_len].decode('latin-1', errors='ignore')
                        status_info['status'] = status
                        logger.info(f"Status: {status}")
                        received_status = True
                        # Check if we have all essential data
                        if received_server_list and received_status:
                            logger.debug("Received all essential data, exiting")
                            break
                elif packet_type == PLO.SITEURL:
                    if len(packet) > 1:
                        msg_len = packet[1] - 32
                        url = packet[2:2+msg_len].decode('latin-1', errors='ignore')
                        status_info['site_url'] = url
                        logger.info(f"Site URL: {url}")
                elif packet_type == PLO.UPGURL:
                    if len(packet) > 1:
                        msg_len = packet[1] - 32
                        url = packet[2:2+msg_len].decode('latin-1', errors='ignore')
                        status_info['upgrade_url'] = url
                        logger.info(f"Upgrade URL: {url}")
                elif packet_type == PLO.ERROR:
                    if len(packet) > 1:
                        msg_len = packet[1] - 32
                        error = packet[2:2+msg_len].decode('latin-1', errors='ignore')
                        status_info['error'] = error
                        logger.error(f"Listserver error: {error}")
                    break
                    
        except socket.timeout:
            logger.debug("Socket timeout while waiting for more packets")
        except Exception as e:
            logger.error(f"Error retrieving server list: {e}")
            
        return servers, status_info
    
    def _send_version_packet(self):
        """Send version/encryption packet to listserver."""
        # Format: PLI_V2ENCRYPTKEYCL (7+32) + key + 8-byte version + client_type + newline
        packet = bytearray()
        packet.append(PLI.V2ENCRYPTKEYCL + 32)  # Packet ID: 7 + 32 = 39
        packet.append(0 + 32)  # Encryption key 0 (no encryption) + 32
        packet.extend(b"GNW30123")  # 8-byte version string
        packet.extend(b"newmain")  # Client type
        packet.append(ord('\n'))  # Newline terminator
        
        self._send_packet(packet, compress=False)
        logger.debug("Sent version packet")
    
    def _send_auth_packet(self, account: str, password: str):
        """Send authentication packet to listserver."""
        # Format: PLI_SERVERLIST (1+32) + account_len + account + pass_len + password + newline
        packet = bytearray()
        packet.append(PLI.SERVERLIST + 32)  # Packet ID: 1 + 32 = 33
        packet.append(len(account) + 32)  # Graal encoded length
        packet.extend(account.encode('latin-1'))
        packet.append(len(password) + 32)  # Graal encoded length
        packet.extend(password.encode('latin-1'))
        packet.append(ord('\n'))  # Newline terminator
        
        self._send_packet(packet, compress=True)
        logger.debug(f"Sent auth packet for account: {account}")
    
    def _send_packet(self, data: bytes, compress: bool = False):
        """Send a packet with big-endian length header."""
        if compress:
            # Compress with zlib (ENCRYPT_GEN_2)
            compressed = zlib.compress(data)
            data = compressed
            
        # Build complete packet: [2-byte length][data]
        length = len(data)
        packet = struct.pack('>H', length) + data
        
        # Send everything in one call
        self._socket.send(packet)
    
    def _receive_packet(self) -> Optional[bytes]:
        """Receive a packet with length header."""
        try:
            # Read 2-byte length header
            length_data = self._socket.recv(2)
            if len(length_data) < 2:
                return None
                
            # Big-endian length (network byte order)
            length = struct.unpack('>H', length_data)[0]
            
            # Read packet data
            data = bytearray()
            while len(data) < length:
                chunk = self._socket.recv(length - len(data))
                if not chunk:
                    break
                data.extend(chunk)
                
            # Check for compression
            if data and data[0] == 0x78:  # zlib magic
                try:
                    decompressed = zlib.decompress(data)
                    return decompressed
                except:
                    pass
                    
            return bytes(data)
            
        except socket.timeout:
            return None
        except Exception as e:
            logger.error(f"Receive error: {e}")
            return None
    
    def _parse_server_list(self, data: bytes) -> List[ServerInfo]:
        """Parse PLO_SVRLIST packet data.
        
        NOTE: The listserver sends malformed data where fields are
        concatenated. This parser handles the actual format we receive.
        """
        servers = []
        
        try:
            pos = 0
            
            # Read server count (Graal-encoded)
            if pos >= len(data):
                return servers
            server_count = data[pos] - 32  # Graal decoded
            pos += 1
            
            logger.debug(f"Parsing {server_count} servers")
            
            # Find server endpoints by looking for pattern: !<players>[,]<host>%<port>
            text = data[pos:].decode('latin-1', errors='ignore')
            server_end_pattern = r'!\d+[,.]?[a-zA-Z0-9.-]+%\d{4,5}'
            end_positions = []
            for match in re.finditer(server_end_pattern, text):
                end_positions.append(pos + match.end())
            
            # Parse each server
            start_pos = pos
            for i, end_pos in enumerate(end_positions[:server_count]):
                # Extract server chunk
                server_chunk = data[start_pos:end_pos]
                
                # Parse this server
                server = self._parse_single_server(server_chunk)
                if server:
                    servers.append(server)
                    logger.debug(f"Parsed server: {server}")
                
                # Next server starts where this one ended
                start_pos = end_pos
                
        except Exception as e:
            logger.error(f"Error parsing server list: {e}")
            
        return servers
    
    def _parse_single_server(self, data: bytes) -> Optional[ServerInfo]:
        """Parse a single server from chunk of data."""
        pos = 0
        
        # Skip packet ID if present
        if pos < len(data) and data[pos] == 40:
            pos += 1
        
        # Read the type+name length
        if pos >= len(data):
            return None
        combined_len = data[pos]
        pos += 1
        
        if pos + combined_len > len(data):
            combined_len = len(data) - pos
        
        # Extract the combined field
        combined = data[pos:pos+combined_len].decode('latin-1', errors='ignore')
        pos += combined_len
        
        # The rest of the data
        remaining = data[pos:].decode('latin-1', errors='ignore')
        full_text = combined + remaining
        
        # Parse server name and language
        name = ""
        language = "English"
        
        # Try to extract server name by looking for language markers
        for lang in ["'English", "'Finnish", "'Deutsch", "'Español", "'Français"]:
            if lang in combined:
                idx = combined.find(lang)
                name = combined[:idx]
                language = lang[1:]
                break
        
        if not name:
            # No language marker found
            if "'" in combined:
                name = combined.split("'")[0]
            else:
                # Use first part before any digit
                match = re.match(r'^([^\d]+)', combined)
                if match:
                    name = match.group(1)
                else:
                    name = combined
        
        # Clean up the name
        name = name.strip()
        if name.startswith("("):
            name = name[1:]
        if len(name) > 1 and ord(name[0]) < 32:
            name = name[1:]
        
        # Check for type prefix
        server_type = ""
        if len(name) >= 2 and name[1] == ' ':
            server_type = name[0]
            name = name[2:]
        
        # Default values
        description = "Server"
        url = ""
        version = ""
        players = 0
        ip = "unknown"
        port = 14802
        
        # Extract IP/hostname and port using pattern: !<players>[,]<host>%<port>
        host_port_match = re.search(r'!(.+?)%(\d+)', full_text)
        if host_port_match:
            middle = host_port_match.group(1)
            port = int(host_port_match.group(2))
            
            # Parse the middle part to separate players and host
            if ',' in middle:
                # Easy case: comma-separated
                parts = middle.split(',')
                if len(parts) >= 2 and parts[0].isdigit():
                    players = int(parts[0])
                    ip = parts[1]
            else:
                # No comma - need to separate players from host
                i = 0
                while i < len(middle) and middle[i].isdigit():
                    i += 1
                
                if i > 0 and i < len(middle):
                    players_str = middle[:i]
                    host_str = middle[i:]
                    
                    # Check if this looks like a hostname (has letters)
                    if any(c.isalpha() for c in host_str):
                        players = int(players_str)
                        ip = host_str
                    else:
                        # Check for IP with too many dots (e.g., "1.208.87.131.106")
                        if middle.count('.') >= 4:
                            first_dot = middle.find('.')
                            if first_dot > 0:
                                players = int(middle[:first_dot])
                                ip = middle[first_dot+1:]
                        else:
                            players = int(players_str) if players_str.isdigit() else 0
                            ip = host_str
                else:
                    # Just use the whole thing as host
                    ip = middle
        
        # Extract other fields from full text
        
        # URL
        url_match = re.search(r'https?://[^\s,!%]+', full_text)
        if url_match:
            url = url_match.group(0)
        
        # Version
        ver_match = re.search(r'[Vv]ersion:?\s*([\d.]+(?:-[\w\s]+)?)', full_text)
        if ver_match:
            version = ver_match.group(0)
        
        # Description (text between language and URL/version)
        desc_match = re.search(language + r'([^!%]+?)(?:https?://|\d+Version:|$)', full_text)
        if desc_match:
            description = desc_match.group(1).strip()
            description = re.sub(r'[\d,]+$', '', description).strip()
        
        return ServerInfo(
            name=name,
            type=server_type,
            language=language,
            description=description,
            url=url,
            version=version,
            players=players,
            ip=ip,
            port=port
        )