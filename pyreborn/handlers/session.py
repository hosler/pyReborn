"""The client handles session, handshake, and server-control packets.

These packets contain raw-data framing, world time, flags, freeze and fullstop
states, profiles, and the different login markers.
"""

from ..packets import (
    PacketID,
    parse_default_weapon,
    parse_flag_del,
    parse_flag_set,
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
from ..ground_items import ITEM_NAMES, WEAPON_GRANT_ITEMS
from ..client_callbacks import emit
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
    client._notify_disconnect(reason)
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
    # TClient.cpp:5162: the payload is an encoded integer, not a boolean.
    if not data:
        return
    client.ghost_mode = data[0] - 32
    emit(client, 'on_ghost_mode', client.ghost_mode)


@handles(PacketID.PLO_SIGNATURE)
def handle_signature(client, data):
    # Server signature/version (packet 25).
    client.server_signature = parse_signature(data)


@handles(PacketID.PLO_FLAGSET)
def handle_flag_set(client, data):
    # Server flag set/clear (packet 28).
    name, value = parse_flag_set(data)
    client.global_flags[name] = value
    emit(client, 'on_flag', name, value)


@handles(PacketID.PLO_FLAGDEL)
def handle_flag_del(client, data):
    # Server-wide flag removed (packet 31).
    name = parse_flag_del(data)
    client.global_flags.pop(name, None)
    emit(client, 'on_flag_del', name)


@handles(PacketID.PLO_FREEZEPLAYER2)
def handle_freeze_player(client, data):
    # Freeze / unfreeze player (packets 154/155) - empty payloads.
    client.frozen = True
    emit(client, 'on_freeze', True)


@handles(PacketID.PLO_UNFREEZEPLAYER)
def handle_unfreeze_player(client, data):
    client.frozen = False
    emit(client, 'on_freeze', False)


@handles(PacketID.PLO_HIDENPCS)
def handle_hide_npcs(client, data):
    # Hide all NPCs (packet 151) - empty payload.
    client.npcs_hidden = True
    emit(client, 'on_hide_npcs')


@handles(PacketID.PLO_SERVERWARP)
def handle_server_warp(client, data):
    # GServer-v2/server/src/ServerList.cpp:974-982.
    client.server_warp_info = parse_server_warp(data)
    # The request is answered, so the same destination may be asked again
    # (the reference never needs this: it follows the answer at once).
    client.last_server_warp = ""
    emit(client, 'on_server_warp', client.server_warp_info)


@handles(PacketID.PLO_KINGDOMSMODE)
def handle_kingdoms_mode(client, data):
    # Packet 176: the server runs `servermode = kingdoms`. A bare marker sent
    # right after PLO_SIGNATURE, `else if` against 177 (GServer-v2 origin/beta4
    # server/src/player/Player.cpp:748-752). It is not a stop or freeze, so
    # input and HUD are untouched. `classic_mode_disabled` is the legacy flag
    # name for the same fact.
    client.classic_mode_disabled = True
    client.server_mode = 'kingdoms'


@handles(PacketID.PLO_NEWWORLDMODE)
def handle_newworld_mode(client, data):
    # Packet 177: `servermode = newworld` (Player.cpp:751-752). Also the
    # server-wide switch to the 8-byte PLPROP_COLORS (PropertySerializers.h:
    # 793-796), so receiving it is positive evidence for that width
    # (handlers/entities.py colors_width_policy); never receiving it proves
    # nothing.
    client.server_mode = 'newworld'


@handles(PacketID.PLO_PROFILE)
def handle_profile(client, data):
    # Another player's profile (packet 75).
    profile = parse_profile(data)
    if profile.get('account'):
        client.profiles[profile['account']] = profile
    emit(client, 'on_profile', profile)


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
    # The server's built-in item weapons are keyed by lowercase item name
    # (GServer-v2 LevelItem::getItemName); no script, the client's own
    # bow/bomb handling runs them.
    if client.default_weapon in WEAPON_GRANT_ITEMS:
        name = ITEM_NAMES[client.default_weapon]
        weapon = client.weapons.get(name)
        if weapon is None:
            weapon = client.weapons[name] = {
                'name': name, 'image': name + '.png', 'script': ''}
            emit(client, 'on_weapon_add', name, weapon)


@handles(PacketID.PLO_STAFFGUILDS)
def handle_staff_guilds(client, data):
    # Staff guild list (packet 47).
    client.staff_guilds = parse_staff_guilds(data)


@handles(PacketID.PLO_ONLINEMODE)
def handle_login_complete(client, data):
    # Login-complete marker, blank (packet 168). GServer-v2 sends this
    # once per connection, right after PLO_HASNPCSERVER, purely to signal
    # "you have finished logging in" - see server/src/player/Player.cpp:
    # 700-709 ("This seems to inform the client that they have logged
    # in."). No payload to parse; just latch the flag.
    client.login_complete = True
    emit(client, 'on_login_complete')


@handles(PacketID.PLO_GHOSTICON)
def handle_ghost_icon(client, data):
    # Ghost icon toggle (packet 174).
    client.ghost_icon = parse_ghost_icon(data)


@handles(PacketID.PLO_STATUSLIST)
def handle_status_list(client, data):
    # Selectable player-status labels (packet 180).
    client.status_list = parse_status_list(data)


@handles(PacketID.PLO_SERVERLISTCONNECTED)
def handle_serverlist_connected(client, data):
    # PLO_SERVERLISTCONNECTED (190), blank: the server tells the client its
    # listserver link is up, so the client may log into IRC
    # (GServer-v2/server/src/player/PlayerClient.cpp:489, ServerList.cpp:368).
    # Our client has no IRC login, so there is nothing to do.
    pass


@handles(PacketID.PLO_HASNPCSERVER)
def handle_has_npc_server(client, data):
    # PLO_HASNPCSERVER (44): empty flag - the server has an npc-server, so
    # the client should not update npc props itself. Just record it.
    client.has_npc_server = True
