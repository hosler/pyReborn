"""
Packet type definitions for GServer protocol
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from enum import IntEnum
import time


class PacketID(IntEnum):
    """Server to client packet IDs"""
    # Core packets
    PLO_NULL = 0
    PLO_SIGNATURE = 25
    PLO_NEWWORLDTIME = 42
    PLO_FLAGSET = 28
    
    # Level packets  
    PLO_LEVELNAME = 6
    PLO_LEVELMODTIME = 39
    PLO_BOARDMODIFY = 7
    PLO_BOARDPACKET = 101
    PLO_LEVELBOARD = 0
    
    # Player packets
    PLO_PLAYERPROPS = 9
    PLO_OTHERPLAYERS = 8
    PLO_ADDPLAYER = 55
    PLO_DELPLAYER = 56
    PLO_PLAYERMOVED = 2
    PLO_PLAYERWARP = 14
    PLO_PLAYERHURT = 40
    
    # File packets
    PLO_FILE = 102
    PLO_RAWDATA = 100
    PLO_LARGEFILESTART = 68
    PLO_LARGEFILEEND = 69
    PLO_LARGEFILESIZE = 84
    PLO_FILESENDFAILED = 30
    
    # NPC packets
    PLO_NPCDEL = 29
    PLO_NPCMOVED = 24
    PLO_NPCACTION = 26
    PLO_NPCPROPS = 3
    
    # Chat packets
    PLO_SAY = 221  # For incoming chat messages from other players
    PLO_TOALL = 13
    PLO_PRIVMESSAGE = 37
    
    # Other
    PLO_SERVERMESSAGE = 92  # Not in v1 list, keeping as is
    PLO_DISCMESSAGE = 16
    PLO_EXPLOSION = 36
    PLO_HITOBJECTS = 46
    PLO_WARPFAILED = 15
    PLO_SERVERTEXT = 82
    
    # Level objects
    PLO_LEVELSIGN = 5
    PLO_LEVELCHEST = 4
    PLO_LEVELLINK = 1
    
    # Combat
    PLO_BOMBADD = 11
    PLO_BOMBDEL = 12
    PLO_ARROWADD = 19
    PLO_FIRESPY = 20
    
    # Weapons
    PLO_NPCWEAPONADD = 33
    PLO_NPCWEAPONDEL = 34
    PLO_DEFAULTWEAPON = 43
    PLO_HASNPCSERVER = 44
    PLO_CLEARWEAPONS = 194  # Not in v1 list, keeping as is
    
    # GMAP packets
    PLO_MINIMAP = 196  # Not in v1 list, keeping as is
    
    # Visual features
    PLO_SHOWIMG = 32
    PLO_GHOSTTEXT = 173
    PLO_GHOSTICON = 174
    
    # Unknown/Other IDs from logs
    PLO_UNKNOWN_168 = 168
    PLO_UNKNOWN_190 = 190


@dataclass
class Packet:
    """Base packet class"""
    packet_id: int
    raw_data: bytes
    timestamp: float = field(default_factory=time.time, init=False)
    
    def __str__(self):
        return f"{self.__class__.__name__}(id={self.packet_id}, size={len(self.raw_data)})"


@dataclass
class RawDataPacket(Packet):
    """PLO_RAWDATA - announces size of next data chunk"""
    expected_size: int
    
    
@dataclass
class FilePacket(Packet):
    """PLO_FILE - file transfer"""
    filename: str
    mod_time: int
    file_data: bytes
    

@dataclass
class BoardPacket(Packet):
    """PLO_BOARDPACKET - full board data"""
    board_data: bytes  # 8192 bytes for 64x64 board
    level_name: Optional[str] = None
    

@dataclass
class LevelNamePacket(Packet):
    """PLO_LEVELNAME - sets current level"""
    level_name: str
    

@dataclass 
class PlayerPropsPacket(Packet):
    """PLO_PLAYERPROPS - player properties"""
    player_id: int
    properties: Dict[int, Any]
    

@dataclass
class AddPlayerPacket(Packet):
    """PLO_ADDPLAYER - new player joined"""
    player_id: int
    account: str
    nickname: str
    x: float
    y: float
    

@dataclass
class PlayerMovedPacket(Packet):
    """PLO_PLAYERMOVED - player position update"""
    player_id: int
    x: float
    y: float
    direction: int
    sprite: int
    

@dataclass
class ChatPacket(Packet):
    """PLO_SAY - chat message"""
    player_id: int
    message: str
    

@dataclass
class ServerMessagePacket(Packet):
    """Server message/notification"""
    message: str
    

@dataclass
class SignaturePacket(Packet):
    """PLO_SIGNATURE - login accepted"""
    signature: str
    

@dataclass
class FlagSetPacket(Packet):
    """PLO_FLAGSET - server flag"""
    flag_name: str
    flag_value: str
    

@dataclass
class BoardModifyPacket(Packet):
    """PLO_BOARDMODIFY - partial board update"""
    x: int
    y: int  
    width: int
    height: int
    tiles: List[int] = field(default_factory=list)
    

@dataclass
class FileSendFailedPacket(Packet):
    """PLO_FILESENDFAILED - file request failed"""
    filename: str


@dataclass
class PlayerWarpPacket(Packet):
    """PLO_PLAYERWARP - player warped to new position/level"""
    player_id: int
    x: float
    y: float
    level_name: Optional[str] = None
    

@dataclass
class HasNPCServerPacket(Packet):
    """PLO_HASNPCSERVER - server has NPC server capability"""
    has_npc_server: bool
    

@dataclass
class DefaultWeaponPacket(Packet):
    """PLO_DEFAULTWEAPON - sets default weapon"""
    weapon_name: str
    

@dataclass
class NPCWeaponAddPacket(Packet):
    """PLO_NPCWEAPONADD - add weapon to player"""
    weapon_name: str
    weapon_script: Optional[str] = None
    

@dataclass
class NPCWeaponDelPacket(Packet):
    """PLO_NPCWEAPONDEL - remove weapon from player"""
    weapon_name: str
    

@dataclass
class ClearWeaponsPacket(Packet):
    """PLO_CLEARWEAPONS - clear all weapons"""
    pass


@dataclass
class ToAllPacket(Packet):
    """PLO_TOALL - broadcast message to all players"""
    message: str
    

@dataclass 
class PrivateMessagePacket(Packet):
    """PLO_PRIVMESSAGE - private message"""
    sender_id: int
    message: str


@dataclass
class BigmapPacket(Packet):
    """PLO_BIGMAP - GMAP layout information"""
    gmap_name: str
    width: int  # Width in segments
    height: int  # Height in segments
    segments: List[str]  # List of segment level names


@dataclass
class LevelSignPacket(Packet):
    """PLO_LEVELSIGN - sign data"""
    x: int
    y: int
    text: str
    
    
@dataclass
class LevelChestPacket(Packet):
    """PLO_LEVELCHEST - chest data"""
    x: int
    y: int
    item_id: int
    sign_text: str
    
    
@dataclass
class LevelLinkPacket(Packet):
    """PLO_LEVELLINK - level warp link"""
    x: int
    y: int
    width: int
    height: int
    destination_level: str
    destination_x: float
    destination_y: float


@dataclass
class BombAddPacket(Packet):
    """PLO_BOMBADD - bomb placed"""
    player_id: int
    x: float
    y: float
    power: int
    time: float
    

@dataclass
class BombDelPacket(Packet):
    """PLO_BOMBDEL - bomb removed"""
    # No additional data, bomb is identified by context
    pass
    

@dataclass
class ArrowAddPacket(Packet):
    """PLO_ARROWADD - arrow shot"""
    player_id: int
    x: float
    y: float
    direction: int
    
    
@dataclass
class ExplosionPacket(Packet):
    """PLO_EXPLOSION - explosion effect"""
    x: float
    y: float
    power: int
    
    
@dataclass
class FirespyPacket(Packet):
    """PLO_FIRESPY - fire effect"""
    player_id: int


@dataclass
class DisconnectMessagePacket(Packet):
    """PLO_DISCMESSAGE - disconnect with message"""
    message: str
    
    
@dataclass
class WarpFailedPacket(Packet):
    """PLO_WARPFAILED - warp to level failed"""
    level_name: str
    
    
@dataclass
class ServerTextPacket(Packet):
    """PLO_SERVERTEXT - server text message"""
    text: str


@dataclass
class NPCPropsPacket(Packet):
    """PLO_NPCPROPS - NPC properties update"""
    npc_id: int
    properties: Dict[int, Any]
    

@dataclass
class NPCMovedPacket(Packet):
    """PLO_NPCMOVED - NPC movement update"""
    npc_id: int
    x: float
    y: float
    direction: int = 0
    sprite: int = 0
    

@dataclass
class NPCActionPacket(Packet):
    """PLO_NPCACTION - NPC action/animation"""
    npc_id: int
    action: str
    

@dataclass
class NPCDeletePacket(Packet):
    """PLO_NPCDEL - NPC removed"""
    npc_id: int


@dataclass
class ShowImagePacket(Packet):
    """PLO_SHOWIMG - display image on screen"""
    image_data: bytes  # Raw data as format varies
    

@dataclass
class GhostTextPacket(Packet):
    """PLO_GHOSTTEXT - ghost mode text"""
    text: str
    

@dataclass
class GhostIconPacket(Packet):
    """PLO_GHOSTICON - ghost mode icon state"""
    enabled: bool


# Packet registry for easy lookup
PACKET_REGISTRY = {
    PacketID.PLO_RAWDATA: RawDataPacket,
    PacketID.PLO_FILE: FilePacket,
    PacketID.PLO_BOARDPACKET: BoardPacket,
    PacketID.PLO_LEVELNAME: LevelNamePacket,
    PacketID.PLO_PLAYERPROPS: PlayerPropsPacket,
    PacketID.PLO_ADDPLAYER: AddPlayerPacket,
    PacketID.PLO_PLAYERMOVED: PlayerMovedPacket,
    PacketID.PLO_SAY: ChatPacket,
    PacketID.PLO_SIGNATURE: SignaturePacket,
    PacketID.PLO_FLAGSET: FlagSetPacket,
    PacketID.PLO_BOARDMODIFY: BoardModifyPacket,
    PacketID.PLO_LEVELSIGN: LevelSignPacket,
    PacketID.PLO_LEVELCHEST: LevelChestPacket,
    PacketID.PLO_LEVELLINK: LevelLinkPacket,
    PacketID.PLO_BOMBADD: BombAddPacket,
    PacketID.PLO_BOMBDEL: BombDelPacket,
    PacketID.PLO_ARROWADD: ArrowAddPacket,
    PacketID.PLO_EXPLOSION: ExplosionPacket,
    PacketID.PLO_FIRESPY: FirespyPacket,
    PacketID.PLO_DISCMESSAGE: DisconnectMessagePacket,
    PacketID.PLO_WARPFAILED: WarpFailedPacket,
    PacketID.PLO_SERVERTEXT: ServerTextPacket,
    PacketID.PLO_FILESENDFAILED: FileSendFailedPacket,
    PacketID.PLO_PLAYERWARP: PlayerWarpPacket,
    PacketID.PLO_HASNPCSERVER: HasNPCServerPacket,
    PacketID.PLO_DEFAULTWEAPON: DefaultWeaponPacket,
    PacketID.PLO_NPCWEAPONADD: NPCWeaponAddPacket,
    PacketID.PLO_NPCWEAPONDEL: NPCWeaponDelPacket,
    PacketID.PLO_CLEARWEAPONS: ClearWeaponsPacket,
    PacketID.PLO_TOALL: ToAllPacket,
    PacketID.PLO_PRIVMESSAGE: PrivateMessagePacket,
    PacketID.PLO_NPCPROPS: NPCPropsPacket,
    PacketID.PLO_NPCMOVED: NPCMovedPacket,
    PacketID.PLO_NPCACTION: NPCActionPacket,
    PacketID.PLO_NPCDEL: NPCDeletePacket,
    PacketID.PLO_SHOWIMG: ShowImagePacket,
    PacketID.PLO_GHOSTTEXT: GhostTextPacket,
    PacketID.PLO_GHOSTICON: GhostIconPacket,
}