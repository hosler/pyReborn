#!/usr/bin/env python3
"""
Async/Await Example
===================

Demonstrates the new async/await support for PyReborn clients.
Perfect for modern Python applications using asyncio.
"""

import sys
import asyncio
import logging
import time

# Add parent directory to path
sys.path.insert(0, '../..')

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')


async def example_basic_async():
    """Example using basic async client"""
    print("=== Basic Async Client ===")
    
    from pyreborn.advanced_api import AsyncClient
    
    client = AsyncClient("localhost", 14900)
    
    try:
        # Connect and login asynchronously
        print("Connecting...")
        if await client.connect():
            print("✅ Connected asynchronously!")
            
            print("Logging in...")
            if await client.login("your_username", "your_password"):
                print("✅ Logged in asynchronously!")
                
                # Get player data
                player = await client.get_player()
                if player:
                    print(f"Player: {player.account} at ({player.x}, {player.y})")
                
                # Perform async operations
                print("Moving player...")
                await client.move(1, 0)  # Move right
                await asyncio.sleep(1)
                
                print("Sending chat...")
                await client.say("Hello async world!")
                await asyncio.sleep(1)
                
                print("Dropping bomb...")
                await client.drop_bomb(power=2, timer=50)
                await asyncio.sleep(1)
                
            else:
                print("❌ Login failed")
        else:
            print("❌ Connection failed")
    
    finally:
        await client.disconnect()
        print("✅ Disconnected asynchronously")


async def example_async_context_manager():
    """Example using async context manager"""
    print("\n=== Async Context Manager ===")
    
    from pyreborn.advanced_api import AsyncClient
    
    try:
        async with AsyncClient("localhost", 14900) as client:
            if await client.connect():
                print("✅ Connected in async context!")
                
                if await client.login("your_username", "your_password"):
                    print("✅ Logged in in async context!")
                    
                    player = await client.get_player()
                    if player:
                        print(f"Player: {player.account} at ({player.x}, {player.y})")
                    
                    # Do async operations
                    await client.move(0, 1)  # Move up
                    await client.say("Async context manager working!")
                    
                    await asyncio.sleep(1)
                else:
                    print("❌ Login failed")
            else:
                print("❌ Connection failed")
        
        print("✅ Auto-disconnected via async context manager")
        
    except Exception as e:
        print(f"❌ Error: {e}")


async def example_async_connect_and_login():
    """Example using async connect_and_login class method"""
    print("\n=== Async Connect and Login ===")
    
    from pyreborn.advanced_api import AsyncClient
    
    try:
        # One-liner async connection and login
        client = await AsyncClient.connect_and_login(
            "localhost", 14900, "your_username", "your_password"
        )
        
        print("✅ Connected and logged in with one async call!")
        
        player = await client.get_player()
        if player:
            print(f"Player: {player.account} at ({player.x}, {player.y})")
        
        # Perform some actions
        await client.move(-1, 0)  # Move left
        await client.say("One-liner async setup!")
        
        # Manual disconnect
        await client.disconnect()
        print("✅ Manually disconnected")
        
    except ConnectionError as e:
        print(f"❌ Connection error: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")


async def example_concurrent_operations():
    """Example using concurrent async operations"""
    print("\n=== Concurrent Operations ===")
    
    from pyreborn.advanced_api import AsyncClient
    
    try:
        client = await AsyncClient.connect_and_login(
            "localhost", 14900, "your_username", "your_password"
        )
        
        print("✅ Connected for concurrent operations test")
        
        # Perform multiple operations concurrently
        print("Performing concurrent operations...")
        
        # Create tasks for concurrent execution
        move_task = client.move(1, 1)  # Move diagonally
        chat_task = client.say("Concurrent async operations!")
        player_task = client.get_player()
        
        # Wait for all operations to complete
        move_result, chat_result, player = await asyncio.gather(
            move_task, chat_task, player_task
        )
        
        print(f"✅ Move result: {move_result}")
        print(f"✅ Chat result: {chat_result}")
        if player:
            print(f"✅ Player: {player.account} at ({player.x}, {player.y})")
        
        await client.disconnect()
        print("✅ Concurrent operations completed")
        
    except Exception as e:
        print(f"❌ Error: {e}")


async def example_async_quick_connect():
    """Example using async quick connect function"""
    print("\n=== Async Quick Connect ===")
    
    from pyreborn.advanced_api import async_quick_connect
    
    client = await async_quick_connect(
        "localhost", 14900, "your_username", "your_password"
    )
    
    if client:
        print("✅ Quick async connect successful!")
        
        player = await client.get_player()
        if player:
            print(f"Player: {player.account} at ({player.x}, {player.y})")
        
        await client.say("Quick connect works!")
        await client.disconnect()
        print("✅ Quick connect test completed")
    else:
        print("❌ Quick connect failed")


async def main():
    """Main async function to run all examples"""
    print("PyReborn Async/Await Examples")
    print("=============================")
    
    try:
        await example_basic_async()
        await example_async_context_manager()
        await example_async_connect_and_login()
        await example_concurrent_operations()
        await example_async_quick_connect()
        
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main())