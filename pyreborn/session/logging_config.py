"""
Logging configuration for PyReborn with clear module prefixes and debug controls
"""

import logging
import os
from typing import Dict, Optional, Set

class ModuleLogger:
    """Custom logger that adds module-specific prefixes and debug control"""
    
    # Module prefix mapping - expanded for better granularity
    MODULE_PREFIXES = {
        # Core components
        'pyreborn.core.client': '[CLIENT]',
        'pyreborn.core.modular_client': '[CLIENT]',
        'pyreborn.core.events': '[EVENT]',
        'pyreborn.core.action_manager': '[ACTION_MGR]',
        
        # Managers
        'pyreborn.managers.level_manager': '[LEVEL_MGR]',
        'pyreborn.managers.gmap_manager': '[GMAP_MGR]',
        'pyreborn.managers.session': '[SESSION_MGR]',
        'pyreborn.managers.npc_manager': '[NPC_MGR]',
        'pyreborn.managers.item_manager': '[ITEM_MGR]',
        'pyreborn.managers.combat_manager': '[COMBAT_MGR]',
        'pyreborn.managers.coordinate_manager': '[COORD_MGR]',
        
        # Actions
        'pyreborn.actions.core_actions': '[ACTIONS]',
        'pyreborn.actions.movement': '[MOVEMENT]',
        'pyreborn.actions.chat': '[CHAT]',
        'pyreborn.actions.items': '[ITEM_ACTIONS]',
        
        # Protocol and handlers
        'pyreborn.handlers.packet_handler': '[PACKET_HANDLER]',
        'pyreborn.protocol': '[PROTOCOL]',
        'pyreborn.protocol.packet_parser': '[PACKET_PARSER]',
        'pyreborn.protocol.protocol_state': '[PROTO_STATE]',
        
        # File and request handling
        'pyreborn.file_request_tracker': '[FILE_REQ]',
        
        # Examples/clients
        'core.connection': '[PG_CONNECTION]',  # pygame client connection
        'core.renderer': '[PG_RENDERER]',      # pygame client renderer
        'core.physics': '[PG_PHYSICS]',        # pygame client physics
        'game.client': '[PG_CLIENT]',          # pygame client main
    }
    
    # Debug subsystems that can be enabled/disabled
    DEBUG_SUBSYSTEMS = {
        'level', 'gmap', 'coords', 'events', 'packet', 'protocol', 
        'movement', 'physics', 'renderer', 'actions', 'files'
    }
    
    # Track which debug subsystems are enabled
    _enabled_debug_subsystems: Set[str] = set()
    
    @classmethod
    def enable_debug_subsystem(cls, subsystem: str) -> None:
        """Enable debug logging for a specific subsystem"""
        if subsystem in cls.DEBUG_SUBSYSTEMS:
            cls._enabled_debug_subsystems.add(subsystem)
        
    @classmethod
    def disable_debug_subsystem(cls, subsystem: str) -> None:
        """Disable debug logging for a specific subsystem"""
        cls._enabled_debug_subsystems.discard(subsystem)
        
    @classmethod
    def is_debug_enabled(cls, subsystem: str) -> bool:
        """Check if debug is enabled for a subsystem"""
        return subsystem in cls._enabled_debug_subsystems
        
    @classmethod
    def get_debug_level_for_module(cls, module_name: str) -> int:
        """Get appropriate debug level for a module based on enabled subsystems"""
        # Check if any debug subsystem applies to this module
        for subsystem in cls._enabled_debug_subsystems:
            if subsystem in module_name.lower():
                return logging.DEBUG
        return logging.INFO
    
    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """Get a logger with appropriate prefix and level for the module"""
        logger = logging.getLogger(name)
        
        # Don't add handler if already configured
        if logger.handlers:
            return logger
            
        # Create handler with custom formatter
        handler = logging.StreamHandler()
        
        # Find the appropriate prefix
        prefix = '[UNKNOWN]'
        for module_name, module_prefix in cls.MODULE_PREFIXES.items():
            if name.startswith(module_name):
                prefix = module_prefix
                break
        
        # Create formatter with prefix
        formatter = ModulePrefixFormatter(prefix)
        handler.setFormatter(formatter)
        
        logger.addHandler(handler)
        
        # Set level based on debug subsystems
        level = cls.get_debug_level_for_module(name)
        logger.setLevel(level)
        logger.propagate = False  # Don't propagate to root logger
        
        return logger


class ModulePrefixFormatter(logging.Formatter):
    """Custom formatter that adds module prefix to log messages"""
    
    def __init__(self, prefix: str):
        self.prefix = prefix
        # Include time, module prefix, level, and message
        super().__init__(
            fmt='%(asctime)s - %(prefix)s %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        )
    
    def format(self, record):
        record.prefix = self.prefix
        return super().format(record)


def configure_logging(level: int = logging.INFO, debug_subsystems: Optional[Set[str]] = None):
    """Configure logging for the entire PyReborn application
    
    Args:
        level: Base logging level for all modules
        debug_subsystems: Set of subsystems to enable debug logging for
    """
    # Set root logger level
    logging.getLogger().setLevel(level)
    
    # Enable debug subsystems if specified
    if debug_subsystems:
        for subsystem in debug_subsystems:
            ModuleLogger.enable_debug_subsystem(subsystem)
    
    # Check environment variables for debug flags
    debug_env = os.environ.get('PYREBORN_DEBUG', '').lower()
    if debug_env:
        env_subsystems = [s.strip() for s in debug_env.split(',')]
        for subsystem in env_subsystems:
            if subsystem == 'all':
                # Enable all debug subsystems
                for s in ModuleLogger.DEBUG_SUBSYSTEMS:
                    ModuleLogger.enable_debug_subsystem(s)
            else:
                ModuleLogger.enable_debug_subsystem(subsystem)
    
    # Configure specific module loggers
    for module_name in ModuleLogger.MODULE_PREFIXES:
        ModuleLogger.get_logger(module_name)


def configure_pygame_client_logging():
    """Configure logging specifically for pygame client examples"""
    # Reduce spam from known noisy modules
    logging.getLogger('pyreborn.handlers.packet_handler').setLevel(logging.WARNING)
    logging.getLogger('pyreborn.core.stream_processor').setLevel(logging.WARNING)
    logging.getLogger('pyreborn.protocol').setLevel(logging.WARNING)
    
    # Pygame client specific modules at warning level by default
    logging.getLogger('core.physics').setLevel(logging.WARNING) 
    logging.getLogger('core.simple_renderer').setLevel(logging.WARNING)


def enable_verbose_logging():
    """Enable verbose logging for all subsystems"""
    for subsystem in ModuleLogger.DEBUG_SUBSYSTEMS:
        ModuleLogger.enable_debug_subsystem(subsystem)
    
    # Reconfigure existing loggers to debug level
    for module_name in ModuleLogger.MODULE_PREFIXES:
        logger = logging.getLogger(module_name)
        logger.setLevel(logging.DEBUG)


def disable_verbose_logging():
    """Disable verbose logging for all subsystems"""
    for subsystem in ModuleLogger.DEBUG_SUBSYSTEMS:
        ModuleLogger.disable_debug_subsystem(subsystem)
    
    # Reconfigure existing loggers to info level
    for module_name in ModuleLogger.MODULE_PREFIXES:
        logger = logging.getLogger(module_name)
        logger.setLevel(logging.INFO)