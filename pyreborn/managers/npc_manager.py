"""
Enhanced NPC management system for PyReborn
"""

from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class NPCData:
    """Extended NPC data beyond basic properties"""
    id: int
    level: str
    x: float
    y: float
    image: str = ""
    script: str = ""
    name: str = ""
    type: str = ""
    
    # Extended properties
    saves: Dict[int, Any] = field(default_factory=dict)  # save0-save9
    gattribs: Dict[int, Any] = field(default_factory=dict)  # gattrib1-30
    flags: Dict[str, Any] = field(default_factory=dict)
    
    # Interaction state
    last_interaction: float = 0
    touch_enabled: bool = True
    visible: bool = True
    blocking: bool = False
    
    def set_save(self, index: int, value: Any):
        """Set a save value (0-9)"""
        if 0 <= index <= 9:
            self.saves[index] = value
            
    def get_save(self, index: int, default: Any = None) -> Any:
        """Get a save value"""
        return self.saves.get(index, default)
        
    def set_gattrib(self, index: int, value: Any):
        """Set a gattrib value (1-30)"""
        if 1 <= index <= 30:
            self.gattribs[index] = value
            
    def get_gattrib(self, index: int, default: Any = None) -> Any:
        """Get a gattrib value"""
        return self.gattribs.get(index, default)


class NPCManager:
    """Manages NPCs with extended functionality"""
    
    def __init__(self):
        # NPCs by ID
        self._npcs: Dict[int, NPCData] = {}
        
        # NPCs by level
        self._npcs_by_level: Dict[str, Set[int]] = {}
        
        # Interaction callbacks
        self._touch_callbacks = []
        self._activate_callbacks = []
        
        # Pending NPC creations
        self._pending_creates: List[NPCData] = []
        
    def add_npc(self, npc_id: int, level: str, x: float, y: float, **kwargs) -> NPCData:
        """Add or update an NPC"""
        npc = NPCData(npc_id, level, x, y, **kwargs)
        
        # Remove from old level if moved
        if npc_id in self._npcs:
            old_npc = self._npcs[npc_id]
            if old_npc.level != level and old_npc.level in self._npcs_by_level:
                self._npcs_by_level[old_npc.level].discard(npc_id)
                
        # Add to new level
        if level not in self._npcs_by_level:
            self._npcs_by_level[level] = set()
        self._npcs_by_level[level].add(npc_id)
        
        self._npcs[npc_id] = npc
        logger.debug(f"Added NPC {npc_id} at ({x}, {y}) in {level}")
        return npc
        
    def remove_npc(self, npc_id: int) -> Optional[NPCData]:
        """Remove an NPC"""
        if npc_id not in self._npcs:
            return None
            
        npc = self._npcs[npc_id]
        del self._npcs[npc_id]
        
        # Remove from level index
        if npc.level in self._npcs_by_level:
            self._npcs_by_level[npc.level].discard(npc_id)
            
        logger.debug(f"Removed NPC {npc_id}")
        return npc
        
    def get_npc(self, npc_id: int) -> Optional[NPCData]:
        """Get NPC by ID"""
        return self._npcs.get(npc_id)
        
    def get_npcs_in_level(self, level: str) -> List[NPCData]:
        """Get all NPCs in a level"""
        npc_ids = self._npcs_by_level.get(level, set())
        return [self._npcs[nid] for nid in npc_ids if nid in self._npcs]
        
    def get_npc_at(self, level: str, x: float, y: float, radius: float = 1.0) -> Optional[NPCData]:
        """Get NPC at or near position"""
        npcs = self.get_npcs_in_level(level)
        
        for npc in npcs:
            dx = abs(npc.x - x)
            dy = abs(npc.y - y)
            if dx <= radius and dy <= radius:
                return npc
                
        return None
        
    def update_npc_position(self, npc_id: int, x: float, y: float, level: Optional[str] = None):
        """Update NPC position"""
        npc = self.get_npc(npc_id)
        if not npc:
            return
            
        # Handle level change
        if level and level != npc.level:
            # Remove from old level
            if npc.level in self._npcs_by_level:
                self._npcs_by_level[npc.level].discard(npc_id)
                
            # Add to new level
            if level not in self._npcs_by_level:
                self._npcs_by_level[level] = set()
            self._npcs_by_level[level].add(npc_id)
            
            npc.level = level
            
        npc.x = x
        npc.y = y
        
    def update_npc_property(self, npc_id: int, prop: str, value: Any):
        """Update an NPC property"""
        npc = self.get_npc(npc_id)
        if not npc:
            return
            
        if prop == "image":
            npc.image = value
        elif prop == "script":
            npc.script = value
        elif prop == "name":
            npc.name = value
        elif prop == "type":
            npc.type = value
        elif prop.startswith("save") and len(prop) == 5:
            index = int(prop[4])
            npc.set_save(index, value)
        elif prop.startswith("gattrib") and len(prop) > 7:
            index = int(prop[7:])
            npc.set_gattrib(index, value)
        else:
            npc.flags[prop] = value
            
    def check_npc_touch(self, level: str, x: float, y: float, radius: float = 1.5) -> List[NPCData]:
        """Check which NPCs are touched at position"""
        touched = []
        npcs = self.get_npcs_in_level(level)
        
        for npc in npcs:
            if not npc.touch_enabled or not npc.visible:
                continue
                
            dx = abs(npc.x - x)
            dy = abs(npc.y - y)
            if dx <= radius and dy <= radius:
                touched.append(npc)
                
        return touched
        
    def trigger_npc_touch(self, npc: NPCData, player_id: int):
        """Trigger NPC touch event"""
        import time
        npc.last_interaction = time.time()
        
        for callback in self._touch_callbacks:
            callback(npc, player_id)
            
        logger.info(f"Player {player_id} touched NPC {npc.id}")
        
    def trigger_npc_activate(self, npc: NPCData, player_id: int):
        """Trigger NPC activation (like pressing A)"""
        import time
        npc.last_interaction = time.time()
        
        for callback in self._activate_callbacks:
            callback(npc, player_id)
            
        logger.info(f"Player {player_id} activated NPC {npc.id}")
        
    def add_touch_callback(self, callback):
        """Add callback for NPC touch events"""
        self._touch_callbacks.append(callback)
        
    def add_activate_callback(self, callback):
        """Add callback for NPC activation events"""
        self._activate_callbacks.append(callback)
        
    def create_npc(self, level: str, x: float, y: float, image: str = "", 
                   script: str = "", name: str = "") -> NPCData:
        """Create a new NPC (pending server confirmation)"""
        # Generate temporary ID (negative to distinguish from server IDs)
        temp_id = -len(self._pending_creates) - 1
        
        npc = NPCData(temp_id, level, x, y, image=image, script=script, name=name)
        self._pending_creates.append(npc)
        
        logger.debug(f"Created pending NPC at ({x}, {y}) in {level}")
        return npc
        
    def confirm_npc_creation(self, temp_id: int, real_id: int):
        """Confirm NPC creation with real server ID"""
        # Find pending NPC
        pending = None
        for npc in self._pending_creates:
            if npc.id == temp_id:
                pending = npc
                break
                
        if pending:
            self._pending_creates.remove(pending)
            pending.id = real_id
            self.add_npc(real_id, pending.level, pending.x, pending.y,
                        image=pending.image, script=pending.script, name=pending.name)
            logger.debug(f"Confirmed NPC creation: temp {temp_id} -> real {real_id}")
            
    def clear_level(self, level: str):
        """Clear all NPCs from a level"""
        npc_ids = list(self._npcs_by_level.get(level, set()))
        for npc_id in npc_ids:
            self.remove_npc(npc_id)
            
    def clear_all(self):
        """Clear all NPCs"""
        self._npcs.clear()
        self._npcs_by_level.clear()
        self._pending_creates.clear()