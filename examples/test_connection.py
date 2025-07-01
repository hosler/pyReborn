#!/usr/bin/env python3
"""
PyReborn Connection Test

A simple script to test connection to a GServer.
"""

import sys
import time
from pyreborn import RebornClient, EventType


def main():
    """Main function for the connection test."""
    print("PyReborn Connection Test")
    print("========================")
    
    # Get connection details
    host = input("Server host (default: localhost): ").strip() or "localhost"
    port_str = input("Server port (default: 14900): ").strip() or "14900"
    
    try:
        port = int(port_str)
    except ValueError:
        print("Invalid port number!")
        return 1
    
    account = input("Account name: ").strip()
    password = input("Password: ").strip()
    
    if not account or not password:
        print("Account and password are required!")
        return 1
    
    # Create client
    client = RebornClient(host, port)
    
    # Event handlers
    def on_connected():
        print("✅ Connected to server!")
    
    def on_login_success():
        print("✅ Login successful!")
        
        # Set a test nickname
        client.set_nickname("PyTest")
        client.say("Hello from PyReborn! 🐍")
        
        # Show current position
        if client.local_player:
            x, y = client.local_player.x, client.local_player.y
            print(f"📍 Position: ({x}, {y})")
    
    def on_chat(player_id, message):
        player = client.get_player_by_id(player_id)
        if player:
            print(f"💬 {player.nickname}: {message}")
        else:
            print(f"💬 Player {player_id}: {message}")
    
    def on_player_added(player):
        print(f"👋 {player.nickname} joined at ({player.x}, {player.y})")
    
    def on_player_removed(player):
        print(f"🚪 {player.nickname} left")
    
    # Subscribe to events
    client.on(EventType.CONNECTED, on_connected)
    client.on(EventType.LOGIN_SUCCESS, on_login_success)
    client.on(EventType.CHAT_MESSAGE, on_chat)
    client.on(EventType.PLAYER_ADDED, on_player_added)
    client.on(EventType.PLAYER_REMOVED, on_player_removed)
    
    # Connect and test
    print(f"\n🔄 Connecting to {host}:{port}...")
    
    if not client.connect():
        print("❌ Failed to connect to server!")
        return 1
    
    print("🔄 Logging in...")
    if not client.login(account, password):
        print("❌ Login failed!")
        client.disconnect()
        return 1
    
    print("\n✅ Connection test successful!")
    print("📊 Keeping connection alive for 30 seconds...")
    print("💬 Watch for chat messages and player activity.")
    print("Press Ctrl+C to exit early.")
    
    try:
        # Keep alive for 30 seconds
        for i in range(30):
            time.sleep(1)
            
            # Show stats every 5 seconds
            if i % 5 == 0 and i > 0:
                player_count = len(client.get_all_players())
                print(f"📊 Players online: {player_count}")
    
    except KeyboardInterrupt:
        print("\n⏹️  Interrupted by user")
    
    print("🔄 Disconnecting...")
    client.disconnect()
    print("✅ Test completed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())