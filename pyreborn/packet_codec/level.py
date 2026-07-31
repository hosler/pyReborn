from .common import *

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
    """Parse PLO_MINIMAP (172) map-image configuration or legacy raw data."""
    text = data.decode('latin-1', errors='replace')
    parts = text.split(',')
    first = parts[0].strip()
    basename = first.replace('\\', '/').rsplit('/', 1)[-1]
    if ',' in text and (
            '.' in basename and not basename.startswith('.')
            and not basename.endswith('.')):
        parts += [''] * (4 - len(parts))

        def _num(v):
            try:
                return float(v)
            except ValueError:
                return 0.0

        return {'image': first, 'levels_file': parts[1].strip(),
                'x': _num(parts[2]), 'y': _num(parts[3])}

    # Preserve raw bytes for servers that use a different minimap payload.
    return {'data': data, 'type': data[0] - 32 if data else 0}


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


# NPCProp streams are ascending and self-delimiting like PlayerProp ones, but
# over a different enum: NPC.h interleaves GMAPLEVELX/GMAPLEVELY/Z (41-43)
# between GATTRIB5 and GATTRIB6, and 75-77 are X2/Y2/Z2 rather than
# OSTYPE/TEXTCODEPAGE/ONLINESECS2. See reborn_protocol.props.NPC_PROPS.
#
# NPC strings are surfaced even when empty: clearing an NPC's message or image
# is a real update, unlike a missing prop (hence handle_empty below).
_NPC_TEXT_KEYS = {0: 'image', 1: 'script', 12: 'gani', 15: 'message',
                  20: 'nickname', 21: 'horseimage', 35: 'bodyimage',
                  52: 'curlevel'}

_NPC_STREAM = StreamPolicy(
    table=NPC_PROPS, max_prop_id=77, require_ascending=True,
    check_alignment=True, require_full_consume=True,
    handle_empty=frozenset(_NPC_TEXT_KEYS))


def _set_text(key):
    return lambda props, value: props.__setitem__(key, value or '')


_NPC_PROP_HANDLERS = {
    2: _set('x'),
    3: _set('y'),
    13: _set('visflags'),
    18: _set_sprite,
    19: _set('colors'),
    # A preset head id is meaningful to the renderer here (unlike the player
    # case), so the int is surfaced alongside custom image names.
    22: _set('headimage'),
    # PropertyImagePart: classic "object" NPCs point image at a tilesheet (e.g.
    # pics1.png) and use this rect to pick the sub-region; without it the
    # renderer blits the whole sheet.
    34: _set('imagepart'),
    # On a gmap, gs2emu streams ALL the map's NPCs under one
    # PLO_SETACTIVELEVEL <map>.gmap, so this pair is the ONLY segment
    # attribution the client gets - see client.py's PLO_NPCPROPS handler.
    41: _set('gmaplevelx'),
    42: _set('gmaplevely'),
    50: _set_text('name'),
    75: _set('x'),
    76: _set('y'),
    77: _set('z'),
    **{pid: _set_text(key) for pid, key in _NPC_TEXT_KEYS.items()},
    # A bare "-" image means "no image", not a filename: both GServer-v2
    # (loader/LevelLoader.cpp:832) and the C# client
    # (Preagonal.GameEngine/Levels/Level.cs:154) clear it on load. Left as a
    # filename it reached the renderer's request-once path, so the client asked
    # every server for a file literally named "-" -- which every server refuses,
    # once per NPC that had no image.
    0: lambda props, value: props.__setitem__(
        'image', '' if (value or '').strip() == '-' else (value or '')),
}


def _parse_npc_props_once(data: bytes, colors_len: int) -> tuple:
    """
    Parse PLO_NPCPROPS (packet 3) -> NPC info dict.

    Format: GInt3(npc_id) followed by [gchar prop_id][value...] pairs.
    """
    if len(data) < 3:
        return {}, False

    npc_id = ((data[0] - 32) << 14) + ((data[1] - 32) << 7) + (data[2] - 32)
    props, clean, _ = parse_prop_stream(
        data, 3,
        _NPC_STREAM.with_colors_len(colors_len),
        _NPC_PROP_HANDLERS,
        out={'id': npc_id})
    return props, clean


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
