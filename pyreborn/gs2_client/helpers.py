"""Client-side GS2 package component."""

from __future__ import annotations

from typing import List
from reborn_protocol.gs2 import to_str
from .registry import _DEFAULT_STAFF_GUILDS

def _is_admin_guild(guild: str, staff_guilds) -> bool:
    if not guild:
        return False
    probe = (to_str(guild) + ")").lower()
    if staff_guilds is None:
        # PLO_STAFFGUILDS never arrived this session: the client-baked
        # defaults apply (the reference seeds them at startup,
        # initStaffGuildList).
        entries = _DEFAULT_STAFF_GUILDS
    else:
        # A server-SENT list is authoritative even when empty: the oracle
        # answers false for every guild then (TPlayerList.cpp:11-12) --
        # it never falls back to the defaults. Blank entries are dropped
        # rather than prefix-matching everything.
        entries = [e for e in staff_guilds if to_str(e)]
    # NB: the case-insensitive match is an unverified inference (TString::
    # starts' case behavior is not established from the decompile).
    return any(probe.startswith(to_str(entry).lower()) for entry in entries)

#: TGaniObject's per-object render transform (TGaniObjectProperties.cpp:199,
#: :217, :226, :235, :244, :253, :262, :271, :280, :289), registered on
#: players AND NPCs. Every getter there is a raw address, so the oracle backs
#: only the names, types and read/write flags -- the values below are the
#: identity transform our own showimg records already use, chosen so a script
#: that reads a slot it never wrote gets a no-op rather than a black,
#: zero-scaled object. Writes are remembered (the renderer does not consume
#: them yet; that lives outside this module).
_GANI_TRANSFORM_DEFAULTS = {
    "rotation": 0.0, "zoom": 1.0, "stretchx": 1.0, "stretchy": 1.0,
    "red": 1.0, "green": 1.0, "blue": 1.0, "alpha": 1.0,
    "mode": 0.0, "useowncenter": 0.0,
}

#: player.zoomfactor's clamp: value <= 16.0 ? max(value, 1.0) : 16.0
#: (quattroplay/src/TPlayerProperties.cpp:44-50, constants FLOAT_0040231c =
#: 16.0 and FLOAT_004022c0 = 1.0 at src/TInitStatics.cpp:1221,1226).
ZOOM_FACTOR_MIN = 1.0
ZOOM_FACTOR_MAX = 16.0

#: player.freezetime is carried as a tick counter decremented once per player
#: update; the property converts with 20 ticks per second and the setter caps
#: at 600 ticks == 30 s (quattroplay/src/TPlayerProperties.cpp:11-37, with
#: DOUBLE_004023f8 = 20.0 and DOUBLE_00402518 = 30.0 at
#: src/TInitStatics.cpp:1264,1254). Not frozen reads -1.0, not 0.
FREEZE_TICKS_PER_SECOND = 20.0
FREEZE_MAX_TICKS = 600


def _csv_flatten(args) -> List[str]:
    """Trigger params as wire CSV fields: a GS2 {array} argument contributes
    one field per element (the client flattens arrays into the action string)."""
    out: List[str] = []
    for a in args:
        if isinstance(a, (list, tuple)):
            values = (to_str(x) for x in a)
        else:
            values = (to_str(a),)
        for value in values:
            if any(char in value for char in '",\\'):
                value = '"' + ''.join(
                    char * 2 if char in '"\\' else char for char in value
                ) + '"'
            out.append(value)
    return out


def _csv_unflatten(value: str) -> List[str]:
    """Decode trigger CSV, falling back to the legacy raw split if malformed."""
    fields, field = [], []
    pos, quoted = 0, False
    try:
        while pos < len(value):
            char = value[pos]
            if not field and char == '"':
                quoted = True
                pos += 1
                continue
            if quoted:
                if char in '"\\':
                    if pos + 1 < len(value) and value[pos + 1] == char:
                        field.append(char)
                        pos += 2
                        continue
                    if char == '"' and (pos + 1 == len(value)
                                       or value[pos + 1] == ','):
                        quoted = False
                        pos += 1
                        continue
                    raise ValueError
                field.append(char)
            elif char == ',':
                fields.append(''.join(field))
                field = []
            elif char == '"':
                raise ValueError
            else:
                field.append(char)
            pos += 1
        if quoted:
            raise ValueError
        fields.append(''.join(field))
        return fields
    except ValueError:
        return value.split(",")


def _image_size(data: bytes):
    """(width, height) from a GIF/PNG/JPEG/BMP header, or None."""
    if len(data) < 26:
        return None
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return (int.from_bytes(data[6:8], "little"),
                int.from_bytes(data[8:10], "little"))
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return (int.from_bytes(data[16:20], "big"),
                int.from_bytes(data[20:24], "big"))
    if data[:2] == b"BM":
        return (int.from_bytes(data[18:22], "little", signed=True),
                abs(int.from_bytes(data[22:26], "little", signed=True)))
    if data[:2] == b"\xff\xd8":  # JPEG: scan for a SOF marker
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                return (int.from_bytes(data[i + 7:i + 9], "big"),
                        int.from_bytes(data[i + 5:i + 7], "big"))
            seg_len = int.from_bytes(data[i + 2:i + 4], "big")
            i += 2 + seg_len
    return None
