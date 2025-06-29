"""
Packet parsing and handling
"""

import struct
from typing import Dict, Callable, Optional, Tuple, Any
from ..protocol.enums import ServerToPlayer, PlayerProp
from ..models.player import Player
from ..models.level import Level, Sign, Chest, LevelLink

class PacketReader:
    """Utility for reading packet data"""
    
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
    
    def read_byte(self) -> int:
        """Read single byte (with -32 decoding)"""
        if self.pos >= len(self.data):
            return 0
        value = self.data[self.pos] - 32
        self.pos += 1
        return max(0, value)
    
    def read_raw_byte(self) -> int:
        """Read raw byte without decoding"""
        if self.pos >= len(self.data):
            return 0
        value = self.data[self.pos]
        self.pos += 1
        return value
    
    def read_short(self) -> int:
        """Read 2-byte value"""
        low = self.read_byte()
        high = self.read_byte()
        return low | (high << 8)
    
    def read_int(self) -> int:
        """Read 4-byte value"""
        value = 0
        for i in range(4):
            value |= (self.read_byte() << (i * 8))
        return value
    
    def read_string(self, length: int) -> str:
        """Read fixed-length string"""
        if self.pos + length > len(self.data):
            length = len(self.data) - self.pos
        text = self.data[self.pos:self.pos + length].decode('ascii', errors='replace')
        self.pos += length
        return text
    
    def read_gstring(self) -> str:
        """Read newline-terminated string"""
        text = ""
        while self.pos < len(self.data):
            char = self.read_raw_byte()
            if char == ord('\n'):
                break
            text += chr(char)
        return text
    
    def read_string_with_length(self) -> str:
        """Read string with length prefix"""
        length = self.read_byte()
        if length < 0 or length > 223:  # Sanity check for Graal encoding
            return ""
        return self.read_string(length)
    
    def remaining(self) -> int:
        """Get remaining bytes"""
        return len(self.data) - self.pos
    
    def has_more(self) -> bool:
        """Check if more data available"""
        return self.pos < len(self.data)
    
    def peek_byte(self) -> int:
        """Peek at next byte without advancing"""
        if self.pos >= len(self.data):
            return 0
        return self.data[self.pos] - 32


class PacketHandler:
    """Handles incoming packets from server"""
    
    def __init__(self):
        self.handlers = {}
        self._register_handlers()
        
    def _register_handlers(self):
        """Register packet handlers"""
        self.handlers[ServerToPlayer.PLO_PLAYERPROPS] = self._handle_player_props
        self.handlers[ServerToPlayer.PLO_OTHERPLPROPS] = self._handle_other_player_props
        self.handlers[ServerToPlayer.PLO_LEVELNAME] = self._handle_level_name
        self.handlers[ServerToPlayer.PLO_BOARDMODIFY] = self._handle_board_modify
        self.handlers[ServerToPlayer.PLO_PLAYERWARP] = self._handle_player_warp
        self.handlers[ServerToPlayer.PLO_TOALL] = self._handle_toall
        self.handlers[ServerToPlayer.PLO_PRIVATEMESSAGE] = self._handle_private_message
        self.handlers[ServerToPlayer.PLO_ADDPLAYER] = self._handle_add_player
        self.handlers[ServerToPlayer.PLO_DELPLAYER] = self._handle_del_player
        self.handlers[ServerToPlayer.PLO_SIGNATURE] = self._handle_signature
        self.handlers[ServerToPlayer.PLO_SERVERTEXT] = self._handle_server_text
        self.handlers[ServerToPlayer.PLO_FILE] = self._handle_file
        self.handlers[ServerToPlayer.PLO_LEVELBOARD] = self._handle_level_board
        self.handlers[ServerToPlayer.PLO_LEVELSIGN] = self._handle_level_sign
        self.handlers[ServerToPlayer.PLO_LEVELCHEST] = self._handle_level_chest
        self.handlers[ServerToPlayer.PLO_LEVELLINK] = self._handle_level_link
        self.handlers[ServerToPlayer.PLO_FLAGSET] = self._handle_flag_set
        self.handlers[ServerToPlayer.PLO_FLAGDEL] = self._handle_flag_del
        self.handlers[ServerToPlayer.PLO_BOMBADD] = self._handle_bomb_add
        self.handlers[ServerToPlayer.PLO_BOMBDEL] = self._handle_bomb_del
        self.handlers[ServerToPlayer.PLO_ARROWADD] = self._handle_arrow_add
        self.handlers[ServerToPlayer.PLO_FIRESPY] = self._handle_firespy
        self.handlers[ServerToPlayer.PLO_EXPLOSION] = self._handle_explosion
        self.handlers[ServerToPlayer.PLO_NPCPROPS] = self._handle_npc_props
        self.handlers[ServerToPlayer.PLO_NPCDEL] = self._handle_npc_del
        self.handlers[ServerToPlayer.PLO_NPCDEL2] = self._handle_npc_del2
        self.handlers[ServerToPlayer.PLO_BADDYPROPS] = self._handle_baddy_props
        self.handlers[ServerToPlayer.PLO_NPCACTION] = self._handle_npc_action
        self.handlers[ServerToPlayer.PLO_CLEARWEAPONS] = self._handle_clear_weapons
        self.handlers[ServerToPlayer.PLO_NC_CLASSADD] = self._handle_nc_classadd
        self.handlers[ServerToPlayer.PLO_FULLSTOP2] = self._handle_fullstop2
        self.handlers[ServerToPlayer.PLO_UNKNOWN198] = self._handle_unknown198
        self.handlers[65] = self._handle_rc_listrcs  # PLI_RC_LISTRCS
        
    
    def handle_packet(self, packet_id: int, data: bytes) -> Optional[Dict[str, Any]]:
        """Handle a single packet"""
        if packet_id in self.handlers:
            reader = PacketReader(data)
            return self.handlers[packet_id](reader)
        return None
    
    def _handle_player_props(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle player properties update"""
        props = {}
        
        while reader.has_more():
            prop_id = reader.read_byte()
            if prop_id == ord('\n') - 32:  # End of packet
                break
                
            # Try to get property enum, handle unknown properties
            try:
                prop = PlayerProp(prop_id)
            except ValueError:
                # Unknown property - try to parse it generically
                # Check if it looks like a string property (has length byte)
                if reader.has_more():
                    peek_byte = reader.peek_byte()
                    if 0 <= peek_byte < 223:  # Looks like a valid string length
                        length = reader.read_byte()
                        if reader.remaining() >= length:
                            reader.read_string(length)  # Skip the string
                        continue
                # Otherwise assume single byte property
                reader.read_byte()
                continue
            
            # Parse property value based on type
            if prop == PlayerProp.PLPROP_COLORS:
                # Colors array - 5 bytes
                value = [reader.read_byte() for _ in range(5)]
            elif prop == PlayerProp.PLPROP_HEADGIF:
                # Head image uses length + 100
                length = reader.read_byte() - 100
                if length > 0 and reader.remaining() >= length:
                    value = reader.read_string(length)
                else:
                    value = ""
            elif prop == PlayerProp.PLPROP_SWORDPOWER:
                # Sword power special encoding: [length][power+30][image]
                length = reader.read_byte()
                if length > 0 and reader.remaining() >= length:
                    sword_id = reader.read_byte() - 30
                    sword_image = reader.read_string(length - 1) if length > 1 else ""
                    value = (sword_id, sword_image)
                else:
                    value = (0, "")
            elif prop in [PlayerProp.PLPROP_NICKNAME, PlayerProp.PLPROP_CURCHAT, 
                         PlayerProp.PLPROP_GANI, PlayerProp.PLPROP_BODYIMG,
                         PlayerProp.PLPROP_HORSEGIF, PlayerProp.PLPROP_ACCOUNTNAME,
                         PlayerProp.PLPROP_CURLEVEL, PlayerProp.PLPROP_COMMUNITYNAME]:
                # String properties with length prefix
                value = reader.read_string_with_length()
            elif prop in [PlayerProp.PLPROP_X2, PlayerProp.PLPROP_Y2, PlayerProp.PLPROP_Z2]:
                # High precision coordinates (2 bytes)
                value = reader.read_short()
            else:
                # All other properties are single byte
                value = reader.read_byte()
            
            props[prop] = value
        
        return {"type": "player_props", "props": props}
    
    def _handle_other_player_props(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle other player properties"""
        player_id = reader.read_short()
        props = self._handle_player_props(reader)["props"]
        return {"type": "other_player_props", "player_id": player_id, "props": props}
    
    def _handle_level_name(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle level name"""
        name = reader.read_gstring()
        return {"type": "level_name", "name": name}
    
    def _handle_board_modify(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle board modification"""
        mod_x = reader.read_byte()
        mod_y = reader.read_byte()
        width = reader.read_byte()
        height = reader.read_byte()
        
        tiles = []
        for _ in range(width * height):
            tiles.append(reader.read_short())
        
        return {
            "type": "board_modify",
            "x": mod_x,
            "y": mod_y,
            "width": width,
            "height": height,
            "tiles": tiles
        }
    
    def _handle_player_warp(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle player warp"""
        x = reader.read_byte() / 2.0
        y = reader.read_byte() / 2.0
        level = reader.read_gstring()
        return {"type": "player_warp", "x": x, "y": y, "level": level}
    
    def _handle_toall(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle chat message (PLO_TOALL format: [player_id][length][message])"""
        player_id = reader.read_short()
        message = reader.read_string_with_length()
        return {"type": "toall", "player_id": player_id, "message": message}
    
    def _handle_private_message(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle private message"""
        player_id = reader.read_short()
        message = reader.read_gstring()
        return {"type": "private_message", "player_id": player_id, "message": message}
    
    def _handle_add_player(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle player addition"""
        # Contains player properties
        props = self._handle_player_props(reader)["props"]
        player_id = props.get(PlayerProp.PLPROP_ID, -1)
        return {"type": "add_player", "player_id": player_id, "props": props}
    
    def _handle_del_player(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle player removal"""
        player_id = reader.read_short()
        return {"type": "del_player", "player_id": player_id}
    
    def _handle_signature(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle server signature"""
        signature = reader.read_gstring()
        return {"type": "signature", "signature": signature}
    
    def _handle_server_text(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle server text"""
        text = reader.read_gstring()
        return {"type": "server_text", "text": text}
    
    def _handle_file(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle file data"""
        filename = reader.read_string_with_length()
        data = reader.data[reader.pos:]  # Rest is file data
        return {"type": "file", "filename": filename, "data": data}
    
    def _handle_level_board(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle level board data"""
        # Complex parsing - simplified version
        return {"type": "level_board", "data": reader.data[reader.pos:]}
    
    def _handle_level_sign(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle level sign"""
        x = reader.read_byte()
        y = reader.read_byte()
        text = reader.read_gstring()
        return {"type": "level_sign", "x": x, "y": y, "text": text}
    
    def _handle_level_chest(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle level chest"""
        x = reader.read_byte()
        y = reader.read_byte()
        item = reader.read_byte()
        sign_text = reader.read_gstring()
        return {"type": "level_chest", "x": x, "y": y, "item": item, "sign_text": sign_text}
    
    def _handle_level_link(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle level link"""
        # Complex format - simplified
        return {"type": "level_link", "data": reader.data[reader.pos:]}
    
    def _handle_flag_set(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle flag set"""
        flag_name = reader.read_string_with_length()
        value = reader.read_gstring()
        return {"type": "flag_set", "flag": flag_name, "value": value}
    
    def _handle_flag_del(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle flag deletion"""
        flag_name = reader.read_string_with_length()
        return {"type": "flag_del", "flag": flag_name}
    
    def _handle_bomb_add(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle bomb addition"""
        player_id = reader.read_short()
        x = reader.read_byte() / 2.0
        y = reader.read_byte() / 2.0
        power = reader.read_byte()
        timer = reader.read_byte()
        return {"type": "bomb_add", "player_id": player_id, "x": x, "y": y, 
                "power": power, "timer": timer}
    
    def _handle_bomb_del(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle bomb deletion"""
        # Format varies
        return {"type": "bomb_del", "data": reader.data[reader.pos:]}
    
    def _handle_arrow_add(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle arrow addition"""
        player_id = reader.read_short()
        # Rest varies by version
        return {"type": "arrow_add", "player_id": player_id, "data": reader.data[reader.pos:]}
    
    def _handle_firespy(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle fire effect"""
        player_id = reader.read_short()
        return {"type": "firespy", "player_id": player_id}
    
    def _handle_explosion(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle explosion"""
        x = reader.read_byte() / 2.0
        y = reader.read_byte() / 2.0
        power = reader.read_byte()
        return {"type": "explosion", "x": x, "y": y, "power": power}
    
    def _handle_npc_props(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle NPC properties"""
        npc_id = reader.read_int()
        # Complex format - simplified
        return {"type": "npc_props", "npc_id": npc_id, "data": reader.data[reader.pos:]}
    
    def _handle_npc_del(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle NPC deletion"""
        npc_id = reader.read_int()
        return {"type": "npc_del", "npc_id": npc_id}
    
    def _handle_npc_del2(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle NPC deletion v2"""
        level = reader.read_string_with_length()
        npc_id = reader.read_int()
        return {"type": "npc_del2", "level": level, "npc_id": npc_id}
    
    def _handle_baddy_props(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle baddy properties"""
        baddy_id = reader.read_byte()
        x = reader.read_byte() / 2.0
        y = reader.read_byte() / 2.0
        baddy_type = reader.read_byte()
        # More properties follow
        return {"type": "baddy_props", "baddy_id": baddy_id, "x": x, "y": y, 
                "baddy_type": baddy_type}
    
    def _handle_clear_weapons(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle clear weapons packet (PLO_CLEARWEAPONS)"""
        # According to GServer source: blank packet sent before weapon list
        return {"type": "clear_weapons"}
    
    def _handle_nc_classadd(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle NPC Controller class add (PLO_NC_CLASSADD)"""
        # Format: {113}{CHAR name length}{name}{GSTRING script}
        class_name = reader.read_string_with_length()
        script_code = reader.read_gstring()
        return {"type": "nc_classadd", "class_name": class_name, "script_code": script_code}
    
    def _handle_fullstop2(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle fullstop2 packet (PLO_FULLSTOP2)"""
        # Causes client to not respond to normal input and hides HUD
        return {"type": "fullstop2"}
    
    def _handle_unknown198(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle unknown packet 198 (PLO_UNKNOWN198)"""
        # Unknown purpose, valid in 6.037
        return {"type": "unknown198", "data": reader.data[reader.pos:]}
    
    def _handle_rc_listrcs(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle RC list RCs packet (PLI_RC_LISTRCS)"""
        # Deprecated RC command to list connected RC clients
        return {"type": "rc_listrcs"}
    
    def _handle_npc_action(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle NPC action packet (PLO_NPCACTION)"""
        # Format varies, usually contains NPC ID and action data
        return {"type": "npc_action", "data": reader.data[reader.pos:]}