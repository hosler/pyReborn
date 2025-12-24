"""
pyreborn - A minimal Python client for Reborn servers

Usage:
    from pyreborn import Client

    client = Client("localhost", 14900)
    client.connect()
    client.login("username", "password")
    client.move(1, 0)  # Move right
    client.say("Hello!")
    client.disconnect()

Or with context manager:
    with Client("localhost", 14900) as client:
        client.connect()
        client.login("username", "password")
        client.move(1, 0)

Or quick connect:
    from pyreborn import connect

    client = connect("username", "password")
    if client:
        client.move(1, 0)
        client.disconnect()

Or via listserver:
    from pyreborn import ListServerClient, connect_via_listserver

    # Get server list
    ls = ListServerClient("listserver.example.com", 14922)
    response = ls.login("username", "password")
    for server in response.servers:
        print(f"{server.name}: {server.ip}:{server.port}")

    # Or connect directly via listserver
    client = connect_via_listserver(
        "listserver.example.com", 14922,
        "username", "password",
        server_name="My Server"
    )

RC (Remote Control) for server administration:
    from pyreborn import RCClient, rc_connect

    # Full control
    rc = RCClient("localhost", 14900)
    rc.connect()
    rc.login("admin_account", "password")
    rc.rc_say("Hello other admins!")
    rc.kick_player(player_id)
    rc.ban_player("baduser", True, "Cheating")
    rc.disconnect()

    # Quick connect
    rc = rc_connect("admin", "password")
    if rc:
        rc.admin_message("Server maintenance in 5 minutes!")
        rc.disconnect()
"""

__version__ = "1.0.0"

from .client import Client, connect
from .player import Player
from .listserver import (
    ListServerClient,
    ServerEntry,
    ListServerResponse,
    get_server_list,
    connect_via_listserver
)
from .rc_client import RCClient, rc_connect

__all__ = [
    "Client",
    "Player",
    "connect",
    "ListServerClient",
    "ServerEntry",
    "ListServerResponse",
    "get_server_list",
    "connect_via_listserver",
    "RCClient",
    "rc_connect"
]
