"""
Mock GServer for testing client functionality without requiring a real server
"""

import socket
import threading
import time
import logging
from typing import Dict, List, Optional, Callable, Any
from enum import Enum
import struct

from ..protocol.enums import ServerToPlayer
from ..core.encryption import RebornEncryption


class ServerState(Enum):
    """Server state enumeration"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"


class MockClient:
    """Represents a client connection to the mock server"""
    
    def __init__(self, socket: socket.socket, address: tuple):
        self.socket = socket
        self.address = address
        self.connected = True
        self.username = None
        self.player_id = None
        self.encryption_key = 0
        self.in_codec = RebornEncryption()
        self.out_codec = RebornEncryption()
        self.authenticated = False
        
    def send_packet(self, packet_data: bytes) -> bool:
        """Send packet to client"""
        try:
            # Encrypt packet
            encrypted_data = self.out_codec.encrypt(packet_data, self.encryption_key)
            self.socket.send(encrypted_data)
            return True
        except Exception:
            return False
    
    def disconnect(self) -> None:
        """Disconnect client"""
        self.connected = False
        try:
            self.socket.close()
        except:
            pass


class ServerScenario:
    """Defines a server scenario for testing"""
    
    def __init__(self, name: str):
        self.name = name
        self.initial_packets: List[bytes] = []
        self.packet_responses: Dict[int, List[bytes]] = {}
        self.login_success = True
        self.login_delay = 0.0
        self.custom_handlers: Dict[int, Callable[[MockClient, bytes], None]] = {}
        
    def add_initial_packet(self, packet_data: bytes) -> None:
        """Add packet to send on client connection"""
        self.initial_packets.append(packet_data)
    
    def add_packet_response(self, packet_id: int, response: bytes) -> None:
        """Add response to send when specific packet is received"""
        if packet_id not in self.packet_responses:
            self.packet_responses[packet_id] = []
        self.packet_responses[packet_id].append(response)
    
    def set_login_behavior(self, success: bool, delay: float = 0.0) -> None:
        """Set login behavior"""
        self.login_success = success
        self.login_delay = delay
    
    def add_custom_handler(self, packet_id: int, handler: Callable[[MockClient, bytes], None]) -> None:
        """Add custom packet handler"""
        self.custom_handlers[packet_id] = handler


class MockGServer:
    """Mock GServer for testing"""
    
    def __init__(self, host: str = "localhost", port: int = 14900):
        self.host = host
        self.port = port
        self.logger = logging.getLogger(__name__)
        
        # Server state
        self.state = ServerState.STOPPED
        self.socket: Optional[socket.socket] = None
        self.server_thread: Optional[threading.Thread] = None
        self.running = False
        
        # Client management
        self.clients: Dict[str, MockClient] = {}
        self.next_player_id = 1
        
        # Scenarios
        self.current_scenario: Optional[ServerScenario] = None
        self.default_packets = self._create_default_packets()
        
        # Statistics
        self.stats = {
            'connections': 0,
            'packets_sent': 0,
            'packets_received': 0,
            'logins': 0
        }
    
    def set_scenario(self, scenario: ServerScenario) -> None:
        """Set the current test scenario"""
        self.current_scenario = scenario
        self.logger.debug(f"Set scenario: {scenario.name}")
    
    def start(self) -> bool:
        """Start the mock server"""
        if self.state != ServerState.STOPPED:
            return False
        
        try:
            self.state = ServerState.STARTING
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind((self.host, self.port))
            self.socket.listen(5)
            
            self.running = True
            self.server_thread = threading.Thread(target=self._server_loop, daemon=True)
            self.server_thread.start()
            
            self.state = ServerState.RUNNING
            self.logger.info(f"Mock server started on {self.host}:{self.port}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to start mock server: {e}")
            self.state = ServerState.STOPPED
            return False
    
    def stop(self) -> None:
        """Stop the mock server"""
        if self.state != ServerState.RUNNING:
            return
        
        self.state = ServerState.STOPPING
        self.running = False
        
        # Disconnect all clients
        for client in list(self.clients.values()):
            client.disconnect()
        self.clients.clear()
        
        # Close server socket
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
        
        # Wait for server thread
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=2.0)
        
        self.state = ServerState.STOPPED
        self.logger.info("Mock server stopped")
    
    def wait_for_connections(self, count: int, timeout: float = 5.0) -> bool:
        """Wait for specified number of client connections"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if len(self.clients) >= count:
                return True
            time.sleep(0.1)
        return False
    
    def get_client_count(self) -> int:
        """Get number of connected clients"""
        return len(self.clients)
    
    def get_stats(self) -> Dict[str, int]:
        """Get server statistics"""
        stats = self.stats.copy()
        stats['connected_clients'] = len(self.clients)
        return stats
    
    def send_to_all_clients(self, packet_data: bytes) -> None:
        """Send packet to all connected clients"""
        for client in self.clients.values():
            if client.connected:
                client.send_packet(packet_data)
                self.stats['packets_sent'] += 1
    
    def send_to_client(self, username: str, packet_data: bytes) -> bool:
        """Send packet to specific client"""
        client = self.clients.get(username)
        if client and client.connected:
            result = client.send_packet(packet_data)
            if result:
                self.stats['packets_sent'] += 1
            return result
        return False
    
    def _server_loop(self) -> None:
        """Main server loop"""
        while self.running and self.socket:
            try:
                # Accept new connections
                client_socket, address = self.socket.accept()
                
                # Handle client in separate thread
                client_thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_socket, address),
                    daemon=True
                )
                client_thread.start()
                
            except socket.error:
                if self.running:
                    self.logger.error("Socket error in server loop")
                break
            except Exception as e:
                if self.running:
                    self.logger.error(f"Error in server loop: {e}")
                break
    
    def _handle_client(self, client_socket: socket.socket, address: tuple) -> None:
        """Handle individual client connection"""
        client = MockClient(client_socket, address)
        client_id = f"{address[0]}:{address[1]}"
        
        self.logger.info(f"Client connected: {client_id}")
        self.stats['connections'] += 1
        
        # Send initial packets
        self._send_initial_packets(client)
        
        try:
            while self.running and client.connected:
                # Receive data
                data = client_socket.recv(1024)
                if not data:
                    break
                
                # Decrypt data
                decrypted_data = client.in_codec.decrypt(data, client.encryption_key)
                
                # Process packets
                self._process_client_packets(client, decrypted_data)
                self.stats['packets_received'] += 1
                
        except Exception as e:
            self.logger.debug(f"Client {client_id} error: {e}")
        finally:
            client.disconnect()
            if client.username and client.username in self.clients:
                del self.clients[client.username]
            self.logger.debug(f"Client disconnected: {client_id}")
    
    def _send_initial_packets(self, client: MockClient) -> None:
        """Send initial packets to new client"""
        packets = []
        
        # Use scenario packets if available
        if self.current_scenario:
            packets.extend(self.current_scenario.initial_packets)
        else:
            packets.extend(self.default_packets)
        
        # Send packets
        for packet_data in packets:
            client.send_packet(packet_data)
            self.stats['packets_sent'] += 1
    
    def _process_client_packets(self, client: MockClient, packet_data: bytes) -> None:
        """Process packets from client"""
        if not packet_data:
            return
        
        # Simple packet parsing (first byte is packet ID + 32)
        packet_id = packet_data[0] - 32 if packet_data else 0
        payload = packet_data[1:] if len(packet_data) > 1 else b''
        
        # Handle login packets
        if packet_id == 14:  # PLO_LOGIN
            self._handle_login(client, payload)
            return
        
        # Check for custom handlers
        if (self.current_scenario and 
            packet_id in self.current_scenario.custom_handlers):
            self.current_scenario.custom_handlers[packet_id](client, payload)
            return
        
        # Check for scenario responses
        if (self.current_scenario and 
            packet_id in self.current_scenario.packet_responses):
            responses = self.current_scenario.packet_responses[packet_id]
            for response in responses:
                client.send_packet(response)
                self.stats['packets_sent'] += 1
        
        # Default packet handling
        self._handle_default_packet(client, packet_id, payload)
    
    def _handle_login(self, client: MockClient, payload: bytes) -> None:
        """Handle login packet"""
        try:
            # Simple login parsing - extract username
            if len(payload) > 2:
                username_len = payload[0]
                if username_len > 0 and len(payload) > username_len:
                    username = payload[1:1+username_len].decode('latin-1', errors='ignore')
                    client.username = username
                    client.player_id = self.next_player_id
                    self.next_player_id += 1
            
            # Determine login success
            success = True
            delay = 0.0
            
            if self.current_scenario:
                success = self.current_scenario.login_success
                delay = self.current_scenario.login_delay
            
            # Apply delay if specified
            if delay > 0:
                time.sleep(delay)
            
            if success:
                # Send login success
                client.authenticated = True
                self.clients[client.username or f"user_{client.player_id}"] = client
                self.stats['logins'] += 1
                
                # Send signature packet (packet ID 25)
                signature_packet = bytes([25 + 32]) + b'test_signature\n'
                client.send_packet(signature_packet)
                self.stats['packets_sent'] += 1
                
                self.logger.debug(f"Login successful: {client.username}")
            else:
                # Send login failure
                client.disconnect()
                self.logger.debug(f"Login failed: {client.username}")
                
        except Exception as e:
            self.logger.error(f"Error handling login: {e}")
            client.disconnect()
    
    def _handle_default_packet(self, client: MockClient, packet_id: int, payload: bytes) -> None:
        """Handle default packet responses"""
        # Add default responses for common packets here
        pass
    
    def _create_default_packets(self) -> List[bytes]:
        """Create default initial packets"""
        return [
            # Could add default server info packets here
        ]
    
    def __enter__(self):
        """Context manager entry"""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.stop()