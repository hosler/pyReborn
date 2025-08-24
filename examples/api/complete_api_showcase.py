#!/usr/bin/env python3
"""
Complete API Showcase
======================

Demonstrates all the new PyReborn API features working together:
- Fluent builder pattern  
- Context managers
- Strongly-typed packet enums
- High-level game actions
- Virtual method patterns

This showcases the full power of the enhanced PyReborn API.
"""

import sys
import time
import logging
import asyncio

# Add parent directory to path
sys.path.insert(0, '../..')

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')


def example_complete_api_workflow():
    """Complete example using all API features together"""
    print("=== Complete API Workflow ===")
    
    from pyreborn import Client
    from pyreborn.advanced_api import CompressionType, LogLevel, enhance_with_actions
    from pyreborn.protocol.packet_enums import IncomingPackets
    
    # 1. Create client using fluent builder
    client = (Client.builder()
              .with_server("localhost", 14900)
              .with_version("6.037")
              .with_compression(CompressionType.AUTO)
              .with_logging(LogLevel.INFO)
              .with_auto_reconnect(max_retries=2)
              .build())
    
    print("✅ Client built with fluent API")
    
    # 2. Enhance with high-level actions
    actions = enhance_with_actions(client)
    print("✅ Client enhanced with game actions")
    
    # 3. Use context manager for automatic cleanup
    try:
        with client:
            # 4. Connect and login
            if client.connect():
                print("✅ Connected!")
                if client.login("your_username", "your_password"):
                    print("✅ Logged in!")
                    
                    # Wait for initial data
                    time.sleep(2)
                    
                    # 5. Get comprehensive status
                    status = actions.get_status()
                    print(f"📊 Status: {status['player']['account']} at ({status['player']['x']}, {status['player']['y']})")
                    
                    # 6. Use high-level actions
                    print("🎮 Performing high-level actions...")
                    
                    # Social actions
                    result = actions.say("Hello from enhanced PyReborn API!")
                    print(f"💬 Chat result: {result.result.value} - {result.message}")
                    
                    time.sleep(0.5)
                    
                    # Movement actions
                    result = actions.walk_direction("right", steps=3)
                    print(f"🚶 Walk result: {result.result.value} - {result.message}")
                    
                    time.sleep(1)
                    
                    # Combat actions
                    result = actions.attack("north")
                    print(f"⚔️ Attack result: {result.result.value} - {result.message}")
                    
                    time.sleep(0.5)
                    
                    # Exploration actions
                    result = actions.exploration.find_level_exits()
                    print(f"🗺️ Exploration result: {result.result.value} - {result.message}")
                    if result.data:
                        print(f"   Found exits: {len(result.data['exits'])}")
                    
                    # Item actions
                    result = actions.pickup_items(radius=1.0)
                    print(f"🎒 Item pickup result: {result.result.value} - {result.message}")
                    
                    time.sleep(1)
                    
                    print("🎮 All high-level actions completed!")
                    
                else:
                    print("❌ Login failed")
            else:
                print("❌ Connection failed")
        
        print("✅ Auto-disconnected via context manager")
        
    except Exception as e:
        print(f"❌ Error: {e}")


async def example_async_with_actions():
    """Example combining async client with game actions"""
    print("\n=== Async Client with Game Actions ===")
    
    from pyreborn.advanced_api import AsyncClient, enhance_with_actions
    
    try:
        async with AsyncClient("localhost", 14900) as client:
            if await client.connect():
                print("✅ Async connected!")
                if await client.login("your_username", "your_password"):
                    print("✅ Async logged in!")
                    
                    # Enhance with actions (note: this works with async client too)
                    actions = enhance_with_actions(client)
                    
                    # Wait for initial data
                    await asyncio.sleep(2)
                    
                    # Use actions asynchronously
                    print("🎮 Performing async high-level actions...")
                    
                    # Get status
                    status = actions.get_status()
                    print(f"📊 Async status: {status['player']['account']} at ({status['player']['x']}, {status['player']['y']})")
                    
                    # Perform concurrent actions
                    chat_task = actions.say("Async actions working!")
                    move_task = actions.walk_direction("left", steps=2)
                    
                    # Wait for both to complete
                    chat_result, move_result = await asyncio.gather(
                        asyncio.create_task(asyncio.to_thread(lambda: chat_task)),
                        asyncio.create_task(asyncio.to_thread(lambda: move_task))
                    )
                    
                    print(f"💬 Async chat: {chat_result.result.value}")
                    print(f"🚶 Async move: {move_result.result.value}")
                    
                else:
                    print("❌ Async login failed")
            else:
                print("❌ Async connection failed")
        
        print("✅ Async auto-disconnected")
        
    except Exception as e:
        print(f"❌ Async error: {e}")


def example_packet_introspection():
    """Example using packet introspection with the new APIs"""
    print("\n=== Packet Introspection ===")
    
    from pyreborn.protocol.packet_enums import IncomingPackets, PacketRegistry, PacketCategories
    
    # Show packet enum information
    print(f"📦 PLAYER_PROPS packet ID: {IncomingPackets.PLAYER_PROPS}")
    print(f"📦 LEVEL_BOARD packet ID: {IncomingPackets.LEVEL_BOARD}")
    print(f"📦 TO_ALL (chat) packet ID: {IncomingPackets.TO_ALL}")
    
    # Show packet categories
    core_packets = PacketCategories.CORE
    print(f"📂 Core packets: {[p.name for p in core_packets[:3]]}...")
    
    communication_packets = PacketCategories.COMMUNICATION
    print(f"💬 Communication packets: {[p.name for p in communication_packets]}")
    
    # Lookup packets
    packet_9 = PacketRegistry.get_incoming_packet(9)
    category = PacketRegistry.get_packet_category(9)
    print(f"🔍 Packet 9: {packet_9.name if packet_9 else 'Unknown'} (category: {category})")
    
    print("✅ Packet introspection working!")


class CompleteGameBot:
    """Example bot using all API features"""
    
    def __init__(self):
        from pyreborn import Client
        from pyreborn.advanced_api import LogLevel, enhance_with_actions
        
        # Create client with builder
        self.client = (Client.builder()
                      .with_server("localhost", 14900)
                      .with_version("6.037")
                      .with_logging(LogLevel.INFO)
                      .with_auto_reconnect(max_retries=3)
                      .build())
        
        # Enhance with actions
        self.actions = enhance_with_actions(self.client)
        
        # Track state
        self.is_running = False
    
    def start(self):
        """Start the bot"""
        print("🤖 Starting CompleteGameBot...")
        
        try:
            with self.client:
                if self.client.connect():
                    print("🤖 Bot connected!")
                    if self.client.login("your_username", "your_password"):
                        print("🤖 Bot logged in!")
                        
                        self.is_running = True
                        self.run_bot_logic()
                        
                    else:
                        print("❌ Bot login failed")
                else:
                    print("❌ Bot connection failed")
            
            print("🤖 Bot stopped")
            
        except Exception as e:
            print(f"❌ Bot error: {e}")
    
    def run_bot_logic(self):
        """Main bot logic using high-level actions"""
        print("🤖 Running bot logic...")
        
        # Wait for initial data
        time.sleep(2)
        
        # Say hello
        result = self.actions.say("Bot is online!")
        print(f"🤖 Greeting: {result.message}")
        
        time.sleep(1)
        
        # Explore the level
        print("🤖 Starting exploration...")
        result = self.actions.explore("spiral")
        print(f"🤖 Exploration: {result.message}")
        
        # Find exits
        result = self.actions.exploration.find_level_exits()
        print(f"🤖 Level analysis: {result.message}")
        
        # Attack in different directions
        for direction in ["north", "east", "south", "west"]:
            result = self.actions.attack(direction)
            print(f"🤖 Attack {direction}: {result.message}")
            time.sleep(0.3)
        
        # Final status
        status = self.actions.get_status()
        print(f"🤖 Final position: ({status['player']['x']}, {status['player']['y']})")
        
        self.actions.say("Bot operations complete!")


def example_complete_bot():
    """Example using a complete bot with all API features"""
    print("\n=== Complete Game Bot ===")
    
    bot = CompleteGameBot()
    bot.start()


def main():
    """Main function to run all showcase examples"""
    print("PyReborn Complete API Showcase")
    print("==============================")
    
    try:
        # Show packet introspection (no server needed)
        example_packet_introspection()
        
        # Show complete workflow
        example_complete_api_workflow()
        
        # Show async integration
        asyncio.run(example_async_with_actions())
        
        # Show complete bot
        example_complete_bot()
        
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()