"""
Interfaces for pyReborn components to enable dependency injection
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List, Callable
from ..core.events import EventManager
from ..config.client_config import ClientConfig


class IManager(ABC):
    """Base interface for all managers"""
    
    @abstractmethod
    def initialize(self, config: ClientConfig, event_manager: EventManager) -> None:
        """Initialize the manager with configuration and event system"""
        pass
    
    @abstractmethod
    def cleanup(self) -> None:
        """Clean up resources when shutting down"""
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Manager name for identification"""
        pass


class ISessionManager(IManager):
    """Interface for session management"""
    
    @abstractmethod
    def get_player(self) -> Optional[Any]:
        """Get current player object"""
        pass
    
    @abstractmethod
    def set_player(self, player: Any) -> None:
        """Set current player object"""
        pass
    
    @abstractmethod
    def is_logged_in(self) -> bool:
        """Check if player is logged in"""
        pass


class ILevelManager(IManager):
    """Interface for level management"""
    
    @abstractmethod
    def get_current_level(self) -> Optional[Any]:
        """Get current level object"""
        pass
    
    @abstractmethod
    def load_level(self, level_name: str) -> bool:
        """Load a specific level"""
        pass
    
    @abstractmethod
    def get_level_cache(self) -> Dict[str, Any]:
        """Get cached levels"""
        pass


class IItemManager(IManager):
    """Interface for item management"""
    
    @abstractmethod
    def get_player_items(self) -> List[Any]:
        """Get player's current items"""
        pass
    
    @abstractmethod
    def add_item(self, item: Any) -> None:
        """Add item to player inventory"""
        pass
    
    @abstractmethod
    def remove_item(self, item_id: str) -> bool:
        """Remove item from inventory"""
        pass


class ICombatManager(IManager):
    """Interface for combat management"""
    
    @abstractmethod
    def handle_damage(self, source: Any, target: Any, damage: float) -> None:
        """Handle damage between entities"""
        pass
    
    @abstractmethod
    def is_in_combat(self, player: Any) -> bool:
        """Check if player is in combat"""
        pass


class INPCManager(IManager):
    """Interface for NPC management"""
    
    @abstractmethod
    def get_npcs(self) -> List[Any]:
        """Get all NPCs in current area"""
        pass
    
    @abstractmethod
    def get_npc_by_id(self, npc_id: str) -> Optional[Any]:
        """Get specific NPC by ID"""
        pass


class IConnectionManager(IManager):
    """Interface for connection management"""
    
    @abstractmethod
    def connect(self, host: str, port: int) -> bool:
        """Establish connection to server"""
        pass
    
    @abstractmethod
    def disconnect(self) -> None:
        """Close connection to server"""
        pass
    
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if connected to server"""
        pass
    
    @abstractmethod
    def send_packet(self, packet_data: bytes) -> bool:
        """Send packet to server"""
        pass


class IPacketProcessor(IManager):
    """Interface for packet processing"""
    
    @abstractmethod
    def process_packet(self, packet_id: int, packet_data: bytes) -> None:
        """Process incoming packet"""
        pass
    
    @abstractmethod
    def register_handler(self, packet_id: int, handler: Callable) -> None:
        """Register packet handler"""
        pass


class IPacketHandler(ABC):
    """Interface for packet handlers"""
    
    @abstractmethod
    def can_handle(self, packet_id: int) -> bool:
        """Check if this handler can process the packet"""
        pass
    
    @abstractmethod
    def handle(self, packet_id: int, packet_data: bytes, context: Dict[str, Any]) -> Any:
        """Handle the packet and return result"""
        pass
    
    @property
    @abstractmethod
    def priority(self) -> int:
        """Handler priority (higher = processed first)"""
        pass