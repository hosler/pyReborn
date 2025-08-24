"""
Protocol state machine - manages packet sequences and emits high-level events
"""

import logging
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum, auto

# Note: Old packet_types system is deprecated, replaced by registry-driven packets
# from ..packet_types import *
from ..session.events import EventType, Event


logger = logging.getLogger(__name__)


class ProtocolState(Enum):
    """Protocol connection states"""
    DISCONNECTED = auto()
    CONNECTED = auto()
    LOGGING_IN = auto()
    LOGGED_IN = auto()
    IN_LEVEL = auto()


@dataclass
class SessionState:
    """Current session state"""
    state: ProtocolState = ProtocolState.DISCONNECTED
    current_level: Optional[str] = None
    player_id: Optional[int] = None
    pending_board_data: Optional[bytes] = None
    pending_files: Dict[str, float] = field(default_factory=dict)  # filename -> request time
    

class ProtocolStateMachine:
    """Manages protocol state and converts packets to high-level events"""
    
    def __init__(self, event_emitter):
        self.event_emitter = event_emitter
        self.session = SessionState()
        self.handlers = self._init_handlers()
        
    def _init_handlers(self) -> Dict[type, callable]:
        """Initialize packet handlers"""
        return {
            SignaturePacket: self._handle_signature,
            LevelNamePacket: self._handle_level_name,
            BoardPacket: self._handle_board_packet,
            FilePacket: self._handle_file_packet,
            FileSendFailedPacket: self._handle_file_failed,
            PlayerPropsPacket: self._handle_player_props,
            AddPlayerPacket: self._handle_add_player,
            PlayerMovedPacket: self._handle_player_moved,
            ChatPacket: self._handle_chat,
            FlagSetPacket: self._handle_flag_set,
            BoardModifyPacket: self._handle_board_modify,
            LevelSignPacket: self._handle_level_sign,
            LevelChestPacket: self._handle_level_chest,
            LevelLinkPacket: self._handle_level_link,
            BombAddPacket: self._handle_bomb_add,
            BombDelPacket: self._handle_bomb_del,
            ArrowAddPacket: self._handle_arrow_add,
            ExplosionPacket: self._handle_explosion,
            FirespyPacket: self._handle_firespy,
            DisconnectMessagePacket: self._handle_disconnect_message,
            WarpFailedPacket: self._handle_warp_failed,
            ServerTextPacket: self._handle_server_text,
            PlayerWarpPacket: self._handle_player_warp,
            HasNPCServerPacket: self._handle_has_npc_server,
            DefaultWeaponPacket: self._handle_default_weapon,
            NPCWeaponAddPacket: self._handle_npc_weapon_add,
            NPCWeaponDelPacket: self._handle_npc_weapon_del,
            ClearWeaponsPacket: self._handle_clear_weapons,
            ToAllPacket: self._handle_toall,
            PrivateMessagePacket: self._handle_private_message,
            ServerMessagePacket: self._handle_server_message,
            NPCPropsPacket: self._handle_npc_props,
            NPCMovedPacket: self._handle_npc_moved,
            NPCActionPacket: self._handle_npc_action,
            NPCDeletePacket: self._handle_npc_del,
            ShowImagePacket: self._handle_show_img,
            GhostTextPacket: self._handle_ghost_text,
            GhostIconPacket: self._handle_ghost_icon,
        }
        
    def process_packet(self, packet: Packet) -> List[Event]:
        """Process a packet and return list of events to emit"""
        events = []
        
        # Get handler for packet type
        handler = self.handlers.get(type(packet))
        
        if handler:
            try:
                packet_events = handler(packet)
                if packet_events:
                    events.extend(packet_events)
            except Exception as e:
                logger.error(f"Error handling packet {type(packet).__name__}: {e}")
                
        # Emit all events
        for event in events:
            self.event_emitter.emit(event.type, event.data)
            
        return events
        
    def _handle_signature(self, packet: SignaturePacket) -> List[Event]:
        """Handle login signature"""
        self.session.state = ProtocolState.LOGGED_IN
        
        return [Event(
            EventType.LOGIN_ACCEPTED,
            {"signature": packet.signature}
        )]
        
    def _handle_level_name(self, packet: LevelNamePacket) -> List[Event]:
        """Handle level change"""
        old_level = self.session.current_level
        new_level = packet.level_name
        
        # Don't set current level to a .gmap file - current level should always be an actual level
        if not new_level.endswith('.gmap'):
            self.session.current_level = new_level
            self.session.state = ProtocolState.IN_LEVEL
        
        events = []
        
        # Always emit level change event so connection manager can track GMAP state
        logger.info(f"[PROTOCOL] Emitting LEVEL_TRANSITION event: {old_level} -> {new_level}")
        events.append(Event(
            EventType.LEVEL_TRANSITION,
            {
                "old_level": old_level,
                "new_level": new_level
            }
        ))
        
        # If we have pending board data, apply it now
        if self.session.pending_board_data:
            events.append(Event(
                EventType.BOARD_UPDATED,
                {
                    "level_name": packet.level_name,
                    "board_data": self.session.pending_board_data
                }
            ))
            self.session.pending_board_data = None
            
        return events
        
    def _handle_board_packet(self, packet: BoardPacket) -> List[Event]:
        """Handle board data"""
        if self.session.current_level:
            # Apply to current level
            return [Event(
                EventType.BOARD_UPDATED,
                {
                    "level_name": self.session.current_level,
                    "board_data": packet.board_data
                }
            )]
        else:
            # Save for when we know the level
            self.session.pending_board_data = packet.board_data
            logger.debug("Received board data before level name, saving")
            return []
            
    def _handle_file_packet(self, packet: FilePacket) -> List[Event]:
        """Handle file received"""
        # Remove from pending if it was requested
        if packet.filename in self.session.pending_files:
            request_time = self.session.pending_files.pop(packet.filename)
            response_time = packet.timestamp - request_time
        else:
            response_time = None
            
        return [Event(
            EventType.FILE_RECEIVED,
            {
                "filename": packet.filename,
                "data": packet.file_data,
                "mod_time": packet.mod_time,
                "size": len(packet.file_data),
                "response_time": response_time
            }
        )]
        
    def _handle_file_failed(self, packet: FileSendFailedPacket) -> List[Event]:
        """Handle file send failed"""
        # Remove from pending
        self.session.pending_files.pop(packet.filename, None)
        
        return [Event(
            EventType.FILE_REQUEST_FAILED,
            {"filename": packet.filename}
        )]
        
    def _handle_player_props(self, packet: PlayerPropsPacket) -> List[Event]:
        """Handle player properties"""
        # Check if this is our player
        if packet.player_id == 0 or packet.player_id == self.session.player_id:
            # Our player
            return [Event(
                EventType.PLAYER_UPDATE,
                {
                    "player_id": packet.player_id,
                    "properties": packet.properties,
                    "source": "self"
                }
            )]
        else:
            # Other player
            return [Event(
                EventType.PLAYER_UPDATE,
                {
                    "player_id": packet.player_id,
                    "properties": packet.properties,
                    "source": "other"
                }
            )]
            
    def _handle_add_player(self, packet: AddPlayerPacket) -> List[Event]:
        """Handle player joined"""
        return [Event(
            EventType.PLAYER_JOINED,
            {
                "player_id": packet.player_id,
                "account": packet.account,
                "nickname": packet.nickname,
                "x": packet.x,
                "y": packet.y
            }
        )]
        
    def _handle_player_moved(self, packet: PlayerMovedPacket) -> List[Event]:
        """Handle player movement"""
        return [Event(
            EventType.PLAYER_MOVED,
            {
                "player_id": packet.player_id,
                "x": packet.x,
                "y": packet.y,
                "direction": packet.direction,
                "sprite": packet.sprite
            }
        )]
        
    def _handle_chat(self, packet: ChatPacket) -> List[Event]:
        """Handle chat message"""
        return [Event(
            EventType.CHAT_MESSAGE,
            {
                "player_id": packet.player_id,
                "message": packet.message
            }
        )]
        
    def _handle_flag_set(self, packet: FlagSetPacket) -> List[Event]:
        """Handle server flag"""
        return [Event(
            EventType.FLAG_SET,
            {
                "flag_name": packet.flag_name,
                "flag_value": packet.flag_value
            }
        )]
        
    def _handle_board_modify(self, packet: BoardModifyPacket) -> List[Event]:
        """Handle board modification"""
        return [Event(
            EventType.BOARD_UPDATED,
            {
                "level_name": self.session.current_level,
                "x": packet.x,
                "y": packet.y,
                "width": packet.width,
                "height": packet.height,
                "tiles": packet.tiles
            }
        )]
        
    def file_requested(self, filename: str):
        """Track file request"""
        self.session.pending_files[filename] = time.time()
        
    def get_state(self) -> ProtocolState:
        """Get current protocol state"""
        return self.session.state
        
    def _handle_player_warp(self, packet: PlayerWarpPacket) -> List[Event]:
        """Handle player warp"""
        events = []
        
        # Check if this is our player
        if packet.player_id == 0 or packet.player_id == self.session.player_id:
            # We warped
            event_type = EventType.SELF_WARPED
        else:
            # Other player warped
            event_type = EventType.PLAYER_WARPED
            
        events.append(Event(
            event_type,
            {
                "player_id": packet.player_id,
                "x": packet.x,
                "y": packet.y,
                "level_name": packet.level_name
            }
        ))
        
        return events
        
    def _handle_has_npc_server(self, packet: HasNPCServerPacket) -> List[Event]:
        """Handle NPC server status"""
        return [Event(
            EventType.NPC_SERVER_STATUS,
            {"has_npc_server": packet.has_npc_server}
        )]
        
    def _handle_default_weapon(self, packet: DefaultWeaponPacket) -> List[Event]:
        """Handle default weapon set"""
        return [Event(
            EventType.DEFAULT_WEAPON_SET,
            {"weapon_name": packet.weapon_name}
        )]
        
    def _handle_npc_weapon_add(self, packet: NPCWeaponAddPacket) -> List[Event]:
        """Handle weapon added"""
        return [Event(
            EventType.WEAPON_ADDED,
            {
                "weapon_name": packet.weapon_name,
                "weapon_script": packet.weapon_script
            }
        )]
        
    def _handle_npc_weapon_del(self, packet: NPCWeaponDelPacket) -> List[Event]:
        """Handle weapon removed"""
        return [Event(
            EventType.WEAPON_REMOVED,
            {"weapon_name": packet.weapon_name}
        )]
        
    def _handle_clear_weapons(self, packet: ClearWeaponsPacket) -> List[Event]:
        """Handle clear all weapons"""
        return [Event(EventType.WEAPONS_CLEARED, {})]
        
    def _handle_toall(self, packet: ToAllPacket) -> List[Event]:
        """Handle broadcast message"""
        return [Event(
            EventType.BROADCAST_MESSAGE,
            {"message": packet.message}
        )]
        
    def _handle_private_message(self, packet: PrivateMessagePacket) -> List[Event]:
        """Handle private message"""
        return [Event(
            EventType.PRIVATE_MESSAGE,
            {
                "sender_id": packet.sender_id,
                "message": packet.message
            }
        )]
        
    def _handle_server_message(self, packet: ServerMessagePacket) -> List[Event]:
        """Handle server message"""
        return [Event(
            EventType.SERVER_MESSAGE,
            {"message": packet.message}
        )]
        
    def _handle_level_sign(self, packet: LevelSignPacket) -> List[Event]:
        """Handle level sign"""
        return [Event(
            EventType.LEVEL_SIGN_ADDED,
            {
                "x": packet.x,
                "y": packet.y,
                "text": packet.text
            }
        )]
        
    def _handle_level_chest(self, packet: LevelChestPacket) -> List[Event]:
        """Handle level chest"""
        return [Event(
            EventType.LEVEL_CHEST_ADDED,
            {
                "x": packet.x,
                "y": packet.y,
                "item_id": packet.item_id,
                "sign_text": packet.sign_text
            }
        )]
        
    def _handle_level_link(self, packet: LevelLinkPacket) -> List[Event]:
        """Handle level link"""
        return [Event(
            EventType.LEVEL_LINK_ADDED,
            {
                "x": packet.x,
                "y": packet.y,
                "width": packet.width,
                "height": packet.height,
                "destination_level": packet.destination_level,
                "destination_x": packet.destination_x,
                "destination_y": packet.destination_y
            }
        )]
        
    def _handle_bomb_add(self, packet: BombAddPacket) -> List[Event]:
        """Handle bomb placement"""
        return [Event(
            EventType.BOMB_ADDED,
            {
                "player_id": packet.player_id,
                "x": packet.x,
                "y": packet.y,
                "power": packet.power,
                "time": packet.time
            }
        )]
        
    def _handle_bomb_del(self, packet: BombDelPacket) -> List[Event]:
        """Handle bomb removal"""
        return [Event(EventType.BOMB_EXPLODED, {})]
        
    def _handle_arrow_add(self, packet: ArrowAddPacket) -> List[Event]:
        """Handle arrow shot"""
        return [Event(
            EventType.ARROW_SHOT,
            {
                "player_id": packet.player_id,
                "x": packet.x,
                "y": packet.y,
                "direction": packet.direction
            }
        )]
        
    def _handle_explosion(self, packet: ExplosionPacket) -> List[Event]:
        """Handle explosion effect"""
        return [Event(
            EventType.EXPLOSION,
            {
                "x": packet.x,
                "y": packet.y,
                "power": packet.power
            }
        )]
        
    def _handle_firespy(self, packet: FirespyPacket) -> List[Event]:
        """Handle fire effect"""
        return [Event(
            EventType.FIRESPY,
            {"player_id": packet.player_id}
        )]
        
    def _handle_disconnect_message(self, packet: DisconnectMessagePacket) -> List[Event]:
        """Handle disconnect message"""
        return [Event(
            EventType.DISCONNECT_MESSAGE,
            {"message": packet.message}
        )]
        
    def _handle_warp_failed(self, packet: WarpFailedPacket) -> List[Event]:
        """Handle warp failed"""
        return [Event(
            EventType.WARP_FAILED,
            {"level_name": packet.level_name}
        )]
        
    def _handle_server_text(self, packet: ServerTextPacket) -> List[Event]:
        """Handle server text"""
        return [Event(
            EventType.SERVER_TEXT,
            {"text": packet.text}
        )]
        
    def _handle_npc_props(self, packet: NPCPropsPacket) -> List[Event]:
        """Handle NPC properties update"""
        return [Event(
            EventType.NPC_UPDATE,
            {
                "npc_id": packet.npc_id,
                "properties": packet.properties
            }
        )]
        
    def _handle_npc_moved(self, packet: NPCMovedPacket) -> List[Event]:
        """Handle NPC movement"""
        return [Event(
            EventType.NPC_MOVED,
            {
                "npc_id": packet.npc_id,
                "x": packet.x,
                "y": packet.y,
                "direction": packet.direction,
                "sprite": packet.sprite
            }
        )]
        
    def _handle_npc_action(self, packet: NPCActionPacket) -> List[Event]:
        """Handle NPC action"""
        return [Event(
            EventType.NPC_ACTION,
            {
                "npc_id": packet.npc_id,
                "action": packet.action
            }
        )]
        
    def _handle_npc_del(self, packet: NPCDeletePacket) -> List[Event]:
        """Handle NPC deletion"""
        return [Event(
            EventType.NPC_REMOVED,
            {
                "npc_id": packet.npc_id
            }
        )]
        
    def _handle_show_img(self, packet: ShowImagePacket) -> List[Event]:
        """Handle show image"""
        return [Event(
            EventType.SHOW_IMAGE,
            {
                "image_data": packet.image_data
            }
        )]
        
    def _handle_ghost_text(self, packet: GhostTextPacket) -> List[Event]:
        """Handle ghost mode text"""
        return [Event(
            EventType.GHOST_TEXT,
            {
                "text": packet.text
            }
        )]
        
    def _handle_ghost_icon(self, packet: GhostIconPacket) -> List[Event]:
        """Handle ghost mode icon"""
        return [Event(
            EventType.GHOST_ICON,
            {
                "enabled": packet.enabled
            }
        )]
    
    def get_stats(self) -> dict:
        """Get state machine statistics"""
        return {
            "state": self.session.state.name,
            "current_level": self.session.current_level,
            "player_id": self.session.player_id,
            "pending_files": len(self.session.pending_files)
        }