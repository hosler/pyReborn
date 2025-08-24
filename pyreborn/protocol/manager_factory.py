"""
Manager Factory - Provides discovery and creation of managers
"""

import logging
from typing import Dict, Type, List, Optional, Any

from .interfaces import IManager, ISessionManager, ILevelManager, IItemManager, ICombatManager, INPCManager
from .container import DIContainer


class ManagerRegistry:
    """Registry for manager implementations"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._implementations: Dict[Type, Dict[str, Type]] = {}
        self._default_implementations: Dict[Type, Type] = {}
        
    def register_implementation(self, interface: Type, implementation: Type, name: str = None) -> None:
        """Register a manager implementation"""
        if interface not in self._implementations:
            self._implementations[interface] = {}
        
        impl_name = name or implementation.__name__
        self._implementations[interface][impl_name] = implementation
        
        self.logger.debug(f"Registered {interface.__name__} implementation: {impl_name}")
    
    def set_default_implementation(self, interface: Type, implementation: Type) -> None:
        """Set the default implementation for an interface"""
        self._default_implementations[interface] = implementation
        self.logger.debug(f"Set default {interface.__name__} implementation: {implementation.__name__}")
    
    def get_implementation(self, interface: Type, name: str = None) -> Optional[Type]:
        """Get a specific implementation"""
        if name:
            return self._implementations.get(interface, {}).get(name)
        else:
            return self._default_implementations.get(interface)
    
    def get_available_implementations(self, interface: Type) -> List[str]:
        """Get list of available implementation names"""
        return list(self._implementations.get(interface, {}).keys())
    
    def has_implementation(self, interface: Type, name: str = None) -> bool:
        """Check if implementation exists"""
        if name:
            return interface in self._implementations and name in self._implementations[interface]
        else:
            return interface in self._default_implementations


class ManagerFactory:
    """Factory for creating and managing manager instances"""
    
    def __init__(self, container: DIContainer = None, registry: ManagerRegistry = None):
        self.logger = logging.getLogger(__name__)
        self.container = container
        self.registry = registry or ManagerRegistry()
        self._manager_instances: Dict[Type, Dict[str, IManager]] = {}
        
        # Register standard implementations
        self._register_standard_implementations()
    
    def _register_standard_implementations(self) -> None:
        """Register the standard manager implementations"""
        try:
            # Import standard implementations
            from .standardized_session_manager import StandardizedSessionManager
            from .standardized_level_manager import StandardizedLevelManager
            from .standardized_item_manager import StandardizedItemManager
            
            # Register them
            self.registry.register_implementation(ISessionManager, StandardizedSessionManager, "standardized")
            self.registry.register_implementation(ILevelManager, StandardizedLevelManager, "standardized")
            self.registry.register_implementation(IItemManager, StandardizedItemManager, "standardized")
            
            # Set as defaults
            self.registry.set_default_implementation(ISessionManager, StandardizedSessionManager)
            self.registry.set_default_implementation(ILevelManager, StandardizedLevelManager)
            self.registry.set_default_implementation(IItemManager, StandardizedItemManager)
            
            self.logger.debug("Registered standard manager implementations")
            
        except ImportError as e:
            self.logger.warning(f"Failed to register some standard implementations: {e}")
    
    def create_manager(self, interface: Type, name: str = None, **kwargs) -> Optional[IManager]:
        """Create a manager instance"""
        implementation = self.registry.get_implementation(interface, name)
        
        if not implementation:
            self.logger.error(f"No implementation found for {interface.__name__}" + 
                            (f" with name '{name}'" if name else ""))
            return None
        
        try:
            # Create instance
            if self.container:
                # Try to use DI container if available
                try:
                    instance = self.container.resolve(implementation)
                except:
                    # Fall back to direct instantiation
                    instance = implementation(**kwargs)
            else:
                instance = implementation(**kwargs)
            
            # Cache the instance
            if interface not in self._manager_instances:
                self._manager_instances[interface] = {}
            
            instance_name = name or "default"
            self._manager_instances[interface][instance_name] = instance
            
            self.logger.debug(f"Created {interface.__name__} instance: {implementation.__name__}")
            return instance
            
        except Exception as e:
            self.logger.error(f"Failed to create {interface.__name__} instance: {e}")
            return None
    
    def get_manager(self, interface: Type, name: str = None) -> Optional[IManager]:
        """Get an existing manager instance"""
        instance_name = name or "default"
        return self._manager_instances.get(interface, {}).get(instance_name)
    
    def get_or_create_manager(self, interface: Type, name: str = None, **kwargs) -> Optional[IManager]:
        """Get existing manager or create new one"""
        manager = self.get_manager(interface, name)
        if manager:
            return manager
        
        return self.create_manager(interface, name, **kwargs)
    
    def register_manager_instance(self, interface: Type, instance: IManager, name: str = None) -> None:
        """Register a pre-created manager instance"""
        if interface not in self._manager_instances:
            self._manager_instances[interface] = {}
        
        instance_name = name or "default"
        self._manager_instances[interface][instance_name] = instance
        
        self.logger.debug(f"Registered {interface.__name__} instance: {instance_name}")
    
    def cleanup_manager(self, interface: Type, name: str = None) -> None:
        """Clean up a specific manager"""
        instance_name = name or "default"
        
        if interface in self._manager_instances and instance_name in self._manager_instances[interface]:
            manager = self._manager_instances[interface][instance_name]
            
            try:
                manager.cleanup()
            except Exception as e:
                self.logger.error(f"Error cleaning up {interface.__name__}: {e}")
            
            del self._manager_instances[interface][instance_name]
            self.logger.debug(f"Cleaned up {interface.__name__} instance: {instance_name}")
    
    def cleanup_all_managers(self) -> None:
        """Clean up all manager instances"""
        for interface, instances in self._manager_instances.items():
            for name, manager in list(instances.items()):
                try:
                    manager.cleanup()
                except Exception as e:
                    self.logger.error(f"Error cleaning up {interface.__name__}[{name}]: {e}")
        
        self._manager_instances.clear()
        self.logger.debug("Cleaned up all managers")
    
    def get_manager_info(self) -> Dict[str, Any]:
        """Get information about registered managers"""
        info = {
            'implementations': {},
            'instances': {},
            'defaults': {}
        }
        
        # Get implementation info
        for interface, impls in self.registry._implementations.items():
            info['implementations'][interface.__name__] = list(impls.keys())
        
        # Get instance info
        for interface, instances in self._manager_instances.items():
            info['instances'][interface.__name__] = list(instances.keys())
        
        # Get default info
        for interface, impl in self.registry._default_implementations.items():
            info['defaults'][interface.__name__] = impl.__name__
        
        return info
    
    def register_custom_implementation(self, interface: Type, implementation: Type, 
                                     name: str, set_as_default: bool = False) -> None:
        """Register a custom manager implementation"""
        self.registry.register_implementation(interface, implementation, name)
        
        if set_as_default:
            self.registry.set_default_implementation(interface, implementation)
    
    def discover_managers(self, package_path: str = None) -> List[Type]:
        """Discover manager implementations in a package"""
        # This could be enhanced to automatically discover managers
        # For now, return the standard ones
        discovered = []
        
        try:
            from .standardized_session_manager import StandardizedSessionManager
            from .standardized_level_manager import StandardizedLevelManager
            from .standardized_item_manager import StandardizedItemManager
            
            discovered.extend([
                StandardizedSessionManager,
                StandardizedLevelManager,
                StandardizedItemManager
            ])
            
        except ImportError:
            pass
        
        return discovered


# Global factory instance
_global_factory: Optional[ManagerFactory] = None


def get_manager_factory() -> ManagerFactory:
    """Get the global manager factory"""
    global _global_factory
    if _global_factory is None:
        _global_factory = ManagerFactory()
    return _global_factory


def set_manager_factory(factory: ManagerFactory) -> None:
    """Set the global manager factory"""
    global _global_factory
    _global_factory = factory


def create_manager(interface: Type, name: str = None, **kwargs) -> Optional[IManager]:
    """Convenience function to create a manager"""
    return get_manager_factory().create_manager(interface, name, **kwargs)


def get_manager(interface: Type, name: str = None) -> Optional[IManager]:
    """Convenience function to get a manager"""
    return get_manager_factory().get_manager(interface, name)