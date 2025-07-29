"""
Modular Reborn Client - Refactored client using dependency injection and component separation
"""

import logging
import time
from typing import Optional, Dict, Any

from ..config.client_config import ClientConfig
from ..core.container import DIContainer, get_container
from ..core.events import EventManager, EventType
from ..core.interfaces import IConnectionManager, IPacketProcessor, IManager
from ..core.connection_manager import ConnectionManager
from ..core.packet_processor import PacketProcessor
from ..core.session_state_manager import SessionStateManager
from ..core.connection_resilience import ConnectionResilientManager, ReconnectPolicy
from ..core.operation_recovery import OperationRecoveryManager, OperationType
from ..models.player import Player
from ..models.level import Level


class ModularRebornClient:
    """Modular client that uses dependency injection for component management
    
    This replaces the monolithic RebornClient with a cleaner, more maintainable architecture.
    """
    
    def __init__(self, host: str = None, port: int = None, version: str = None, 
                 config: ClientConfig = None, container: DIContainer = None):
        """Initialize modular client
        
        Args:
            host: Server hostname (or use config)
            port: Server port (or use config) 
            version: Protocol version (or use config)
            config: Pre-configured ClientConfig object
            container: Custom DI container (uses global if None)
        """
        
        # Configuration
        if config:
            self.config = config
        else:
            self.config = ClientConfig(
                host=host or 'localhost',
                port=port or 14900,
                version=version or '2.22'
            )
        
        # Setup logging first
        self.logger = logging.getLogger(__name__)
        
        # Dependency injection
        self.container = container or get_container()
        self._setup_dependencies()
        
        # Core components (resolved from container)
        self.events: EventManager = self.container.resolve(EventManager)
        self.connection: IConnectionManager = self.container.resolve(IConnectionManager)
        self.packet_processor: IPacketProcessor = self.container.resolve(IPacketProcessor)
        self.session: SessionStateManager = self.container.resolve(SessionStateManager)
        
        # Connection resilience manager
        self.resilience: ConnectionResilientManager = ConnectionResilientManager(self.config, self.events)
        
        # Operation recovery manager
        self.recovery: OperationRecoveryManager = OperationRecoveryManager(self.events)
        
        # Initialize components
        self._initialize_components()
        
        # State (delegated to components)
        self._login_success = False
        
        # Backward compatibility properties
        self._flags: Dict[str, str] = {}
        self._levels: Dict[str, Level] = {}
    
    def _setup_dependencies(self) -> None:
        """Register dependencies in the container"""
        
        # Register configuration
        self.container.register_instance(ClientConfig, self.config)
        
        # Register event manager
        if not self.container.is_registered(EventManager):
            self.container.register_singleton(EventManager, EventManager)
        
        # Register core components
        if not self.container.is_registered(IConnectionManager):
            self.container.register_singleton(IConnectionManager, ConnectionManager)
        
        if not self.container.is_registered(IPacketProcessor):
            self.container.register_singleton(IPacketProcessor, PacketProcessor)
        
        if not self.container.is_registered(SessionStateManager):
            self.container.register_singleton(SessionStateManager, SessionStateManager)
    
    def _initialize_components(self) -> None:
        """Initialize all components"""
        
        # Initialize core components
        self.connection.initialize(self.config, self.events)
        self.packet_processor.initialize(self.config, self.events)
        self.session.initialize(self.config, self.events)
        
        # Set up component connections
        self.connection.set_packet_callback(self.packet_processor.process_raw_data)
        self.packet_processor.set_client_context(self)  # For backward compatibility
        
        # Subscribe to session events
        self.events.subscribe(EventType.LOGIN_SUCCESS, self._on_login_success)
        self.events.subscribe(EventType.LOGIN_FAILED, self._on_login_failed)
        
        # Set up connection resilience callbacks
        self.resilience.set_connection_callbacks(
            connect_func=lambda: self.connection.connect(self.config.host, self.config.port),
            disconnect_func=lambda: self.connection.disconnect()
        )
        
        self.logger.debug("Modular client initialized")
    
    def connect(self) -> bool:
        """Connect to server with resilience"""
        return self.resilience.start_connection()
    
    def disconnect(self) -> None:
        """Disconnect from server and stop auto-reconnect"""
        self.resilience.stop_connection()
    
    def force_reconnect(self) -> bool:
        """Force immediate reconnection"""
        return self.resilience.force_reconnect()
    
    def login(self, username: str, password: str) -> bool:
        """Login to server with recovery support"""
        if not self.connection.is_connected():
            self.logger.error("Cannot login: not connected to server")
            return False
        
        # Register operation for recovery
        operation_id = f"login_{username}_{int(time.time())}"
        context = self.recovery.register_operation(
            operation_id, OperationType.LOGIN,
            args=(username, password),
            max_attempts=3
        )
        
        try:
            # Set credentials and start login
            self.session.set_credentials(username, password)
            result = self.session.start_login(self.connection)
            
            if result:
                self.recovery.unregister_operation(operation_id)
            
            return result
            
        except Exception as e:
            # Attempt recovery
            recovery_functions = {
                'retry_function': lambda u=username, p=password: self._retry_login(u, p),
                'fallback_function': lambda server: self._fallback_login(username, password, server)
            }
            
            if self.recovery.recover_operation(operation_id, e, recovery_functions):
                return True
            
            self.logger.error(f"Login failed after recovery attempts: {e}")
            return False
    
    def is_connected(self) -> bool:
        """Check if connected to server"""
        return self.connection.is_connected()
    
    def is_logged_in(self) -> bool:
        """Check if logged in"""
        return self.session.is_logged_in()
    
    def get_local_player(self) -> Optional[Player]:
        """Get local player object"""
        return self.session.get_player()
    
    def send_packet(self, packet_data: bytes) -> bool:
        """Send packet to server"""
        return self.connection.send_packet(packet_data)
    
    def send_raw_packet(self, packet_data: bytes) -> bool:
        """Send raw packet to server"""
        return self.connection.send_raw_packet(packet_data)
    
    # Event handlers
    def _on_login_success(self, event) -> None:
        """Handle successful login"""
        self._login_success = True
        self.logger.info(f"Login successful for user: {event.data.get('username')}")
    
    def _on_login_failed(self, event) -> None:
        """Handle failed login"""
        self._login_success = False
        error = event.data.get('error', 'Unknown error')
        self.logger.error(f"Login failed: {error}")
    
    # Event system delegation
    def on(self, event_type, handler) -> None:
        """Subscribe to events"""
        self.events.subscribe(event_type, handler)
    
    def emit(self, event_type, **kwargs) -> None:
        """Emit events"""
        self.events.emit(event_type, **kwargs)
    
    # Backward compatibility properties
    @property
    def login_success(self) -> bool:
        """Backward compatibility: login success status"""
        return self._login_success
    
    @property
    def local_player(self) -> Optional[Player]:
        """Backward compatibility: local player access"""
        return self.get_local_player()
    
    @property
    def connected(self) -> bool:
        """Backward compatibility: connection status"""
        return self.is_connected()
    
    @property
    def flags(self) -> Dict[str, str]:
        """Backward compatibility: flags storage"""
        return self._flags
    
    @property
    def levels(self) -> Dict[str, Level]:
        """Backward compatibility: levels storage"""
        return self._levels
    
    @property
    def host(self) -> str:
        """Backward compatibility: host access"""
        return self.config.host
    
    @property
    def port(self) -> int:
        """Backward compatibility: port access"""
        return self.config.port
    
    # Component access methods
    def get_connection_manager(self) -> IConnectionManager:
        """Get connection manager"""
        return self.connection
    
    def get_packet_processor(self) -> IPacketProcessor:
        """Get packet processor"""
        return self.packet_processor
    
    def get_session_manager(self) -> SessionStateManager:
        """Get session state manager"""
        return self.session
    
    def get_event_manager(self) -> EventManager:
        """Get event manager"""
        return self.events
    
    def get_container(self) -> DIContainer:
        """Get dependency injection container"""
        return self.container
    
    def get_config(self) -> ClientConfig:
        """Get client configuration"""
        return self.config
    
    # Statistics and diagnostics
    def get_statistics(self) -> Dict[str, Any]:
        """Get client statistics"""
        return {
            'connected': self.is_connected(),
            'logged_in': self.is_logged_in(),
            'session_state': self.session.get_state().value,
            'packet_stats': self.packet_processor.get_packet_statistics(),
            'session_duration': self.session.get_session_duration(),
            'config': self.config.to_dict(),
            'connection_health': self.resilience.get_metrics(),
            'connection_state': self.resilience.get_connection_state().value
        }
    
    # Connection resilience methods
    def set_reconnect_policy(self, policy: ReconnectPolicy) -> None:
        """Configure reconnection policy"""
        self.resilience.set_reconnect_policy(policy)
    
    def get_connection_health(self) -> bool:
        """Check if connection is healthy"""
        return self.resilience.is_healthy()
    
    def get_connection_metrics(self):
        """Get connection health metrics"""
        return self.resilience.get_metrics()
    
    def get_recovery_statistics(self) -> Dict[str, Any]:
        """Get operation recovery statistics"""
        return self.recovery.get_recovery_statistics()
    
    def _retry_login(self, username: str, password: str) -> bool:
        """Retry login operation"""
        try:
            self.session.set_credentials(username, password)
            return self.session.start_login(self.connection)
        except Exception as e:
            self.logger.warning(f"Login retry failed: {e}")
            return False
    
    def _fallback_login(self, username: str, password: str, server_info: Dict[str, Any]) -> bool:
        """Attempt login to fallback server"""
        try:
            # This would require reconfiguring the connection to use fallback server
            # For now, just log the attempt
            self.logger.info(f"Fallback login attempt to {server_info} (not implemented)")
            return False
        except Exception as e:
            self.logger.warning(f"Fallback login failed: {e}")
            return False
    
    def cleanup(self) -> None:
        """Clean up all resources"""
        self.logger.debug("Cleaning up modular client")
        
        # Disconnect if connected
        if self.is_connected():
            self.disconnect()
        
        # Clean up components
        self.connection.cleanup()
        self.packet_processor.cleanup()
        self.session.cleanup()
        self.resilience.cleanup()
        self.recovery.cleanup()
        
        # Clear event subscriptions
        self.events.clear()
        
        self.logger.debug("Modular client cleanup complete")
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.cleanup()