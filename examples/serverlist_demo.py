#!/usr/bin/env python3
"""
Comprehensive Server List Demo

This example shows how to:
1. Connect to a server list
2. Authenticate
3. Retrieve available servers
4. Connect to a selected server
"""

import sys
import time
from typing import Optional

sys.path.insert(0, '..')
from pyreborn import RebornClient, ServerListClient, ServerInfo


def display_servers(servers: list[ServerInfo]):
    """Display server list in a nice format"""
    if not servers:
        print("No servers available.")
        return
    
    print("\n" + "="*80)
    print(f"{'#':<3} {'Server Name':<25} {'Type':<10} {'Players':<8} {'Connection':<20}")
    print("="*80)
    
    for i, server in enumerate(servers, 1):
        print(f"{i:<3} {server.name[:24]:<25} {server.type:<10} "
              f"{server.player_count:<8} {server.ip}:{server.port:<20}")
    
    print("="*80)
    print(f"Total servers: {len(servers)}")


def select_server_interactive(servers: list[ServerInfo]) -> Optional[ServerInfo]:
    """Let user select a server interactively"""
    if not servers:
        return None
    
    while True:
        try:
            choice = input(f"\nSelect server (1-{len(servers)}, or 0 to cancel): ")
            choice = int(choice)
            
            if choice == 0:
                return None
            elif 1 <= choice <= len(servers):
                return servers[choice - 1]
            else:
                print("Invalid choice. Please try again.")
        except ValueError:
            print("Please enter a number.")


def main():
    """Main demo function"""
    print("PyReborn Server List Demo")
    print("========================")
    print()
    
    # Configuration
    serverlist_host = input("Server list host (default: listserver.graal.in): ").strip() or "listserver.graal.in"
    serverlist_port = input("Server list port (default: 14922): ").strip() or "14922"
    
    try:
        serverlist_port = int(serverlist_port)
    except:
        print("Invalid port, using default 14922")
        serverlist_port = 14922
    
    # Create server list client
    print(f"\nConnecting to server list at {serverlist_host}:{serverlist_port}...")
    sl_client = ServerListClient(serverlist_host, serverlist_port)
    
    # Setup callbacks
    servers_received = []
    status_messages = []
    error_messages = []
    
    def on_servers(servers):
        servers_received.extend(servers)
        print(f"\nReceived {len(servers)} servers from server list")
    
    def on_status(msg):
        status_messages.append(msg)
        print(f"Status: {msg}")
    
    def on_error(msg):
        error_messages.append(msg)
        print(f"Error: {msg}")
    
    sl_client.set_callbacks(on_servers, on_status, on_error)
    
    # Connect to server list
    if not sl_client.connect():
        print("Failed to connect to server list!")
        return 1
    
    print("Connected to server list!")
    
    # Authenticate
    print("\nServer List Authentication:")
    account = input("Account name: ").strip()
    password = input("Password: ").strip()
    
    print("\nAuthenticating...")
    if not sl_client.request_server_list(account, password):
        print("Failed to send authentication request!")
        sl_client.disconnect()
        return 1
    
    # Wait for response
    print("Waiting for server list...")
    time.sleep(2)
    
    # Check results
    if error_messages:
        print(f"\nAuthentication failed: {error_messages[-1]}")
        sl_client.disconnect()
        return 1
    
    if not servers_received:
        print("\nNo servers received. This could mean:")
        print("- Invalid credentials")
        print("- No servers are currently online")
        print("- Network issues")
        sl_client.disconnect()
        return 1
    
    # Display servers
    display_servers(servers_received)
    
    # Server selection
    selected = select_server_interactive(servers_received)
    
    if not selected:
        print("\nNo server selected.")
        sl_client.disconnect()
        return 0
    
    print(f"\nSelected: {selected.name}")
    print(f"Description: {selected.description}")
    print(f"Players online: {selected.player_count}")
    print(f"Connection info: {selected.ip}:{selected.port}")
    
    # Disconnect from server list
    sl_client.disconnect()
    
    # Ask if user wants to connect
    connect = input("\nConnect to this server? (y/n): ").strip().lower()
    if connect != 'y':
        print("Not connecting.")
        return 0
    
    # Connect to game server
    print(f"\nConnecting to game server at {selected.ip}:{selected.port}...")
    
    game_client = RebornClient(selected.ip, selected.port)
    
    if not game_client.connect():
        print("Failed to connect to game server!")
        return 1
    
    print("Connected to game server!")
    
    # Login to game server
    game_account = input("\nGame account (press Enter to use same): ").strip() or account
    game_password = input("Game password (press Enter to use same): ").strip() or password
    
    print("\nLogging in...")
    if not game_client.login(game_account, game_password):
        print("Failed to login to game server!")
        game_client.disconnect()
        return 1
    
    print("Login successful!")
    print(f"Player ID: {game_client.local_player.id}")
    print(f"Nickname: {game_client.local_player.nickname}")
    print(f"Position: ({game_client.local_player.x}, {game_client.local_player.y})")
    
    # Stay connected for a bit
    print("\nConnected! Press Ctrl+C to disconnect...")
    try:
        while game_client.connected:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nDisconnecting...")
    
    game_client.disconnect()
    print("Disconnected.")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())