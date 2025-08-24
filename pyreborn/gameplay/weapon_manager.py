#!/usr/bin/env python3
"""
Weapon Manager - Handles weapon-related packets and weapon state

This manager handles:
- PLO_DEFAULTWEAPON (43) - Default weapon assignment
- PLO_NPCWEAPONADD (33) - NPC weapon additions
- PLO_NPCWEAPONDEL (34) - NPC weapon deletions  
- PLO_CLEARWEAPONS (194) - Clear all weapons
"""

import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from ..protocol.interfaces import IManager
from ..session.events import EventType

logger = logging.getLogger(__name__)


@dataclass
class Weapon:
    """Represents a weapon in the game"""
    name: str
    image: Optional[str] = None
    script: Optional[str] = None
    owner_id: Optional[int] = None  # NPC that owns this weapon
    is_default: bool = False


class WeaponManager(IManager):
    """Manager for handling weapon-related packets and state"""
    
    def __init__(self):
        self.event_manager = None
        self.config = None
        self.logger = logger
        
        # Weapon storage
        self._weapons: Dict[str, Weapon] = {}  # weapon_name -> Weapon
        self._npc_weapons: Dict[int, List[str]] = {}  # npc_id -> [weapon_names]
        self._default_weapon: Optional[str] = None
        
    def initialize(self, config, event_manager) -> None:
        """Initialize the manager"""
        self.config = config
        self.event_manager = event_manager
        logger.info("Weapon manager initialized")
        
    def cleanup(self) -> None:
        """Clean up manager resources"""
        self._weapons.clear()
        self._npc_weapons.clear()
        self._default_weapon = None
        logger.info("Weapon manager cleaned up")
        
    @property
    def name(self) -> str:
        """Get manager name"""
        return "weapon_manager"
        
    def handle_packet(self, packet_id: int, packet_data: Dict[str, Any]) -> None:
        """Handle incoming weapon packets"""
        packet_name = packet_data.get('packet_name', 'UNKNOWN')
        
        logger.debug(f"Weapon manager handling packet: {packet_name} ({packet_id})")
        
        # Route based on packet ID
        if packet_id == 43:  # PLO_DEFAULTWEAPON
            self.handle_plo_defaultweapon(packet_data)
        elif packet_id == 33:  # PLO_NPCWEAPONADD
            self.handle_plo_npcweaponadd(packet_data)
        elif packet_id == 34:  # PLO_NPCWEAPONDEL
            self.handle_plo_npcweapondel(packet_data)
        elif packet_id == 194:  # PLO_CLEARWEAPONS
            self.handle_plo_clearweapons(packet_data)
        else:
            logger.warning(f"Weapon manager received unhandled packet: {packet_name} ({packet_id})")
    
    def handle_plo_defaultweapon(self, packet_data: Dict[str, Any]) -> None:
        """Handle PLO_DEFAULTWEAPON - default weapon assignment"""
        fields = packet_data.get('fields', {})
        weapon_name = fields.get('weapon_name', '')
        weapon_script = fields.get('weapon_script', '')
        
        logger.info(f"⚔️ Default weapon assigned: {weapon_name}")
        
        # Store default weapon
        self._default_weapon = weapon_name
        
        # Create/update weapon entry
        weapon = Weapon(
            name=weapon_name,
            script=weapon_script,
            is_default=True
        )
        self._weapons[weapon_name] = weapon
        
        # Emit event
        if self.event_manager:
            self.event_manager.emit(EventType.WEAPON_EQUIPPED, {
                'weapon_name': weapon_name,
                'is_default': True,
                'script_length': len(weapon_script) if weapon_script else 0
            })
    
    def handle_plo_npcweaponadd(self, packet_data: Dict[str, Any]) -> None:
        """Handle PLO_NPCWEAPONADD - NPC weapon addition"""
        fields = packet_data.get('fields', {})
        npc_id = fields.get('npc_id', 0)
        weapon_name = fields.get('weapon_name', '')
        weapon_image = fields.get('weapon_image', '')
        weapon_script = fields.get('weapon_script', '')
        
        logger.info(f"🗡️ NPC {npc_id} equipped weapon: {weapon_name}")
        
        # Create/update weapon entry
        weapon = Weapon(
            name=weapon_name,
            image=weapon_image,
            script=weapon_script,
            owner_id=npc_id
        )
        self._weapons[weapon_name] = weapon
        
        # Track NPC weapons
        if npc_id not in self._npc_weapons:
            self._npc_weapons[npc_id] = []
        if weapon_name not in self._npc_weapons[npc_id]:
            self._npc_weapons[npc_id].append(weapon_name)
        
        # Emit event
        if self.event_manager:
            self.event_manager.emit(EventType.NPC_WEAPON_CHANGED, {
                'npc_id': npc_id,
                'weapon_name': weapon_name,
                'weapon_image': weapon_image,
                'action': 'add'
            })
    
    def handle_plo_npcweapondel(self, packet_data: Dict[str, Any]) -> None:
        """Handle PLO_NPCWEAPONDEL - NPC weapon deletion"""
        fields = packet_data.get('fields', {})
        npc_id = fields.get('npc_id', 0)
        weapon_name = fields.get('weapon_name', '')
        
        logger.info(f"🗡️ NPC {npc_id} removed weapon: {weapon_name}")
        
        # Remove from NPC weapons
        if npc_id in self._npc_weapons and weapon_name in self._npc_weapons[npc_id]:
            self._npc_weapons[npc_id].remove(weapon_name)
            if not self._npc_weapons[npc_id]:
                del self._npc_weapons[npc_id]
        
        # Don't remove from weapons dict as other NPCs might use it
        
        # Emit event
        if self.event_manager:
            self.event_manager.emit(EventType.NPC_WEAPON_CHANGED, {
                'npc_id': npc_id,
                'weapon_name': weapon_name,
                'action': 'remove'
            })
    
    def handle_plo_clearweapons(self, packet_data: Dict[str, Any]) -> None:
        """Handle PLO_CLEARWEAPONS - clear all weapons"""
        logger.info("⚔️ Clearing all weapons")
        
        # Clear all weapons except default
        weapons_to_remove = [
            name for name, weapon in self._weapons.items()
            if not weapon.is_default
        ]
        
        for name in weapons_to_remove:
            del self._weapons[name]
        
        # Clear NPC weapons
        self._npc_weapons.clear()
        
        # Emit event
        if self.event_manager:
            self.event_manager.emit(EventType.WEAPONS_CLEARED, {
                'weapons_removed': len(weapons_to_remove)
            })
    
    # Public interface methods
    
    def get_default_weapon(self) -> Optional[str]:
        """Get the default weapon name"""
        return self._default_weapon
    
    def get_weapon(self, weapon_name: str) -> Optional[Weapon]:
        """Get a specific weapon by name"""
        return self._weapons.get(weapon_name)
    
    def get_all_weapons(self) -> Dict[str, Weapon]:
        """Get all weapons"""
        return self._weapons.copy()
    
    def get_npc_weapons(self, npc_id: int) -> List[str]:
        """Get weapons for a specific NPC"""
        return self._npc_weapons.get(npc_id, []).copy()
    
    def has_weapon(self, weapon_name: str) -> bool:
        """Check if a weapon exists"""
        return weapon_name in self._weapons
    
    def get_weapon_count(self) -> int:
        """Get total number of weapons"""
        return len(self._weapons)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get weapon manager statistics"""
        return {
            'total_weapons': len(self._weapons),
            'default_weapon': self._default_weapon,
            'npcs_with_weapons': len(self._npc_weapons),
            'total_npc_weapons': sum(len(weapons) for weapons in self._npc_weapons.values())
        }