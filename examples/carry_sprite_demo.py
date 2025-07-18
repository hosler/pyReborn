#!/usr/bin/env python3
"""
Carry Sprite Demo - Demonstrates setting carry sprites in PyReborn

This example shows how to use the set_carry_sprite method to make
your player carry different items.
"""

import time
from pyreborn.client import RebornClient
from pyreborn.protocol.enums import LevelItemType

def main():
    # Connect to server
    client = RebornClient("localhost", 14900)
    
    if not client.connect():
        print("Failed to connect to server")
        return
        
    # Login
    if not client.login("hosler", "1234"):
        print("Failed to login")
        client.disconnect()
        return
        
    print("Connected and logged in!")
    
    # Set a nickname
    client.set_nickname("CarryBot")
    
    # Move to a visible position
    client.move_to(30, 30)
    
    # Common carry sprite IDs in Graal:
    # -1 = No carry sprite (empty hands)
    # 0 = Green rupee
    # 1 = Blue rupee  
    # 2 = Red rupee
    # 3 = Bombs
    # 4 = Darts/Arrows
    # 5 = Heart
    # 6 = Glove1
    # 7 = Bow
    # 8 = Bomb (single)
    # 9 = Shield
    # 10 = Sword
    # 11 = Full heart
    # 12 = Super bomb
    # 13 = Battle axe
    # 14 = Golden sword
    # 15 = Mirror shield
    # 16 = Glove2
    # 17 = Lizard shield
    # 18 = Lizard sword
    # 19 = Gold rupee
    # 20 = Fireball
    # 21 = Fireblast
    # 22 = Nukeshot
    # 23 = Joltbomb
    
    try:
        while True:
            # Cycle through different carry sprites
            items = [
                (-1, "Nothing"),
                (0, "Green Rupee"),
                (1, "Blue Rupee"),
                (2, "Red Rupee"),
                (3, "Bombs"),
                (5, "Heart"),
                (8, "Bomb"),
                (9, "Shield"),
                (10, "Sword"),
                (19, "Gold Rupee"),
            ]
            
            for sprite_id, item_name in items:
                print(f"Carrying: {item_name} (sprite ID: {sprite_id})")
                client.set_carry_sprite(sprite_id)
                client.set_chat(f"Carrying {item_name}!")
                time.sleep(2)
                
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        # Clear carry sprite before disconnecting
        client.set_carry_sprite(-1)
        client.disconnect()
        print("Disconnected")

if __name__ == "__main__":
    main()