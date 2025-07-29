"""
Configuration validation utilities
"""

class ConfigValidationError(Exception):
    """Raised when configuration validation fails"""
    pass


def validate_host(host: str) -> str:
    """Validate host address"""
    if not host or not isinstance(host, str):
        raise ConfigValidationError("Host must be a non-empty string")
    
    if len(host.strip()) == 0:
        raise ConfigValidationError("Host cannot be empty or whitespace")
    
    return host.strip()


def validate_port(port: int) -> int:
    """Validate port number"""
    if not isinstance(port, int):
        raise ConfigValidationError("Port must be an integer")
    
    if port < 1 or port > 65535:
        raise ConfigValidationError("Port must be between 1 and 65535")
    
    return port


def validate_version(version: str) -> str:
    """Validate protocol version"""
    valid_versions = ["2.1", "2.19", "2.22", "6.034"]
    
    if not isinstance(version, str):
        raise ConfigValidationError("Version must be a string")
    
    if version not in valid_versions:
        raise ConfigValidationError(f"Version must be one of: {', '.join(valid_versions)}")
    
    return version


def validate_timeout(timeout: float) -> float:
    """Validate timeout value"""
    if not isinstance(timeout, (int, float)):
        raise ConfigValidationError("Timeout must be a number")
    
    if timeout <= 0:
        raise ConfigValidationError("Timeout must be greater than 0")
    
    return float(timeout)