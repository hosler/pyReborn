"""
Client Configuration - Consolidated configuration management
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional


@dataclass
class ClientConfig:
    """Client configuration settings"""
    
    # Connection settings
    host: str = "localhost"
    port: int = 14900
    version: str = "6.037"
    
    # Client behavior
    auto_reconnect: bool = True
    reconnect_delay: float = 5.0
    max_reconnect_attempts: int = 3
    packet_timeout: float = 5.0
    heartbeat_interval: float = 30.0
    connect_timeout: float = 10.0
    
    # Debug settings
    debug: bool = False
    debug_packets: bool = False
    
    # Logging
    log_level: str = "INFO"
    log_packets: bool = False
    
    # Features
    enable_gmap: bool = True
    enable_compression: bool = True
    enable_encryption: bool = True
    
    # Advanced
    max_packet_size: int = 65536
    buffer_size: int = 8192
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'host': self.host,
            'port': self.port,
            'version': self.version,
            'auto_reconnect': self.auto_reconnect,
            'packet_timeout': self.packet_timeout,
            'heartbeat_interval': self.heartbeat_interval,
            'log_level': self.log_level,
            'log_packets': self.log_packets,
            'enable_gmap': self.enable_gmap,
            'enable_compression': self.enable_compression,
            'enable_encryption': self.enable_encryption,
            'max_packet_size': self.max_packet_size,
            'buffer_size': self.buffer_size
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ClientConfig':
        """Create from dictionary"""
        return cls(**data)
    
    def update(self, **kwargs):
        """Update configuration values"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)