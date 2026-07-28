from .common import *

def parse_rawdata(data: bytes) -> int:
    """
    Parse PLO_RAWDATA (packet 100) - announces size of incoming raw data.
    Returns the number of bytes to expect.
    """
    if len(data) < 3:
        return 0
    reader = PacketReader(data)
    return reader.read_gint3()


# GServer-v2 emits props in strictly ascending id order (PlayerProps.cpp
# getPropsPacketFromList / getModifiedPropsPacket) with no padding, except that
# OTHERPLPROPS join/leave notifications prepend a standalone JOINLEAVELVL(50)
# header before the (also ascending) blob. A wrong COLORS width desyncs that
# ordering almost immediately, which is what lets _parse_with_colors_retry tell
# a correct parse from a corrupted one.

# Same wire contract, but an empty CURCHAT still reaches its handler here so the
# chat bubble can be cleared (see StreamPolicy.handle_empty). DISCONNECT (51)
# is a Wire.VOID prop whose PRESENCE is the payload -- the server's "this
# player logged out" notification (GServer-v2 Player.cpp:362 sends
# PLO_OTHERPLPROPS >> id >> DISCONNECT to every client; the reference client's
# setProperties case for it tears the player down and setotherplayerprops then
# fires onPlayerLogout) -- so it must reach its handler despite decoding to
# None.
# ...and one more ordering exemption: the external/pseudo-player packets
# (irc channels, cross-server PM players) are hand-built as ACCOUNTNAME(34),
# NICKNAME(0), PLAYERLISTCATEGORY(81) -- non-ascending -- by BOTH GServer-v2
# emitters (PlayerRequestText.cpp:170, PlayerExternalPlayers.cpp:182-184) and
# by the live Login servers (2026-07-28 capture: id 16000, 34 then 0 then
# 81), so a prop following ACCOUNTNAME may restart the ordering. The strict
# rule stopped the parse after the account and silently dropped the nick and
# the category flags of every pseudo-player.
_OTHER_STREAM = StreamPolicy(
    table=PLAYER_PROPS, max_prop_id=83, require_ascending=True,
    ascending_exempt=frozenset({34, 50}), check_alignment=True,
    handle_empty=frozenset({12, 51}))

# Props another player's PLO_OTHERPLPROPS surfaces. Deliberately not the same
# set or the same keys as _SELF_PROP_HANDLERS below: this describes somebody
# else's avatar (no inventory/stats, no ID - the packet's own leading gshort is
# authoritative), an empty CURCHAT clears their chat bubble, and a later
# ACCOUNTNAME wins because the server re-sends it on rename.
_OTHER_PROP_HANDLERS = {
    0: _set('nickname'),
    8: _set_power_image('sword_power', 'sword_image'),
    9: _set_power_image('shield_power', 'shield_image'),
    10: _set('ani'),
    11: _set_head_image,
    12: lambda props, value: props.__setitem__('chat', value or ''),
    13: _set('colors'),
    15: _set('x'),
    16: _set('y'),
    17: _set_sprite,
    18: _set('status'),
    20: _set('level'),
    26: _set('mp'),
    32: _set('ap'),
    34: _set('account'),
    35: _set('body_image'),
    # The server's level-leave notification IS this prop with value 0 (pygserver
    # build_player_left; GServer-v2 sends the same shape). Without capturing it,
    # departed players linger forever in the level roster as ghosts.
    50: _set('joinleave'),
    # DISCONNECT: payload-less logout marker (see _OTHER_STREAM's handle_empty
    # note) -- distinct from joinleave==0, which is only a LEVEL leave.
    51: lambda props, value: props.__setitem__('disconnect', True),
    # PLAYERLISTSTATUS: the numeric status-icon index every server oracle we
    # have emits (GServer-v2 PlayerProps.cpp:904 PropertyNumeric<GBYTE1>).
    # NB the v6 mobile client instead reads prop 53 as a short STRING into
    # its `message` slot (FourPlay TServerPlayer.cpp PLPROP_PSTATUSMSG case);
    # no server in the tree sends that form, so the validated gbyte width is
    # kept and the waiting-PM `message` surface is fed from
    # PLO_PRIVATEMESSAGE instead (gs2_client.pm_received).
    53: _set('playerlist_status'),
    75: _set('os_type'),
    76: _set('codepage'),
    78: _set('x'),
    79: _set('y'),
    # PLAYERLISTCATEGORY bit-flags: 1=isexternal 2=ischannel 4=ischanneluser
    # 8=ischannelopen (FourPlay TServerPlayer.cpp:1940-1954). Kept raw here;
    # gs2_client's roster wrapper decodes the bits.
    81: _set('playerlist_flags'),
    82: _set('communityname'),
    **_gattrib_handlers(),
}


def parse_other_player(data: bytes, colors_len: int = COLORS_CLASSIC,
                       diagnostics: Optional[Dict[str, int]] = None) -> dict:
    """
    Parse PLO_OTHERPLPROPS (8).
    Format: gshort(player_id) + props...

    colors_len: preferred byte width of PLPROP_COLORS (5 classic / 8 v6
    extended) to try first. Wrong value misaligns every prop after COLORS,
    so if this guess doesn't let the rest of the packet parse cleanly, the
    other known width is tried instead (see _parse_with_colors_retry).
    """
    if len(data) < 2:
        return {}

    reader = PacketReader(data)
    player_id = reader.read_gshort()
    start_pos = reader.pos

    def _run(width):
        props, clean, _ = parse_prop_stream(
            data, start_pos,
            _OTHER_STREAM.with_colors_len(width),
            _OTHER_PROP_HANDLERS,
            out={'id': player_id})
        return props, clean

    return _parse_with_colors_retry(_run, colors_len, diagnostics)


# LevelItemType id -> name (from GServer-v2 LevelItem.h enum order).


def parse_level_chest(data: bytes) -> dict:
    """Parse PLO_LEVELCHEST (4).

    Format: {gchar opened}{gchar x}{gchar y}[ {gchar item}{gchar sign} ].
    (Packet id 4 is LEVELCHEST, not a "player left" message — there is no
    player-left packet in this protocol.)

    The trailing item/sign pair is only present for *unopened* chests announced
    when entering a level. The response to actually opening a chest, and entries
    for already-opened chests, are just the 3-byte form.
    """
    if len(data) < 3:
        return {}
    result = {
        'opened': (data[0] - 32) != 0,
        'x': data[1] - 32,
        'y': data[2] - 32,
    }
    if len(data) >= 5:
        item_id = data[3] - 32
        result['item_id'] = item_id
        result['item'] = LEVEL_ITEM_NAMES.get(item_id, f'item{item_id}')
        result['sign'] = data[4] - 32
    return result


def parse_newworldtime(data: bytes) -> dict:
    """
    Parse PLO_NEWWORLDTIME (packet 42) - server heartbeat/time sync.

    The server writes this with writeGInt4 (GServer-v2 server/src/Server.cpp:148):
    four G-encoded bytes (-32 each, 7 bits per byte, big-endian), NOT raw
    little-endian bytes. PacketReader.read_gint4 performs the shared decode.
    """
    if len(data) < 4:
        return {'time': 0}

    return {'time': PacketReader(data).read_gint4()}


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

    Two wire formats exist:
      - Structured (classic 2.22 + GServer-v2): ``(gchar)namelen, name,
        (gchar)propid, value...`` where prop 0 = image (gchar len + str) and
        prop 1 = SCRIPT (gshort len + raw). This is what real Reborn servers send.
      - Legacy text: ``+name image!<script``.

    A short-lived server bug omitted the image/script property ids, producing
    ``gstring(name), gstring(image), gshort-string(script)``.  That shape is
    also accepted so an otherwise valid grant is not silently lost.

    They're ambiguous for an 11-char name (namelen 11 -> '+'), so we try the
    structured parse first and accept it only if it cleanly consumes the packet
    and yields a whitespace-free name; otherwise fall back to the text format.

    Returns dict with: name, image, script.
    """
    structured = _parse_weapon_add_structured(data)
    if structured is not None:
        return structured
    return _parse_weapon_add_text(data)


def _parse_weapon_add_structured(data: bytes):
    try:
        n = len(data)
        if n < 2:
            return None
        namelen = data[0] - 32
        if namelen <= 0 or 1 + namelen > n:
            return None
        name = data[1:1 + namelen].decode('latin-1', errors='replace')
        # A real weapon name has no spaces / script punctuation; if we see them
        # we misread a text-format packet's length byte — bail to the text path.
        if any(c in name for c in ' \t\n!<'):
            return None
        pos = 1 + namelen
        image = ''
        script = None
        classes = None
        while pos < n:
            prop = data[pos] - 32
            pos += 1
            if prop == 1:  # SCRIPT: gshort len + raw
                if pos + 1 >= n:
                    return None
                slen = ((data[pos] - 32) << 7) + (data[pos + 1] - 32)
                pos += 2
                if pos + slen > n:
                    return None
                script = data[pos:pos + slen].decode('latin-1', errors='replace')
                pos += slen
            elif prop == 74:  # CLASS: gshort len + comma-separated names
                if pos + 1 >= n:
                    return None
                clen = ((data[pos] - 32) << 7) + (data[pos + 1] - 32)
                pos += 2
                if clen < 0 or pos + clen > n:
                    return None
                classes = data[pos:pos + clen].decode('latin-1', errors='replace')
                pos += clen
            elif prop in (0, 2, 3):  # image / other gchar-len string props
                if pos >= n:
                    return None
                ln = data[pos] - 32
                pos += 1
                if ln < 0 or pos + ln > n:
                    return None
                val = data[pos:pos + ln].decode('latin-1', errors='replace')
                pos += ln
                if prop in (0, 2) and not image:
                    image = val
            else:
                return None
        if script is None and classes is None:
            return None
        result = {'name': name, 'image': image, 'script': script or ''}
        if classes is not None:
            result['classes'] = classes
        return result
    except Exception:
        return None


def parse_shoot(data: bytes, v2: bool) -> dict:
    """Parse a relayed projectile (PLO_SHOOT=40 v1 / PLO_SHOOT2=48 v2).

    Wire format mirrors GServer-v2 ShootPacketWrapper::constructShootV1/V2,
    prefixed by the shooter id (gshort). We only need the gani + the GS1 shoot
    params (the CSV string set by setshootparams), which a receiving weapon reads
    via #p(n) in an actionprojectile2 handler.

    x/y are normalized to tiles for both variants: v1 writes (pixels%1024)/8
    (half-tile units, Player.cpp:224-225) while v2 writes raw pixel gshorts
    (Player.cpp:240-241) — dividing by 2 vs 16 respectively puts both in tiles.

    Returns {shooter, gani, params, x, y} (params is the raw CSV string).
    """
    try:
        r = PacketReader(data)
        shooter = r.read_gshort()        # >> (short) m_id
        if v2:
            x = r.read_gshort(); y = r.read_gshort(); _z = r.read_gshort()
            r.read_byte(); r.read_byte()                 # offsetx/offsety (+32)
            r.read_gchar(); r.read_gchar()               # sangle, sanglez
            r.read_gchar(); r.read_gchar()               # power, gravity
            gani = r.read_gstring_short()                # gshort len + gani
            x /= 16.0
            y /= 16.0
        else:
            r.read_gint3()                               # GInt source
            x = r.read_gchar(); y = r.read_gchar(); r.read_gchar()  # x,y,z
            r.read_gchar(); r.read_gchar(); r.read_gchar()          # sangle,sanglez,power
            gani = r.read_gstring()                      # gchar len + gani
            x /= 2.0
            y /= 2.0
        params = r.read_gstring()                        # gchar len + params (CSV)
        return {'shooter': shooter, 'gani': gani, 'params': params,
                'x': x, 'y': y}
    except Exception:
        return {}


def _parse_weapon_add_text(data: bytes) -> dict:
    """Parse legacy text and the former unlabeled structured server shape."""
    try:
        if data and data[0] != ord('+'):
            namelen = data[0] - 32
            name_end = 1 + namelen
            if namelen > 0 and name_end < len(data):
                image_len = data[name_end] - 32
                image_start = name_end + 1
                image_end = image_start + image_len
                if image_len >= 0 and image_end + 2 <= len(data):
                    script_len = ((data[image_end] - 32) << 7) + (data[image_end + 1] - 32)
                    script_start = image_end + 2
                    if script_len >= 0 and script_start + script_len == len(data):
                        return {
                            'name': data[1:name_end].decode('latin-1', errors='replace'),
                            'image': data[image_start:image_end].decode('latin-1', errors='replace'),
                            'script': data[script_start:].decode('latin-1', errors='replace'),
                        }
        text = data.decode('latin-1', errors='replace')
        if not text.startswith('+'):
            return {}
        text = text[1:]
        space_idx = text.find(' ')
        if space_idx == -1:
            return {'name': text, 'image': '', 'script': ''}
        name = text[:space_idx]
        rest = text[space_idx + 1:]
        script_sep = rest.find('!<')
        if script_sep != -1:
            image = rest[:script_sep]
            script = rest[script_sep + 2:]
        else:
            if_idx = rest.lower().find('if(')
            if if_idx != -1:
                image = rest[:if_idx].strip()
                script = rest[if_idx:]
            else:
                image = rest
                script = ''
        return {'name': name, 'image': image.strip(), 'script': script}
    except Exception:
        return {}


# Props our OWN PLO_PLAYERPROPS surfaces. Deliberately a different set and
# different keys from _OTHER_PROP_HANDLERS: this is the local player, so
# inventory/stats/horse/carry state and the assigned player ID matter, an empty
# CURCHAT is nothing to act on, and the FIRST ACCOUNTNAME wins (the login flow
# can repeat the prop, and the first one is the account we authenticated as).


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
    """Build PLI_TOALL (packet 6) body for a server-wide message.

    Server (Player::msgPLI_TOALL) reads `readString(readGUChar())` — i.e. a
    gchar length prefix (raw byte - 32) followed by the raw message bytes.
    Without the length prefix the server consumes the first message char as the
    length and the relayed text is shifted/garbled.
    """
    msg = message.encode('latin-1', errors='replace')[:223]
    return bytes([len(msg) + 32]) + msg


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
        pixel_x = _round_position(x, 16)
        pixel_y = _round_position(y, 16)

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
        x_byte = _round_position(x, 2)
        y_byte = _round_position(y, 2)

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


