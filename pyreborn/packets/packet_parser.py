"""
Packet parser - converts raw packets to typed packet objects
"""

import logging
import struct
from typing import Optional, Dict, Any, List

from .packet_types import *


logger = logging.getLogger(__name__)


class PacketReader:
    """Helper for reading packet data"""
    
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        
    def read_byte(self) -> int:
        """Read a single byte"""
        if self.pos >= len(self.data):
            return 0
        value = self.data[self.pos]
        self.pos += 1
        return value
        
    def read_char(self) -> int:
        """Read GChar (subtract 32)"""
        return self.read_byte() - 32
        
    def read_short(self) -> int:
        """Read 2-byte short"""
        if self.pos + 1 >= len(self.data):
            return 0
        value = struct.unpack_from('<H', self.data, self.pos)[0]
        self.pos += 2
        return value
        
    def read_gshort(self) -> int:
        """Read Graal-encoded short (2 bytes)
        
        Graal uses a special encoding where each byte has 32 added,
        and the value is split into 7-bit chunks. The server caps
        values at 28767, but can send negative values.
        """
        if self.pos + 1 >= len(self.data):
            return 0
        b1 = self.data[self.pos] - 32
        b2 = self.data[self.pos + 1] - 32
        self.pos += 2
        
        # Reconstruct the value
        value = (b1 << 7) + b2
        
        # Handle signed values - if value > 16383, it's negative
        if value > 16383:
            value = value - 32768
            
        return value
        
    def read_gushort(self) -> int:
        """Read Graal-encoded unsigned short (2 bytes)
        
        Same as read_gshort but returns unsigned value
        """
        if self.pos + 1 >= len(self.data):
            return 0
        b1 = self.data[self.pos] - 32
        b2 = self.data[self.pos + 1] - 32
        self.pos += 2
        
        # Reconstruct the value (unsigned)
        value = (b1 << 7) + b2
        return value
        
    def read_int(self) -> int:
        """Read 4-byte int"""
        if self.pos + 3 >= len(self.data):
            return 0
        value = struct.unpack_from('<I', self.data, self.pos)[0]
        self.pos += 4
        return value
        
    def read_gint3(self) -> int:
        """Read 3-byte GINT"""
        if self.pos + 2 >= len(self.data):
            return 0
        b1 = self.read_char()
        b2 = self.read_char()
        b3 = self.read_char()
        return b1 | (b2 << 6) | (b3 << 12)
        
    def read_gint5(self) -> int:
        """Read 5-byte GINT"""
        if self.pos + 4 >= len(self.data):
            return 0
        b1 = self.read_char()
        b2 = self.read_char()
        b3 = self.read_char()
        b4 = self.read_char()
        b5 = self.read_char()
        return b1 | (b2 << 6) | (b3 << 12) | (b4 << 18) | (b5 << 24)
        
    def read_string(self, length: int) -> str:
        """Read fixed-length string"""
        if self.pos + length > len(self.data):
            length = len(self.data) - self.pos
        value = self.data[self.pos:self.pos + length].decode('latin-1', errors='replace')
        self.pos += length
        return value
        
    def read_gstring(self) -> str:
        """Read length-prefixed string (GChar length)"""
        length = self.read_char()
        return self.read_string(length)
        
    def read_line(self) -> str:
        """Read until newline or end"""
        start = self.pos
        while self.pos < len(self.data) and self.data[self.pos] != ord('\n'):
            self.pos += 1
        value = self.data[start:self.pos].decode('latin-1', errors='replace')
        if self.pos < len(self.data):
            self.pos += 1  # Skip newline
        return value
        
    def read_remaining(self) -> bytes:
        """Read all remaining data"""
        value = self.data[self.pos:]
        self.pos = len(self.data)
        return value
        
    def remaining(self) -> int:
        """Get number of bytes remaining"""
        return len(self.data) - self.pos
        
    def peek_byte(self) -> int:
        """Peek at next byte without advancing"""
        if self.pos >= len(self.data):
            return 0
        return self.data[self.pos]


class PacketParser:
    """Parses raw packets into typed packet objects"""
    
    def __init__(self, version: str = "2.19"):
        self.version = version
        self.parsers = self._init_parsers()
        
    def _copy_timestamp(self, new_packet: Packet, old_packet: Packet) -> Packet:
        """Copy timestamp from old packet to new"""
        new_packet.timestamp = old_packet.timestamp
        return new_packet
        
    def _init_parsers(self) -> Dict[int, callable]:
        """Initialize packet parsers"""
        return {
            PacketID.PLO_RAWDATA: self._parse_raw_data,
            PacketID.PLO_FILE: self._parse_file,
            PacketID.PLO_BOARDPACKET: self._parse_board,
            PacketID.PLO_LEVELNAME: self._parse_level_name,
            PacketID.PLO_PLAYERPROPS: self._parse_player_props,
            PacketID.PLO_ADDPLAYER: self._parse_add_player,
            PacketID.PLO_PLAYERMOVED: self._parse_player_moved,
            PacketID.PLO_SAY: self._parse_chat,
            PacketID.PLO_SIGNATURE: self._parse_signature,
            PacketID.PLO_FLAGSET: self._parse_flag_set,
            PacketID.PLO_BOARDMODIFY: self._parse_board_modify,
            PacketID.PLO_LEVELSIGN: self._parse_level_sign,
            PacketID.PLO_LEVELCHEST: self._parse_level_chest,
            PacketID.PLO_LEVELLINK: self._parse_level_link,
            PacketID.PLO_BOMBADD: self._parse_bomb_add,
            PacketID.PLO_BOMBDEL: self._parse_bomb_del,
            PacketID.PLO_ARROWADD: self._parse_arrow_add,
            PacketID.PLO_EXPLOSION: self._parse_explosion,
            PacketID.PLO_FIRESPY: self._parse_firespy,
            PacketID.PLO_DISCMESSAGE: self._parse_disconnect_message,
            PacketID.PLO_WARPFAILED: self._parse_warp_failed,
            PacketID.PLO_SERVERTEXT: self._parse_server_text,
            PacketID.PLO_FILESENDFAILED: self._parse_file_failed,
            PacketID.PLO_PLAYERWARP: self._parse_player_warp,
            PacketID.PLO_HASNPCSERVER: self._parse_has_npc_server,
            PacketID.PLO_DEFAULTWEAPON: self._parse_default_weapon,
            PacketID.PLO_NPCWEAPONADD: self._parse_npc_weapon_add,
            PacketID.PLO_NPCWEAPONDEL: self._parse_npc_weapon_del,
            PacketID.PLO_CLEARWEAPONS: self._parse_clear_weapons,
            PacketID.PLO_TOALL: self._parse_toall,
            PacketID.PLO_PRIVMESSAGE: self._parse_private_message,
            PacketID.PLO_SERVERMESSAGE: self._parse_server_message,
            PacketID.PLO_NPCPROPS: self._parse_npc_props,
            PacketID.PLO_NPCMOVED: self._parse_npc_moved,
            PacketID.PLO_NPCACTION: self._parse_npc_action,
            PacketID.PLO_NPCDEL: self._parse_npc_del,
            PacketID.PLO_SHOWIMG: self._parse_show_img,
            PacketID.PLO_GHOSTTEXT: self._parse_ghost_text,
            PacketID.PLO_GHOSTICON: self._parse_ghost_icon,
        }
        
    def parse(self, packet: Packet) -> Packet:
        """Parse a raw packet into a typed packet object"""
        parser = self.parsers.get(packet.packet_id)
        
        if parser:
            try:
                return parser(packet)
            except Exception as e:
                logger.error(f"Failed to parse packet {packet.packet_id}: {e}")
                return packet
        else:
            # No parser, return raw packet
            return packet
            
    def _parse_raw_data(self, packet: Packet) -> RawDataPacket:
        """Parse PLO_RAWDATA packet"""
        reader = PacketReader(packet.raw_data)
        
        # Read expected size (3 bytes GINT3)
        expected_size = reader.read_gint3()
        
        return self._copy_timestamp(RawDataPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            expected_size=expected_size
        ), packet)
            
    def _parse_file(self, packet: Packet) -> FilePacket:
        """Parse PLO_FILE packet"""
        reader = PacketReader(packet.raw_data)
        
        # Read modTime (5 bytes for v2.1+)
        mod_time = reader.read_gint5()
        
        # Read filename (length-prefixed)
        filename = reader.read_gstring()
        
        # Rest is file data
        file_data = reader.read_remaining()
        
        return self._copy_timestamp(FilePacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            filename=filename,
            mod_time=mod_time,
            file_data=file_data
        ), packet)
        
    def _parse_board(self, packet: Packet) -> BoardPacket:
        """Parse PLO_BOARDPACKET"""
        # Board packet is just 8192 bytes of tile data
        return BoardPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            board_data=packet.raw_data[:8192] if len(packet.raw_data) >= 8192 else packet.raw_data
        )
        
    def _parse_level_name(self, packet: Packet) -> LevelNamePacket:
        """Parse PLO_LEVELNAME"""
        level_name = packet.raw_data.decode('latin-1', errors='replace').strip()
        return LevelNamePacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            level_name=level_name
        )
        
    def _parse_player_props(self, packet: Packet) -> PlayerPropsPacket:
        """Parse PLO_PLAYERPROPS"""
        reader = PacketReader(packet.raw_data)
        
        # Read player ID
        player_id = reader.read_byte()
        
        # Read properties
        properties = {}
        while reader.remaining() > 0:
            prop_id = reader.read_byte()
            
            if prop_id == 0:  # NICKNAME
                properties[prop_id] = reader.read_gstring()
            elif prop_id == 1:  # MAXHP
                properties[prop_id] = reader.read_byte()
            elif prop_id == 2:  # HP
                properties[prop_id] = reader.read_byte() / 2.0
            elif prop_id == 3:  # MINIMAP
                properties[prop_id] = reader.read_gstring()
            elif prop_id == 4:  # ARROWS
                properties[prop_id] = reader.read_byte()
            elif prop_id == 5:  # BOMBS
                properties[prop_id] = reader.read_byte()
            # ... add more properties as needed
            else:
                # Unknown property, try to skip
                break
                
        return PlayerPropsPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            player_id=player_id,
            properties=properties
        )
        
    def _parse_add_player(self, packet: Packet) -> AddPlayerPacket:
        """Parse PLO_ADDPLAYER"""
        reader = PacketReader(packet.raw_data)
        
        player_id = reader.read_short()
        
        # Parse player properties inline
        x = 30.0
        y = 30.0
        account = ""
        nickname = ""
        
        while reader.remaining() > 0:
            prop_id = reader.read_byte()
            
            if prop_id == 0:  # NICKNAME
                nickname = reader.read_gstring()
            elif prop_id == 35:  # ACCOUNT
                account = reader.read_gstring()
            elif prop_id == 84:  # X2
                x = reader.read_byte() / 2.0
            elif prop_id == 85:  # Y2
                y = reader.read_byte() / 2.0
            else:
                # Skip unknown properties
                break
                
        return AddPlayerPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            player_id=player_id,
            account=account,
            nickname=nickname,
            x=x,
            y=y
        )
        
    def _parse_player_moved(self, packet: Packet) -> PlayerMovedPacket:
        """Parse PLO_PLAYERMOVED"""
        reader = PacketReader(packet.raw_data)
        
        player_id = reader.read_short()
        
        # Movement data format varies by version
        # Simplified parsing here
        x = reader.read_byte() / 2.0
        y = reader.read_byte() / 2.0
        direction = reader.read_byte() % 4
        sprite = reader.read_byte()
        
        return PlayerMovedPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            player_id=player_id,
            x=x,
            y=y,
            direction=direction,
            sprite=sprite
        )
        
    def _parse_chat(self, packet: Packet) -> ChatPacket:
        """Parse PLO_SAY"""
        reader = PacketReader(packet.raw_data)
        
        player_id = reader.read_short()
        message = reader.read_remaining().decode('latin-1', errors='replace')
        
        return ChatPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            player_id=player_id,
            message=message
        )
        
    def _parse_signature(self, packet: Packet) -> SignaturePacket:
        """Parse PLO_SIGNATURE"""
        signature = packet.raw_data.decode('latin-1', errors='replace')
        
        return SignaturePacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            signature=signature
        )
        
    def _parse_flag_set(self, packet: Packet) -> FlagSetPacket:
        """Parse PLO_FLAGSET"""
        flag_data = packet.raw_data.decode('latin-1', errors='replace')
        
        # Format: flagname=value
        if '=' in flag_data:
            flag_name, flag_value = flag_data.split('=', 1)
        else:
            flag_name = flag_data
            flag_value = ""
            
        return FlagSetPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            flag_name=flag_name,
            flag_value=flag_value
        )
        
    def _parse_board_modify(self, packet: Packet) -> BoardModifyPacket:
        """Parse PLO_BOARDMODIFY"""
        reader = PacketReader(packet.raw_data)
        
        x = reader.read_byte()
        y = reader.read_byte()
        width = reader.read_byte()
        height = reader.read_byte()
        
        # Read tile data
        tiles = []
        tile_count = width * height
        for _ in range(tile_count):
            if reader.remaining() >= 2:
                tiles.append(reader.read_short())
                
        result = BoardModifyPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            x=x,
            y=y,
            width=width,
            height=height,
            tiles=tiles
        )
        result.timestamp = packet.timestamp
        return result
        
    def _parse_file_failed(self, packet: Packet) -> FileSendFailedPacket:
        """Parse PLO_FILESENDFAILED"""
        filename = packet.raw_data.decode('latin-1', errors='replace')
        
        return self._copy_timestamp(FileSendFailedPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            filename=filename
        ), packet)
        
    def _parse_player_warp(self, packet: Packet) -> PlayerWarpPacket:
        """Parse PLO_PLAYERWARP"""
        reader = PacketReader(packet.raw_data)
        
        # Read player ID
        player_id = reader.read_short()
        
        # Read X and Y coordinates
        x = reader.read_byte() / 2.0
        y = reader.read_byte() / 2.0
        
        # Read level name if present
        level_name = None
        if reader.remaining() > 0:
            level_name = reader.read_remaining().decode('latin-1', errors='replace').strip()
            
        return self._copy_timestamp(PlayerWarpPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            player_id=player_id,
            x=x,
            y=y,
            level_name=level_name
        ), packet)
        
    def _parse_has_npc_server(self, packet: Packet) -> HasNPCServerPacket:
        """Parse PLO_HASNPCSERVER"""
        # Single byte: 1 = has NPC server, 0 = doesn't
        has_npc_server = len(packet.raw_data) > 0 and packet.raw_data[0] == 1
        
        return self._copy_timestamp(HasNPCServerPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            has_npc_server=has_npc_server
        ), packet)
        
    def _parse_default_weapon(self, packet: Packet) -> DefaultWeaponPacket:
        """Parse PLO_DEFAULTWEAPON"""
        weapon_name = packet.raw_data.decode('latin-1', errors='replace').strip()
        
        return self._copy_timestamp(DefaultWeaponPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            weapon_name=weapon_name
        ), packet)
        
    def _parse_npc_weapon_add(self, packet: Packet) -> NPCWeaponAddPacket:
        """Parse PLO_NPCWEAPONADD"""
        reader = PacketReader(packet.raw_data)
        
        # Read weapon name (null-terminated or newline-terminated)
        weapon_data = reader.read_remaining().decode('latin-1', errors='replace')
        
        # Split by newline for name and potential script
        parts = weapon_data.split('\n', 1)
        weapon_name = parts[0].strip('\x00').strip()
        weapon_script = parts[1] if len(parts) > 1 else None
        
        return self._copy_timestamp(NPCWeaponAddPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            weapon_name=weapon_name,
            weapon_script=weapon_script
        ), packet)
        
    def _parse_npc_weapon_del(self, packet: Packet) -> NPCWeaponDelPacket:
        """Parse PLO_NPCWEAPONDEL"""
        weapon_name = packet.raw_data.decode('latin-1', errors='replace').strip()
        
        return self._copy_timestamp(NPCWeaponDelPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            weapon_name=weapon_name
        ), packet)
        
    def _parse_clear_weapons(self, packet: Packet) -> ClearWeaponsPacket:
        """Parse PLO_CLEARWEAPONS"""
        # This packet has no data
        return self._copy_timestamp(ClearWeaponsPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data
        ), packet)
        
    def _parse_toall(self, packet: Packet) -> ToAllPacket:
        """Parse PLO_TOALL"""
        message = packet.raw_data.decode('latin-1', errors='replace')
        
        return self._copy_timestamp(ToAllPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            message=message
        ), packet)
        
    def _parse_private_message(self, packet: Packet) -> PrivateMessagePacket:
        """Parse PLO_PRIVMESSAGE"""
        reader = PacketReader(packet.raw_data)
        
        # Read sender ID
        sender_id = reader.read_short()
        
        # Read message
        message = reader.read_remaining().decode('latin-1', errors='replace')
        
        return self._copy_timestamp(PrivateMessagePacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            sender_id=sender_id,
            message=message
        ), packet)
        
    def _parse_server_message(self, packet: Packet) -> ServerMessagePacket:
        """Parse PLO_SERVERMESSAGE"""
        message = packet.raw_data.decode('latin-1', errors='replace')
        
        return self._copy_timestamp(ServerMessagePacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            message=message
        ), packet)
        
    def _parse_level_sign(self, packet: Packet) -> LevelSignPacket:
        """Parse PLO_LEVELSIGN"""
        reader = PacketReader(packet.raw_data)
        
        x = reader.read_byte()
        y = reader.read_byte()
        text = reader.read_remaining().decode('latin-1', errors='replace')
        
        return self._copy_timestamp(LevelSignPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            x=x,
            y=y,
            text=text
        ), packet)
        
    def _parse_level_chest(self, packet: Packet) -> LevelChestPacket:
        """Parse PLO_LEVELCHEST"""
        reader = PacketReader(packet.raw_data)
        
        x = reader.read_byte()
        y = reader.read_byte()
        item_id = reader.read_byte()
        sign_text = reader.read_remaining().decode('latin-1', errors='replace')
        
        return self._copy_timestamp(LevelChestPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            x=x,
            y=y,
            item_id=item_id,
            sign_text=sign_text
        ), packet)
        
    def _parse_level_link(self, packet: Packet) -> LevelLinkPacket:
        """Parse PLO_LEVELLINK"""
        reader = PacketReader(packet.raw_data)
        
        # Skip level name and newworld string
        level_name = reader.read_gstring()
        newworld_data = reader.read_gstring()
        
        # Debug log the raw data
        self.logger.debug(f"[LEVELLINK] Level: {level_name}, Raw newworld data: '{newworld_data}'")
        
        # Parse newworld data (format: x y width height destlevel destx desty ...)
        parts = newworld_data.split()
        
        if len(parts) >= 7:
            x = int(parts[0])
            y = int(parts[1])
            width = int(parts[2])
            height = int(parts[3])
            destination_level = parts[4]
            destination_x = parts[5]
            destination_y = parts[6]
            
            # Handle playerx/playery special values
            # Use None to indicate "keep player position"
            if destination_x == 'playerx':
                destination_x = None  # Will be replaced with player's current X
            else:
                destination_x = float(destination_x)
                
            if destination_y == 'playery':
                destination_y = None  # Will be replaced with player's current Y
            else:
                destination_y = float(destination_y)
                
            # Debug log parsed values
            self.logger.debug(f"[LEVELLINK] Parsed: pos({x},{y}) size({width}x{height}) -> {destination_level} at ({destination_x},{destination_y})")
            
            # Log the original parts for debugging
            self.logger.debug(f"[LEVELLINK] Raw parts: {parts}")
        else:
            # Default values if parsing fails
            x = y = 0
            width = height = 1
            destination_level = ""
            destination_x = destination_y = 0.0
        
        return self._copy_timestamp(LevelLinkPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            x=x,
            y=y,
            width=width,
            height=height,
            destination_level=destination_level,
            destination_x=destination_x,
            destination_y=destination_y
        ), packet)
        
    def _parse_bomb_add(self, packet: Packet) -> BombAddPacket:
        """Parse PLO_BOMBADD"""
        reader = PacketReader(packet.raw_data)
        
        player_id = reader.read_short()
        x = reader.read_byte() / 2.0
        y = reader.read_byte() / 2.0
        power = reader.read_byte()
        time = reader.read_byte() / 2.0
        
        return self._copy_timestamp(BombAddPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            player_id=player_id,
            x=x,
            y=y,
            power=power,
            time=time
        ), packet)
        
    def _parse_bomb_del(self, packet: Packet) -> BombDelPacket:
        """Parse PLO_BOMBDEL"""
        # This packet has no data
        return self._copy_timestamp(BombDelPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data
        ), packet)
        
    def _parse_arrow_add(self, packet: Packet) -> ArrowAddPacket:
        """Parse PLO_ARROWADD"""
        reader = PacketReader(packet.raw_data)
        
        player_id = reader.read_short()
        # Arrow packets may have position and direction data
        if reader.remaining() >= 3:
            x = reader.read_byte() / 2.0
            y = reader.read_byte() / 2.0
            direction = reader.read_byte() % 4
        else:
            x = y = 0.0
            direction = 0
        
        return self._copy_timestamp(ArrowAddPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            player_id=player_id,
            x=x,
            y=y,
            direction=direction
        ), packet)
        
    def _parse_explosion(self, packet: Packet) -> ExplosionPacket:
        """Parse PLO_EXPLOSION"""
        reader = PacketReader(packet.raw_data)
        
        # Skip radius and time bytes
        reader.read_byte()  # radius
        reader.read_byte()  # time
        
        x = reader.read_byte() / 2.0
        y = reader.read_byte() / 2.0
        power = reader.read_byte()
        
        return self._copy_timestamp(ExplosionPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            x=x,
            y=y,
            power=power
        ), packet)
        
    def _parse_firespy(self, packet: Packet) -> FirespyPacket:
        """Parse PLO_FIRESPY"""
        reader = PacketReader(packet.raw_data)
        
        player_id = reader.read_short()
        
        return self._copy_timestamp(FirespyPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            player_id=player_id
        ), packet)
        
    def _parse_disconnect_message(self, packet: Packet) -> DisconnectMessagePacket:
        """Parse PLO_DISCMESSAGE"""
        message = packet.raw_data.decode('latin-1', errors='replace')
        
        return self._copy_timestamp(DisconnectMessagePacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            message=message
        ), packet)
        
    def _parse_warp_failed(self, packet: Packet) -> WarpFailedPacket:
        """Parse PLO_WARPFAILED"""
        level_name = packet.raw_data.decode('latin-1', errors='replace').strip()
        
        return self._copy_timestamp(WarpFailedPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            level_name=level_name
        ), packet)
        
    def _parse_server_text(self, packet: Packet) -> ServerTextPacket:
        """Parse PLO_SERVERTEXT"""
        text = packet.raw_data.decode('latin-1', errors='replace')
        
        return self._copy_timestamp(ServerTextPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            text=text
        ), packet)
        
    def _parse_npc_props(self, packet: Packet) -> NPCPropsPacket:
        """Parse PLO_NPCPROPS"""
        reader = PacketReader(packet.raw_data)
        
        # Read NPC ID (2 bytes)
        npc_id = reader.read_short()
        
        # Read properties
        properties = {}
        while reader.remaining() > 0:
            prop_id = reader.read_byte()
            
            # Parse property based on ID
            # NPCProp enum values from v1
            if prop_id == 0:  # IMAGE
                properties[prop_id] = reader.read_gstring()
            elif prop_id == 1:  # SCRIPT
                # Script is length-prefixed with GINT3
                script_len = reader.read_gint3()
                properties[prop_id] = reader.read_string(script_len)
            elif prop_id == 2:  # X
                properties[prop_id] = reader.read_byte() / 2.0
            elif prop_id == 3:  # Y
                properties[prop_id] = reader.read_byte() / 2.0
            elif prop_id in range(4, 14):  # SAVE0-SAVE9
                properties[prop_id] = reader.read_byte()
            elif prop_id == 14:  # NICK
                properties[prop_id] = reader.read_gstring()
            elif prop_id == 15:  # X2
                properties[prop_id] = reader.read_byte() / 2.0
            elif prop_id == 16:  # Y2
                properties[prop_id] = reader.read_byte() / 2.0
            elif prop_id == 17:  # VISFLAGS
                properties[prop_id] = reader.read_byte()
            else:
                # Unknown property, try to skip
                # Most properties are single bytes or strings
                if prop_id < 32:
                    # Single byte property (standard protocol)
                    properties[prop_id] = reader.read_byte()
                else:
                    # Higher property IDs use variable length encoding
                    break
                
        return self._copy_timestamp(NPCPropsPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            npc_id=npc_id,
            properties=properties
        ), packet)
        
    def _parse_npc_moved(self, packet: Packet) -> NPCMovedPacket:
        """Parse PLO_NPCMOVED"""
        reader = PacketReader(packet.raw_data)
        
        # Read NPC ID
        npc_id = reader.read_short()
        
        # Read position and movement data
        x = reader.read_byte() / 2.0
        y = reader.read_byte() / 2.0
        
        # Direction and sprite may be combined in a byte
        if reader.remaining() > 0:
            dir_sprite = reader.read_byte()
            direction = dir_sprite % 4
            sprite = dir_sprite // 4
        else:
            direction = 0
            sprite = 0
            
        return self._copy_timestamp(NPCMovedPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            npc_id=npc_id,
            x=x,
            y=y,
            direction=direction,
            sprite=sprite
        ), packet)
        
    def _parse_npc_action(self, packet: Packet) -> NPCActionPacket:
        """Parse PLO_NPCACTION"""
        reader = PacketReader(packet.raw_data)
        
        # Read NPC ID
        npc_id = reader.read_short()
        
        # Read action string
        action = reader.read_remaining().decode('latin-1', errors='replace')
        
        return self._copy_timestamp(NPCActionPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            npc_id=npc_id,
            action=action
        ), packet)
        
    def _parse_npc_del(self, packet: Packet) -> NPCDeletePacket:
        """Parse PLO_NPCDEL"""
        reader = PacketReader(packet.raw_data)
        
        # Read NPC ID
        npc_id = reader.read_short()
        
        return self._copy_timestamp(NPCDeletePacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            npc_id=npc_id
        ), packet)
        
    def _parse_show_img(self, packet: Packet) -> ShowImagePacket:
        """Parse PLO_SHOWIMG"""
        # Format varies - keep raw data
        return self._copy_timestamp(ShowImagePacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            image_data=packet.raw_data
        ), packet)
        
    def _parse_ghost_text(self, packet: Packet) -> GhostTextPacket:
        """Parse PLO_GHOSTTEXT"""
        reader = PacketReader(packet.raw_data)
        
        # Read text string
        text = reader.read_gstring()
        
        return self._copy_timestamp(GhostTextPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            text=text
        ), packet)
        
    def _parse_ghost_icon(self, packet: Packet) -> GhostIconPacket:
        """Parse PLO_GHOSTICON"""
        reader = PacketReader(packet.raw_data)
        
        # Single byte: 1 = enabled, 0 = disabled
        enabled = reader.read_byte() == 1
        
        return self._copy_timestamp(GhostIconPacket(
            packet_id=packet.packet_id,
            raw_data=packet.raw_data,
            enabled=enabled
        ), packet)