#!/usr/bin/env python3
"""
Player Detection Demo
Demonstrates how to detect and track other players in PyReborn
"""

import time
from pyreborn.client import RebornClient
from pyreborn.events import EventType

def main():
    # Track all players we've seen
    players_seen = set()
    
    def on_player_added(player):
        """Called when a new player is detected"""
        players_seen.add(player.id)
        print(f"➕ New player joined: {player.nickname} (ID: {player.id})")
        print(f"   Account: {player.account}")
        print(f"   Position: ({player.x:.1f}, {player.y:.1f})")
        print(f"   Total players in level: {len(client.players)}")
        
    def on_player_removed(player):
        """Called when a player leaves"""
        if player.id in players_seen:
            players_seen.remove(player.id)
        print(f"➖ Player left: {player.nickname} (ID: {player.id})")
        print(f"   Total players in level: {len(client.players)}")
        
    def on_player_update(player):
        """Called when an existing player's properties change"""
        # Only log position changes
        if hasattr(player, '_last_pos'):
            last_x, last_y = player._last_pos
            if abs(player.x - last_x) > 0.1 or abs(player.y - last_y) > 0.1:
                print(f"🚶 {player.nickname} moved to ({player.x:.1f}, {player.y:.1f})")
        player._last_pos = (player.x, player.y)
    
    # Create and connect client
    print("🔌 Connecting to Reborn server...")
    client = RebornClient("localhost", 14900)
    
    # Subscribe to player events
    client.events.subscribe(EventType.PLAYER_ADDED, on_player_added)
    client.events.subscribe(EventType.PLAYER_REMOVED, on_player_removed)
    client.events.subscribe(EventType.OTHER_PLAYER_UPDATE, on_player_update)
    
    # Connect and login
    if not client.connect():
        print("❌ Failed to connect to server")
        return
        
    if not client.login("hosler", "1234"):
        print("❌ Failed to login")
        return
        
    print("✅ Connected successfully!")
    
    # Set our appearance
    client.set_nickname("PlayerTracker")
    client.set_chat("Tracking players...")
    
    # Show initial player list
    print("\n📊 Players currently online:")
    if client.players:
        for player_id, player in client.players.items():
            print(f"   - {player.nickname} (ID: {player_id}) at ({player.x:.1f}, {player.y:.1f})")
            players_seen.add(player_id)
    else:
        print("   (No other players detected yet)")
    
    print("\n👀 Monitoring for player activity...")
    print("Press Ctrl+C to stop\n")
    
    # Main monitoring loop
    try:
        last_status_time = time.time()
        
        while True:
            time.sleep(0.1)
            
            # Show status every 30 seconds
            if time.time() - last_status_time > 30:
                last_status_time = time.time()
                print(f"\n📊 Status Update:")
                print(f"   Players online: {len(client.players)}")
                print(f"   Players seen this session: {len(players_seen)}")
                
    except KeyboardInterrupt:
        print("\n\n🛑 Stopping player tracker...")
        
    # Disconnect cleanly
    client.disconnect()
    print("👋 Disconnected from server")
    
    # Final stats
    print(f"\n📈 Session Statistics:")
    print(f"   Total unique players seen: {len(players_seen)}")

if __name__ == "__main__":
    main()