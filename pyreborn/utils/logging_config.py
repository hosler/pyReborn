"""
Logging configuration for PyReborn with clear module prefixes
"""

import logging
from typing import Dict, Optional

class ModuleLogger:
    """Custom logger that adds module-specific prefixes"""
    
    # Module prefix mapping
    MODULE_PREFIXES = {
        'pyreborn.core.client': '[CLIENT]',
        'pyreborn.managers.level_manager': '[LEVEL]',
        'pyreborn.managers.gmap_manager': '[GMAP]',
        'pyreborn.actions.core_actions': '[ACTION]',
        'pyreborn.handlers.packet_handler': '[PACKET]',
        'pyreborn.protocol': '[PROTO]',
        'pyreborn.managers.session': '[SESSION]',
        'pyreborn.managers.npc_manager': '[NPC]',
        'pyreborn.managers.item_manager': '[ITEM]',
        'pyreborn.managers.combat_manager': '[COMBAT]',
        'pyreborn.core.events': '[EVENT]',
        'pyreborn.file_request_tracker': '[FILES]',
    }
    
    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """Get a logger with appropriate prefix for the module"""
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
        logger.setLevel(logging.DEBUG)
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


def configure_logging(level: int = logging.INFO):
    """Configure logging for the entire PyReborn application"""
    # Set root logger level
    logging.getLogger().setLevel(level)
    
    # Configure specific module loggers
    for module_name in ModuleLogger.MODULE_PREFIXES:
        ModuleLogger.get_logger(module_name)