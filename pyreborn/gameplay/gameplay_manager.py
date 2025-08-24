"""
Unified Gameplay Manager

This is the main interface for all gameplay functionality, consolidating:
- Combat mechanics and weapons
- Item management and inventory
- NPC interactions and behavior
- Game rules and mechanics
"""

import logging
from typing import Dict, List, Optional, Any

from .combat_manager import CombatManager
from .item_manager import ItemManager
from .npc_manager import NPCManager


class GameplayManager:
    """Unified gameplay management interface"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Core gameplay components
        self.combat = CombatManager()
        self.items = ItemManager()
        self.npcs = NPCManager()
        
        # Game state
        self.gameplay_active = False
        self.game_rules: Dict[str, Any] = {}
        
    def initialize_gameplay(self):
        """Initialize gameplay systems"""
        self.logger.info("Initializing gameplay systems")
        
        # Initialize all subsystems
        if hasattr(self.combat, 'initialize'):
            self.combat.initialize()
        if hasattr(self.items, 'initialize'):
            self.items.initialize()
        if hasattr(self.npcs, 'initialize'):
            self.npcs.initialize()
            
        self.gameplay_active = True
        self.logger.info("Gameplay systems initialized")
        
    def shutdown_gameplay(self):
        """Shutdown gameplay systems"""
        self.logger.info("Shutting down gameplay systems")
        
        self.gameplay_active = False
        
        # Shutdown all subsystems
        if hasattr(self.combat, 'shutdown'):
            self.combat.shutdown()
        if hasattr(self.items, 'shutdown'):
            self.items.shutdown()
        if hasattr(self.npcs, 'shutdown'):
            self.npcs.shutdown()
            
        self.game_rules.clear()
        self.logger.info("Gameplay systems shut down")
        
    def update(self, delta_time: float):
        """Update all gameplay systems"""
        if not self.gameplay_active:
            return
            
        # Update subsystems
        if hasattr(self.combat, 'update'):
            self.combat.update(delta_time)
        if hasattr(self.items, 'update'):
            self.items.update(delta_time)
        if hasattr(self.npcs, 'update'):
            self.npcs.update(delta_time)
            
    def set_game_rule(self, rule_name: str, value: Any):
        """Set a game rule"""
        self.game_rules[rule_name] = value
        self.logger.debug(f"Game rule set: {rule_name} = {value}")
        
    def get_game_rule(self, rule_name: str, default: Any = None) -> Any:
        """Get a game rule value"""
        return self.game_rules.get(rule_name, default)
        
    def is_gameplay_active(self) -> bool:
        """Check if gameplay is active"""
        return self.gameplay_active
        
    def get_gameplay_status(self) -> Dict[str, Any]:
        """Get comprehensive gameplay status"""
        status = {
            'gameplay_active': self.gameplay_active,
            'game_rules': self.game_rules.copy()
        }
        
        # Add subsystem status
        if hasattr(self.combat, 'get_status'):
            status['combat'] = self.combat.get_status()
        if hasattr(self.items, 'get_status'):
            status['items'] = self.items.get_status()
        if hasattr(self.npcs, 'get_status'):
            status['npcs'] = self.npcs.get_status()
            
        return status
        
    def reset_gameplay(self):
        """Reset all gameplay state"""
        self.logger.info("Resetting gameplay state")
        
        # Reset subsystems
        if hasattr(self.combat, 'reset'):
            self.combat.reset()
        if hasattr(self.items, 'reset'):
            self.items.reset()
        if hasattr(self.npcs, 'reset'):
            self.npcs.reset()
            
        self.game_rules.clear()
        self.logger.info("Gameplay state reset")