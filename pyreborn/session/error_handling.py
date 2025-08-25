"""
Simplified Error Handling - Basic error handling without complex patterns
"""

from enum import Enum
from typing import Any, Callable

class ErrorCategory(Enum):
    """Basic error categories"""
    CONNECTION = "connection"
    PROTOCOL = "protocol"
    AUTHENTICATION = "authentication"
    PARSING = "parsing"
    NETWORK = "network"
    PACKET = "packet"
    
class ErrorSeverity(Enum):
    """Error severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class ErrorHandler:
    """Simple error handler"""
    
    def __init__(self, config=None):
        self.config = config
    
    def handle_error(self, category: ErrorCategory, severity: ErrorSeverity, message: str):
        # Simple logging
        print(f"[{severity.value.upper()}] {category.value}: {message}")
    
    def register_category_handler(self, category, handler):
        # Simple stub for compatibility
        pass
    
    def handle_packet_error(self, *args, **kwargs):
        # Simple stub for packet error handling - accepts any arguments
        pass

def handle_errors(func):
    """Simple error handling decorator"""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            print(f"Error in {func.__name__}: {e}")
            return None
    return wrapper