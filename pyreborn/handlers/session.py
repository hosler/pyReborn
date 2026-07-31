"""The client handles session, handshake, and server-control packets.

These packets contain raw-data framing, world time, flags, freeze and fullstop
states, profiles, and the different login markers.
"""

from ..packets import (
    PacketID,
    parse_default_weapon,
    parse_flag_del,
    parse_flag_set,
    parse_fullstop,
    parse_fullstop2,
    parse_ghost_icon,
    parse_newworldtime,
    parse_npcserveraddr,
    parse_profile,
    parse_rawdata,
    parse_server_warp,
    parse_setnetcookie,
    parse_signature,
    parse_staff_guilds,
    parse_status_list,
)
from .registry import handles


@handles(PacketID.PLO_RAWDATA)
def handle_rawdata(client, data):
    # Raw data announcement
    client._raw_data_expected = parse_rawdata(data)


@handles(PacketID.PLO_NEWWORLDTIME)
def handle_new_world_time(client, data):
    # Heartbeat / time sync
    info = parse_newworldtime(data)
    client.server_time = info.get('time', 0)


@handles(PacketID.PLO_DISCMESSAGE)
def handle_disc_message(client, data):
    # Disconnect message (packet 16) - server kicked us / is shutting down
    reason = data.decode('latin-1', errors='replace').strip()
    client.disconnect_reason = reason
    if client.on_disconnect:
        client.on_disconnect(reason)
    client.disconnect()


@handles(PacketID.PLO_LISTPROCESSES)
def handle_list_processes(client, data):
    # Process-list request (packet 182).  The server's PLI_PROCESSLIST
    # handler guntokenizes this payload into newline-separated identities;
    # one simple token is therefore a complete, truthful one-entry list.
    client._protocol.send_packet(PacketID.PLI_PROCESSLIST, b"pyReborn")


@handles(PacketID.PLO_GHOSTMODE)
def handle_ghost_mode(client, data):
    # Ghost mode (packet 170)
    # Ghost mode packet - typically just a toggle flag
    enabled = data[0] != 0 if data else True
    client.ghost_mode = enabled
    if client.on_ghost_mode:
        client.on_ghost_mode(enabled)


@handles(PacketID.PLO_SIGNATURE)
def handle_signature(client, data):
    # Server signature/version (packet 25).
    client.server_signature = parse_signature(data)


@handles(PacketID.PLO_FLAGSET)
def handle_flag_set(client, data):
    # Server flag set/clear (packet 28).
    name, value = parse_flag_set(data)
    client.global_flags[name] = value
    if client.on_flag:
        client.on_flag(name, value)


@handles(PacketID.PLO_FLAGDEL)
def handle_flag_del(client, data):
    # Server-wide flag removed (packet 31).
    name = parse_flag_del(data)
    client.global_flags.pop(name, None)
    if client.on_flag_del:
        client.on_flag_del(name)


@handles(PacketID.PLO_FREEZEPLAYER2)
def handle_freeze_player(client, data):
    # Freeze / unfreeze player (packets 154/155) - empty payloads.
    client.frozen = True
    if client.on_freeze:
        client.on_freeze(True)


@handles(PacketID.PLO_UNFREEZEPLAYER)
def handle_unfreeze_player(client, data):
    client.frozen = False
    if client.on_freeze:
        client.on_freeze(False)


@handles(PacketID.PLO_HIDENPCS)
def handle_hide_npcs(client, data):
    # Hide all NPCs (packet 151) - empty payload.
    client.npcs_hidden = True
    if client.on_hide_npcs:
        client.on_hide_npcs()


@handles(PacketID.PLO_SERVERWARP)
def handle_server_warp(client, data):
    # Server warp target (packet 178) - do NOT auto-connect; just record
    # the destination and notify the app.
    client.server_warp_info = parse_server_warp(data)
    if client.on_server_warp:
        client.on_server_warp(client.server_warp_info)


@handles(PacketID.PLO_DISABLECLASSICMODE)
def handle_disable_classic_mode(client, data):
    # Disable classic mode (packet 176) - fully-scripted server marker.
    client.classic_mode_disabled = True
    client.input_frozen = parse_fullstop(data)
    if client.on_fullstop:
        client.on_fullstop(client.input_frozen)


@handles(PacketID.PLO_FULLSTOP2)
def handle_fullstop2(client, data):
    # Alternate blank input-stop command (packet 177).
    client.input_frozen = parse_fullstop2(data)
    if client.on_fullstop:
        client.on_fullstop(client.input_frozen)


@handles(PacketID.PLO_PROFILE)
def handle_profile(client, data):
    # Another player's profile (packet 75).
    profile = parse_profile(data)
    if profile.get('account'):
        client.profiles[profile['account']] = profile
    if client.on_profile:
        client.on_profile(profile)


@handles(PacketID.PLO_NPCSERVERADDR)
def handle_npcserver_addr(client, data):
    # NPC-server address (packet 79).
    client.npcserver_addr = parse_npcserveraddr(data)


@handles(PacketID.PLO_SETNETCOOKIE)
def handle_set_net_cookie(client, data):
    # Net cookie (packet 111).
    client.net_cookie = parse_setnetcookie(data)


@handles(PacketID.PLO_DEFAULTWEAPON)
def handle_default_weapon(client, data):
    # Default weapon id (packet 43).
    client.default_weapon = parse_default_weapon(data)


@handles(PacketID.PLO_STAFFGUILDS)
def handle_staff_guilds(client, data):
    # Staff guild list (packet 47).
    client.staff_guilds = parse_staff_guilds(data)


@handles(PacketID.PLO_UNKNOWN168)
def handle_login_complete(client, data):
    # Login-complete marker, blank (packet 168). GServer-v2 sends this
    # once per connection, right after PLO_HASNPCSERVER, purely to signal
    # "you have finished logging in" - see server/src/player/Player.cpp:
    # 700-709 ("This seems to inform the client that they have logged
    # in."). No payload to parse; just latch the flag.
    client.login_complete = True
    if client.on_login_complete:
        client.on_login_complete()


@handles(PacketID.PLO_GHOSTICON)
def handle_ghost_icon(client, data):
    # Ghost icon toggle (packet 174).
    client.ghost_icon = parse_ghost_icon(data)


@handles(PacketID.PLO_STATUSLIST)
def handle_status_list(client, data):
    # Selectable player-status labels (packet 180).
    client.status_list = parse_status_list(data)


@handles(PacketID.PLO_UNKNOWN190)
def handle_unknown190(client, data):
    # Blank marker before weapon list (packet 190) - no-op. NOTE:
    # GServer-v2 (this workspace's ground truth) never actually sends
    # this packet - dependencies/gs2lib/include/IEnums.h:306 and
    # server/src/player/Player.cpp only list it in the packet-name enum
    # table, with no sendPacket call anywhere in server/src. Kept as a
    # defensive no-op in case another server implementation emits it.
    pass


@handles(PacketID.PLO_HASNPCSERVER)
def handle_has_npc_server(client, data):
    # PLO_HASNPCSERVER (44): empty flag - the server has an npc-server, so
    # the client should not update npc props itself. Just record it.
    client.has_npc_server = True
