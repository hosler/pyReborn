"""The client handles chat, private messages, and server-pushed text windows."""

from ..packets import (
    PacketID,
    parse_chat,
    parse_private_message,
    parse_rpg_window,
    parse_say2,
    parse_server_text,
    parse_start_message,
)
from .registry import handles


@handles(PacketID.PLO_TOALL)
def handle_toall(client, data):
    # Chat message OR movement update
    # PLO_TOALL is a server-wide broadcast message only. Player movement
    # arrives via PLO_OTHERPLPROPS (8), never here.
    player_id, message = parse_chat(data)
    if message and client.on_chat:
        client.on_chat(player_id, message)


@handles(PacketID.PLO_SHOWIMG)
def handle_showimg(client, data):
    # PLO_SHOWIMG (32) - also carries level chat messages
    # Same format as PLO_TOALL for chat: gshort(player_id) + message
    player_id, message = parse_chat(data)
    if message and client.on_chat:
        client.on_chat(player_id, message)


@handles(PacketID.PLO_PRIVATEMESSAGE)
def handle_private_message(client, data):
    # PLO_PRIVATEMESSAGE (37) - private message received
    pm_info = parse_private_message(data)
    if not pm_info:
        return
    if client.on_pm:
        client.on_pm(pm_info.get('from_id', 0), pm_info.get('message', ''))
    # Engine leg: stash the waiting-PM text on the sender's persistent
    # roster wrapper (so pmswaiting()/ismasspm() answer truthfully) and
    # fire universe.onPM(other) -- the -Playerlist weapon's flash/resort
    # handler. Message set BEFORE the event fires, per the reference's
    # relog-preservation code (FourPlay TClient.cpp:3096-3105).
    host = getattr(client, 'gs2_host', None)
    if host is not None:
        host.pm_received(pm_info.get('from_id', 0),
                         pm_info.get('type', ''),
                         pm_info.get('message', ''))


@handles(PacketID.PLO_SAY2)
def handle_say2(client, data):
    # Sign-style text window pushed by the server (packet 153).
    text = parse_say2(data)
    if client.on_say2:
        client.on_say2(text)


@handles(PacketID.PLO_STARTMESSAGE)
def handle_start_message(client, data):
    # Server MOTD (packet 41).
    client.server_message = parse_start_message(data)
    if client.on_start_message:
        client.on_start_message(client.server_message)


@handles(PacketID.PLO_SERVERTEXT)
def handle_server_text(client, data):
    # Server text answer (packet 82).
    client.server_text = parse_server_text(data)
    if client.on_server_text:
        client.on_server_text(client.server_text)


@handles(PacketID.PLO_RPGWINDOW)
def handle_rpg_window(client, data):
    # RPG-style text window (packet 179).
    client.rpg_window_lines = parse_rpg_window(data)
    if client.on_rpg_window:
        client.on_rpg_window(client.rpg_window_lines)
