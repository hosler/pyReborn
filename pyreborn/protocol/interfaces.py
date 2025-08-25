"""
Simplified interfaces - removed complex abstractions

Instead of complex interface hierarchies, we use simple base classes.
"""

class IManager:
    """Simple base class for managers (replaces complex interface)"""
    def initialize(self, config, event_manager):
        pass
    
    def cleanup(self):
        pass
    
    @property
    def name(self):
        return self.__class__.__name__

class IPacketProcessor:
    """Simple base for packet processors"""
    pass

class IConnectionManager:
    """Simple base for connection managers"""
    pass

# Other simple stubs for compatibility
class IPacketHandler:
    pass

class ISessionManager(IManager):
    pass

class ILevelManager(IManager):
    pass

class IItemManager(IManager):
    pass

class ICombatManager(IManager):
    pass

class INPCManager(IManager):
    pass

class IWeaponManager(IManager):
    pass