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
        if length < 0 or length > 223:  # Sanity check for Reborn encoding
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
    
    def read_remaining(self) -> bytes:
        """Read all remaining bytes"""
        if self.pos >= len(self.data):
            return b''
        remaining = self.data[self.pos:]
        self.pos = len(self.data)
        return remaining
    
    def skip(self, count: int):
        """Skip forward by count bytes"""
        self.pos += count
        if self.pos > len(self.data):
            self.pos = len(self.data)
    
    def read_bytes(self, count: int) -> bytes:
        """Read raw bytes without decoding"""
        if self.pos + count > len(self.data):
            count = len(self.data) - self.pos
        result = self.data[self.pos:self.pos + count]
        self.pos += count
        return result
    
    def read_gint(self) -> int:
        """Read GInt (Graal integer format) - 3 bytes with +32 encoding"""
        if self.pos + 3 > len(self.data):
            return 0
        
        # Read 3 raw bytes (without -32 decoding)
        val = [self.data[self.pos + i] for i in range(3)]
        self.pos += 3
        
        # Subtract 32 from each byte (reverse the +32 encoding)
        val = [b - 32 for b in val]
        
        # Reconstruct the value: (val[0] << 14) + (val[1] << 7) + val[2]
        return (val[0] << 14) + (val[1] << 7) + val[2]


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
        self.handlers[ServerToPlayer.PLO_RAWDATA] = self._handle_rawdata
        self.handlers[ServerToPlayer.PLO_BOARDPACKET] = self._handle_board_packet
        print(f"🔧 Registered board packet handler for ID {ServerToPlayer.PLO_BOARDPACKET}")  # Debug
        self.handlers[ServerToPlayer.PLO_PLAYERWARP] = self._handle_player_warp
        self.handlers[ServerToPlayer.PLO_DISCMESSAGE] = self._handle_disconnect_message
        self.handlers[ServerToPlayer.PLO_TOALL] = self._handle_toall
        self.handlers[ServerToPlayer.PLO_PRIVATEMESSAGE] = self._handle_private_message
        self.handlers[ServerToPlayer.PLO_ADDPLAYER] = self._handle_add_player
        self.handlers[ServerToPlayer.PLO_DELPLAYER] = self._handle_del_player
        self.handlers[ServerToPlayer.PLO_SIGNATURE] = self._handle_signature
        self.handlers[ServerToPlayer.PLO_SERVERTEXT] = self._handle_server_text
        self.handlers[ServerToPlayer.PLO_WARPFAILED] = self._handle_warp_failed
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
        self.handlers[ServerToPlayer.PLO_SHOWIMG] = self._handle_show_img
        self.handlers[ServerToPlayer.PLO_NPCPROPS] = self._handle_npc_props
        self.handlers[ServerToPlayer.PLO_NPCDEL] = self._handle_npc_del
        self.handlers[ServerToPlayer.PLO_NPCDEL2] = self._handle_npc_del2
        self.handlers[ServerToPlayer.PLO_NPCWEAPONADD] = self._handle_npc_weapon_add
        self.handlers[ServerToPlayer.PLO_NPCWEAPONDEL] = self._handle_npc_weapon_del
        self.handlers[ServerToPlayer.PLO_BADDYPROPS] = self._handle_baddy_props
        self.handlers[ServerToPlayer.PLO_NPCACTION] = self._handle_npc_action
        self.handlers[ServerToPlayer.PLO_CLEARWEAPONS] = self._handle_clear_weapons
        self.handlers[ServerToPlayer.PLO_NC_CLASSADD] = self._handle_nc_classadd
        self.handlers[ServerToPlayer.PLO_FULLSTOP2] = self._handle_fullstop2
        self.handlers[ServerToPlayer.PLO_UNKNOWN198] = self._handle_unknown198
        self.handlers[ServerToPlayer.PLO_NEWWORLDTIME] = self._handle_newworld_time
        self.handlers[ServerToPlayer.PLO_STAFFGUILDS] = self._handle_staff_guilds
        self.handlers[ServerToPlayer.PLO_TRIGGERACTION] = self._handle_trigger_action
        # Unknown packet IDs that appear in logs
        self.handlers[10] = self._handle_unknown_10
        self.handlers[30] = self._handle_unknown_30
        self.handlers[45] = self._handle_file_uptodate
        self.handlers[33] = self._handle_unknown_33
        # self.handlers[34] = PLO_NPCWEAPONDEL - not BOARD data!
        self.handlers[41] = self._handle_unknown_41  # Large HTML packet
        self.handlers[43] = self._handle_unknown_43
        self.handlers[44] = self._handle_unknown_44
        self.handlers[49] = self._handle_unknown_49
        self.handlers[52] = self._handle_unknown_52  # TILESET packet
        self.handlers[179] = self._handle_unknown_179
        self.handlers[180] = self._handle_unknown_180
        self.handlers[190] = self._handle_unknown_190
        self.handlers[197] = self._handle_unknown_197
        self.handlers[65] = self._handle_rc_listrcs  # PLI_RC_LISTRCS
        
        # New GServer-V2 packet handlers
        self.handlers[ServerToPlayer.PLO_GHOSTTEXT] = self._handle_ghost_text
        self.handlers[ServerToPlayer.PLO_GHOSTICON] = self._handle_ghost_icon
        self.handlers[ServerToPlayer.PLO_MINIMAP] = self._handle_minimap
        self.handlers[ServerToPlayer.PLO_SERVERWARP] = self._handle_server_warp
        self.handlers[ServerToPlayer.PLO_FULLSTOP] = self._handle_fullstop
        
        # Note: Board data after 0-byte board packet is handled as raw stream, not packets
        
    
    def handle_packet(self, packet_id: int, data: bytes) -> Optional[Dict[str, Any]]:
        """Handle a single packet"""
        print(f"🔍 PACKET DEBUG: ID={packet_id}, Size={len(data)} bytes")
        
        # Special debug for board packet
        if packet_id == 101:
            print(f"🎯🎯🎯 PLO_BOARDPACKET (101) DETECTED IN HANDLER!")
        
        # Show raw data for debugging (first 50 bytes)
        if len(data) > 0:
            hex_preview = data[:50].hex()
            print(f"   Raw data: {hex_preview}{'...' if len(data) > 50 else ''}")
        
        if packet_id in self.handlers:
            handler_name = self.handlers[packet_id].__name__
            print(f"   ✅ Handler found: {handler_name}")
            
            reader = PacketReader(data)
            try:
                result = self.handlers[packet_id](reader)
                if result:
                    # Handle both dict and string results
                    if isinstance(result, dict):
                        print(f"   📤 Handler result: {result.get('type', 'unknown')}")
                        if result.get('type') == 'board_packet':
                            print(f"   🎯 BOARD PACKET: {len(result.get('board_data', b''))} bytes")
                    else:
                        print(f"   📤 Handler result: {result}")
                return result
            except Exception as e:
                print(f"   ❌ Handler error: {e}")
                import traceback
                traceback.print_exc()
                return None
        else:
            print(f"   ❌ NO HANDLER for packet ID {packet_id}")
            # Try to identify what this packet might be
            if len(data) == 8192:
                print(f"   🎯 UNHANDLED 8192-byte packet - could be board data!")
            elif len(data) > 1000:
                print(f"   📦 Large unhandled packet ({len(data)} bytes)")
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
            elif prop in [PlayerProp.PLPROP_GMAPLEVELX, PlayerProp.PLPROP_GMAPLEVELY]:
                # GMAP segment position (1 byte)
                value = reader.read_byte()
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
    
    def _handle_rawdata(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle PLO_RAWDATA packet - specifies the size of the next packet"""
        print(f"🎯 PLO_RAWDATA packet detected!")
        
        # Read the size as GInt (3 bytes)
        expected_size = reader.read_gint()
        print(f"   📏 Next packet size: {expected_size} bytes")
        
        return {
            "type": "rawdata",
            "expected_size": expected_size
        }
    
    def _handle_board_packet(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle full board data packet"""
        print(f"🎯 BOARD PACKET HANDLER TRIGGERED!")
        print(f"   Data size: {len(reader.data)} bytes")
        print(f"   Position: {reader.pos}")
        print(f"   Remaining: {reader.remaining()}")
        
        # Board packet should be 8192 bytes (64x64 tiles, 2 bytes per tile)
        # But it might be truncated and need continuation packets
        board_data = b''
        remaining = reader.remaining()
        
        if remaining > 0:
            print(f"   📦 Reading {remaining} bytes of board data")
            # Read all available board data
            board_data = reader.data[reader.pos:reader.pos+remaining]
            reader.pos += remaining
            
            # Show first few tile IDs for debugging
            import struct
            first_tiles = []
            for i in range(min(10, len(board_data)//2)):
                if i*2+1 < len(board_data):
                    tile_id = struct.unpack('<H', board_data[i*2:i*2+2])[0]
                    first_tiles.append(tile_id)
            print(f"   First tile IDs: {first_tiles}")
            
            if len(board_data) == 8192:
                print(f"   ✅ Complete board data received")
            else:
                print(f"   ⚠️  Partial board data - expected 8192, got {len(board_data)}")
        else:
            print(f"   ❌ No board data available")
        
        result = {
            "type": "board_packet",
            "board_data": board_data,
            "size": len(board_data),
            "is_complete": len(board_data) == 8192
        }
        print(f"   📤 Returning board packet result: {len(board_data)} bytes")
        return result
    
    def _handle_player_warp(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle player warp"""
        x = reader.read_byte() / 2.0
        y = reader.read_byte() / 2.0
        level = reader.read_gstring()
        return {"type": "player_warp", "x": x, "y": y, "level": level}
    
    def _handle_disconnect_message(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle disconnect message"""
        message = reader.read_gstring()
        print(f"❌ DISCONNECT: {message}")
        return {"type": "disconnect_message", "message": message}
    
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
    
    def _handle_warp_failed(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle warp failed packet"""
        # The packet contains the level name that failed
        level_name = reader.read_gstring()
        print(f"❌ WARP FAILED: Cannot warp to '{level_name}'")
        return {"type": "warp_failed", "level_name": level_name}
    
    def _handle_file(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle file data"""
        import os
        
        # The format appears to be:
        # [compressed length][compressed data that includes part of filename][rest of filename][file data]
        
        # First byte is length of compressed/obfuscated data
        compressed_len = reader.read_byte()
        
        # The compressed data contains obfuscated filename info
        compressed_data = b''
        if compressed_len > 0:
            compressed_data = reader.read_bytes(compressed_len)
            print(f"📁 Compressed data ({compressed_len} bytes): {compressed_data.hex()}")
            # Try to extract readable chars from compressed data
            readable = ''.join(chr(b) if 32 <= b < 127 else '.' for b in compressed_data)
            print(f"   As text: {readable}")
        
        # Now read the actual filename
        # The filename continues after the compressed data
        known_headers = [b'GLEVNW01', b'GRMAP001', b'GLVLNW01', b'GANI0001']
        
        filename = ""
        
        # The last byte of compressed data often contains the first character of the filename
        if compressed_len > 0:
            # The last byte seems to be the first character of the filename
            last_byte = compressed_data[-1]
            if 32 <= last_byte < 127:  # Printable ASCII
                filename = chr(last_byte)
        
        # Continue reading the filename
        while reader.has_more():
            # Check if we're at a known header
            current_pos = reader.pos
            remaining = reader.data[current_pos:]
            
            header_found = False
            for header in known_headers:
                if remaining.startswith(header):
                    header_found = True
                    break
            
            if header_found:
                break
                
            char = reader.read_raw_byte()
            if char == 0:  # Null terminates
                break
            elif 32 <= char < 127:  # Printable ASCII
                filename += chr(char)
            else:
                # Non-printable char might indicate end of filename
                # Put it back and break
                reader.pos -= 1
                break
        
        # Clean up the filename - remove any trailing junk
        filename = filename.rstrip('\r\n\x00')
        
        # The rest is file data
        data = reader.read_remaining()
        
        print(f"📁 File packet: compressed_len={compressed_len}, filename='{filename}', data_size={len(data)}")
        if len(data) > 0:
            print(f"   Data starts with: {data[:min(32, len(data))].hex()}")
            if len(data) > 32:
                print(f"   Data preview: {repr(data[:100])}")
        
        # Save file to downloads directory for inspection
        downloads_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "downloads")
        os.makedirs(downloads_dir, exist_ok=True)
        
        # Clean filename for filesystem
        safe_filename = filename.replace('/', '_').replace('\\', '_')
        file_path = os.path.join(downloads_dir, safe_filename)
        
        try:
            with open(file_path, 'wb') as f:
                f.write(data)
            print(f"💾 Saved file to: {file_path}")
        except Exception as e:
            print(f"⚠️ Failed to save file: {e}")
        
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
        # Chest coordinates are sent as pixel coordinates / 2
        x_raw = reader.read_byte()
        y_raw = reader.read_byte()
        x = x_raw / 2.0
        y = y_raw / 2.0
        item = reader.read_byte()
        sign_text = reader.read_gstring()
        return {"type": "level_chest", "x": x, "y": y, "item": item, "sign_text": sign_text}
    
    def _handle_level_link(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle level link"""
        # Level link format: x, y, width, height, new_x, new_y, level_name
        x = reader.read_byte()
        y = reader.read_byte()
        width = reader.read_byte()
        height = reader.read_byte()
        new_x = reader.read_byte()
        new_y = reader.read_byte()
        
        # The level name follows - appears to be null-terminated or gstring
        level_name = reader.read_gstring()
        
        print(f"🔗 Level link: ({x},{y}) size {width}x{height} -> {level_name} at ({new_x/2},{new_y/2})")
        
        return {
            "type": "level_link", 
            "x": x, "y": y, 
            "width": width, "height": height,
            "new_x": new_x / 2.0, "new_y": new_y / 2.0,
            "level_name": level_name,
            "data": reader.data[reader.pos:]  # Keep raw data for compatibility
        }
    
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
    
    def _handle_npc_weapon_add(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle NPC weapon add"""
        # Format: weapon name (gstring)
        weapon_name = reader.read_gstring()
        return {"type": "npc_weapon_add", "weapon": weapon_name}
    
    def _handle_npc_weapon_del(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle NPC weapon delete"""
        # Format: weapon name (gstring)  
        weapon_name = reader.read_gstring()
        return {"type": "npc_weapon_del", "weapon": weapon_name}
    
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
        # According to Reborn Server source: blank packet sent before weapon list
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
    
    def _handle_newworld_time(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle new world time packet (PLO_NEWWORLDTIME)"""
        # Server clock/time update
        # Format: 4 bytes for time value
        if reader.remaining() >= 4:
            time_value = reader.read_int()
            return {"type": "newworld_time", "time": time_value}
        return {"type": "newworld_time", "raw": reader.data[reader.pos:]}
    
    def _handle_show_img(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle show image packet (PLO_SHOWIMG)"""
        # Display image on screen
        # Format varies - could be image name, position, etc.
        return {"type": "show_img", "data": reader.data[reader.pos:]}
    
    def _handle_staff_guilds(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle staff guilds packet (PLO_STAFFGUILDS)"""
        # List of staff guilds - read as gstring (null-terminated)
        guilds_str = reader.read_gstring()
        guilds = guilds_str.split(",") if guilds_str else []
        return {"type": "staff_guilds", "guilds": guilds}
    
    def _handle_trigger_action(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle trigger action packet (PLO_TRIGGERACTION)"""
        # Trigger action from server/NPC
        # Format: action_name,param1,param2,...
        data = reader.read_gstring()
        
        # Parse action and parameters
        parts = data.split(',') if data else []
        action = parts[0] if parts else ""
        params = parts[1:] if len(parts) > 1 else []
        
        return {
            "type": "trigger_action", 
            "action": action,
            "params": params,
            "raw": data
        }
    
    def _handle_rc_listrcs(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle RC list RCs packet (PLI_RC_LISTRCS)"""
        # Deprecated RC command to list connected RC clients
        return {"type": "rc_listrcs"}
    
    def _handle_npc_action(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle NPC action packet (PLO_NPCACTION)"""
        # Format varies, usually contains NPC ID and action data
        return {"type": "npc_action", "data": reader.data[reader.pos:]}
    
    def _handle_ghost_text(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle ghost text packet (PLO_GHOSTTEXT)"""
        # Shows static text in lower-right corner of screen only when in ghost mode
        text = reader.read_gstring()
        return {"type": "ghost_text", "text": text}
    
    def _handle_ghost_icon(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle ghost icon packet (PLO_GHOSTICON)"""
        # Pass 1 to enable the ghost icon
        enabled = reader.read_byte() == 1 if reader.has_more() else False
        return {"type": "ghost_icon", "enabled": enabled}
    
    def _handle_minimap(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle minimap packet (PLO_MINIMAP)"""
        # Format: [172] minimap.txt,minimapimage.png,10,10
        data = reader.read_gstring()
        parts = data.split(',')
        result = {"type": "minimap", "raw": data}
        
        if len(parts) >= 4:
            result.update({
                "text_file": parts[0],
                "image_file": parts[1],
                "x": int(parts[2]) if parts[2].isdigit() else 0,
                "y": int(parts[3]) if parts[3].isdigit() else 0
            })
        
        return result
    
    def _handle_server_warp(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle server warp packet (PLO_SERVERWARP)"""
        # Server-initiated warp to another server
        # Format appears to be server info for connection
        data = reader.data[reader.pos:]
        return {"type": "server_warp", "data": data}
    
    def _handle_fullstop(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle fullstop packet (PLO_FULLSTOP)"""
        # Sending this causes the entire client to not respond to normal input and hides the HUD
        return {"type": "fullstop"}
    
    def _handle_unknown_10(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle unknown packet 10"""
        return {"type": "unknown_10", "data": reader.read_remaining()}
    
    def _handle_unknown_30(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle PLO_FILESENDFAILED (30) - File send failed"""
        filename = reader.read_gstring()
        print(f"❌ PLO_FILESENDFAILED: Failed to send file '{filename}'")
        return {"type": "file_send_failed", "filename": filename}
    
    def _handle_file_uptodate(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle PLO_FILEUPTODATE (45) - File is already up to date"""
        filename = reader.read_gstring()
        print(f"✓ PLO_FILEUPTODATE: File '{filename}' is already up to date")
        return {"type": "file_uptodate", "filename": filename}
    
    def _handle_unknown_33(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle unknown packet 33 - appears to be weapon/image related"""
        data = reader.read_gstring()
        return {"type": "unknown_33", "data": data}
    
    
    def _handle_unknown_41(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle unknown packet 41 - appears to be HTML content"""
        html_content = reader.read_gstring()
        return {"type": "unknown_41", "html": html_content}
    
    def _handle_unknown_43(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle unknown packet 43"""
        return {"type": "unknown_43", "data": reader.read_remaining()}
    
    def _handle_unknown_44(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle unknown packet 44"""
        return {"type": "unknown_44", "data": reader.read_remaining()}
    
    def _handle_unknown_49(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle unknown packet 49 - appears to be level/gmap related"""
        data = reader.read_gstring()
        return {"type": "unknown_49", "data": data}
    
    def _handle_unknown_52(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle unknown packet 52 - TILESET command"""
        tileset = reader.read_gstring()
        return {"type": "tileset", "tileset": tileset}
    
    def _handle_unknown_179(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle unknown packet 179"""
        data = reader.read_gstring()
        return {"type": "unknown_179", "data": data}
    
    def _handle_unknown_180(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle unknown packet 180"""
        data = reader.read_gstring()
        return {"type": "unknown_180", "data": data}
    
    def _handle_unknown_190(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle unknown packet 190"""
        return {"type": "unknown_190", "data": reader.read_remaining()}
    
    def _handle_unknown_197(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle unknown packet 197 - appears to be weapon/class data"""
        data = reader.read_gstring()
        return {"type": "unknown_197", "data": data}