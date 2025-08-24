#!/usr/bin/env python3
"""
RC Manager - Central coordinator for Remote Control operations

Handles RC authentication, session management, and command routing.
Integrates with the main pyReborn client for server administration.
"""

import logging
import asyncio
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from enum import IntEnum

logger = logging.getLogger(__name__)


class RCPermission(IntEnum):
    """RC Permission levels"""
    NONE = 0
    BASIC = 1          # Basic commands
    PLAYER_ADMIN = 2   # Player management 
    SERVER_ADMIN = 3   # Server configuration
    FILE_ADMIN = 4     # File management
    SUPER_ADMIN = 5    # Full access


@dataclass
class RCSession:
    """RC Session information"""
    authenticated: bool = False
    permissions: RCPermission = RCPermission.NONE
    username: str = ""
    session_id: str = ""
    active_commands: List[str] = None
    
    def __post_init__(self):
        if self.active_commands is None:
            self.active_commands = []


class RCManager:
    """Central manager for Remote Control functionality"""
    
    def __init__(self, client):
        """Initialize RC Manager with client connection"""
        self.client = client
        self.session = RCSession()
        self.command_handlers: Dict[str, Callable] = {}
        self.response_callbacks: Dict[int, Callable] = {}
        
        # RC packet IDs for responses
        self.rc_packets = {
            35: "RC_ADMINMESSAGE",
            50: "RC_ACCOUNTADD", 
            51: "RC_ACCOUNTSTATUS",
            61: "RC_SERVERFLAGSGET",
            62: "RC_PLAYERRIGHTSGET",
            63: "RC_PLAYERCOMMENTSGET", 
            64: "RC_PLAYERBANGET",
            65: "RC_FILEBROWSER_DIRLIST",
            66: "RC_FILEBROWSER_DIR",
            67: "RC_FILEBROWSER_MESSAGE",
            74: "RC_CHAT",
            75: "PROFILE",
            76: "RC_SERVEROPTIONSGET",
            77: "RC_FOLDERCONFIGGET"
        }
        
        self._setup_packet_handlers()
        logger.info("RC Manager initialized")
    
    def _setup_packet_handlers(self):
        """Register packet handlers for RC responses"""
        for packet_id in self.rc_packets.keys():
            if hasattr(self.client, 'add_packet_handler'):
                self.client.add_packet_handler(packet_id, self._handle_rc_response)
    
    def _handle_rc_response(self, packet_id: int, data: bytes):
        """Handle RC response packets from server"""
        packet_name = self.rc_packets.get(packet_id, f"UNKNOWN_{packet_id}")
        logger.debug(f"Received RC response: {packet_name} (ID: {packet_id})")
        
        # Call registered callback if available
        if packet_id in self.response_callbacks:
            try:
                self.response_callbacks[packet_id](data)
            except Exception as e:
                logger.error(f"Error in RC response callback for {packet_name}: {e}")
    
    def authenticate(self, username: str, password: str) -> bool:
        """
        Authenticate RC session (placeholder - needs server implementation)
        
        In a real implementation, this would:
        1. Send RC authentication packet to server
        2. Wait for authentication response
        3. Set session permissions based on user rights
        """
        logger.info(f"RC Authentication attempt for user: {username}")
        
        # TODO: Implement actual RC authentication protocol
        # For now, assume authentication based on connection success
        if hasattr(self.client, 'connected') and self.client.connected:
            self.session.authenticated = True
            self.session.username = username
            # For demo purposes, give admin users full permissions
            if username.lower() in ['admin', 'administrator', 'root']:
                self.session.permissions = RCPermission.SUPER_ADMIN
            else:
                self.session.permissions = RCPermission.BASIC
            logger.info(f"RC Session authenticated for {username} with {self.session.permissions.name} permissions")
            return True
        
        logger.warning("RC Authentication failed - client not connected")
        return False
    
    def has_permission(self, required: RCPermission) -> bool:
        """Check if current session has required permission level"""
        return self.session.authenticated and self.session.permissions >= required
    
    def send_admin_message(self, message: str) -> bool:
        """Send admin message to all players"""
        if not self.has_permission(RCPermission.PLAYER_ADMIN):
            logger.error("Insufficient permissions for admin message")
            return False
            
        # RC Admin Message packet (Client to Server packet 63)
        try:
            packet_data = self._build_rc_packet(63, message)
            self.client.send_raw_packet(packet_data)
            logger.info(f"Sent admin message: {message[:50]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to send admin message: {e}")
            return False
    
    def disconnect_player(self, player_name: str) -> bool:
        """Disconnect a player from the server"""
        if not self.has_permission(RCPermission.PLAYER_ADMIN):
            logger.error("Insufficient permissions to disconnect player")
            return False
            
        # RC Disconnect Player packet (Client to Server packet 61)
        try:
            packet_data = self._build_rc_packet(61, player_name)
            self.client.send_raw_packet(packet_data)
            logger.info(f"Sent disconnect command for player: {player_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to disconnect player {player_name}: {e}")
            return False
    
    def get_server_flags(self, callback: Optional[Callable] = None) -> bool:
        """Request server flags from server"""
        if not self.has_permission(RCPermission.SERVER_ADMIN):
            logger.error("Insufficient permissions to get server flags")
            return False
            
        # Register callback for response
        if callback:
            self.response_callbacks[61] = callback
            
        # RC Server Flags Get packet (Client to Server packet 68)
        try:
            packet_data = self._build_rc_packet(68, "")
            self.client.send_raw_packet(packet_data)
            logger.info("Requested server flags")
            return True
        except Exception as e:
            logger.error(f"Failed to request server flags: {e}")
            return False
    
    def set_server_flags(self, flags: str) -> bool:
        """Set server flags"""
        if not self.has_permission(RCPermission.SERVER_ADMIN):
            logger.error("Insufficient permissions to set server flags")
            return False
            
        # RC Server Flags Set packet (Client to Server packet 69)
        try:
            packet_data = self._build_rc_packet(69, flags)
            self.client.send_raw_packet(packet_data)
            logger.info(f"Set server flags: {flags}")
            return True
        except Exception as e:
            logger.error(f"Failed to set server flags: {e}")
            return False
    
    def get_player_rights(self, player_name: str, callback: Optional[Callable] = None) -> bool:
        """Get player rights information"""
        if not self.has_permission(RCPermission.PLAYER_ADMIN):
            logger.error("Insufficient permissions to get player rights")
            return False
            
        # Register callback for response
        if callback:
            self.response_callbacks[62] = callback
            
        # RC Player Rights Get packet (Client to Server packet 83)
        try:
            packet_data = self._build_rc_packet(83, player_name)
            self.client.send_raw_packet(packet_data)
            logger.info(f"Requested player rights for: {player_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to request player rights: {e}")
            return False
    
    def _build_rc_packet(self, packet_id: int, data: str) -> bytes:
        """Build RC packet with proper format"""
        # Basic packet format: [PACKET_ID][DATA]
        packet = bytes([packet_id])
        if data:
            # Add string data (most RC commands use GSTRING format)
            packet += data.encode('latin1', errors='ignore') + b'\x00'
        
        return packet
    
    def get_session_info(self) -> Dict[str, Any]:
        """Get current RC session information"""
        return {
            'authenticated': self.session.authenticated,
            'username': self.session.username,
            'permissions': self.session.permissions.name,
            'permission_level': int(self.session.permissions),
            'active_commands': len(self.session.active_commands),
            'available_packets': list(self.rc_packets.keys())
        }
    
    def logout(self):
        """Logout RC session"""
        logger.info(f"RC Session logout for {self.session.username}")
        self.session = RCSession()
        self.response_callbacks.clear()