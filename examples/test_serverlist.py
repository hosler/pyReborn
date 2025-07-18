#!/usr/bin/env python3
"""Test server list functionality"""

import sys
import time
from pyreborn import ServerListClient


def main():
    """Test server list connection"""
    print("PyReborn Server List Test")
    print("========================")
    print()
    
    # Get credentials
    account = input("Account (default: hosler): ").strip() or "hosler"
    password = input("Password (default: 1234): ").strip() or "1234"
    
    # Create server list client
    client = ServerListClient()  # defaults to listserver.graal.in
    
    # Set up callbacks
    def on_server_list(servers):
        print(f"\nReceived {len(servers)} servers:")
        for i, server in enumerate(servers):
            print(f"{i+1}. {server}")
    
    def on_status(message):
        print(f"\nStatus: {message}")
    
    def on_error(message):
        print(f"\nError: {message}")
    
    client.set_callbacks(on_server_list, on_status, on_error)
    
    # Connect
    print("\nConnecting to server list...")
    if not client.connect():
        print("Failed to connect!")
        return 1
    
    print("Connected!")
    
    # Request server list
    print("Requesting server list...")
    if not client.request_server_list(account, password):
        print("Failed to request server list!")
        client.disconnect()
        return 1
    
    # Wait for response
    print("Waiting for response...")
    time.sleep(2)
    
    # Display results
    if client.servers:
        print(f"\nAvailable servers:")
        for i, server in enumerate(client.servers):
            print(f"\n{i+1}. {server.name}")
            print(f"   Type: {server.type}")
            print(f"   Players: {server.player_count}")
            print(f"   Description: {server.description}")
            print(f"   Connection: {server.ip}:{server.port}")
    else:
        print("\nNo servers available or authentication failed.")
    
    # Disconnect
    client.disconnect()
    print("\nDisconnected.")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())