#!/usr/bin/env python3
"""
Working Echo Bot - Detects chat through PLPROP_CURCHAT in player updates
"""

from pyreborn import RebornClient
from pyreborn.events import EventType
import time

def main():
    client = RebornClient("localhost", 14900)
    
    # Track last seen chat for each player
    last_chat = {}
    last_echo_time = {}
    
    def on_player_added(player):
        """Initialize tracking for new players"""
        last_chat[player.id] = player.chat or ""
        if player.chat:
            print(f"👋 {player.nickname} joined with chat: '{player.chat}'")
    
    def on_other_player_update(player):
        """Monitor player updates for chat changes"""
        # Skip our own updates
        if player.id == client.local_player.id:
            return
        
        # Check if chat changed
        current_chat = player.chat or ""
        previous_chat = last_chat.get(player.id, "")
        
        if current_chat and current_chat != previous_chat:
            print(f"💬 {player.nickname} says: '{current_chat}'")
            last_chat[player.id] = current_chat
            
            # Rate limit echoes per player
            current_time = time.time()
            if player.id in last_echo_time:
                if current_time - last_echo_time[player.id] < 2.0:
                    print("   (Rate limited, skipping echo)")
                    return
            
            last_echo_time[player.id] = current_time
            
            # Echo the message
            echo_msg = f"Echo: {current_chat}"
            if len(echo_msg) > 220:  # Leave room for "Echo: "
                echo_msg = echo_msg[:217] + "..."
            
            # Use set_chat to echo as a chat bubble
            client.set_chat(echo_msg)
            print(f"   ✅ Echoed: '{echo_msg}'")
    
    # Subscribe to events
    client.events.subscribe(EventType.PLAYER_ADDED, on_player_added)
    client.events.subscribe(EventType.OTHER_PLAYER_UPDATE, on_other_player_update)
    
    # Connect and login
    print("🔌 Connecting to server...")
    if not client.connect():
        print("❌ Failed to connect")
        return
    
    if not client.login("hosler", "1234"):
        print("❌ Failed to login")
        return
    
    print("✅ Connected successfully!")
    
    # Set our appearance
    client.set_nickname("EchoBot")
    client.set_chat("Say something!")
    
    # Initialize our own entry
    last_chat[client.local_player.id] = "Say something!"
    
    print("\n🤖 EchoBot is running!")
    print("The bot will echo any chat messages from other players.")
    print("Press Ctrl+C to stop.\n")
    
    # Periodically update our chat to show we're active
    last_status_update = time.time()
    status_messages = [
        "Say something!",
        "I'm listening...",
        "Echo bot active!",
        "Talk to me!"
    ]
    status_index = 0
    
    try:
        while client.connected:
            time.sleep(0.1)
            
            # Update status every 30 seconds
            if time.time() - last_status_update > 30:
                last_status_update = time.time()
                status_index = (status_index + 1) % len(status_messages)
                client.set_chat(status_messages[status_index])
                
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
    
    client.disconnect()
    print("👋 Goodbye!")

if __name__ == "__main__":
    main()