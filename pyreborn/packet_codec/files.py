from .common import *

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

