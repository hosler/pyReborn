#!/usr/bin/env python3
"""
RC Manager Adapter - Integrates RC system with ModularRebornClient architecture

This adapter allows the existing RC system to work seamlessly with the 
ModularRebornClient's dependency injection and manager pattern.
"""

import logging
from typing import Optional, Dict, Any
from ..protocol.interfaces import IManager
from ..config.client_config import ClientConfig
from ..session.events import EventManager, EventType
from ..rc import RCClient, RCManager
from ..rc.rc_manager import RCPermission

logger = logging.getLogger(__name__)


class RCManagerAdapter(IManager):
    """Adapter to integrate RC system with ModularRebornClient architecture"""
    
    def __init__(self):
        """Initialize RC manager adapter"""
        self.config: Optional[ClientConfig] = None
        self.events: Optional[EventManager] = None
        self.client = None  # Reference to ModularRebornClient
        
        # RC system components
        self.rc_manager: Optional[RCManager] = None
        self.rc_client: Optional[RCClient] = None
        
        # State tracking
        self._initialized = False
        self._rc_active = False
        
        logger.debug("RC Manager Adapter created")
    
    def initialize(self, config: ClientConfig, event_manager: EventManager) -> None:
        """Initialize the RC manager adapter (IManager interface)"""
        self.config = config
        self.events = event_manager
        
        # Subscribe to RC-related events
        self.events.subscribe(EventType.RC_RIGHTS_RECEIVED, self._on_rc_rights_received)
        self.events.subscribe(EventType.LOGIN_SUCCESS, self._on_login_success)
        self.events.subscribe(EventType.DISCONNECTED, self._on_disconnected)
        
        self._initialized = True
        logger.debug("RC Manager Adapter initialized")
    
    def cleanup(self) -> None:
        """Cleanup resources (IManager interface)"""
        if self._rc_active and self.rc_client:
            try:
                self.rc_client.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting RC client during cleanup: {e}")
        
        self._rc_active = False
        self.rc_manager = None
        self.rc_client = None
        logger.debug("RC Manager Adapter cleaned up")
    
    @property
    def name(self) -> str:
        """Manager name for identification"""
        return "rc_manager_adapter"
    
    def set_client(self, client) -> None:
        """Set reference to ModularRebornClient
        
        Args:
            client: ModularRebornClient instance
        """
        self.client = client
        logger.debug("RC Manager Adapter: client reference set")
    
    def _on_login_success(self, event) -> None:
        """Handle login success - prepare for potential RC initialization"""
        logger.debug("RC Manager Adapter: login success received")
        # RC initialization will happen when rights are received
    
    def _on_disconnected(self, event) -> None:
        """Handle disconnection - cleanup RC session"""
        if self._rc_active:
            logger.info("RC Manager Adapter: disconnecting RC session due to client disconnect")
            self._deactivate_rc_system()
    
    def _on_rc_rights_received(self, event) -> None:
        """Handle RC rights received event - initialize RC system if needed
        
        Args:
            event: Event with RC rights data
        """
        player = event.data.get('player')
        rights_level = event.data.get('rights_level', 0)
        permission_level = event.data.get('permission_level', 'NONE')
        
        if not player or rights_level <= 0:
            logger.debug("RC Manager Adapter: no RC rights, not initializing RC system")
            return
            
        logger.info(f"RC Manager Adapter: initializing RC system for {player.account} with {permission_level} permissions")
        
        try:
            self._initialize_rc_system(player, rights_level)
            
            # Emit RC session started event
            self.events.emit(
                EventType.RC_SESSION_STARTED,
                player=player,
                rights_level=rights_level,
                permission_level=permission_level,
                rc_client=self.rc_client
            )
            
            logger.info(f"🚀 RC system initialized for {player.account}")
            
        except Exception as e:
            logger.error(f"Failed to initialize RC system: {e}")
    
    def _initialize_rc_system(self, player, rights_level: int) -> None:
        """Initialize RC system components
        
        Args:
            player: Local player with RC rights
            rights_level: RC rights level
        """
        if not self.client:
            raise RuntimeError("Cannot initialize RC system: no client reference")
            
        # Create RC manager with client reference
        self.rc_manager = RCManager(self.client)
        
        # Create RC client
        self.rc_client = RCClient(self.client)
        
        # Set up authentication automatically
        # In a real implementation, this would use proper authentication
        # For now, we'll mock the authentication based on rights
        self.rc_client.rc_manager.session.authenticated = True
        self.rc_client.rc_manager.session.username = player.account
        
        # Map rights level to RC permissions
        permission_level = self._map_rights_to_permissions(rights_level)
        self.rc_client.rc_manager.session.permissions = permission_level
        
        # Also set the client state
        self.rc_client.authenticated = True
        self.rc_client.connected = True
        
        self._rc_active = True
        logger.debug(f"RC system initialized with {permission_level.name} permissions")
    
    def _map_rights_to_permissions(self, rights_level: int) -> RCPermission:
        """Map server rights level to RC permission enum
        
        Args:
            rights_level: Rights level from server
            
        Returns:
            RCPermission enum value
        """
        if rights_level >= 5:
            return RCPermission.SUPER_ADMIN
        elif rights_level >= 4:
            return RCPermission.FILE_ADMIN
        elif rights_level >= 3:
            return RCPermission.SERVER_ADMIN
        elif rights_level >= 2:
            return RCPermission.PLAYER_ADMIN
        elif rights_level >= 1:
            return RCPermission.BASIC
        else:
            return RCPermission.NONE
    
    def _deactivate_rc_system(self) -> None:
        """Deactivate RC system"""
        if not self._rc_active:
            return
            
        try:
            if self.rc_client:
                self.rc_client.disconnect()
            
            # Emit RC session ended event
            self.events.emit(EventType.RC_SESSION_ENDED)
            
            logger.info("RC system deactivated")
            
        except Exception as e:
            logger.error(f"Error deactivating RC system: {e}")
        finally:
            self._rc_active = False
            self.rc_manager = None
            self.rc_client = None
    
    # Public API for RC access
    
    def is_rc_active(self) -> bool:
        """Check if RC system is active"""
        return self._rc_active and self.rc_client is not None
    
    def get_rc_client(self) -> Optional[RCClient]:
        """Get RC client instance
        
        Returns:
            RCClient instance if RC is active, None otherwise
        """
        return self.rc_client if self._rc_active else None
    
    def get_rc_status(self) -> Dict[str, Any]:
        """Get RC system status information
        
        Returns:
            Dictionary with RC status information
        """
        if not self._rc_active or not self.rc_client:
            return {
                'active': False,
                'authenticated': False,
                'username': None,
                'permission_level': 'NONE',
                'available_commands': 0
            }
            
        status = self.rc_client.get_status()
        return {
            'active': self._rc_active,
            'authenticated': status['authenticated'],
            'username': status['session']['username'],
            'permission_level': status['session']['permissions'],
            'available_commands': status['available_commands'],
            'total_commands': status['total_commands']
        }
    
    def execute_rc_command(self, command: str, *args, **kwargs) -> bool:
        """Execute RC command
        
        Args:
            command: Command name
            *args: Command arguments
            **kwargs: Command keyword arguments
            
        Returns:
            bool: True if command executed successfully
        """
        if not self._rc_active or not self.rc_client:
            logger.warning(f"Cannot execute RC command '{command}': RC system not active")
            return False
            
        try:
            result = self.rc_client.execute_command(command, *args, **kwargs)
            
            # Emit RC command executed event
            self.events.emit(
                EventType.RC_COMMAND_EXECUTED,
                command=command,
                args=args,
                kwargs=kwargs,
                result=result
            )
            
            return result
            
        except Exception as e:
            logger.error(f"RC command '{command}' execution failed: {e}")
            return False
    
    # High-level RC methods for ModularRebornClient
    
    def send_admin_message(self, message: str) -> bool:
        """Send admin message to all players"""
        if not self._rc_active:
            return False
        return self.rc_client.send_admin_message(message)
    
    def disconnect_player(self, player_name: str, reason: str = "") -> bool:
        """Disconnect player from server"""
        if not self._rc_active:
            return False
        return self.rc_client.disconnect_player(player_name, reason)
    
    def warp_player(self, player_name: str, level: str, x: int = 0, y: int = 0) -> bool:
        """Warp player to location"""
        if not self._rc_active:
            return False
        return self.rc_client.warp_player(player_name, level, x, y)
    
    def browse_server_files(self, directory: str = "/", callback=None) -> bool:
        """Browse server file system"""
        if not self._rc_active:
            return False
        
        # Start file browser if not started
        if not self.rc_client.start_file_browser():
            return False
            
        return self.rc_client.browse_directory(directory, callback)
    
    def upload_file(self, local_path: str, remote_path: str = "", callback=None) -> bool:
        """Upload file to server"""
        if not self._rc_active:
            return False
        return self.rc_client.upload_file(local_path, remote_path, callback)
    
    def download_file(self, file_path: str, callback=None) -> bool:
        """Download file from server"""
        if not self._rc_active:
            return False
        return self.rc_client.download_file(file_path, callback)


# Convenience function for creating RC manager adapter
def create_rc_manager_adapter() -> RCManagerAdapter:
    """Create and return RC manager adapter instance"""
    return RCManagerAdapter()