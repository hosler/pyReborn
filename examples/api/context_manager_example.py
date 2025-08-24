#!/usr/bin/env python3
"""
Context Manager Example
=======================

Demonstrates the new context manager support for automatic connection management.

Usage:
    # Update the credentials in this file before running, or use environment variables:
    export REBORN_USERNAME=your_username
    export REBORN_PASSWORD=your_password
    python context_manager_example.py
"""

import sys
import time
import logging
import os

# Add parent directory to path
sys.path.insert(0, '../..')

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# Configuration (can be overridden with environment variables)
USERNAME = os.getenv("REBORN_USERNAME", "your_username")
PASSWORD = os.getenv("REBORN_PASSWORD", "your_password")
HOST = os.getenv("REBORN_HOST", "localhost")
PORT = int(os.getenv("REBORN_PORT", "14900"))

# Check credentials
if USERNAME == "your_username" or PASSWORD == "your_password":
    print("⚠️  Please configure credentials:")
    print("   Set REBORN_USERNAME and REBORN_PASSWORD environment variables")
    print("   Example: REBORN_USERNAME=testuser REBORN_PASSWORD=testpass python context_manager_example.py")
    sys.exit(1)

def example_basic_context_manager():
    """Example using basic context manager"""
    print("=== Basic Context Manager ===")
    
    from pyreborn import Client
    
    # Create client and use context manager for auto-disconnect
    client = Client(HOST, PORT)
    
    with client:
        if client.connect():
            print("✅ Connected!")
            if client.login(USERNAME, PASSWORD):
                print("✅ Logged in!")
                
                player = client.get_player()
                if player:
                    print(f"Player: {player.account} at ({player.x}, {player.y})")
                
                time.sleep(1)
            else:
                print("❌ Login failed")
        else:
            print("❌ Connection failed")
    
    print("✅ Auto-disconnected via context manager")


def example_session_context_manager():
    """Example using session class method with context manager"""
    print("\n=== Session Context Manager ===")
    
    from pyreborn import Client
    
    try:
        # This automatically connects and logs in
        with Client.session(HOST, PORT, USERNAME, PASSWORD) as client:
            print("✅ Connected and logged in automatically!")
            
            player = client.get_player()
            if player:
                print(f"Player: {player.account} at ({player.x}, {player.y})")
            
            # Do some actions
            print("Moving player...")
            client.move(1, 0)  # Move right
            time.sleep(1)
            
            print("Sending chat...")
            if hasattr(client, 'say'):
                client.say("Hello from context manager!")
            
            time.sleep(1)
            
        print("✅ Auto-disconnected via session context manager")
        
    except ConnectionError as e:
        print(f"❌ Connection error: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")


def example_packet_enums():
    """Example using the new packet enums"""
    print("\n=== Packet Enums ===")
    
    from pyreborn.protocol.packet_enums import IncomingPackets, OutgoingPackets, PacketRegistry
    
    # Show some packet information
    print(f"PLAYER_PROPS packet ID: {IncomingPackets.PLAYER_PROPS}")
    print(f"LEVEL_BOARD packet ID: {IncomingPackets.LEVEL_BOARD}")
    print(f"PLAYER_MOVE packet ID: {OutgoingPackets.PLAYER_MOVE}")
    
    # Demonstrate packet lookup
    packet_9 = PacketRegistry.get_incoming_packet(9)
    print(f"Packet ID 9 is: {packet_9}")
    
    # Show packet category
    category = PacketRegistry.get_packet_category(9)
    print(f"Packet ID 9 category: {category}")
    
    # Get packets by category
    core_packets = PacketRegistry.get_packets_by_category("core")
    print(f"Core packets: {[p.name for p in core_packets[:5]]}...")  # Show first 5


if __name__ == "__main__":
    print("PyReborn API Enhancement Examples")
    print("=================================")
    
    try:
        # Run packet enum example (doesn't need server)
        example_packet_enums()
        
        # Run context manager examples (need server)
        example_basic_context_manager()
        example_session_context_manager()
        
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()