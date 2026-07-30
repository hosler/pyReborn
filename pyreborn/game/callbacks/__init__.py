"""Export callback wiring entry points."""

from .client_callbacks import wire_client_callbacks
from .gs1_callbacks import wire_gs1_callbacks

__all__ = ["wire_client_callbacks", "wire_gs1_callbacks"]
