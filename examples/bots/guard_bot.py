#!/usr/bin/env python3
"""
Guard Bot - Guards an area and warns/chases away intruders
"""

from pyreborn import RebornClient
from pyreborn.events import EventType
import math
import time
import logging
import threading

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class GuardBot:
    def __init__(self, client, guard_x, guard_y, guard_radius=8):
        self.client = client
        self.guard_x = guard_x
        self.guard_y = guard_y
        self.guard_radius = guard_radius
        self.warning_radius = guard_radius + 3
        self.warned_players = {}  # player_name -> last_warning_time
        self.chasing = None
        self.return_thread = None
        
    def distance_to_guard_post(self, x, y):
        """Calculate distance from a position to the guard post"""
        return math.sqrt((x - self.guard_x) ** 2 + (y - self.guard_y) ** 2)
        
    def on_player_update(self, player):
        """Check if player is entering guarded area"""
        # Don't guard against ourselves
        if player.id == self.client.local_player.id:
            return
            
        dist = self.distance_to_guard_post(player.x, player.y)
        current_time = time.time()
        
        # Check if player is in warning zone
        if dist < self.warning_radius:
            # Check if we've warned this player recently
            player_key = player.nickname or f"Player{player.id}"
            last_warning = self.warned_players.get(player_key, 0)
            
            if current_time - last_warning > 5.0:  # Warn every 5 seconds
                if dist < self.guard_radius:
                    # Player is too close - chase them!
                    self.chase_player(player)
                    self.client.set_chat(f"Get out, {player.nickname}!")
                    logging.info(f"Chasing {player.nickname} away from guard post")
                else:
                    # Just warn them
                    self.client.set_chat(f"Stay back, {player.nickname}!")
                    logging.info(f"Warning {player.nickname} - distance: {dist:.1f}")
                    
                self.warned_players[player_key] = current_time
                
    def chase_player(self, player):
        """Chase a player away from the guard post"""
        self.chasing = player.nickname or f"Player{player.id}"
        
        # Calculate direction to player
        dx = player.x - self.client.local_player.x
        dy = player.y - self.client.local_player.y
        
        # Normalize and move towards them
        if dx != 0 or dy != 0:
            length = math.sqrt(dx*dx + dy*dy)
            move_x = dx/length * 3  # Move 3 tiles towards them
            move_y = dy/length * 3
            
            self.client.move(move_x, move_y)
            
            # Schedule return to post
            self.schedule_return_to_post()
            
    def schedule_return_to_post(self):
        """Return to guard post after chasing"""
        if self.return_thread and self.return_thread.is_alive():
            return
            
        def return_to_post():
            time.sleep(2.0)  # Wait 2 seconds
            if self.client.connected:
                self.client.move_to(self.guard_x, self.guard_y)
                self.client.set_chat("Returning to post...")
                self.chasing = None
                logging.info("Returning to guard post")
                
        self.return_thread = threading.Thread(target=return_to_post)
        self.return_thread.daemon = True
        self.return_thread.start()
        
    def on_player_removed(self, player):
        """Clean up when player leaves"""
        player_key = player.nickname or f"Player{player.id}"
        if player_key in self.warned_players:
            del self.warned_players[player_key]
            
        if self.chasing == player_key:
            self.client.set_chat("Good riddance!")
            self.chasing = None

def main():
    client = RebornClient("localhost", 14900)
    
    # Guard position (center of map)
    guard_x, guard_y = 32, 32
    guard_radius = 8
    
    # Create guard bot
    guard = GuardBot(client, guard_x, guard_y, guard_radius)
    
    # Subscribe to events
    client.events.subscribe(EventType.OTHER_PLAYER_UPDATE, guard.on_player_update)
    client.events.subscribe(EventType.PLAYER_REMOVED, guard.on_player_removed)
    
    # Handle chat commands
    last_chat = {}
    
    def on_player_added(player):
        """Initialize chat tracking"""
        last_chat[player.id] = player.chat or ""
    
    def on_chat_update(player):
        """Handle chat commands"""
        # Skip our own updates
        if player.id == client.local_player.id:
            return
            
        # Check if chat changed
        current_chat = player.chat or ""
        previous_chat = last_chat.get(player.id, "")
        
        if current_chat and current_chat != previous_chat:
            last_chat[player.id] = current_chat
            message = current_chat.lower()
            
            if message == "!radius":
                client.set_chat(f"Guard radius: {guard.guard_radius} tiles")
                
            elif message.startswith("!radius "):
                try:
                    new_radius = float(message.split()[1])
                    guard.guard_radius = max(3, min(20, new_radius))
                    guard.warning_radius = guard.guard_radius + 3
                    client.set_chat(f"Guard radius set to {guard.guard_radius}")
                except:
                    client.set_chat("Usage: !radius <number>")
                    
            elif message == "!post":
                client.set_chat(f"Guarding ({guard.guard_x}, {guard.guard_y})")
            
    client.events.subscribe(EventType.PLAYER_ADDED, on_player_added)
    client.events.subscribe(EventType.OTHER_PLAYER_UPDATE, on_chat_update)
    
    # Connect and run
    if client.connect():
        logging.info("Connected to server")
        
        if client.login("hosler", "1234"):
            logging.info("Login successful")
            
            # Set appearance
            client.set_nickname("GuardBot")
            client.set_head_image("head3.png")
            client.set_body_image("body3.png")
            # Note: Shield and sword appearances are typically set by power levels,
            # not by direct image setting. You would need to pick up shield/sword items
            # to change these appearances.
            
            # Move to guard position
            client.move_to(guard_x, guard_y)
            client.set_chat("No trespassing! Keep your distance!")
            
            # Show guard area visually by moving in a small circle
            def show_guard_area():
                for i in range(4):
                    angle = (math.pi / 2) * i
                    x = guard_x + 2 * math.cos(angle)
                    y = guard_y + 2 * math.sin(angle)
                    client.move_to(x, y)
                    time.sleep(0.3)
                client.move_to(guard_x, guard_y)
                
            threading.Thread(target=show_guard_area, daemon=True).start()
            
            try:
                logging.info(f"GuardBot is protecting area around ({guard_x}, {guard_y}). Press Ctrl+C to stop.")
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