"""
Dependency injection container for pyReborn
"""

import logging
from typing import Any, Dict, Type, TypeVar, Callable, Optional, List
from enum import Enum

T = TypeVar('T')
logger = logging.getLogger(__name__)


class LifetimeScope(Enum):
    """Dependency lifetime scopes"""
    SINGLETON = "singleton"  # One instance per container
    TRANSIENT = "transient"  # New instance every time
    SCOPED = "scoped"        # One instance per scope/request


class DIContainer:
    """Dependency injection container
    
    Provides registration and resolution of dependencies with lifetime management.
    """
    
    def __init__(self, parent: Optional['DIContainer'] = None):
        self.parent = parent
        self._registrations: Dict[Type, Dict[str, Any]] = {}
        self._instances: Dict[str, Any] = {}
        self._resolving: set = set()  # Circular dependency detection
        
    def register(
        self,
        interface: Type[T],
        implementation: Type[T] = None,
        factory: Callable[[], T] = None,
        instance: T = None,
        lifetime: LifetimeScope = LifetimeScope.SINGLETON,
        name: str = None
    ) -> 'DIContainer':
        """Register a dependency
        
        Args:
            interface: The interface/type to register
            implementation: The concrete implementation class
            factory: Factory function that creates instances
            instance: Pre-created instance to use
            lifetime: Lifetime scope for the dependency
            name: Optional name for named registrations
            
        Returns:
            Self for method chaining
        """
        key = name or interface.__name__
        
        if sum(x is not None for x in [implementation, factory, instance]) != 1:
            raise ValueError("Must provide exactly one of: implementation, factory, or instance")
        
        registration = {
            'interface': interface,
            'implementation': implementation,
            'factory': factory,
            'instance': instance,
            'lifetime': lifetime,
            'name': name
        }
        
        if interface not in self._registrations:
            self._registrations[interface] = {}
        
        self._registrations[interface][key] = registration
        
        logger.debug(f"Registered {interface.__name__} -> {key} ({lifetime.value})")
        return self
    
    def register_singleton(self, interface: Type[T], implementation: Type[T] = None, **kwargs) -> 'DIContainer':
        """Register as singleton"""
        return self.register(interface, implementation, lifetime=LifetimeScope.SINGLETON, **kwargs)
    
    def register_transient(self, interface: Type[T], implementation: Type[T] = None, **kwargs) -> 'DIContainer':
        """Register as transient"""
        return self.register(interface, implementation, lifetime=LifetimeScope.TRANSIENT, **kwargs)
    
    def register_instance(self, interface: Type[T], instance: T, **kwargs) -> 'DIContainer':
        """Register pre-created instance"""
        return self.register(interface, instance=instance, **kwargs)
    
    def resolve(self, interface: Type[T], name: str = None) -> T:
        """Resolve a dependency
        
        Args:
            interface: The interface/type to resolve
            name: Optional name for named resolution
            
        Returns:
            Instance of the requested type
        """
        # Handle string type annotations (forward references)
        if isinstance(interface, str):
            # For now, we can't resolve string annotations without more context
            raise RuntimeError(f"Cannot resolve string type annotation: {interface}")
        
        key = name or interface.__name__
        circular_key = f"{interface.__name__}:{key}"
        
        # Check for circular dependencies
        if circular_key in self._resolving:
            raise RuntimeError(f"Circular dependency detected: {circular_key}")
        
        try:
            self._resolving.add(circular_key)
            return self._do_resolve(interface, key)
        finally:
            self._resolving.discard(circular_key)
    
    def _do_resolve(self, interface: Type[T], key: str) -> T:
        """Internal resolution method"""
        
        # Check local registrations first
        if interface in self._registrations and key in self._registrations[interface]:
            registration = self._registrations[interface][key]
            return self._create_instance(registration, key)
        
        # Check parent container if not found locally
        if self.parent:
            try:
                return self.parent.resolve(interface, key if key != interface.__name__ else None)
            except KeyError:
                pass
        
        # Try to auto-resolve if it's a concrete class
        if hasattr(interface, '__init__') and not getattr(interface, '__abstractmethods__', None):
            logger.debug(f"Auto-resolving concrete class: {interface.__name__}")
            return self._auto_resolve(interface)
        
        raise KeyError(f"No registration found for {interface.__name__}:{key}")
    
    def _create_instance(self, registration: Dict[str, Any], key: str) -> Any:
        """Create instance based on registration"""
        lifetime = registration['lifetime']
        
        # For singletons, check if we already have an instance
        if lifetime == LifetimeScope.SINGLETON:
            instance_key = f"{registration['interface'].__name__}:{key}"
            if instance_key in self._instances:
                return self._instances[instance_key]
        
        # Create new instance
        if registration['instance'] is not None:
            instance = registration['instance']
        elif registration['factory'] is not None:
            instance = registration['factory']()
        elif registration['implementation'] is not None:
            instance = self._auto_resolve(registration['implementation'])
        else:
            raise RuntimeError(f"Invalid registration for {key}")
        
        # Cache singletons
        if lifetime == LifetimeScope.SINGLETON:
            instance_key = f"{registration['interface'].__name__}:{key}"
            self._instances[instance_key] = instance
        
        return instance
    
    def _auto_resolve(self, cls: Type[T]) -> T:
        """Auto-resolve a class by analyzing its constructor"""
        import inspect
        
        # Get constructor signature
        sig = inspect.signature(cls.__init__)
        
        # Resolve constructor arguments
        args = {}
        for param_name, param in sig.parameters.items():
            if param_name == 'self':
                continue
                
            if param.annotation != inspect.Parameter.empty:
                # Skip string annotations (forward references) for now
                if isinstance(param.annotation, str):
                    if param.default != inspect.Parameter.empty:
                        args[param_name] = param.default
                    else:
                        raise RuntimeError(f"Cannot resolve string type annotation: {param.annotation}")
                    continue
                
                # Try to resolve the parameter type
                try:
                    args[param_name] = self.resolve(param.annotation)
                except KeyError:
                    if param.default != inspect.Parameter.empty:
                        # Use default value
                        args[param_name] = param.default
                    else:
                        raise RuntimeError(f"Cannot resolve parameter {param_name} of type {param.annotation}")
            elif param.default != inspect.Parameter.empty:
                args[param_name] = param.default
            else:
                raise RuntimeError(f"Cannot resolve parameter {param_name} (no type annotation)")
        
        return cls(**args)
    
    def resolve_all(self, interface: Type[T]) -> List[T]:
        """Resolve all registrations for an interface"""
        instances = []
        
        if interface in self._registrations:
            for key, registration in self._registrations[interface].items():
                instances.append(self._create_instance(registration, key))
        
        # Include parent registrations
        if self.parent:
            try:
                instances.extend(self.parent.resolve_all(interface))
            except KeyError:
                pass
        
        return instances
    
    def is_registered(self, interface: Type, name: str = None) -> bool:
        """Check if interface is registered"""
        key = name or interface.__name__
        
        if interface in self._registrations and key in self._registrations[interface]:
            return True
        
        if self.parent:
            return self.parent.is_registered(interface, name)
        
        return False
    
    def create_scope(self) -> 'DIContainer':
        """Create a child scope"""
        return DIContainer(parent=self)
    
    def clear(self):
        """Clear all registrations and instances"""
        self._registrations.clear()
        self._instances.clear()
        
    def get_registrations(self) -> Dict[Type, Dict[str, Any]]:
        """Get all registrations (for debugging)"""
        return self._registrations.copy()


# Global container instance
_global_container = DIContainer()


def get_container() -> DIContainer:
    """Get the global container instance"""
    return _global_container


def set_container(container: DIContainer):
    """Set the global container instance"""
    global _global_container
    _global_container = container