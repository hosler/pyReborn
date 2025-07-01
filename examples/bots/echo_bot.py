#!/usr/bin/env python3
"""
Echo Bot - Repeats everything said in chat
"""

from pyreborn import RebornClient
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
    
    def on_chat(event):
        player = event['player']
        message = event['message']
        
        # Don't echo our own messages
        if player.name == client.account_name:
            return
            
        # Rate limit echoes per player
        current_time = time.time()
        if player.name in last_echo_time:
            if current_time - last_echo_time[player.name] < 2.0:
                return
                
        last_echo_time[player.name] = current_time
        
        # Echo the message
        echo_msg = f"Echo: {message}"
        if len(echo_msg) > 200:  # Respect chat limits
            echo_msg = echo_msg[:200] + "..."
            
        client.set_chat(echo_msg)
        logging.info(f"Echoed {player.nickname}: {message}")
    
    # Subscribe to chat events
    client.events.subscribe('player_chat', on_chat)
    
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