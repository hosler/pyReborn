#!/usr/bin/env python3
"""
Bot that follows SpaceManSpiff around
"""

import time
import math
from pyreborn import GraalClient, EventType

class SpaceManSpiffFollower:
    def __init__(self):
        self.client = GraalClient("localhost", 14900)
        self.spaceman_id = None
        self.spaceman_position = None
        self.last_move_time = 0
        self.follow_distance = 2.0  # Stay 2 tiles away
        self.move_cooldown = 0.3  # Don't move more than once per 300ms
        
        # Setup event handlers
        self.client.on(EventType.PLAYER_ADDED, self.on_player_added)
        self.client.on(EventType.OTHER_PLAYER_UPDATE, self.on_player_update)
        self.client.on(EventType.PLAYER_REMOVED, self.on_player_removed)
        
    def on_player_added(self, player):
        if player.nickname and "SpaceManSpiff" in player.nickname:
            self.spaceman_id = player.id
            self.spaceman_position = (player.x, player.y)
            print(f"🎯 Found SpaceManSpiff! (ID: {player.id}) at ({player.x}, {player.y})")
            self.client.say(f"Hello SpaceManSpiff! I'm your new follower bot!")
    
    def on_player_update(self, player):
        # Check if this is SpaceManSpiff
        if player.nickname and "SpaceManSpiff" in player.nickname:
            if self.spaceman_id is None:
                self.spaceman_id = player.id
                print(f"🎯 Tracking SpaceManSpiff! (ID: {player.id})")
                self.client.say("Found you! Following mode activated!")
            
            # Update position
            old_pos = self.spaceman_position
            self.spaceman_position = (player.x, player.y)
            
            # Check if SpaceManSpiff moved significantly
            if old_pos:
                distance_moved = self.calculate_distance(old_pos, self.spaceman_position)
                if distance_moved > 0.5:  # Only print if moved more than half a tile
                    print(f"📍 SpaceManSpiff moved to ({player.x}, {player.y})")
            
            # Try to follow
            self.follow_spaceman()
    
    def on_player_removed(self, player):
        if player.id == self.spaceman_id:
            print("😢 SpaceManSpiff left! Waiting for return...")
            self.spaceman_id = None
            self.spaceman_position = None
            self.client.say("SpaceManSpiff left... I'll wait here for you!")
    
    def calculate_distance(self, pos1, pos2):
        """Calculate distance between two positions"""
        if not pos1 or not pos2:
            return float('inf')
        dx = pos2[0] - pos1[0]
        dy = pos2[1] - pos1[1]
        return math.sqrt(dx * dx + dy * dy)
    
    def get_direction_to(self, target_x, target_y):
        """Get movement direction toward target"""
        my_x = self.client.local_player.x
        my_y = self.client.local_player.y
        
        dx = target_x - my_x
        dy = target_y - my_y
        
        # Return direction vector (normalized if needed)
        distance = math.sqrt(dx * dx + dy * dy)
        if distance == 0:
            return 0, 0
        return dx / distance, dy / distance
    
    def follow_spaceman(self):
        """Follow SpaceManSpiff while maintaining distance"""
        if not self.spaceman_position:
            return
            
        current_time = time.time()
        if current_time - self.last_move_time < self.move_cooldown:
            return  # Still in cooldown
        
        my_x = self.client.local_player.x
        my_y = self.client.local_player.y
        target_x, target_y = self.spaceman_position
        
        # Calculate distance to SpaceManSpiff
        distance = self.calculate_distance((my_x, my_y), (target_x, target_y))
        
        # Determine if we need to move
        move_needed = False
        new_x, new_y = my_x, my_y
        
        if distance > self.follow_distance + 1.0:
            # Too far away - move closer
            move_needed = True
            # Move toward SpaceManSpiff but stop at follow_distance
            dx, dy = self.get_direction_to(target_x, target_y)
            move_distance = min(1.0, distance - self.follow_distance)
            new_x = my_x + dx * move_distance
            new_y = my_y + dy * move_distance
            
        elif distance < self.follow_distance - 0.5:
            # Too close - back away slightly
            move_needed = True
            dx, dy = self.get_direction_to(target_x, target_y)
            move_distance = 0.5
            new_x = my_x - dx * move_distance
            new_y = my_y - dy * move_distance
        
        # Perform the move
        if move_needed:
            # Determine sprite direction
            dx = new_x - my_x
            dy = new_y - my_y
            
            if abs(dx) > abs(dy):
                sprite = 1 if dx > 0 else 3  # Right : Left
            else:
                sprite = 2 if dy > 0 else 0  # Down : Up
            
            # Move and update direction
            from pyreborn.protocol.enums import Direction
            direction_map = {0: Direction.UP, 1: Direction.RIGHT, 2: Direction.DOWN, 3: Direction.LEFT}
            
            self.client.move_to(new_x, new_y, direction_map.get(sprite, Direction.DOWN))
            self.last_move_time = current_time
            
            # Occasional chat
            if distance > 5:
                if current_time % 10 < 1:  # Every ~10 seconds when far
                    self.client.say("Wait for me SpaceManSpiff!")
    
    def run(self):
        """Main bot loop"""
        print("🤖 SpaceManSpiff Follower Bot")
        print("=" * 40)
        
        # Connect
        print("🔌 Connecting...")
        if not self.client.connect():
            print("❌ Failed to connect!")
            return
        
        # Login
        print("🔐 Logging in...")
        if not self.client.login("hosler", "1234"):
            print("❌ Login failed!")
            self.client.disconnect()
            return
        
        print("✅ Logged in successfully!")
        print(f"📍 Starting position: ({self.client.local_player.x}, {self.client.local_player.y})")
        
        # Set bot appearance
        self.client.set_nickname("SpiffFollower")
        self.client.set_body_image("body23.png")  # Different body
        self.client.set_head_image("head127.png")  # Robot-like head
        
        # Announce presence
        self.client.say("SpaceManSpiff Follower Bot online! Looking for SpaceManSpiff...")
        
        # Main loop
        print("\n🎯 Searching for SpaceManSpiff...")
        print("💡 Press Ctrl+C to stop\n")
        
        last_status_time = time.time()
        search_messages = [
            "Where are you SpaceManSpiff?",
            "SpaceManSpiff, I'm looking for you!",
            "Come out SpaceManSpiff!",
            "I'm your loyal follower bot!"
        ]
        search_msg_index = 0
        
        try:
            while True:
                current_time = time.time()
                
                # If we haven't found SpaceManSpiff, search actively
                if self.spaceman_id is None:
                    # Periodic search messages
                    if current_time - last_status_time > 15:  # Every 15 seconds
                        self.client.say(search_messages[search_msg_index])
                        search_msg_index = (search_msg_index + 1) % len(search_messages)
                        last_status_time = current_time
                        
                        # Check all current players
                        print(f"🔍 Scanning {len(self.client.players)} players...")
                        for pid, player in self.client.players.items():
                            if player.nickname and "SpaceManSpiff" in player.nickname:
                                print(f"🎯 Found SpaceManSpiff in existing players!")
                                self.spaceman_id = pid
                                self.spaceman_position = (player.x, player.y)
                                break
                
                # Status update
                if current_time - last_status_time > 5:
                    if self.spaceman_id:
                        spaceman = self.client.get_player_by_id(self.spaceman_id)
                        if spaceman:
                            distance = self.calculate_distance(
                                (self.client.local_player.x, self.client.local_player.y),
                                (spaceman.x, spaceman.y)
                            )
                            print(f"👥 Following SpaceManSpiff - Distance: {distance:.1f} tiles")
                        else:
                            print("⚠️  Lost track of SpaceManSpiff...")
                            self.spaceman_id = None
                    else:
                        print(f"🔍 Still searching... ({len(self.client.players)} players online)")
                    
                    last_status_time = current_time
                
                # Small delay
                time.sleep(0.1)
                
        except KeyboardInterrupt:
            print("\n\n⏹️  Stopping follower bot...")
            
        # Farewell
        if self.spaceman_id:
            self.client.say("Goodbye SpaceManSpiff! It was fun following you! 👋")
        else:
            self.client.say("Never found SpaceManSpiff, but it was worth the search! 👋")
        
        time.sleep(1)
        self.client.disconnect()
        print("✅ Bot stopped successfully!")

def main():
    bot = SpaceManSpiffFollower()
    bot.run()

if __name__ == "__main__":
    main()