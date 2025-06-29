#!/usr/bin/env python3
"""
Simple demo - login, walk around, swing sword, and chat
"""

import sys
import time
sys.path.insert(0, '..')

from pyreborn import GraalClient, EventType
from pyreborn.protocol.enums import Direction

def main():
    # Create client
    client = GraalClient("localhost", 14900)
    
    # Connect
    print("Connecting to server...")
    if not client.connect():
        print("Failed to connect!")
        return
    
    # Login
    print("Logging in...")
    if not client.login("DemoBot", "password"):
        print("Failed to login!")
        return
    
    print("✓ Connected!")
    time.sleep(2)  # Wait for initial packets
    
    # Say hello
    client.say("Hello everyone! I'm a pyReborn bot!")
    time.sleep(2)
    
    # Walk in a square pattern
    print("\nWalking in a square...")
    start_x = client.local_player.x
    start_y = client.local_player.y
    
    # Walk right
    client.move_to(start_x + 5, start_y, Direction.RIGHT)
    time.sleep(1)
    client.say("Walking right...")
    time.sleep(1)
    
    # Walk down
    client.move_to(start_x + 5, start_y + 5, Direction.DOWN)
    time.sleep(1)
    client.say("Now going down...")
    time.sleep(1)
    
    # Walk left
    client.move_to(start_x, start_y + 5, Direction.LEFT)
    time.sleep(1)
    client.say("Heading left...")
    time.sleep(1)
    
    # Walk up (back to start)
    client.move_to(start_x, start_y, Direction.UP)
    time.sleep(1)
    client.say("And back to where I started!")
    time.sleep(2)
    
    # Swing sword a few times
    print("\nSwinging sword...")
    for i in range(3):
        client.set_gani("sword")
        client.say(f"Sword swing #{i+1}!")
        time.sleep(2)
        client.set_gani("idle")
        time.sleep(1)
    
    # Final message
    client.say("That's all folks! pyReborn is awesome!")
    time.sleep(2)
    
    # Disconnect
    print("\nDisconnecting...")
    client.disconnect()
    print("✓ Done!")

if __name__ == "__main__":
    main()