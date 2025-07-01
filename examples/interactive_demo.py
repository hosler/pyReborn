#!/usr/bin/env python3
"""
PyReborn Interactive Demo Bot
=============================

An interactive bot that demonstrates PyReborn's capabilities by responding
to player actions and commands. Type "help" in chat to see available commands.
"""

import sys
import time
import random
import math
from collections import deque
from datetime import datetime

sys.path.insert(0, '..')

from pyreborn import RebornClient

class InteractiveBot:
    def __init__(self):
        self.client = RebornClient("localhost", 14900)
        self.running = True
        self.following = None
        self.chat_history = deque(maxlen=10)
        self.last_position = None
        self.move_patterns = {
            'circle': self.move_in_circle,
            'square': self.move_in_square,
            'random': self.move_randomly
        }
        self.current_pattern = None
        self.pattern_step = 0
        self.center_x = 30
        self.center_y = 30
        
    def setup_events(self):
        """Setup event handlers"""
        self.client.events.subscribe('player_chat', self.on_player_chat)
        self.client.events.subscribe('player_moved', self.on_player_moved)
        self.client.events.subscribe('player_added', self.on_player_added)
        self.client.events.subscribe('player_removed', self.on_player_removed)
        
    def on_player_added(self, event):
        """Welcome new players"""
        player = event.get('player')
        if player and hasattr(player, 'name') and player.name != "InteractiveBot":
            self.client.set_chat(f"Welcome {player.name}! Say 'help' for commands")
            
    def on_player_removed(self, event):
        """Say goodbye to leaving players"""
        player = event.get('player')
        if player and hasattr(player, 'name'):
            if self.following and player.name == self.following:
                self.following = None
                self.client.set_chat(f"Goodbye {player.name}! Stopped following.")
            else:
                self.client.set_chat(f"Bye {player.name}!")
                
    def on_player_moved(self, event):
        """Follow a player if we're in follow mode"""
        if not self.following:
            return
            
        player = event.get('player')
        if player and hasattr(player, 'name') and player.name == self.following:
            # Calculate distance
            my_player = self.client.session.get_player()
            if my_player:
                distance = math.sqrt(
                    (player.x - my_player.x) ** 2 + 
                    (player.y - my_player.y) ** 2
                )
                
                # Follow if too far
                if distance > 2.0:
                    # Move towards the player
                    dx = player.x - my_player.x
                    dy = player.y - my_player.y
                    
                    # Normalize and move
                    if distance > 0:
                        move_x = my_player.x + (dx / distance) * 1.0
                        move_y = my_player.y + (dy / distance) * 1.0
                        self.client.move_to(move_x, move_y)
                        
    def on_player_chat(self, event):
        """Respond to player chat commands"""
        player = event.get('player')
        message = event.get('message', '').lower().strip()
        
        if not player or not hasattr(player, 'name'):
            return
            
        # Add to chat history
        self.chat_history.append({
            'player': player.name,
            'message': message,
            'time': datetime.now()
        })
        
        # Process commands
        if message == 'help':
            self.show_help()
        elif message.startswith('follow me'):
            self.start_following(player.name)
        elif message == 'stop':
            self.stop_following()
        elif message.startswith('move '):
            self.process_move_command(message[5:])
        elif message.startswith('say '):
            self.client.set_chat(message[4:])
        elif message == 'dance':
            self.dance()
        elif message == 'stats':
            self.show_stats()
        elif message.startswith('tile '):
            self.check_tile(message[5:])
        elif message in ['hi', 'hello', 'hey']:
            self.client.set_chat(f"Hello {player.name}! 👋")
        elif 'bot' in message:
            responses = [
                "Yes, I'm a bot! 🤖",
                "Beep boop! How can I help?",
                "That's me! Try 'help' for commands",
                f"Hello {player.name}! I'm InteractiveBot"
            ]
            self.client.set_chat(random.choice(responses))
            
    def show_help(self):
        """Show available commands"""
        commands = [
            "Commands: help, follow me, stop, dance",
            "move [circle/square/random], stats",
            "say [message], tile [x,y]",
            "Just say 'hi' to greet me!"
        ]
        
        for cmd in commands:
            self.client.set_chat(cmd)
            time.sleep(2)
            
    def start_following(self, player_name):
        """Start following a player"""
        self.following = player_name
        self.current_pattern = None
        self.client.set_chat(f"Following {player_name}! Say 'stop' to stop")
        
    def stop_following(self):
        """Stop following or moving"""
        if self.following:
            self.client.set_chat(f"Stopped following {self.following}")
            self.following = None
        elif self.current_pattern:
            self.client.set_chat("Stopped moving pattern")
            self.current_pattern = None
        else:
            self.client.set_chat("I wasn't doing anything!")
            
    def process_move_command(self, pattern):
        """Process movement pattern commands"""
        if pattern in self.move_patterns:
            self.current_pattern = pattern
            self.pattern_step = 0
            self.following = None
            
            # Get current position as center
            my_player = self.client.session.get_player()
            if my_player:
                self.center_x = my_player.x
                self.center_y = my_player.y
                
            self.client.set_chat(f"Moving in {pattern} pattern!")
        else:
            self.client.set_chat("Try: move circle, move square, or move random")
            
    def move_in_circle(self):
        """Move in a circle pattern"""
        radius = 5
        angle = (self.pattern_step * 30) * math.pi / 180  # 30 degrees per step
        
        x = self.center_x + radius * math.cos(angle)
        y = self.center_y + radius * math.sin(angle)
        
        self.client.move_to(x, y)
        self.pattern_step = (self.pattern_step + 1) % 12
        
    def move_in_square(self):
        """Move in a square pattern"""
        size = 8
        positions = [
            (self.center_x - size/2, self.center_y - size/2),
            (self.center_x + size/2, self.center_y - size/2),
            (self.center_x + size/2, self.center_y + size/2),
            (self.center_x - size/2, self.center_y + size/2)
        ]
        
        pos = positions[self.pattern_step % 4]
        self.client.move_to(pos[0], pos[1])
        self.pattern_step += 1
        
    def move_randomly(self):
        """Move to random positions"""
        x = self.center_x + random.uniform(-10, 10)
        y = self.center_y + random.uniform(-10, 10)
        
        # Keep within reasonable bounds
        x = max(5, min(59, x))
        y = max(5, min(59, y))
        
        self.client.move_to(x, y)
        
    def dance(self):
        """Perform a dance by changing appearance rapidly"""
        self.client.set_chat("💃 Dancing! 🕺")
        
        # Save current appearance
        my_player = self.client.session_manager.get_player()
        original_head = my_player.head_image if my_player else "head0.png"
        original_body = my_player.body_image if my_player else "body0.png"
        
        # Dance moves
        for i in range(8):
            head = f"head{i % 4}.png"
            body = f"body{i % 4}.png"
            self.client.set_head_image(head)
            self.client.set_body_image(body)
            
            # Also spin around
            x_offset = math.cos(i * math.pi / 4) * 0.5
            y_offset = math.sin(i * math.pi / 4) * 0.5
            
            if my_player:
                self.client.move_to(my_player.x + x_offset, my_player.y + y_offset)
                
            time.sleep(0.5)
            
        # Restore original appearance
        self.client.set_head_image(original_head)
        self.client.set_body_image(original_body)
        self.client.set_chat("Dance complete! 🎉")
        
    def show_stats(self):
        """Show current statistics"""
        level = self.client.level_manager.get_current_level()
        my_player = self.client.session_manager.get_player()
        
        if level:
            self.client.set_chat(f"Level: {level.name}, Players: {len(level.players)}")
            time.sleep(2)
            
        if my_player:
            self.client.set_chat(f"Position: ({my_player.x:.1f}, {my_player.y:.1f})")
            time.sleep(2)
            
        self.client.set_chat(f"Chat history: {len(self.chat_history)} messages")
        
    def check_tile(self, coords):
        """Check tile at given coordinates"""
        try:
            parts = coords.replace(',', ' ').split()
            if len(parts) >= 2:
                x = int(parts[0])
                y = int(parts[1])
                
                level = self.client.level_manager.get_current_level()
                if level and hasattr(level, 'get_board_tile_id'):
                    tile_id = level.get_board_tile_id(x, y)
                    tx, ty, px, py = level.tile_to_tileset_coords(tile_id)
                    self.client.set_chat(f"Tile at ({x},{y}): ID {tile_id}, tileset ({tx},{ty})")
                else:
                    self.client.set_chat("No level data available")
            else:
                self.client.set_chat("Usage: tile x,y (e.g., tile 30,30)")
        except Exception as e:
            self.client.set_chat(f"Error: {str(e)}")
            
    def update_movement(self):
        """Update movement patterns"""
        if self.current_pattern and self.current_pattern in self.move_patterns:
            self.move_patterns[self.current_pattern]()
            
    def run(self):
        """Main bot loop"""
        print("Interactive Bot Starting...")
        print("=" * 50)
        
        # Connect
        print("Connecting...")
        if not self.client.connect():
            print("Failed to connect!")
            return 1
            
        print("Logging in...")
        if not self.client.login("interactivebot", "1234"):
            print("Login failed!")
            return 1
            
        print("Setting up...")
        self.setup_events()
        self.client.set_nickname("InteractiveBot")
        self.client.set_chat("Interactive Bot Online! Say 'help' for commands")
        
        print("\nBot is running! Press Ctrl+C to stop")
        print("=" * 50)
        
        # Main loop
        last_update = time.time()
        
        try:
            while self.running:
                current_time = time.time()
                
                # Update movement patterns every second
                if current_time - last_update >= 1.0:
                    self.update_movement()
                    last_update = current_time
                    
                time.sleep(0.1)
                
        except KeyboardInterrupt:
            print("\nShutting down...")
            self.running = False
            
        self.client.set_chat("Goodbye! 👋")
        time.sleep(1)
        self.client.disconnect()
        
        print("Bot stopped.")
        return 0

def main():
    """Main entry point"""
    print("\n🤖 PyReborn Interactive Demo Bot")
    print("=" * 50)
    print("\nThis bot responds to player commands:")
    print("- help: Show available commands")
    print("- follow me: Bot will follow you")
    print("- move [pattern]: Make bot move in patterns")
    print("- dance: Make the bot dance")
    print("- stats: Show current statistics")
    print("- tile x,y: Check tile information")
    print("\nRequirements:")
    print("- GServer running on localhost:14900")
    print("- Account 'interactivebot' with password '1234'")
    print()
    
    bot = InteractiveBot()
    return bot.run()

if __name__ == "__main__":
    sys.exit(main())