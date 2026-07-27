from .common import *

def parse_hurt_player(data: bytes) -> dict:
    """
    Parse PLO_HURTPLAYER (packet 40) - player hurt notification.

    Server layout (PlayerClient::msgPLI_HURTPLAYER relay):
        gshort(attacker_id) gchar(hurtdx) gchar(hurtdy) gchar(power) gint3(npc)
    `power` is the damage in half-hearts. The old parser mistook the first
    knockback byte (hurtdx) for damage, so an attack with no knockback read as
    0 damage.
    """
    if len(data) < 2:
        return {}

    reader = PacketReader(data)
    player_id = reader.read_gshort()
    hurt_dx = reader.read_gchar() if reader.has_data() else 0
    hurt_dy = reader.read_gchar() if reader.has_data() else 0
    power = reader.read_gchar() if reader.has_data() else 0
    npc_id = reader.read_gint3() if reader.has_data() else 0

    return {
        'player_id': player_id,       # attacker id; 0 = environment/self
        'damage': power / 2.0,        # power is in half-hearts
        'knockback_x': hurt_dx,
        'knockback_y': hurt_dy,
        'npc_id': npc_id,
        # legacy keys kept for callers that referenced the old field names
        'damage_type': 0,
        'source_x': hurt_dx,
        'source_y': hurt_dy,
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


def parse_item_add(data: bytes) -> dict:
    """
    Parse PLO_ITEMADD (packet 22) - item added to level.
    Format (GServer-v2 Level.cpp): gchar(x*2) + gchar(y*2) + gchar(item_id).
    item_id is the numeric LevelItemType; map it to a name for convenience.
    """
    if len(data) < 3:
        return {}

    reader = PacketReader(data)
    x = reader.read_gchar() / 2.0  # half-tiles to tiles
    y = reader.read_gchar() / 2.0
    item_id = reader.read_gchar()

    return {
        'x': x,
        'y': y,
        'item_id': item_id,
        'type': LEVEL_ITEM_NAMES.get(item_id, f'item{item_id}'),
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

    # PLPROP_SPRITE (17) - direction (0=up, 1=left, 2=down, 3=right).
    # NOT prop 14: PLPROP_ID is a 2-byte prop, so sending it with 1 byte
    # misaligns the server's parser - the X2 marker byte gets eaten as ID's
    # second byte and the X2 HIGH byte is then read as a prop id. Depending on
    # the player's x position that garbage prop id could be COLORS (13), whose
    # 5-byte read overruns the packet and got the session kicked by GServer
    # ("Not enough data to deserialize PropertyArray.").
    packet.append(17 + 32)
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


def build_arrow_count(count: int) -> bytes:
    """Build PLI_PLAYERPROPS payload reporting the new ARROWSCOUNT (prop 4).

    Ammo is client-authoritative on GServer-v2 (PlayerProps.cpp ARROWSCOUNT/
    BOMBSCOUNT store the client-sent value; PLI_ARROWADD/PLI_BOMBADD only
    spawn the projectile), so the client must report the decremented count
    itself after firing. Clamped to GServer's props::Limits::MaxArrows (99).
    """
    return bytes([4 + 32, max(0, min(int(count), 99)) + 32])


def build_bomb_count(count: int) -> bytes:
    """Build PLI_PLAYERPROPS payload reporting the new BOMBSCOUNT (prop 5).

    See build_arrow_count for why the client reports its own ammo counts.
    """
    return bytes([5 + 32, max(0, min(int(count), 99)) + 32])


def build_hurt_response(hearts: float, x: float, y: float, direction: int,
                        gani_name: str = "hurt",
                        use_new_format: bool = True) -> bytes:
    """
    Build PLI_PLAYERPROPS packet for hurt response.
    Sends updated health and hurt animation together.

    Args:
        hearts: New hearts value after damage
        x: X position in tiles
        y: Y position in tiles
        direction: 0=up, 1=left, 2=down, 3=right
        gani_name: Hurt animation name (default "hurt")
        use_new_format: as in build_movement -- PLPROP_X2/Y2 (78/79) for
            v2.30+/v6, PLPROP_X/Y (15/16) for classic. This used to be hard
            wired to the X2/Y2 pair, so on a classic (2.22) session every
            hurt response re-announced our position in a prop pair the rest
            of that session never uses.
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

    # PLPROP_SPRITE (17) - direction (see build_animation: prop 14/ID is
    # 2 bytes and misaligns the server parser if sent with 1 byte).
    packet.append(17 + 32)
    packet.append(direction + 32)

    if not use_new_format:
        # Classic PLPROP_X (15) / PLPROP_Y (16), half-tiles.
        packet.append(15 + 32)
        packet.append(max(0, min(223, _round_position(x, 2))) + 32)
        packet.append(16 + 32)
        packet.append(max(0, min(223, _round_position(y, 2))) + 32)
        return bytes(packet)

    # PLPROP_X2 (78) - pixel X position
    pixel_x = _round_position(x, 16)
    packet.append(78 + 32)
    if pixel_x < 0:
        value = ((-pixel_x) << 1) | 1
    else:
        value = pixel_x << 1
    packet.append(((value >> 7) & 0x7F) + 32)
    packet.append((value & 0x7F) + 32)

    # PLPROP_Y2 (79) - pixel Y position
    pixel_y = _round_position(y, 16)
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

    # npc_id (gint3 - 3 bytes; server reads readGUInt() == readGInt() == 3 bytes)
    packet.append(((npc_id >> 14) & 0x7F) + 32)
    packet.append(((npc_id >> 7) & 0x7F) + 32)
    packet.append((npc_id & 0x7F) + 32)

    return bytes(packet)


def build_shoot_v1(x: float, y: float, z: float, angle: float, power: int,
                   gani: str = "blank", params: str = "") -> bytes:
    """Build the old PLI_SHOOT (packet 40) - shoot a projectile.

    Classic servers (v2.22, e.g. Bomber Arena) only handle this form; they
    ignore PLI_SHOOT2 (48), so the room-system projectiles never relay if you
    send v2. Format mirrors GServer-v2 msgPLI_SHOOT:
        gint(unused=0), gchar x, gchar y, gchar z, gchar sangle, gchar sanglez,
        gchar power, gchar ganilen + gani, gchar paramslen + params.
    Position is in 1/8-pixel units (gchar = tile*2); z is +50 biased.
    """
    import math
    def gc(v):
        return bytes([(int(v) % 224) + 32])
    sangle = int((angle / (2 * math.pi)) * 220) % 224
    p = bytearray()
    p += bytes([32, 32, 32])                         # gint(0): unused shoot id
    p += gc(int(x * 2)) + gc(int(y * 2)) + gc(int(z * 16 / 16) + 50)
    p += gc(sangle) + gc(0) + gc(power)              # sangle, sanglez, power
    gb = gani.encode('latin-1'); pb = params.encode('latin-1')
    p += gc(len(gb)) + gb
    p += gc(len(pb)) + pb
    return bytes(p)


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

    # Angle: convert radians to 0-220 range. Server decodes sangle as
    # 0..2*pi -> 0..220 (GServer-v2 PlayerClientPackets.cpp:1348,1381), so
    # this must match build_shoot_v1's 2*pi divisor, not pi (that was 2x).
    angle_byte = int((angle / (2 * math.pi)) * 220) & 0xFF
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

    # NPC ID — GUInt, which on the wire is a 3-byte GInt (server reads
    # readGUInt() == readGInt() == 3 bytes). Writing 4 bytes here shifted the
    # x/y/action by one, so the server parsed a garbage action and silently
    # ignored every triggeraction (gr.addweapon never added a weapon).
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


def build_weapon_add(npc_id: int) -> bytes:
    """Build PLI_WEAPONADD: type 1 followed by the level NPC's gint3 id."""
    return PacketBuilder().write_gchar(1).write_gint3(npc_id).build()


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

    # Position in half-tiles (gchar = byte + 32). Clamp so an out-of-range
    # coord can never raise "byte must be in range(0, 256)" from deep in the
    # builder — callers should validate first (see Client.warp_to_level), but
    # a crash here corrupts client state, so never let one escape.
    packet.append(max(0, min(255, int(x * 2) + 32)))
    packet.append(max(0, min(255, int(y * 2) + 32)))

    # Level name
    packet.extend((level_name or "").encode('latin-1'))

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


def _untokenize_csv_fields(text: str):
    """Untokenize a GServer-v2 toCSV() field list (StringUtils.h:895).

    Fields are comma-separated; a field is quoted when it contains a
    complex char (or always, with force_quoted as sendPrivateMessage uses),
    and inside quotes '"' and '\\' are written DOUBLED by the server.

    Returns (fields, quoted, starts): the decoded field values, whether each
    was quoted on the wire, and each field's start offset in `text` (so a
    caller can recover a raw unquoted tail verbatim).
    """
    fields, quoted, starts = [], [], []
    i, n = 0, len(text)
    while True:
        starts.append(i)
        if i < n and text[i] == '"':
            quoted.append(True)
            i += 1
            buf = []
            while i < n:
                c = text[i]
                if c == '"':
                    if i + 1 < n and text[i + 1] == '"':
                        buf.append('"')
                        i += 2
                        continue
                    i += 1  # closing quote
                    break
                if c == '\\' and i + 1 < n and text[i + 1] == '\\':
                    buf.append('\\')
                    i += 2
                    continue
                buf.append(c)
                i += 1
            fields.append(''.join(buf))
            while i < n and text[i] != ',':  # tolerate junk after close quote
                i += 1
        else:
            quoted.append(False)
            j = text.find(',', i)
            if j == -1:
                j = n
            fields.append(text[i:j])
            i = j
        if i >= n:
            break
        i += 1  # skip the comma
        if i == n:  # trailing comma = trailing empty field
            starts.append(i)
            fields.append('')
            quoted.append(False)
            break
    return fields, quoted, starts


def parse_private_message(data: bytes) -> dict:
    """
    Parse PLO_PRIVATEMESSAGE (packet 37) - received private message.

    Wire format (GServer-v2 Player.cpp sendPrivateMessage): gshort(sender_id)
    followed by the message split on "#b" line breaks and re-joined with
    toCSV(force_quoted=True) - i.e. every line arrives as a quoted CSV field:

        gshort(3) + '"","Private message:","Hello!"'      (player PM)
        gshort(1) + '"Welcome to the server."'            (NPC-server message)

    pygserver instead sends '"<sender>","Private message:",<raw message>' with
    the message part unquoted, so an unquoted message tail is kept verbatim
    (it may legitimately contain commas).

    Returns:
        dict with 'from_id' (sender player ID), 'type', and 'message'
        (quote wrappers removed; multi-line messages joined with '\\n')
    """
    try:
        if len(data) < 2:
            return {'from_id': 0, 'type': '', 'message': ''}

        # First 2 bytes are the GShort sender id (same encoding as PLO_TOALL).
        sender_id = ((data[0] - 32) << 7) + (data[1] - 32)

        text = data[2:].decode('latin-1', errors='replace')
        fields, quoted, starts = _untokenize_csv_fields(text)

        # GServer constructs player PMs as '#b{type}:#b{msg}' (empty first
        # line, then "Private message:"/"Mass message:"), and some server
        # messages as '{type}:#b{msg}'. Anything else (e.g. NPC-server script
        # PMs) is pure message lines.
        msg_type = ''
        msg_idx = 0
        if len(fields) >= 3 and fields[1].endswith(':'):
            msg_type = fields[1]
            msg_idx = 2
        elif len(fields) >= 2 and fields[0].endswith(':'):
            msg_type = fields[0]
            msg_idx = 1

        if msg_idx < len(fields) and not quoted[msg_idx]:
            # pygserver-style raw (unquoted) tail: keep it byte-exact,
            # commas included.
            message = text[starts[msg_idx]:]
        else:
            message = '\n'.join(fields[msg_idx:])

        return {
            'from_id': sender_id,
            'type': msg_type,
            'message': message
        }
    except Exception:
        return {'from_id': 0, 'type': '', 'message': ''}


def build_hit_objects(power: float, x: float, y: float) -> bytes:
    """
    Build PLI_HITOBJECTS (packet 36) - report a sword-swing hit probe.

    Format (GServer-v2 msgPLI_HITOBJECTS): [power*2:GCHAR][x*2:GCHAR][y*2:GCHAR]
    (an optional trailing GINT3 npc_id exists for NPC-server weapons; a plain
    sword swing does not send it). The server runs its own hit detection at
    (x, y) and fires `washit` on server-side scripted NPCs.

    Args:
        power: Hit power (sword power, hearts)
        x, y: Probe location in level tiles (center of the swing arc)
    """
    packet = bytearray()
    packet.append((int(power * 2) & 0x7F) + 32)
    packet.append((int(x * 2) & 0x7F) + 32)
    packet.append((int(y * 2) & 0x7F) + 32)
    return bytes(packet)


def build_baddy_hurt(baddy_id: int, damage: float,
                      hurt_dx: float = 0.0, hurt_dy: float = 0.0) -> bytes:
    """
    Build PLI_BADDYHURT (packet 16) - attack a baddy/enemy.

    Wire format (GServer-v2 msgPLI_BADDYHURT, PlayerClientPackets.cpp:523-539,
    commit e0cd07af9bb4be09c54c0335f222dd0eacb71c1): [GUChar baddyId][GChar
    hurtDX][GChar hurtDY][GUChar damage, half-hearts]. hurtDX/hurtDY use the
    "midpoint: 64" gchar idiom noted at that read site - a value of 0.0
    encodes as byte 64+32, +1.0 as 128+32, -1.0 as 0+32 - the same convention
    pygserver's own build_baddy_hurt (protocol/packets.py) uses for its
    PLO_BADDYHURT relay, and the mirror of parse_baddy_hurt below.

    Args:
        baddy_id: ID of the baddy to hurt
        damage: Damage amount in hearts (encoded as half-hearts on the wire)
        hurt_dx, hurt_dy: Attack direction, -1.0..1.0 per axis (0,0 = no
            direction / environment hit)

    Returns:
        Packet data for PLI_BADDYHURT
    """
    packet = bytearray()

    # Baddy ID (GUChar)
    packet.append((baddy_id & 0x7F) + 32)

    # hurtDX/hurtDY (GChar, midpoint 64) - clamp to the documented -1.0..1.0
    # range before recentering so a stray large vector doesn't wrap the byte.
    packet.append((int(max(-1.0, min(1.0, hurt_dx)) * 64) + 64 + 32) & 0xFF)
    packet.append((int(max(-1.0, min(1.0, hurt_dy)) * 64) + 64 + 32) & 0xFF)

    # Damage in half-hearts (GUChar)
    packet.append(int(damage * 2) + 32)

    return bytes(packet)


# BaddyProp ids over their own small enum (GServer-v2
# server/src/level/LevelBaddy.cpp:124 LevelBaddy::getProp). Only ever
# serialized by the reference server, so X/Y are the plain unsigned
# `position / 8` half-tiles it writes.
_BADDY_STREAM = StreamPolicy(table=BADDY_PROPS, max_prop_id=100)

_BADDY_PROP_HANDLERS = {
    1: _set('x'),
    2: _set('y'),
    3: _set('type'),
    4: _set_power_image('power', 'image'),
    5: _set('mode'),
    6: _set('animation'),
    7: lambda props, value: props.__setitem__('direction', value & 0x03),
    8: _set('verse_sight'),
    9: _set('verse_hurt'),
    10: _set('verse_attack'),
}


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
    props, _clean, _pos = parse_prop_stream(
        data, reader.pos, _BADDY_STREAM, _BADDY_PROP_HANDLERS,
        out={'id': baddy_id})
    return props


def build_baddy_props(baddy_id: int, props: dict) -> bytes:
    """
    Build PLI_BADDYPROPS (packet 15) - leader-authoritative baddy state
    update.

    Wire format (GServer-v2 msgPLI_BADDYPROPS, PlayerClientPackets.cpp:
    494-521): {GUChar baddyId}{prop blocks, same encoding as PLO_BADDYPROPS}.
    The server applies these directly to its own copy of the baddy
    (`baddy->setPropsFromPacket(props)`) and relays PLO_BADDYPROPS to every
    OTHER player in the level - the leader itself is excluded from that
    relay because it already applied the change locally before sending this.

    Only the leader ever sends this packet (see Client._leader_apply_baddy_
    damage), and only after resolving a PLI_BADDYHURT hit, so only the two
    props that hit resolution actually changes are implemented here (mirrors
    pygserver's own build_baddy_props subset in protocol/packets.py):

        BDPROP.POWERIMAGE (4) -> (power: int, image: str)
        BDPROP.MODE       (5) -> mode: int

    Args:
        baddy_id: Baddy ID
        props: {BDPROP id: value} - POWERIMAGE takes (power, image), MODE
            takes a plain int mode

    Returns:
        Packet data for PLI_BADDYPROPS
    """
    builder = PacketBuilder()
    builder.write_gchar(baddy_id)
    for prop_id, value in props.items():
        builder.write_gchar(int(prop_id))
        if prop_id == BDPROP.POWERIMAGE:
            power, image = value
            builder.write_gchar(int(power))
            builder.write_gstring(image or '')
        elif prop_id == BDPROP.MODE:
            builder.write_gchar(int(value))
        else:
            raise ValueError(f"build_baddy_props: unsupported prop id {prop_id!r}")
    return builder.build()


def build_putnpc(image: str, script_file: str, x: float, y: float) -> bytes:
    """
    Build PLI_PUTNPC (packet 21) - the classic client's `putnpc
    image,scriptfile,x,y` GS1 command. The SERVER opens `script_file` from its
    own filesystem and adds a real level NPC, which then streams back to every
    player in the level (including the sender) as ordinary NPC props - the
    client never fetches the script itself and must NOT also spawn a local
    copy, or the server echo would double it.

    Wire format (GServer-v2 msgPLI_PUTNPC, PlayerClientPackets.cpp:753-760):
    {GUChar len}{image}{GUChar len}{scriptfile}{GUChar x*2}{GUChar y*2}.
    x/y are level-local tiles at half-tile precision.
    """
    builder = PacketBuilder()
    builder.write_gstring(image or '')
    builder.write_gstring(script_file or '')
    builder.write_gchar(max(0, min(223, int(float(x) * 2))))
    builder.write_gchar(max(0, min(223, int(float(y) * 2))))
    return builder.build()


def build_baddy_add(x: float, y: float, baddy_type: int, power: int,
                    image: str) -> bytes:
    """
    Build PLI_BADDYADD (packet 17) - the classic client's `putcomp` /
    `putnewcomp` GS1 commands. The server adds the baddy (respawn disabled),
    then broadcasts PLO_BADDYPROPS to the whole level, so the baddy comes back
    to us through the normal baddy stream - no local spawn here either.

    Wire format (GServer-v2 msgPLI_BADDYADD, PlayerClientPackets.cpp:544-575):
    {GUChar x*2}{GUChar y*2}{GUChar type}{GUChar power}{image chars to end of
    packet, NO length prefix}. Power is half-hearts, server-clamped to 12.
    """
    builder = PacketBuilder()
    builder.write_gchar(max(0, min(223, int(float(x) * 2))))
    builder.write_gchar(max(0, min(223, int(float(y) * 2))))
    builder.write_gchar(int(baddy_type) & 0x7F)
    builder.write_gchar(max(0, min(12, int(power))))
    builder.write_string(image or '')
    return builder.build()


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

    # Whole-tile local position. The server (msgPLI_OPENCHEST) reads two gchars
    # and matches them directly against the chest's whole-tile position from the
    # .nw "CHEST x y item sign" line — NOT half-tiles.
    local_x = int(x) % 64
    local_y = int(y) % 64
    packet.append(local_x + 32)
    packet.append(local_y + 32)

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

def parse_bomb_add(data: bytes) -> dict:
    """
    Parse PLO_BOMBADD (11).
    Format: {GSHORT owner_id}{GCHAR x2}{GCHAR y2}{GCHAR player_power}{GCHAR timer}
    x2/y2 are tile position * 2 (half-tile precision, like PLPROP_X/Y).
    player_power packs (player_local_id << 2 | power) - power is bits 0-1.
    timer is 50ms increments until explosion (+50ms - see msgPLI_BOMBADD).
    """
    reader = PacketReader(data)
    owner_id = reader.read_gshort()
    x2 = reader.read_gchar()
    y2 = reader.read_gchar()
    player_power = reader.read_gchar()
    timer = reader.read_gchar()
    return {
        'owner_id': owner_id, 'x': x2 / 2.0, 'y': y2 / 2.0,
        'power': player_power & 0x03, 'timer_ms': timer * 50 + 50,
    }


def build_bomb_add(x: float, y: float, power: int = 1, timer_ms: int = 3050) -> bytes:
    """
    Build PLI_BOMBADD (4) payload.
    Format (msgPLI_BOMBADD): {GCHAR x*2}{GCHAR y*2}{GCHAR player_power}{GCHAR timer_increments}
    timer_ms mirrors what parse_bomb_add reports back (increments*50 + 50).
    """
    builder = PacketBuilder()
    builder.write_gchar(int(x * 2))
    builder.write_gchar(int(y * 2))
    builder.write_gchar(power & 0x03)
    builder.write_gchar(max(0, (timer_ms - 50) // 50))
    return builder.build()


def parse_bomb_del(data: bytes) -> dict:
    """
    Parse PLO_BOMBDEL (12).
    Format: {GCHAR x2}{GCHAR y2} - half-tile position of the removed bomb.
    """
    reader = PacketReader(data)
    x2 = reader.read_gchar()
    y2 = reader.read_gchar()
    return {'x': x2 / 2.0, 'y': y2 / 2.0}


def build_bomb_del(x: float, y: float) -> bytes:
    """Build PLI_BOMBDEL (5) payload: {GCHAR x*2}{GCHAR y*2}."""
    builder = PacketBuilder()
    builder.write_gchar(int(x * 2))
    builder.write_gchar(int(y * 2))
    return builder.build()


def build_explosion_add(radius: int, x: float, y: float, power: int = 1) -> bytes:
    """Build PLI_EXPLOSION (27) - a client-scripted explosion (GS1
    putexplosion/putexplosion2).

    Format (GServer-v2 msgPLI_EXPLOSION, PlayerClientPackets.cpp:840-847):
    {GUChar radius}{GUChar x*2}{GUChar y*2}{GUChar power}. x/y are level-local
    tiles at half-tile precision. The server relays it level-wide as
    PLO_EXPLOSION with our player id prepended.
    """
    builder = PacketBuilder()
    builder.write_gchar(max(0, int(radius)) & 0x7F)
    builder.write_gchar(int(x * 2))
    builder.write_gchar(int(y * 2))
    builder.write_gchar(max(0, int(power)) & 0x7F)
    return builder.build()


def build_item_add(x: float, y: float, item_id: int) -> bytes:
    """Build PLI_ITEMADD (12) - drop a level item (GS1 lay/lay2).

    Format (GServer-v2 msgPLI_ITEMADD, PlayerClientPackets.cpp:345-349):
    {GUChar x*2}{GUChar y*2}{GUChar item_id}. x/y are level-local tiles at
    half-tile precision; item_id is the LevelItemType (LEVEL_ITEM_NAMES).
    """
    builder = PacketBuilder()
    builder.write_gchar(int(x * 2))
    builder.write_gchar(int(y * 2))
    builder.write_gchar(max(0, int(item_id)) & 0x7F)
    return builder.build()


def parse_arrow_add(data: bytes) -> dict:
    """
    Parse PLO_ARROWADD (19).
    Format: {GSHORT owner_id}{GCHAR x2}{GCHAR y2}{GCHAR flags}{GCHAR sprite}{GCHAR power}
    flags: bits 0-1 direction, bit 2 reflect, bit 3 fromPlayer.
    """
    reader = PacketReader(data)
    owner_id = reader.read_gshort()
    x2 = reader.read_gchar()
    y2 = reader.read_gchar()
    flags = reader.read_gchar()
    sprite = reader.read_gchar()
    power = reader.read_gchar()
    return {
        'owner_id': owner_id, 'x': x2 / 2.0, 'y': y2 / 2.0,
        'direction': flags & 0x03, 'reflect': bool(flags & 0x04),
        'from_player': bool(flags & 0x08), 'sprite': sprite, 'power': power,
    }


def build_arrow_add(x: float, y: float, direction: int = 0, sprite: int = 0,
                    power: int = 1, reflect: bool = False, from_player: bool = True) -> bytes:
    """Build PLI_ARROWADD (9) payload: {GCHAR x*2}{GCHAR y*2}{GCHAR flags}{GCHAR sprite}{GCHAR power}."""
    flags = (direction & 0x03) | (0x04 if reflect else 0) | (0x08 if from_player else 0)
    builder = PacketBuilder()
    builder.write_gchar(int(x * 2))
    builder.write_gchar(int(y * 2))
    builder.write_gchar(flags)
    builder.write_gchar(sprite)
    builder.write_gchar(power)
    return builder.build()


def parse_horse_add(data: bytes) -> dict:
    """
    Parse PLO_HORSEADD (17) - relayed verbatim from PLI_HORSEADD, no owner id.
    Format: {GCHAR x2}{GCHAR y2}{GCHAR dir_bush}{image, raw string to end}
    dir_bush: bits 0-1 direction, remaining bits bush-power.
    """
    reader = PacketReader(data)
    x2 = reader.read_gchar()
    y2 = reader.read_gchar()
    dir_bush = reader.read_gchar()
    image = reader.remaining().decode('latin-1', errors='replace')
    return {
        'x': x2 / 2.0, 'y': y2 / 2.0, 'direction': dir_bush & 0x03,
        'bushes': dir_bush >> 2, 'image': image,
    }


def parse_horse_del(data: bytes) -> dict:
    """Parse PLO_HORSEDEL (18) - relayed verbatim. Format: {GCHAR x2}{GCHAR y2}."""
    reader = PacketReader(data)
    x2 = reader.read_gchar()
    y2 = reader.read_gchar()
    return {'x': x2 / 2.0, 'y': y2 / 2.0}


def build_horse_del(x: float, y: float) -> bytes:
    """Build PLI_HORSEDEL (8) payload: {GCHAR x*2}{GCHAR y*2}."""
    builder = PacketBuilder()
    builder.write_gchar(int(x * 2))
    builder.write_gchar(int(y * 2))
    return builder.build()


def parse_firespy(data: bytes) -> dict:
    """
    Parse PLO_FIRESPY (20).
    Format: {GSHORT owner_id}{GCHAR length_power}
    length_power: bits 0-2 power, bits 3-7 length.
    """
    reader = PacketReader(data)
    owner_id = reader.read_gshort()
    length_power = reader.read_gchar()
    return {'owner_id': owner_id, 'power': length_power & 0x07, 'length': length_power >> 3}


def build_firespy(power: int = 1, length: int = 1) -> bytes:
    """Build PLI_FIRESPY (10) payload: {GCHAR length_power} (length<<3 | power)."""
    builder = PacketBuilder()
    builder.write_gchar(((length & 0x1F) << 3) | (power & 0x07))
    return builder.build()


def parse_throwcarried(data: bytes) -> dict:
    """Parse PLO_THROWCARRIED (21). Format: {GSHORT owner_id} - no other payload."""
    reader = PacketReader(data)
    return {'owner_id': reader.read_gshort()}


def build_throwcarried() -> bytes:
    """Build PLI_THROWCARRIED (11) payload - empty, the server infers what's carried."""
    return b''


def parse_push_away(data: bytes) -> dict:
    """
    Parse PLO_PUSHAWAY (packet 38) - knockback impulse.
    Format: {GCHAR dx}{GCHAR dy}

    Per GServer-v2 (dependencies/gs2lib/include/IEnums.h): "dx is calculated
    as: dx * 0.0625 - 4.0, which is a range of -2.0 to 2.0 in 1/16 tile
    increments" - applied here to each decoded GCHAR byte (0-223) in turn, the
    same formula for dy. GServer-v2 itself never sends this packet (server/src
    only lists it in TPlayer's DO(PLO_PUSHAWAY) packet-name table) and
    pygserver's build_push_away (protocol/packets.py) uses a different,
    unused-in-practice encoding (write_gchar(dx*2)) - so this doc comment is
    the sole cross-checkable reference for the wire format; no live sender
    exists in this workspace to verify against.
    """
    if len(data) < 2:
        return {}
    reader = PacketReader(data)
    dx = reader.read_gchar() * 0.0625 - 4.0
    dy = reader.read_gchar() * 0.0625 - 4.0
    return {'dx': dx, 'dy': dy}


# =============================================================================
# NPC movement/lifecycle: PLO_NPCMOVED / PLO_MOVE2 / PLO_MOVE / PLO_NPCDEL2
# (protocol parity tier 2c)
# =============================================================================

def parse_npcmoved(data: bytes) -> dict:
    """
    Parse PLO_NPCMOVED (24) - fired when an NPC's CURLEVEL prop changes
    (server/src/object/NPC.cpp setProp CURLEVEL case): the NPC's *old*
    position (in the level it's leaving) plus the new level name.
    Format: {GINT3 npc_id}{GCHAR x/8}{GCHAR y/8}{new_level, raw string to end}
    """
    reader = PacketReader(data)
    npc_id = reader.read_gint3()
    x8 = reader.read_gchar()
    y8 = reader.read_gchar()
    new_level = reader.remaining().decode('latin-1', errors='replace')
    return {'npc_id': npc_id, 'x': x8 * 8 / 16.0, 'y': y8 * 8 / 16.0, 'new_level': new_level}


def parse_move2(data: bytes) -> dict:
    """
    Parse PLO_MOVE2 (189) - NPC move-queue update for clients >= CLVER_2_3
    (server/src/object/NPC.cpp getMoveQueuePacketData / sendMoveQueueToLevel).
    Format:
        {GINT3 npc_id}
        {GSHORT posX}{GSHORT posY}     - PropertyPixelCoordinate, local pixels
        {GSHORT dx}{GSHORT dy}         - PropertyPixelCoordinate, pixel delta to target
        {GSHORT time_50ms_increments}
        {GCHAR options}
    PropertyPixelCoordinate encodes raw pixels (not /16 tiles) as
    ((abs(v)<<1)|sign, gshort) - see PropertySerializers.cpp.
    """
    def _read_pixel_coord(reader: 'PacketReader') -> int:
        raw = reader.read_gshort()
        v = raw >> 1
        return -v if (raw & 1) else v

    reader = PacketReader(data)
    npc_id = reader.read_gint3()
    pos_x = _read_pixel_coord(reader)
    pos_y = _read_pixel_coord(reader)
    dx = _read_pixel_coord(reader)
    dy = _read_pixel_coord(reader)
    time_increments = reader.read_gshort()
    options = reader.read_gchar()
    return {
        'npc_id': npc_id, 'x': pos_x / 16.0, 'y': pos_y / 16.0,
        'dx': dx / 16.0, 'dy': dy / 16.0,
        'duration_ms': time_increments * 50, 'options': options,
    }


def parse_move(data: bytes) -> dict:
    """
    Parse PLO_MOVE (165) - NPC move-queue update for legacy clients (version
    < CLVER_2_3); the GCHAR-precision counterpart to PLO_MOVE2 (189)
    (server/src/object/NPC.cpp getMoveQueuePacketData, 'result.first' branch,
    lines 447-457; sent from sendMoveQueueToPlayer/sendMoveQueueToLevel,
    NPC.cpp:473/496).
    Format:
        {GINT3 npc_id}
        {GCHAR posX/8}{GCHAR posY/8}      - local pixel position, 1/8 precision
        {GCHAR (dx/8)+100}{GCHAR (dy/8)+100} - pixel delta to target, offset so
                                                small negative deltas stay positive
        {GSHORT time_50ms_increments}
        {GCHAR options}
    Same fields as parse_move2, coarser precision (matches the 1/8-tile scale
    PLO_NPCMOVED also uses for its GCHAR position).
    """
    reader = PacketReader(data)
    npc_id = reader.read_gint3()
    pos_x8 = reader.read_gchar()
    pos_y8 = reader.read_gchar()
    dx_units = reader.read_gchar() - 100
    dy_units = reader.read_gchar() - 100
    time_increments = reader.read_gshort()
    options = reader.read_gchar()
    return {
        'npc_id': npc_id, 'x': pos_x8 * 8 / 16.0, 'y': pos_y8 * 8 / 16.0,
        'dx': dx_units * 8 / 16.0, 'dy': dy_units * 8 / 16.0,
        'duration_ms': time_increments * 50, 'options': options,
    }


def parse_npcdel2(data: bytes) -> dict:
    """
    Parse PLO_NPCDEL2 (150) - NPC delete scoped to an explicit level name,
    sent (instead of the plain PLO_NPCDEL) when the target player's active
    level differs from the NPC's level - e.g. the NPC's clientside script was
    reloaded while the player was elsewhere but still holds a cached copy
    from a past visit (server/src/Server.cpp:1950-1954; also
    player/PlayerProps.cpp:641 and object/NPC.cpp:865
    sendScriptUpdatesToLevel, which explicitly targets
    sendPacketToLevelAndPastVisitorsAfter - i.e. it's meant to reach clients
    with a stale per-level cache, not just the current level roster).
    Format: {GCHAR level_length}{level, raw}{GINT3 npc_id}
    """
    reader = PacketReader(data)
    level = reader.read_gstring()
    npc_id = reader.read_gint3()
    return {'level': level, 'npc_id': npc_id}


def parse_flag_del(data: bytes) -> str:
    """Parse PLO_FLAGDEL (31) - name of the server-wide flag to remove (raw string)."""
    return data.decode('latin-1', errors='replace')


# =============================================================================
# Server-control packets (protocol parity tier 3)
# =============================================================================



def parse_say2(data: bytes) -> str:
    """
    Parse PLO_SAY2 (153) - a sign-style text window pushed by the server
    (PlayerClient.cpp sendSignMessage). Payload is plain translated text with
    newlines already converted to '#b'; convert them back for the caller.
    """
    text = data.decode('latin-1', errors='replace')
    return text.replace('#b', '\n')


def parse_server_warp(data: bytes) -> dict:
    """
    Parse PLO_SERVERWARP (178) - the target server to warp to.

    Payload is a gtokenized string built by the listserver
    (the C++ serverlist server's ServerConnection::msgSVI_SERVERINFO):
        "<name>\\n<name>\\n<ip>\\n<port>".gtokenize()
    relayed verbatim by GServer (ServerList.cpp msgSVI_SERVERINFO).
    """
    raw = data.decode('latin-1', errors='replace')
    tokens = _guntokenize(raw)
    tokens += [''] * (4 - len(tokens))
    try:
        port = int(tokens[3])
    except ValueError:
        port = 0
    return {'raw': raw, 'name': tokens[0], 'display_name': tokens[1],
            'host': tokens[2], 'port': port}


def parse_triggeraction_in(data: bytes) -> dict:
    """
    Parse inbound PLO_TRIGGERACTION (48).

    Two producers, same layout (Server.cpp sendTriggerActionToPlayer /
    TriggerCommandHandlers.cpp, and the player-to-player relay in
    PlayerClientPackets.cpp msgPLI_TRIGGERACTION):
        {GSHORT from_player_id}{GINT3 from_npc_id}{GCHAR x*2}{GCHAR y*2}{action CSV}
    (The relay path prepends the sender's gshort id to the sender's raw PLI
    payload, which itself starts with the gint3 npc id - identical layout.)
    """
    reader = PacketReader(data)
    player_id = reader.read_gshort()
    npc_id = reader.read_gint3()
    x2 = reader.read_gchar()
    y2 = reader.read_gchar()
    action = reader.remaining().decode('latin-1', errors='replace')
    return {'player_id': player_id, 'npc_id': npc_id,
            'x': x2 / 2.0, 'y': y2 / 2.0, 'action': action}


def parse_profile(data: bytes) -> dict:
    """
    Parse PLO_PROFILE (75) - another player's profile.

    Built by GServer ServerList.cpp msgSVI_PROFILE:
        {GCHAR len}{account}          - ACCOUNTNAME serialized
        9 x {GCHAR len}{field}        - name, age, gender, country, messenger,
                                        email, website, hangout, quote
                                        (from the listserver's SVO_PROFILE)
        {GCHAR len}{"H hrs M mins S secs"}  - online time
        [{GCHAR len}{"name:=value"}]* - playerProfileVariables (modern clients)
    """
    reader = PacketReader(data)
    account = reader.read_gstring()
    fields = []
    while reader.has_data():
        fields.append(reader.read_gstring())
    field_names = ['name', 'age', 'gender', 'country', 'messenger',
                   'email', 'website', 'hangout', 'quote', 'online_time']
    result = {'account': account}
    for i, fname in enumerate(field_names):
        result[fname] = fields[i] if i < len(fields) else ''
    variables = {}
    for extra in fields[len(field_names):]:
        if ':=' in extra:
            k, v = extra.split(':=', 1)
            variables[k] = v
    result['variables'] = variables
    return result


def build_profile_get(account: str) -> bytes:
    """
    Build PLI_PROFILEGET (80) payload - request another player's profile.

    Format: the account name raw, no length prefix (the listserver reads it
    with readString("") after skipping the forwarded packet-id byte - see
    the C++ serverlist server's ServerConnection::msgSVI_GETPROF).
    """
    return account.encode('latin-1', errors='replace')


def build_profile_set(account: str, name: str = '', age: str = '',
                      gender: str = '', country: str = '', messenger: str = '',
                      email: str = '', website: str = '', hangout: str = '',
                      quote: str = '') -> bytes:
    """
    Build PLI_PROFILESET (81) payload - update our own profile.

    Format (Player.cpp msgPLI_PROFILESET + the C++ serverlist server's msgSVI_SETPROF):
        {GCHAR len}{account} then 9 x {GCHAR len}{field}:
        name, age, gender, country, messenger, email, website, hangout, quote.
    The server rejects the whole packet if account != our account name.
    """
    builder = PacketBuilder()
    builder.write_gstring(account)
    for field in (name, age, gender, country, messenger, email, website,
                  hangout, quote):
        builder.write_gstring(field)
    return builder.build()


