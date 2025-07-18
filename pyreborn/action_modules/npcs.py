"""
NPC-related actions for PyReborn client
"""

from typing import Optional, Dict, Any
import logging
from ..protocol.packet_types.npcs import (
    NPCPropsPacket, PutNPCPacket, NPCDeletePacket, TriggerActionPacket
)

logger = logging.getLogger(__name__)


class NPCActions:
    """NPC-related player actions"""
    
    def __init__(self, client):
        self.client = client
        
    def touch_npc(self, npc_id: int) -> bool:
        """Trigger NPC touch interaction
        
        Args:
            npc_id: NPC ID to touch
            
        Returns:
            True if NPC was touched
        """
        npc = self.client.npc_manager.get_npc(npc_id)
        if not npc:
            logger.debug(f"NPC {npc_id} not found")
            return False
            
        # Trigger local touch event
        self.client.npc_manager.trigger_npc_touch(npc, self.client.local_player.id)
        
        # Send touch notification to server (via triggeraction)
        self.trigger_action("npctouch", f"{npc_id}")
        
        return True
        
    def activate_npc(self, npc_id: int) -> bool:
        """Activate an NPC (like pressing A)
        
        Args:
            npc_id: NPC ID to activate
            
        Returns:
            True if NPC was activated
        """
        npc = self.client.npc_manager.get_npc(npc_id)
        if not npc:
            logger.debug(f"NPC {npc_id} not found")
            return False
            
        # Trigger local activation event
        self.client.npc_manager.trigger_npc_activate(npc, self.client.local_player.id)
        
        # Send activation to server
        self.trigger_action("npcactivate", f"{npc_id}")
        
        return True
        
    def update_npc_prop(self, npc_id: int, prop_id: int, value: Any):
        """Update an NPC property
        
        Args:
            npc_id: NPC ID
            prop_id: Property ID (from NPC prop enum)
            value: New value
        """
        packet = NPCPropsPacket()
        packet.npc_id = npc_id
        packet.properties = {prop_id: value}
        self.client._send_packet(packet)
        
        logger.info(f"Updated NPC {npc_id} property {prop_id} to {value}")
        
    def create_npc(self, x: float, y: float, image: str = "", script: str = "") -> int:
        """Create a new NPC
        
        Args:
            x: X position
            y: Y position
            image: NPC image
            script: NPC script
            
        Returns:
            Temporary NPC ID (negative)
        """
        # Create pending NPC locally
        level = self.client.local_player.level
        npc = self.client.npc_manager.create_npc(level, x, y, image, script)
        
        # Send creation packet
        packet = PutNPCPacket()
        packet.x = x
        packet.y = y
        packet.image = image
        packet.script = script
        self.client._send_packet(packet)
        
        logger.info(f"Created NPC at ({x}, {y}) with image '{image}'")
        return npc.id
        
    def delete_npc(self, npc_id: int):
        """Delete an NPC
        
        Args:
            npc_id: NPC ID to delete
        """
        packet = NPCDeletePacket()
        packet.npc_id = npc_id
        self.client._send_packet(packet)
        
        logger.info(f"Deleted NPC {npc_id}")
        
    def trigger_action(self, action: str, params: str = "", x: Optional[float] = None, y: Optional[float] = None):
        """Send a triggeraction to the server
        
        Args:
            action: Action name
            params: Action parameters
            x: X position (defaults to player position)
            y: Y position (defaults to player position)
        """
        if x is None:
            x = self.client.local_player.x
        if y is None:
            y = self.client.local_player.y
            
        packet = TriggerActionPacket()
        packet.x = x
        packet.y = y
        packet.action = action
        packet.params = params
        self.client._send_packet(packet)
        
        logger.info(f"Triggered action '{action}' with params '{params}'")
        
    def find_nearby_npcs(self, radius: float = 2.0) -> list:
        """Find NPCs near the player
        
        Args:
            radius: Search radius
            
        Returns:
            List of nearby NPCs
        """
        px = self.client.local_player.x
        py = self.client.local_player.y
        level = self.client.local_player.level
        
        return self.client.npc_manager.check_npc_touch(level, px, py, radius)
        
    def interact_with_nearest_npc(self) -> bool:
        """Interact with the nearest NPC
        
        Returns:
            True if an NPC was found and interacted with
        """
        npcs = self.find_nearby_npcs(1.5)
        if not npcs:
            return False
            
        # Sort by distance
        px = self.client.local_player.x
        py = self.client.local_player.y
        
        npcs.sort(key=lambda n: ((n.x - px)**2 + (n.y - py)**2))
        
        # Activate closest
        return self.activate_npc(npcs[0].id)
        
    def set_npc_image(self, npc_id: int, image: str):
        """Set NPC image
        
        Args:
            npc_id: NPC ID
            image: New image name
        """
        from ..protocol.enums import NPCProp
        self.update_npc_prop(npc_id, NPCProp.IMAGE, image)
        
    def set_npc_nickname(self, npc_id: int, nickname: str):
        """Set NPC nickname
        
        Args:
            npc_id: NPC ID
            nickname: New nickname
        """
        from ..protocol.enums import NPCProp
        self.update_npc_prop(npc_id, NPCProp.NICKNAME, nickname)
        
    def move_npc(self, npc_id: int, x: float, y: float):
        """Move an NPC to a new position
        
        Args:
            npc_id: NPC ID
            x: New X position
            y: New Y position
        """
        from ..protocol.enums import NPCProp
        packet = NPCPropsPacket()
        packet.npc_id = npc_id
        packet.properties = {
            NPCProp.X: x,
            NPCProp.Y: y
        }
        self.client._send_packet(packet)
        
        logger.info(f"Moved NPC {npc_id} to ({x}, {y})")