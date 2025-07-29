"""
Integration test helpers for comprehensive testing scenarios
"""

import time
import logging
from typing import Dict, List, Optional, Any, Callable
from contextlib import contextmanager

from .mock_server import MockGServer, ServerScenario
from .test_fixtures import ClientTestFixture
from ..core.modular_client import ModularRebornClient
from ..config.client_config import ClientConfig
from ..core.events import EventType


class IntegrationTestHelper:
    """Helper for integration testing with mock server"""
    
    def __init__(self, server_port: int = 14901):
        self.server_port = server_port
        self.mock_server: Optional[MockGServer] = None
        self.client_fixtures: List[ClientTestFixture] = []
        self.logger = logging.getLogger(__name__)
        
    def create_mock_server(self, scenario: ServerScenario = None) -> MockGServer:
        """Create and configure mock server"""
        self.mock_server = MockGServer("localhost", self.server_port)
        
        if scenario:
            self.mock_server.set_scenario(scenario)
        
        return self.mock_server
    
    def create_test_client(self, **config_kwargs) -> ClientTestFixture:
        """Create a test client fixture"""
        config = ClientConfig(
            host="localhost",
            port=self.server_port,
            version="2.22",
            connect_timeout=3.0,
            login_timeout=5.0,
            **config_kwargs
        )
        
        fixture = ClientTestFixture(config)
        fixture.create_client()
        self.client_fixtures.append(fixture)
        
        return fixture
    
    def cleanup(self) -> None:
        """Clean up all resources"""
        # Clean up clients
        for fixture in self.client_fixtures:
            fixture.cleanup()
        self.client_fixtures.clear()
        
        # Stop mock server
        if self.mock_server:
            self.mock_server.stop()
            self.mock_server = None
    
    @contextmanager
    def test_scenario(self, scenario: ServerScenario):
        """Context manager for test scenario"""
        try:
            self.create_mock_server(scenario)
            self.mock_server.start()
            
            # Wait for server to be ready
            time.sleep(0.1)
            
            yield self
        finally:
            self.cleanup()
    
    def run_connection_test(self, username: str = "testuser", password: str = "testpass") -> Dict[str, Any]:
        """Run basic connection test"""
        results = {
            'server_started': False,
            'client_connected': False,
            'login_successful': False,
            'events_received': [],
            'errors': []
        }
        
        try:
            # Start server
            if not self.mock_server:
                self.create_mock_server()
            
            if not self.mock_server.start():
                results['errors'].append("Failed to start mock server")
                return results
            
            results['server_started'] = True
            time.sleep(0.1)  # Let server initialize
            
            # Create client
            client_fixture = self.create_test_client()
            client = client_fixture.get_client()
            
            # Connect
            if client.connect():
                results['client_connected'] = True
                
                # Wait for connection event
                connection_event = client_fixture.wait_for_event(EventType.CONNECTED, 3.0)
                if connection_event:
                    results['events_received'].append('CONNECTED')
                
                # Login
                if client.login(username, password):
                    # Wait for login result
                    login_event = client_fixture.wait_for_event(EventType.LOGIN_SUCCESS, 5.0)
                    if login_event:
                        results['login_successful'] = True
                        results['events_received'].append('LOGIN_SUCCESS')
                    else:
                        failed_event = client_fixture.wait_for_event(EventType.LOGIN_FAILED, 1.0)
                        if failed_event:
                            results['events_received'].append('LOGIN_FAILED')
                            results['errors'].append(f"Login failed: {failed_event.get('data', {}).get('error', 'Unknown')}")
                else:
                    results['errors'].append("Failed to initiate login")
            else:
                results['errors'].append("Failed to connect to server")
                
        except Exception as e:
            results['errors'].append(f"Test exception: {e}")
        
        return results
    
    def run_packet_flow_test(self, packets_to_send: List[bytes], 
                           expected_responses: List[int]) -> Dict[str, Any]:
        """Test packet flow between client and server"""
        results = {
            'packets_sent': 0,
            'responses_received': [],
            'expected_responses': expected_responses,
            'success': False,
            'errors': []
        }
        
        try:
            if not self.mock_server or not self.client_fixtures:
                results['errors'].append("Server or client not initialized")
                return results
            
            client_fixture = self.client_fixtures[0]
            client = client_fixture.get_client()
            
            if not client.is_connected():
                results['errors'].append("Client not connected")
                return results
            
            # Send packets and monitor responses
            initial_event_count = len(client_fixture.events_received)
            
            for packet_data in packets_to_send:
                if client.send_raw_packet(packet_data):
                    results['packets_sent'] += 1
                    time.sleep(0.1)  # Allow processing time
            
            # Wait for responses
            time.sleep(1.0)
            
            # Analyze received events
            new_events = client_fixture.events_received[initial_event_count:]
            for event in new_events:
                if 'packet_id' in event.get('data', {}):
                    results['responses_received'].append(event['data']['packet_id'])
            
            # Check if we got expected responses
            results['success'] = all(
                expected in results['responses_received'] 
                for expected in expected_responses
            )
            
        except Exception as e:
            results['errors'].append(f"Packet flow test error: {e}")
        
        return results
    
    def run_stress_test(self, num_clients: int = 5, duration: float = 10.0) -> Dict[str, Any]:
        """Run stress test with multiple clients"""
        results = {
            'clients_created': 0,
            'clients_connected': 0,
            'clients_logged_in': 0,
            'total_events': 0,
            'errors': [],
            'duration': duration
        }
        
        try:
            if not self.mock_server:
                self.create_mock_server()
                self.mock_server.start()
                time.sleep(0.1)
            
            # Create multiple clients
            client_fixtures = []
            for i in range(num_clients):
                try:
                    fixture = self.create_test_client()
                    client_fixtures.append(fixture)
                    results['clients_created'] += 1
                    
                    # Connect client
                    client = fixture.get_client()
                    if client.connect():
                        results['clients_connected'] += 1
                        
                        # Login
                        if client.login(f"user{i}", "password"):
                            time.sleep(0.1)  # Stagger logins
                            if client.is_logged_in():
                                results['clients_logged_in'] += 1
                
                except Exception as e:
                    results['errors'].append(f"Client {i} error: {e}")
            
            # Let clients run for duration
            time.sleep(duration)
            
            # Collect statistics
            for fixture in client_fixtures:
                results['total_events'] += len(fixture.events_received)
            
            server_stats = self.mock_server.get_stats()
            results['server_stats'] = server_stats
            
        except Exception as e:
            results['errors'].append(f"Stress test error: {e}")
        
        return results


def create_login_scenario(success: bool = True, delay: float = 0.0) -> ServerScenario:
    """Create a basic login scenario"""
    scenario = ServerScenario("login_test")
    scenario.set_login_behavior(success, delay)
    return scenario


def create_packet_response_scenario(packet_responses: Dict[int, List[bytes]]) -> ServerScenario:
    """Create scenario with specific packet responses"""
    scenario = ServerScenario("packet_response_test")
    
    for packet_id, responses in packet_responses.items():
        for response in responses:
            scenario.add_packet_response(packet_id, response)
    
    return scenario


def create_level_loading_scenario() -> ServerScenario:
    """Create scenario that simulates level loading"""
    scenario = ServerScenario("level_loading")
    
    # Add level name packet
    level_name_packet = bytes([6 + 32]) + b"test_level.nw\n"  # PLO_LEVELNAME
    scenario.add_initial_packet(level_name_packet)
    
    # Add basic level board packet
    board_packet = bytes([0 + 32]) + b"test_board_data\n"  # PLO_LEVELBOARD
    scenario.add_initial_packet(board_packet)
    
    return scenario


@contextmanager
def integration_test_environment(port: int = 14901, scenario: ServerScenario = None):
    """Context manager for integration test environment"""
    helper = IntegrationTestHelper(port)
    
    try:
        if scenario:
            with helper.test_scenario(scenario):
                yield helper
        else:
            helper.create_mock_server()
            helper.mock_server.start()
            time.sleep(0.1)
            yield helper
    finally:
        helper.cleanup()


def run_quick_integration_test(test_func: Callable, port: int = 14901, 
                              scenario: ServerScenario = None) -> Any:
    """Run a quick integration test with automatic setup/teardown"""
    with integration_test_environment(port, scenario) as helper:
        return test_func(helper)