"""
pyreborn - Packet parsing
Essential packet handlers for basic gameplay.

Uses the shared reborn_protocol library for core protocol components.
"""

import math
from typing import Dict, Any, Optional

# Import shared protocol components
from reborn_protocol import PLI, PLO
from reborn_protocol.props import (
    COLORS_CLASSIC,
    PLAYER_PROPS,
    StreamPolicy,
    parse_prop_stream,
)
from reborn_protocol import BDPROP, PLPROP, PacketBuilder, PacketReader  # noqa: F401  - kept: original import block (star-import consumers rely on it)
from reborn_protocol.props import BADDY_PROPS, NPC_PROPS  # noqa: F401  - kept: original import block (star-import consumers rely on it)


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
# Payload widths and encodings live in reborn_protocol.props (one descriptor
# table per property enum, sourced from GServer-v2's X-macros + serializers).
# Getting any width wrong misaligns the rest of the props packet (the classic
# "Y position suddenly jumps" symptom), so nothing here re-derives one.
# pyReborn targets v6.037 (MODERN / new-world mode => COLORS is 8 bytes).
# =============================================================================

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


def _set(key):
    """Handler that stores a decoded prop value under `key` verbatim."""
    return lambda props, value: props.__setitem__(key, value)


def _set_scaled(key, scale):
    return lambda props, value: props.__setitem__(key, value * scale)


def _set_sprite(props, value):
    props['sprite'] = value
    props['direction'] = value & 0x03


def _set_power_image(power_key, image_key):
    """SWORDPOWER/SHIELDPOWER: always record the power, the image only when one
    was actually on the wire (a bare preset power carries none, and the client
    keeps its own default sprite rather than GServer's synthesised name)."""
    def handler(props, value):
        power, image = value
        props[power_key] = power
        if image is not None:
            props[image_key] = image
    return handler


def _set_head_image(props, value):
    # HEADGIF is a preset id below 100, else a filename (props.py's Wire.HEADGIF
    # decodes to int or str respectively). Both forms name an image: the
    # reference client turns the preset id N into "head{N}.png" (decompiled
    # client, Preagonal/FourPlay/quattroplay/src/TServerPlayer.cpp:1659-1666).
    # Dropping the int form left the avatar wearing whatever head it had before
    # -- head0.png for a fresh player -- while everyone else saw the real one.
    if isinstance(value, str):
        props['head_image'] = value
    elif isinstance(value, int):
        props['head_image'] = f'head{value}.png'


def _gattrib_handlers():
    return {pid: _set(f'gattrib{idx}') for pid, idx in _GATTRIB_IDS.items()}


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

_PLAYER_STREAM = StreamPolicy(
    table=PLAYER_PROPS, max_prop_id=83, require_ascending=True,
    ascending_exempt=frozenset({50}), check_alignment=True)
LEVEL_ITEM_NAMES = {
    0: 'greenrupee', 1: 'bluerupee', 2: 'redrupee', 3: 'bombs', 4: 'darts',
    5: 'heart', 6: 'glove1', 7: 'bow', 8: 'bomb', 9: 'shield', 10: 'sword',
    11: 'fullheart', 12: 'superbomb', 13: 'battleaxe', 14: 'goldensword',
    15: 'mirrorshield', 16: 'glove2', 17: 'lizardshield', 18: 'lizardsword',
    19: 'goldrupee', 20: 'fireball', 21: 'fireblast', 22: 'nukeshot',
    23: 'joltbomb', 24: 'spinattack',
}
_SELF_PROP_HANDLERS = {
    0: _set('nickname'),
    # MAXPOWER is whole hearts while CURPOWER is halves: GServer-v2
    # PlayerProps.cpp:171-186 stores MAXPOWER straight into account.maxHitpoints
    # (hitpointsInHalves = value * 2), and LevelItem.cpp:148-151 sends a
    # fullheart pickup as `>> MAXPOWER >> heartMax >> CURPOWER >> heartMax * 2`.
    1: lambda props, value: props.__setitem__('max_hearts', float(value)),
    2: _set_scaled('hearts', 0.5),
    3: _set('rupees'),
    4: _set('arrows'),
    5: _set('bombs'),
    6: _set('glove_power'),
    7: _set('bomb_power'),
    8: _set_power_image('sword_power', 'sword_image'),
    9: _set_power_image('shield_power', 'shield_image'),
    10: _set('animation'),
    11: _set_head_image,
    12: _set('chat'),
    13: _set('colors'),
    14: _set('id'),
    15: _set('x'),
    16: _set('y'),
    17: _set_sprite,
    18: _set('status'),
    19: _set('carry_sprite'),
    20: _set('level'),
    21: _set('horse_image'),
    22: _set('horse_bushes'),
    24: _set('carry_npc'),
    26: _set('mp'),
    32: _set('ap'),
    34: lambda props, value: props.setdefault('account', value),
    35: _set('body_image'),
    78: _set('x'),
    79: _set('y'),
    **_gattrib_handlers(),
}


def parse_player_props(data: bytes, colors_len: int = COLORS_CLASSIC,
                       diagnostics: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """
    Parse PLO_PLAYERPROPS (packet 9) - returns dict of properties.

    colors_len: preferred byte width of PLPROP_COLORS (5 classic / 8 v6
    extended) to try first. Wrong value misaligns everything after COLORS,
    so if this guess doesn't let the rest of the packet parse cleanly, the
    other known width is tried instead (see _parse_with_colors_retry).
    """
    def _run(width):
        props, clean, _ = parse_prop_stream(
            data, 0,
            _PLAYER_STREAM.with_colors_len(width),
            _SELF_PROP_HANDLERS)
        return props, clean

    return _parse_with_colors_retry(_run, colors_len, diagnostics)
def _round_position(value: float, units_per_tile: int) -> int:
    """Quantize a tile coordinate to the wire's sub-tile unit the way the real
    client does: ROUND to nearest, not truncate.

    The reference client encodes every position property as
    ``floorToInt(tiles * units + 0.5)`` -- half-tiles for the classic
    PLPROP_X/Y and pixels for PLPROP_X2/Y2 (decompiled client,
    Preagonal/FourPlay/quattroplay/src/TPlayer.cpp:3213-3216 and 3336-3339).
    Truncating instead (the old ``int(x * 2)``) biases every reported position
    toward the origin by up to one unit -- half a tile on a classic server --
    so we consistently reported ourselves above/left of where we actually
    stood. Bomber Arena's own scripts round the same way
    (weapon-gr_movement: ``int((playerx+0.25)*2)/2``).
    """
    return math.floor(value * units_per_tile + 0.5)
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

__all__ = [name for name in globals() if not name.startswith('__')]
