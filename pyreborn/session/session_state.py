"""
Session State Management

Defines all session states and authentication statuses used throughout the system.
"""

from enum import Enum


class SessionState(Enum):
    """Overall session state"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    AUTHENTICATING = "authenticating"
    AUTHENTICATED = "authenticated"
    ACTIVE = "active"
    LOGIN_FAILED = "login_failed"
    RECONNECTING = "reconnecting"


class AuthenticationStatus(Enum):
    """Authentication process status"""
    NONE = "none"
    PENDING = "pending"
    AUTHENTICATED = "authenticated"
    FAILED = "failed"
    TIMEOUT = "timeout"


class PlayerStatus(Enum):
    """Player status within the game world"""
    OFFLINE = "offline"
    ONLINE = "online"
    IDLE = "idle"
    ACTIVE = "active"
    BUSY = "busy"