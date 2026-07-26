from .common import *

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


