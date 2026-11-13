from .common import *
import logging
from ..logutil import log_swallowed
logger = logging.getLogger(__name__)

def parse_npc_showimgs(data: bytes, id_bytes: int = 3) -> dict:
    """Parse PLO_SHOWIMGNPC (166) into NPC showimg layer updates."""
    def read_gchar(position):
        if position >= len(data):
            return None, len(data)
        return data[position] - 32, position + 1

    npc_id, pos = _read_gbyte(data, 0, id_bytes)
    result = {'npc_id': npc_id, 'clear': False, 'records': {}}
    if id_bytes == 2:
        result['player_images'] = True
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
            empty = pos < len(data) and data[pos] == 32
            value, pos = _read_string(data, pos)
            if value is not None or empty:
                current['image'] = value or ''
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
            current['colors'] = tuple(value / (255.0 if id_bytes == 2 else 200.0) for value in values)
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
        log_swallowed(logger, level=logging.DEBUG)
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
    Format: {GSHORT owner_id}{GCHAR radius}{GCHAR x*2}{GCHAR y*2}{GCHAR type|8}

    Decompiled reference client TClient.cpp:3593-3620
    (scriptfun_client_addexplosion): type is `flags & 7` (0 -> 1, >= 4 -> 3)
    and bit 3 (8) marks a player-owned explosion. Positions are half-tiles.
    """
    if len(data) < 6:
        return {}
    reader = PacketReader(data)
    owner_id = reader.read_gshort()
    radius = reader.read_gchar()
    x = reader.read_gchar() / 2.0
    y = reader.read_gchar() / 2.0
    flags = reader.read_gchar()
    kind = flags & 0x07
    if kind == 0:
        kind = 1
    elif kind >= 4:
        kind = 3
    return {
        'owner_id': owner_id, 'x': x, 'y': y, 'radius': radius,
        'power': kind, 'from_player': bool(flags & 0x08),
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


_MAP_IMAGE_EXTENSIONS = ('.png', '.gif', '.bmp', '.jpg', '.jpeg', '.mng')


def _map_number(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        return 0.0


def _parse_map_option(parts, positional_fallback: bool = True):
    """Shared body of PLO_BIGMAP / PLO_MINIMAP: four comma tokens, the first
    two being an image and a level-list file in EITHER order.

    The server forwards the option verbatim (GServer-v2 origin/beta4
    PlayerClient.cpp:499-512), and the order in use differs: shipped
    serveroptions say `maptext,image,x,y`, real GS1 setmap calls pass
    `image,levelsfile,x,y`. So the image is whichever of the first two tokens
    ends in an image extension, the level list the other one. With no image
    extension among them, the non-.txt token is the image (image-first when
    neither is .txt), when `positional_fallback` allows.
    Returns None when nothing usable is there.
    """
    parts = [p.strip() for p in parts]
    parts += [''] * (4 - len(parts))
    first_two = parts[:2]
    image_at = next(
        (i for i, tok in enumerate(first_two)
         if tok.lower().endswith(_MAP_IMAGE_EXTENSIONS)), None)
    if image_at is None:
        if not positional_fallback:
            return None
        image_at = 1 if (first_two[0].lower().endswith('.txt')
                         and not first_two[1].lower().endswith('.txt')) else 0
    return {'image': first_two[image_at],
            'levels_file': first_two[1 - image_at],
            'x': _map_number(parts[2]), 'y': _map_number(parts[3])}


def parse_minimap(data: bytes) -> dict:
    """Parse PLO_MINIMAP (172) map-image configuration or legacy raw data."""
    text = data.decode('latin-1', errors='replace')
    parts = text.split(',')
    first = parts[0].strip()
    basename = first.replace('\\', '/').rsplit('/', 1)[-1]
    if ',' in text:
        parsed = _parse_map_option(parts, positional_fallback=False)
        if parsed is None and (
                '.' in basename and not basename.startswith('.')
                and not basename.endswith('.')):
            parsed = _parse_map_option(parts)
        if parsed is not None:
            return parsed

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
    handle_empty=frozenset(_NPC_TEXT_KEYS) | frozenset(
        [36, 37, 38, 39, 40, 44, 45, 46, 47, *range(53, 74)]))


def _set_text(key):
    return lambda props, value: props.__setitem__(key, value or '')


def _set_npc_visflags(props, flags):
    # FourPlay/quattroplay/src/TServerNPC.cpp:1098-1113.
    props.update(visflags=flags, visible=bool(flags & 1))
    if flags & 4:
        props['draw_layer'] = 'under'
    elif flags & 2:
        props['draw_layer'] = 'over'
    elif flags & 0x26 == 0:
        props['draw_layer'] = None


def _set_npc_hurt_dxdy(props, raw):
    # NPCProp::HURTDXDY: two bytes, each the signed push plus MidPoint 32,
    # written as gchars (another +32): GServer-v2 PropertySerializers.h:636-645
    # (PropertyHurtDxDy<MidPoint = 32>). The reference client reads each raw
    # byte as (byte - 0x40) * 0.0625 into the NPC's hurtdx/hurtdy
    # (Preagonal/FourPlay/quattroplay/src/TServerNPC.cpp:1137-1144;
    # DOUBLE_00402550 = 0.0625 at TInitStatics.cpp:1245). The C# client divides
    # by 32 instead (its Levels/NPC.cs:648-650); the decompiled client is the
    # oracle here. Nothing in this client reads hurt_dx/hurt_dy yet.
    props['hurt_dx'] = (raw[0] - 0x40) * 0.0625
    props['hurt_dy'] = (raw[1] - 0x40) * 0.0625


def _set_npc_equipment(kind):
    def handler(props, value):
        power, image = value
        props[kind + '_power'] = power
        image = image if image is not None else ''
        # TServerNPC.cpp:70-74,1034-1080 appendExtensionIfMissing(".png"): a
        # name with no extension at all gets one.
        if image and '.' not in image.rsplit('/', 1)[-1]:
            image += '.png'
        props[kind + '_image'] = image
    return handler


#: Joined-class names kept from one NPC's CLASS prop, and the longest name.
NPC_CLASS_LIST_MAX = 64
NPC_CLASS_NAME_MAX = 128


def clean_class_list(value) -> list:
    """Comma list from NPC prop CLASS (74) -> usable class names.

    The list is server-supplied and each name becomes a PLI_UPDATECLASS
    request, so names with path separators or control bytes are dropped, as
    are over-long names and everything past NPC_CLASS_LIST_MAX. Order is kept
    and repeats removed.
    """
    names = []
    for raw in (value or '').split(','):
        name = raw.strip()
        if (not name or len(name) > NPC_CLASS_NAME_MAX or name in names
                or '/' in name or '\\' in name
                or any(ord(ch) < 32 or ord(ch) == 127 for ch in name)):
            continue
        names.append(name)
        if len(names) >= NPC_CLASS_LIST_MAX:
            break
    return names


def _set_npc_classes(props, value):
    # GServer-v2 origin/beta4 PropertySerializers.cpp:84-88 (CLASS is a
    # GSHORT-length comma list; modern servers only, NPC.cpp:74-75).
    props['classes'] = clean_class_list(value)


_NPC_PROP_HANDLERS = {
    74: _set_npc_classes,
    2: _set('x'),
    3: _set('y'),
    10: _set_npc_equipment('sword'),
    11: _set_npc_equipment('shield'),
    13: _set_npc_visflags,
    # NPCBlockFlags: bit 0 = NOBLOCK (dontblock/blockagain). Surfaced as the
    # same 'dontblock' key the local GS1 runtime's collision gate reads.
    14: lambda props, value: props.update(
        blockflags=int(value), dontblock=bool(int(value) & 1)),
    16: _set_npc_hurt_dxdy,
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
    43: lambda props, value: props.update(z=value) if value <= 170 else None,
    50: _set_text('name'),
    # FourPlay/quattroplay/src/TServerNPC.cpp:1260-1339.
    **{pid: _set_text(f'gattrib{idx}') for idx, pid in enumerate(
        [36, 37, 38, 39, 40, 44, 45, 46, 47, *range(53, 74)], 1)},
    75: _set('x'),
    76: _set('y'),
    77: _set_z2,
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
                    diagnostics: Optional[Dict[str, int]] = None,
                    colors_len_known: bool = False) -> dict:
    """Parse an NPC property stream, retrying the alternate color width
    unless `colors_len_known` (see _parse_with_colors_retry)."""
    return _parse_with_colors_retry(
        lambda width: _parse_npc_props_once(data, width),
        colors_len, diagnostics, colors_len_known)


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


def parse_bigmap(data: bytes) -> dict:
    """PLO_BIGMAP (171): four comma tokens, image and level list in either
    order (see _parse_map_option), then x,y of the off-map head position.

    Sent right after PLO_RESETCLIENT at login when the server has the
    `bigmap` option (GServer-v2 origin/beta4 PlayerClient.cpp:500) and by the
    GS1 setmap command.
    """
    return _parse_map_option(
        data.decode('latin-1', errors='replace').split(','))


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
