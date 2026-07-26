from .common import *

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
