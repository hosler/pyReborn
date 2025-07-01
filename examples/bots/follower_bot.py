#!/usr/bin/env python3
"""
Follower Bot Example - follows a target player and mimics their actions
"""

import sys
import time
import math
import threading
sys.path.insert(0, '../..')

from pyreborn import RebornClient

class PlayerFollower:
    def __init__(self, client, target_name):
        self.client = client
        self.target_player = None
        self.target_name = target_name.lower()
        self.following = False
        self.follow_distance = 1.5  # Stay within 1.5 tiles
        self.running = True
        
        # Subscribe to events
        self.client.events.subscribe('player_moved', self.on_player_moved)
        self.client.events.subscribe('player_chat', self.on_player_chat)
        self.client.events.subscribe('player_props_changed', self.on_player_props_changed)
        self.client.events.subscribe('level_changed', self.on_level_changed)
    
    def find_target_player(self):
        """Find target player in current level"""
        level = self.client.level_manager.get_current_level()
        if not level:
            return None
            
        for player_id, player in level.players.items():
            if hasattr(player, 'name') and player.name.lower() == self.target_name:
                return player
        return None
    
    def calculate_distance(self, x1, y1, x2, y2):
        """Calculate distance between two points"""
        return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
    
    def follow_target(self):
        """Move towards target if too far away"""
        if not self.target_player:
            return
            
        my_player = self.client.session_manager.get_player()
        if not my_player:
            return
            
        distance = self.calculate_distance(
            my_player.x, my_player.y,
            self.target_player.x, self.target_player.y
        )
        
        if distance > self.follow_distance:
            # Move closer to target
            dx = self.target_player.x - my_player.x
            dy = self.target_player.y - my_player.y
            
            if distance > 0:
                move_x = my_player.x + (dx / distance) * 0.7
                move_y = my_player.y + (dy / distance) * 0.7
                
                print(f"Following {self.target_name} to ({move_x:.1f}, {move_y:.1f})")
                self.client.move_to(move_x, move_y)
    
    def on_player_moved(self, event):
        """Handle player movement"""
        player = event.get('player')
        if not player or not hasattr(player, 'name'):
            return
            
        if player.name.lower() == self.target_name:
            self.target_player = player
            threading.Timer(0.5, self.follow_target).start()
    
    def on_player_chat(self, event):
        """Mimic player chat"""
        player = event.get('player')
        message = event.get('message', '')
        
        if player and hasattr(player, 'name') and player.name.lower() == self.target_name:
            def mimic_chat():
                time.sleep(1)
                mimic_message = f"*copies {player.name}* {message}"
                self.client.set_chat(mimic_message)
            
            threading.Timer(1, mimic_chat).start()
    
    def on_player_props_changed(self, event):
        """Mimic appearance changes"""
        player = event.get('player')
        if player and hasattr(player, 'name') and player.name.lower() == self.target_name:
            def mimic_appearance():
                time.sleep(2)
                try:
                    if hasattr(player, 'head_image'):
                        self.client.set_head_image(player.head_image)
                    if hasattr(player, 'body_image'):
                        self.client.set_body_image(player.body_image)
                except Exception as e:
                    print(f"Error copying appearance: {e}")
            
            threading.Timer(2, mimic_appearance).start()
    
    def on_level_changed(self, event):
        """Find target in new level"""
        self.target_player = self.find_target_player()
        if self.target_player:
            print(f"Found {self.target_name} in new level!")
    
    def start(self):
        """Start following"""
        self.target_player = self.find_target_player()
        if self.target_player:
            print(f"Found target: {self.target_name}")
            self.following = True
        else:
            print(f"Target {self.target_name} not found")
        
        while self.running:
            try:
                if self.target_player:
                    self.follow_target()
                time.sleep(2)
            except KeyboardInterrupt:
                break
    
    def stop(self):
        self.running = False

def main():
    """Follower bot example"""
    if len(sys.argv) < 2:
        print("Usage: python follower_bot.py <target_player_name>")
        return 1
    
    target_name = sys.argv[1]
    print(f"Follower Bot - Target: {target_name}")
    print("=" * 40)
    
    client = RebornClient("localhost", 14900)
    
    if not client.connect():
        return 1
    
    if not client.login("followerbot", "1234"):
        return 1
    
    client.set_nickname("FollowerBot")
    client.set_chat(f"Following {target_name}!")
    
    follower = PlayerFollower(client, target_name)
    
    try:
        follower.start()
    except KeyboardInterrupt:
        pass
    
    follower.stop()
    client.disconnect()
    return 0

if __name__ == "__main__":
    sys.exit(main())