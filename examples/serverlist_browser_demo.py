#!/usr/bin/env python3
"""
Server Browser Demo - Console-based server selection
"""

import sys
import time

sys.path.insert(0, '..')
from pyreborn import RebornClient, ServerListClient

def display_servers(servers):
    """Display server list in a nice format"""
    if not servers:
        print("No servers available.")
        return
    
    print("\n" + "="*80)
    print(f"{'#':<3} {'Server Name':<30} {'Players':<8} {'Connection':<30}")
    print("="*80)
    
    for i, server in enumerate(servers, 1):
        print(f"{i:<3} {server.name[:29]:<30} {server.player_count:<8} {server.ip}:{server.port}")
    
    print("="*80)

def main():
    """Main demo function"""
    print("PyReborn Server Browser Demo")
    print("============================")
    print()
    
    # Get credentials
    print("Please login to fetch server list:")
    username = input("Username: ").strip()
    password = input("Password: ").strip()
    
    # Connect to server list
    print("\nConnecting to server list...")
    sl_client = ServerListClient()
    
    if not sl_client.connect():
        print("Failed to connect to server list!")
        return 1
    
    print("Fetching servers...")
    if not sl_client.request_server_list(username, password, use_rc_format=True):
        print("Failed to request server list!")
        sl_client.disconnect()
        return 1
    
    # Wait for response
    time.sleep(2)
    
    # Display servers
    servers = sl_client.servers
    sl_client.disconnect()
    
    if not servers:
        print("No servers found or invalid credentials.")
        return 1
    
    display_servers(servers)
    
    # Select server
    while True:
        try:
            choice = input(f"\nSelect server (1-{len(servers)}, or 0 to quit): ")
            choice = int(choice)
            
            if choice == 0:
                print("Quitting...")
                return 0
            elif 1 <= choice <= len(servers):
                selected = servers[choice - 1]
                break
            else:
                print("Invalid choice. Please try again.")
        except ValueError:
            print("Please enter a number.")
    
    # Connect to selected server
    print(f"\nConnecting to {selected.name} at {selected.ip}:{selected.port}...")
    
    client = RebornClient(selected.ip, selected.port)
    
    if not client.connect():
        print("Failed to connect to game server!")
        return 1
    
    print("Connected to game server!")
    
    # Login with same credentials
    print(f"Logging in as {username}...")
    if not client.login(username, password):
        print("Failed to login! The server might require different credentials.")
        client.disconnect()
        return 1
    
    print("Login successful!")
    print(f"Player ID: {client.local_player.id}")
    print(f"Position: ({client.local_player.x}, {client.local_player.y})")
    print(f"Level: {client.local_player.level_name}")
    
    # Stay connected for a bit
    print("\nConnected! Press Ctrl+C to disconnect...")
    try:
        while client.connected:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nDisconnecting...")
    
    client.disconnect()
    print("Disconnected.")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())