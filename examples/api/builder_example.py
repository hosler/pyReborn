#!/usr/bin/env python3
"""
Fluent Builder Pattern Example
==============================

Demonstrates the new fluent builder pattern for creating configured PyReborn clients.
This approach provides a discoverable, chainable API for setting up clients.
"""

import sys
import time
import logging

# Add parent directory to path
sys.path.insert(0, '../..')

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')


def example_basic_builder():
    """Example using basic fluent builder"""
    print("=== Basic Fluent Builder ===")
    
    from pyreborn import Client
    from pyreborn.advanced_api import CompressionType, EncryptionGen, LogLevel
    
    # Create client with fluent builder pattern
    client = (Client.builder()
              .with_server("localhost", 14900)
              .with_version("6.037")
              .with_compression(CompressionType.AUTO)
              .with_encryption(EncryptionGen.GEN5)
              .with_logging(LogLevel.INFO)
              .build())
    
    print(f"✅ Client built with fluent API")
    
    # Test connection
    with client:
        if client.connect():
            print("✅ Connected via builder-created client!")
            if client.login("your_username", "your_password"):
                print("✅ Logged in via builder!")
                
                player = client.get_player()
                if player:
                    print(f"Player: {player.account} at ({player.x}, {player.y})")
                
                time.sleep(1)
            else:
                print("❌ Login failed")
        else:
            print("❌ Connection failed")
    
    print("✅ Auto-disconnected")


def example_advanced_builder():
    """Example using advanced builder features"""
    print("\n=== Advanced Builder Features ===")
    
    from pyreborn import Client
    from pyreborn.advanced_api import ClientBuilder, CompressionType, EncryptionGen, LogLevel
    
    # Create client with advanced configuration
    client = (Client.builder()
              .with_server("localhost", 14900)
              .with_version("6.037")
              .with_compression(CompressionType.ZLIB)
              .with_encryption(EncryptionGen.GEN5)
              .with_auto_reconnect(enabled=True, max_retries=3, delay=1.0)
              .with_timeout(30.0)
              .with_logging(LogLevel.DEBUG, log_packets=False)
              .with_performance(buffer_size=16384, queue_size=1500, enable_metrics=True)
              .with_property("custom_user_agent", "PyReborn-Builder/1.0")
              .with_property("enable_experimental_features", True)
              .build())
    
    print("✅ Client built with advanced configuration")
    
    # Test the configured client
    try:
        with client:
            if client.connect():
                print("✅ Connected with advanced settings!")
                time.sleep(0.5)
            else:
                print("❌ Connection failed")
    except Exception as e:
        print(f"❌ Error: {e}")


def example_preset_builders():
    """Example using preset builder configurations"""
    print("\n=== Preset Builders ===")
    
    from pyreborn.advanced_api import PresetBuilder
    
    # Development preset
    dev_client = PresetBuilder.development().build()
    print("✅ Development preset client created")
    
    # Production preset  
    prod_client = (PresetBuilder.production()
                   .with_server("production.server.com", 14900)
                   .build())
    print("✅ Production preset client created")
    
    # Testing preset
    test_client = PresetBuilder.testing().build()
    print("✅ Testing preset client created")
    
    # Classic server preset
    classic_client = (PresetBuilder.classic_server()
                      .with_server("classic.reborn.com", 14900)
                      .build())
    print("✅ Classic server preset client created")


def example_build_and_connect():
    """Example using build_and_connect for one-liner setup"""
    print("\n=== Build and Connect ===")
    
    from pyreborn import Client
    from pyreborn.advanced_api import LogLevel
    
    try:
        # One-liner client creation with auto-connect and login
        client = (Client.builder()
                  .with_server("localhost", 14900)
                  .with_version("6.037")
                  .with_logging(LogLevel.INFO)
                  .with_auto_reconnect(max_retries=2)
                  .build_and_connect("your_username", "your_password"))
        
        print("✅ Built, connected, and logged in with one chain!")
        
        # Use the client
        player = client.get_player()
        if player:
            print(f"Player: {player.account} at ({player.x}, {player.y})")
        
        # Move around a bit
        print("Moving player...")
        client.move(1, 0)
        time.sleep(1)
        client.move(0, 1)
        time.sleep(1)
        
        print("Sending chat...")
        if hasattr(client, 'say'):
            client.say("Hello from fluent builder!")
        
        # Manual disconnect
        client.disconnect()
        print("✅ Manually disconnected")
        
    except ConnectionError as e:
        print(f"❌ Connection error: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    print("PyReborn Fluent Builder Pattern Examples")
    print("========================================")
    
    try:
        # Run all examples
        example_basic_builder()
        example_advanced_builder()
        example_preset_builders()
        example_build_and_connect()
        
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()