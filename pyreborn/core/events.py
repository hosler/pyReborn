"""
Events compatibility layer

This file provides backward compatibility for the old events import location.
The actual events module is now part of the consolidated session manager.
"""

# Import from the new consolidated location
from ..session.events import EventType, EventManager

# Re-export for backward compatibility
__all__ = ['EventType', 'EventManager']