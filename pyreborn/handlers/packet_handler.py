"""
Packet parsing and handling
"""

import struct
import logging
from typing import Dict, Callable, Optional, Tuple, Any
from ..protocol.enums import ServerToPlayer, PlayerProp
from ..models.player import Player
from ..models.level import Level, Sign, Chest, LevelLink
from .initial_props_parser import parse_initial_login_props

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
        """Read 2-byte value in BIG-ENDIAN order (correct for Graal protocol)"""
        high = self.read_byte()
        low = self.read_byte()
        return (high << 8) | low
    
    def read_gshort(self) -> int:
        """Read Graal-encoded short (2 bytes)
        
        Graal uses a special encoding where each byte has 32 added,
        and the value is split into 7-bit chunks.
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
        """Read newline-terminated string (plain text, not encoded)"""
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
    
    def peek_raw_byte(self) -> int:
        """Peek at next raw byte without advancing or decoding"""
        if self.pos >= len(self.data):
            return 0
        return self.data[self.pos]
    
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
    
    def read_gint5(self) -> int:
        """Read GInt5 (5-byte Graal integer) with +32 encoding"""
        if self.pos + 5 > len(self.data):
            return 0
        
        # Read 5 raw bytes
        bytes_val = [self.data[self.pos + i] for i in range(5)]
        self.pos += 5
        
        # Subtract 32 from each byte
        bytes_val = [(b - 32) & 0x7F for b in bytes_val]
        
        # Reconstruct as big-endian style
        # Each byte contributes 7 bits: byte0 is most significant
        result = 0
        for i in range(5):
            result = (result << 7) | bytes_val[i]
        
        return result


class PacketHandler:
    """Handles incoming packets from server"""
    
    def __init__(self, client=None):
        self.client = client
        self.handlers = {}
        from ..utils.logging_config import ModuleLogger
        self.logger = ModuleLogger.get_logger(__name__)
        self._register_handlers()
        
    def _register_handlers(self):
        """Register packet handlers"""
        self.handlers[ServerToPlayer.PLO_PLAYERPROPS] = self._handle_player_props
        self.handlers[ServerToPlayer.PLO_OTHERPLPROPS] = self._handle_other_player_props
        self.handlers[ServerToPlayer.PLO_LEVELNAME] = self._handle_level_name
        self.handlers[ServerToPlayer.PLO_BOARDMODIFY] = self._handle_board_modify
        self.handlers[ServerToPlayer.PLO_RAWDATA] = self._handle_rawdata
        self.handlers[ServerToPlayer.PLO_BOARDPACKET] = self._handle_board_packet
        self.logger.debug(f"Registered board packet handler for ID {ServerToPlayer.PLO_BOARDPACKET}")
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
        # Improved handlers using structure-aware parsing
        self.handlers[10] = self._handle_is_leader
        self.handlers[30] = self._handle_unknown_30
        self.handlers[45] = self._handle_file_uptodate
        self.handlers[33] = self._handle_npc_weapon_add_improved  # Use structure parsing
        self.handlers[39] = self._handle_level_mod_time  # New handler
        self.handlers[41] = self._handle_start_message   # HTML start message
        self.handlers[43] = self._handle_unknown_43
        self.handlers[44] = self._handle_unknown_44
        self.handlers[49] = self._handle_player_warp2    # GMAP warp handler
        self.handlers[52] = self._handle_unknown_52      # TILESET packet
        self.handlers[156] = self._handle_set_active_level  # New handler
        self.handlers[174] = self._handle_ghost_icon     # Already exists
        self.handlers[179] = self._handle_rpg_window     # Improved handler
        self.handlers[180] = self._handle_unknown_180
        self.handlers[190] = self._handle_unknown_190
        self.handlers[197] = self._handle_unknown_197
        self.handlers[65] = self._handle_rc_listrcs  # PLI_RC_LISTRCS
        
        # Large file transfer handlers
        self.handlers[68] = self._handle_large_file_start  # PLO_LARGEFILESTART
        self.handlers[69] = self._handle_large_file_end    # PLO_LARGEFILEEND
        self.handlers[84] = self._handle_large_file_size   # PLO_LARGEFILESIZE
        
        # New GServer-V2 packet handlers
        self.handlers[ServerToPlayer.PLO_GHOSTTEXT] = self._handle_ghost_text
        self.handlers[ServerToPlayer.PLO_GHOSTICON] = self._handle_ghost_icon
        self.handlers[ServerToPlayer.PLO_MINIMAP] = self._handle_minimap
        self.handlers[ServerToPlayer.PLO_SERVERWARP] = self._handle_server_warp
        self.handlers[ServerToPlayer.PLO_FULLSTOP] = self._handle_fullstop
        
        # Note: Board data after 0-byte board packet is handled as raw stream, not packets
        
    
    def handle_packet(self, packet_id: int, data: bytes) -> Optional[Dict[str, Any]]:
        """Handle a single packet"""
        self.logger.debug(f"PACKET DEBUG: ID={packet_id}, Size={len(data)} bytes")
        
        # Special debug for board packet
        if packet_id == 101:
            self.logger.debug("PLO_BOARDPACKET (101) DETECTED IN HANDLER!")
        
        # Show raw data for debugging (first 50 bytes)
        if len(data) > 0:
            hex_preview = data[:50].hex()
            self.logger.debug(f"Raw data: {hex_preview}{'...' if len(data) > 50 else ''}")
        
        if packet_id in self.handlers:
            handler_name = self.handlers[packet_id].__name__
            self.logger.debug(f"Handler found: {handler_name}")
            
            reader = PacketReader(data)
            try:
                result = self.handlers[packet_id](reader)
                if result:
                    # Handle both dict and string results
                    if isinstance(result, dict):
                        self.logger.debug(f"Handler result: {result.get('type', 'unknown')}")
                        if result.get('type') == 'board_packet':
                            self.logger.debug(f"BOARD PACKET: {len(result.get('board_data', b''))} bytes")
                    else:
                        self.logger.debug(f"Handler result: {result}")
                return result
            except Exception as e:
                self.logger.error(f"Handler error: {e}", exc_info=True)
                return None
        else:
            self.logger.debug(f"NO HANDLER for packet ID {packet_id}")
            # Attempt to identify this unknown packet type
            if len(data) == 8192:
                self.logger.debug("UNHANDLED 8192-byte packet - could be board data!")
            elif len(data) > 1000:
                self.logger.debug(f"Large unhandled packet ({len(data)} bytes)")
            return None
    
    def _handle_player_props(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle player properties update"""
        # Check if this is the initial login properties blob (large packet)
        initial_remaining = reader.remaining()
        is_initial_blob = initial_remaining > 150
        
        self.logger.info(f"[PLAYER_PROPS] Processing packet: {initial_remaining} bytes, is_initial_blob={is_initial_blob}")
        
        # Add raw packet dump for debugging
        raw_bytes = reader.data[reader.pos:reader.pos + min(50, reader.remaining())]
        self.logger.info(f"[RAW_PACKET] First 50 bytes: {raw_bytes}")
        
        if is_initial_blob:
            # Initial blob uses +32 offset encoding
            return self._handle_initial_login_props(reader)
        
        # PLO_PLAYERPROPS (our player) has NO player ID prefix
        # Only PLO_OTHERPLPROPS has a player ID prefix
        player_id = -1  # Our own player
        props = {}
        
        # Process properties until end of packet
        prop_count = 0
        while reader.has_more():
            prop_id = reader.read_byte()
            if prop_id == ord('\n') - 32:  # End of packet
                break
            
            prop_count += 1
            start_pos = reader.pos - 1  # Account for the prop_id we just read
            self.logger.info(f"[PROP {prop_count}] Raw prop_id={prop_id}, pos={start_pos}, remaining={reader.remaining()}")
            
            if is_initial_blob:
                self.logger.debug(f"[BLOB PROP {prop_count}] ID={prop_id}, remaining={reader.remaining()}")
                
            # Try to get property enum, handle unknown properties
            try:
                prop = PlayerProp(prop_id)
                self.logger.info(f"[PROP {prop_count}] Recognized as {prop.name}")
            except ValueError:
                self.logger.warning(f"[PROP {prop_count}] UNKNOWN property ID {prop_id}")
                # Unknown property - be more careful with parsing to avoid corruption
                if reader.has_more():
                    peek_byte = reader.peek_byte()
                    self.logger.info(f"[PROP {prop_count}] Next byte peek: {peek_byte}")
                    
                    # If peek byte looks like a reasonable string length AND we have enough data
                    if 0 < peek_byte < 100 and reader.remaining() >= peek_byte + 1:
                        length = reader.read_byte()
                        self.logger.info(f"[PROP {prop_count}] Treating as string with length: {length}")
                        if reader.remaining() >= length:
                            skipped_data = reader.read_string(length)
                            self.logger.info(f"[PROP {prop_count}] Skipped string: '{skipped_data}'")
                        else:
                            self.logger.error(f"[PROP {prop_count}] Not enough data for string length {length}, remaining: {reader.remaining()}")
                            # Skip rest of packet to avoid corruption
                            break
                        continue
                    
                # Property ID 127 and other high values are typically single-byte flags
                if prop_id >= 120:
                    self.logger.info(f"[PROP {prop_count}] Treating high prop_id {prop_id} as single-byte flag")
                    # Skip this property as it's a flag without data
                    continue
                    
                # Default to single byte property for unknown IDs
                if reader.has_more():
                    skipped_byte = reader.read_byte()
                    self.logger.info(f"[PROP {prop_count}] Skipped single byte: {skipped_byte}")
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
            elif prop == PlayerProp.PLPROP_SHIELDPOWER:
                # Shield power similar to sword: [length][power+30][image]
                length = reader.read_byte()
                if length > 0 and reader.remaining() >= length:
                    shield_id = reader.read_byte() - 30
                    shield_image = reader.read_string(length - 1) if length > 1 else ""
                    value = (shield_id, shield_image)
                else:
                    value = (0, "")
            elif PlayerProp.PLPROP_GATTRIB1 <= prop <= PlayerProp.PLPROP_GATTRIB30:
                # GATTRIB properties are flags - no data to read
                value = True
                if is_initial_blob:
                    self.logger.debug(f"[BLOB PROP {prop_count}] GATTRIB flag {prop.name} - no data")
            # Note: PLATTRIB properties (42-46) were removed - they don't exist in the protocol
            elif prop in [PlayerProp.PLPROP_NICKNAME, PlayerProp.PLPROP_CURCHAT, 
                         PlayerProp.PLPROP_GANI, PlayerProp.PLPROP_BODYIMG,
                         PlayerProp.PLPROP_HORSEGIF, PlayerProp.PLPROP_ACCOUNTNAME,
                         PlayerProp.PLPROP_CURLEVEL, PlayerProp.PLPROP_COMMUNITYNAME]:
                # String properties with length prefix
                value = reader.read_string_with_length()
                if is_initial_blob:
                    self.logger.debug(f"[BLOB PROP {prop_count}] String property {prop.name}='{value}'")
            elif prop in [PlayerProp.PLPROP_X2, PlayerProp.PLPROP_Y2, PlayerProp.PLPROP_Z2]:
                # High precision coordinates (2 bytes)
                value = reader.read_short()
            elif prop in [PlayerProp.PLPROP_GMAPLEVELX, PlayerProp.PLPROP_GMAPLEVELY]:
                # GMAP segment position (1 byte)
                value = reader.read_byte()
            elif prop == PlayerProp.PLPROP_DEATHSCOUNT:
                # Property 28 can contain packed player data on some servers
                # Check if it has a length prefix
                if reader.has_more():
                    peek_byte = reader.peek_byte()
                    if 0 <= peek_byte < 223:  # Looks like a string length
                        length = reader.read_byte()
                        if reader.remaining() >= length:
                            data = reader.read_bytes(length)
                            self.logger.info(f"PLPROP_DEATHSCOUNT (28) contains {length} bytes of data: {data[:50]}...")
                            self.logger.info(f"As string: {data.decode('latin-1', errors='replace')[:50]}...")
                            # For now, skip processing this data
                            value = 0  # Default deaths count
                        else:
                            value = reader.read_byte()
                    else:
                        value = reader.read_byte()
                else:
                    value = reader.read_byte()
            else:
                # All other properties are single byte
                value = reader.read_byte()
                if is_initial_blob:
                    self.logger.debug(f"[BLOB PROP {prop_count}] Single byte property {prop.name}={value}")
            
            props[prop] = value
            end_pos = reader.pos
            bytes_consumed = end_pos - start_pos
            self.logger.info(f"[PROP {prop_count}] Parsed {prop.name}={value}, consumed {bytes_consumed} bytes, now at pos {end_pos}")
            
            if is_initial_blob:
                self.logger.debug(f"[BLOB PROP {prop_count}] Parsed {prop.name}={value}")
        
        # Log ALL properties for debugging
        self.logger.info(f"[PLAYER_PROPS] COMPLETE DUMP - {len(props)} properties:")
        for prop, value in props.items():
            if hasattr(prop, 'name'):
                prop_name = prop.name
            else:
                prop_name = f"UNKNOWN_{prop}"
            self.logger.info(f"  {prop_name} = {value} (type: {type(value)})")
        
        # Log important coordinate properties for debugging
        if PlayerProp.PLPROP_X in props:
            self.logger.warning(f"*** Player local X: {props[PlayerProp.PLPROP_X]} ***")
        if PlayerProp.PLPROP_Y in props:
            self.logger.warning(f"*** Player local Y: {props[PlayerProp.PLPROP_Y]} ***")
        if PlayerProp.PLPROP_X2 in props:
            self.logger.warning(f"*** Player world X2: {props[PlayerProp.PLPROP_X2]} ***")
        if PlayerProp.PLPROP_Y2 in props:
            self.logger.warning(f"*** Player world Y2: {props[PlayerProp.PLPROP_Y2]} ***")
        if PlayerProp.PLPROP_GMAPLEVELX in props:
            self.logger.info(f"GMAP level X: {props[PlayerProp.PLPROP_GMAPLEVELX]}")
        if PlayerProp.PLPROP_GMAPLEVELY in props:
            self.logger.info(f"GMAP level Y: {props[PlayerProp.PLPROP_GMAPLEVELY]}")
            
        # Log if we have many properties (initial load)
        if len(props) > 10:
            self.logger.info(f"[INITIAL PROPS] Received {len(props)} properties: {list(props.keys())}")
        
        return {"type": "player_props", "player_id": player_id, "props": props}
    
    def _handle_initial_login_props(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle initial login properties with +32 offset encoding"""
        player_id = 1  # Our player is always ID 1 for initial props
        
        self.logger.info(f"[INITIAL LOGIN PROPS] Processing {reader.remaining()} bytes with +32 offset encoding")
        
        # Get the raw data for specialized parsing
        raw_data = reader.data[reader.pos:]
        
        # Use the comprehensive parser
        props = parse_initial_login_props(raw_data)
        
        # Mark the reader as consumed
        reader.pos = len(reader.data)
        
        self.logger.info(f"[INITIAL LOGIN PROPS] Extracted {len(props)} properties")
        
        # Log ALL initial properties for debugging
        self.logger.info(f"[INITIAL_LOGIN_PROPS] COMPLETE DUMP - {len(props)} properties:")
        for prop, value in props.items():
            if hasattr(prop, 'name'):
                prop_name = prop.name
            else:
                prop_name = f"UNKNOWN_{prop}"
            self.logger.info(f"  {prop_name} = {value} (type: {type(value)})")
        
        return {"type": "player_props", "player_id": player_id, "props": props}
    
    def _handle_other_player_props(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle other player properties
        
        OTHER_PLAYER_PROPS uses a different format than regular player props:
        - Player ID (Graal-encoded short)
        - Property ID (1 byte) 
        - Serialized property data (varies by property type)
        """
        # Read player ID as Graal-encoded short
        # Testing shows the server sends player IDs as Graal shorts in OTHER_PLAYER_PROPS
        player_id = reader.read_gshort()
        self.logger.debug(f"[OTHER_PLAYER_PROPS] Player ID: {player_id}, remaining bytes: {reader.remaining()}")
        
        props = {}
        prop_count = 0
        
        # Parse properties until we run out of data
        # Track consecutive unknown properties as a sign we've gone too far
        consecutive_unknown = 0
        
        while reader.remaining() > 0:
            prop_count += 1
            start_pos = reader.pos
            
            # Read property ID
            if reader.remaining() < 1:
                self.logger.debug(f"[OTHER_PLAYER_PROPS] Not enough data for property ID")
                break
                
            prop_id = reader.read_byte()
            self.logger.debug(f"[OTHER_PLAYER_PROPS] Prop {prop_count}: ID={prop_id}")
            
            # Map to PlayerProp enum
            try:
                prop = PlayerProp(prop_id)
                prop_name = prop.name
                consecutive_unknown = 0  # Reset counter on valid property
            except ValueError:
                prop = None
                prop_name = f"UNKNOWN_{prop_id}"
                consecutive_unknown += 1
                self.logger.debug(f"[OTHER_PLAYER_PROPS] Unknown property ID: {prop_id}")
                
                # If we see property ID 0 (NICKNAME) after we already have a nickname,
                # or if we see too many unknown properties, we've likely gone too far
                if prop_id == 0 and PlayerProp.PLPROP_NICKNAME in props:
                    self.logger.warning(f"[OTHER_PLAYER_PROPS] Duplicate NICKNAME property - stopping parse")
                    # Reset reader position to before this property
                    reader.pos = start_pos
                    break
                
                if consecutive_unknown >= 2:
                    self.logger.warning(f"[OTHER_PLAYER_PROPS] Too many unknown properties - stopping parse")
                    # Reset reader position to before the first unknown property
                    reader.pos = start_pos - consecutive_unknown + 1
                    break
            
            # Parse property value based on type
            value = None
            
            # Handle X2/Y2 properties (2 bytes, with bit-shift encoding)
            if prop in [PlayerProp.PLPROP_X2, PlayerProp.PLPROP_Y2]:
                if reader.remaining() >= 2:
                    # Server encodes as: (abs(pixels) << 1) | (negative ? 1 : 0)
                    # Then sends with writeGShort
                    
                    # Read as unsigned Graal short
                    b1 = reader.read_raw_byte() - 32
                    b2 = reader.read_raw_byte() - 32
                    encoded = (b1 << 7) + b2
                    
                    # Apply bit-shift decoding
                    pixels = encoded >> 1
                    if encoded & 0x0001:
                        pixels = -pixels
                    value = pixels
                    
                    self.logger.debug(f"[OTHER_PLAYER_PROPS] {prop_name}: encoded={encoded}, pixels={value}")
                else:
                    self.logger.debug(f"[OTHER_PLAYER_PROPS] Not enough data for {prop_name}")
                    break
            
            # Handle Z2 property (similar but no bit-shift)
            elif prop == PlayerProp.PLPROP_Z2:
                if reader.remaining() >= 2:
                    value = reader.read_gshort()
                    self.logger.debug(f"[OTHER_PLAYER_PROPS] Z2: {value} pixels")
                else:
                    self.logger.debug(f"[OTHER_PLAYER_PROPS] Not enough data for Z2")
                    break
            
            # Handle string properties and GATTRIB (length-prefixed)
            elif prop in [PlayerProp.PLPROP_NICKNAME, PlayerProp.PLPROP_ACCOUNTNAME, 
                         PlayerProp.PLPROP_BODYIMG, PlayerProp.PLPROP_CURLEVEL,
                         PlayerProp.PLPROP_CURCHAT, PlayerProp.PLPROP_COMMUNITYNAME,
                         PlayerProp.PLPROP_HORSEGIF, PlayerProp.PLPROP_PSTATUSMSG] or \
                 (prop and hasattr(prop, 'name') and 'GATTRIB' in prop.name):
                if reader.remaining() >= 1:
                    str_len = reader.read_raw_byte() - 32
                    if str_len >= 0 and reader.remaining() >= str_len:
                        value = reader.read_string(str_len)
                        self.logger.debug(f"[OTHER_PLAYER_PROPS] String {prop_name}: '{value}'")
                    else:
                        self.logger.debug(f"[OTHER_PLAYER_PROPS] Not enough data for string {prop_name}")
                        break
                else:
                    self.logger.debug(f"[OTHER_PLAYER_PROPS] Not enough data for string length {prop_name}")
                    break
            
            # Handle HEADGIF property (can be preset or custom)
            elif prop == PlayerProp.PLPROP_HEADGIF:
                if reader.remaining() >= 1:
                    # First decode the Graal-encoded length byte
                    decoded_len = reader.read_byte()  # This subtracts 32
                    if decoded_len < 100:
                        # Preset head (decoded value < 100)
                        value = decoded_len
                        self.logger.debug(f"[OTHER_PLAYER_PROPS] Head preset: {value}")
                    else:
                        # Custom head image (length = decoded_byte - 100)
                        str_len = decoded_len - 100
                        if str_len > 0 and reader.remaining() >= str_len:
                            value = reader.read_string(str_len)
                            self.logger.debug(f"[OTHER_PLAYER_PROPS] Head image: '{value}'")
                        else:
                            self.logger.debug(f"[OTHER_PLAYER_PROPS] Not enough data for head image (len={str_len})")
                            break
                else:
                    self.logger.debug(f"[OTHER_PLAYER_PROPS] Not enough data for HEADGIF")
                    break
            
            # Handle SWORDPOWER property
            elif prop == PlayerProp.PLPROP_SWORDPOWER:
                if reader.remaining() >= 1:
                    first_byte = reader.read_byte()  # Read with -32
                    
                    if first_byte == 0:
                        # No sword
                        value = (0, "")
                        self.logger.debug(f"[OTHER_PLAYER_PROPS] No sword")
                    elif first_byte >= 1 and first_byte <= 4:
                        # Just power, no image (for sword1-4)
                        value = (first_byte, "")
                        self.logger.debug(f"[OTHER_PLAYER_PROPS] Sword power only: {first_byte}")
                    else:
                        # Has custom sword image
                        # The byte is the string length
                        str_len = first_byte
                        if str_len > 0 and reader.remaining() >= 1:
                            # First byte of string is the power + 30
                            power_encoded = reader.read_byte()  # Sword power encoded as power + 30
                            power = power_encoded - 30
                            if reader.remaining() >= str_len - 1:
                                image = reader.read_string(str_len - 1)
                                value = (power, image)
                                self.logger.debug(f"[OTHER_PLAYER_PROPS] Sword: power={power}, image='{image}'")
                            else:
                                self.logger.debug(f"[OTHER_PLAYER_PROPS] Not enough data for sword image")
                                break
                        else:
                            self.logger.debug(f"[OTHER_PLAYER_PROPS] Missing sword image length")
                            break
                else:
                    self.logger.debug(f"[OTHER_PLAYER_PROPS] Not enough data for SWORDPOWER")
                    break
            
            # Handle SHIELDPOWER property
            elif prop == PlayerProp.PLPROP_SHIELDPOWER:
                if reader.remaining() >= 1:
                    first_byte = reader.read_byte()  # Read with -32
                    
                    if first_byte == 0:
                        # No shield
                        value = (0, "")
                        self.logger.debug(f"[OTHER_PLAYER_PROPS] No shield")
                    elif first_byte >= 1 and first_byte <= 3:
                        # Just power, no image (for shield1-3)
                        value = (first_byte, "")
                        self.logger.debug(f"[OTHER_PLAYER_PROPS] Shield power only: {first_byte}")
                    else:
                        # Has custom shield image
                        # The byte is the string length
                        str_len = first_byte
                        if str_len > 0 and reader.remaining() >= 1:
                            # First byte of string is the power + 30
                            power_encoded = reader.read_byte()  # Shield power encoded as power + 30
                            power = power_encoded - 30
                            if reader.remaining() >= str_len - 1:
                                image = reader.read_string(str_len - 1)
                                value = (power, image)
                                self.logger.debug(f"[OTHER_PLAYER_PROPS] Shield: power={power}, image='{image}'")
                            else:
                                self.logger.debug(f"[OTHER_PLAYER_PROPS] Not enough data for shield image")
                                break
                        else:
                            self.logger.debug(f"[OTHER_PLAYER_PROPS] Invalid shield data")
                            break
                else:
                    self.logger.debug(f"[OTHER_PLAYER_PROPS] Not enough data for SHIELDPOWER")
                    break
            
            # Handle GANI property (version-dependent)
            elif prop == PlayerProp.PLPROP_GANI:
                # For now, treat as regular string (v2+ behavior)
                if reader.remaining() >= 1:
                    str_len = reader.read_raw_byte() - 32
                    if str_len >= 0 and reader.remaining() >= str_len:
                        value = reader.read_string(str_len)
                        self.logger.debug(f"[OTHER_PLAYER_PROPS] GANI: '{value}'")
                    else:
                        self.logger.debug(f"[OTHER_PLAYER_PROPS] Not enough data for GANI")
                        break
                else:
                    self.logger.debug(f"[OTHER_PLAYER_PROPS] Not enough data for GANI length")
                    break
            
            # Handle X/Y properties (single byte / 2)
            elif prop in [PlayerProp.PLPROP_X, PlayerProp.PLPROP_Y]:
                if reader.remaining() >= 1:
                    value = reader.read_byte() / 2.0
                    self.logger.debug(f"[OTHER_PLAYER_PROPS] Position {prop_name}: {value}")
                else:
                    self.logger.debug(f"[OTHER_PLAYER_PROPS] Not enough data for position {prop_name}")
                    break
            
            # Handle Z property (has +25 offset)
            elif prop == PlayerProp.PLPROP_Z:
                if reader.remaining() >= 1:
                    raw_z = reader.read_byte()
                    value = (raw_z - 25) / 2.0  # Subtract 25 offset, then divide by 2
                    self.logger.debug(f"[OTHER_PLAYER_PROPS] Z: raw={raw_z}, value={value}")
                else:
                    self.logger.debug(f"[OTHER_PLAYER_PROPS] Not enough data for Z")
                    break
            
            # Handle COLORS property (5 bytes)
            elif prop == PlayerProp.PLPROP_COLORS:
                if reader.remaining() >= 5:
                    colors = [reader.read_byte() for _ in range(5)]
                    value = colors
                    self.logger.debug(f"[OTHER_PLAYER_PROPS] Colors: {colors}")
                else:
                    self.logger.debug(f"[OTHER_PLAYER_PROPS] Not enough data for colors")
                    break
            
            # Handle SPRITE property
            elif prop == PlayerProp.PLPROP_SPRITE:
                if reader.remaining() >= 1:
                    sprite_value = reader.read_byte()
                    # SPRITE is just the sprite ID, not encoded with direction
                    value = sprite_value
                    self.logger.debug(f"[OTHER_PLAYER_PROPS] Sprite: {sprite_value}")
                else:
                    self.logger.debug(f"[OTHER_PLAYER_PROPS] Not enough data for SPRITE")
                    break
            
            # Handle 3-byte properties (CARRYNPC, UDPPORT)
            elif prop in [PlayerProp.PLPROP_CARRYNPC, PlayerProp.PLPROP_UDPPORT]:
                if reader.remaining() >= 3:
                    value = reader.read_gint()
                    self.logger.debug(f"[OTHER_PLAYER_PROPS] GINT3 {prop_name}: {value}")
                else:
                    self.logger.debug(f"[OTHER_PLAYER_PROPS] Not enough data for GINT3 {prop_name}")
                    break
            
            # Handle 5-byte property (IPADDR)
            elif prop == PlayerProp.PLPROP_IPADDR:
                if reader.remaining() >= 5:
                    value = reader.read_gint5()
                    self.logger.debug(f"[OTHER_PLAYER_PROPS] IPADDR: {value}")
                else:
                    self.logger.debug(f"[OTHER_PLAYER_PROPS] Not enough data for IPADDR")
                    break
            
            # Handle RATING property (two floats)
            elif prop == PlayerProp.PLPROP_RATING:
                if reader.remaining() >= 8:
                    import struct
                    # Read 8 bytes for two floats
                    float_data = reader.read_bytes(8)
                    rating, deviation = struct.unpack('<ff', float_data)
                    value = (rating, deviation)
                    self.logger.debug(f"[OTHER_PLAYER_PROPS] Rating: {rating}, Deviation: {deviation}")
                else:
                    self.logger.debug(f"[OTHER_PLAYER_PROPS] Not enough data for RATING")
                    break
            
            # Handle byte properties (most common)
            else:
                if reader.remaining() >= 1:
                    value = reader.read_byte()
                    self.logger.debug(f"[OTHER_PLAYER_PROPS] Byte {prop_name}: {value}")
                    # Special logging for GMAP properties
                    if prop in [PlayerProp.PLPROP_GMAPLEVELX, PlayerProp.PLPROP_GMAPLEVELY]:
                        self.logger.info(f"[OTHER_PLAYER_PROPS] GMAP property {prop_name} = {value}")
                else:
                    self.logger.debug(f"[OTHER_PLAYER_PROPS] Not enough data for byte {prop_name}")
                    break
            
            # Store the property if we have a valid enum
            if prop and value is not None:
                # Validate suspicious values that indicate parsing errors
                if prop == PlayerProp.PLPROP_CARRYSPRITE and value > 100:
                    self.logger.warning(f"[OTHER_PLAYER_PROPS] Suspicious CARRYSPRITE value: {value} - likely parsing error")
                    # Stop parsing - we've gone too far
                    reader.pos = start_pos
                    break
                    
                props[prop] = value
            
            bytes_consumed = reader.pos - start_pos
            self.logger.debug(f"[OTHER_PLAYER_PROPS] Prop {prop_count} consumed {bytes_consumed} bytes")
            
            # Safety check to avoid infinite loops
            if bytes_consumed == 0:
                self.logger.warning(f"[OTHER_PLAYER_PROPS] Consumed 0 bytes for prop {prop_name}, breaking")
                break
        
        self.logger.debug(f"[OTHER_PLAYER_PROPS] Player {player_id} - parsed {len(props)} properties")
        
        # Log coordinate properties specifically
        if PlayerProp.PLPROP_X2 in props:
            self.logger.info(f"[OTHER_PLAYER_PROPS] Player {player_id} X2: {props[PlayerProp.PLPROP_X2]} pixels (= {props[PlayerProp.PLPROP_X2]/16.0:.1f} tiles)")
        if PlayerProp.PLPROP_Y2 in props:
            self.logger.info(f"[OTHER_PLAYER_PROPS] Player {player_id} Y2: {props[PlayerProp.PLPROP_Y2]} pixels (= {props[PlayerProp.PLPROP_Y2]/16.0:.1f} tiles)")
        
        return {"type": "other_player_props", "player_id": player_id, "props": props}
    
    def _handle_level_name(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle level name"""
        # PLO_LEVELNAME reads to end of packet
        # Server sends null-terminated strings in this packet
        remaining = reader.read_remaining()
        if remaining:
            # Find null terminator
            null_pos = remaining.find(b'\x00')
            if null_pos >= 0:
                # Read up to null
                name = remaining[:null_pos].decode('latin-1', errors='replace')
            else:
                # No null, use all data
                name = remaining.decode('latin-1', errors='replace')
            name = name.strip()  # Remove any trailing spaces
        else:
            name = ""
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
        self.logger.debug("PLO_RAWDATA packet detected!")
        
        # Read the size as GInt (3 bytes)
        expected_size = reader.read_gint()
        self.logger.debug(f"Next packet size: {expected_size} bytes")
        
        return {
            "type": "rawdata",
            "expected_size": expected_size
        }
    
    def _handle_board_packet(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle full board data packet"""
        self.logger.debug("BOARD PACKET HANDLER TRIGGERED!")
        self.logger.debug(f"Data size: {len(reader.data)} bytes")
        self.logger.debug(f"Position: {reader.pos}")
        self.logger.debug(f"Remaining: {reader.remaining()}")
        
        # Board packet is 8192 bytes (64x64 tiles, 2 bytes per tile)
        # Handle cases where it's sent in multiple packets
        board_data = b''
        remaining = reader.remaining()
        
        if remaining > 0:
            self.logger.debug(f"Reading {remaining} bytes of board data")
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
            self.logger.debug(f"First tile IDs: {first_tiles}")
            
            if len(board_data) == 8192:
                self.logger.info("Complete board data received")
            else:
                self.logger.warning(f"Partial board data - expected 8192, got {len(board_data)}")
        else:
            self.logger.error("No board data available")
        
        result = {
            "type": "board_packet",
            "board_data": board_data,
            "size": len(board_data),
            "is_complete": len(board_data) == 8192
        }
        self.logger.debug(f"Returning board packet result: {len(board_data)} bytes")
        return result
    
    def _handle_player_warp(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle player warp"""
        x = reader.read_byte() / 2.0
        y = reader.read_byte() / 2.0
        # PLI_LEVELWARP reads to end of packet
        # Server sends null-terminated strings in this packet
        remaining = reader.read_remaining()
        if remaining:
            # Find null terminator
            null_pos = remaining.find(b'\x00')
            if null_pos >= 0:
                # Read up to null
                level = remaining[:null_pos].decode('latin-1', errors='replace')
            else:
                # No null, use all data
                level = remaining.decode('latin-1', errors='replace')
            level = level.strip()  # Remove any trailing spaces
        else:
            level = ""
        return {"type": "player_warp", "x": x, "y": y, "level": level}
    
    def _handle_disconnect_message(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle disconnect message"""
        message = reader.read_gstring()
        self.logger.error(f"DISCONNECT: {message}")
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
        """Handle player addition
        
        ADDPLAYER format:
        - Player ID (Graal-encoded short)
        - Properties (same format as OTHER_PLAYER_PROPS)
        """
        # Read player ID as Graal-encoded short
        player_id = reader.read_gshort()
        self.logger.info(f"[ADDPLAYER] Player ID: {player_id}, remaining bytes: {reader.remaining()}")
        
        # Parse properties same as OTHER_PLAYER_PROPS
        props = {}
        prop_count = 0
        
        while reader.remaining() > 0:
            prop_count += 1
            start_pos = reader.pos
            
            # Read property ID
            prop_id = reader.read_byte()
            
            # Try to identify the property enum
            try:
                prop = PlayerProp(prop_id)
            except ValueError:
                self.logger.warning(f"  [{prop_count}] Unknown property ID: {prop_id}")
                prop = prop_id
            
            self.logger.debug(f"  [{prop_count}] Property {prop} at byte {start_pos}")
            
            # Parse property value based on type
            value = self._parse_player_property(reader, prop_id, is_other_player=True)
            
            if value is not None:
                props[prop] = value
                self.logger.debug(f"    -> Value: {value}")
            else:
                self.logger.warning(f"    -> Failed to parse value")
                break
        
        self.logger.info(f"[ADDPLAYER] Player {player_id}: Parsed {len(props)} properties")
        
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
        self.logger.error(f"WARP FAILED: Cannot warp to '{level_name}'")
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
            self.logger.debug(f"Compressed data ({compressed_len} bytes): {compressed_data.hex()}")
            # Try to extract readable chars from compressed data
            readable = ''.join(chr(b) if 32 <= b < 127 else '.' for b in compressed_data)
            self.logger.debug(f"As text: {readable}")
        
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
                # Non-printable char indicates end of filename
                # Put it back and break
                reader.pos -= 1
                break
        
        # Clean up the filename - remove any trailing junk
        filename = filename.rstrip('\r\n\x00')
        
        # The rest is file data
        data = reader.read_remaining()
        
        self.logger.debug(f"File packet: compressed_len={compressed_len}, filename='{filename}', data_size={len(data)}")
        if len(data) > 0:
            self.logger.debug(f"Data starts with: {data[:min(32, len(data))].hex()}")
            if len(data) > 32:
                self.logger.debug(f"Data preview: {repr(data[:100])}")
        
        # Save file to downloads directory for inspection
        downloads_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "downloads")
        os.makedirs(downloads_dir, exist_ok=True)
        
        # Clean filename for filesystem
        safe_filename = filename.replace('/', '_').replace('\\', '_')
        file_path = os.path.join(downloads_dir, safe_filename)
        
        try:
            with open(file_path, 'wb') as f:
                f.write(data)
            self.logger.info(f"Saved file to: {file_path}")
        except Exception as e:
            self.logger.warning(f"Failed to save file: {e}")
        
        return {"type": "file", "filename": filename, "data": data}
    
    def _handle_large_file_start(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle large file start packet (68)"""
        # Read filename
        filename = reader.read_gstring()
        
        self.logger.info(f"[LARGE FILE] Starting transfer of: {filename}")
        
        # Check if there's additional data indicating file content
        remaining = reader.read_remaining()
        if remaining:
            self.logger.warning(f"[LARGE FILE] START packet has {len(remaining)} bytes of additional data!")
            self.logger.debug(f"Additional data (hex): {remaining[:100].hex()}")
            
            # This is the first chunk of file data
            if self.client and hasattr(self.client, '_raw_data_handler'):
                self.client._raw_data_handler.start_large_file(filename)
                # Add this as the first chunk
                self.client._raw_data_handler.accumulate_file_chunk(filename, remaining)
                self.logger.info(f"[LARGE FILE] Added first chunk from START packet: {len(remaining)} bytes")
        else:
            # Normal case - just notify raw data handler
            if self.client and hasattr(self.client, '_raw_data_handler'):
                self.client._raw_data_handler.start_large_file(filename)
        
        return {"type": "large_file_start", "filename": filename, "initial_bytes": len(remaining) if remaining else 0}
    
    def _handle_large_file_size(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle large file size packet (84)"""
        # Read total file size as GInt5
        total_size = reader.read_gint5()
        
        self.logger.info(f"[LARGE FILE] Total size: {total_size:,} bytes")
        
        # Check for additional data
        remaining = reader.read_remaining()
        if remaining:
            self.logger.warning(f"[LARGE FILE] SIZE packet has {len(remaining)} bytes of additional data!")
            self.logger.debug(f"Additional data (hex): {remaining[:100].hex()}")
            
            # This is more file data for the current transfer
            if self.client and hasattr(self.client, '_raw_data_handler'):
                rdh = self.client._raw_data_handler
                if rdh.file_accumulator:
                    filename = list(rdh.file_accumulator.keys())[-1]
                    rdh.set_large_file_size(filename, total_size)
                    # Add as chunk
                    rdh.accumulate_file_chunk(filename, remaining)
                    self.logger.info(f"[LARGE FILE] Added chunk from SIZE packet: {len(remaining)} bytes")
        else:
            # Normal case
            if self.client and hasattr(self.client, '_raw_data_handler'):
                rdh = self.client._raw_data_handler
                if rdh.file_accumulator:
                    filename = list(rdh.file_accumulator.keys())[-1]
                    rdh.set_large_file_size(filename, total_size)
        
        return {"type": "large_file_size", "size": total_size, "additional_bytes": len(remaining) if remaining else 0}
    
    def _handle_large_file_end(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle large file end packet (69)"""
        # The END packet contains the filename
        remaining_data = reader.read_remaining()
        
        if remaining_data:
            # The remaining data is the filename
            try:
                filename = remaining_data.decode('latin-1')
                self.logger.info(f"[LARGE FILE] END for file: {filename}")
                
                # Mark the file transfer as ended
                if self.client and hasattr(self.client, '_raw_data_handler'):
                    rdh = self.client._raw_data_handler
                    rdh.mark_large_file_ended(filename)
                    
            except Exception as e:
                self.logger.error(f"[LARGE FILE] Failed to decode filename from END packet: {e}")
                # Fallback to marking the last file
                if self.client and hasattr(self.client, '_raw_data_handler'):
                    rdh = self.client._raw_data_handler
                    if rdh.file_accumulator:
                        filename = list(rdh.file_accumulator.keys())[-1]
                        rdh.mark_large_file_ended(filename)
        else:
            self.logger.warning(f"[LARGE FILE] END packet has no filename!")
            # Try to end the last file in accumulator
            if self.client and hasattr(self.client, '_raw_data_handler'):
                rdh = self.client._raw_data_handler
                if rdh.file_accumulator:
                    filename = list(rdh.file_accumulator.keys())[-1]
                    rdh.mark_large_file_ended(filename)
        
        return {"type": "large_file_end"}
    
    def _handle_file_uptodate(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle file up-to-date packet (45)"""
        # This packet indicates the file is already up to date
        self.logger.info("[FILE] File is already up to date")
        return {"type": "file_uptodate"}
    
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
        """Handle level link
        
        Server sends level links in a single gstring with all data
        """
        # Read the entire data as one gstring
        data_str = reader.read_gstring()
        
        self.logger.debug(f"Level link raw data: '{data_str}'")
        
        # Parse the data string - format: "destlevel x y width height destx desty"
        parts = data_str.split()
        if len(parts) >= 7:
            dest_level = parts[0]
            x = int(parts[1])
            y = int(parts[2])
            width = int(parts[3])
            height = int(parts[4])
            dest_x = parts[5]
            dest_y = parts[6]
            
            # Handle playerx/playery
            # Use None to indicate "keep player position"
            if dest_x == 'playerx':
                dest_x = None  # Will be replaced with player's current X
            else:
                dest_x = float(dest_x)
                
            if dest_y == 'playery':
                dest_y = None  # Will be replaced with player's current Y
            else:
                dest_y = float(dest_y)
            
            self.logger.info(f"Level link: ({x},{y}) size {width}x{height} -> {dest_level} at ({dest_x},{dest_y})")
            
            return {
                "type": "level_link",
                "x": x, "y": y,
                "width": width, "height": height,
                "level_name": dest_level,  # Keep compatibility with old code
                "new_x": dest_x,  # Keep compatibility
                "new_y": dest_y,  # Keep compatibility
                "data": reader.data[reader.pos:]  # Keep raw data for compatibility
            }
        else:
            self.logger.warning(f"Malformed level link data: {newworld_str}")
            return {
                "type": "level_link",
                "x": 0, "y": 0,
                "width": 1, "height": 1,
                "level_name": "unknown",
                "new_x": 0, "new_y": 0,
                "data": reader.data[reader.pos:]
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
        # The server sends the filename as raw string data, not gstring
        filename = reader.read_remaining().decode('latin-1', errors='replace')
        self.logger.error(f"PLO_FILESENDFAILED: Failed to send file '{filename}'")
        
        # Track failed file requests
        if not hasattr(self, '_failed_files'):
            self._failed_files = []
        self._failed_files.append(filename)
        
        # Track with file tracker if available
        if hasattr(self.client, 'file_tracker'):
            self.client.file_tracker.on_file_failed(filename)
        
        # Log accumulated failures
        self.logger.warning(f"Total failed file requests: {len(self._failed_files)}")
        if len(self._failed_files) > 5:
            self.logger.error(f"Multiple file failures detected! Last 5: {self._failed_files[-5:]}")
        
        return {"type": "file_send_failed", "filename": filename}
    
    def _handle_file_uptodate(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle PLO_FILEUPTODATE (45) - File is already up to date"""
        filename = reader.read_gstring()
        self.logger.info(f"PLO_FILEUPTODATE: File '{filename}' is already up to date")
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
    
    # === NEW IMPROVED HANDLERS USING STRUCTURE-AWARE PARSING ===
    
    def _handle_is_leader(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle PLO_ISLEADER (10) - Player is leader notification"""
        # This is a zero-byte packet, just indicates player is leader
        return {"type": "is_leader", "is_leader": True}
    
    def _handle_npc_weapon_add_improved(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle PLO_NPCWEAPONADD (33) - Add weapon to NPC using structure parsing"""
        weapon_script = reader.read_gstring()
        self.logger.info(f"[NPC_WEAPON_ADD] Adding NPC weapon script ({len(weapon_script)} chars)")
        return {"type": "npc_weapon_add", "weapon_script": weapon_script}
    
    def _handle_level_mod_time(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle PLO_LEVELMODTIME (39) - Level modification timestamp"""
        # This should use GINT5 format according to our structure
        timestamp = reader.read_gint5()
        self.logger.info(f"[LEVEL_MOD_TIME] Level modification timestamp: {timestamp}")
        return {"type": "level_mod_time", "timestamp": timestamp}
    
    def _handle_start_message(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle PLO_STARTMESSAGE (41) - Server start message (often HTML)"""
        message = reader.read_gstring()
        self.logger.info(f"[START_MESSAGE] Server start message ({len(message)} chars)")
        return {"type": "start_message", "message": message}
    
    def _handle_player_warp2(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle PLO_PLAYERWARP2 (49) - Advanced player warp with GMAP data"""
        warp_data = reader.read_gstring()
        self.logger.info(f"[PLAYER_WARP2] GMAP warp data: {warp_data[:50]}...")
        
        # Emit GMAP-related events if needed
        if self.client:
            from ..core.events import EventType
            self.client.events.emit(EventType.PLAYER_WARPED, warp_data=warp_data)
        
        return {"type": "player_warp2", "warp_data": warp_data}
    
    def _handle_set_active_level(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle PLO_SETACTIVELEVEL (156) - Set active level for server operations"""
        level_name = reader.read_gstring()
        self.logger.info(f"[SET_ACTIVE_LEVEL] Active level: {level_name}")
        
        # Emit level change event
        if self.client:
            from ..core.events import EventType
            self.client.events.emit(EventType.LEVEL_CHANGE, level_name=level_name)
        
        return {"type": "set_active_level", "level_name": level_name}
    
    def _handle_rpg_window(self, reader: PacketReader) -> Dict[str, Any]:
        """Handle PLO_RPGWINDOW (179) - RPG window content"""
        window_content = reader.read_gstring()
        self.logger.info(f"[RPG_WINDOW] Window content ({len(window_content)} chars)")
        
        # Emit RPG window event
        if self.client:
            from ..core.events import EventType
            self.client.events.emit(EventType.LEVEL_UPDATE, window_content=window_content)
        
        return {"type": "rpg_window", "window_content": window_content}