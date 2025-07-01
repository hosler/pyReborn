#!/usr/bin/env python3
"""
Echo Bot - Repeats everything said in chat
"""

from pyreborn import RebornClient
from pyreborn.events import EventType
import time
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def main():
    client = RebornClient("localhost", 14900)
    
    # Keep track of last echo to avoid infinite loops
    last_echo_time = {}
    last_chat = {}
    
    def on_player_added(player):
        """Track new players"""
        last_chat[player.id] = player.chat or ""
        logging.info(f"Player joined: {player.nickname} (ID: {player.id})")
    
    def on_player_update(player):
        """Monitor player chat bubble changes"""
        # Skip our own updates
        if player.id == client.local_player.id:
            return
        
        # Check if chat changed
        current_chat = player.chat or ""
        previous_chat = last_chat.get(player.id, "")
        
        if current_chat and current_chat != previous_chat:
            last_chat[player.id] = current_chat
            logging.info(f"Chat detected from {player.nickname}: {current_chat}")
            
            # Rate limit echoes per player
            current_time = time.time()
            if player.id in last_echo_time:
                if current_time - last_echo_time[player.id] < 2.0:
                    return
                    
            last_echo_time[player.id] = current_time
            
            # Echo the message
            echo_msg = f"Echo: {current_chat}"
            if len(echo_msg) > 200:  # Respect chat limits
                echo_msg = echo_msg[:197] + "..."
                
            client.set_chat(echo_msg)
            logging.info(f"Echoed: {echo_msg}")
    
    # Subscribe to player events to monitor chat changes
    client.events.subscribe(EventType.PLAYER_ADDED, on_player_added)
    client.events.subscribe(EventType.OTHER_PLAYER_UPDATE, on_player_update)
    
    # Connect and run
    if client.connect():
        logging.info("Connected to server")
        
        if client.login("hosler", "1234"):
            logging.info("Login successful")
            
            # Set appearance
            client.set_nickname("EchoBot")
            client.set_head_image("head1.png")
            client.set_body_image("body1.png")
            client.set_chat("I repeat what you say!")
            
            # Move to a visible spot
            client.move_to(32, 32)
            
            try:
                logging.info("EchoBot is running. Press Ctrl+C to stop.")
                while client.connected:
                    time.sleep(0.1)
            except KeyboardInterrupt:
                logging.info("Shutting down...")
            finally:
                client.disconnect()
        else:
            logging.error("Login failed")
    else:
        logging.error("Connection failed")

if __name__ == "__main__":
    main()