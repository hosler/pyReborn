"""
pyreborn - Packet parsing
Essential packet handlers for basic gameplay.
"""

from typing import Dict, Any, Optional


# =============================================================================
# Packet Reader Utility
# =============================================================================

class PacketReader:
    """Utility for reading packet data with Reborn protocol encodings"""

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def read_byte(self) -> int:
        """Read a raw byte"""
        if self.pos >= len(self.data):
            return 0
        value = self.data[self.pos]
        self.pos += 1
        return value

    def read_gchar(self) -> int:
        """Read a GCHAR (byte - 32)"""
        return max(0, self.read_byte() - 32)

    def read_gshort(self) -> int:
        """Read a 2-byte protocol integer"""
        if self.pos + 1 >= len(self.data):
            return 0
        b1 = self.data[self.pos] - 32
        b2 = self.data[self.pos + 1] - 32
        self.pos += 2
        return (b1 << 7) + b2

    def read_gint3(self) -> int:
        """Read a 3-byte protocol integer"""
        if self.pos + 2 >= len(self.data):
            return 0
        b1 = self.data[self.pos] - 32
        b2 = self.data[self.pos + 1] - 32
        b3 = self.data[self.pos + 2] - 32
        self.pos += 3
        return (b1 << 14) | (b2 << 7) | b3

    def read_string(self, length: int) -> str:
        """Read a fixed-length string"""
        if self.pos + length > len(self.data):
            length = len(self.data) - self.pos
        data = self.data[self.pos:self.pos + length]
        self.pos += length
        return data.decode('latin-1', errors='replace')

    def read_gstring(self) -> str:
        """Read a length-prefixed string (GCHAR length)"""
        length = self.read_gchar()
        return self.read_string(length)

    def remaining(self) -> bytes:
        """Get remaining data"""
        return self.data[self.pos:]

    def has_data(self) -> bool:
        return self.pos < len(self.data)


# =============================================================================
# Packet IDs
# =============================================================================

class PacketID:
    """Common packet IDs"""
    # Server -> Client
    PLO_LEVELBOARD = 0       # Level-related data (NOT tile data, possibly compressed metadata)
    PLO_LEVELLINK = 1        # Level link/warp definition
    PLO_NPCPROPS = 3         # NPC properties
    PLO_PLAYERLEFT = 4       # Player left level
    PLO_LEVELSIGN = 5        # Level sign text
    PLO_LEVELNAME = 6        # Level name
    PLO_OTHERPLPROPS = 8     # Other player properties
    PLO_PLAYERPROPS = 9      # Player properties
    PLO_TOALL = 13           # Chat
    PLO_PLAYERWARP = 14      # Warp confirmation: [x*2:GChar][y*2:GChar][level_name]
    PLO_NPCDEL = 29          # NPC deleted
    PLO_SHOWIMG = 32         # Show image - also used for level chat!
    PLO_NPCWEAPONADD = 33    # Weapon added: +name image!<script
    PLO_RC_ADMINMESSAGE = 35 # Admin message to all players
    PLO_HURTPLAYER = 40      # Player hurt/damage notification
    PLO_NEWWORLDTIME = 42    # Heartbeat/time sync
    PLO_BADDYPROPS = 2       # Baddy/enemy properties
    PLO_ITEMADD = 22         # Item added to level
    PLO_ITEMDEL = 23         # Item removed from level
    PLO_EXPLOSION = 36       # Explosion effect
    PLO_PRIVATEMESSAGE = 37  # Private message received
    PLO_HITOBJECTS = 46      # Hit objects notification
    PLO_PLAYERWARP2 = 49     # Player warp with gmap position
    PLO_RAWDATA = 100        # Raw data size announcement
    PLO_BOARDPACKET = 101    # Level tile data (8192 bytes = 64x64 tiles @ 2 bytes each)
    PLO_FILE = 102           # File transfer packet
    PLO_FILESENDFAILED = 104 # File send failed

    # RC Server -> Client packets
    PLO_RC_SERVERFLAGSGET = 61    # Server flags response
    PLO_RC_PLAYERRIGHTSGET = 62   # Player rights response
    PLO_RC_PLAYERCOMMENTSGET = 63 # Player comments response
    PLO_RC_PLAYERBANGET = 64      # Ban status response
    PLO_RC_FILEBROWSER_DIRLIST = 65  # Directory listing
    PLO_RC_FILEBROWSER_DIR = 66   # Current directory contents
    PLO_RC_FILEBROWSER_MESSAGE = 67  # File operation message
    PLO_RC_ACCOUNTLISTGET = 70    # Account list response
    PLO_RC_PLAYERPROPSGET = 72    # Player properties (RC format)
    PLO_RC_ACCOUNTGET = 73        # Account details response
    PLO_RC_CHAT = 74              # RC chat message
    PLO_RC_SERVEROPTIONSGET = 76  # Server options response
    PLO_RC_FOLDERCONFIGGET = 77   # Folder config response
    PLO_RC_MAXUPLOADFILESIZE = 103  # Max upload size (GINT5)

    # Client -> Server
    PLI_LEVELWARP = 0        # Warp to level (x, y, level_name)
    PLI_PLAYERPROPS = 2      # Send player properties (note: 6 is PLI_TOALL in old protocol)
    PLI_NPCPROPS = 3         # Send NPC properties (char props like #P1, #P2)
    PLI_HORSEADD = 7         # Add/mount horse
    PLI_ARROWADD = 9         # Add arrow to level
    PLI_BADDYHURT = 16       # Hurt a baddy
    PLI_FLAGSET = 18         # Set a flag
    PLI_FLAGDEL = 19         # Delete a flag
    PLI_TOALL = 6            # Chat (this is the actual PLI_TOALL)
    PLI_OPENCHEST = 20       # Open a chest
    PLI_WANTFILE = 23        # Request file from server
    PLI_SHOWIMG = 24         # Show image (chat in level)
    PLI_HURTPLAYER = 26      # Attack/hurt player (send damage to victim)
    PLI_EXPLOSION = 27       # Bomb explosion
    PLI_PRIVATEMESSAGE = 28  # Private message
    PLI_ITEMTAKE = 32        # Pick up item
    PLI_ADJACENTLEVEL = 35   # Request adjacent GMAP level
    PLI_HITOBJECTS = 36      # Hit objects (sword, etc.)
    PLI_TRIGGERACTION = 38   # Trigger server action
    PLI_SHOOT = 40           # Shoot projectile (old format)
    PLI_LANGUAGE = 44        # Set language
    PLI_SHOOT2 = 48          # Shoot projectile (new format, v5.07+)

    # RC Client -> Server packets
    PLI_RC_SERVEROPTIONSGET = 51     # Get server configuration
    PLI_RC_SERVEROPTIONSSET = 52     # Set server configuration
    PLI_RC_FOLDERCONFIGGET = 53      # Get folder configuration
    PLI_RC_FOLDERCONFIGSET = 54      # Set folder configuration
    PLI_RC_RESPAWNSET = 55           # Set respawn settings
    PLI_RC_HORSELIFESET = 56         # Set horse lifetime
    PLI_RC_APINCREMENTSET = 57       # Set AP increment
    PLI_RC_BADDYRESPAWNSET = 58      # Set baddy respawn
    PLI_RC_PLAYERPROPSGET = 59       # Get player properties
    PLI_RC_PLAYERPROPSSET = 60       # Set player properties
    PLI_RC_DISCONNECTPLAYER = 61     # Kick a player
    PLI_RC_UPDATELEVELS = 62         # Update/reload server levels
    PLI_RC_ADMINMESSAGE = 63         # Send admin message to all
    PLI_RC_PRIVADMINMESSAGE = 64     # Send private admin message
    PLI_RC_LISTRCS = 65              # Get list of connected RCs
    PLI_RC_DISCONNECTRC = 66         # Disconnect another RC
    PLI_RC_APPLYREASON = 67          # Set disconnect reason
    PLI_RC_SERVERFLAGSGET = 68       # Get server flags
    PLI_RC_SERVERFLAGSSET = 69       # Set server flags
    PLI_RC_ACCOUNTADD = 70           # Create new account
    PLI_RC_ACCOUNTDEL = 71           # Delete account
    PLI_RC_ACCOUNTLISTGET = 72       # Get list of accounts
    PLI_RC_PLAYERPROPSGET2 = 73      # Get player by ID
    PLI_RC_PLAYERPROPSGET3 = 74      # Get player by account name
    PLI_RC_PLAYERPROPSRESET = 75     # Reset player props
    PLI_RC_PLAYERPROPSSET2 = 76      # Set player props (alt)
    PLI_RC_ACCOUNTGET = 77           # Get account details
    PLI_RC_ACCOUNTSET = 78           # Set account properties
    PLI_RC_CHAT = 79                 # Send message in RC chat
    PLI_RC_WARPPLAYER = 82           # Warp player to level
    PLI_RC_PLAYERRIGHTSGET = 83      # Get player rights
    PLI_RC_PLAYERRIGHTSSET = 84      # Set player rights
    PLI_RC_PLAYERCOMMENTSGET = 85    # Get player comments
    PLI_RC_PLAYERCOMMENTSSET = 86    # Set player comments
    PLI_RC_PLAYERBANGET = 87         # Get ban status
    PLI_RC_PLAYERBANSET = 88         # Set ban (duration, reason)
    PLI_RC_FILEBROWSER_START = 89    # Start file browser session
    PLI_RC_FILEBROWSER_CD = 90       # Change directory
    PLI_RC_FILEBROWSER_END = 91      # End session
    PLI_RC_FILEBROWSER_DOWN = 92     # Download file
    PLI_RC_FILEBROWSER_UP = 93       # Upload file
    PLI_RC_FILEBROWSER_MOVE = 96     # Move/rename file
    PLI_RC_FILEBROWSER_DELETE = 97   # Delete file/directory
    PLI_RC_FILEBROWSER_RENAME = 98   # Rename file
    PLI_RC_LARGEFILESTART = 155      # Start large file transfer
    PLI_RC_LARGEFILEEND = 156        # End large file transfer
    PLI_RC_FOLDERDELETE = 160        # Delete folder


# =============================================================================
# Packet Parsers
# =============================================================================

def parse_level_name(data: bytes) -> str:
    """Parse PLO_LEVELNAME (packet 6) - returns level name"""
    return data.decode('latin-1', errors='replace').strip()


def parse_level_link(data: bytes) -> dict:
    """
    Parse PLO_LEVELLINK (packet 1) - returns link info.
    Format: "destLevel x y width height newX newY"
    """
    try:
        text = data.decode('latin-1', errors='replace').strip()
        parts = text.split()
        if len(parts) >= 7:
            return {
                'dest_level': parts[0],
                'x': int(parts[1]),
                'y': int(parts[2]),
                'width': int(parts[3]),
                'height': int(parts[4]),
                'dest_x': parts[5],
                'dest_y': parts[6]
            }
    except:
        pass
    return {}


def parse_npc_props(data: bytes) -> dict:
    """
    Parse PLO_NPCPROPS (packet 3) - returns NPC info.
    Format: INT3(npc_id) + props...
    """
    if len(data) < 3:
        return {}

    reader = PacketReader(data)
    npc_id = reader.read_gint3()

    props = {'id': npc_id}
    pos = reader.pos

    while pos < len(data):
        if pos >= len(data):
            break

        prop_id = data[pos] - 32
        pos += 1

        if prop_id < 0 or prop_id > 100:
            break

        # Image (prop 0) - string with gchar length
        if prop_id == 0:
            if pos < len(data):
                str_len = data[pos] - 32
                pos += 1
                if str_len > 0 and pos + str_len <= len(data):
                    props['image'] = data[pos:pos + str_len].decode('latin-1', errors='replace')
                    pos += str_len

        # Script (prop 1) - string with SHORT length (2 bytes)
        elif prop_id == 1:
            if pos + 1 < len(data):
                # Read 2-byte length (gshort)
                b1 = data[pos] - 32
                b2 = data[pos + 1] - 32
                str_len = (b1 << 7) + b2
                pos += 2
                if str_len > 0 and pos + str_len <= len(data):
                    props['script'] = data[pos:pos + str_len].decode('latin-1', errors='replace')
                    pos += str_len

        # X position (prop 2) - 1 byte
        elif prop_id == 2:
            if pos < len(data):
                props['x'] = (data[pos] - 32) / 2.0
                pos += 1

        # Y position (prop 3) - 1 byte
        elif prop_id == 3:
            if pos < len(data):
                props['y'] = (data[pos] - 32) / 2.0
                pos += 1

        # Direction (prop 5) - 1 byte
        elif prop_id == 5:
            if pos < len(data):
                props['direction'] = data[pos] - 32
                pos += 1

        # PLPROP_OSTYPE (75) - string (1 byte length + chars)
        elif prop_id == 75:
            if pos < len(data):
                str_len = data[pos] - 32
                pos += 1
                if str_len > 0 and pos + str_len <= len(data):
                    props['os_type'] = data[pos:pos + str_len].decode('latin-1', errors='replace')
                    pos += str_len

        # PLPROP_TEXTCODEPAGE (76) - gInt (3 bytes)
        elif prop_id == 76:
            if pos + 2 < len(data):
                b1 = data[pos] - 32
                b2 = data[pos + 1] - 32
                b3 = data[pos + 2] - 32
                props['codepage'] = (b1 << 14) | (b2 << 7) | b3
                pos += 3

        # String properties - skip
        elif prop_id in [1, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35]:
            if pos < len(data):
                str_len = data[pos] - 32
                pos += 1
                if str_len > 0:
                    pos += str_len

        # Default: single byte
        else:
            if pos < len(data):
                pos += 1

    return props


def parse_chat(data: bytes) -> tuple:
    """
    Parse PLO_TOALL (packet 13) - returns (player_id, message)
    Format: gshort(player_id) + gchar(message_length-1) + message[1:]

    Note: GServer v6.037 appears to send chat messages with the first
    character encoded in a gchar length byte. The actual first character
    is NOT transmitted - only the message length and remaining characters.

    We attempt to reconstruct the first character by computing first_byte * 2,
    which works for some characters (like 'H' = 72 = 36 * 2).
    """
    if len(data) < 2:
        return (0, "")
    reader = PacketReader(data)
    player_id = reader.read_gshort()

    remaining = reader.remaining()
    if not remaining:
        return (player_id, "")

    # First byte is gchar(message_length - 1), NOT the first character
    first_byte = remaining[0]
    length_minus_1 = first_byte - 32  # Decode gchar

    # Rest of message (starting from second character)
    rest = remaining[1:].decode('latin-1', errors='replace') if len(remaining) > 1 else ""

    # The first character is lost in transmission.
    # We can try to recover it with first_byte * 2, but this only works
    # when the first char's ASCII value happens to equal 2 * gchar(len-1).
    # For most messages, we just have to accept the first char is missing.

    # If the message is very short (1 char), the whole message is just the length byte
    if length_minus_1 == 0 and not rest:
        # Single character message - try first_byte * 2
        first_char_doubled = first_byte * 2
        if 32 <= first_char_doubled < 127:
            return (player_id, chr(first_char_doubled))
        return (player_id, "")

    # For longer messages, just return what we have (missing first char)
    # The caller/display can handle this
    message = rest if rest else ""
    return (player_id, message)


def parse_player_movement(data: bytes) -> dict:
    """
    Parse PLO_TOALL (packet 13) as movement update.
    Movement updates contain props 78 (X2) and 79 (Y2) for position.
    Returns dict with player_id, x, y, or None if not a movement packet.
    """
    if len(data) < 4:
        return None

    reader = PacketReader(data)
    player_id = reader.read_gshort()

    result = {'id': player_id}
    pos = reader.pos

    # Check if this looks like movement data (starts with prop 7 or similar)
    if pos >= len(data):
        return None

    first_prop = data[pos] - 32
    if first_prop < 0 or first_prop > 100:
        return None  # Probably text, not props

    while pos < len(data):
        if pos >= len(data):
            break
        prop_id = data[pos] - 32
        pos += 1

        if prop_id < 0 or prop_id > 100:
            # This looks like text, not movement data
            return None

        # PLPROP_X2 (78) - high precision X position
        if prop_id == 78:
            if pos + 1 < len(data):
                b1 = data[pos] - 32
                b2 = data[pos + 1] - 32
                pos += 2
                raw = (b1 << 7) | b2
                pixels = raw >> 1
                if raw & 1:
                    pixels = -pixels
                result['x'] = pixels / 16.0

        # PLPROP_Y2 (79) - high precision Y position
        elif prop_id == 79:
            if pos + 1 < len(data):
                b1 = data[pos] - 32
                b2 = data[pos + 1] - 32
                pos += 2
                raw = (b1 << 7) | b2
                pixels = raw >> 1
                if raw & 1:
                    pixels = -pixels
                result['y'] = pixels / 16.0

        # PLPROP_SPRITE (17) or direction
        elif prop_id == 17:
            if pos < len(data):
                result['sprite'] = data[pos] - 32
                pos += 1

        # Single byte props (0-20 range typically)
        elif prop_id in [1, 2, 3, 4, 5, 6, 7, 18, 19]:
            if pos < len(data):
                pos += 1  # Skip value byte

        # PLPROP_CURLEVEL (20) - level name string - extract it
        elif prop_id == 20:
            if pos < len(data):
                str_len = data[pos] - 32
                pos += 1
                if str_len > 0 and pos + str_len <= len(data):
                    result['level'] = data[pos:pos + str_len].decode('latin-1', errors='replace')
                    pos += str_len

        # String props - skip them
        elif prop_id in [0, 10, 11, 12, 21, 22, 23]:
            if pos < len(data):
                str_len = data[pos] - 32
                pos += 1 + str_len

        else:
            # Unknown prop, assume 1 byte
            if pos < len(data):
                pos += 1

    # Only return if we got position data
    if 'x' in result or 'y' in result:
        return result
    return None


def parse_board_packet(data: bytes) -> list:
    """
    Parse PLO_BOARDPACKET (packet 101) - 8192 bytes of raw tile data.
    Returns list of 4096 tile IDs (64x64 grid).
    """
    tiles = []
    for i in range(0, min(len(data), 8192), 2):
        byte1 = data[i] if i < len(data) else 0
        byte2 = data[i + 1] if i + 1 < len(data) else 0
        tile_id = byte1 + (byte2 << 8)  # Little-endian
        tiles.append(tile_id & 0xFFF)   # Clamp to 12-bit

    # Pad to 4096 tiles if needed
    while len(tiles) < 4096:
        tiles.append(0)

    return tiles[:4096]


def parse_level_board(data: bytes) -> list:
    """
    Parse PLO_LEVELBOARD (packet 0) - compressed tile data.
    Returns list of 4096 tile IDs (64x64 grid).
    """
    import zlib

    if len(data) < 2:
        return [0] * 4096

    # First 2 bytes might be length prefix
    try:
        # Try decompressing the whole thing
        decompressed = zlib.decompress(data)
    except:
        try:
            # Skip first 2 bytes (length prefix) and try again
            decompressed = zlib.decompress(data[2:])
        except:
            return [0] * 4096

    return parse_board_packet(decompressed)


def parse_rawdata(data: bytes) -> int:
    """
    Parse PLO_RAWDATA (packet 100) - announces size of incoming raw data.
    Returns the number of bytes to expect.
    """
    if len(data) < 3:
        return 0
    reader = PacketReader(data)
    return reader.read_gint3()


def parse_other_player(data: bytes) -> dict:
    """
    Parse PLO_OTHERPLPROPS (8).
    Format: gshort(player_id) + props...
    """
    if len(data) < 2:
        return {}

    reader = PacketReader(data)
    player_id = reader.read_gshort()

    props = {'id': player_id}
    pos = reader.pos

    while pos < len(data):
        prop_id = data[pos] - 32
        pos += 1

        # PLPROP_NICKNAME (0) - string
        if prop_id == 0:
            if pos < len(data):
                str_len = data[pos] - 32
                pos += 1
                if str_len > 0 and pos + str_len <= len(data):
                    props['nickname'] = data[pos:pos + str_len].decode('latin-1', errors='replace')
                    pos += str_len

        # PLPROP_GANI (10) - animation string
        elif prop_id == 10:
            if pos < len(data):
                str_len = data[pos] - 32
                pos += 1
                if str_len > 0 and pos + str_len <= len(data):
                    props['ani'] = data[pos:pos + str_len].decode('latin-1', errors='replace')
                    pos += str_len

        # PLPROP_CURLEVEL (20) - level name string
        elif prop_id == 20:
            if pos < len(data):
                str_len = data[pos] - 32
                pos += 1
                if str_len > 0 and pos + str_len <= len(data):
                    props['level'] = data[pos:pos + str_len].decode('latin-1', errors='replace')
                    pos += str_len

        # PLPROP_ACCOUNTNAME (34) - account name string
        elif prop_id == 34:
            if pos < len(data):
                str_len = data[pos] - 32
                pos += 1
                if str_len > 0 and pos + str_len <= len(data):
                    props['account'] = data[pos:pos + str_len].decode('latin-1', errors='replace')
                    pos += str_len

        # PLPROP_X (15) - 1 byte gchar (tiles * 2)
        elif prop_id == 15:
            if pos < len(data):
                props['x'] = float(data[pos] - 32) / 2.0
                pos += 1

        # PLPROP_Y (16) - 1 byte gchar (tiles * 2)
        elif prop_id == 16:
            if pos < len(data):
                props['y'] = float(data[pos] - 32) / 2.0
                pos += 1

        # PLPROP_SPRITE (17) - contains direction in lower 2 bits
        elif prop_id == 17:
            if pos < len(data):
                props['sprite'] = data[pos] - 32
                pos += 1

        # PLPROP_STATUS (18) - 1 byte
        elif prop_id == 18:
            if pos < len(data):
                props['status'] = data[pos] - 32
                pos += 1

        # PLPROP_SWORDPOWER (8) - may have gchar followed by string for custom sword
        elif prop_id == 8:
            if pos < len(data):
                val = data[pos] - 32
                pos += 1
                if val > 4:  # Custom image - power is (val - 30)
                    props['sword_power'] = val - 30
                    if pos < len(data):
                        str_len = data[pos] - 32
                        pos += 1
                        if str_len > 0 and pos + str_len <= len(data):
                            props['sword_image'] = data[pos:pos + str_len].decode('latin-1', errors='replace')
                            pos += str_len
                else:
                    props['sword_power'] = val

        # PLPROP_SHIELDPOWER (9) - similar to sword
        elif prop_id == 9:
            if pos < len(data):
                val = data[pos] - 32
                pos += 1
                if val > 3:  # Custom shield - power is (val - 10)
                    props['shield_power'] = val - 10
                    if pos < len(data):
                        str_len = data[pos] - 32
                        pos += 1
                        if str_len > 0 and pos + str_len <= len(data):
                            props['shield_image'] = data[pos:pos + str_len].decode('latin-1', errors='replace')
                            pos += str_len
                else:
                    props['shield_power'] = val

        # PLPROP_HEADGIF (11) - head image
        elif prop_id == 11:
            if pos < len(data):
                str_len = data[pos] - 32
                pos += 1
                if str_len > 0 and pos + str_len <= len(data):
                    props['head_image'] = data[pos:pos + str_len].decode('latin-1', errors='replace')
                    pos += str_len

        # PLPROP_CURCHAT (12) - chat string (skip)
        elif prop_id == 12:
            if pos < len(data):
                str_len = data[pos] - 32
                pos += 1
                if str_len > 0 and pos + str_len <= len(data):
                    pos += str_len

        # PLPROP_COLORS (13) - 5 bytes
        elif prop_id == 13:
            pos += 5

        # PLPROP_ID (14) - 2 bytes gshort
        elif prop_id == 14:
            pos += 2

        # PLPROP_CARRYSPRITE (19) - 1 byte
        elif prop_id == 19:
            pos += 1

        # PLPROP_HORSEGIF (21), PLPROP_HORSEBUSHES (22), PLPROP_EFFECTCOLORS (23) - strings
        elif prop_id in [21, 22, 23]:
            if pos < len(data):
                str_len = data[pos] - 32
                pos += 1
                if str_len > 0 and pos + str_len <= len(data):
                    pos += str_len

        # PLPROP_BODYIMG (35) - body image string
        elif prop_id == 35:
            if pos < len(data):
                str_len = data[pos] - 32
                pos += 1
                if str_len > 0 and pos + str_len <= len(data):
                    props['body_image'] = data[pos:pos + str_len].decode('latin-1', errors='replace')
                    pos += str_len

        # Various other string props
        elif prop_id in [24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 36, 37, 38, 39, 40, 41]:
            if pos < len(data):
                str_len = data[pos] - 32
                pos += 1
                if str_len > 0 and pos + str_len <= len(data):
                    pos += str_len

        # PLPROP_OSTYPE (75) - string (1 byte length + chars)
        elif prop_id == 75:
            if pos < len(data):
                str_len = data[pos] - 32
                pos += 1
                if str_len > 0 and pos + str_len <= len(data):
                    props['os_type'] = data[pos:pos + str_len].decode('latin-1', errors='replace')
                    pos += str_len

        # PLPROP_TEXTCODEPAGE (76) - gInt (3 bytes)
        elif prop_id == 76:
            if pos + 2 < len(data):
                b1 = data[pos] - 32
                b2 = data[pos + 1] - 32
                b3 = data[pos + 2] - 32
                props['codepage'] = (b1 << 14) | (b2 << 7) | b3
                pos += 3

        # Single byte props (1-7 are numeric stats)
        elif prop_id in [1, 2, 3, 4, 5, 6, 7]:
            pos += 1

        # PLPROP_X2 (78) - 2 bytes, high precision X
        elif prop_id == 78:
            if pos + 1 < len(data):
                b1 = data[pos] - 32
                b2 = data[pos + 1] - 32
                value = (b1 << 7) | b2
                pixels = value >> 1
                if value & 0x0001:
                    pixels = -pixels
                props['x'] = pixels / 16.0
                pos += 2

        # PLPROP_Y2 (79) - 2 bytes, high precision Y
        elif prop_id == 79:
            if pos + 1 < len(data):
                b1 = data[pos] - 32
                b2 = data[pos + 1] - 32
                value = (b1 << 7) | b2
                pixels = value >> 1
                if value & 0x0001:
                    pixels = -pixels
                props['y'] = pixels / 16.0
                pos += 2

        # PLPROP_Z2 (80) - 2 bytes, high precision Z
        elif prop_id == 80:
            if pos + 1 < len(data):
                pos += 2

        # Default: single byte
        else:
            if pos < len(data):
                pos += 1

    return props


def parse_player_left(data: bytes) -> int:
    """Parse PLO_PLAYERLEFT (4) - returns player_id that left."""
    if len(data) < 2:
        return 0
    reader = PacketReader(data)
    return reader.read_gshort()


def parse_newworldtime(data: bytes) -> dict:
    """
    Parse PLO_NEWWORLDTIME (packet 42) - server heartbeat/time sync.
    Returns dict with time info.
    """
    if len(data) < 4:
        return {'time': 0}

    reader = PacketReader(data)
    # Time is typically a 4-byte value
    b1 = reader.read_byte()
    b2 = reader.read_byte()
    b3 = reader.read_byte()
    b4 = reader.read_byte() if reader.has_data() else 0

    time_val = b1 | (b2 << 8) | (b3 << 16) | (b4 << 24)
    return {'time': time_val}


def parse_playerwarp(data: bytes) -> dict:
    """
    Parse PLO_PLAYERWARP (packet 14) - player warp/spawn position.
    Format: x*2(gchar) y*2(gchar) level_name

    x, y are sent as half-tile coordinates (multiplied by 2).
    We convert to full tile coordinates for consistency.

    Returns dict with:
        x, y: position in tiles (local coordinates 0-63)
        level: level name
    """
    if len(data) < 2:
        return {}

    reader = PacketReader(data)
    x_halftile = reader.read_gchar()
    y_halftile = reader.read_gchar()
    level = reader.remaining().decode('latin-1', errors='replace').strip()

    return {
        'x': float(x_halftile) / 2.0,
        'y': float(y_halftile) / 2.0,
        'level': level
    }


def parse_playerwarp2(data: bytes) -> dict:
    """
    Parse PLO_PLAYERWARP2 (packet 49) - player position in GMAP.
    Format: x(gchar) y(gchar) z(gchar) gmap_x(gchar) gmap_y(gchar) level_name

    x, y are sent as half-tile coordinates (8 pixels per unit).
    We convert to full tile coordinates for consistency.

    Returns dict with:
        x, y: position in tiles (GMAP-relative, can be > 63)
        z: height/layer
        gmap_x, gmap_y: position in gmap grid
        level: level name (e.g., "chicken.gmap")
    """
    if len(data) < 5:
        return {}

    reader = PacketReader(data)
    x_halftile = reader.read_gchar()
    y_halftile = reader.read_gchar()
    z = reader.read_gchar()
    gmap_x = reader.read_gchar()
    gmap_y = reader.read_gchar()
    level = reader.remaining().decode('latin-1', errors='replace').strip()

    # Convert half-tiles to tiles
    return {
        'x': float(x_halftile) / 2.0,
        'y': float(y_halftile) / 2.0,
        'z': z,
        'gmap_x': gmap_x,
        'gmap_y': gmap_y,
        'level': level
    }


def parse_weapon_add(data: bytes) -> dict:
    """
    Parse PLO_NPCWEAPONADD (packet 33) - weapon being added to player.
    Format: +weaponname imagename!<script

    Returns dict with:
        name: weapon name (without + prefix)
        image: weapon image
        script: weapon GS1 script
    """
    try:
        text = data.decode('latin-1', errors='replace')

        # Format: +name image!<script  or  +name image script
        if not text.startswith('+'):
            return {}

        # Remove + prefix
        text = text[1:]

        # Find first space (separates name from rest)
        space_idx = text.find(' ')
        if space_idx == -1:
            return {'name': text, 'image': '', 'script': ''}

        name = text[:space_idx]
        rest = text[space_idx + 1:]

        # Find script separator (!< or just find script start)
        script_sep = rest.find('!<')
        if script_sep != -1:
            image = rest[:script_sep]
            script = rest[script_sep + 2:]  # Skip !<
        else:
            # Try to find 'if(' as script start
            if_idx = rest.lower().find('if(')
            if if_idx != -1:
                image = rest[:if_idx].strip()
                script = rest[if_idx:]
            else:
                image = rest
                script = ''

        return {
            'name': name,
            'image': image.strip(),
            'script': script
        }
    except:
        return {}


def parse_player_props(data: bytes) -> Dict[str, Any]:
    """
    Parse PLO_PLAYERPROPS (packet 9) - returns dict of properties.
    Simplified parser that extracts essential properties only.
    """
    props = {}
    pos = 0

    while pos < len(data):
        if pos >= len(data):
            break

        prop_id = data[pos] - 32
        pos += 1

        if prop_id < 0 or prop_id > 125:
            break

        # Nickname (prop 0) - string
        if prop_id == 0:
            if pos < len(data):
                str_len = data[pos] - 32
                pos += 1
                if str_len > 0 and pos + str_len <= len(data):
                    props['nickname'] = data[pos:pos + str_len].decode('latin-1', errors='replace')
                    pos += str_len

        # Max hearts (prop 1)
        elif prop_id == 1:
            if pos < len(data):
                props['max_hearts'] = (data[pos] - 32) / 2.0
                pos += 1

        # Current hearts (prop 2)
        elif prop_id == 2:
            if pos < len(data):
                props['hearts'] = (data[pos] - 32) / 2.0
                pos += 1

        # Rupees (prop 3) - 3 bytes
        elif prop_id == 3:
            if pos + 2 < len(data):
                b1 = data[pos] - 32
                b2 = data[pos + 1] - 32
                b3 = data[pos + 2] - 32
                props['rupees'] = (b1 << 14) | (b2 << 7) | b3
                pos += 3

        # Arrows (prop 4) - 1 byte
        elif prop_id == 4:
            if pos < len(data):
                props['arrows'] = data[pos] - 32
                pos += 1

        # Bombs (prop 5) - 1 byte
        elif prop_id == 5:
            if pos < len(data):
                props['bombs'] = data[pos] - 32
                pos += 1

        # Glove power (prop 6) - 1 byte
        elif prop_id == 6:
            if pos < len(data):
                props['glove_power'] = data[pos] - 32
                pos += 1

        # Bomb power (prop 7) - 1 byte
        elif prop_id == 7:
            if pos < len(data):
                props['bomb_power'] = data[pos] - 32
                pos += 1

        # Sword (prop 8) - power + image
        # Format: (swordPower + 30), imgLen, imgString
        elif prop_id == 8:
            if pos < len(data):
                sp = data[pos] - 32
                pos += 1
                sword_power = sp
                if sp > 4:
                    # Has image: power is encoded as (power + 30)
                    sword_power = sp - 30
                    if pos < len(data):
                        img_len = data[pos] - 32
                        pos += 1
                        if img_len > 0 and pos + img_len <= len(data):
                            props['sword_image'] = data[pos:pos + img_len].decode('latin-1', errors='replace')
                            pos += img_len
                props['sword_power'] = max(0, sword_power)

        # Shield (prop 9) - power + image
        # Format: (shieldPower + 10), imgLen, imgString
        elif prop_id == 9:
            if pos < len(data):
                sp = data[pos] - 32
                pos += 1
                shield_power = sp
                if sp > 3:
                    # Has image: power is encoded as (power + 10)
                    shield_power = sp - 10
                    if shield_power < 0:
                        break
                    if pos < len(data):
                        img_len = data[pos] - 32
                        pos += 1
                        if img_len > 0 and pos + img_len <= len(data):
                            props['shield_image'] = data[pos:pos + img_len].decode('latin-1', errors='replace')
                            pos += img_len
                props['shield_power'] = max(0, shield_power)

        # Animation (prop 10) - string
        elif prop_id == 10:
            if pos < len(data):
                str_len = data[pos] - 32
                pos += 1
                if str_len > 0 and pos + str_len <= len(data):
                    props['animation'] = data[pos:pos + str_len].decode('latin-1', errors='replace')
                    pos += str_len

        # Head image (prop 11) - special encoding
        # Format: (imgLen + 100), imgString
        elif prop_id == 11:
            if pos < len(data):
                len_val = data[pos] - 32
                pos += 1
                if len_val >= 100:
                    actual_len = len_val - 100
                    if actual_len > 0 and pos + actual_len <= len(data):
                        props['head_image'] = data[pos:pos + actual_len].decode('latin-1', errors='replace')
                        pos += actual_len

        # Current chat (prop 12) - string (what player is saying)
        elif prop_id == 12:
            if pos < len(data):
                str_len = data[pos] - 32
                pos += 1
                if str_len > 0 and pos + str_len <= len(data):
                    props['chat'] = data[pos:pos + str_len].decode('latin-1', errors='replace')
                    pos += str_len

        # Colors (prop 13) - 5 bytes
        elif prop_id == 13:
            if pos + 4 < len(data):
                pos += 5

        # Direction (prop 14)
        elif prop_id == 14:
            if pos < len(data):
                props['direction'] = data[pos] - 32
                pos += 1

        # X coordinate (prop 15) - half-tiles
        elif prop_id == 15:
            if pos < len(data):
                props['x'] = (data[pos] - 32) / 2.0
                pos += 1

        # Y coordinate (prop 16) - half-tiles
        elif prop_id == 16:
            if pos < len(data):
                props['y'] = (data[pos] - 32) / 2.0
                pos += 1

        # Sprite (prop 17)
        elif prop_id == 17:
            if pos < len(data):
                props['sprite'] = data[pos] - 32
                pos += 1

        # Status (prop 18) - 1 byte
        elif prop_id == 18:
            if pos < len(data):
                props['status'] = data[pos] - 32
                pos += 1

        # Carry sprite (prop 19) - 1 byte
        elif prop_id == 19:
            if pos < len(data):
                props['carry_sprite'] = data[pos] - 32
                pos += 1

        # Current level (prop 20) - string
        elif prop_id == 20:
            if pos < len(data):
                str_len = data[pos] - 32
                pos += 1
                if str_len > 0 and pos + str_len <= len(data):
                    props['level'] = data[pos:pos + str_len].decode('latin-1', errors='replace')
                    pos += str_len

        # Horse image (prop 21) - string
        elif prop_id == 21:
            if pos < len(data):
                str_len = data[pos] - 32
                pos += 1
                if str_len > 0 and pos + str_len <= len(data):
                    props['horse_image'] = data[pos:pos + str_len].decode('latin-1', errors='replace')
                    pos += str_len

        # Horse bushes (prop 22) - 1 byte
        elif prop_id == 22:
            if pos < len(data):
                props['horse_bushes'] = data[pos] - 32
                pos += 1

        # Effect colors (prop 23) - 4 bytes (RGBA)
        elif prop_id == 23:
            if pos + 3 < len(data):
                pos += 4

        # Carry NPC ID (prop 24) - 4 bytes (int)
        elif prop_id == 24:
            if pos + 3 < len(data):
                # Read as 4-byte GInt
                b1 = data[pos] - 32
                b2 = data[pos + 1] - 32
                b3 = data[pos + 2] - 32
                b4 = data[pos + 3] - 32
                props['carry_npc'] = (b1 << 21) | (b2 << 14) | (b3 << 7) | b4
                pos += 4

        # Account name (prop 34) - string
        # Only parse if we haven't seen account yet (avoid corruption from misinterpreted bytes)
        elif prop_id == 34:
            if pos < len(data):
                str_len = data[pos] - 32
                pos += 1
                if str_len > 0 and pos + str_len <= len(data):
                    # Only set account if we haven't parsed it yet
                    if 'account' not in props:
                        props['account'] = data[pos:pos + str_len].decode('latin-1', errors='replace')
                    pos += str_len

        # Body image (prop 35) - string
        elif prop_id == 35:
            if pos < len(data):
                str_len = data[pos] - 32
                pos += 1
                if str_len > 0 and pos + str_len <= len(data):
                    props['body_image'] = data[pos:pos + str_len].decode('latin-1', errors='replace')
                    pos += str_len

        # PixelX (prop 78) - 2 bytes, precise position
        elif prop_id == 78:
            if pos + 1 < len(data):
                b1 = data[pos] - 32
                b2 = data[pos + 1] - 32
                value = (b1 << 7) | b2
                pixels = value >> 1
                if value & 0x0001:
                    pixels = -pixels
                props['x'] = pixels / 16.0
                pos += 2

        # PixelY (prop 79) - 2 bytes, precise position
        elif prop_id == 79:
            if pos + 1 < len(data):
                b1 = data[pos] - 32
                b2 = data[pos + 1] - 32
                value = (b1 << 7) | b2
                pixels = value >> 1
                if value & 0x0001:
                    pixels = -pixels
                props['y'] = pixels / 16.0
                pos += 2

        # PixelZ (prop 80) - 2 bytes
        elif prop_id == 80:
            if pos + 1 < len(data):
                pos += 2

        # String properties (various) - skip with length
        elif prop_id in [35, 37, 38, 39, 40, 41, 46, 47, 48, 49, 52, 54, 55, 56, 57, 58, 59,
                         60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 82]:
            if pos < len(data):
                str_len = data[pos] - 32
                pos += 1
                if str_len > 0:
                    pos += str_len

        # High-numbered string properties (83-125)
        elif prop_id >= 83:
            if pos < len(data):
                str_len = data[pos] - 32
                pos += 1
                if str_len > 0:
                    pos += str_len

        # Default: single byte property
        else:
            if pos < len(data):
                pos += 1

    return props


# =============================================================================
# Packet Builders
# =============================================================================

def build_player_props(x: Optional[float] = None, y: Optional[float] = None,
                       chat: Optional[str] = None) -> bytes:
    """
    Build PLI_PLAYERPROPS (packet 6) for sending to server.
    """
    packet = bytearray()

    # X coordinate (prop 15)
    if x is not None:
        packet.append(15 + 32)  # prop_id
        packet.append(int(x * 2) + 32)  # half-tiles

    # Y coordinate (prop 16)
    if y is not None:
        packet.append(16 + 32)  # prop_id
        packet.append(int(y * 2) + 32)  # half-tiles

    return bytes(packet)


def build_chat(message: str) -> bytes:
    """Build PLI_TOALL (packet 24) for chat message."""
    return message.encode('latin-1', errors='replace')


def build_player_chat(message: str) -> bytes:
    """
    Build PLI_PLAYERPROPS with PLPROP_CURCHAT (prop 12) for local level chat.
    This shows the message above the player's head.
    """
    packet = bytearray()

    # PLPROP_CURCHAT = 12
    packet.append(12 + 32)

    # Message length (guchar) + message
    msg_bytes = message.encode('latin-1', errors='replace')
    msg_len = min(len(msg_bytes), 223)
    packet.append(msg_len + 32)
    packet.extend(msg_bytes[:msg_len])

    return bytes(packet)


def build_movement(x: float, y: float, direction: int = 2,
                   level_name: Optional[str] = None,
                   use_new_format: bool = False) -> bytes:
    """
    Build movement packet.
    Direction: 0=up, 1=left, 2=down, 3=right
    level_name: If provided, include PLPROP_CURLEVEL to notify server of level change
    use_new_format: If True, use PLPROP_X2/Y2 (for v2.30+), else use PLPROP_X/Y (for pre-2.30)
    """
    packet = bytearray()

    # Sprite/Direction (prop 17 - PLPROP_SPRITE)
    # This is the direction/animation index (0=up, 1=left, 2=down, 3=right)
    packet.append(17 + 32)
    packet.append(direction + 32)

    if use_new_format:
        # For v2.30+ clients: use PLPROP_X2 (78) and PLPROP_Y2 (79)
        # Position is in pixels (tiles * 16), encoded as GUShort with sign bit
        pixel_x = int(x * 16)
        pixel_y = int(y * 16)

        # PixelX (prop 78) - 2-byte encoding
        packet.append(78 + 32)
        if pixel_x < 0:
            value = ((-pixel_x) << 1) | 1
        else:
            value = pixel_x << 1
        packet.append(((value >> 7) & 0x7F) + 32)
        packet.append((value & 0x7F) + 32)

        # PixelY (prop 79) - 2-byte encoding
        packet.append(79 + 32)
        if pixel_y < 0:
            value = ((-pixel_y) << 1) | 1
        else:
            value = pixel_y << 1
        packet.append(((value >> 7) & 0x7F) + 32)
        packet.append((value & 0x7F) + 32)
    else:
        # For pre-2.30 clients: use PLPROP_X (15) and PLPROP_Y (16)
        # Position is in half-tiles: x_byte = x * 2 (GUChar format)
        # Server reads: x = pPacket.readGUChar() / 2.0f
        # So we send: (x * 2) + 32
        x_byte = int(x * 2)
        y_byte = int(y * 2)

        # Clamp to valid range (0-223 after +32 = 32-255)
        x_byte = max(0, min(223, x_byte))
        y_byte = max(0, min(223, y_byte))

        # PLPROP_X (15)
        packet.append(15 + 32)
        packet.append(x_byte + 32)

        # PLPROP_Y (16)
        packet.append(16 + 32)
        packet.append(y_byte + 32)

    # PLPROP_CURLEVEL (prop 20) - current level name (for GMAP level changes)
    if level_name:
        packet.append(20 + 32)
        level_bytes = level_name.encode('latin-1')
        packet.append(len(level_bytes) + 32)
        packet.extend(level_bytes)

    return bytes(packet)


def parse_hurt_player(data: bytes) -> dict:
    """
    Parse PLO_HURTPLAYER (packet 40) - player hurt notification.
    Format: gshort(player_id) + gchar(damage) + gchar(type) + gchar(source_x) + gchar(source_y)
    """
    if len(data) < 2:
        return {}

    reader = PacketReader(data)
    player_id = reader.read_gshort()
    damage = reader.read_gchar() if reader.has_data() else 0
    damage_type = reader.read_gchar() if reader.has_data() else 0
    source_x = reader.read_gchar() if reader.has_data() else 0
    source_y = reader.read_gchar() if reader.has_data() else 0

    return {
        'player_id': player_id,  # 0 = self
        'damage': damage / 2.0,  # damage in half-hearts
        'damage_type': damage_type,  # 0=sword, 1=bomb, etc.
        'source_x': source_x,
        'source_y': source_y
    }


def build_sword_attack(x: float, y: float, direction: int) -> bytes:
    """
    Build sword attack packet.
    Sword attacks are sent via player props with sword animation.

    Direction: 0=up, 1=left, 2=down, 3=right
    """
    packet = bytearray()

    # Set animation to sword (prop 10 = GANI)
    packet.append(10 + 32)  # prop_id for animation
    ani_name = b"sword"
    packet.append(len(ani_name) + 32)
    packet.extend(ani_name)

    # Sprite/Direction (prop 17 - PLPROP_SPRITE)
    packet.append(17 + 32)
    packet.append(direction + 32)

    # Position with pixel precision (props 78, 79)
    pixel_x = int(x * 16)
    pixel_y = int(y * 16)

    # PixelX (prop 78)
    packet.append(78 + 32)
    if pixel_x < 0:
        value = ((-pixel_x) << 1) | 1
    else:
        value = pixel_x << 1
    packet.append(((value >> 7) & 0x7F) + 32)
    packet.append((value & 0x7F) + 32)

    # PixelY (prop 79)
    packet.append(79 + 32)
    if pixel_y < 0:
        value = ((-pixel_y) << 1) | 1
    else:
        value = pixel_y << 1
    packet.append(((value >> 7) & 0x7F) + 32)
    packet.append((value & 0x7F) + 32)

    return bytes(packet)


def build_bomb_drop(x: float, y: float, power: int = 1) -> bytes:
    """
    Build bomb drop packet (PLI_EXPLOSION).
    Format: gchar(x) + gchar(y) + gchar(power)
    Uses local position (0-63 range).
    """
    packet = bytearray()
    # Use local position within level (mod 64)
    local_x = x % 64
    local_y = y % 64
    # Position in half-tiles (gchar = byte-32)
    packet.append(int(local_x * 2) + 32)
    packet.append(int(local_y * 2) + 32)
    packet.append(power + 32)

    return bytes(packet)


def parse_item_add(data: bytes) -> dict:
    """
    Parse PLO_ITEMADD (packet 22) - item added to level.
    Format: gchar(x) + gchar(y) + gchar(len) + string(item_type)
    """
    if len(data) < 2:
        return {}

    reader = PacketReader(data)
    x = reader.read_gchar() / 2.0  # half-tiles to tiles
    y = reader.read_gchar() / 2.0
    item_type = reader.read_gstring()

    return {
        'x': x,
        'y': y,
        'type': item_type
    }


def parse_item_del(data: bytes) -> dict:
    """
    Parse PLO_ITEMDEL (packet 23) - item removed from level.
    Format: gchar(x) + gchar(y)
    """
    if len(data) < 2:
        return {}

    reader = PacketReader(data)
    x = reader.read_gchar() / 2.0
    y = reader.read_gchar() / 2.0

    return {
        'x': x,
        'y': y
    }


def build_item_take(x: float, y: float) -> bytes:
    """
    Build PLI_ITEMTAKE (packet 32) - pick up an item.
    Format: gchar(x) + gchar(y)
    """
    packet = bytearray()
    # Use local position within level (mod 64)
    local_x = x % 64
    local_y = y % 64
    # Position in half-tiles
    packet.append(int(local_x * 2) + 32)
    packet.append(int(local_y * 2) + 32)

    return bytes(packet)


def build_animation(gani_name: str, x: float, y: float, direction: int) -> bytes:
    """
    Build PLI_PLAYERPROPS packet with animation (gani) and position.

    Args:
        gani_name: Animation name (e.g., "sword", "hurt", "idle", "walk")
        x: X position in tiles
        y: Y position in tiles
        direction: 0=up, 1=left, 2=down, 3=right
    """
    packet = bytearray()

    # PLPROP_GANI (10) - animation name
    packet.append(10 + 32)
    gani_bytes = gani_name.encode('latin-1')
    packet.append(len(gani_bytes) + 32)
    packet.extend(gani_bytes)

    # PLPROP_ID (14) - direction
    packet.append(14 + 32)
    packet.append(direction + 32)

    # PLPROP_X2 (78) - pixel X position
    pixel_x = int(x * 16)
    packet.append(78 + 32)
    if pixel_x < 0:
        value = ((-pixel_x) << 1) | 1
    else:
        value = pixel_x << 1
    packet.append(((value >> 7) & 0x7F) + 32)
    packet.append((value & 0x7F) + 32)

    # PLPROP_Y2 (79) - pixel Y position
    pixel_y = int(y * 16)
    packet.append(79 + 32)
    if pixel_y < 0:
        value = ((-pixel_y) << 1) | 1
    else:
        value = pixel_y << 1
    packet.append(((value >> 7) & 0x7F) + 32)
    packet.append((value & 0x7F) + 32)

    return bytes(packet)


def build_hearts(hearts: float) -> bytes:
    """
    Build PLI_PLAYERPROPS packet with current hearts value.

    Args:
        hearts: Current hearts (0.0 to max, in 0.5 increments)
    """
    packet = bytearray()

    # PLPROP_CURPOWER (2) - current hearts
    # Value is hearts * 2 (stored in half-hearts)
    packet.append(2 + 32)
    packet.append(int(hearts * 2) + 32)

    return bytes(packet)


def build_hurt_response(hearts: float, x: float, y: float, direction: int,
                        gani_name: str = "hurt") -> bytes:
    """
    Build PLI_PLAYERPROPS packet for hurt response.
    Sends updated health and hurt animation together.

    Args:
        hearts: New hearts value after damage
        x: X position in tiles
        y: Y position in tiles
        direction: 0=up, 1=left, 2=down, 3=right
        gani_name: Hurt animation name (default "hurt")
    """
    packet = bytearray()

    # PLPROP_CURPOWER (2) - current hearts
    packet.append(2 + 32)
    packet.append(int(hearts * 2) + 32)

    # PLPROP_GANI (10) - hurt animation
    packet.append(10 + 32)
    gani_bytes = gani_name.encode('latin-1')
    packet.append(len(gani_bytes) + 32)
    packet.extend(gani_bytes)

    # PLPROP_ID (14) - direction
    packet.append(14 + 32)
    packet.append(direction + 32)

    # PLPROP_X2 (78) - pixel X position
    pixel_x = int(x * 16)
    packet.append(78 + 32)
    if pixel_x < 0:
        value = ((-pixel_x) << 1) | 1
    else:
        value = pixel_x << 1
    packet.append(((value >> 7) & 0x7F) + 32)
    packet.append((value & 0x7F) + 32)

    # PLPROP_Y2 (79) - pixel Y position
    pixel_y = int(y * 16)
    packet.append(79 + 32)
    if pixel_y < 0:
        value = ((-pixel_y) << 1) | 1
    else:
        value = pixel_y << 1
    packet.append(((value >> 7) & 0x7F) + 32)
    packet.append((value & 0x7F) + 32)

    return bytes(packet)


def build_attack_player(victim_id: int, hurt_dx: int, hurt_dy: int,
                        damage: float, npc_id: int = 0) -> bytes:
    """
    Build PLI_HURTPLAYER (packet 26) - attack another player.

    Args:
        victim_id: Player ID of the victim
        hurt_dx: Knockback direction X (-128 to 127)
        hurt_dy: Knockback direction Y (-128 to 127)
        damage: Damage in hearts (will be converted to half-hearts)
        npc_id: NPC ID if caused by NPC (0 for player attack)
    """
    packet = bytearray()

    # victim player_id (gshort)
    packet.append(((victim_id >> 7) & 0x7F) + 32)
    packet.append((victim_id & 0x7F) + 32)

    # hurt_dx (gchar) - knockback direction, clamped to valid range
    # gchar encoding: value + 32, where value should be in -32 to 95
    dx_clamped = max(-32, min(95, hurt_dx))
    packet.append(dx_clamped + 32)

    # hurt_dy (gchar)
    dy_clamped = max(-32, min(95, hurt_dy))
    packet.append(dy_clamped + 32)

    # power (guchar) - damage in half-hearts
    packet.append(int(damage * 2) + 32)

    # npc_id (guint - 4 bytes)
    packet.append(((npc_id >> 21) & 0x7F) + 32)
    packet.append(((npc_id >> 14) & 0x7F) + 32)
    packet.append(((npc_id >> 7) & 0x7F) + 32)
    packet.append((npc_id & 0x7F) + 32)

    return bytes(packet)


def build_shoot(x: float, y: float, z: float, angle: float, speed: int,
                gani: str = "arrow", params: str = "", gravity: int = 8) -> bytes:
    """
    Build PLI_SHOOT2 (packet 48) - shoot a projectile.

    Args:
        x: X position in tiles
        y: Y position in tiles
        z: Z height (0 for ground level)
        angle: Angle in radians (0 = right, pi/2 = up)
        speed: Speed in pixels per 0.05 seconds (1 = 44 pixels in gscript)
        gani: Projectile animation name (default "arrow")
        gravity: Gravity effect (default 8)
        params: Additional shoot parameters

    Returns:
        Packet data for PLI_SHOOT2
    """
    import math

    packet = bytearray()

    # Convert tile position to pixels
    pixel_x = int(x * 16)
    pixel_y = int(y * 16)
    pixel_z = int(z * 16)

    # Pixel positions (gushort each)
    packet.append(((pixel_x >> 7) & 0x7F) + 32)
    packet.append((pixel_x & 0x7F) + 32)

    packet.append(((pixel_y >> 7) & 0x7F) + 32)
    packet.append((pixel_y & 0x7F) + 32)

    packet.append(((pixel_z >> 7) & 0x7F) + 32)
    packet.append((pixel_z & 0x7F) + 32)

    # Level offset x, y (gchar) - 0 for same level
    packet.append(0 + 32)  # offset_x
    packet.append(0 + 32)  # offset_y

    # Angle: convert radians to 0-220 range (0-pi = 0-220)
    angle_byte = int((angle / math.pi) * 220) & 0xFF
    packet.append(angle_byte + 32)

    # Z-angle (usually 0 for flat shots)
    packet.append(0 + 32)

    # Speed
    packet.append(min(speed, 127) + 32)

    # Gravity
    packet.append(min(gravity, 127) + 32)

    # Gani name (gushort length + string)
    gani_bytes = gani.encode('latin-1')
    gani_len = len(gani_bytes)
    packet.append(((gani_len >> 7) & 0x7F) + 32)
    packet.append((gani_len & 0x7F) + 32)
    packet.extend(gani_bytes)

    # Params (guchar length + string)
    params_bytes = params.encode('latin-1')
    packet.append(len(params_bytes) + 32)
    packet.extend(params_bytes)

    return bytes(packet)


def build_triggeraction(x: float, y: float, action: str, npc_id: int = 0) -> bytes:
    """
    Build PLI_TRIGGERACTION (packet 38) - trigger a server-side action.

    Args:
        x: X position in tiles
        y: Y position in tiles
        action: Action string (e.g., "warp,level.nw,30,30" or "serverside,funcname")
        npc_id: NPC ID to trigger on (0 for level/weapon triggers)

    Returns:
        Packet data for PLI_TRIGGERACTION
    """
    packet = bytearray()

    # NPC ID (guint - 4 bytes)
    packet.append(((npc_id >> 21) & 0x7F) + 32)
    packet.append(((npc_id >> 14) & 0x7F) + 32)
    packet.append(((npc_id >> 7) & 0x7F) + 32)
    packet.append((npc_id & 0x7F) + 32)

    # Position in half-tiles
    local_x = x % 64
    local_y = y % 64
    packet.append(int(local_x * 2) + 32)
    packet.append(int(local_y * 2) + 32)

    # Action string
    packet.extend(action.encode('latin-1'))

    return bytes(packet)


def build_npc_props(npc_id: int, prop_name: str, value: str) -> bytes:
    """
    Build PLI_NPCPROPS (packet 3) - update NPC properties.

    Args:
        npc_id: NPC ID to update
        prop_name: Property name (e.g., "P1", "P2", "P3" for gani attrs)
        value: Property value

    Returns:
        Packet data for PLI_NPCPROPS
    """
    packet = bytearray()

    # NPC ID (guint - 4 bytes)
    packet.append(((npc_id >> 21) & 0x7F) + 32)
    packet.append(((npc_id >> 14) & 0x7F) + 32)
    packet.append(((npc_id >> 7) & 0x7F) + 32)
    packet.append((npc_id & 0x7F) + 32)

    # Map prop name to NPCPROP_GATTRIB
    # P1 -> GATTRIB1 (36), P2 -> GATTRIB2 (37), P3 -> GATTRIB3 (38), etc.
    gattrib_map = {
        'P1': 36, 'P2': 37, 'P3': 38, 'P4': 39, 'P5': 40,
        'P6': 44, 'P7': 45, 'P8': 46, 'P9': 47,
        'P10': 53, 'P11': 54, 'P12': 55, 'P13': 56, 'P14': 57,
        'P15': 58, 'P16': 59, 'P17': 60, 'P18': 61, 'P19': 62,
        'P20': 63, 'P21': 64, 'P22': 65, 'P23': 66, 'P24': 67,
        'P25': 68, 'P26': 69, 'P27': 70, 'P28': 71, 'P29': 72,
        'P30': 73
    }

    prop_id = gattrib_map.get(prop_name, 15)  # Default to MESSAGE if unknown
    packet.append(prop_id + 32)

    # Value length (guchar) + value
    val_bytes = value.encode('latin-1', errors='replace')
    val_len = min(len(val_bytes), 223)
    packet.append(val_len + 32)
    packet.extend(val_bytes[:val_len])

    return bytes(packet)


def build_flag_set(flag_name: str, flag_value: str = "") -> bytes:
    """
    Build PLI_FLAGSET (packet 18) - set a player flag.

    Args:
        flag_name: Name of the flag
        flag_value: Value to set (empty string for boolean true)

    Returns:
        Packet data for PLI_FLAGSET
    """
    if flag_value:
        flag_str = f"{flag_name}={flag_value}"
    else:
        flag_str = flag_name

    return flag_str.encode('latin-1')


def build_flag_del(flag_name: str) -> bytes:
    """
    Build PLI_FLAGDEL (packet 19) - delete a player flag.

    Args:
        flag_name: Name of the flag to delete

    Returns:
        Packet data for PLI_FLAGDEL
    """
    return flag_name.encode('latin-1')


def build_level_warp(x: float, y: float, level_name: str) -> bytes:
    """
    Build PLI_LEVELWARP (packet 0) - warp to a different level.

    Args:
        x: X position in tiles (destination)
        y: Y position in tiles (destination)
        level_name: Name of the level to warp to

    Returns:
        Packet data for PLI_LEVELWARP
    """
    packet = bytearray()

    # Position in half-tiles (gchar = byte + 32)
    packet.append(int(x * 2) + 32)
    packet.append(int(y * 2) + 32)

    # Level name
    packet.extend(level_name.encode('latin-1'))

    return bytes(packet)


def build_private_message(player_ids: list, message: str) -> bytes:
    """
    Build PLI_PRIVATEMESSAGE (packet 28) - send a private message.

    Args:
        player_ids: List of numeric player IDs to send to
        message: Message to send

    Returns:
        Packet data for PLI_PRIVATEMESSAGE
    """
    packet = bytearray()

    # GUShort: player count
    count = len(player_ids)
    packet.append(((count >> 7) & 0x7F) + 32)
    packet.append((count & 0x7F) + 32)

    # GUShort for each player ID
    for pid in player_ids:
        packet.append(((pid >> 7) & 0x7F) + 32)
        packet.append((pid & 0x7F) + 32)

    # Message string
    packet.extend(message.encode('latin-1'))

    return bytes(packet)


def parse_private_message(data: bytes) -> dict:
    """
    Parse PLO_PRIVATEMESSAGE (packet 37) - received private message.

    Format: short(sender_id) + "type," + message
    Example: "\x00\x03\"Private message:\",Hello!"

    Returns:
        dict with 'from_id' (sender player ID), 'type', and 'message'
    """
    try:
        if len(data) < 2:
            return {'from_id': 0, 'type': '', 'message': ''}

        # First 2 bytes are raw short (big endian) sender ID
        sender_id = (data[0] << 8) | data[1]

        # Rest is the message type and content
        text = data[2:].decode('latin-1', errors='replace')

        # Format is like: "","Private message:",actual message
        # Split on first comma after "Private message:" or "Mass message:"
        msg_type = ''
        message = text

        # Try to extract type from quoted strings
        if text.startswith('"'):
            # Parse quoted format: "","Private message:",message
            parts = text.split(',', 2)
            if len(parts) >= 3:
                msg_type = parts[1].strip('"')
                message = parts[2]
            elif len(parts) == 2:
                msg_type = parts[0].strip('"')
                message = parts[1]

        return {
            'from_id': sender_id,
            'type': msg_type,
            'message': message
        }
    except:
        return {'from_id': 0, 'type': '', 'message': ''}


def build_baddy_hurt(baddy_id: int, damage: float) -> bytes:
    """
    Build PLI_BADDYHURT (packet 16) - attack a baddy/enemy.

    Args:
        baddy_id: ID of the baddy to hurt
        damage: Damage amount in hearts

    Returns:
        Packet data for PLI_BADDYHURT
    """
    packet = bytearray()

    # Baddy ID (gchar)
    packet.append((baddy_id & 0x7F) + 32)

    # Damage in half-hearts (gchar)
    packet.append(int(damage * 2) + 32)

    return bytes(packet)


def parse_baddy_props(data: bytes) -> dict:
    """
    Parse PLO_BADDYPROPS (packet 2) - baddy/enemy properties.

    Returns:
        dict with baddy id, position, type, etc.
    """
    if len(data) < 1:
        return {}

    reader = PacketReader(data)
    baddy_id = reader.read_gchar()

    props = {'id': baddy_id}
    pos = reader.pos

    while pos < len(data):
        if pos >= len(data):
            break

        prop_id = data[pos] - 32
        pos += 1

        if prop_id < 0 or prop_id > 100:
            break

        # BDPROP_X (1) - X position
        if prop_id == 1:
            if pos < len(data):
                props['x'] = (data[pos] - 32) / 2.0
                pos += 1

        # BDPROP_Y (2) - Y position
        elif prop_id == 2:
            if pos < len(data):
                props['y'] = (data[pos] - 32) / 2.0
                pos += 1

        # BDPROP_TYPE (3) - Baddy type
        elif prop_id == 3:
            if pos < len(data):
                props['type'] = data[pos] - 32
                pos += 1

        # BDPROP_POWER (4) - Remaining power/health
        elif prop_id == 4:
            if pos < len(data):
                props['power'] = data[pos] - 32
                pos += 1

        # BDPROP_DIR (5) - Direction
        elif prop_id == 5:
            if pos < len(data):
                props['direction'] = data[pos] - 32
                pos += 1

        # BDPROP_IMAGE (6) - Image string
        elif prop_id == 6:
            if pos < len(data):
                str_len = data[pos] - 32
                pos += 1
                if str_len > 0 and pos + str_len <= len(data):
                    props['image'] = data[pos:pos + str_len].decode('latin-1', errors='replace')
                    pos += str_len

        # BDPROP_ANI (7) - Animation string
        elif prop_id == 7:
            if pos < len(data):
                str_len = data[pos] - 32
                pos += 1
                if str_len > 0 and pos + str_len <= len(data):
                    props['animation'] = data[pos:pos + str_len].decode('latin-1', errors='replace')
                    pos += str_len

        # Default: single byte
        else:
            if pos < len(data):
                pos += 1

    return props


def build_open_chest(x: float, y: float) -> bytes:
    """
    Build PLI_OPENCHEST (packet 20) - open a chest at position.

    Args:
        x: Chest X position in tiles
        y: Chest Y position in tiles

    Returns:
        Packet data for PLI_OPENCHEST
    """
    packet = bytearray()

    # Local position in half-tiles
    local_x = x % 64
    local_y = y % 64
    packet.append(int(local_x * 2) + 32)
    packet.append(int(local_y * 2) + 32)

    return bytes(packet)


def build_horse_add(x: float, y: float, image: str = "horse.png",
                    direction: int = 2, bush_type: int = 0) -> bytes:
    """
    Build PLI_HORSEADD (packet 7) - add/mount a horse.

    Args:
        x: Horse X position in tiles
        y: Horse Y position in tiles
        image: Horse image name (default "horse.png")
        direction: Direction (0=up, 1=left, 2=down, 3=right)
        bush_type: Bush hiding type (0=none)

    Returns:
        Packet data for PLI_HORSEADD
    """
    packet = bytearray()

    # Position in half-tiles
    local_x = x % 64
    local_y = y % 64
    packet.append(int(local_x * 2) + 32)
    packet.append(int(local_y * 2) + 32)

    # Direction + bush type combined (dir in lower 2 bits)
    dir_bush = (direction & 0x03) | ((bush_type & 0x3F) << 2)
    packet.append(dir_bush + 32)

    # Horse image name
    packet.extend(image.encode('latin-1'))

    return bytes(packet)


# =============================================================================
# RC Packet Parsers
# =============================================================================

def parse_rc_chat(data: bytes) -> str:
    """
    Parse PLO_RC_CHAT (packet 74) - RC chat message.
    Returns the message string.
    """
    return data.decode('latin-1', errors='replace')


def parse_rc_admin_message(data: bytes) -> dict:
    """
    Parse PLO_RC_ADMINMESSAGE (packet 35) - Admin message to all players.
    Format: "Admin accountname:" + 0xa7 + message
    """
    text = data.decode('latin-1', errors='replace')
    # Split on 0xa7 (section sign character)
    if '\xa7' in text:
        header, message = text.split('\xa7', 1)
        # Extract admin name from header like "Admin username:"
        admin = header.replace('Admin ', '').rstrip(':')
        return {'admin': admin, 'message': message}
    return {'admin': '', 'message': text}


def parse_rc_server_flags(data: bytes) -> dict:
    """
    Parse PLO_RC_SERVERFLAGSGET (packet 61) - Server flags response.
    Format: gshort(count) + [gchar(len) + flag_string] * count
    """
    if len(data) < 2:
        return {'flags': []}

    reader = PacketReader(data)
    count = reader.read_gshort()

    flags = []
    for _ in range(count):
        flag = reader.read_gstring()
        if flag:
            flags.append(flag)

    return {'flags': flags}


def parse_rc_player_props(data: bytes) -> dict:
    """
    Parse PLO_RC_PLAYERPROPSGET (packet 72) - Player properties (RC format).
    Format: gshort(player_id) + props...
    """
    if len(data) < 2:
        return {}

    reader = PacketReader(data)
    player_id = reader.read_gshort()

    # The rest is player props in standard format
    props = parse_player_props(reader.remaining())
    props['player_id'] = player_id
    return props


def parse_rc_account_list(data: bytes) -> dict:
    """
    Parse PLO_RC_ACCOUNTLISTGET (packet 70) - Account list response.
    Returns list of account names.
    """
    # Format: tokenized list of account names
    text = data.decode('latin-1', errors='replace')
    accounts = [a.strip() for a in text.split('\n') if a.strip()]
    return {'accounts': accounts}


def parse_rc_account_get(data: bytes) -> dict:
    """
    Parse PLO_RC_ACCOUNTGET (packet 73) - Account details response.
    Format: gchar(name_len) + name + gchar(banned) + ban_reason + gchar(pw_len) + password + ...
    """
    if len(data) < 1:
        return {}

    reader = PacketReader(data)
    name = reader.read_gstring()
    banned = reader.read_gchar() == 1 if reader.has_data() else False
    ban_reason = reader.read_gstring() if reader.has_data() else ''

    return {
        'name': name,
        'banned': banned,
        'ban_reason': ban_reason
    }


def parse_rc_player_rights(data: bytes) -> dict:
    """
    Parse PLO_RC_PLAYERRIGHTSGET (packet 62) - Player rights response.
    Format: gchar(name_len) + name + rights_flags + folder_access
    """
    if len(data) < 1:
        return {}

    reader = PacketReader(data)
    name = reader.read_gstring()
    # Rights are in remaining data as encoded flags
    rights_data = reader.remaining().decode('latin-1', errors='replace')

    return {
        'name': name,
        'rights': rights_data
    }


def parse_rc_player_comments(data: bytes) -> dict:
    """
    Parse PLO_RC_PLAYERCOMMENTSGET (packet 63) - Player comments response.
    Format: gchar(name_len) + name + comments
    """
    if len(data) < 1:
        return {}

    reader = PacketReader(data)
    name = reader.read_gstring()
    comments = reader.remaining().decode('latin-1', errors='replace')

    return {
        'name': name,
        'comments': comments
    }


def parse_rc_player_ban(data: bytes) -> dict:
    """
    Parse PLO_RC_PLAYERBANGET (packet 64) - Ban status response.
    Format: gchar(name_len) + name + gchar(banned) + reason
    """
    if len(data) < 1:
        return {}

    reader = PacketReader(data)
    name = reader.read_gstring()
    banned = reader.read_gchar() == 1 if reader.has_data() else False
    reason = reader.remaining().decode('latin-1', errors='replace') if reader.has_data() else ''

    return {
        'name': name,
        'banned': banned,
        'reason': reason
    }


def parse_rc_filebrowser_dirlist(data: bytes) -> dict:
    """
    Parse PLO_RC_FILEBROWSER_DIRLIST (packet 65) - Directory listing.
    Format: tokenized list of folder names
    """
    text = data.decode('latin-1', errors='replace')
    folders = [f.strip() for f in text.split('\n') if f.strip()]
    return {'folders': folders}


def parse_rc_filebrowser_dir(data: bytes) -> dict:
    """
    Parse PLO_RC_FILEBROWSER_DIR (packet 66) - Current directory contents.
    Format: gchar(folder_len) + folder_name + file_list
    """
    if len(data) < 1:
        return {}

    reader = PacketReader(data)
    folder = reader.read_gstring()
    files_data = reader.remaining().decode('latin-1', errors='replace')

    # Parse file list (tokenized: filename, size, modtime per entry)
    files = []
    lines = files_data.split('\n')
    for line in lines:
        parts = line.split(',')
        if len(parts) >= 3:
            files.append({
                'name': parts[0],
                'size': int(parts[1]) if parts[1].isdigit() else 0,
                'modified': int(parts[2]) if parts[2].isdigit() else 0
            })

    return {
        'folder': folder,
        'files': files
    }


def parse_rc_filebrowser_message(data: bytes) -> str:
    """
    Parse PLO_RC_FILEBROWSER_MESSAGE (packet 67) - File operation message.
    """
    return data.decode('latin-1', errors='replace')


def parse_rc_server_options(data: bytes) -> dict:
    """
    Parse PLO_RC_SERVEROPTIONSGET (packet 76) - Server options response.
    Format: tokenized key=value pairs
    """
    text = data.decode('latin-1', errors='replace')
    options = {}
    for line in text.split('\n'):
        if '=' in line:
            key, value = line.split('=', 1)
            options[key.strip()] = value.strip()
    return {'options': options}


def parse_rc_folder_config(data: bytes) -> dict:
    """
    Parse PLO_RC_FOLDERCONFIGGET (packet 77) - Folder config response.
    """
    text = data.decode('latin-1', errors='replace')
    return {'config': text}


# =============================================================================
# RC Packet Builders
# =============================================================================

def build_rc_chat(message: str) -> bytes:
    """
    Build PLI_RC_CHAT (packet 79) - Send message in RC chat.
    """
    return message.encode('latin-1', errors='replace')


def build_rc_admin_message(message: str) -> bytes:
    """
    Build PLI_RC_ADMINMESSAGE (packet 63) - Send admin message to all.
    """
    return message.encode('latin-1', errors='replace')


def build_rc_priv_admin_message(player_id: int, message: str) -> bytes:
    """
    Build PLI_RC_PRIVADMINMESSAGE (packet 64) - Send private admin message.
    Format: gshort(player_id) + message
    """
    packet = bytearray()
    packet.append(((player_id >> 7) & 0x7F) + 32)
    packet.append((player_id & 0x7F) + 32)
    packet.extend(message.encode('latin-1', errors='replace'))
    return bytes(packet)


def build_rc_disconnect_player(player_id: int) -> bytes:
    """
    Build PLI_RC_DISCONNECTPLAYER (packet 61) - Kick a player.
    Format: gshort(player_id)
    """
    packet = bytearray()
    packet.append(((player_id >> 7) & 0x7F) + 32)
    packet.append((player_id & 0x7F) + 32)
    return bytes(packet)


def build_rc_warp_player(player_id: int, x: float, y: float, level: str) -> bytes:
    """
    Build PLI_RC_WARPPLAYER (packet 82) - Warp player to level.
    Format: gshort(player_id) + gchar(x) + gchar(y) + level_name
    """
    packet = bytearray()
    packet.append(((player_id >> 7) & 0x7F) + 32)
    packet.append((player_id & 0x7F) + 32)
    packet.append(int(x * 2) + 32)  # half-tiles
    packet.append(int(y * 2) + 32)
    packet.extend(level.encode('latin-1', errors='replace'))
    return bytes(packet)


def build_rc_player_props_get(player_id: int) -> bytes:
    """
    Build PLI_RC_PLAYERPROPSGET2 (packet 73) - Get player by ID.
    Format: gshort(player_id)
    """
    packet = bytearray()
    packet.append(((player_id >> 7) & 0x7F) + 32)
    packet.append((player_id & 0x7F) + 32)
    return bytes(packet)


def build_rc_player_props_get_by_name(account: str) -> bytes:
    """
    Build PLI_RC_PLAYERPROPSGET3 (packet 74) - Get player by account name.
    Format: gchar(name_len) + name
    """
    packet = bytearray()
    name_bytes = account.encode('latin-1', errors='replace')
    packet.append(len(name_bytes) + 32)
    packet.extend(name_bytes)
    return bytes(packet)


def build_rc_account_get(account: str) -> bytes:
    """
    Build PLI_RC_ACCOUNTGET (packet 77) - Get account details.
    """
    return account.encode('latin-1', errors='replace')


def build_rc_account_add(account: str, password: str, email: str = "") -> bytes:
    """
    Build PLI_RC_ACCOUNTADD (packet 70) - Create new account.
    Format: gchar(name_len) + name + gchar(pass_len) + pass + gchar(email_len) + email
    """
    packet = bytearray()
    acc_bytes = account.encode('latin-1', errors='replace')
    pass_bytes = password.encode('latin-1', errors='replace')
    email_bytes = email.encode('latin-1', errors='replace')

    packet.append(len(acc_bytes) + 32)
    packet.extend(acc_bytes)
    packet.append(len(pass_bytes) + 32)
    packet.extend(pass_bytes)
    packet.append(len(email_bytes) + 32)
    packet.extend(email_bytes)

    return bytes(packet)


def build_rc_account_del(account: str) -> bytes:
    """
    Build PLI_RC_ACCOUNTDEL (packet 71) - Delete account.
    """
    return account.encode('latin-1', errors='replace')


def build_rc_player_ban_get(account: str) -> bytes:
    """
    Build PLI_RC_PLAYERBANGET (packet 87) - Get ban status.
    """
    return account.encode('latin-1', errors='replace')


def build_rc_player_ban_set(account: str, banned: bool, reason: str = "") -> bytes:
    """
    Build PLI_RC_PLAYERBANSET (packet 88) - Set ban.
    Format: gchar(name_len) + name + gchar(banned) + reason
    """
    packet = bytearray()
    name_bytes = account.encode('latin-1', errors='replace')
    packet.append(len(name_bytes) + 32)
    packet.extend(name_bytes)
    packet.append((1 if banned else 0) + 32)
    packet.extend(reason.encode('latin-1', errors='replace'))
    return bytes(packet)


def build_rc_player_rights_get(account: str) -> bytes:
    """
    Build PLI_RC_PLAYERRIGHTSGET (packet 83) - Get player rights.
    """
    return account.encode('latin-1', errors='replace')


def build_rc_player_comments_get(account: str) -> bytes:
    """
    Build PLI_RC_PLAYERCOMMENTSGET (packet 85) - Get player comments.
    """
    return account.encode('latin-1', errors='replace')


def build_rc_player_comments_set(account: str, comments: str) -> bytes:
    """
    Build PLI_RC_PLAYERCOMMENTSSET (packet 86) - Set player comments.
    Format: gchar(name_len) + name + comments
    """
    packet = bytearray()
    name_bytes = account.encode('latin-1', errors='replace')
    packet.append(len(name_bytes) + 32)
    packet.extend(name_bytes)
    packet.extend(comments.encode('latin-1', errors='replace'))
    return bytes(packet)


def build_rc_server_flags_get() -> bytes:
    """
    Build PLI_RC_SERVERFLAGSGET (packet 68) - Get server flags.
    """
    return b''


def build_rc_server_options_get() -> bytes:
    """
    Build PLI_RC_SERVEROPTIONSGET (packet 51) - Get server configuration.
    """
    return b''


def build_rc_folder_config_get() -> bytes:
    """
    Build PLI_RC_FOLDERCONFIGGET (packet 53) - Get folder configuration.
    """
    return b''


def build_rc_account_list_get() -> bytes:
    """
    Build PLI_RC_ACCOUNTLISTGET (packet 72) - Get list of accounts.
    """
    return b''


def build_rc_update_levels() -> bytes:
    """
    Build PLI_RC_UPDATELEVELS (packet 62) - Update/reload server levels.
    """
    return b''


def build_rc_filebrowser_start() -> bytes:
    """
    Build PLI_RC_FILEBROWSER_START (packet 89) - Start file browser session.
    """
    return b''


def build_rc_filebrowser_cd(folder: str) -> bytes:
    """
    Build PLI_RC_FILEBROWSER_CD (packet 90) - Change directory.
    """
    return folder.encode('latin-1', errors='replace')


def build_rc_filebrowser_end() -> bytes:
    """
    Build PLI_RC_FILEBROWSER_END (packet 91) - End file browser session.
    """
    return b''


def build_rc_filebrowser_download(filename: str) -> bytes:
    """
    Build PLI_RC_FILEBROWSER_DOWN (packet 92) - Download file.
    """
    return filename.encode('latin-1', errors='replace')


def build_rc_filebrowser_delete(filename: str) -> bytes:
    """
    Build PLI_RC_FILEBROWSER_DELETE (packet 97) - Delete file/directory.
    """
    return filename.encode('latin-1', errors='replace')


def build_rc_filebrowser_rename(old_name: str, new_name: str) -> bytes:
    """
    Build PLI_RC_FILEBROWSER_RENAME (packet 98) - Rename file.
    Format: old_name + "," + new_name
    """
    return f"{old_name},{new_name}".encode('latin-1', errors='replace')


# =============================================================================
# File Transfer Packets
# =============================================================================

def build_wantfile(filename: str) -> bytes:
    """
    Build PLI_WANTFILE (packet 23) - Request file from server.
    Format: filename
    """
    return filename.encode('latin-1', errors='replace')


def parse_file(data: bytes) -> dict:
    """
    Parse PLO_FILE (packet 102) - File transfer packet.

    Format (version >= 2.1):
        modTime (5 bytes GCHAR5) + filename_length (1 byte GCHAR) + filename + file_data

    Note: GCHAR values have 32 added to them for encoding.

    Returns dict with:
        - mod_time: int - file modification time
        - filename: str - name of the file
        - data: bytes - file contents
    """
    if len(data) < 7:  # Minimum: 5 (modTime) + 1 (len) + 1 (min filename)
        return {'mod_time': 0, 'filename': '', 'data': b''}

    pos = 0

    # Read modification time (5 bytes, GCHAR encoded - subtract 32 from each)
    mod_time = 0
    for i in range(5):
        if pos < len(data):
            byte_val = max(0, data[pos] - 32)  # GCHAR decode
            mod_time = (mod_time << 8) | byte_val
            pos += 1

    # Read filename length (GCHAR encoded)
    if pos >= len(data):
        return {'mod_time': mod_time, 'filename': '', 'data': b''}

    filename_len = max(0, data[pos] - 32)  # GCHAR decode
    pos += 1

    # Read filename
    if pos + filename_len > len(data):
        filename_len = len(data) - pos
    filename = data[pos:pos + filename_len].decode('latin-1', errors='replace')
    pos += filename_len

    # Rest is file data (may end with \n which we strip)
    file_data = data[pos:]
    if file_data and file_data[-1:] == b'\n':
        file_data = file_data[:-1]

    return {
        'mod_time': mod_time,
        'filename': filename,
        'data': file_data
    }


def parse_filesendfailed(data: bytes) -> str:
    """
    Parse PLO_FILESENDFAILED (packet 104) - File send failed.
    Format: filename
    """
    return data.decode('latin-1', errors='replace')
