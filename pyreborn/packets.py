"""
pyreborn - Packet parsing
Essential packet handlers for basic gameplay.

Uses the shared reborn_protocol library for core protocol components.
"""

from typing import Dict, Any, Optional

# Import shared protocol components
from reborn_protocol import PacketReader, PacketBuilder, PLI, PLO, PLPROP, BDPROP


# =============================================================================
# Packet IDs (backwards compatibility layer)
# =============================================================================

class PacketID:
    """Protocol packet IDs.

    These are generated from the canonical ``reborn_protocol`` PLO/PLI enums so
    there is a single source of truth. This class used to hard-code the numbers
    and had drifted out of sync with the server (e.g. FILESENDFAILED was 104
    instead of 30, PLI_LANGUAGE was 44 instead of 37, and a bogus PLO_PLAYERLEFT
    aliased PLO_LEVELCHEST=4). Access them as ``PacketID.PLO_LEVELCHEST`` etc.
    """
    pass


# Populate PacketID.<PREFIX><NAME> from the authoritative enums.
for _enum, _prefix in ((PLO, "PLO_"), (PLI, "PLI_")):
    for _member in _enum:
        setattr(PacketID, _prefix + _member.name, int(_member))
del _enum, _prefix, _member

# Not present in the shared beta4 enum; used by the GS1 server showimg stream.
PacketID.PLO_SHOWIMGNPC = 166


# =============================================================================
# Player property parsing helpers
#
# Player-property payload widths are authoritative per GServer-v2:
#   server/include/object/Player.h           (prop -> serializer X-macro)
#   server/include/utilities/PropertySerializers.{h,cpp}  (serializer widths)
#   dependencies/gs2lib/src/CString.cpp       (readGChar/Short/Int = 1/2/3 bytes)
# Getting any width wrong misaligns the rest of the props packet (the classic
# "Y position suddenly jumps" symptom), so all skipping goes through one table.
# pyReborn targets v6.037 (MODERN / new-world mode => COLORS is 8 bytes).
# =============================================================================

# Fixed-size numeric props: prop_id -> payload byte count.
_PROP_FIXED_BYTES = {
    1: 1, 2: 1, 3: 3, 4: 1, 5: 1, 6: 1, 7: 1,   # power/rupees/arrows/bombs/gloves
    # 13 (COLORS) is version-dependent (classic v2/v5 = 5 bytes, v6 extended = 8)
    # so it's handled via the colors_len arg in _prop_payload_len, not here.
    14: 2,                                        # ID (gshort)
    15: 1, 16: 1, 17: 1, 18: 1, 19: 1,           # X / Y / SPRITE / STATUS / CARRYSPRITE
    22: 1, 24: 3, 25: 2, 26: 1, 27: 3, 28: 3,    # horsebushes/carrynpc/apcounter/mp/kills/deaths
    29: 3, 30: 5, 31: 3, 32: 1, 33: 1,           # onlinesecs/ip/udpport/alignment/additflags
    36: 3,                                        # RATING (PropertyEloRating, readGInt = 3)
    42: 4,                                        # ATTACHNPC (1-byte type + readGInt 3)
    43: 1, 44: 1, 45: 1,                         # GMAPLEVELX / GMAPLEVELY / Z
    50: 1, 51: 0, 53: 1,                         # JOINLEAVELVL / DISCONNECT(void) / PLAYERLISTSTATUS
    76: 3, 77: 5, 78: 2, 79: 2, 80: 2, 81: 1,    # codepage/onlinesecs2/X2/Y2/Z2/listcategory
    83: 5,                                        # UNKNOWN83 (v6 reads a GBYTE5)
}

# Length-prefixed string props (1-byte length + chars).
_PROP_STRING_IDS = (
    {0, 10, 12, 20, 21, 34, 35, 52, 75, 82}
    | {37, 38, 39, 40, 41}        # GATTRIB1-5
    | {46, 47, 48, 49}            # GATTRIB6-9
    | set(range(54, 75))          # GATTRIB10-30
)

# GATTRIB prop_id -> attribute index (1..30), in protocol order.
_GATTRIB_IDS = {
    pid: i + 1 for i, pid in enumerate(
        [37, 38, 39, 40, 41, 46, 47, 48, 49, 54, 55, 56, 57, 58, 59,
         60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74]
    )
}
# attribute index (1..30) -> GATTRIB prop_id (inverse of _GATTRIB_IDS).
_GATTRIB_PROP = {idx: pid for pid, idx in _GATTRIB_IDS.items()}


def build_player_gattrib(index: int, value: str) -> bytes:
    """Build PLI_PLAYERPROPS setting gani attribute `index` (1..30) to `value`.
    These are #P1..#P30 in GS1 — Bomber Arena's room slot lists. String prop:
    gchar(prop_id) + gchar(len) + chars."""
    pid = _GATTRIB_PROP.get(index)
    if pid is None:
        return b""
    vb = value.encode('latin-1', errors='replace')[:223]
    return bytes([pid + 32, len(vb) + 32]) + vb


def _read_string(data: bytes, pos: int):
    """Read a 1-byte-length-prefixed string. Returns (value_or_None, new_pos)."""
    n = len(data)
    if pos >= n:
        return None, pos
    str_len = data[pos] - 32
    pos += 1
    if str_len <= 0:
        return None, pos
    end = pos + str_len
    if end > n:
        return None, n
    return data[pos:end].decode('latin-1', errors='replace'), end


def _read_gbyte(data: bytes, pos: int, count: int):
    """Read a `count`-byte Reborn-packed unsigned int. Returns (value_or_None, new_pos)."""
    n = len(data)
    if pos + count > n:
        return None, n
    value = 0
    for i in range(count):
        value = (value << 7) | ((data[pos + i] - 32) & 0x7F)
    return value, pos + count


def _read_pixel(data: bytes, pos: int):
    """Read a 2-byte high-precision pixel coordinate (PropertyPixelCoordinate).
    Returns (tiles_float_or_None, new_pos)."""
    if pos + 2 > len(data):
        return None, len(data)
    value = ((data[pos] - 32) << 7) | (data[pos + 1] - 32)
    pixels = value >> 1
    if value & 0x0001:
        pixels = -pixels
    return pixels / 16.0, pos + 2


def _read_sword(data: bytes, pos: int, threshold: int):
    """Read a SWORDPOWER/SHIELDPOWER prop. `threshold` is 30 (sword) or 10 (shield):
    a raw value below it is a preset power with no image; at/above it the power is
    (raw - threshold) followed by a length-prefixed image. Returns (power, image_or_None, new_pos)."""
    if pos >= len(data):
        return 0, None, pos
    raw = data[pos] - 32
    pos += 1
    if raw < threshold:
        return raw, None, pos
    image, pos = _read_string(data, pos)
    return raw - threshold, image, pos


def _read_headgif(data: bytes, pos: int):
    """Read a HEADGIF prop. Length < 100 is a preset id (int); otherwise a custom
    image string of (length - 100) chars. Returns (value_or_None, new_pos)."""
    n = len(data)
    if pos >= n:
        return None, pos
    length = data[pos] - 32
    pos += 1
    if length < 100:
        return length, pos
    end = pos + (length - 100)
    if end > n:
        return None, n
    return data[pos:end].decode('latin-1', errors='replace'), end


def _prop_payload_len(prop_id: int, data: bytes, pos: int, colors_len: int = 5) -> int:
    """Number of payload bytes a player-prop occupies (prop-id byte already consumed).
    Used to keep the stream aligned for props the caller does not decode itself.

    colors_len is the width of PLPROP_COLORS (13): 5 for classic/v2.22 clients, 8
    for v6 clients with extended body colors. Getting this wrong misaligns every
    prop after COLORS (garbled level name, lost X/Y), so it must match the version.
    """
    if prop_id == 13:       # COLORS
        return colors_len
    fixed = _PROP_FIXED_BYTES.get(prop_id)
    if fixed is not None:
        return fixed
    if prop_id in _PROP_STRING_IDS:
        return 1 + (data[pos] - 32) if pos < len(data) else 0
    if prop_id == 8:        # SWORDPOWER
        if pos >= len(data):
            return 0
        return 1 + (1 + (data[pos + 1] - 32) if (data[pos] - 32) >= 30 and pos + 1 < len(data) else 0)
    if prop_id == 9:        # SHIELDPOWER
        if pos >= len(data):
            return 0
        return 1 + (1 + (data[pos + 1] - 32) if (data[pos] - 32) >= 10 and pos + 1 < len(data) else 0)
    if prop_id == 11:       # HEADGIF
        if pos >= len(data):
            return 0
        length = data[pos] - 32
        return 1 + ((length - 100) if length >= 100 else 0)
    if prop_id == 23:       # EFFECTCOLORS: 1 byte if first is 0, else 5
        if pos >= len(data):
            return 0
        return 1 if (data[pos] - 32) == 0 else 5
    # Unknown: advance a single byte so the loop makes progress.
    return 1


def _parse_with_colors_retry(run_once, colors_len: int,
                             diagnostics: Optional[Dict[str, int]] = None):
    """Try `colors_len`, then fall back to the other known PLPROP_COLORS
    width, keeping whichever cleanly parses the whole props stream.

    PLPROP_COLORS' wire width (5 classic / 8 new-world) is a *server-wide*
    mode switch (`Server::isNewWorldMode()`), not something derivable from
    the client's negotiated protocol version - see
    reborn-protocol-docs/docs/protocol/version-gated-behavior.md
    ("PLPROP_COLORS Width: Two Independent Switches"). A static per-version
    guess is therefore wrong against any server that doesn't happen to match
    the guess (e.g. a real GServer-v2 instance with new-world mode off,
    which always sends 5 bytes regardless of client version).

    Every prop after COLORS in getPropsPacketFromList()/getModifiedPropsPacket()
    (GServer-v2 server/src/player/PlayerProps.cpp) is written in strictly
    ascending PlayerProp-id order with no padding, so guessing the wrong
    width desyncs the rest of the stream - it either hits an out-of-range
    prop id (parse stops early, "not clean") or leaves trailing bytes
    unconsumed. Whether a given width lets the parse consume the *entire*
    packet without hitting that failure mode is therefore a reliable,
    self-correcting signal for which width the server actually used.

    `run_once(cl)` must return (props_dict, clean_bool).
    """
    candidates = [colors_len] + [c for c in (5, 8) if c != colors_len]
    fallback = None
    failed_attempts = 0
    for cl in candidates:
        props, clean = run_once(cl)
        if clean:
            if diagnostics is not None and failed_attempts:
                diagnostics['warnings'] = diagnostics.get('warnings', 0) + 1
                diagnostics['width_fallbacks'] = diagnostics.get('width_fallbacks', 0) + 1
            return props
        failed_attempts += 1
        if fallback is None:
            fallback = props
    if diagnostics is not None:
        diagnostics['errors'] = diagnostics.get('errors', 0) + 1
    return fallback if fallback is not None else {}


# =============================================================================
# Packet Parsers
# =============================================================================

def parse_npc_showimgs(data: bytes) -> dict:
    """Parse PLO_SHOWIMGNPC (166) into NPC showimg layer updates."""
    def read_gchar(position):
        if position >= len(data):
            return None, len(data)
        return data[position] - 32, position + 1

    npc_id, pos = _read_gbyte(data, 0, 3)
    result = {'npc_id': npc_id, 'clear': False, 'records': {}}
    current = None
    while pos < len(data):
        selector = data[pos] - 32
        pos += 1
        if selector == 9:
            result['clear'] = True
            current = None
            continue
        if selector >= 10:
            index = selector - 10
            current = result['records'].setdefault(index, {}) if index <= 199 else None
            continue
        if current is None:
            break
        if selector == 0:
            value, pos = _read_string(data, pos)
            if value is not None:
                current['image'] = value
        elif selector in (1, 2, 3, 6, 8):
            value, pos = read_gchar(pos)
            if value is None:
                break
            key = {1: 'x', 2: 'y', 3: 'vis', 6: 'zoom', 8: 'mode'}[selector]
            current[key] = value / 2.0 if selector in (1, 2) else (
                value / 10.0 if selector == 6 else value)
        elif selector == 4:
            enabled, pos = read_gchar(pos)
            if enabled is None:
                break
            if not enabled:
                current['part'] = None
            else:
                x, pos = _read_gbyte(data, pos, 2)
                y, pos = _read_gbyte(data, pos, 2)
                width, pos = read_gchar(pos)
                height, pos = read_gchar(pos)
                current['part'] = (x, y, width, height)
        elif selector == 5:
            values = []
            for _ in range(4):
                value, pos = read_gchar(pos)
                values.append(value)
            if None in values:
                break
            current['colors'] = tuple(value / 200.0 for value in values)
        elif selector == 7:
            value, pos = read_gchar(pos)
            if value is None:
                break
            current['z'] = value - 50
        else:
            break
    return result

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


# Reborn sign text alphabet (from GServer-v2 LevelSign.cpp `signText`). Each
# encoded sign byte is `index_into_this_string + 32`.
_SIGN_ALPHABET = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    "0123456789!?-.,#>()#####\"####':/~&### <####;\n"
)
# Button-symbol escape tables (ctab/ctabindex/signSymbols in LevelSign.cpp).
_SIGN_CTAB = [91, 92, 93, 94, 77, 78, 79, 80, 74, 75, 71, 72, 73, 86, 86, 87, 88, 67]
_SIGN_CTABINDEX = [0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 15, 17]
_SIGN_SYMBOLS = "ABXYudlrhxyz#4."


def decode_sign_text(body: bytes) -> str:
    """Decode the Reborn-encoded sign text body (after the x/y bytes).

    Mirrors LevelSign::decodeSignCode: each byte's code (byte-32) either maps to
    a button-symbol escape (#A, #B, ...) via the ctab tables or indexes the sign
    alphabet directly.
    """
    out = []
    for raw in body:
        code = raw - 32
        if code in _SIGN_CTAB:
            code_id = _SIGN_CTAB.index(code)
            if code_id in _SIGN_CTABINDEX:
                out.append('#' + _SIGN_SYMBOLS[_SIGN_CTABINDEX.index(code_id)])
                continue
        if 0 <= code < len(_SIGN_ALPHABET):
            out.append(_SIGN_ALPHABET[code])
    return ''.join(out).replace('#K(13)', '').replace('##', '#')


def parse_level_sign(data: bytes) -> dict:
    """
    Parse PLO_LEVELSIGN (packet 5) - sign/board text.
    Format: [x:GCHAR][y:GCHAR][encoded_text...]

    x/y are whole-tile coordinates. The text is Reborn sign-encoded and must be
    run through decode_sign_text to recover readable characters.
    """
    if len(data) < 2:
        return {}
    reader = PacketReader(data)
    x = reader.read_gchar()
    y = reader.read_gchar()
    return {
        'x': x,
        'y': y,
        'text': decode_sign_text(reader.remaining()),
    }


def parse_explosion(data: bytes) -> dict:
    """
    Parse PLO_EXPLOSION (packet 36) - explosion effect.
    Format: [x:GCHAR][y:GCHAR][radius:GCHAR][power:GCHAR?]

    Position values are in half-tiles. Power is optional.
    """
    if len(data) < 3:
        return {}
    reader = PacketReader(data)
    return {
        'x': reader.read_gchar() / 2.0,
        'y': reader.read_gchar() / 2.0,
        'radius': reader.read_gchar(),
        'power': reader.read_gchar() if reader.has_data() else 1
    }


def parse_hit_objects(data: bytes) -> dict:
    """
    Parse PLO_HITOBJECTS (packet 46) - relayed sword-swing hit probe.
    Format: [player_id:GSHORT][power:GCHAR][x*2:GCHAR][y*2:GCHAR][npc_id:GINT3?]

    Verified against a live gs2emu beta4 packet trace (relay of
    PLI_HITOBJECTS, e.g. body 20 23 22 5e 63 = player 3, power 1,
    x 31, y 33.5); pygserver's build_hit_objects emits the same layout.
    The old parse here read [x][y][power][id] and produced garbage.
    """
    if len(data) < 5:
        return {}
    reader = PacketReader(data)
    return {
        'player_id': reader.read_gshort(),
        'power': reader.read_gchar() / 2.0,
        'x': reader.read_gchar() / 2.0,
        'y': reader.read_gchar() / 2.0,
        'npc_id': reader.read_gint3() if reader.has_data() else None
    }


def parse_minimap(data: bytes) -> dict:
    """
    Parse PLO_MINIMAP (packet 172) - minimap data.
    Format varies by server implementation.
    """
    return {
        'data': data,
        'type': data[0] - 32 if data else 0
    }


def parse_board_layer(data: bytes) -> dict:
    """
    Parse PLO_BOARDLAYER (packet 107) - extra level layer.

    Format (Level.cpp sendBoardLayerToPlayer - note these are RAW bytes
    written with `<< (char)`, NOT gchars):
        [layer:BYTE][x:BYTE][y:BYTE][width:BYTE][height:BYTE][tiles:raw]
    x/y are always 0 and width/height always 64 in current GServer; tiles are
    width*height little-endian uint16s (same encoding as PLO_BOARDPACKET).

    An older version of this parser read only 3 gchar header fields, leaving
    the w/h bytes glued onto the tile blob (the pygame renderer carried a
    defensive workaround for that - see game/render_world.py
    _decode_board_layer_tiles).
    """
    if len(data) < 5:
        return {}
    return {
        'layer': data[0],
        'x': data[1],
        'y': data[2],
        'width': data[3],
        'height': data[4],
        'tiles': data[5:],
    }


# NPCProp string props: serialized as [gchar len][raw bytes].
# (PropertyString in GServer-v2 NPC.h FOR_LIST_OF_NPC_PROPS.)
_NPC_STRING_PROPS = frozenset({
    0,                       # IMAGE
    15,                      # MESSAGE (chat)
    20,                      # NICKNAME
    21,                      # HORSEIMAGE
    35,                      # BODYIMAGE
    49, 50, 51, 52,          # SCRIPTER, NAME, TYPE, CURLEVEL (NC-only, normally not sent)
    # GATTRIBs are NOT contiguous here: NPC.h interleaves GMAPLEVELX(41),
    # GMAPLEVELY(42) and Z(43) - all 1-byte numerics - between GATTRIB5(40)
    # and GATTRIB6(44). Treating 41-43 as strings misaligned the parser on
    # every gmap-level NPC gs2emu sends (their gchar values became bogus
    # string lengths that swallowed the rest of the packet, losing X2/Y2 and
    # filling 'script' with raw prop bytes).
    *range(36, 41),          # GATTRIB1-5   (36-40)
    *range(44, 48),          # GATTRIB6-9   (44-47)
    *range(53, 74),          # GATTRIB10-30 (53-73)
})
# NPCProp single-byte numeric props (PropertyNumeric<GBYTE1> / flags / Z-tile).
_NPC_BYTE_PROPS = frozenset({
    4,                       # POWER
    6, 7, 8, 9,              # ARROWS, BOMBS, GLOVEPOWER, BOMBPOWER
    13, 14,                  # VISFLAGS, BLOCKFLAGS
    *range(23, 34),          # SAVE0-9 (23-32), ALIGNMENT (33)
    41, 42,                  # GMAPLEVELX, GMAPLEVELY
    43,                      # Z (TileCoordinateZ, 1 byte)
})
# Friendly names for the props we surface as dict keys.
_NPC_STRING_KEYS = {0: 'image', 15: 'message', 20: 'nickname',
                    21: 'horseimage', 35: 'bodyimage', 52: 'curlevel'}


def _parse_npc_props_once(data: bytes, colors_len: int) -> tuple:
    """
    Parse PLO_NPCPROPS (packet 3) -> NPC info dict.

    Format: GInt3(npc_id) followed by [gchar prop_id][value...] pairs.
    Widths/encodings come straight from GServer-v2 NPC.h FOR_LIST_OF_NPC_PROPS
    + PropertySerializers.cpp (modern / new-world generation). Prop ids are the
    NPCProp enum, which differs from PlayerProp (e.g. 75/76/77 are X2/Y2/Z2,
    NOT OSTYPE/codepage).
    """
    if len(data) < 3:
        return {}, False

    n = len(data)
    pos = 3  # GInt3 npc id
    props = {'id': ((data[0] - 32) << 14) + ((data[1] - 32) << 7) + (data[2] - 32)}
    clean = True
    last_prop_id = -1

    def read_gstr():
        """[gchar len][raw len bytes] -> str (advances pos)."""
        nonlocal pos
        if pos >= n:
            return None
        slen = data[pos] - 32
        pos += 1
        if slen < 0:
            slen = 0
        s = data[pos:pos + slen].decode('latin-1', errors='replace')
        pos += slen
        return s

    while pos < n:
        prop_id = data[pos] - 32
        pos += 1
        if prop_id < 0 or prop_id >= 78 or prop_id <= last_prop_id:
            clean = False
            break
        last_prop_id = prop_id

        if prop_id in _NPC_STRING_PROPS:
            s = read_gstr()
            key = _NPC_STRING_KEYS.get(prop_id)
            if key:
                props[key] = s

        elif prop_id == 1:  # SCRIPT - PropertyGS1Script: gshort len + raw
            if pos + 1 >= n:
                clean = False
                break
            slen = ((data[pos] - 32) << 7) + (data[pos + 1] - 32)
            pos += 2
            props['script'] = data[pos:pos + slen].decode('latin-1', errors='replace')
            pos += slen

        elif prop_id == 2 or prop_id == 3:  # X / Y tile coordinate (1 byte)
            v = data[pos] - 32
            pos += 1
            if v >= 216:        # negative tile coordinate (signed)
                v -= 256
            props['x' if prop_id == 2 else 'y'] = v / 2.0

        elif prop_id in (75, 76, 77):  # X2 / Y2 / Z2 - PixelCoordinate (gshort)
            if pos + 1 >= n:
                clean = False
                break
            value = ((data[pos] - 32) << 7) + (data[pos + 1] - 32)
            pos += 2
            pixels = value >> 1
            if value & 1:
                pixels = -pixels
            key = {75: 'x', 76: 'y', 77: 'z'}[prop_id]
            props[key] = pixels / 16.0

        elif prop_id in _NPC_BYTE_PROPS:
            v = data[pos] - 32
            pos += 1
            if prop_id == 13:
                props['visflags'] = v
            elif prop_id == 41:
                # GMAPLEVELX: grid column of the segment this NPC lives in.
                # On a gmap, gs2emu streams ALL the map's NPCs under
                # PLO_SETACTIVELEVEL <map>.gmap (the whole gmap is one level
                # server-side), so this pair is the ONLY segment attribution
                # the client gets - see client.py's PLO_NPCPROPS handler.
                props['gmaplevelx'] = v
            elif prop_id == 42:
                props['gmaplevely'] = v

        elif prop_id == 5:  # RUPEES - GBYTE3 (also covers 17 ID below)
            pos += 3

        elif prop_id == 17:  # ID - GBYTE3
            pos += 3

        elif prop_id == 18:  # SPRITE: (sprite<<2)|direction, 1 byte
            v = data[pos] - 32
            pos += 1
            props['sprite'] = v
            props['direction'] = v & 3

        elif prop_id == 12:  # GANI (modern: gchar len + raw)
            props['gani'] = read_gstr()

        elif prop_id == 22:  # HEADIMAGE - PropertyHeadGif
            marker = data[pos] - 32
            pos += 1
            if marker >= 100:
                props['headimage'] = data[pos:pos + (marker - 100)].decode('latin-1', errors='replace')
                pos += marker - 100
            else:
                props['headimage'] = marker  # preset id

        elif prop_id == 10:  # SWORDIMAGE - PropertySwordPower
            v = data[pos] - 32
            pos += 1
            if v >= 30:
                read_gstr()  # custom image name

        elif prop_id == 11:  # SHIELDIMAGE - PropertyShieldPower
            v = data[pos] - 32
            pos += 1
            if v >= 10:
                read_gstr()

        elif prop_id == 19:  # COLORS
            if pos + colors_len > n:
                clean = False
            props['colors'] = [
                data[i] - 32 for i in range(pos, min(pos + colors_len, n))]
            pos += colors_len

        elif prop_id == 16:  # HURTDXDY - 2 bytes
            pos += 2

        elif prop_id == 34:  # IMAGEPART - PropertyImagePart: gushort x, gushort
            # y, gchar w, gchar h (6 bytes). Classic "object" NPCs set image to a
            # tilesheet (e.g. pics1.png) and use this rect to pick the sub-region
            # to draw; without it the renderer blits the whole sheet.
            if pos + 5 < n:
                px = ((data[pos] - 32) << 7) + (data[pos + 1] - 32)
                py = ((data[pos + 2] - 32) << 7) + (data[pos + 3] - 32)
                pw = data[pos + 4] - 32
                ph = data[pos + 5] - 32
                props['imagepart'] = (px, py, pw, ph)
            pos += 6

        elif prop_id == 74:  # CLASS - PropertyLongString: gshort len + raw
            if pos + 1 >= n:
                clean = False
                break
            slen = ((data[pos] - 32) << 7) + (data[pos + 1] - 32)
            pos += 2
            pos += slen

        elif prop_id == 48:  # UNKNOWN48 - PropertyVoid (0 bytes)
            pass

        else:
            # Unknown id within range: assume single byte (best-effort).
            pos += 1

        if pos > n:
            clean = False
    return props, clean and pos == n


def parse_npc_props(data: bytes, colors_len: int = 5,
                    diagnostics: Optional[Dict[str, int]] = None) -> dict:
    """Parse an NPC property stream, retrying the alternate color width."""
    return _parse_with_colors_retry(
        lambda width: _parse_npc_props_once(data, width),
        colors_len, diagnostics)


def parse_chat(data: bytes) -> tuple:
    """
    Parse PLO_TOALL (packet 13) - returns (player_id, message)
    Format: [player_id:GShort][message_length:GChar][message:raw_bytes]

    The message length is gchar-encoded (value + 32), followed by the
    full message text as raw bytes (not gchar-encoded).
    """
    if len(data) < 3:
        return (0, "")

    reader = PacketReader(data)
    player_id = reader.read_gshort()

    # Read the gchar-encoded message length
    message_length = reader.read_gchar()

    # Read exactly 'message_length' bytes as the plain message text
    message = reader.read_string(message_length)

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


def parse_other_player(data: bytes, colors_len: int = 5,
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

    def _run(colors_len):
        props = {'id': player_id}
        pos = start_pos
        clean = True
        last_prop_id = -1

        while pos < len(data):
            prop_id = data[pos] - 32
            pos += 1
            if prop_id < 0 or prop_id > 83:
                clean = False
                break
            if pos + _prop_payload_len(prop_id, data, pos, colors_len) > len(data):
                clean = False
            # Every PlayerProp stream GServer-v2 emits (getPropsPacketFromList/
            # getModifiedPropsPacket, server/src/player/PlayerProps.cpp) writes
            # prop ids in strictly ascending order, except that OTHERPLPROPS
            # join/leave notifications prepend a standalone JOINLEAVELVL(50)
            # header before the (also ascending) props blob - so a JOINLEAVELVL
            # header resets the ascending-order tracker instead of breaking it.
            # A wrong colors_len (COLORS' width is a server-wide mode, not
            # something derivable from the client's protocol version - see
            # reborn-protocol-docs/docs/protocol/version-gated-behavior.md)
            # desyncs this ordering almost immediately, which is what lets
            # _parse_with_colors_retry tell a correct parse from a corrupted one.
            if prop_id <= last_prop_id and last_prop_id != 50:
                clean = False
                break
            last_prop_id = prop_id

            if prop_id == 0:          # NICKNAME
                val, pos = _read_string(data, pos)
                if val is not None:
                    props['nickname'] = val
            elif prop_id == 8:        # SWORDPOWER
                power, image, pos = _read_sword(data, pos, 30)
                props['sword_power'] = power
                if image is not None:
                    props['sword_image'] = image
            elif prop_id == 9:        # SHIELDPOWER
                power, image, pos = _read_sword(data, pos, 10)
                props['shield_power'] = power
                if image is not None:
                    props['shield_image'] = image
            elif prop_id == 10:       # GANI
                val, pos = _read_string(data, pos)
                if val is not None:
                    props['ani'] = val
            elif prop_id == 11:       # HEADGIF
                val, pos = _read_headgif(data, pos)
                if isinstance(val, str):
                    props['head_image'] = val
            elif prop_id == 12:       # CURCHAT (chat bubble above the player)
                val, pos = _read_string(data, pos)
                # An empty CURCHAT clears the bubble; surface '' too so callers
                # can distinguish "no chat prop" (key absent) from "chat cleared".
                props['chat'] = val if val is not None else ''
            elif prop_id == 13:       # COLORS (colors_len gchar color indices)
                end = min(pos + colors_len, len(data))
                props['colors'] = [max(0, data[i] - 32) for i in range(pos, end)]
                pos = end
            elif prop_id == 15:       # X (half-tiles)
                if pos < len(data):
                    props['x'] = float(data[pos] - 32) / 2.0
                    pos += 1
            elif prop_id == 16:       # Y (half-tiles)
                if pos < len(data):
                    props['y'] = float(data[pos] - 32) / 2.0
                    pos += 1
            elif prop_id == 17:       # SPRITE (direction in lower 2 bits)
                if pos < len(data):
                    sprite = data[pos] - 32
                    props['sprite'] = sprite
                    props['direction'] = sprite & 0x03
                    pos += 1
            elif prop_id == 18:       # STATUS
                if pos < len(data):
                    props['status'] = data[pos] - 32
                    pos += 1
            elif prop_id == 20:       # CURLEVEL
                val, pos = _read_string(data, pos)
                if val is not None:
                    props['level'] = val
            elif prop_id == 26:       # MAGICPOINTS (mp, 1 gchar)
                if pos < len(data):
                    props['mp'] = data[pos] - 32
                    pos += 1
            elif prop_id == 32:       # ALIGNMENT (ap, 1 gchar)
                if pos < len(data):
                    props['ap'] = data[pos] - 32
                    pos += 1
            elif prop_id == 34:       # ACCOUNTNAME
                val, pos = _read_string(data, pos)
                if val is not None:
                    props['account'] = val
            elif prop_id == 50:       # JOINLEAVELVL (1=joined level, 0=left)
                # The server's level-leave notification IS this prop with
                # value 0 (pygserver build_player_left; GServer-v2 sends the
                # same shape). Without capturing it, departed players linger
                # forever in the client's level roster as ghosts.
                if pos < len(data):
                    props['joinleave'] = data[pos] - 32
                    pos += 1
            elif prop_id == 35:       # BODYIMG
                val, pos = _read_string(data, pos)
                if val is not None:
                    props['body_image'] = val
            elif prop_id in _GATTRIB_IDS:
                val, pos = _read_string(data, pos)
                if val is not None:
                    props[f'gattrib{_GATTRIB_IDS[prop_id]}'] = val
            elif prop_id == 75:       # OSTYPE
                val, pos = _read_string(data, pos)
                if val is not None:
                    props['os_type'] = val
            elif prop_id == 76:       # TEXTCODEPAGE (gbyte3)
                val, pos = _read_gbyte(data, pos, 3)
                if val is not None:
                    props['codepage'] = val
            elif prop_id == 78:       # X2 (high-precision X)
                val, pos = _read_pixel(data, pos)
                if val is not None:
                    props['x'] = val
            elif prop_id == 79:       # Y2 (high-precision Y)
                val, pos = _read_pixel(data, pos)
                if val is not None:
                    props['y'] = val
            else:
                # Everything else (incl. COLORS/EFFECTCOLORS/CARRYNPC/numeric stats):
                # consume the correct number of bytes to keep the stream aligned.
                pos += _prop_payload_len(prop_id, data, pos, colors_len)

        return props, clean

    return _parse_with_colors_retry(_run, colors_len, diagnostics)


# LevelItemType id -> name (from GServer-v2 LevelItem.h enum order).
LEVEL_ITEM_NAMES = {
    0: 'greenrupee', 1: 'bluerupee', 2: 'redrupee', 3: 'bombs', 4: 'darts',
    5: 'heart', 6: 'glove1', 7: 'bow', 8: 'bomb', 9: 'shield', 10: 'sword',
    11: 'fullheart', 12: 'superbomb', 13: 'battleaxe', 14: 'goldensword',
    15: 'mirrorshield', 16: 'glove2', 17: 'lizardshield', 18: 'lizardsword',
    19: 'goldrupee', 20: 'fireball', 21: 'fireblast', 22: 'nukeshot',
    23: 'joltbomb', 24: 'spinattack',
}


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


def parse_player_props(data: bytes, colors_len: int = 5,
                       diagnostics: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """
    Parse PLO_PLAYERPROPS (packet 9) - returns dict of properties.
    Simplified parser that extracts essential properties only.

    colors_len: preferred byte width of PLPROP_COLORS (5 classic / 8 v6
    extended) to try first. Wrong value misaligns everything after COLORS,
    so if this guess doesn't let the rest of the packet parse cleanly, the
    other known width is tried instead (see _parse_with_colors_retry).
    """
    def _run(colors_len):
        props = {}
        pos = 0
        clean = True
        last_prop_id = -1

        while pos < len(data):
            prop_id = data[pos] - 32
            pos += 1
            if prop_id < 0 or prop_id > 83:
                clean = False
                break
            if pos + _prop_payload_len(prop_id, data, pos, colors_len) > len(data):
                clean = False
            # See the matching comment in parse_other_player: GServer-v2 always
            # emits prop ids in ascending order, so this catches the desync a
            # wrong colors_len guess causes and lets _parse_with_colors_retry
            # self-correct. Self-props packets have no JOINLEAVELVL header, but
            # the same exemption is harmless here (id 50 never legitimately
            # repeats within a single PLO_PLAYERPROPS packet).
            if prop_id <= last_prop_id and last_prop_id != 50:
                clean = False
                break
            last_prop_id = prop_id

            if prop_id == 0:          # NICKNAME
                val, pos = _read_string(data, pos)
                if val is not None:
                    props['nickname'] = val
            elif prop_id == 1:        # MAXPOWER (FULL hearts, not halves!)
                # Unlike CURPOWER, MAXPOWER is sent in whole hearts:
                # GServer-v2 PlayerProps.cpp:171-186 stores it straight into
                # account.maxHitpoints (hitpointsInHalves = value * 2), and
                # LevelItem.cpp:148-151 sends a fullheart pickup as
                # `>> MAXPOWER >> heartMax >> CURPOWER >> (heartMax * 2)`.
                # Decoding /2.0 here halved max hearts against the real server
                # (account MAXHP 6 rendered as 3.0).
                if pos < len(data):
                    props['max_hearts'] = float(data[pos] - 32)
                    pos += 1
            elif prop_id == 2:        # CURPOWER (halves)
                if pos < len(data):
                    props['hearts'] = (data[pos] - 32) / 2.0
                    pos += 1
            elif prop_id == 3:        # RUPEESCOUNT (gbyte3)
                val, pos = _read_gbyte(data, pos, 3)
                if val is not None:
                    props['rupees'] = val
            elif prop_id == 4:        # ARROWSCOUNT
                if pos < len(data):
                    props['arrows'] = data[pos] - 32
                    pos += 1
            elif prop_id == 5:        # BOMBSCOUNT
                if pos < len(data):
                    props['bombs'] = data[pos] - 32
                    pos += 1
            elif prop_id == 6:        # GLOVEPOWER
                if pos < len(data):
                    props['glove_power'] = data[pos] - 32
                    pos += 1
            elif prop_id == 7:        # BOMBPOWER
                if pos < len(data):
                    props['bomb_power'] = data[pos] - 32
                    pos += 1
            elif prop_id == 8:        # SWORDPOWER
                power, image, pos = _read_sword(data, pos, 30)
                props['sword_power'] = power
                if image is not None:
                    props['sword_image'] = image
            elif prop_id == 9:        # SHIELDPOWER
                power, image, pos = _read_sword(data, pos, 10)
                props['shield_power'] = power
                if image is not None:
                    props['shield_image'] = image
            elif prop_id == 10:       # GANI
                val, pos = _read_string(data, pos)
                if val is not None:
                    props['animation'] = val
            elif prop_id == 11:       # HEADGIF
                val, pos = _read_headgif(data, pos)
                if isinstance(val, str):
                    props['head_image'] = val
            elif prop_id == 12:       # CURCHAT
                val, pos = _read_string(data, pos)
                if val is not None:
                    props['chat'] = val
            elif prop_id == 13:       # COLORS (colors_len gchar color indices)
                if pos + colors_len > len(data):
                    clean = False
                end = min(pos + colors_len, len(data))
                props['colors'] = [max(0, data[i] - 32) for i in range(pos, end)]
                pos = end
            elif prop_id == 14:       # ID
                val, pos = _read_gbyte(data, pos, 2)
                if val is not None:
                    props['id'] = val
            elif prop_id == 15:       # X (half-tiles)
                if pos < len(data):
                    props['x'] = (data[pos] - 32) / 2.0
                    pos += 1
            elif prop_id == 16:       # Y (half-tiles)
                if pos < len(data):
                    props['y'] = (data[pos] - 32) / 2.0
                    pos += 1
            elif prop_id == 17:       # SPRITE (direction in lower 2 bits)
                if pos < len(data):
                    sprite = data[pos] - 32
                    props['sprite'] = sprite
                    props['direction'] = sprite & 0x03
                    pos += 1
            elif prop_id == 18:       # STATUS
                if pos < len(data):
                    props['status'] = data[pos] - 32
                    pos += 1
            elif prop_id == 19:       # CARRYSPRITE
                if pos < len(data):
                    props['carry_sprite'] = data[pos] - 32
                    pos += 1
            elif prop_id == 20:       # CURLEVEL
                val, pos = _read_string(data, pos)
                if val is not None:
                    props['level'] = val
            elif prop_id == 21:       # HORSEGIF
                val, pos = _read_string(data, pos)
                if val is not None:
                    props['horse_image'] = val
            elif prop_id == 22:       # HORSEBUSHES
                if pos < len(data):
                    props['horse_bushes'] = data[pos] - 32
                    pos += 1
            elif prop_id == 24:       # CARRYNPC (gbyte3)
                val, pos = _read_gbyte(data, pos, 3)
                if val is not None:
                    props['carry_npc'] = val
            elif prop_id == 26:       # MAGICPOINTS (mp, 1 gchar)
                if pos < len(data):
                    props['mp'] = data[pos] - 32
                    pos += 1
            elif prop_id == 32:       # ALIGNMENT (ap, 1 gchar)
                if pos < len(data):
                    props['ap'] = data[pos] - 32
                    pos += 1
            elif prop_id == 34:       # ACCOUNTNAME
                val, pos = _read_string(data, pos)
                if val is not None and 'account' not in props:
                    props['account'] = val
            elif prop_id == 35:       # BODYIMG
                val, pos = _read_string(data, pos)
                if val is not None:
                    props['body_image'] = val
            elif prop_id in _GATTRIB_IDS:
                val, pos = _read_string(data, pos)
                if val is not None:
                    props[f'gattrib{_GATTRIB_IDS[prop_id]}'] = val
            elif prop_id == 78:       # X2 (high-precision X)
                val, pos = _read_pixel(data, pos)
                if val is not None:
                    props['x'] = val
            elif prop_id == 79:       # Y2 (high-precision Y)
                val, pos = _read_pixel(data, pos)
                if val is not None:
                    props['y'] = val
            else:
                # Everything else (COLORS/EFFECTCOLORS/numeric stats/OSTYPE/etc.):
                # consume the correct number of bytes to keep the stream aligned.
                pos += _prop_payload_len(prop_id, data, pos, colors_len)

        if pos > len(data):
            clean = False
        return props, clean

    return _parse_with_colors_retry(_run, colors_len, diagnostics)


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

    # PLPROP_SPRITE (17) - direction (see build_animation: prop 14/ID is
    # 2 bytes and misaligns the server parser if sent with 1 byte).
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

        # BDPROP_POWERIMAGE (4) - power byte + length-prefixed image string
        # (GServer-v2 BaddyProp::POWERIMAGE getProp).
        elif prop_id == 4:
            if pos < len(data):
                props['power'] = data[pos] - 32
                pos += 1
                if pos < len(data):
                    str_len = data[pos] - 32
                    pos += 1
                    if str_len > 0 and pos + str_len <= len(data):
                        props['image'] = data[pos:pos + str_len].decode('latin-1', errors='replace')
                    pos += max(0, str_len)

        # BDPROP_MODE (5) - 1 byte
        elif prop_id == 5:
            if pos < len(data):
                props['mode'] = data[pos] - 32
                pos += 1

        # BDPROP_ANI (6) - 1 byte animation index
        elif prop_id == 6:
            if pos < len(data):
                props['animation'] = data[pos] - 32
                pos += 1

        # BDPROP_DIR (7) - 1 byte (headDir << 2 | direction)
        elif prop_id == 7:
            if pos < len(data):
                props['direction'] = (data[pos] - 32) & 0x03
                pos += 1

        # BDPROP_VERSESIGHT/HURT/ATTACK (8/9/10) - length-prefixed strings
        elif prop_id in (8, 9, 10):
            if pos < len(data):
                str_len = data[pos] - 32
                pos += 1
                if str_len > 0 and pos + str_len <= len(data):
                    key = {8: 'verse_sight', 9: 'verse_hurt', 10: 'verse_attack'}[prop_id]
                    props[key] = data[pos:pos + str_len].decode('latin-1', errors='replace')
                pos += max(0, str_len)

        # Default: single byte
        else:
            if pos < len(data):
                pos += 1

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

    Server layout: gshort(player_id) then getPropsForRCPacket()
    (PlayerProps.cpp Player::getPropsForRCPacket):
      gstring(account) gstring(worldName) gstring_short? -> actually
      gstring(props_blob) gshort(flag_count)[gstring(flag)]*
      gshort(chest_count)[gchar(len) gchar(x) gchar(y) str(level)]*
      gchar(weapon_count)[gstring(weapon)]*
    The embedded props_blob is a standard player-props packet.
    """
    if len(data) < 2:
        return {}

    reader = PacketReader(data)
    player_id = reader.read_gshort()
    account = reader.read_gstring()
    world = reader.read_gstring()

    props_blob = reader.read_gstring()  # gchar-length-prefixed props packet
    props = parse_player_props(props_blob.encode('latin-1')) if props_blob else {}

    flags = []
    if reader.has_data():
        flag_count = reader.read_gshort()
        for _ in range(flag_count):
            if not reader.has_data():
                break
            flags.append(reader.read_gstring())

    chests = []
    if reader.has_data():
        chest_count = reader.read_gshort()
        for _ in range(chest_count):
            if not reader.has_data():
                break
            entry_len = reader.read_gchar()      # level length + 2
            x = reader.read_gchar()
            y = reader.read_gchar()
            level = reader.read_string(max(0, entry_len - 2))
            chests.append({'x': x, 'y': y, 'level': level})

    weapons = []
    if reader.has_data():
        weapon_count = reader.read_gchar()
        for _ in range(weapon_count):
            if not reader.has_data():
                break
            weapons.append(reader.read_gstring())

    return {
        'player_id': player_id,
        'account': account,
        'world': world,
        'props': props,
        'flags': flags,
        'chests': chests,
        'weapons': weapons,
    }


def parse_rc_max_upload_size(data: bytes) -> int:
    """PLO_RC_MAXUPLOADFILESIZE (103): gint5 max upload size in bytes."""
    if len(data) < 5:
        return 0
    return PacketReader(data).read_gint5()


# PLO_ADDPLAYER prop tail (GServer-v2 Player.cpp): propid -> field/width.
_ADDPLAYER_STR_PROPS = {0: 'nickname', 20: 'level', 34: 'account', 82: 'community'}
_ADDPLAYER_BYTE_PROPS = {53: 'status', 81: 'category'}


def parse_rc_add_player(data: bytes) -> dict:
    """
    Parse PLO_ADDPLAYER (55) - a player-list entry (used both by RC and by the
    client's global online-player list).

    Layout (Player.cpp): gshort(id) gchar(namelen) name, then a stream of
    ``gchar(propid) <serialized>`` pairs — CURLEVEL/PLAYERLISTSTATUS/NICKNAME/
    COMMUNITYNAME for client lists. We decode the id + account plus the known
    props; an unrecognised propid (unknown width) stops the scan rather than
    misaligning.
    """
    if len(data) < 3:
        return {}
    reader = PacketReader(data)
    pid = reader.read_gshort()
    account = reader.read_gstring()
    out = {'id': pid, 'account': account}
    while reader.has_data():
        prop = reader.read_gchar()
        if prop in _ADDPLAYER_STR_PROPS:
            out[_ADDPLAYER_STR_PROPS[prop]] = reader.read_gstring()
        elif prop in _ADDPLAYER_BYTE_PROPS:
            out[_ADDPLAYER_BYTE_PROPS[prop]] = reader.read_gchar()
        else:
            break
    return out


def parse_rc_del_player(data: bytes) -> int:
    """Parse PLO_DELPLAYER (56) - returns the removed player id (gshort)."""
    if len(data) < 2:
        return 0
    return PacketReader(data).read_gshort()


def parse_rc_account_list(data: bytes) -> dict:
    """
    Parse PLO_RC_ACCOUNTLISTGET (packet 70) - Account list response.

    Server layout (PlayerRCPackets.cpp msgPLI_RC_ACCOUNTLISTGET): a sequence of
    length-prefixed account names, ``[gchar(len)][name]`` repeated. NOT
    newline-separated (the old parser produced one mashed string).
    """
    reader = PacketReader(data)
    accounts = []
    while reader.has_data():
        name = reader.read_gstring()
        if name:
            accounts.append(name)
    return {'accounts': accounts}


def parse_rc_account_get(data: bytes) -> dict:
    """
    Parse PLO_RC_ACCOUNTGET (packet 73) - Account details response.

    Server layout (PlayerRCPackets.cpp msgPLI_RC_ACCOUNTGET):
      gstring(name) gstring(password, always empty) gstring(email)
      gchar(banned) gchar(loadOnly) gchar(adminlevel)
      gstring(folders, e.g. "main") gstring(banLength) gstring(banReason)
    """
    if len(data) < 1:
        return {}

    reader = PacketReader(data)
    name = reader.read_gstring()
    password = reader.read_gstring() if reader.has_data() else ''
    email = reader.read_gstring() if reader.has_data() else ''
    banned = (reader.read_gchar() == 1) if reader.has_data() else False
    load_only = (reader.read_gchar() == 1) if reader.has_data() else False
    admin_level = reader.read_gchar() if reader.has_data() else 0
    folders = reader.read_gstring() if reader.has_data() else ''
    ban_length = reader.read_gstring() if reader.has_data() else ''
    ban_reason = reader.read_gstring() if reader.has_data() else ''

    return {
        'name': name,
        'password': password,
        'email': email,
        'banned': banned,
        'load_only': load_only,
        'admin_level': admin_level,
        'folders': folders,
        'ban_length': ban_length,
        'ban_reason': ban_reason,
    }


def parse_rc_player_rights(data: bytes) -> dict:
    """
    Parse PLO_RC_PLAYERRIGHTSGET (packet 62) - Player rights response.

    Server layout (PlayerRCPackets.cpp msgPLI_RC_PLAYERRIGHTSGET):
      gstring(name) gint5(adminRights) gstring(adminIp) gstring_short(folders CSV)
    """
    if len(data) < 1:
        return {}

    reader = PacketReader(data)
    name = reader.read_gstring()
    admin_rights = reader.read_gint5() if reader.has_data() else 0
    admin_ip = reader.read_gstring() if reader.has_data() else ''
    folders = reader.read_gstring_short() if reader.has_data() else ''

    return {
        'name': name,
        'admin_rights': admin_rights,
        'admin_ip': admin_ip,
        'folders': _parse_reborn_csv(folders) if folders else [],
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

    Server sends ``string::toCSV(serveroptions.txt lines)`` - a quoted CSV where
    each element is one ``key=value`` (or comment/blank) line of the config file.
    """
    text = data.decode('latin-1', errors='replace')
    lines = _parse_reborn_csv(text)
    options = {}
    for line in lines:
        if '=' in line:
            key, value = line.split('=', 1)
            options[key.strip()] = value.strip()
    return {'options': options, 'lines': lines}


def parse_rc_folder_config(data: bytes) -> dict:
    """
    Parse PLO_RC_FOLDERCONFIGGET (packet 77) - Folder config response.

    Server sends ``string::toCSV(foldersconfig.txt lines)``; each element is one
    ``rights folder/path`` line (e.g. ``rw world/*``).
    """
    text = data.decode('latin-1', errors='replace')
    return {'lines': _parse_reborn_csv(text)}


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


def parse_file(data: bytes, no_modtime: bool = False) -> dict:
    """
    Parse PLO_FILE (packet 102) - File transfer packet.

    Format (version >= 2.1):
        modTime (5 bytes GCHAR5) + filename_length (1 byte GCHAR) + filename + file_data
    Clients older than 2.1 receive it WITHOUT the modTime header
    (Player.cpp sendFile) - pass no_modtime=True for those versions.

    Note: GCHAR values have 32 added to them for encoding.

    Returns dict with:
        - mod_time: int - file modification time
        - filename: str - name of the file
        - data: bytes - file contents
    """
    min_len = 2 if no_modtime else 7
    if len(data) < min_len:
        return {'mod_time': 0, 'filename': '', 'data': b''}

    pos = 0

    # Read modification time (GINT5: five 7-bit groups, each byte offset by
    # 32 - Player.cpp sendFile writes it with `>> (long long)modTime` =
    # CString::writeGInt5). A previous version of this decoder shifted by 8
    # bits per byte, producing garbage modtimes. Skipped for pre-2.1 clients.
    mod_time = 0
    if not no_modtime:
        for i in range(5):
            if pos < len(data):
                byte_val = max(0, data[pos] - 32)  # GCHAR decode
                mod_time = (mod_time << 7) | byte_val
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

    # Rest is the file data. The server appends one framing '\n' after the file
    # bytes, but the protocol raw-data layer (PLO_RAWDATA) already strips that
    # trailing newline before handing the body here. Stripping again would
    # truncate any file whose real last byte is 0x0A (corrupts binary files and
    # drops the final newline of text/level files).
    file_data = data[pos:]

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


# =============================================================================
# Misc server packets
#
# Wire layouts confirmed against GServer-v2 4.0 source + GS_PKTLOG trace.
# String payloads are RAW ascii (no length prefix, no +32 offset); numeric
# payloads are gchar/gint encoded (value + 32 per byte). The framing layer has
# already stripped the leading id byte and trailing newline.
# =============================================================================

def _parse_reborn_csv(text: str) -> list:
    """Parse a Reborn/quoted CSV row (toCSV format).

    Fields are comma-separated; a field may be wrapped in double quotes, inside
    which a literal quote is doubled ("").  Used by STAFFGUILDS and RPGWINDOW.
    """
    out, field, i, n, in_quotes = [], [], 0, len(text), False
    while i < n:
        ch = text[i]
        if in_quotes:
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field.append('"')
                    i += 1
                else:
                    in_quotes = False
            else:
                field.append(ch)
        else:
            if ch == '"':
                in_quotes = True
            elif ch == ',':
                out.append(''.join(field))
                field = []
            else:
                field.append(ch)
        i += 1
    out.append(''.join(field))
    return out


def parse_signature(data: bytes) -> int:
    """PLO_SIGNATURE (25): one gchar server signature/version (73 = stock)."""
    return (data[0] - 32) if data else 0


def parse_default_weapon(data: bytes) -> int:
    """PLO_DEFAULTWEAPON (43): one gchar default-weapon enum id."""
    return (data[0] - 32) if data else 0


def parse_ghost_icon(data: bytes) -> bool:
    """PLO_GHOSTICON (174): one gchar, 1 = show ghost icon."""
    return bool(data and (data[0] - 32))


def parse_level_modtime(data: bytes) -> int:
    """PLO_LEVELMODTIME (39): gint5 unix mod-time of the active level."""
    if len(data) < 5:
        return 0
    return PacketReader(data).read_gint5()


def parse_set_active_level(data: bytes) -> str:
    """PLO_SETACTIVELEVEL (156): raw level name. Routes subsequent
    chest/baddy/npc/board packets to this level."""
    return data.decode('latin-1', errors='replace')


def parse_flag_set(data: bytes) -> tuple:
    """PLO_FLAGSET (28): raw 'name' or 'name=value' server flag."""
    text = data.decode('latin-1', errors='replace')
    name, sep, value = text.partition('=')
    return name, (value if sep else '')


def parse_npcweapondel(data: bytes) -> str:
    """PLO_NPCWEAPONDEL (34): raw weapon name to remove from inventory."""
    return data.decode('latin-1', errors='replace')


def parse_start_message(data: bytes) -> str:
    """PLO_STARTMESSAGE (41): raw server MOTD (often HTML)."""
    return data.decode('latin-1', errors='replace')


def parse_fullstop(data: bytes) -> bool:
    """Parse packet 176 or 177 as a one-way input stop command.

    The C# server sends packet 176 with an empty payload (Player.cpp:696), and
    its protocol enum defines both packet ids as blank stop commands
    (IEnums.h:292-293). There is no payload toggle or matching resume packet;
    a new connection clears the state.
    """
    return True


def parse_fullstop2(data: bytes) -> bool:
    """Parse packet 177, which has the same blank one-way semantics."""
    return parse_fullstop(data)


def parse_server_text(data: bytes) -> str:
    """PLO_SERVERTEXT (82): raw text; answer to PLI_REQUESTTEXT/SENDTEXT."""
    return data.decode('latin-1', errors='replace')


def parse_staff_guilds(data: bytes) -> list:
    """PLO_STAFFGUILDS (47): quoted-CSV list of staff guild names."""
    return _parse_reborn_csv(data.decode('latin-1', errors='replace'))


def parse_status_list(data: bytes) -> list:
    """PLO_STATUSLIST (180): plain comma-separated player-status labels."""
    text = data.decode('latin-1', errors='replace')
    return text.split(',') if text else []


def parse_rpg_window(data: bytes) -> list:
    """PLO_RPGWINDOW (179): quoted-CSV text lines for an RPG-style window."""
    return _parse_reborn_csv(data.decode('latin-1', errors='replace'))


def parse_baddy_hurt(data: bytes) -> dict:
    """PLO_BADDYHURT (27): relayed from PLI_BADDYHURT, forwarded to the level
    leader.

    Wire format (GServer-v2 msgPLI_BADDYHURT, PlayerClientPackets.cpp:523-539,
    commit e0cd07af9bb4be09c54c0335f222dd0eacb71c1): [GUChar baddyId][GChar
    hurtDX][GChar hurtDY][GUChar damage, half-hearts]. hurtDX/hurtDY use the
    "midpoint: 64" gchar idiom - value = read_gchar() - 64 (mirrors
    build_baddy_hurt above and pygserver player.py:_handle_baddy_hurt, which
    decode the same way).
    """
    reader = PacketReader(data)
    baddy_id = reader.read_gchar() if reader.has_data() else 0
    hurt_dx = (reader.read_gchar() - 64) if reader.has_data() else 0
    hurt_dy = (reader.read_gchar() - 64) if reader.has_data() else 0
    power = reader.read_gchar() if reader.has_data() else 0
    return {'baddy_id': baddy_id, 'power': power,
            'knockback_x': hurt_dx, 'knockback_y': hurt_dy}


# =============================================================================
# NC (NPC Control) packets
#
# NC is the npc-control connection (PLTYPE_NC, ENCRYPT_GEN_2). Wire formats are
# taken from the server build code:
#   server/src/player/packets/PlayerNCPackets.cpp  (PLI handlers / PLO replies)
#   dependencies/gs2lib/include/IEnums.h           (ids + layout comments)
# NPC ids are gint3 (CString writeGInt = 3 bytes); coords are gchar(tiles*2);
# trailing scripts/levels/flags are raw strings read to end-of-packet.
# =============================================================================


def _gint3(value: int) -> bytes:
    """Encode a 3-byte GInt (matches CString::writeGInt / readGUInt)."""
    return bytes((
        ((value >> 14) & 0x7F) + 32,
        ((value >> 7) & 0x7F) + 32,
        (value & 0x7F) + 32,
    ))


def _raw(text: str) -> bytes:
    return text.encode('latin-1', errors='replace')


def _gtokenize(text: str) -> str:
    """Encode a multi-line string the way CString::gtokenize does.

    Each line becomes one comma-separated token; tokens that start with a quote,
    are blank/whitespace, or contain a non-printable / ',' / '/' char are wrapped
    in double quotes with internal backslash and quote doubled. The server
    reverses this with guntokenize(). Crucially this removes raw newlines, which
    would otherwise split the packet under the bundle's newline framing.
    """
    if not text.endswith('\n'):
        text = text + '\n'
    tokens = []
    for line in text.split('\n')[:-1]:
        line = line.replace('\r', '')
        if line == '':
            tokens.append('')
            continue
        complex_ = (line[0] == '"' or line.strip() == '' or
                    any(ord(c) < 33 or ord(c) > 126 or c == ',' or c == '/'
                        for c in line))
        if complex_:
            esc = line.replace('\\', '\\\\').replace('"', '""')
            tokens.append('"' + esc + '"')
        else:
            tokens.append(line)
    return ','.join(tokens)


# ---- PLI builders (client -> server) ----------------------------------------

def build_nc_npcget(npc_id: Optional[int] = None) -> bytes:
    """PLI_NC_NPCGET (103): {INT id}. Empty body is a server ping/poll."""
    return b"" if npc_id is None else _gint3(npc_id)


def build_nc_npcdelete(npc_id: int) -> bytes:
    """PLI_NC_NPCDELETE (104): {INT id}."""
    return _gint3(npc_id)


def build_nc_npcreset(npc_id: int) -> bytes:
    """PLI_NC_NPCRESET (105): {INT id}."""
    return _gint3(npc_id)


def build_nc_npcscriptget(npc_id: int) -> bytes:
    """PLI_NC_NPCSCRIPTGET (106): {INT id}."""
    return _gint3(npc_id)


def build_nc_npcwarp(npc_id: int, x: float, y: float, level: str) -> bytes:
    """PLI_NC_NPCWARP (107): {INT id}{CHAR x*2}{CHAR y*2}{level}."""
    out = bytearray(_gint3(npc_id))
    out.append((int(round(x * 2)) & 0xFF) + 32)
    out.append((int(round(y * 2)) & 0xFF) + 32)
    out.extend(_raw(level))
    return bytes(out)


def build_nc_npcflagsget(npc_id: int) -> bytes:
    """PLI_NC_NPCFLAGSGET (108): {INT id}."""
    return _gint3(npc_id)


def build_nc_npcscriptset(npc_id: int, script: str) -> bytes:
    """PLI_NC_NPCSCRIPTSET (109): {INT id}{GSTRING script}.

    The script is gtokenized (the server calls guntokenize on it). This also
    encodes any newlines so they don't split the packet under newline framing.
    """
    return _gint3(npc_id) + _raw(_gtokenize(script))


def build_nc_npcflagsset(npc_id: int, flags: str) -> bytes:
    """PLI_NC_NPCFLAGSSET (110): {INT id}{GSTRING flags} (CSV key=value list)."""
    return _gint3(npc_id) + _raw(flags)


def build_nc_npcadd(info: str) -> bytes:
    """PLI_NC_NPCADD (111): {GSTRING info} = CSV name,id,type,scripter,level,x,y."""
    return _raw(info)


def build_nc_classedit(class_name: str) -> bytes:
    """PLI_NC_CLASSEDIT (112): {class}."""
    return _raw(class_name)


def build_nc_classadd(class_name: str, script: str) -> bytes:
    """PLI_NC_CLASSADD (113): {CHAR name length}{name}{GSTRING script}.

    The script is gtokenized (server reverses it with fromCSV + join "\\n").
    """
    name = _raw(class_name)
    return bytes([(len(name) + 32) & 0xFF]) + name + _raw(_gtokenize(script))


def build_nc_localnpcsget(level: str) -> bytes:
    """PLI_NC_LOCALNPCSGET (114): {level}."""
    return _raw(level)


def build_nc_weaponlistget() -> bytes:
    """PLI_NC_WEAPONLISTGET (115): no body."""
    return b""


def build_nc_weaponget(weapon: str) -> bytes:
    """PLI_NC_WEAPONGET (116): {weapon}."""
    return _raw(weapon)


def build_nc_weaponadd(weapon: str, image: str, code: str) -> bytes:
    """PLI_NC_WEAPONADD (117): {CHAR wlen}{weapon}{CHAR ilen}{image}{code}.

    Newlines in the code are sent as 0xA7 (the server replaces 0xA7 -> '\\n');
    this also keeps raw newlines out of the newline-framed bundle.
    """
    w = _raw(weapon)
    img = _raw(image)
    out = bytearray([(len(w) + 32) & 0xFF])
    out.extend(w)
    out.append((len(img) + 32) & 0xFF)
    out.extend(img)
    out.extend(_raw(code.replace('\n', '\xa7')))
    return bytes(out)


def build_nc_weapondelete(weapon: str) -> bytes:
    """PLI_NC_WEAPONDELETE (118): {weapon}."""
    return _raw(weapon)


def build_nc_classdelete(class_name: str) -> bytes:
    """PLI_NC_CLASSDELETE (119): {class}."""
    return _raw(class_name)


def build_nc_levellistget() -> bytes:
    """PLI_NC_LEVELLISTGET (150): no body."""
    return b""


# ---- PLO parsers (server -> client) -----------------------------------------

def parse_nc_weapon_list(data: bytes) -> list:
    """PLO_NC_WEAPONLISTGET (167): sequence of [CHAR len][name] weapon names."""
    names = []
    reader = PacketReader(data)
    while reader.has_data():
        name = reader.read_gstring()
        if name == "" and not reader.has_data():
            break
        names.append(name)
    return names


def parse_nc_level_list(data: bytes) -> list:
    """PLO_NC_LEVELLIST (80): {GSTRING levels}, reborn-tokenized (toCSV-style)."""
    text = data.decode('latin-1', errors='replace')
    return [lvl for lvl in _parse_reborn_csv(text) if lvl]


def parse_nc_level_dump(data: bytes) -> str:
    """PLO_NC_LEVELDUMP (164): reborn-tokenized variable dump for a level.

    The body is one toCSV row whose joined fields reconstruct the multi-line
    dump; returned as the decoded text for inspection.
    """
    text = data.decode('latin-1', errors='replace')
    return "\n".join(_parse_reborn_csv(text))


def parse_nc_weapon_get(data: bytes) -> dict:
    """PLO_NC_WEAPONGET (192): {CHAR nlen}{name}{CHAR ilen}{image}{script}.

    (NC >= 2.1 reply; older clients get PLO_NPCWEAPONADD instead.)
    """
    reader = PacketReader(data)
    name = reader.read_gstring()
    image = reader.read_gstring()
    script = reader.remaining().decode('latin-1', errors='replace')
    # Server replaces newlines with 0xA7 on the wire; restore them.
    script = script.replace('\xa7', '\n')
    return {'name': name, 'image': image, 'script': script}


# ---- NC NPC / class management replies (require a running npc-server) --------

def parse_nc_npc_attributes(data: bytes) -> list:
    """PLO_NC_NPCATTRIBUTES (157): toCSV variable dump for one database NPC."""
    return _parse_reborn_csv(data.decode('latin-1', errors='replace'))


def parse_nc_npc_add(data: bytes) -> dict:
    """PLO_NC_NPCADD (158): {INT id} then [gchar propid][gchar len][string]*.

    Props: 50=NAME, 51=TYPE, 52=CURLEVEL (NPCProp ids, gchar-encoded).
    """
    reader = PacketReader(data)
    npc_id = reader.read_gint3()
    fields = {'id': npc_id, 'name': '', 'type': '', 'level': ''}
    prop_map = {50: 'name', 51: 'type', 52: 'level'}
    while reader.has_data():
        prop_id = reader.read_gchar()
        value = reader.read_gstring()
        key = prop_map.get(prop_id)
        if key:
            fields[key] = value
    return fields


def parse_nc_npc_delete(data: bytes) -> int:
    """PLO_NC_NPCDELETE (159): {INT id}."""
    return PacketReader(data).read_gint3()


def parse_nc_npc_script(data: bytes) -> dict:
    """PLO_NC_NPCSCRIPT (160): {INT id}{toCSV(script, "\\n")}."""
    reader = PacketReader(data)
    npc_id = reader.read_gint3()
    script = "\n".join(_parse_reborn_csv(
        reader.remaining().decode('latin-1', errors='replace')))
    return {'id': npc_id, 'script': script}


def parse_nc_npc_flags(data: bytes) -> dict:
    """PLO_NC_NPCFLAGS (161): {INT id}{toCSV(flag list)}."""
    reader = PacketReader(data)
    npc_id = reader.read_gint3()
    text = reader.remaining().decode('latin-1', errors='replace')
    flags = [f for f in _parse_reborn_csv(text) if f] if text else []
    return {'id': npc_id, 'flags': flags}


def parse_nc_class_get(data: bytes) -> dict:
    """PLO_NC_CLASSGET (162): {CHAR name length}{name}{toCSV(script)}."""
    reader = PacketReader(data)
    name = reader.read_gstring()
    script = "\n".join(_parse_reborn_csv(
        reader.remaining().decode('latin-1', errors='replace')))
    return {'name': name, 'script': script}


def parse_nc_class_add(data: bytes) -> str:
    """PLO_NC_CLASSADD (163): {class} - the class name (raw)."""
    return data.decode('latin-1', errors='replace')


def parse_nc_class_delete(data: bytes) -> str:
    """PLO_NC_CLASSDELETE (188): {class} - the class name (raw)."""
    return data.decode('latin-1', errors='replace')


def parse_bigmap(data: bytes) -> dict:
    """PLO_BIGMAP (171): "<imgfile>,<levelsfile>,<x>,<y>" minimap/bigmap config.

    Sent on entering a gmap/bigmap world (and via the GS1 setmap command).
    """
    parts = data.decode('latin-1', errors='replace').split(',')
    parts += [''] * (4 - len(parts))
    def _num(v):
        try:
            return float(v)
        except ValueError:
            return 0.0
    return {'image': parts[0].strip(), 'levels_file': parts[1].strip(),
            'x': _num(parts[2]), 'y': _num(parts[3])}


# =============================================================================
# Board modify / large files / board heights (protocol parity tier 1)
# =============================================================================

def parse_board_modify(data: bytes) -> dict:
    """
    Parse PLO_BOARDMODIFY (7) - single-level tile-delta.

    Wire format (server/src/level/LevelBoardChange.cpp getPropsForSingleLevel,
    server/src/player/packets/PlayerClientPackets.cpp msgPLI_BOARDMODIFY relay):
        {GCHAR x}{GCHAR y}{GCHAR width}{GCHAR height}{GSHORT tile}*(width*height)
    or, for a non-zero board layer:
        {GCHAR layer+64}{GCHAR x}{GCHAR y}{GCHAR width}{GCHAR height}{GSHORT tile}*...

    A first gchar value >= 64 indicates the layer-prefixed form (layer = v-64).
    """
    reader = PacketReader(data)
    layer = 0
    first = reader.read_gchar()
    if first >= 64:
        layer = first - 64
        x = reader.read_gchar()
    else:
        x = first
    y = reader.read_gchar()
    width = reader.read_gchar()
    height = reader.read_gchar()
    count = max(0, width * height)
    tiles = [reader.read_gshort() for _ in range(count)]
    return {'layer': layer, 'x': x, 'y': y, 'width': width, 'height': height,
            'tiles': tiles}


def parse_board_modify2(data: bytes) -> dict:
    """
    Parse PLO_BOARDMODIFY2 (186) - gmap tile-delta.

    Wire format (PlayerClientPackets.cpp msgPLI_BOARDMODIFY gmap relay /
    LevelBoardChange::getPropsForMapClassic - this is the format the server
    actually sends; the "GSHORT x/y" newmain form documented in IEnums.h is
    dead code, see LevelBoardChange.cpp getPropsForMapNewMain which is never
    called):
        {GCHAR mapX}{GCHAR mapY}<same body as PLO_BOARDMODIFY>
    """
    reader = PacketReader(data)
    map_x = reader.read_gchar()
    map_y = reader.read_gchar()
    result = parse_board_modify(data[reader.pos:])
    result['map_x'] = map_x
    result['map_y'] = map_y
    return result


def build_board_modify(x: int, y: int, width: int, height: int, tiles) -> bytes:
    """
    Build PLI_BOARDMODIFY (1) payload.

    Format (server/src/player/packets/PlayerClientPackets.cpp msgPLI_BOARDMODIFY):
        {GCHAR x}{GCHAR y}{GCHAR width}{GCHAR height}{GSHORT tile}*(width*height)
    tiles must contain exactly width*height raw tile ids.
    """
    builder = PacketBuilder()
    builder.write_gchar(x).write_gchar(y).write_gchar(width).write_gchar(height)
    for tile in tiles:
        builder.write_gshort(tile)
    return builder.build()


def parse_board_heights(data: bytes) -> dict:
    """
    Parse PLO_BOARDHEIGHTS (185) - gmap level-height overrides.

    Wire format (server/src/level/Level.cpp SubLevel::sendBoardHeightsToPlayer):
        {GCHAR mapX}{GCHAR mapY}{GCHAR blockX}{GCHAR blockY}
        {GCHAR blockWidth}{GCHAR blockHeight}
        [{GCHAR wholePart}{GCHAR fracPart}...]
    blockWidth/blockHeight are 0-indexed (a value of 8 means 9 cells), and the
    heightmap is stored row-major (block_height+1) * (block_width+1) entries.
    wholePart is (whole + 50); fracPart is (fraction * 128).
    """
    reader = PacketReader(data)
    map_x = reader.read_gchar()
    map_y = reader.read_gchar()
    block_x = reader.read_gchar()
    block_y = reader.read_gchar()
    block_width = reader.read_gchar()
    block_height = reader.read_gchar()
    cols = block_width + 1
    rows = block_height + 1
    heights = []
    for _ in range(cols * rows):
        whole = reader.read_gchar() - 50
        frac = reader.read_gchar() / 128.0
        # Server always computes decimal = height - floor(height) (>= 0) and
        # whole = round(height - decimal), so height = whole + decimal always
        # holds, even for negative whole (e.g. -3.5 -> whole=-4, decimal=0.5).
        heights.append(whole + frac)
    return {'map_x': map_x, 'map_y': map_y, 'block_x': block_x, 'block_y': block_y,
            'block_width': cols, 'block_height': rows, 'heights': heights}


def parse_large_file_marker(data: bytes) -> str:
    """
    Parse PLO_LARGEFILESTART (68) / PLO_LARGEFILEEND (69) - just a filename,
    no length prefix (server/src/player/Player.cpp sendFile: `<< filename`).
    """
    return data.decode('latin-1', errors='replace')


def parse_large_file_size(data: bytes) -> int:
    """
    Parse PLO_LARGEFILESIZE (84) - total size of the large file about to be
    streamed in PLO_FILE chunks (server/src/player/Player.cpp sendFile:
    `>> (long long)fileData.size()`, a GINT5).
    """
    reader = PacketReader(data)
    return reader.read_gint5()


def parse_file_uptodate(data: bytes) -> str:
    """
    Parse PLO_FILEUPTODATE (45) - filename the server confirms is unchanged
    (server/src/player/packets/PlayerClientPackets.cpp msgPLI_UPDATEFILE:
    `<< file`, no length prefix).
    """
    return data.decode('latin-1', errors='replace')


def build_update_file(filename: str, mod_time: int = 0) -> bytes:
    """
    Build PLI_UPDATEFILE (34) payload - ask the server whether our cached copy
    (with mtime mod_time) of filename is current.

    Format (PlayerClientPackets.cpp msgPLI_UPDATEFILE):
        {GINT5 modTime}{filename}   (filename raw, no length prefix)
    """
    builder = PacketBuilder()
    builder.write_gint5(mod_time)
    builder.write_string(filename)
    return builder.build()


# =============================================================================
# Entity families: bombs / arrows / horses / firespy / throwcarried
# (protocol parity tier 2a/2b)
# =============================================================================
#
# All of these are client->server relays: the server mostly forwards what the
# sending client sent (minus the sender), often prefixing the sender's gshort
# player id. Formats below are read directly from
# server/src/player/packets/PlayerClientPackets.cpp msgPLI_BOMBADD / BOMBDEL /
# HORSEADD / HORSEDEL / ARROWADD / FIRESPY / THROWCARRIED.

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

def _guntokenize(text: str) -> list:
    """Decode a CString::gtokenize'd string back into its lines.

    Inverse of _gtokenize: comma-separated tokens; a token wrapped in double
    quotes may contain commas, doubled quotes (""->") and doubled backslashes.
    """
    tokens = []
    i, n = 0, len(text)
    while i <= n:
        if i < n and text[i] == '"':
            # Quoted token: scan to the closing quote (doubled quote = literal).
            i += 1
            buf = []
            while i < n:
                c = text[i]
                if c == '"':
                    if i + 1 < n and text[i + 1] == '"':
                        buf.append('"')
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(c)
                i += 1
            tokens.append(''.join(buf).replace('\\\\', '\\'))
            if i < n and text[i] == ',':
                i += 1
            elif i >= n:
                break
        else:
            end = text.find(',', i)
            if end == -1:
                tokens.append(text[i:])
                break
            tokens.append(text[i:end])
            i = end + 1
    return tokens


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


def parse_npcserveraddr(data: bytes) -> dict:
    """
    Parse PLO_NPCSERVERADDR (79) - the npc-server's player id + address.
    Format (npcserver/NPCServer.cpp): {GSHORT npcserver_player_id}{"<ip>,<port>"}
    """
    reader = PacketReader(data)
    npcserver_id = reader.read_gshort()
    rest = reader.remaining().decode('latin-1', errors='replace')
    host, _, port_s = rest.partition(',')
    try:
        port = int(port_s)
    except ValueError:
        port = 0
    return {'npcserver_id': npcserver_id, 'host': host, 'port': port, 'raw': rest}


def parse_setnetcookie(data: bytes) -> str:
    """Parse PLO_SETNETCOOKIE (111): {STR cookie} - raw cookie string."""
    return data.decode('latin-1', errors='replace')


# =============================================================================
# GS2 bytecode transport (protocol parity tier 5 - parse and store only)
# =============================================================================
#
# The GS2 script pipeline (no VM here, just lossless transport):
#   weapon: PLO_NPCWEAPONADD announces name/image/classes, PLO_LOADSCRIPT(197)
#           announces the script header ("weapon,<name>,1,<desKey>,<crc>");
#           the client requests the blob with PLI_UPDATESCRIPT(158) and gets
#           PLO_NPCWEAPONSCRIPT(140) = {GSHORT hdr_len}{hdr CSV}{bytecode}.
#   npc:    PLO_NPCBYTECODE(131) = {GINT3 npc_id}{bytecode}, streamed inside
#           PLO_RAWDATA automatically for clients >= 4.0211 (Level.cpp
#           sendNPCsToPlayer).
#   gani:   client asks PLI_UPDATEGANI(157) = {GINT5 crc}{name}; server sends
#           PLO_GANISCRIPT(134) = {GCHAR name_len}{name}{bytecode} (in RAWDATA)
#           when the crc differs, then always PLO_LOADGANI(195) =
#           {GCHAR name_len}{name}"SETBACKTO <ani>".
#   class:  client asks PLI_UPDATECLASS(161) = {GINT5 crc}{name}; server sends
#           PLO_LOADSCRIPT(197) = {GCHAR hdr_len}{hdr CSV}{bytecode} in RAWDATA
#           (ScriptClass.cpp getClassPacket).
# Note PLO_LOADSCRIPT has TWO payload forms (see parse_loadscript).


def parse_npc_bytecode(data: bytes) -> dict:
    """Parse PLO_NPCBYTECODE (131): {GINT3 npc_id}{bytecode}."""
    reader = PacketReader(data)
    npc_id = reader.read_gint3()
    return {'npc_id': npc_id, 'bytecode': reader.remaining()}


def parse_gani_script(data: bytes) -> dict:
    """Parse PLO_GANISCRIPT (134): {GCHAR name_len}{gani_name}{bytecode}
    (GameAni.cpp getBytecodePacket; name has no .gani suffix)."""
    reader = PacketReader(data)
    name = reader.read_gstring()
    return {'gani': name, 'bytecode': reader.remaining()}


def _parse_script_header(header: str) -> dict:
    """Split a GS2 script header CSV: type,name,saveToDisk[,desKey[,crc]]."""
    parts = _guntokenize(header)
    parts += [''] * (5 - len(parts))
    return {'type': parts[0], 'name': parts[1], 'save_to_disk': parts[2] == '1',
            'des_key': parts[3], 'crc': parts[4]}


def parse_npcweaponscript(data: bytes) -> dict:
    """Parse PLO_NPCWEAPONSCRIPT (140): {GSHORT header_len}{header CSV}{bytecode}
    (Weapon.cpp sendByteCodeToPlayer). The bytecode may be empty (the server
    answers unknown class requests with a header-only packet)."""
    reader = PacketReader(data)
    header_len = reader.read_gshort()
    header = reader.read_string(header_len)
    info = _parse_script_header(header)
    info['header'] = header
    info['bytecode'] = reader.remaining()
    return info


def parse_loadgani(data: bytes) -> dict:
    """Parse PLO_LOADGANI (195): {GCHAR name_len}{gani}{stringlist}
    where the stringlist is e.g. '"SETBACKTO idle"'
    (PlayerClientPackets.cpp msgPLI_UPDATEGANI)."""
    reader = PacketReader(data)
    name = reader.read_gstring()
    params = reader.remaining().decode('latin-1', errors='replace')
    setbackto = ''
    for token in _guntokenize(params):
        if token.startswith('SETBACKTO'):
            setbackto = token[len('SETBACKTO'):].strip()
    return {'gani': name, 'setbackto': setbackto, 'params': params}


def parse_loadscript(data: bytes) -> dict:
    """
    Parse PLO_LOADSCRIPT (197). Two payload forms exist server-side:

    1. Weapon announcement (Weapon.cpp registerWeaponWithPlayer):
         {header CSV}                       - raw, no length prefix, no bytecode
       header = "weapon,<name>,1,<desKey>,<crc32>"
    2. Class bytecode (ScriptClass.cpp getClassPacket, arrives via RAWDATA):
         {GCHAR header_len}{header CSV}{bytecode}

    Disambiguation: in form 2 the first byte is a small gchar length whose
    slice starts with a known script type; in form 1 the payload is pure CSV
    text starting with the type name itself.
    """
    for known in (b'weapon,', b'npc,', b'class,', b'gani,'):
        if data.startswith(known):
            header = data.decode('latin-1', errors='replace')
            info = _parse_script_header(header)
            info['header'] = header
            info['bytecode'] = b''
            return info

    reader = PacketReader(data)
    header_len = reader.read_gchar()
    header = reader.read_string(header_len)
    info = _parse_script_header(header)
    info['header'] = header
    info['bytecode'] = reader.remaining()
    return info


def build_update_script(weapon_name: str) -> bytes:
    """Build PLI_UPDATESCRIPT (158): {weapon_name} - request weapon bytecode."""
    return weapon_name.encode('latin-1', errors='replace')


def build_update_gani(gani_name: str, checksum: int = 0) -> bytes:
    """Build PLI_UPDATEGANI (157): {GINT5 crc32}{gani_name} (no .gani suffix).
    Send checksum=0 to force a fresh PLO_GANISCRIPT."""
    builder = PacketBuilder()
    builder.write_gint5(checksum)
    builder.write_string(gani_name)
    return builder.build()


def build_update_class(class_name: str, checksum: int = 0) -> bytes:
    """Build PLI_UPDATECLASS (161): {GINT5 crc32}{class_name}.
    Send checksum=0 to force a fresh class PLO_LOADSCRIPT."""
    builder = PacketBuilder()
    builder.write_gint5(checksum)
    builder.write_string(class_name)
    return builder.build()


# =============================================================================
# RC write-side builders (protocol parity tier 6)
#
# Formats read from GServer-v2 server/src/player/packets/PlayerRCPackets.cpp
# (each function's msgPLI_RC_* handler) and PlayerProps.cpp
# setPropsFromRCPacket. Several are deprecated no-ops server-side but keep
# their historical payloads so the packets are at least well-formed.
# =============================================================================

def build_rc_serveroptions_set(options_text: str) -> bytes:
    """
    Build PLI_RC_SERVEROPTIONSSET (52) - replace serveroptions.txt content.
    Format: the whole options text gtokenized (the server guntokenizes and
    writes the lines back to config/serveroptions.txt).
    """
    return _gtokenize(options_text).encode('latin-1', errors='replace')


def build_rc_folderconfig_set(config_text: str) -> bytes:
    """
    Build PLI_RC_FOLDERCONFIGSET (54) - replace foldersconfig.txt content.
    Format: the folder config lines as a CSV/gtokenized list (the server
    splits with string::fromCSV and writes the lines).
    """
    return _gtokenize(config_text).encode('latin-1', errors='replace')


def build_rc_respawn_set(seconds: int) -> bytes:
    """Build PLI_RC_RESPAWNSET (55): {GCHAR seconds}. Deprecated no-op server-side."""
    return PacketBuilder().write_gchar(seconds).build()


def build_rc_horselife_set(seconds: int) -> bytes:
    """Build PLI_RC_HORSELIFESET (56): {GCHAR seconds}. Deprecated no-op server-side."""
    return PacketBuilder().write_gchar(seconds).build()


def build_rc_apincrement_set(seconds: int) -> bytes:
    """Build PLI_RC_APINCREMENTSET (57): {GCHAR seconds}. Deprecated no-op server-side."""
    return PacketBuilder().write_gchar(seconds).build()


def build_rc_baddyrespawn_set(seconds: int) -> bytes:
    """Build PLI_RC_BADDYRESPAWNSET (58): {GCHAR seconds}. Deprecated no-op server-side."""
    return PacketBuilder().write_gchar(seconds).build()


def _build_rc_props_tail(world: str, props: bytes, flags, chests, weapons) -> 'PacketBuilder':
    """Common tail for PLAYERPROPSSET/SET2 (PlayerProps.cpp
    setPropsFromRCPacket):
        {GCHAR len}{world}{GCHAR len}{props bytes}
        {GSHORT flag_count}[{GCHAR len}{"name=value"}]*
        {GSHORT chest_count}[{GCHAR len(level)+2}{GCHAR x}{GCHAR y}{level}]*
        {GCHAR weapon_count}[{GCHAR len}{weapon}]*
    NOTE: this REPLACES the account's flags/chests/weapons wholesale - only
    use against throwaway accounts.
    """
    builder = PacketBuilder()
    builder.write_gstring(world)
    builder.write_gchar(len(props))
    builder.write_bytes(props)
    builder.write_gshort(len(flags))
    for name, value in flags:
        builder.write_gstring(f"{name}={value}" if value else name)
    builder.write_gshort(len(chests))
    for level, x, y in chests:
        encoded = level.encode('latin-1', errors='replace')
        builder.write_gchar(len(encoded) + 2)
        builder.write_gchar(int(x))
        builder.write_gchar(int(y))
        builder.write_bytes(encoded)
    builder.write_gchar(len(weapons))
    for weapon in weapons:
        builder.write_gstring(weapon)
    return builder


def build_rc_playerprops_set(player_id: int, world: str = '', props: bytes = b'',
                             flags=(), chests=(), weapons=()) -> bytes:
    """
    Build PLI_RC_PLAYERPROPSSET (60) - replace an ONLINE player's account
    state, addressed by player id. props is a raw player-prop stream
    (setPropsFromPacket format). DESTRUCTIVE: wholesale-replaces flags,
    chests and weapons.
    """
    builder = PacketBuilder()
    builder.write_gshort(player_id)
    builder.write_bytes(_build_rc_props_tail(world, props, flags, chests, weapons).build())
    return builder.build()


def build_rc_playerprops_set2(account: str, world: str = '', props: bytes = b'',
                              flags=(), chests=(), weapons=()) -> bytes:
    """
    Build PLI_RC_PLAYERPROPSSET2 (76) - like PLAYERPROPSSET but addressed by
    account name (works for offline accounts too). DESTRUCTIVE - see
    _build_rc_props_tail.
    """
    builder = PacketBuilder()
    builder.write_gstring(account)
    builder.write_bytes(_build_rc_props_tail(world, props, flags, chests, weapons).build())
    return builder.build()


def build_rc_listrcs() -> bytes:
    """Build PLI_RC_LISTRCS (65) - list connected RCs. Deprecated no-op; empty payload."""
    return b''


def build_rc_disconnect_rc(player_id: int = 0) -> bytes:
    """Build PLI_RC_DISCONNECTRC (66): {GSHORT rc_player_id}. Deprecated no-op server-side."""
    return PacketBuilder().write_gshort(player_id).build()


def build_rc_apply_reason(account: str, reason: str = '') -> bytes:
    """Build PLI_RC_APPLYREASON (67): {GCHAR len}{account}{reason}.
    Deprecated no-op server-side."""
    builder = PacketBuilder()
    builder.write_gstring(account)
    builder.write_string(reason)
    return builder.build()


def build_rc_serverflags_set(flags: dict) -> bytes:
    """
    Build PLI_RC_SERVERFLAGSSET (69) - replace ALL server flags.
    Format: {GSHORT count}[{GCHAR len}{"name=value"}]*
    DESTRUCTIVE: the server clears flags that aren't in the list.
    """
    builder = PacketBuilder()
    builder.write_gshort(len(flags))
    for name, value in flags.items():
        builder.write_gstring(f"{name}={value}" if value != '' else name)
    return builder.build()


def build_rc_playerprops_reset(account: str) -> bytes:
    """
    Build PLI_RC_PLAYERPROPSRESET (75) - reset an account to defaultaccount
    (keeps admin rights/ip/folders). Format: account name raw.
    DESTRUCTIVE and boots the player if online.
    """
    return account.encode('latin-1', errors='replace')


def build_rc_account_set(account: str, password: str = '', email: str = '',
                         banned: bool = False, load_only: bool = False,
                         admin_level: int = 0, world: str = '',
                         ban_reason: str = '') -> bytes:
    """
    Build PLI_RC_ACCOUNTSET (78) - edit account metadata.
    Format (msgPLI_RC_ACCOUNTSET):
        {GCHAR len}{account}{GCHAR len}{password}{GCHAR len}{email}
        {GCHAR banned}{GCHAR load_only}{GCHAR admin_level}
        {GCHAR len}{world}{GCHAR len}{ban_reason}
    """
    builder = PacketBuilder()
    builder.write_gstring(account)
    builder.write_gstring(password)
    builder.write_gstring(email)
    builder.write_gchar(1 if banned else 0)
    builder.write_gchar(1 if load_only else 0)
    builder.write_gchar(admin_level)
    builder.write_gstring(world)
    builder.write_gstring(ban_reason)
    return builder.build()


def build_rc_playerrights_set(account: str, rights: int, admin_ip: str = '*.*.*.*',
                              folders=()) -> bytes:
    """
    Build PLI_RC_PLAYERRIGHTSSET (84) - set an account's admin rights.
    Format (msgPLI_RC_PLAYERRIGHTSSET):
        {GCHAR len}{account}{GINT5 rights}{GCHAR len}{admin_ip CSV}
        {GSHORT len}{folder list CSV}
    """
    builder = PacketBuilder()
    builder.write_gstring(account)
    builder.write_gint5(rights)
    builder.write_gstring(admin_ip)
    folder_csv = _gtokenize('\n'.join(folders)) if folders else ''
    builder.write_gstring_short(folder_csv)
    return builder.build()


def build_rc_filebrowser_up(filename: str, file_data: bytes) -> bytes:
    """
    Build PLI_RC_FILEBROWSER_UP (93) - upload a file into the RC's current
    folder. Format: {GCHAR len}{filename}{file bytes to end}.
    Files larger than one packet should be bracketed with
    PLI_RC_LARGEFILESTART/END and chunked through this packet.
    """
    builder = PacketBuilder()
    builder.write_gstring(filename)
    builder.write_bytes(file_data)
    return builder.build()


def build_rc_filebrowser_move(destination_dir: str, filename: str) -> bytes:
    """
    Build PLI_RC_FILEBROWSER_MOVE (96) - move a file from the RC's current
    folder. Format: {GCHAR len}{destination dir}{filename to end}.
    """
    builder = PacketBuilder()
    builder.write_gstring(destination_dir)
    builder.write_string(filename)
    return builder.build()


def build_rc_npcserverquery(player_id: int = 0, message: str = 'location') -> bytes:
    """
    Build PLI_NPCSERVERQUERY (94): {GSHORT player_id}{message}.
    message 'location' asks for the NC address (PLO_NPCSERVERADDR reply).
    """
    builder = PacketBuilder()
    builder.write_gshort(player_id)
    builder.write_string(message)
    return builder.build()


def build_rc_largefile_start(filename: str) -> bytes:
    """Build PLI_RC_LARGEFILESTART (155): {filename raw} - begin a chunked
    RC file upload (subsequent FILEBROWSER_UP packets accumulate)."""
    return filename.encode('latin-1', errors='replace')


def build_rc_largefile_end(filename: str) -> bytes:
    """Build PLI_RC_LARGEFILEEND (156): {filename raw} - finish a chunked RC
    file upload (server writes the accumulated data to disk)."""
    return filename.encode('latin-1', errors='replace')


def build_rc_folder_delete(folder: str) -> bytes:
    """Build PLI_RC_FOLDERDELETE (160): {folder raw} - delete an (empty)
    folder, path relative to the server root."""
    return folder.encode('latin-1', errors='replace')
