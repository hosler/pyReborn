"""
Enhanced NPC management system for PyReborn
"""

from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)

# Import GS1 scripting support
try:
    from ..scripting.gs1 import GS1Interpreter, GS1Context
    GS1_SUPPORT = True
except ImportError:
    GS1_SUPPORT = False
    logger.debug("GS1 scripting support not available")


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
    
    # GS1 scripting
    gs1_interpreter: Optional[Any] = field(default=None, init=False)
    gs1_context: Optional[Any] = field(default=None, init=False)
    weapon_name: str = ""  # Set by toweapon command
    destroyed: bool = False
    image_part: Optional[tuple] = None  # (x, y, w, h) for setimgpart
    gani: str = ""  # Animation
    
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
        
        # Current level for new NPCs
        self._current_level: Optional[str] = None
        
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
        
        # Initialize GS1 script if present
        if npc.script and GS1_SUPPORT:
            self._init_npc_script(npc)
            # Trigger created event
            self._trigger_npc_event(npc, 'created')
        
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
    
    def get_all_npcs(self) -> List[NPCData]:
        """Get all NPCs"""
        return list(self._npcs.values())
    
    def set_current_level(self, level: str):
        """Set the current level for new NPCs"""
        self._current_level = level
        logger.debug(f"Current level set to: {level}")
        
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
            
    def get_visible_npcs(self) -> List[NPCData]:
        """Get all visible NPCs in the current level
        
        This method is used by the EntityRenderer to get NPCs to render.
        Returns NPCs from the current level that are visible.
        """
        # Try to get current level from client context
        current_level = None
        
        # First try from client's level manager if we have client reference
        if hasattr(self, '_client') and self._client:
            level_manager = self._client.get_manager('level')
            if level_manager and hasattr(level_manager, 'get_current_level'):
                level_obj = level_manager.get_current_level()
                if level_obj and hasattr(level_obj, 'name'):
                    current_level = level_obj.name
        
        # If we couldn't get current level, return all NPCs marked as visible
        if not current_level:
            return [npc for npc in self._npcs.values() if npc.visible]
        
        # Return NPCs in current level that are visible
        npcs = self.get_npcs_in_level(current_level)
        return [npc for npc in npcs if npc.visible]
    
    def get_all_npcs(self) -> List[NPCData]:
        """Get all NPCs regardless of level or visibility"""
        return list(self._npcs.values())
    
    def set_client_reference(self, client):
        """Set reference to client for context access
        
        Args:
            client: ModularRebornClient instance
        """
        self._client = client
            
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
    
    # Interface methods required by INPCManager
    def initialize(self, config, event_manager) -> None:
        """Initialize the manager with configuration and event system"""
        self.config = config
        self.event_manager = event_manager
        logger.info("NPC manager initialized")
    
    def cleanup(self) -> None:
        """Clean up resources when shutting down"""
        self.clear_all()
        self._touch_callbacks.clear()
        self._activate_callbacks.clear()
        logger.info("NPC manager cleaned up")
    
    @property
    def name(self) -> str:
        """Manager name for identification"""
        return "npc_manager"
    
    def get_npcs(self) -> List[Any]:
        """Get all NPCs in current area (interface method)"""
        return list(self._npcs.values())
    
    def get_npc_by_id(self, npc_id: str) -> Optional[Any]:
        """Get specific NPC by ID (interface method)"""
        # Convert string ID to int if needed
        try:
            npc_id_int = int(npc_id)
            return self.get_npc(npc_id_int)
        except (ValueError, TypeError):
            return None
    
    # GS1 Scripting Support Methods
    def _init_npc_script(self, npc: NPCData, player=None, level=None):
        """Initialize GS1 script for an NPC"""
        if not GS1_SUPPORT or not npc.script:
            return
            
        try:
            # Create context with NPC, player, and level references
            npc.gs1_context = GS1Context(npc=npc, player=player, level=level)
            
            # Initialize interpreter
            npc.gs1_interpreter = GS1Interpreter(npc.gs1_context)
            
            # Parse and prepare the script
            npc.gs1_interpreter.interpret(npc.script)
            
            logger.debug(f"Initialized GS1 script for NPC {npc.id}")
        except Exception as e:
            logger.error(f"Failed to initialize GS1 script for NPC {npc.id}: {e}")
            
    def _trigger_npc_event(self, npc: NPCData, event_name: str, **kwargs):
        """Trigger a GS1 event on an NPC"""
        if not npc.gs1_interpreter:
            return
            
        try:
            npc.gs1_interpreter.trigger_event(event_name, **kwargs)
            
            # Check if NPC was destroyed
            if npc.destroyed:
                self.remove_npc(npc.id)
                
        except Exception as e:
            logger.error(f"Error triggering event '{event_name}' on NPC {npc.id}: {e}")
            
    def trigger_player_enters(self, level: str, player=None):
        """Trigger playerenters event for all NPCs in a level"""
        if level not in self._npcs_by_level:
            return
            
        for npc_id in self._npcs_by_level[level]:
            npc = self._npcs.get(npc_id)
            if npc and npc.gs1_interpreter:
                # Update player reference in context
                if player and npc.gs1_context:
                    npc.gs1_context.player = player
                self._trigger_npc_event(npc, 'playerenters')
                
    def trigger_player_touch(self, npc_id: int, player=None):
        """Trigger playertouchsme event for a specific NPC"""
        npc = self._npcs.get(npc_id)
        if npc and npc.gs1_interpreter:
            # Update player reference in context
            if player and npc.gs1_context:
                npc.gs1_context.player = player
            self._trigger_npc_event(npc, 'playertouchsme')
            
            # Also trigger existing touch callbacks
            if player:
                self.trigger_npc_touch(npc, getattr(player, 'id', 0))
                
    def trigger_player_chat(self, level: str, message: str, player=None):
        """Trigger playerchats event for all NPCs in a level"""
        if level not in self._npcs_by_level:
            return
            
        for npc_id in self._npcs_by_level[level]:
            npc = self._npcs.get(npc_id)
            if npc and npc.gs1_interpreter:
                # Update player reference in context
                if player and npc.gs1_context:
                    npc.gs1_context.player = player
                self._trigger_npc_event(npc, 'playerchats', message=message)
                
    def update_npc_script(self, npc_id: int, script: str, player=None, level=None):
        """Update an NPC's GS1 script"""
        npc = self._npcs.get(npc_id)
        if not npc:
            return
            
        npc.script = script
        if GS1_SUPPORT:
            self._init_npc_script(npc, player, level)
            # Don't trigger created again on update
    
    # Packet handler methods for ManagerPacketProcessor
    
    def handle_plo_npcprops(self, parsed_packet: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle PLO_NPCPROPS packet (NPC properties update)
        
        Args:
            parsed_packet: Parsed packet data with fields
            
        Returns:
            Processing result or None
        """
        fields = parsed_packet.get('fields', {})
        properties = fields.get('properties', b'')
        
        # Parse NPC properties data
        # The properties format varies but typically includes:
        # - NPC ID (4 bytes)
        # - Property type and values
        if len(properties) >= 4:
            import struct
            npc_id = struct.unpack('<I', properties[:4])[0]
            prop_data = properties[4:]
            
            logger.debug(f"Received properties for NPC {npc_id} ({len(prop_data)} bytes)")
            
            # Check if NPC exists, create if not
            npc = self.get_npc(npc_id)
            if not npc:
                # Create placeholder NPC
                npc = self.add_npc(npc_id, level="unknown", x=0, y=0)
                logger.debug(f"Created placeholder NPC {npc_id}")
            
            # TODO: Parse specific property updates from prop_data
            # This would require understanding the exact property format
            
            return {
                'type': 'npc_props',
                'npc_id': npc_id,
                'processed': True
            }
        
        return None
    
    def handle_plo_npcmoved(self, parsed_packet: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle PLO_NPCMOVED packet (NPC movement update)
        
        Args:
            parsed_packet: Parsed packet data
            
        Returns:
            Processing result or None
        """
        fields = parsed_packet.get('fields', {})
        # Parse movement data and update NPC position
        # TODO: Implement based on packet structure
        logger.debug(f"NPC movement packet received: {fields}")
        return {'type': 'npc_moved', 'processed': True}
    
    def handle_plo_npcaction(self, parsed_packet: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle PLO_NPCACTION packet (NPC action/animation)
        
        Args:
            parsed_packet: Parsed packet data
            
        Returns:
            Processing result or None
        """
        fields = parsed_packet.get('fields', {})
        # Parse action data and trigger NPC action
        # TODO: Implement based on packet structure
        logger.debug(f"NPC action packet received: {fields}")
        return {'type': 'npc_action', 'processed': True}
    
    def handle_plo_npcdel(self, parsed_packet: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle PLO_NPCDEL packet (NPC deletion)
        
        Args:
            parsed_packet: Parsed packet data
            
        Returns:
            Processing result or None
        """
        fields = parsed_packet.get('fields', {})
        npc_id = fields.get('npc_id')
        
        if npc_id is not None:
            removed = self.remove_npc(npc_id)
            if removed:
                logger.info(f"Removed NPC {npc_id}")
                return {
                    'type': 'npc_deleted',
                    'npc_id': npc_id,
                    'processed': True
                }
        
        return None
    
    def handle_packet(self, packet_id: int, parsed_packet: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Generic packet handler fallback
        
        Args:
            packet_id: Packet ID
            parsed_packet: Parsed packet data
            
        Returns:
            Processing result or None
        """
        packet_name = parsed_packet.get('packet_name', '').lower()
        
        # Try to find a specific handler
        handler_name = f"handle_{packet_name}"
        if hasattr(self, handler_name):
            handler = getattr(self, handler_name)
            return handler(parsed_packet)
        
        logger.debug(f"No specific handler for packet {packet_id} ({packet_name})")
        return None
    
    def handle_plo_npcprops(self, parsed_packet: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle NPC properties packet
        
        Args:
            parsed_packet: Parsed NPC props packet
            
        Returns:
            Processing result
        """
        parsed_data = parsed_packet.get('parsed_data', {})
        npc_id = parsed_data.get('npc_id')
        properties = parsed_data.get('properties', {})
        
        if npc_id is None:
            logger.warning("NPC props packet missing NPC ID")
            return None
        
        # Get or create NPC
        npc = self.get_npc(npc_id)
        if not npc:
            # Create new NPC
            x = properties.get('x', 0)
            y = properties.get('y', 0)
            level = self._current_level or "unknown"
            npc = self.add_npc(npc_id, x, y, level)
        
        # Update NPC properties
        if 'x' in properties:
            npc.x = properties['x']
        if 'y' in properties:
            npc.y = properties['y']
        if 'image' in properties:
            npc.image = properties['image']
        if 'script' in properties:
            npc.script = properties['script']
        if 'nickname' in properties:
            npc.name = properties['nickname']
        if 'gani' in properties:
            npc.gani = properties['gani']
        if 'vis_flags' in properties:
            npc.visible = (properties['vis_flags'] & 1) != 0
        if 'block_flags' in properties:
            npc.blocking = properties['block_flags'] > 0
        
        # Store save values
        for i in range(10):
            key = f'save{i}'
            if key in properties:
                npc.saves[i] = properties[key]
        
        if len(properties) > 0:
            logger.debug(f"Updated NPC {npc_id} with {len(properties)} properties")
        
        return {
            'type': 'npc_updated',
            'npc_id': npc_id,
            'properties': properties,
            'processed': True
        }
    
    def handle_plo_baddyprops(self, parsed_packet: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle baddy properties packet (server-controlled NPCs)
        
        Args:
            parsed_packet: Parsed baddy props packet
            
        Returns:
            Processing result
        """
        # Baddies are just server-controlled NPCs, handle them the same way
        parsed_data = parsed_packet.get('parsed_data', {})
        fields = parsed_packet.get('fields', {})
        
        # Get NPC ID from parsed data or fields
        npc_id = parsed_data.get('baddy_id') or fields.get('baddy_id')
        properties = parsed_data.get('properties', {})
        
        # If properties not in parsed_data, check fields
        if not properties and 'baddy_props' in fields:
            properties = fields['baddy_props'] if isinstance(fields['baddy_props'], dict) else {}
        
        if npc_id is None:
            logger.warning("Baddy props packet missing baddy ID")
            return None
        
        # Get or create NPC
        npc = self.get_npc(npc_id)
        if not npc:
            # Create new NPC
            x = properties.get('x', fields.get('baddy_x', 0))
            y = properties.get('y', fields.get('baddy_y', 0))
            level = self._current_level or "unknown"
            npc = self.add_npc(npc_id, x, y, level)
            npc.type = "baddy"  # Mark as server NPC
        
        # Update NPC properties
        if 'x' in properties:
            npc.x = properties['x']
        elif 'baddy_x' in fields:
            npc.x = fields['baddy_x']
            
        if 'y' in properties:
            npc.y = properties['y']
        elif 'baddy_y' in fields:
            npc.y = fields['baddy_y']
            
        if 'image' in properties:
            npc.image = properties['image']
        if 'script' in properties:
            npc.script = properties['script']
        if 'nickname' in properties:
            npc.name = properties['nickname']
        if 'gani' in properties:
            npc.gani = properties['gani']
        if 'vis_flags' in properties:
            npc.visible = (properties['vis_flags'] & 1) != 0
        if 'block_flags' in properties:
            npc.blocking = properties['block_flags'] > 0
        
        logger.info(f"Updated baddy/NPC {npc_id} at ({npc.x:.1f}, {npc.y:.1f})")
        
        return {
            'type': 'baddy_updated',
            'npc_id': npc_id,
            'properties': properties,
            'processed': True
        }