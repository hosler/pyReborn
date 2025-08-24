#!/usr/bin/env python3
"""
Fluent Builder Pattern for PyReborn Client
==========================================

Provides a discoverable, chainable API for configuring and creating PyReborn clients.
Inspired by modern builder patterns and industry best practices.

Example usage:
    client = (Client.builder()
        .with_server("localhost", 14900)
        .with_version("6.037")
        .with_compression(CompressionType.ZLIB)
        .with_encryption(EncryptionGen.GEN5)
        .with_auto_reconnect(max_retries=3)
        .with_logging(level="DEBUG")
        .build())
"""

from typing import Optional, Dict, Any, Callable
from enum import Enum
import logging

# Import from our protocol enums
from ..protocol.enums import Direction


class CompressionType(Enum):
    """Compression options for client communication"""
    NONE = "none"
    ZLIB = "zlib"
    BZIP2 = "bzip2"
    AUTO = "auto"  # Let client decide based on packet size


class EncryptionGen(Enum):
    """Encryption generation options"""
    GEN1 = "gen1"  # No encryption
    GEN2 = "gen2"  # Basic encryption
    GEN3 = "gen3"  # Zlib compression
    GEN4 = "gen4"  # BZip2 compression
    GEN5 = "gen5"  # Auto compression selection (recommended)


class LogLevel(Enum):
    """Logging level options"""
    DEBUG = "DEBUG"
    INFO = "INFO" 
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ClientBuilder:
    """
    Fluent builder for creating configured PyReborn clients.
    
    Provides a chainable API for setting up all client options before creation.
    """
    
    def __init__(self):
        # Connection settings
        self._host: str = "localhost"
        self._port: int = 14900
        self._version: str = "6.037"
        
        # Protocol settings
        self._compression: CompressionType = CompressionType.AUTO
        self._encryption: EncryptionGen = EncryptionGen.GEN5
        
        # Reliability settings
        self._auto_reconnect: bool = False
        self._max_retries: int = 3
        self._reconnect_delay: float = 1.0
        self._timeout: float = 30.0
        
        # Logging settings
        self._log_level: LogLevel = LogLevel.INFO
        self._log_packets: bool = False
        self._log_to_file: Optional[str] = None
        
        # Event callbacks
        self._event_handlers: Dict[str, Callable] = {}
        
        # Advanced settings
        self._buffer_size: int = 8192
        self._packet_queue_size: int = 1000
        self._enable_metrics: bool = False
        
        # Custom properties
        self._properties: Dict[str, Any] = {}
    
    def with_server(self, host: str, port: int = 14900) -> 'ClientBuilder':
        """
        Configure server connection details.
        
        Args:
            host: Server hostname or IP address
            port: Server port number (default: 14900)
            
        Returns:
            Builder instance for chaining
        """
        self._host = host
        self._port = port
        return self
    
    def with_version(self, version: str) -> 'ClientBuilder':
        """
        Set the protocol version to use.
        
        Args:
            version: Protocol version (e.g., "6.037", "2.22", "2.19")
            
        Returns:
            Builder instance for chaining
        """
        self._version = version
        return self
    
    def with_compression(self, compression: CompressionType) -> 'ClientBuilder':
        """
        Configure compression settings.
        
        Args:
            compression: Compression type to use
            
        Returns:
            Builder instance for chaining
        """
        self._compression = compression
        return self
    
    def with_encryption(self, encryption: EncryptionGen) -> 'ClientBuilder':
        """
        Configure encryption generation.
        
        Args:
            encryption: Encryption generation to use
            
        Returns:
            Builder instance for chaining
        """
        self._encryption = encryption
        return self
    
    def with_auto_reconnect(self, enabled: bool = True, max_retries: int = 3, delay: float = 1.0) -> 'ClientBuilder':
        """
        Configure automatic reconnection behavior.
        
        Args:
            enabled: Whether to enable auto-reconnect
            max_retries: Maximum number of reconnection attempts
            delay: Delay between reconnection attempts in seconds
            
        Returns:
            Builder instance for chaining
        """
        self._auto_reconnect = enabled
        self._max_retries = max_retries
        self._reconnect_delay = delay
        return self
    
    def with_timeout(self, timeout: float) -> 'ClientBuilder':
        """
        Set connection timeout.
        
        Args:
            timeout: Connection timeout in seconds
            
        Returns:
            Builder instance for chaining
        """
        self._timeout = timeout
        return self
    
    def with_logging(self, level: LogLevel = LogLevel.INFO, 
                    log_packets: bool = False, 
                    log_to_file: Optional[str] = None) -> 'ClientBuilder':
        """
        Configure logging options.
        
        Args:
            level: Logging level to use
            log_packets: Whether to log packet details
            log_to_file: Optional file path to write logs to
            
        Returns:
            Builder instance for chaining
        """
        self._log_level = level
        self._log_packets = log_packets
        self._log_to_file = log_to_file
        return self
    
    def with_event_handler(self, event_type: str, handler: Callable) -> 'ClientBuilder':
        """
        Register an event handler.
        
        Args:
            event_type: Type of event to handle (e.g., "player_chat", "player_moved")
            handler: Callback function to handle the event
            
        Returns:
            Builder instance for chaining
        """
        self._event_handlers[event_type] = handler
        return self
    
    def with_performance(self, buffer_size: int = 8192, 
                        queue_size: int = 1000, 
                        enable_metrics: bool = False) -> 'ClientBuilder':
        """
        Configure performance settings.
        
        Args:
            buffer_size: Network buffer size in bytes
            queue_size: Packet queue size
            enable_metrics: Whether to collect performance metrics
            
        Returns:
            Builder instance for chaining
        """
        self._buffer_size = buffer_size
        self._packet_queue_size = queue_size
        self._enable_metrics = enable_metrics
        return self
    
    def with_property(self, key: str, value: Any) -> 'ClientBuilder':
        """
        Set a custom property.
        
        Args:
            key: Property name
            value: Property value
            
        Returns:
            Builder instance for chaining
        """
        self._properties[key] = value
        return self
    
    def build(self) -> 'Client':
        """
        Build and return the configured client.
        
        Returns:
            Configured Client instance
        """
        # Import here to avoid circular imports
        from ..client import Client
        
        # Create client with basic settings
        client = Client(
            host=self._host,
            port=self._port,
            version=self._version
        )
        
        # Apply advanced configuration
        self._apply_logging_config(client)
        self._apply_connection_config(client)
        self._apply_event_handlers(client)
        self._apply_performance_config(client)
        
        return client
    
    def build_and_connect(self, username: str, password: str) -> 'Client':
        """
        Build client and automatically connect and login.
        
        Args:
            username: Account username
            password: Account password
            
        Returns:
            Connected and logged-in Client instance
            
        Raises:
            ConnectionError: If connection or login fails
        """
        client = self.build()
        
        if not client.connect():
            raise ConnectionError(f"Failed to connect to {self._host}:{self._port}")
        
        if not client.login(username, password):
            raise ConnectionError(f"Failed to login as {username}")
        
        return client
    
    def _apply_logging_config(self, client):
        """Apply logging configuration to client"""
        if hasattr(client, '_client') and client._client:
            # Configure logging level
            logger = logging.getLogger('pyreborn')
            logger.setLevel(getattr(logging, self._log_level.value))
            
            if self._log_to_file:
                handler = logging.FileHandler(self._log_to_file)
                formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
                handler.setFormatter(formatter)
                logger.addHandler(handler)
    
    def _apply_connection_config(self, client):
        """Apply connection configuration to client"""
        # Store configuration for future use by the underlying client
        if hasattr(client, '_client') and client._client:
            # Apply compression/encryption settings if supported
            underlying_client = client._client
            
            # Set properties that can be used by connection managers
            if hasattr(underlying_client, 'config'):
                config = underlying_client.config
                config.compression_type = self._compression.value
                config.encryption_gen = self._encryption.value
                config.auto_reconnect = self._auto_reconnect
                config.max_retries = self._max_retries
                config.reconnect_delay = self._reconnect_delay
                config.timeout = self._timeout
                config.buffer_size = self._buffer_size
                config.packet_queue_size = self._packet_queue_size
                config.enable_metrics = self._enable_metrics
                
                # Add custom properties
                for key, value in self._properties.items():
                    setattr(config, key, value)
    
    def _apply_event_handlers(self, client):
        """Apply event handlers to client"""
        if hasattr(client, '_client') and client._client:
            underlying_client = client._client
            
            # Register event handlers if the client supports them
            if hasattr(underlying_client, 'events'):
                for event_type, handler in self._event_handlers.items():
                    try:
                        underlying_client.events.subscribe(event_type, handler)
                    except Exception as e:
                        logging.warning(f"Failed to register event handler for {event_type}: {e}")
    
    def _apply_performance_config(self, client):
        """Apply performance configuration to client"""
        # Performance settings are typically applied at the connection manager level
        # These would be used during connection establishment
        pass


class PresetBuilder:
    """Provides preset configurations for common use cases"""
    
    @staticmethod
    def development() -> ClientBuilder:
        """
        Development preset with debug logging and relaxed settings.
        
        Returns:
            Configured builder for development use
        """
        return (ClientBuilder()
                .with_server("localhost", 14900)
                .with_version("6.037")
                .with_logging(LogLevel.DEBUG, log_packets=True)
                .with_auto_reconnect(enabled=True, max_retries=5, delay=0.5)
                .with_performance(enable_metrics=True))
    
    @staticmethod
    def production() -> ClientBuilder:
        """
        Production preset with optimized settings.
        
        Returns:
            Configured builder for production use
        """
        return (ClientBuilder()
                .with_version("6.037")
                .with_compression(CompressionType.AUTO)
                .with_encryption(EncryptionGen.GEN5)
                .with_logging(LogLevel.WARNING)
                .with_auto_reconnect(enabled=True, max_retries=3, delay=2.0)
                .with_performance(buffer_size=16384, queue_size=2000))
    
    @staticmethod
    def testing() -> ClientBuilder:
        """
        Testing preset with fast reconnects and detailed logging.
        
        Returns:
            Configured builder for testing use
        """
        return (ClientBuilder()
                .with_server("localhost", 14900)
                .with_version("6.037")
                .with_logging(LogLevel.INFO, log_packets=False)
                .with_auto_reconnect(enabled=True, max_retries=1, delay=0.1)
                .with_timeout(5.0))
    
    @staticmethod
    def classic_server() -> ClientBuilder:
        """
        Preset for connecting to classic Reborn servers (older protocol versions).
        
        Returns:
            Configured builder for classic servers
        """
        return (ClientBuilder()
                .with_version("2.22")
                .with_compression(CompressionType.ZLIB)
                .with_encryption(EncryptionGen.GEN3)
                .with_logging(LogLevel.INFO))


# Export commonly used classes and enums
__all__ = [
    'ClientBuilder',
    'PresetBuilder', 
    'CompressionType',
    'EncryptionGen',
    'LogLevel'
]