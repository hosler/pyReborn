#!/usr/bin/env python3
"""
Simple Example Bot - Basic PyReborn Usage

This bot demonstrates the most common PyReborn usage patterns:
- Connecting to a server
- Basic movement and chat
- Using context managers for automatic cleanup

Usage:
    python simple_bot.py your_username your_password
    python simple_bot.py your_username your_password --server myserver.com
"""

import sys
import time
import argparse
from pyreborn import Client


def main():
    parser = argparse.ArgumentParser(description="Simple PyReborn Example Bot")
    parser.add_argument("username", help="Username to login with")
    parser.add_argument("password", help="Password to login with")
    parser.add_argument("--server", default="localhost", help="Server to connect to")
    parser.add_argument("--port", type=int, default=14900, help="Port to connect to")
    
    args = parser.parse_args()
    
    print(f"🎮 Simple Bot Starting...")
    print(f"Server: {args.server}:{args.port}")
    print(f"Username: {args.username}")
    
    # Use context manager for automatic cleanup
    with Client.session(args.server, args.port, args.username, args.password) as client:
        print("✅ Connected and logged in!")
        
        # Get initial player data
        player = client.get_player()
        if player:
            print(f"Player position: ({player.x}, {player.y}) in level '{player.level}'")
        
        # Say hello
        client.say("🤖 Simple bot online!")
        time.sleep(1)
        
        # Demonstrate basic movement pattern
        print("🚶 Starting movement pattern...")
        movements = [
            (1, 0, "east"),
            (0, 1, "south"), 
            (-1, 0, "west"),
            (0, -1, "north")
        ]
        
        for dx, dy, direction in movements:
            print(f"Moving {direction}...")
            client.move(dx, dy)
            client.say(f"Moving {direction}!")
            time.sleep(2)
        
        # Final status
        final_player = client.get_player()
        if final_player:
            print(f"Final position: ({final_player.x}, {final_player.y})")
        
        client.say("🤖 Simple bot completed patrol!")
        print("✅ Bot completed successfully!")
    
    print("👋 Disconnected. Bot finished.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)