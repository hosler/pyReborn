#!/usr/bin/env python3
"""
PyReborn Feature Demonstration
==============================

This demo showcases all major features of the PyReborn library:
- Connection and authentication
- Movement and positioning
- Chat and communication
- Event handling system
- Level data access
- Player tracking
- Session management
"""

import sys
import time
import random
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, '..')

from pyreborn import RebornClient

class FeatureDemo:
    def __init__(self):
        self.client = RebornClient("localhost", 14900)
        self.demo_complete = False
        self.players_seen = set()
        self.chat_count = 0
        self.start_time = time.time()
        
    def setup_event_handlers(self):
        """Setup all event handlers to demonstrate event system"""
        print("\n📡 Setting up event handlers...")
        
        # Player events
        self.client.events.subscribe('player_added', self.on_player_added)
        self.client.events.subscribe('player_removed', self.on_player_removed)
        self.client.events.subscribe('player_moved', self.on_player_moved)
        self.client.events.subscribe('player_chat', self.on_player_chat)
        self.client.events.subscribe('player_props_changed', self.on_player_props_changed)
        
        # Level events
        self.client.events.subscribe('level_changed', self.on_level_changed)
        
        print("✅ Event handlers configured")
        
    def on_player_added(self, event):
        """Handle player joining"""
        player = event.get('player')
        if player and hasattr(player, 'name'):
            self.players_seen.add(player.name)
            print(f"   👋 Player joined: {player.name} at ({player.x:.1f}, {player.y:.1f})")
            
    def on_player_removed(self, event):
        """Handle player leaving"""
        player = event.get('player')
        if player and hasattr(player, 'name'):
            print(f"   🚪 Player left: {player.name}")
            
    def on_player_moved(self, event):
        """Handle player movement"""
        player = event.get('player')
        if player and hasattr(player, 'name') and player.name != "DemoBot":
            # Only log movements occasionally to avoid spam
            if random.random() < 0.1:  # 10% chance
                print(f"   🚶 {player.name} moved to ({player.x:.1f}, {player.y:.1f})")
                
    def on_player_chat(self, event):
        """Handle chat messages"""
        player = event.get('player')
        message = event.get('message', '')
        if player and hasattr(player, 'name'):
            self.chat_count += 1
            print(f"   💬 {player.name}: {message}")
            
    def on_player_props_changed(self, event):
        """Handle player property changes"""
        player = event.get('player')
        if player and hasattr(player, 'name'):
            print(f"   🎨 {player.name} changed appearance")
            
    def on_level_changed(self, event):
        """Handle level changes"""
        level_name = event.get('level_name', 'unknown')
        print(f"   🗺️  Level changed to: {level_name}")
        
    def demonstrate_movement(self):
        """Demonstrate movement capabilities"""
        print("\n🏃 Demonstrating Movement")
        print("=" * 40)
        
        # Define a path to walk
        waypoints = [
            (30, 30, "Starting position"),
            (35, 30, "Moving east"),
            (35, 35, "Moving south"),
            (30, 35, "Moving west"),
            (30, 30, "Back to start")
        ]
        
        for x, y, description in waypoints:
            print(f"   Moving to ({x}, {y}) - {description}")
            self.client.move_to(x, y)
            time.sleep(2)
            
    def demonstrate_chat(self):
        """Demonstrate chat capabilities"""
        print("\n💬 Demonstrating Chat System")
        print("=" * 40)
        
        messages = [
            "Hello, I'm DemoBot!",
            "I'm demonstrating PyReborn features",
            f"I've seen {len(self.players_seen)} players so far",
            "Watch me move around!"
        ]
        
        for message in messages:
            print(f"   Setting chat bubble: '{message}'")
            self.client.set_chat(message)
            time.sleep(3)
            
    def demonstrate_appearance(self):
        """Demonstrate appearance customization"""
        print("\n🎨 Demonstrating Appearance Changes")
        print("=" * 40)
        
        # Set nickname
        print("   Setting nickname to 'DemoBot'")
        self.client.set_nickname("DemoBot")
        time.sleep(1)
        
        # Change head images
        heads = ["head0.png", "head1.png", "head2.png", "head3.png"]
        for head in heads:
            print(f"   Changing head to: {head}")
            self.client.set_head_image(head)
            time.sleep(2)
            
        # Change body images
        bodies = ["body0.png", "body1.png", "body2.png", "body3.png"]
        for body in bodies:
            print(f"   Changing body to: {body}")
            self.client.set_body_image(body)
            time.sleep(2)
            
    def demonstrate_level_data(self):
        """Demonstrate level data access"""
        print("\n🗺️  Demonstrating Level Data Access")
        print("=" * 40)
        
        # Get current level
        level = self.client.level_manager.get_current_level()
        if not level:
            print("   ❌ No level data available")
            return
            
        print(f"   Current level: {level.name}")
        print(f"   Level size: {level.width}x{level.height} tiles")
        
        # Check if we have board data
        if hasattr(level, 'board_tiles_64x64') and level.board_tiles_64x64:
            print(f"   Board data available: {len(level.board_tiles_64x64)} tiles")
            
            # Get tile statistics
            tiles = level.get_board_tiles_array()
            unique_tiles = len(set(tiles))
            print(f"   Unique tile types: {unique_tiles}")
            
            # Sample some tiles
            sample_positions = [(10, 10), (30, 30), (50, 50)]
            print("   Sample tiles:")
            for x, y in sample_positions:
                tile_id = level.get_board_tile_id(x, y)
                print(f"      Position ({x}, {y}): Tile ID {tile_id}")
                
            # Show tileset coordinate conversion
            print("   Tileset coordinate conversion:")
            for tile_id in [0, 100, 500, 1000]:
                tx, ty, px, py = level.tile_to_tileset_coords(tile_id)
                print(f"      Tile {tile_id} -> Tileset position ({tx}, {ty}), pixels ({px}, {py})")
        else:
            print("   No board data loaded yet")
            
    def demonstrate_player_tracking(self):
        """Demonstrate player tracking capabilities"""
        print("\n👥 Demonstrating Player Tracking")
        print("=" * 40)
        
        # Get current level
        level = self.client.level_manager.get_current_level()
        if not level:
            print("   No level loaded")
            return
            
        # Show players in level
        players = level.players
        print(f"   Players in level: {len(players)}")
        
        for player_id, player in players.items():
            if hasattr(player, 'name'):
                print(f"      - {player.name} (ID: {player_id}) at ({player.x:.1f}, {player.y:.1f})")
                if hasattr(player, 'head_image'):
                    print(f"        Head: {player.head_image}")
                if hasattr(player, 'body_image'):
                    print(f"        Body: {player.body_image}")
                    
    def demonstrate_session_info(self):
        """Demonstrate session management"""
        print("\n📊 Session Information")
        print("=" * 40)
        
        session = self.client.session
        
        # Get current player info
        my_player = session.get_player()
        if my_player:
            print(f"   My player ID: {my_player.id}")
            print(f"   My position: ({my_player.x:.1f}, {my_player.y:.1f})")
            print(f"   My nickname: {my_player.nickname}")
            
        # Session stats
        elapsed = time.time() - self.start_time
        print(f"\n   Session duration: {elapsed:.1f} seconds")
        print(f"   Players encountered: {len(self.players_seen)}")
        print(f"   Chat messages seen: {self.chat_count}")
        
        if self.players_seen:
            print("   Players seen this session:")
            for name in sorted(self.players_seen):
                print(f"      - {name}")
                
    def run_demo(self):
        """Run the complete feature demonstration"""
        print("\n🎮 PyReborn Feature Demonstration")
        print("=" * 50)
        print("This demo will showcase all major library features")
        print("=" * 50)
        
        # Connect
        print("\n1️⃣  Connecting to server...")
        if not self.client.connect():
            print("❌ Failed to connect!")
            return 1
        print("✅ Connected successfully")
        
        # Login
        print("\n2️⃣  Logging in...")
        if not self.client.login("hosler", "1234"):
            print("❌ Login failed!")
            return 1
        print("✅ Logged in successfully")
        
        # Setup events
        self.setup_event_handlers()
        
        # Wait for initial data
        print("\n⏳ Waiting for initial level data...")
        time.sleep(5)
        
        # Run demonstrations
        try:
            self.demonstrate_appearance()
            self.demonstrate_movement()
            self.demonstrate_chat()
            self.demonstrate_level_data()
            self.demonstrate_player_tracking()
            self.demonstrate_session_info()
            
            # Final message
            print("\n✅ Demo Complete!")
            print("=" * 50)
            self.client.set_chat("Demo complete! Thanks for watching! 👋")
            time.sleep(3)
            
        except KeyboardInterrupt:
            print("\n\n⚠️  Demo interrupted by user")
        except Exception as e:
            print(f"\n❌ Error during demo: {e}")
            import traceback
            traceback.print_exc()
            
        # Disconnect
        print("\n🔌 Disconnecting...")
        self.client.disconnect()
        print("✅ Disconnected")
        
        return 0

def main():
    """Main entry point"""
    print("PyReborn Feature Demonstration")
    print("==============================")
    print()
    print("This demo requires:")
    print("- GServer running on localhost:14900")
    print("- Account 'demobot' with password '1234'")
    print()
    print("Press Ctrl+C to stop the demo at any time")
    print()
    
    input("Press Enter to start the demo...")
    
    demo = FeatureDemo()
    return demo.run_demo()

if __name__ == "__main__":
    sys.exit(main())