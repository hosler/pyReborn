#!/usr/bin/env python3
"""
Trash-talking sword bot - walks around, swings sword, and talks smack
"""

import sys
import time
import random
sys.path.insert(0, '..')

from pyreborn import GraalClient, EventType
from pyreborn.protocol.enums import Direction

# Trash talk phrases
TRASH_TALK = [
    "Is that the best you got?",
    "My grandma swings better than that!",
    "You call that a sword?",
    "I've seen NPCs fight better!",
    "Git gud scrub!",
    "Ez clap!",
    "You swing like a level 1 noob",
    "Dodge this!",
    "*yawns* Too easy",
    "Uninstall please",
    "Are you even trying?",
    "That's it? That's your move?",
    "I'm not even warmed up yet",
    "You must be lagging",
    "Nice try... NOT!",
    "Better luck next respawn",
    "Outplayed and outsmarted",
    "Calculated.",
    "All skill no luck baby",
    "Where'd you learn to fight, tutorial island?"
]

# Movement patterns
def random_walk_pattern():
    """Generate a random walk pattern"""
    patterns = [
        # Square pattern
        [(2, 0, Direction.RIGHT), (0, 2, Direction.DOWN), 
         (-2, 0, Direction.LEFT), (0, -2, Direction.UP)],
        # Diamond pattern
        [(2, 2, Direction.RIGHT), (-2, 2, Direction.DOWN),
         (-2, -2, Direction.LEFT), (2, -2, Direction.UP)],
        # Random steps
        [(random.randint(-3, 3), random.randint(-3, 3), random.choice(list(Direction)))
         for _ in range(4)],
        # Circle-ish
        [(2, 1, Direction.RIGHT), (1, 2, Direction.DOWN),
         (-1, 2, Direction.DOWN), (-2, 1, Direction.LEFT),
         (-2, -1, Direction.LEFT), (-1, -2, Direction.UP),
         (1, -2, Direction.UP), (2, -1, Direction.RIGHT)]
    ]
    return random.choice(patterns)

def main():
    client = GraalClient("localhost", 14900)
    
    # Track other players for targeted trash talk
    other_players = {}
    
    def on_player_update(player):
        """Track other players"""
        if player.id != client.local_player.id:
            other_players[player.id] = player
            if len(other_players) == 1:  # First player spotted
                client.say("Fresh meat! Prepare to get rekt!")
    
    def on_player_removed(player_id):
        """Handle rage quits"""
        if player_id in other_players:
            client.say("Another one bites the dust! Too ez!")
            del other_players[player_id]
    
    # Subscribe to events
    client.on(EventType.OTHER_PLAYER_UPDATE, on_player_update)
    client.on(EventType.PLAYER_REMOVED, on_player_removed)
    
    # Connect and login
    print("🤖 Trash-Talking Sword Bot Starting...")
    if not client.connect():
        print("Failed to connect!")
        return
        
    if not client.login("TrashBot", "bot123"):
        print("Failed to login!")
        return
    
    print("✓ Connected and logged in!")
    time.sleep(2)
    
    # Set nickname
    client.set_nickname("xXx_SwordMaster_xXx")
    client.say("The champ has arrived! Who wants some?")
    
    # Main bot loop
    start_x = client.local_player.x
    start_y = client.local_player.y
    pattern_index = 0
    current_pattern = random_walk_pattern()
    last_trash_talk = time.time()
    last_sword_swing = time.time()
    
    print("\n🎮 Bot is running! Press Ctrl+C to stop")
    
    try:
        while True:
            current_time = time.time()
            
            # Movement
            if pattern_index < len(current_pattern):
                dx, dy, direction = current_pattern[pattern_index]
                new_x = start_x + dx
                new_y = start_y + dy
                
                # Move to new position
                client.move_to(new_x, new_y, direction)
                pattern_index += 1
                
                # Sometimes do a sword swing after moving
                if random.random() < 0.3:
                    time.sleep(0.5)
                    client.set_gani("sword")
                    client.say("Hyahhh!")
                    last_sword_swing = current_time
            else:
                # Reset pattern
                pattern_index = 0
                start_x = client.local_player.x
                start_y = client.local_player.y
                current_pattern = random_walk_pattern()
                
                # Change up our style
                if random.random() < 0.5:
                    client.set_gani("idle")
                    client.say("*cracks knuckles* Who's next?")
            
            # Periodic sword swinging
            if current_time - last_sword_swing > random.uniform(5, 10):
                client.set_gani("sword")
                
                # Target specific player if any nearby
                if other_players:
                    target = random.choice(list(other_players.values()))
                    client.say(f"This one's for you, {target.nickname}!")
                else:
                    client.say("*swings at air* Shadow boxing!")
                    
                last_sword_swing = current_time
            
            # Trash talk
            if current_time - last_trash_talk > random.uniform(8, 15):
                # Mix between general and targeted trash talk
                if other_players and random.random() < 0.6:
                    target = random.choice(list(other_players.values()))
                    targeted_talk = [
                        f"Hey {target.nickname}, you fight like a dairy farmer!",
                        f"{target.nickname} couldn't hit water if they fell out of a boat!",
                        f"I've seen better moves from {target.nickname}'s mom!",
                        f"Yo {target.nickname}, is your sword made of rubber?",
                        f"{target.nickname} vs Me = GG EZ NO RE"
                    ]
                    client.say(random.choice(targeted_talk))
                else:
                    client.say(random.choice(TRASH_TALK))
                    
                last_trash_talk = current_time
            
            # Sometimes spin for style points
            if random.random() < 0.1:
                client.set_gani("spin")
                client.say("360 no scope!")
                time.sleep(1)
            
            # Occasional emotes
            if random.random() < 0.05:
                emotes = ["flex", "dance", "laugh"]
                if random.choice(emotes) == "flex":
                    client.say("💪 Check out these gains!")
                elif random.choice(emotes) == "dance":
                    client.say("🕺 Victory dance!")
                else:
                    client.say("😂 LOL get rekt!")
            
            time.sleep(1.5)  # Don't spam too fast
            
    except KeyboardInterrupt:
        print("\n\n🛑 Bot stopped by user")
        client.say("GG losers, I'm out! *mic drop*")
        time.sleep(1)
    
    # Disconnect
    client.disconnect()
    print("✓ Disconnected")

if __name__ == "__main__":
    main()