"""
Centralized configuration for pyReborn clients
"""

import os
from typing import Optional, Dict, Any
from .validation import (
    validate_host, validate_port, validate_version, 
    validate_timeout, ConfigValidationError
)


class ClientConfig:
    """Centralized configuration for pyReborn clients
    
    Supports environment variables and provides validation for all settings.
    Environment variables use the format: PYREBORN_{SETTING_NAME}
    """
    
    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        version: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        cache_dir: Optional[str] = None,
        disable_cache: Optional[bool] = None,
        connect_timeout: Optional[float] = None,
        login_timeout: Optional[float] = None,
        packet_timeout: Optional[float] = None,
        enable_compression: Optional[bool] = None,
        debug_packets: Optional[bool] = None,
        max_reconnect_attempts: Optional[int] = None,
        reconnect_delay: Optional[float] = None,
        **kwargs
    ):
        """Initialize configuration with optional overrides
        
        Args:
            host: Server hostname or IP
            port: Server port (default: 14900)
            version: Protocol version (default: "2.22")
            username: Login username
            password: Login password
            cache_dir: Directory for file caching
            disable_cache: Disable file caching entirely
            connect_timeout: Timeout for initial connection (seconds)
            login_timeout: Timeout for login process (seconds)
            packet_timeout: Timeout for individual packets (seconds)
            enable_compression: Enable packet compression
            debug_packets: Enable packet debugging output
            max_reconnect_attempts: Maximum reconnection attempts
            reconnect_delay: Delay between reconnection attempts (seconds)
            **kwargs: Additional configuration options
        """
        
        # Connection settings
        self.host = self._get_setting('host', host, str, 'localhost')
        self.port = self._get_setting('port', port, int, 14900)
        self.version = self._get_setting('version', version, str, '2.22')
        
        # Authentication settings
        self.username = self._get_setting('username', username, str, None)
        self.password = self._get_setting('password', password, str, None)
        
        # Caching settings
        self.cache_dir = self._get_setting('cache_dir', cache_dir, str, None)
        self.disable_cache = self._get_setting('disable_cache', disable_cache, bool, False)
        
        # Timeout settings
        self.connect_timeout = self._get_setting('connect_timeout', connect_timeout, float, 10.0)
        self.login_timeout = self._get_setting('login_timeout', login_timeout, float, 15.0)
        self.packet_timeout = self._get_setting('packet_timeout', packet_timeout, float, 5.0)
        
        # Protocol settings
        self.enable_compression = self._get_setting('enable_compression', enable_compression, bool, True)
        self.debug_packets = self._get_setting('debug_packets', debug_packets, bool, False)
        
        # Resilience settings
        self.max_reconnect_attempts = self._get_setting('max_reconnect_attempts', max_reconnect_attempts, int, 3)
        self.reconnect_delay = self._get_setting('reconnect_delay', reconnect_delay, float, 2.0)
        
        # Store additional settings
        self.additional_settings = kwargs
        
        # Validate all settings
        self._validate()
    
    def _get_setting(self, name: str, value: Any, expected_type: type, default: Any) -> Any:
        """Get setting value with environment variable fallback"""
        if value is not None:
            return value
        
        # Check environment variable
        env_name = f"PYREBORN_{name.upper()}"
        env_value = os.environ.get(env_name)
        
        if env_value is not None:
            # Convert string environment value to expected type
            if expected_type == bool:
                return env_value.lower() in ('true', '1', 'yes', 'on')
            elif expected_type == int:
                return int(env_value)
            elif expected_type == float:
                return float(env_value)
            else:
                return env_value
        
        return default
    
    def _validate(self):
        """Validate all configuration settings"""
        try:
            self.host = validate_host(self.host)
            self.port = validate_port(self.port)
            self.version = validate_version(self.version)
            self.connect_timeout = validate_timeout(self.connect_timeout)
            self.login_timeout = validate_timeout(self.login_timeout)
            self.packet_timeout = validate_timeout(self.packet_timeout)
            self.reconnect_delay = validate_timeout(self.reconnect_delay)
            
            if self.max_reconnect_attempts < 0:
                raise ConfigValidationError("max_reconnect_attempts must be >= 0")
                
        except (ValueError, TypeError) as e:
            raise ConfigValidationError(f"Configuration validation failed: {e}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary"""
        result = {
            'host': self.host,
            'port': self.port,
            'version': self.version,
            'username': self.username,
            'password': self.password,
            'cache_dir': self.cache_dir,
            'disable_cache': self.disable_cache,
            'connect_timeout': self.connect_timeout,
            'login_timeout': self.login_timeout,
            'packet_timeout': self.packet_timeout,
            'enable_compression': self.enable_compression,
            'debug_packets': self.debug_packets,
            'max_reconnect_attempts': self.max_reconnect_attempts,
            'reconnect_delay': self.reconnect_delay,
        }
        result.update(self.additional_settings)
        return result
    
    def update(self, **kwargs):
        """Update configuration with new values"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
            else:
                self.additional_settings[key] = value
        
        # Re-validate after updates
        self._validate()
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value with fallback to additional settings"""
        if hasattr(self, key):
            return getattr(self, key)
        return self.additional_settings.get(key, default)
    
    def __repr__(self) -> str:
        """String representation hiding sensitive data"""
        safe_dict = self.to_dict().copy()
        if safe_dict.get('password'):
            safe_dict['password'] = '***'
        return f"ClientConfig({safe_dict})"