"""
Packet registry compatibility module

This module provides compatibility access to the packet registry from the internal architecture.
"""

# Re-export the packet registry for compatibility
try:
    from ..packets import PACKET_REGISTRY
except ImportError:
    # Fallback for cases where internal structure is not available
    PACKET_REGISTRY = None

__all__ = ['PACKET_REGISTRY']