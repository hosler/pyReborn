#!/usr/bin/env python3
"""
Basic Bot Example - demonstrates fundamental PyReborn functionality
"""

import sys
import time
sys.path.insert(0, '../..')

from pyreborn.client import RebornClient

def main():
    """Basic bot that logs in, moves around, and chats"""
    print("Basic Bot Example")
    print("=================\n")
    
    # Create client
    client = RebornClient("localhost", 14900)
    
    print("1. Connecting...")
    if not client.connect():
        print("❌ Failed to connect!")
        return 1
    
    print("2. Logging in...")
    if not client.login("basicbot", "1234"):
        print("❌ Login failed!")
        return 1
    
    print("3. Setting up bot...")
    client.set_nickname("BasicBot")
    client.set_chat("Hello, I'm a basic bot!")
    
    print("4. Moving around...")
    positions = [(30, 30), (35, 30), (35, 35), (30, 35)]
    
    for i, (x, y) in enumerate(positions):
        print(f"   Moving to ({x}, {y})")
        client.move_to(x, y)
        client.set_chat(f"Position {i+1}: ({x}, {y})")
        time.sleep(3)
    
    print("5. Final message...")
    client.set_chat("Basic bot demonstration complete!")
    time.sleep(2)
    
    print("6. Disconnecting...")
    client.disconnect()
    print("✅ Done!")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())