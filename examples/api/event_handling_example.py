#!/usr/bin/env python3
"""
Event Handling Examples
========================

Demonstrates the new decorator-based and virtual method event handling systems.
Shows different approaches for handling game events in a clean, organized way.
"""

import sys
import time
import logging
from typing import Optional, Dict, Any

# Add parent directory to path
sys.path.insert(0, '../..')

# Import types for type hints
from pyreborn.models import Player, Level

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')


def example_decorator_based_events():
    """Example using decorator-based event handling"""
    print("=== Decorator-Based Event Handling ===")
    
    from pyreborn import Client
    from pyreborn.advanced_api import create_decorated_client
    from pyreborn.protocol.packet_enums import IncomingPackets
    
    # Create a regular client and wrap it with decorators
    base_client = Client("localhost", 14900)
    client = create_decorated_client(base_client)
    
    # Register event handlers using decorators
    @client.on_chat()
    def handle_all_chat(player_id, message):
        print(f"💬 Chat from player {player_id}: {message}")
    
    @client.on_chat(lambda msg: "help" in msg.lower())
    def handle_help_requests(player_id, message):
        print(f"🆘 Help request from player {player_id}: {message}")
    
    @client.on_packet(IncomingPackets.PLAYER_PROPS)
    def handle_player_props(packet_data):
        print(f"👤 Player properties updated: {type(packet_data)}")
    
    @client.on_event("player_moved")
    def handle_movement(player):
        print(f"🚶 Player moved to ({player.x}, {player.y})")
    
    @client.middleware
    def log_all_events(event_type, event_data, next_handler):
        print(f"🔍 Processing event: {event_type}")
        return next_handler(event_data)
    
    # Test the client
    try:
        with client:
            if client.connect():
                print("✅ Connected with decorator support!")
                if client.login("your_username", "your_password"):
                    print("✅ Logged in with event handlers!")
                    
                    # Trigger some events
                    time.sleep(2)  # Let initial events process
                    
                    print("Triggering events...")
                    client.say("This should trigger chat handler")
                    time.sleep(0.5)
                    
                    client.say("Can someone help me?")  # Should trigger help handler
                    time.sleep(0.5)
                    
                    client.move(1, 0)  # Should trigger movement handler
                    time.sleep(1)
                    
                else:
                    print("❌ Login failed")
            else:
                print("❌ Connection failed")
        
        print("✅ Decorator-based events tested")
        
        # Show registered handlers
        handlers = client.decorators.get_registered_handlers()
        print(f"📊 Registered handlers: {handlers}")
        
    except Exception as e:
        print(f"❌ Error: {e}")


class MyGameClient:
    """Example custom client using virtual method overrides"""
    # For this example, we'll use composition instead of inheritance
    # since ExtensibleClient needs more integration work
    
    def __init__(self, host: str = "localhost", port: int = 14900, version: str = "6.037"):
        from pyreborn import Client
        self.client = Client(host, port, version)
    
    def connect(self):
        return self.client.connect()
    
    def login(self, username, password):
        return self.client.login(username, password)
    
    def disconnect(self):
        return self.client.disconnect()
    
    def say(self, message):
        if hasattr(self.client, 'say'):
            return self.client.say(message)
        return False
    
    def move(self, dx, dy):
        return self.client.move(dx, dy)
    
    def get_player(self):
        return self.client.get_player()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False
    
    def on_player_chat(self, player_id: int, message: str) -> None:
        """Handle chat messages"""
        print(f"🎮 [MyGameClient] Chat from {player_id}: {message}")
        
        # Custom logic for chat handling
        if "hello" in message.lower():
            self.say("Hello there!")
        elif "time" in message.lower():
            import datetime
            current_time = datetime.datetime.now().strftime("%H:%M:%S")
            self.say(f"Current time is {current_time}")
    
    def on_player_moved(self, player: Player) -> None:
        """Handle player movement"""
        print(f"🎮 [MyGameClient] Player moved to ({player.x}, {player.y})")
        
        # Custom logic for movement
        if hasattr(player, 'account') and player.account == "your_username":
            print("🎮 [MyGameClient] That's me moving!")
    
    def on_level_changed(self, level_name: str, level: Optional[Level] = None) -> None:
        """Handle level changes"""
        print(f"🎮 [MyGameClient] Entered level: {level_name}")
        
        # Custom logic for level changes
        if "cave" in level_name.lower():
            print("🎮 [MyGameClient] Entered a cave - watch out for monsters!")
        elif "gmap" in level_name.lower():
            print("🎮 [MyGameClient] Entered GMAP mode!")
    
    def on_npc_added(self, npc_id: int, x: float, y: float, npc_data: Dict[str, Any]) -> None:
        """Handle NPC additions"""
        print(f"🎮 [MyGameClient] NPC {npc_id} added at ({x}, {y})")
    
    def on_connected(self) -> None:
        """Handle successful connection"""
        print("🎮 [MyGameClient] Successfully connected to server!")
    
    def on_logged_in(self, player: Player) -> None:
        """Handle successful login"""
        print(f"🎮 [MyGameClient] Successfully logged in as {player.account}!")
    
    def on_disconnected(self, reason: str = "") -> None:
        """Handle disconnection"""
        print(f"🎮 [MyGameClient] Disconnected: {reason}")


def example_virtual_method_client():
    """Example using virtual method inheritance"""
    print("\n=== Virtual Method Client ===")
    
    client = MyGameClient("localhost", 14900)
    
    try:
        with client:
            if client.connect():
                print("✅ Connected with virtual method client!")
                if client.login("your_username", "your_password"):
                    print("✅ Logged in with custom handlers!")
                    
                    # Give time for initial events
                    time.sleep(2)
                    
                    # Trigger some events
                    print("Triggering custom event handlers...")
                    client.say("Hello everyone!")
                    time.sleep(0.5)
                    
                    client.say("What time is it?")
                    time.sleep(0.5)
                    
                    client.move(1, 1)  # Move diagonally
                    time.sleep(1)
                    
                else:
                    print("❌ Login failed")
            else:
                print("❌ Connection failed")
        
        print("✅ Virtual method client tested")
        
    except Exception as e:
        print(f"❌ Error: {e}")


class HybridClient:
    """Example client using both virtual methods and decorators"""
    
    def __init__(self, host: str = "localhost", port: int = 14900, version: str = "6.037"):
        from pyreborn import Client
        self.client = Client(host, port, version)
        
        # Add decorator support
        from pyreborn.advanced_api import create_decorated_client
        self._decorated = create_decorated_client(self.client)
        
        # Set up decorator handlers
        self._setup_decorators()
    
    def connect(self):
        return self.client.connect()
    
    def login(self, username, password):
        return self.client.login(username, password)
    
    def disconnect(self):
        return self.client.disconnect()
    
    def say(self, message):
        if hasattr(self.client, 'say'):
            return self.client.say(message)
        return False
    
    def move(self, dx, dy):
        return self.client.move(dx, dy)
    
    def get_player(self):
        return self.client.get_player()
    
    def drop_bomb(self, power=1, timer=55):
        if hasattr(self.client, 'drop_bomb'):
            return self.client.drop_bomb(power, timer)
        return False
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False
    
    def _setup_decorators(self):
        """Set up decorator-based handlers alongside virtual methods"""
        from pyreborn.protocol.packet_enums import IncomingPackets
        
        @self._decorated.on_packet(IncomingPackets.BOMB_ADD)
        def handle_bomb_added(packet_data):
            print(f"💣 [Decorator] Bomb added: {packet_data}")
        
        @self._decorated.on_packet(IncomingPackets.EXPLOSION)
        def handle_explosion(packet_data):
            print(f"💥 [Decorator] Explosion: {packet_data}")
        
        @self._decorated.filter_events(lambda data: True)  # Example filter
        @self._decorated.on_event("player_died")
        def handle_player_death(event_data):
            print(f"☠️ [Decorator] Player died: {event_data}")
    
    # Virtual method overrides
    def on_player_chat(self, player_id: int, message: str) -> None:
        """Virtual method for chat"""
        print(f"🎭 [Virtual] Chat from {player_id}: {message}")
    
    def on_level_changed(self, level_name: str, level: Optional[Level] = None) -> None:
        """Virtual method for level changes"""
        print(f"🎭 [Virtual] Level changed to: {level_name}")


def example_hybrid_approach():
    """Example using both virtual methods and decorators together"""
    print("\n=== Hybrid Approach (Virtual + Decorators) ===")
    
    client = HybridClient("localhost", 14900)
    
    try:
        with client:
            if client.connect():
                print("✅ Connected with hybrid client!")
                if client.login("your_username", "your_password"):
                    print("✅ Logged in with hybrid handlers!")
                    
                    time.sleep(2)
                    
                    # Test both types of handlers
                    client.say("Testing hybrid handlers")
                    time.sleep(0.5)
                    
                    # Try to trigger bomb/explosion events
                    if hasattr(client, 'drop_bomb'):
                        client.drop_bomb(power=1, timer=30)
                        time.sleep(2)  # Wait for explosion
                    
                else:
                    print("❌ Login failed")
            else:
                print("❌ Connection failed")
        
        print("✅ Hybrid approach tested")
        
    except Exception as e:
        print(f"❌ Error: {e}")


def main():
    """Main function to run all examples"""
    print("PyReborn Event Handling Examples")
    print("================================")
    
    try:
        example_decorator_based_events()
        example_virtual_method_client()
        example_hybrid_approach()
        
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()