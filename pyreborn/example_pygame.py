#!/usr/bin/env python3
"""
pyreborn - Enhanced Pygame Client

A full-featured pygame game client with proper animations, sounds, and inventory.

Usage:
    # Launch with graphical login screen (recommended)
    python -m pyreborn.example_pygame

    # Direct connection to a server (skip login screen)
    python -m pyreborn.example_pygame <username> <password> [host] [port]

    # Via listserver with command line credentials
    python -m pyreborn.example_pygame <username> <password> --listserver [listserver_host]

Examples:
    python -m pyreborn.example_pygame
    python -m pyreborn.example_pygame myuser mypass localhost 14900
    python -m pyreborn.example_pygame myuser mypass --listserver listserver.example.com

Login Screen Controls:
    Tab         - Next field
    Shift+Tab   - Previous field
    F1          - Toggle Listserver/Direct mode
    Enter       - Connect
    Escape      - Quit

Game Controls:
    Arrow Keys  - Move
    A           - Grab/interact
    A + Arrow   - Pickup objects (bushes/pots/rocks based on glove power)
    S or Space  - Swing sword
    D           - Use equipped weapon
    Q           - Toggle inventory
    S + A       - Cycle through weapons
    Enter       - Chat
    Escape      - Quit
"""

import sys
import os
import re

try:
    import pygame
except ImportError:
    print("pygame not installed. Install with: pip install pygame")
    sys.exit(1)

from . import Client
from .listserver import ListServerClient
from .pygame_screens import LoginScreen, ServerSelectScreen, show_loading_screen
from .pygame_game import GameClient


def version_for(server, default):
    """Map a listserver entry's reported version to a client protocol version.
    "G3D*" -> 6.037, "2.*" -> 2.22; otherwise keep the default."""
    v = getattr(server, "version", "") or ""
    if v.startswith("G3D"):
        return "6.037"
    if v.startswith("2."):
        return "2.22"
    return default


def main():
    """Main entry point."""
    # Check for command line arguments
    username = None
    password = None
    use_listserver = False
    listserver_host = "listserver.example.com"
    listserver_port = 14922
    host = "localhost"
    port = 14900
    version = "6.037"  # Default version, can be overridden with --version
    servers = []        # listserver result, passed to the game for the F8 switcher

    if len(sys.argv) >= 3:
        # Credentials provided via command line
        username = sys.argv[1]
        password = sys.argv[2]

        args = sys.argv[3:]

        # Parse --version flag
        if "--version" in args or "-v" in args:
            flag_idx = args.index("--version") if "--version" in args else args.index("-v")
            if flag_idx + 1 < len(args) and not args[flag_idx + 1].startswith("-"):
                version = args[flag_idx + 1]
                args = args[:flag_idx] + args[flag_idx + 2:]  # Remove flag and value from args

        if "--listserver" in args or "-l" in args:
            use_listserver = True
            flag_idx = args.index("--listserver") if "--listserver" in args else args.index("-l")
            if flag_idx + 1 < len(args) and not args[flag_idx + 1].startswith("-"):
                listserver_host = args[flag_idx + 1]
        else:
            if len(args) >= 1:
                host = args[0]
            if len(args) >= 2:
                port = int(args[1])
    else:
        # No credentials - show login screen
        print("Starting login screen...")
        print("Usage (optional): python -m pyreborn.example_pygame [user] [pass] [host] [port] [--version VER] [--listserver [host]]")

        login_screen = LoginScreen()
        login_result = login_screen.run()

        if not login_result:
            print("Login cancelled.")
            pygame.quit()
            sys.exit(0)

        username = login_result["username"]
        password = login_result["password"]
        use_listserver = login_result["use_listserver"]
        host = login_result["host"]
        port = login_result["port"]
        listserver_host = login_result["listserver_host"]

        # Clean up pygame for re-init
        pygame.quit()

    if use_listserver:
        # Listserver mode - authenticate and show server selection
        print(f"Connecting to listserver at {listserver_host}:{listserver_port}...")
        show_loading_screen(f"Connecting to {listserver_host}...")

        ls = ListServerClient(listserver_host, listserver_port)
        response = ls.login(username, password)

        if not response.success:
            print(f"Listserver login failed: {response.error}")
            pygame.quit()
            sys.exit(1)

        print(f"Login successful! {response.status}")
        print(f"Found {len(response.servers)} servers")
        servers = response.servers  # keep for the in-game F8 server switcher

        if not response.servers:
            print("No servers available!")
            pygame.quit()
            sys.exit(1)

        # Show server selection screen
        select_screen = ServerSelectScreen(response.servers, username)
        selected_server = select_screen.run()

        if not selected_server:
            print("No server selected, exiting.")
            pygame.quit()
            sys.exit(0)

        print(f"Selected: {selected_server.display_name}")
        host = selected_server.ip
        port = selected_server.port

        # Use server's reported version to determine client version.
        version = version_for(selected_server, version)
        if selected_server.version:
            print(f"Using version {version} (server reports: {selected_server.version})")

        # Clean up pygame for re-init by GameClient
        pygame.quit()

    # Connect to game server. The listserver reports the SERVER software build
    # (e.g. "Beta 4.0.0"), not the client protocol it accepts, so our guessed
    # `version` may be wrong. When the server rejects it, it tells us what it
    # wants ("Allowed: 2.22") — parse that and retry once with the right version.
    def connect_and_login(ver):
        print(f"Connecting to {host}:{port} (version {ver})...")
        cl = Client(host, port, version=ver)
        if not cl.connect():
            # Don't hard-exit: an unreachable host (e.g. a listserver entry with
            # a "$AUTO" placeholder IP) must let the caller recover, not kill the
            # whole session mid server-switch.
            return None, "could not connect"
        print(f"Logging in as {username}...")
        if cl.login(username, password, timeout=30.0):
            return cl, None
        reason = cl.disconnect_reason
        cl.disconnect()
        return None, reason

    # Connect → play → maybe switch servers (F8) → reconnect, until quit.
    while True:
        client, reason = connect_and_login(version)
        if client is None and reason and "version" in reason.lower():
            m = re.search(r'(\d+\.\d+\d*)', reason)
            if m and m.group(1) != version:
                version = m.group(1)
                print(f"Server requires client version {version}; retrying...")
                client, reason = connect_and_login(version)

        if client is None:
            print(f"Login failed: {reason}" if reason else
                  "Login failed! (no response — wrong password or server unreachable)")
            # Recover: if we came in via the listserver, let the player pick a
            # different server instead of crashing. Otherwise there's nowhere to
            # fall back to, so exit.
            if servers:
                pick = ServerSelectScreen(servers, username).run()
                pygame.quit()
                if not pick:
                    break
                host, port = pick.ip, pick.port
                version = version_for(pick, version)
                print(f"Trying {pick.display_name} ({host}:{port}, version {version})...")
                continue
            sys.exit(1)

        print(f"Logged in! Level: {client.level}, Position: ({client.x:.1f}, {client.y:.1f})")

        # Load GMAP if available
        gmap_name = client.level if client.level.endswith('.gmap') else None
        if gmap_name:
            cache_path = f"cache/levels/{host}_{port}/{gmap_name}"
            if os.path.exists(cache_path):
                with open(cache_path) as f:
                    client.load_gmap(f.read())
                client._gmap_base_level = client._current_level_name
                print(f"Loaded GMAP: {client.gmap_width}x{client.gmap_height} grid")

                # Request adjacent levels
                count = client.request_adjacent_levels()
                print(f"Requesting {count} adjacent levels...")
                for _ in range(30):
                    client.update(timeout=0.1)
                print(f"Loaded {len(client.levels)} levels")

        # Create and run game client
        print("\nStarting game client...")
        print("Controls: Arrows=Move, A=Grab, S/Space=Sword, D=Weapon, Q=Inventory, F7=Players, F8=Servers")
        game = GameClient(client)
        game.servers = servers      # populate the in-game F8 server switcher
        switch = game.run()

        if not switch:
            break  # normal quit

        # F8: reconnect to the chosen server.
        host, port = switch.ip, switch.port
        version = version_for(switch, version)
        print(f"\nSwitching to {switch.display_name} ({host}:{port}, version {version})...")

    print("Disconnected.")


if __name__ == "__main__":
    main()
