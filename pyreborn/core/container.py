"""
Container compatibility layer

This file provides backward compatibility for the old container import location.
The actual container functionality is now part of the consolidated protocol module.
"""

# Dependency injection removed for simplicity
# Use direct instantiation instead of complex DI patterns

class SimpleDIContainer:
    """Simplified container - just a basic registry"""
    def __init__(self):
        self._services = {}
    
    def register(self, name: str, instance):
        self._services[name] = instance
    
    def get(self, name: str):
        return self._services.get(name)

DIContainer = SimpleDIContainer  # Compatibility alias
get_container = lambda: SimpleDIContainer()  # Compatibility function

__all__ = ['DIContainer', 'get_container']