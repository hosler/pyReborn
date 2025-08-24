#!/usr/bin/env python3
"""
Reborn Protocol Packet Structure Definitions

Based on GServer-v2 source code analysis and protocol documentation.
Each packet type defines its exact structure for proper parsing.
"""

from enum import IntEnum
from dataclasses import dataclass
from typing import List, Optional, Union, Callable
import struct

class PacketFieldType(IntEnum):
    """Field types in packet structures"""
    BYTE = 1           # 1 byte
    GCHAR = 2          # 1 byte with +32 offset  
    GSHORT = 3         # 2 bytes with GServer encoding (GShort)
    GINT3 = 4          # 3 bytes with GServer encoding
    GINT4 = 5          # 4 bytes with GServer encoding  
    GINT5 = 6          # 5 bytes with GServer encoding
    STRING_LEN = 7     # Length-prefixed string (1 byte len + string)
    STRING_GCHAR_LEN = 8  # GCHAR length + string
    FIXED_DATA = 9     # Fixed number of bytes
    VARIABLE_DATA = 10  # Variable data (rest of packet)
    ANNOUNCED_DATA = 11 # Data size announced by previous PLO_RAWDATA
    COORDINATE = 12     # GCHAR coordinate with /8 division for positions

@dataclass
class PacketField:
    """Definition of a field within a packet"""
    name: str
    field_type: PacketFieldType
    size: Optional[int] = None  # For FIXED_DATA
    description: str = ""

@dataclass
class PacketStructure:
    """Complete structure definition for a packet type"""
    packet_id: int
    name: str
    fields: List[PacketField]
    description: str = ""
    variable_length: bool = False  # True if packet has variable length

class PacketRegistry:
    """Registry of all known packet structures"""
    
    def __init__(self):
        self.structures = {}
        self._initialize_structures()
    
    def _initialize_structures(self):
        """Initialize all known packet structures from GServer analysis"""
        
        # Based on GServer source code analysis
        
        # Level data packets (0-5) - Core level content packets
        
        # PLO_LEVELBOARD (0) - Level board data
        self.structures[0] = PacketStructure(
            packet_id=0,
            name="PLO_LEVELBOARD",
            fields=[
                PacketField("compressed_length", PacketFieldType.GSHORT, description="Compressed data length"),
                PacketField("compressed_data", PacketFieldType.VARIABLE_DATA, description="Compressed level board data")
            ],
            description="Level board tile data (typically 8192 bytes uncompressed)",
            variable_length=True
        )
        
        # PLO_LEVELLINK (1) - Level connection links
        self.structures[1] = PacketStructure(
            packet_id=1,
            name="PLO_LEVELLINK",
            fields=[
                PacketField("link_data", PacketFieldType.STRING_GCHAR_LEN, description="Level link string (destlevel x y width height destx desty)")
            ],
            description="Level connection data for transitions",
            variable_length=True
        )
        
        # PLO_LEVELCHEST (4) - Level chest data  
        self.structures[4] = PacketStructure(
            packet_id=4,
            name="PLO_LEVELCHEST",
            fields=[
                PacketField("x_coord", PacketFieldType.BYTE, description="X coordinate (pixels/2)"),
                PacketField("y_coord", PacketFieldType.BYTE, description="Y coordinate (pixels/2)"),
                PacketField("item", PacketFieldType.BYTE, description="Item/chest type"),
                PacketField("sign_text", PacketFieldType.STRING_GCHAR_LEN, description="Sign text for chest")
            ],
            description="Chest placement and contents",
            variable_length=True
        )
        
        # PLO_LEVELSIGN (5) - Level sign data
        self.structures[5] = PacketStructure(
            packet_id=5,
            name="PLO_LEVELSIGN",
            fields=[
                PacketField("x_coord", PacketFieldType.BYTE, description="X coordinate"),
                PacketField("y_coord", PacketFieldType.BYTE, description="Y coordinate"),
                PacketField("sign_text", PacketFieldType.STRING_GCHAR_LEN, description="Sign text content")
            ],
            description="Sign placement and text content",
            variable_length=True
        )
        
        # PLO_BOMBDEL (12) - Bomb deletion with coordinates
        self.structures[12] = PacketStructure(
            packet_id=12,
            name="PLO_BOMBDEL", 
            fields=[
                PacketField("x_coord", PacketFieldType.COORDINATE, description="X coordinate"),
                PacketField("y_coord", PacketFieldType.COORDINATE, description="Y coordinate")
            ],
            description="Delete bomb at coordinates"
        )
        
        # PLO_RAWDATA (100) - Raw data announcement  
        self.structures[100] = PacketStructure(
            packet_id=100,
            name="PLO_RAWDATA",
            fields=[
                PacketField("size", PacketFieldType.GINT3, description="Size of following data")
            ],
            description="Announces size of raw data in next packet"
        )
        
        # PLO_BOARDPACKET (101) - Board data
        self.structures[101] = PacketStructure(
            packet_id=101,
            name="PLO_BOARDPACKET",
            fields=[
                PacketField("board_data", PacketFieldType.FIXED_DATA, size=8192, description="Board tile data (8192 bytes)")
            ],
            description="Level board data (usually 8192 bytes)"
        )
        
        # PLO_FILE (102) - File transfer (simplified - complex structure)
        self.structures[102] = PacketStructure(
            packet_id=102,
            name="PLO_FILE",
            fields=[
                PacketField("file_data", PacketFieldType.VARIABLE_DATA, description="File transfer data (complex structure)")  
            ],
            description="File transfer packet (needs special handling)",
            variable_length=True
        )
        
        # PLO_LEVELNAME (6) - Level name  
        self.structures[6] = PacketStructure(
            packet_id=6,
            name="PLO_LEVELNAME",
            fields=[
                PacketField("level_name", PacketFieldType.VARIABLE_DATA, description="Null-terminated level name")
            ],
            description="Current level name"
        )
        
        # PLO_PLAYERPROPS (9) - Player properties
        self.structures[9] = PacketStructure(
            packet_id=9,
            name="PLO_PLAYERPROPS", 
            fields=[
                PacketField("properties", PacketFieldType.VARIABLE_DATA, description="Encoded player properties")
            ],
            description="Player properties blob",
            variable_length=True
        )
        
        # Add more structures as needed...
        self._add_simple_packets()
        self._add_common_packets()
        self._add_complex_packets()
        self._add_reborn_specific_packets()
    
    def _add_simple_packets(self):
        """Add simple packets with known structures"""
        
        # Zero-byte packets
        for packet_id, name in [
            (194, "PLO_CLEARWEAPONS"), 
            (182, "UNKNOWN_182"),
            (190, "UNKNOWN_190")
        ]:
            self.structures[packet_id] = PacketStructure(
                packet_id=packet_id,
                name=name,
                fields=[],
                description=f"Simple packet with no data"
            )
        
        # Packet 44 - Based on analysis, this appears to be part of PLO_BOMBDEL pattern
        # But since we're seeing it as separate packet, it might have coordinate data
        self.structures[44] = PacketStructure(
            packet_id=44,
            name="UNKNOWN_44_WITH_DATA",
            fields=[
                PacketField("data1", PacketFieldType.BYTE, description="First data byte"),
                PacketField("data2", PacketFieldType.BYTE, description="Second data byte") 
            ],
            description="Unknown packet 44 with 2 bytes of data"
        )
    
    def _add_common_packets(self):
        """Add common packets we see in captures"""
        
        # From our analysis of initial packets
        common_packets = [
            # PLO_BADDYPROPS (2) - Variable length  
            (2, "PLO_BADDYPROPS", "VARIABLE_DATA", "Baddy properties"),
            # PLO_NPCPROPS (3) - Variable length
            (3, "PLO_NPCPROPS", "VARIABLE_DATA", "NPC properties"),
            # PLO_OTHERPLPROPS (8) - Variable length
            (8, "PLO_OTHERPLPROPS", "VARIABLE_DATA", "Other player properties"),
            # PLO_TOALL (13) - Variable length
            (13, "PLO_TOALL", "VARIABLE_DATA", "Message to all players"),
            # PLO_NPCMOVED (24) - Variable length
            (24, "PLO_NPCMOVED", "VARIABLE_DATA", "NPC moved notification"), 
            # PLO_NPCWEAPONADD (33) - Variable length
            (33, "PLO_NPCWEAPONADD", "VARIABLE_DATA", "Add NPC weapon"),
            # PLO_STARTMESSAGE (41) - Variable length  
            (41, "PLO_STARTMESSAGE", "VARIABLE_DATA", "Server start message"),
            # PLO_DEFAULTWEAPON (43) - Variable length
            (43, "PLO_DEFAULTWEAPON", "VARIABLE_DATA", "Default weapon"),
            # PLO_STAFFGUILDS (47) - Variable length
            (47, "PLO_STAFFGUILDS", "VARIABLE_DATA", "Staff guild list"),
            # PLO_PLAYERWARP2 (49) - Has specific structure
            (49, "PLO_PLAYERWARP2", "VARIABLE_DATA", "Player warp with GMAP coordinates"),
            # PLO_TILESET (52) - From our capture
            (52, "PLO_TILESET", "VARIABLE_DATA", "Tileset filename"),
            # PLO_ADDPLAYER (55) - Variable length
            (55, "PLO_ADDPLAYER", "VARIABLE_DATA", "Add player to level"),
            # PLO_SERVERTEXT (82) - Variable length  
            (82, "PLO_SERVERTEXT", "VARIABLE_DATA", "Server text message"),
            # PLO_LARGEFILESIZE (84) - Has size field
            (84, "PLO_LARGEFILESIZE", "GINT5", "Large file size announcement"),
            # PLO_RPGWINDOW (179) - Variable length
            (179, "PLO_RPGWINDOW", "VARIABLE_DATA", "RPG window content"),
            # PLO_STATUSLIST (180) - Variable length  
            (180, "PLO_STATUSLIST", "VARIABLE_DATA", "Status list"),
            # PLO_UNKNOWN168 (168) - Login server blank packet
            (168, "PLO_UNKNOWN168", None, "Login server blank packet")
        ]
        
        for packet_id, name, field_type, desc in common_packets:
            if field_type is None:
                # Blank packet
                self.structures[packet_id] = PacketStructure(
                    packet_id=packet_id,
                    name=name,
                    fields=[],
                    description=desc
                )
            elif field_type == "VARIABLE_DATA":
                # Variable length packet
                self.structures[packet_id] = PacketStructure(
                    packet_id=packet_id,
                    name=name,  
                    fields=[PacketField("data", PacketFieldType.VARIABLE_DATA, description=desc)],
                    description=desc,
                    variable_length=True
                )
            elif field_type == "GINT5":
                # GINT5 field
                self.structures[packet_id] = PacketStructure(
                    packet_id=packet_id,
                    name=name,
                    fields=[PacketField("size", PacketFieldType.GINT5, description=desc)],
                    description=desc
                )
    
    def _add_complex_packets(self):
        """Add more complex packet structures"""
        
        # PLO_SIGNATURE (25) - Login signature
        self.structures[25] = PacketStructure(
            packet_id=25,
            name="PLO_SIGNATURE",
            fields=[
                PacketField("signature", PacketFieldType.BYTE, description="Login signature byte")
            ],
            description="Server login signature"
        )
        
        # NPC weapon deletion (34)
        self.structures[34] = PacketStructure(
            packet_id=34,
            name="PLO_NPCWEAPONDEL",
            fields=[
                PacketField("weapon_name", PacketFieldType.VARIABLE_DATA, description="Weapon name to delete")
            ],
            description="Delete NPC weapon",
            variable_length=True
        )
    
    def _add_reborn_specific_packets(self):
        """Add Reborn-specific packets with known structures"""
        
        # PLO_NPCBYTECODE (131) - NPC script bytecode
        self.structures[131] = PacketStructure(
            packet_id=131,
            name="PLO_NPCBYTECODE",
            fields=[
                PacketField("npc_id", PacketFieldType.GINT3, description="NPC ID"),
                PacketField("bytecode", PacketFieldType.VARIABLE_DATA, description="Compiled script bytecode")
            ],
            description="NPC script bytecode transfer",
            variable_length=True
        )
        
        # PLO_NPCWEAPONSCRIPT (140) - NPC weapon script
        self.structures[140] = PacketStructure(
            packet_id=140,
            name="PLO_NPCWEAPONSCRIPT", 
            fields=[
                PacketField("info_length", PacketFieldType.GINT3, description="Info length"),
                PacketField("script", PacketFieldType.VARIABLE_DATA, description="Weapon script")
            ],
            description="NPC weapon script transfer",
            variable_length=True
        )
        
        # PLO_NPCDEL2 (150) - Enhanced NPC deletion
        self.structures[150] = PacketStructure(
            packet_id=150,
            name="PLO_NPCDEL2",
            fields=[
                PacketField("level_length", PacketFieldType.GCHAR, description="Level name length"),
                PacketField("level_name", PacketFieldType.STRING_GCHAR_LEN, description="Level name"),
                PacketField("npc_id", PacketFieldType.GINT3, description="NPC ID to delete")
            ],
            description="Delete NPC from specific level"
        )
        
        # PLO_SAY2 (153) - Enhanced say/sign
        self.structures[153] = PacketStructure(
            packet_id=153,
            name="PLO_SAY2",
            fields=[
                PacketField("text", PacketFieldType.VARIABLE_DATA, description="Say text or sign content")
            ],
            description="Enhanced say command or sign text",
            variable_length=True
        )
        
        # Add more protocol packets from GServer analysis
        self._add_movement_packets()
        self._add_item_packets()
        self._add_level_packets()
        self._add_weapon_packets()
        self._add_system_packets()
        self._add_missing_packets()
    
    def _add_movement_packets(self):
        """Add movement and positioning packets"""
        
        # PLO_PLAYERMOVE (17) - Player movement
        self.structures[17] = PacketStructure(
            packet_id=17,
            name="PLO_PLAYERMOVE",
            fields=[
                PacketField("x", PacketFieldType.COORDINATE, description="X coordinate"),
                PacketField("y", PacketFieldType.COORDINATE, description="Y coordinate"),
                PacketField("direction", PacketFieldType.GCHAR, description="Direction facing")
            ],
            description="Player movement update"
        )
        
        # PLO_PLAYERDIR (18) - Player direction change
        self.structures[18] = PacketStructure(
            packet_id=18,
            name="PLO_PLAYERDIR",
            fields=[
                PacketField("direction", PacketFieldType.GCHAR, description="New direction")
            ],
            description="Player direction change"
        )
        
        # PLO_PLAYERWARP (19) - Simple warp
        self.structures[19] = PacketStructure(
            packet_id=19,
            name="PLO_PLAYERWARP",
            fields=[
                PacketField("x", PacketFieldType.COORDINATE, description="X coordinate"),
                PacketField("y", PacketFieldType.COORDINATE, description="Y coordinate")
            ],
            description="Player warp to coordinates"
        )
    
    def _add_item_packets(self):
        """Add item and inventory packets"""
        
        # PLO_ADDITEM (50) - Add item to player
        self.structures[50] = PacketStructure(
            packet_id=50,
            name="PLO_ADDITEM",
            fields=[
                PacketField("item_name", PacketFieldType.VARIABLE_DATA, description="Item filename")
            ],
            description="Add item to player inventory",
            variable_length=True
        )
        
        # PLO_REMOVEITEM (51) - Remove item from player
        self.structures[51] = PacketStructure(
            packet_id=51,
            name="PLO_REMOVEITEM",
            fields=[
                PacketField("item_name", PacketFieldType.VARIABLE_DATA, description="Item filename")
            ],
            description="Remove item from player inventory",
            variable_length=True
        )
        
        # PLO_ITEMTAKEN (53) - Item taken by player
        self.structures[53] = PacketStructure(
            packet_id=53,
            name="PLO_ITEMTAKEN",
            fields=[
                PacketField("x", PacketFieldType.COORDINATE, description="X coordinate"),
                PacketField("y", PacketFieldType.COORDINATE, description="Y coordinate")
            ],
            description="Item taken from level"
        )
        
        # PLO_BOMBADDED (54) - Bomb placed
        self.structures[54] = PacketStructure(
            packet_id=54,
            name="PLO_BOMBADDED",
            fields=[
                PacketField("x", PacketFieldType.COORDINATE, description="X coordinate"),
                PacketField("y", PacketFieldType.COORDINATE, description="Y coordinate"),
                PacketField("power", PacketFieldType.GCHAR, description="Bomb power")
            ],
            description="Bomb placed on level"
        )
    
    def _add_level_packets(self):
        """Add level and world packets"""
        
        # PLO_BOARDPACKAGE (7) - Board changes
        self.structures[7] = PacketStructure(
            packet_id=7,
            name="PLO_BOARDPACKAGE",
            fields=[
                PacketField("changes", PacketFieldType.VARIABLE_DATA, description="Board change data")
            ],
            description="Board tile changes",
            variable_length=True
        )
        
        # PLO_LEVELMODI (10) - Level modification
        self.structures[10] = PacketStructure(
            packet_id=10,
            name="PLO_LEVELMODI",
            fields=[
                PacketField("x", PacketFieldType.COORDINATE, description="X coordinate"),
                PacketField("y", PacketFieldType.COORDINATE, description="Y coordinate"), 
                PacketField("new_tile", PacketFieldType.GINT3, description="New tile ID")
            ],
            description="Single tile modification"
        )
        
        # PLO_HURTPLAYER (14) - Player hurt
        self.structures[14] = PacketStructure(
            packet_id=14,
            name="PLO_HURTPLAYER",
            fields=[
                PacketField("damage", PacketFieldType.GCHAR, description="Damage amount"),
                PacketField("x", PacketFieldType.COORDINATE, description="X coordinate"),
                PacketField("y", PacketFieldType.COORDINATE, description="Y coordinate")
            ],
            description="Player takes damage"
        )
        
        # PLO_LEVELMODTIME (39) - Level modification time  
        self.structures[39] = PacketStructure(
            packet_id=39,
            name="PLO_LEVELMODTIME",
            fields=[
                PacketField("timestamp", PacketFieldType.GINT5, description="Level modification timestamp")
            ],
            description="Level modification timestamp"
        )
    
    def _add_weapon_packets(self):
        """Add weapon and combat packets"""
        
        # PLO_WEAPONADD (35) - Add weapon to player
        self.structures[35] = PacketStructure(
            packet_id=35,
            name="PLO_WEAPONADD",
            fields=[
                PacketField("weapon_data", PacketFieldType.VARIABLE_DATA, description="Weapon script data")
            ],
            description="Add weapon to player",
            variable_length=True
        )
        
        # PLO_WEAPONDEL (36) - Remove weapon from player
        self.structures[36] = PacketStructure(
            packet_id=36,
            name="PLO_WEAPONDEL",
            fields=[
                PacketField("weapon_name", PacketFieldType.VARIABLE_DATA, description="Weapon name")
            ],
            description="Remove weapon from player",
            variable_length=True
        )
        
        # PLO_EXPLOSION (40) - Explosion effect
        self.structures[40] = PacketStructure(
            packet_id=40,
            name="PLO_EXPLOSION",
            fields=[
                PacketField("x", PacketFieldType.COORDINATE, description="X coordinate"),
                PacketField("y", PacketFieldType.COORDINATE, description="Y coordinate"),
                PacketField("radius", PacketFieldType.GCHAR, description="Explosion radius"),
                PacketField("power", PacketFieldType.GCHAR, description="Explosion power")
            ],
            description="Explosion at coordinates"
        )
    
    def _add_system_packets(self):
        """Add system and protocol packets"""
        
        # PLO_NICKNAME (56) - Player nickname change
        self.structures[56] = PacketStructure(
            packet_id=56,
            name="PLO_NICKNAME",
            fields=[
                PacketField("nickname", PacketFieldType.VARIABLE_DATA, description="New nickname")
            ],
            description="Player nickname change",
            variable_length=True
        )
        
        # PLO_SERVERMESSAGE (57) - Server message
        self.structures[57] = PacketStructure(
            packet_id=57,
            name="PLO_SERVERMESSAGE",
            fields=[
                PacketField("message", PacketFieldType.VARIABLE_DATA, description="Server message text")
            ],
            description="Server broadcast message",
            variable_length=True
        )
        
        # PLO_TIMEGET (58) - Time synchronization
        self.structures[58] = PacketStructure(
            packet_id=58,
            name="PLO_TIMEGET",
            fields=[
                PacketField("timestamp", PacketFieldType.GINT4, description="Server timestamp")
            ],
            description="Server time synchronization"
        )
        
        # PLO_UNKNOWN188 (188) - Unknown system packet
        self.structures[188] = PacketStructure(
            packet_id=188,
            name="PLO_UNKNOWN188",
            fields=[],
            description="Unknown system packet"
        )
        
        # PLO_NEWPLAYERC (95) - New player connect
        self.structures[95] = PacketStructure(
            packet_id=95,
            name="PLO_NEWPLAYERC",
            fields=[
                PacketField("connection_data", PacketFieldType.VARIABLE_DATA, description="Connection info")
            ],
            description="New player connection",
            variable_length=True
        )
    
    def _add_missing_packets(self):
        """Add missing packets found in test logs"""
        
        # PLO_ISLEADER (10) - Player is leader
        self.structures[10] = PacketStructure(
            packet_id=10,
            name="PLO_ISLEADER",
            fields=[],
            description="Player is leader notification"
        )
        
        # PLO_NPCWEAPONADD (33) - NPC weapon addition (seen in logs)
        self.structures[33] = PacketStructure(
            packet_id=33,
            name="PLO_NPCWEAPONADD",
            fields=[
                PacketField("weapon_script", PacketFieldType.VARIABLE_DATA, description="NPC weapon script data")
            ],
            description="Add weapon to NPC",
            variable_length=True
        )
        
        # PLO_PLAYERWARP2 (49) - Advanced player warp with GMAP data
        self.structures[49] = PacketStructure(
            packet_id=49,
            name="PLO_PLAYERWARP2",
            fields=[
                PacketField("x2", PacketFieldType.BYTE, description="X coordinate * 2"),
                PacketField("y2", PacketFieldType.BYTE, description="Y coordinate * 2"),
                PacketField("z_plus_50", PacketFieldType.BYTE, description="Z coordinate + 50"),
                PacketField("map_x", PacketFieldType.BYTE, description="GMAP level X coordinate"),
                PacketField("map_y", PacketFieldType.BYTE, description="GMAP level Y coordinate"),
                PacketField("gmap_name", PacketFieldType.VARIABLE_DATA, description="GMAP filename")
            ],
            description="Advanced player warp with GMAP coordinates",
            variable_length=True
        )
        
        # PLO_SETACTIVELEVEL (156) - Set active level
        self.structures[156] = PacketStructure(
            packet_id=156,
            name="PLO_SETACTIVELEVEL",
            fields=[
                PacketField("level_name", PacketFieldType.VARIABLE_DATA, description="Active level name")
            ],
            description="Set active level for server operations",
            variable_length=True
        )
        
        # PLO_GHOSTICON (174) - Ghost mode icon
        self.structures[174] = PacketStructure(
            packet_id=174,
            name="PLO_GHOSTICON",
            fields=[
                PacketField("icon_data", PacketFieldType.GCHAR, description="Ghost icon data")
            ],
            description="Ghost mode icon display"
        )
        
        # PLO_RPGWINDOW (179) - RPG window content
        self.structures[179] = PacketStructure(
            packet_id=179,
            name="PLO_RPGWINDOW",
            fields=[
                PacketField("window_content", PacketFieldType.VARIABLE_DATA, description="RPG window HTML/text content")
            ],
            description="RPG window display content",
            variable_length=True
        )
        
        # PLO_LARGEFILESTART (68) - Large file transfer start
        self.structures[68] = PacketStructure(
            packet_id=68,
            name="PLO_LARGEFILESTART",
            fields=[
                PacketField("filename", PacketFieldType.STRING_GCHAR_LEN, description="File name to be transferred")
            ],
            description="Large file transfer initiation",
            variable_length=True
        )
        
        # PLO_LARGEFILEEND (69) - Large file transfer end
        self.structures[69] = PacketStructure(
            packet_id=69,
            name="PLO_LARGEFILEEND",
            fields=[
                PacketField("filename", PacketFieldType.VARIABLE_DATA, description="Completed file name")
            ],
            description="Large file transfer completion",
            variable_length=True
        )
        
        # PLO_LARGEFILESIZE (84) - Large file size notification
        self.structures[84] = PacketStructure(
            packet_id=84,
            name="PLO_LARGEFILESIZE",
            fields=[
                PacketField("file_size", PacketFieldType.GINT5, description="Total file size in bytes")
            ],
            description="Large file total size information",
            variable_length=False
        )
    
    def get_structure(self, packet_id: int) -> Optional[PacketStructure]:
        """Get packet structure by ID"""
        return self.structures.get(packet_id)
    
    def has_structure(self, packet_id: int) -> bool:
        """Check if packet structure is known"""
        return packet_id in self.structures
    
    def get_all_structures(self) -> dict:
        """Get all registered structures"""
        return self.structures.copy()

# Global registry instance
PACKET_REGISTRY = PacketRegistry()