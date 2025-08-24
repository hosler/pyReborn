"""
Container compatibility layer

This file provides backward compatibility for the old container import location.
The actual container functionality is now part of the consolidated protocol module.
"""

# Import from the new consolidated location
from ..protocol.container import DIContainer, get_container

# Re-export for backward compatibility
__all__ = ['DIContainer', 'get_container']