"""
Plugin & Extension System - Provides extensible architecture for custom functionality
"""

import logging
import importlib
import inspect
from typing import Dict, List, Type, Any, Optional, Callable
from abc import ABC, abstractmethod
from pathlib import Path

from .events import Event, EventType, EventManager
from .interfaces import IPacketHandler
from .middleware import IEventMiddleware


class IPlugin(ABC):
    """Interface for plugins"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Plugin name"""
        pass
    
    @property
    @abstractmethod
    def version(self) -> str:
        """Plugin version"""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Plugin description"""
        pass
    
    @abstractmethod
    def initialize(self, context: 'PluginContext') -> None:
        """Initialize the plugin with context"""
        pass
    
    @abstractmethod
    def cleanup(self) -> None:
        """Clean up plugin resources"""
        pass
    
    def get_dependencies(self) -> List[str]:
        """Get list of required plugin dependencies"""
        return []
    
    def get_packet_handlers(self) -> List[IPacketHandler]:
        """Get packet handlers provided by this plugin"""
        return []
    
    def get_middleware(self) -> List[IEventMiddleware]:
        """Get event middleware provided by this plugin"""
        return []
    
    def get_commands(self) -> Dict[str, Callable]:
        """Get custom commands provided by this plugin"""
        return {}


class PluginContext:
    """Context provided to plugins for accessing system resources"""
    
    def __init__(self, event_manager: EventManager, client=None):
        self.event_manager = event_manager
        self.client = client
        self.logger = logging.getLogger(__name__)
        self._shared_data: Dict[str, Any] = {}
    
    def get_shared_data(self, key: str, default: Any = None) -> Any:
        """Get shared data between plugins"""
        return self._shared_data.get(key, default)
    
    def set_shared_data(self, key: str, value: Any) -> None:
        """Set shared data for other plugins"""
        self._shared_data[key] = value
    
    def emit_event(self, event_type: EventType, **kwargs) -> None:
        """Emit an event"""
        self.event_manager.emit(event_type, **kwargs)
    
    def subscribe_event(self, event_type: EventType, handler: Callable) -> None:
        """Subscribe to an event"""
        self.event_manager.subscribe(event_type, handler)


class PluginManager:
    """Manages plugin loading, initialization, and lifecycle"""
    
    def __init__(self, event_manager: EventManager, client=None):
        self.logger = logging.getLogger(__name__)
        self.event_manager = event_manager
        self.client = client
        self.context = PluginContext(event_manager, client)
        
        # Plugin registry
        self._plugins: Dict[str, IPlugin] = {}
        self._plugin_metadata: Dict[str, Dict[str, Any]] = {}
        self._initialization_order: List[str] = []
        
        # Plugin resources
        self._packet_handlers: Dict[int, List[IPacketHandler]] = {}
        self._middleware: List[IEventMiddleware] = []
        self._commands: Dict[str, Callable] = {}
        
        # Plugin paths
        self._plugin_paths: List[Path] = []
    
    def add_plugin_path(self, path: str) -> None:
        """Add a directory to search for plugins"""
        plugin_path = Path(path)
        if plugin_path.exists() and plugin_path.is_dir():
            self._plugin_paths.append(plugin_path)
            self.logger.debug(f"Added plugin path: {path}")
        else:
            self.logger.warning(f"Plugin path does not exist: {path}")
    
    def register_plugin(self, plugin: IPlugin) -> bool:
        """Register a plugin instance"""
        try:
            name = plugin.name
            
            if name in self._plugins:
                self.logger.warning(f"Plugin {name} is already registered")
                return False
            
            # Store plugin
            self._plugins[name] = plugin
            self._plugin_metadata[name] = {
                'version': plugin.version,
                'description': plugin.description,
                'dependencies': plugin.get_dependencies(),
                'initialized': False
            }
            
            self.logger.info(f"Registered plugin: {name} v{plugin.version}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to register plugin: {e}")
            return False
    
    def load_plugin_from_module(self, module_name: str, plugin_class_name: str = None) -> bool:
        """Load a plugin from a module"""
        try:
            module = importlib.import_module(module_name)
            
            # Find plugin class
            plugin_class = None
            if plugin_class_name:
                plugin_class = getattr(module, plugin_class_name, None)
            else:
                # Search for IPlugin implementation
                for name, obj in inspect.getmembers(module):
                    if (inspect.isclass(obj) and 
                        issubclass(obj, IPlugin) and 
                        obj != IPlugin):
                        plugin_class = obj
                        break
            
            if not plugin_class:
                self.logger.error(f"No plugin class found in module {module_name}")
                return False
            
            # Create plugin instance
            plugin = plugin_class()
            return self.register_plugin(plugin)
            
        except Exception as e:
            self.logger.error(f"Failed to load plugin from module {module_name}: {e}")
            return False
    
    def discover_plugins(self) -> List[str]:
        """Discover plugins in plugin paths"""
        discovered = []
        
        for plugin_path in self._plugin_paths:
            try:
                for file_path in plugin_path.glob("*.py"):
                    if file_path.name.startswith("_"):
                        continue  # Skip private files
                    
                    module_name = file_path.stem
                    spec = importlib.util.spec_from_file_location(module_name, file_path)
                    module = importlib.util.module_from_spec(spec)
                    
                    try:
                        spec.loader.exec_module(module)
                        
                        # Look for plugin classes
                        for name, obj in inspect.getmembers(module):
                            if (inspect.isclass(obj) and 
                                issubclass(obj, IPlugin) and 
                                obj != IPlugin):
                                discovered.append(f"{module_name}.{name}")
                                
                    except Exception as e:
                        self.logger.warning(f"Error loading plugin module {file_path}: {e}")
                        
            except Exception as e:
                self.logger.error(f"Error discovering plugins in {plugin_path}: {e}")
        
        return discovered
    
    def initialize_plugins(self) -> None:
        """Initialize all registered plugins"""
        # Resolve dependency order
        self._resolve_initialization_order()
        
        # Initialize plugins in dependency order
        for plugin_name in self._initialization_order:
            plugin = self._plugins[plugin_name]
            
            try:
                self.logger.info(f"Initializing plugin: {plugin_name}")
                plugin.initialize(self.context)
                
                # Register plugin resources
                self._register_plugin_resources(plugin)
                
                self._plugin_metadata[plugin_name]['initialized'] = True
                self.logger.info(f"Plugin initialized successfully: {plugin_name}")
                
            except Exception as e:
                self.logger.error(f"Failed to initialize plugin {plugin_name}: {e}")
                # Mark as failed but continue with others
                self._plugin_metadata[plugin_name]['initialized'] = False
    
    def cleanup_plugins(self) -> None:
        """Clean up all plugins"""
        # Cleanup in reverse order
        for plugin_name in reversed(self._initialization_order):
            if plugin_name in self._plugins:
                plugin = self._plugins[plugin_name]
                try:
                    plugin.cleanup()
                    self.logger.debug(f"Cleaned up plugin: {plugin_name}")
                except Exception as e:
                    self.logger.error(f"Error cleaning up plugin {plugin_name}: {e}")
        
        # Clear resources
        self._packet_handlers.clear()
        self._middleware.clear()
        self._commands.clear()
        self._plugins.clear()
        self._plugin_metadata.clear()
        self._initialization_order.clear()
    
    def get_plugin(self, name: str) -> Optional[IPlugin]:
        """Get a plugin by name"""
        return self._plugins.get(name)
    
    def get_plugin_info(self, name: str) -> Optional[Dict[str, Any]]:
        """Get plugin information"""
        return self._plugin_metadata.get(name)
    
    def list_plugins(self) -> Dict[str, Dict[str, Any]]:
        """List all registered plugins"""
        return self._plugin_metadata.copy()
    
    def get_packet_handlers(self, packet_id: int) -> List[IPacketHandler]:
        """Get packet handlers for a specific packet ID"""
        return self._packet_handlers.get(packet_id, []).copy()
    
    def get_all_middleware(self) -> List[IEventMiddleware]:
        """Get all registered middleware"""
        return self._middleware.copy()
    
    def get_command(self, command_name: str) -> Optional[Callable]:
        """Get a custom command"""
        return self._commands.get(command_name)
    
    def get_all_commands(self) -> Dict[str, Callable]:
        """Get all custom commands"""
        return self._commands.copy()
    
    def _resolve_initialization_order(self) -> None:
        """Resolve plugin initialization order based on dependencies"""
        # Simple topological sort
        remaining = set(self._plugins.keys())
        resolved = []
        
        while remaining:
            # Find plugins with no unresolved dependencies
            ready = []
            for plugin_name in remaining:
                deps = self._plugin_metadata[plugin_name]['dependencies']
                if all(dep in resolved or dep not in self._plugins for dep in deps):
                    ready.append(plugin_name)
            
            if not ready:
                # Circular dependency or missing dependency
                self.logger.warning("Circular dependency detected or missing dependencies")
                # Add remaining plugins anyway
                ready = list(remaining)
            
            for plugin_name in ready:
                resolved.append(plugin_name)
                remaining.remove(plugin_name)
        
        self._initialization_order = resolved
        self.logger.debug(f"Plugin initialization order: {resolved}")
    
    def _register_plugin_resources(self, plugin: IPlugin) -> None:
        """Register resources provided by a plugin"""
        # Register packet handlers
        for handler in plugin.get_packet_handlers():
            # Determine which packets this handler can process
            # This is a simplified approach - in practice you might want more sophisticated routing
            for packet_id in range(256):  # Check all possible packet IDs
                if handler.can_handle(packet_id):
                    if packet_id not in self._packet_handlers:
                        self._packet_handlers[packet_id] = []
                    self._packet_handlers[packet_id].append(handler)
        
        # Register middleware
        self._middleware.extend(plugin.get_middleware())
        
        # Register commands
        self._commands.update(plugin.get_commands())
        
        self.logger.debug(f"Registered resources for plugin: {plugin.name}")


class BasePlugin(IPlugin):
    """Base plugin class with common functionality"""
    
    def __init__(self):
        self.context: Optional[PluginContext] = None
        self.logger = logging.getLogger(f"{__name__}.{self.name}")
        self._initialized = False
    
    def initialize(self, context: PluginContext) -> None:
        """Initialize the plugin"""
        self.context = context
        self._initialized = True
        self.on_initialize()
    
    def cleanup(self) -> None:
        """Clean up the plugin"""
        self.on_cleanup()
        self._initialized = False
        self.context = None
    
    def on_initialize(self) -> None:
        """Override this method for custom initialization"""
        pass
    
    def on_cleanup(self) -> None:
        """Override this method for custom cleanup"""
        pass
    
    def is_initialized(self) -> bool:
        """Check if plugin is initialized"""
        return self._initialized


# Example plugins
class ExampleLoggerPlugin(BasePlugin):
    """Example plugin that logs specific events"""
    
    @property
    def name(self) -> str:
        return "example_logger"
    
    @property
    def version(self) -> str:
        return "1.0.0"
    
    @property
    def description(self) -> str:
        return "Example plugin that demonstrates event logging"
    
    def on_initialize(self) -> None:
        # Subscribe to events
        self.context.subscribe_event(EventType.LOGIN_SUCCESS, self._on_login)
        self.context.subscribe_event(EventType.DISCONNECTED, self._on_disconnect)
    
    def _on_login(self, event: Event) -> None:
        username = event.data.get('username', 'unknown')
        self.logger.info(f"[PLUGIN] User logged in: {username}")
    
    def _on_disconnect(self, event: Event) -> None:
        self.logger.info("[PLUGIN] User disconnected")


class ExampleStatsPlugin(BasePlugin):
    """Example plugin that collects statistics"""
    
    def __init__(self):
        super().__init__()
        self.event_count = 0
        self.login_count = 0
    
    @property
    def name(self) -> str:
        return "example_stats"
    
    @property
    def version(self) -> str:
        return "1.0.0"
    
    @property
    def description(self) -> str:
        return "Example plugin that collects usage statistics"
    
    def on_initialize(self) -> None:
        # Subscribe to all events via a generic handler
        # In practice, you'd be more selective
        self.context.subscribe_event(EventType.LOGIN_SUCCESS, self._count_login)
    
    def _count_login(self, event: Event) -> None:
        self.login_count += 1
        self.event_count += 1
    
    def get_stats(self) -> Dict[str, int]:
        """Get collected statistics"""
        return {
            'total_events': self.event_count,
            'login_count': self.login_count
        }