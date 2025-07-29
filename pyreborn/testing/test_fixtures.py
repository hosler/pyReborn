"""
Test fixtures for pyReborn testing
"""

import logging
from typing import Optional, Dict, Any, List
from contextlib import contextmanager

from ..core.modular_client import ModularRebornClient
from ..config.client_config import ClientConfig
from ..core.events import EventManager
from ..core.container import DIContainer


class ClientTestFixture:
    """Test fixture for client testing"""
    
    def __init__(self, config: ClientConfig = None, container: DIContainer = None):
        self.config = config or ClientConfig(
            host="localhost",
            port=14900,
            version="2.22",
            connect_timeout=2.0,
            login_timeout=3.0
        )
        self.container = container
        self.client: Optional[ModularRebornClient] = None
        self.events_received: List[Any] = []
        self.logger = logging.getLogger(__name__)
        
    def create_client(self) -> ModularRebornClient:
        """Create a test client"""
        if self.client:
            self.client.cleanup()
        
        self.client = ModularRebornClient(config=self.config, container=self.container)
        
        # Set up event monitoring
        self._setup_event_monitoring()
        
        return self.client
    
    def get_client(self) -> Optional[ModularRebornClient]:
        """Get current test client"""
        return self.client
    
    def cleanup(self) -> None:
        """Clean up test fixture"""
        if self.client:
            self.client.cleanup()
            self.client = None
        self.events_received.clear()
        
    def _setup_event_monitoring(self) -> None:
        """Set up event monitoring for testing"""
        def event_monitor(event):
            self.events_received.append({
                'type': event.type,
                'data': event.data,
                'timestamp': __import__('time').time()
            })
        
        # Monitor all events by subscribing to common ones
        from ..core.events import EventType
        
        important_events = [
            EventType.CONNECTED,
            EventType.DISCONNECTED,
            EventType.LOGIN_SUCCESS,
            EventType.LOGIN_FAILED,
            EventType.PACKET_RECEIVED,
            EventType.PLAYER_ADDED,
            EventType.LEVEL_ENTERED
        ]
        
        for event_type in important_events:
            self.client.on(event_type, event_monitor)
    
    def wait_for_event(self, event_type, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
        """Wait for a specific event"""
        import time
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            for event in self.events_received:
                if event['type'] == event_type:
                    return event
            time.sleep(0.1)
        return None
    
    def get_events_of_type(self, event_type) -> List[Dict[str, Any]]:
        """Get all events of a specific type"""
        return [event for event in self.events_received if event['type'] == event_type]
    
    def clear_events(self) -> None:
        """Clear recorded events"""
        self.events_received.clear()
    
    def get_event_count(self, event_type=None) -> int:
        """Get count of events"""
        if event_type:
            return len(self.get_events_of_type(event_type))
        return len(self.events_received)
    
    def connect_and_login(self, username: str, password: str, timeout: float = 10.0) -> bool:
        """Connect and login with timeout"""
        import time
        
        if not self.client:
            return False
        
        # Connect
        if not self.client.connect():
            return False
        
        # Wait for connection
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.client.is_connected():
                break
            time.sleep(0.1)
        else:
            return False
        
        # Login
        if not self.client.login(username, password):
            return False
        
        # Wait for login success
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.client.is_logged_in():
                return True
            time.sleep(0.1)
        
        return False
    
    def assert_event_received(self, event_type, timeout: float = 5.0) -> Dict[str, Any]:
        """Assert that an event was received"""
        event = self.wait_for_event(event_type, timeout)
        if not event:
            raise AssertionError(f"Event {event_type} not received within {timeout}s")
        return event
    
    def assert_client_state(self, connected: bool = None, logged_in: bool = None) -> None:
        """Assert client state"""
        if connected is not None:
            actual_connected = self.client.is_connected() if self.client else False
            if actual_connected != connected:
                raise AssertionError(f"Expected connected={connected}, got {actual_connected}")
        
        if logged_in is not None:
            actual_logged_in = self.client.is_logged_in() if self.client else False
            if actual_logged_in != logged_in:
                raise AssertionError(f"Expected logged_in={logged_in}, got {actual_logged_in}")


def create_test_client(host: str = "localhost", port: int = 14900, 
                      version: str = "2.22", **config_kwargs) -> ModularRebornClient:
    """Create a test client with default settings"""
    config = ClientConfig(
        host=host,
        port=port,
        version=version,
        connect_timeout=2.0,
        login_timeout=3.0,
        **config_kwargs
    )
    
    return ModularRebornClient(config=config)


@contextmanager
def test_client_context(host: str = "localhost", port: int = 14900, 
                       version: str = "2.22", **config_kwargs):
    """Context manager for test client"""
    fixture = ClientTestFixture(ClientConfig(
        host=host,
        port=port,
        version=version,
        connect_timeout=2.0,
        login_timeout=3.0,
        **config_kwargs
    ))
    
    try:
        client = fixture.create_client()
        yield fixture
    finally:
        fixture.cleanup()


class MockEventHandler:
    """Mock event handler for testing"""
    
    def __init__(self):
        self.events_handled = []
        self.call_count = 0
    
    def __call__(self, event):
        self.call_count += 1
        self.events_handled.append({
            'type': event.type,
            'data': event.data
        })
    
    def was_called(self) -> bool:
        """Check if handler was called"""
        return self.call_count > 0
    
    def was_called_with(self, event_type) -> bool:
        """Check if handler was called with specific event type"""
        return any(event['type'] == event_type for event in self.events_handled)
    
    def get_call_count(self) -> int:
        """Get number of times handler was called"""
        return self.call_count
    
    def reset(self) -> None:
        """Reset handler state"""
        self.events_handled.clear()
        self.call_count = 0


class MockPacketHandler:
    """Mock packet handler for testing"""
    
    def __init__(self, packet_ids: List[int] = None):
        self.packet_ids = set(packet_ids) if packet_ids else set()
        self.packets_handled = []
        self.call_count = 0
    
    def can_handle(self, packet_id: int) -> bool:
        """Check if can handle packet"""
        return packet_id in self.packet_ids if self.packet_ids else True
    
    def handle(self, packet_id: int, packet_data: bytes, context: Dict[str, Any]) -> Any:
        """Handle packet"""
        self.call_count += 1
        self.packets_handled.append({
            'packet_id': packet_id,
            'data': packet_data,
            'context': context
        })
        return f"handled_packet_{packet_id}"
    
    @property
    def priority(self) -> int:
        """Handler priority"""
        return 100
    
    def was_called(self) -> bool:
        """Check if handler was called"""
        return self.call_count > 0
    
    def was_called_with_packet(self, packet_id: int) -> bool:
        """Check if handler was called with specific packet"""
        return any(packet['packet_id'] == packet_id for packet in self.packets_handled)
    
    def get_call_count(self) -> int:
        """Get number of times handler was called"""
        return self.call_count
    
    def reset(self) -> None:
        """Reset handler state"""
        self.packets_handled.clear()
        self.call_count = 0


class TestDataGenerator:
    """Generates test data for various scenarios"""
    
    @staticmethod
    def create_test_player_data() -> Dict[str, Any]:
        """Create test player data"""
        return {
            'player_id': 123,
            'username': 'testuser',
            'nickname': 'TestPlayer',
            'x': 30.0,
            'y': 30.0,
            'level': 'test_level.nw'
        }
    
    @staticmethod
    def create_test_level_data() -> Dict[str, Any]:
        """Create test level data"""
        return {
            'name': 'test_level.nw',
            'width': 64,
            'height': 64,
            'tiles': [[0 for _ in range(64)] for _ in range(64)]
        }
    
    @staticmethod
    def create_test_packet_data(packet_id: int, payload: bytes = b'') -> bytes:
        """Create test packet data"""
        return bytes([packet_id + 32]) + payload + b'\n'
    
    @staticmethod
    def create_login_packet(username: str, password: str) -> bytes:
        """Create login packet"""
        username_bytes = username.encode('latin-1')
        password_bytes = password.encode('latin-1')
        
        payload = bytes([len(username_bytes)]) + username_bytes
        payload += bytes([len(password_bytes)]) + password_bytes
        payload += b'\x00' * 10  # Additional login fields
        
        return TestDataGenerator.create_test_packet_data(14, payload)  # PLO_LOGIN = 14