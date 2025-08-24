"""
Interfaces compatibility layer

This file provides backward compatibility for the old interfaces import location.
The actual interfaces are now part of the consolidated protocol module.
"""

# Import from the new consolidated location
from ..protocol.interfaces import *

# Re-export all interfaces for backward compatibility