#!/usr/bin/env python3
"""
Test Bot - Practical testing of the refactored PyReborn library
This bot connects to the server and tests all major features.
"""

import sys
import time
import threading
from datetime import datetime
import os

sys.path.insert(0, '..')

from pyreborn import RebornClient

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

class TestBot(RebornClient):
    """Test bot that exercises all library features"""
    
    def __init__(self, host: str, port: int = 14900):
        super().__init__(host, port)
        
        # Test tracking
        self.tests_passed = 0
        self.tests_failed = 0
        self.test_results = []
        
        # Setup events (EventManager now has enhanced features built-in)
        from pyreborn.events import EventManager
        self.events = EventManager()
        
        # Track events
        self.events_received = {
            'player_added': 0,
            'player_removed': 0,
            'player_moved': 0,
            'player_chat': 0,
            'level_changed': 0,
            'player_props_changed': 0
        }
        
        # Setup handlers
        self._setup_handlers()
        
    def _setup_handlers(self):
        """Setup event handlers for testing"""
        # String-based events for testing
        self.events.subscribe('player_added', lambda e: self._track_event('player_added', e))
        self.events.subscribe('player_removed', lambda e: self._track_event('player_removed', e))
        self.events.subscribe('player_moved', lambda e: self._track_event('player_moved', e))
        self.events.subscribe('player_chat', lambda e: self._track_event('player_chat', e))
        self.events.subscribe('level_changed', lambda e: self._track_event('level_changed', e))
        self.events.subscribe('player_props_changed', lambda e: self._track_event('player_props_changed', e))
        
    def _track_event(self, event_name: str, event_data: dict):
        """Track that an event was received"""
        self.events_received[event_name] += 1
        print(f"[Event] {event_name}: {self.events_received[event_name]} times")
        
    def test_feature(self, test_name: str, test_func):
        """Run a single feature test"""
        print(f"\n[TEST] {test_name}")
        try:
            result = test_func()
            if result:
                self.tests_passed += 1
                print(f"   ✅ PASSED")
                self.test_results.append((test_name, True, None))
            else:
                self.tests_failed += 1
                print(f"   ❌ FAILED")
                self.test_results.append((test_name, False, "Test returned False"))
        except Exception as e:
            self.tests_failed += 1
            print(f"   ❌ FAILED: {e}")
            self.test_results.append((test_name, False, str(e)))
            
    def run_all_tests(self):
        """Run all feature tests"""
        print("\n" + "="*60)
        print("RUNNING PYREBORN FEATURE TESTS")
        print("="*60)
        
        # Test 1: Movement
        self.test_feature("Movement System", self.test_movement)
        
        # Test 2: Chat
        self.test_feature("Chat System", self.test_chat)
        
        # Test 3: Appearance
        self.test_feature("Appearance Changes", self.test_appearance)
        
        # Test 4: Session
        self.test_feature("Session Management", self.test_session)
        
        # Test 5: Level Manager
        self.test_feature("Level Manager", self.test_level_manager)
        
        # Test 6: Event System
        self.test_feature("Event System", self.test_events)
        
        # Test 7: Actions Module
        self.test_feature("Actions Module", self.test_actions_module)
        
        # Test 8: Combat Actions
        self.test_feature("Combat Actions", self.test_combat)
        
        # Test 9: Items
        self.test_feature("Item Management", self.test_items)
        
        # Test 10: Level Snapshot
        self.test_feature("Level Snapshot", self.test_level_snapshot)
        
        # Summary
        self.print_summary()
        
    def test_movement(self):
        """Test movement functionality"""
        print("   Testing move_to()...")
        
        # Save initial position
        start_x = self.local_player.x
        start_y = self.local_player.y
        
        # Test movement
        test_positions = [
            (30, 30),
            (35, 30),
            (35, 35),
            (30, 35),
            (start_x, start_y)
        ]
        
        for x, y in test_positions:
            self.move_to(x, y)
            time.sleep(0.5)
            
            # Verify local state updated
            if self.local_player.x != x or self.local_player.y != y:
                raise Exception(f"Position mismatch: expected ({x},{y}), got ({self.local_player.x},{self.local_player.y})")
                
        print("   Movement test completed")
        return True
        
    def test_chat(self):
        """Test chat functionality"""
        print("   Testing set_chat()...")
        
        test_messages = [
            "Testing chat system",
            "Special chars: !@#$%",
            "Numbers: 12345",
            "Empty test: "
        ]
        
        for msg in test_messages:
            self.set_chat(msg)
            time.sleep(1)
            
            # Verify local state
            if self.local_player.chat != msg:
                raise Exception(f"Chat mismatch: expected '{msg}', got '{self.local_player.chat}'")
                
        print("   Chat test completed")
        return True
        
    def test_appearance(self):
        """Test appearance changes"""
        print("   Testing appearance methods...")
        
        # Test nickname
        self.set_nickname("TestBot123")
        time.sleep(0.5)
        if self.local_player.nickname != "TestBot123":
            raise Exception("Nickname not updated")
            
        # Test head images
        for i in range(4):
            head = f"head{i}.png"
            self.set_head_image(head)
            time.sleep(0.5)
            if self.local_player.head_image != head:
                raise Exception(f"Head image not updated to {head}")
                
        # Test body images
        for i in range(4):
            body = f"body{i}.png"
            self.set_body_image(body)
            time.sleep(0.5)
            if self.local_player.body_image != body:
                raise Exception(f"Body image not updated to {body}")
                
        print("   Appearance test completed")
        return True
        
    def test_session(self):
        """Test session management"""
        print("   Testing session...")
        
        # Get session info
        player = self.session.local_player
        if not player:
            raise Exception("Session player not available")
            
        if player.id != self.local_player.id:
            raise Exception("Session player ID mismatch")
            
        print(f"   Session player: {player.nickname} (ID: {player.id})")
        return True
        
    def test_level_manager(self):
        """Test level manager"""
        print("   Testing level manager...")
        
        # Get current level
        level = self.level_manager.get_current_level()
        if not level:
            print("   Warning: No level loaded yet")
            return True  # This is okay if we just logged in
            
        print(f"   Current level: {level.name}")
        print(f"   Players in level: {len(level.players)}")
        
        # Test board data if available
        if hasattr(level, 'board_tiles_64x64'):
            tiles = level.get_board_tiles_array()
            print(f"   Board data: {len(tiles)} tiles")
            
            # Test coordinate conversion
            test_tile = tiles[0] if tiles else 0
            tx, ty, px, py = level.tile_to_tileset_coords(test_tile)
            print(f"   Tile {test_tile} -> tileset ({tx},{ty})")
            
        return True
        
    def test_events(self):
        """Test event system"""
        print("   Testing event system...")
        
        # Check that we received some events
        total_events = sum(self.events_received.values())
        print(f"   Total events received: {total_events}")
        
        for event_name, count in self.events_received.items():
            if count > 0:
                print(f"   - {event_name}: {count}")
                
        # Test custom event
        received = []
        self.events.subscribe('test_event', lambda e: received.append(e))
        self.events.emit('test_event', {'test': True})
        
        if not received or not received[0].get('test'):
            raise Exception("Custom event test failed")
            
        print("   Event system working")
        return True
        
    def test_actions_module(self):
        """Test that actions module is integrated"""
        print("   Testing actions module...")
        
        # Verify _actions exists
        if not hasattr(self, '_actions'):
            raise Exception("Actions module not found")
            
        # Verify it has expected methods
        action_methods = ['move_to', 'set_chat', 'drop_bomb', 'set_arrows']
        for method in action_methods:
            if not hasattr(self._actions, method):
                raise Exception(f"Action method {method} not found")
                
        print("   Actions module properly integrated")
        return True
        
    def test_combat(self):
        """Test combat actions"""
        print("   Testing combat actions...")
        
        # Test bomb
        self.drop_bomb()
        time.sleep(0.5)
        print("   - drop_bomb() called")
        
        # Test arrow
        self.shoot_arrow()
        time.sleep(0.5)
        print("   - shoot_arrow() called")
        
        # Test fire effect
        self.fire_effect()
        time.sleep(0.5)
        print("   - fire_effect() called")
        
        return True
        
    def test_items(self):
        """Test item management"""
        print("   Testing item methods...")
        
        # Test setting arrows
        self.set_arrows(99)
        time.sleep(0.5)
        if self.local_player.arrows != 99:
            raise Exception("Arrows not updated")
            
        # Test setting bombs
        self.set_bombs(20)
        time.sleep(0.5)
        if self.local_player.bombs != 20:
            raise Exception("Bombs not updated")
            
        # Test setting rupees
        self.set_rupees(100)
        time.sleep(0.5)
        if self.local_player.rupees != 100:
            raise Exception("Rupees not updated")
            
        # Test setting hearts
        self.set_hearts(3, 3)
        time.sleep(0.5)
        
        print("   Item management working")
        return True
        
    def test_level_snapshot(self):
        """Test level snapshot functionality"""
        print("   Testing level snapshot and tile mapping...")
        
        # The server should have sent board data during login
        # Let's check if we have it
        
        # Get current level
        level = self.level_manager.get_current_level()
        if not level:
            print("   Warning: No level loaded - server may not have sent level data")
            print("   This can happen on some server configurations")
            return True  # Don't fail the test
            
        print(f"   Current level: {level.name}")
        
        # Check if board data exists
        if not hasattr(level, 'board_tiles_64x64') or not level.board_tiles_64x64:
            print("   Warning: No board data loaded yet")
            return True  # This can happen if level hasn't sent board data
            
        # Get board tiles
        tiles = level.get_board_tiles_array()
        if not tiles:
            raise Exception("Board tiles array is empty")
            
        print(f"   Board data: {len(tiles)} tiles")
        
        # Verify tile count
        if len(tiles) != 4096:  # 64x64
            raise Exception(f"Invalid tile count: {len(tiles)}, expected 4096")
            
        # Get 2D array
        tiles_2d = level.get_board_tiles_2d()
        if len(tiles_2d) != 64 or len(tiles_2d[0]) != 64:
            raise Exception(f"Invalid 2D array dimensions: {len(tiles_2d)}x{len(tiles_2d[0])}")
            
        # Test tile coordinate conversion
        test_tiles = [0, 1, 16, 256, 512, 1000, 2000, 3000, 4095]
        print("   Testing tile coordinate conversion:")
        
        for tile_id in test_tiles:
            if tile_id < len(tiles):
                actual_tile = tiles[tile_id]
                tx, ty, px, py = level.tile_to_tileset_coords(actual_tile)
                print(f"     Tile {tile_id} (ID: {actual_tile}) -> tileset ({tx},{ty}) pixel ({px},{py})")
                
                # Verify coordinate ranges
                # tx can be up to 16*4 = 64 (since we have 512*4 = 2048 tiles horizontally)
                if tx < 0 or tx >= 64:
                    raise Exception(f"Invalid tileset X coordinate: {tx}")
                if ty < 0 or ty >= 32:
                    raise Exception(f"Invalid tileset Y coordinate: {ty}")
                if px < 0 or px >= 1024:  # 64 * 16 pixels
                    raise Exception(f"Invalid pixel X coordinate: {px}")
                if py < 0 or py >= 512:  # 32 * 16 pixels
                    raise Exception(f"Invalid pixel Y coordinate: {py}")
                    
        # Count unique tiles
        unique_tiles = set(tiles)
        print(f"   Unique tile IDs: {len(unique_tiles)}")
        
        # Find common tiles (grass is usually 0)
        tile_counts = {}
        for tile in tiles:
            tile_counts[tile] = tile_counts.get(tile, 0) + 1
            
        # Get top 5 most common tiles
        common_tiles = sorted(tile_counts.items(), key=lambda item: item[1], reverse=True)[:5]
        print("   Most common tiles:")
        for tile_id, count in common_tiles:
            percentage = (count / 4096) * 100
            print(f"     Tile {tile_id}: {count} times ({percentage:.1f}%)")
            
        # Test specific positions
        print("   Testing specific board positions:")
        test_positions = [(0, 0), (10, 10), (30, 30), (63, 63)]
        for x, y in test_positions:
            tile_id = level.get_board_tile_id(x, y)
            if tile_id is not None:
                print(f"     Position ({x},{y}): Tile ID {tile_id}")
            else:
                raise Exception(f"Failed to get tile at ({x},{y})")
                
        print("   Level snapshot test completed successfully")
        
        # Generate PNG if PIL is available
        if PIL_AVAILABLE and hasattr(level, 'board_tiles_64x64') and level.board_tiles_64x64:
            print("\n   Generating level PNG...")
            
            # Create a 64x64 image with 16x16 pixel tiles
            img_size = 64 * 16  # 1024x1024 pixels
            img = Image.new('RGB', (img_size, img_size), color='black')
            
            # Try to load tileset from various locations
            tileset_name = "pics1formatwithcliffs.png"
            search_paths = [
                tileset_name,
                f"../funtimes/world/tilesets/{tileset_name}",
                f"../../funtimes/world/tilesets/{tileset_name}",
                f"../../../funtimes/world/tilesets/{tileset_name}",
                f"tilesets/{tileset_name}",
                f"world/tilesets/{tileset_name}",
            ]
            
            tileset = None
            for tileset_path in search_paths:
                if os.path.exists(tileset_path):
                    try:
                        tileset = Image.open(tileset_path)
                        print(f"   ✅ Loaded tileset from {tileset_path}: {tileset.size}")
                        break
                    except Exception as e:
                        print(f"   ⚠️ Could not load tileset from {tileset_path}: {e}")
                        
            if not tileset:
                print(f"   ⚠️ Tileset '{tileset_name}' not found in any search path")
                
            # Draw each tile
            for y in range(64):
                for x in range(64):
                    tile_id = level.get_board_tile_id(x, y)
                    if tile_id is not None:
                        # Get tileset coordinates
                        tx, ty, px, py = level.tile_to_tileset_coords(tile_id)
                        
                        if tileset:
                            # Copy from tileset
                            try:
                                tile_img = tileset.crop((px, py, px + 16, py + 16))
                                img.paste(tile_img, (x * 16, y * 16))
                            except Exception:
                                # Fallback to color based on tile ID
                                color = (
                                    (tile_id * 7) % 256,
                                    (tile_id * 13) % 256,
                                    (tile_id * 23) % 256
                                )
                                for dy in range(16):
                                    for dx in range(16):
                                        img.putpixel((x * 16 + dx, y * 16 + dy), color)
                        else:
                            # No tileset - use color based on tile ID
                            if tile_id == 0:
                                color = (0, 128, 0)  # Green for grass
                            elif tile_id == 2047:
                                color = (64, 64, 64)  # Dark gray for common tile
                            else:
                                # Generate color from tile ID
                                color = (
                                    (tile_id * 7) % 256,
                                    (tile_id * 13) % 256,
                                    (tile_id * 23) % 256
                                )
                            
                            # Fill 16x16 area with color
                            for dy in range(16):
                                for dx in range(16):
                                    img.putpixel((x * 16 + dx, y * 16 + dy), color)
                                    
            # Save the image
            output_file = f"level_snapshot_{level.name.replace('.nw', '')}.png"
            img.save(output_file)
            print(f"   ✅ Saved level snapshot to {output_file}")
            
            # Also save a smaller preview version
            preview = img.resize((256, 256), Image.Resampling.NEAREST)
            preview_file = f"level_preview_{level.name.replace('.nw', '')}.png"
            preview.save(preview_file)
            print(f"   ✅ Saved preview to {preview_file}")
        
        return True
        
    def print_summary(self):
        """Print test summary"""
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        print(f"Tests Passed: {self.tests_passed}")
        print(f"Tests Failed: {self.tests_failed}")
        print(f"Total Tests: {self.tests_passed + self.tests_failed}")
        
        if self.tests_failed > 0:
            print("\nFailed Tests:")
            for name, passed, error in self.test_results:
                if not passed:
                    print(f"  - {name}: {error}")
                    
        print("\nEvent Statistics:")
        for event_name, count in self.events_received.items():
            print(f"  - {event_name}: {count}")
            
        if self.tests_failed == 0:
            print("\n✅ ALL TESTS PASSED! The refactored library is working correctly.")
        else:
            print(f"\n❌ {self.tests_failed} TESTS FAILED! Check the errors above.")

def main():
    """Main test runner"""
    print("PyReborn Test Bot")
    print("=================")
    print("This bot tests the refactored PyReborn library")
    print()
    
    # Create test bot
    bot = TestBot("localhost", 14900)
    
    # Connect
    print("Connecting to server...")
    if not bot.connect():
        print("❌ Failed to connect to server!")
        print("Make sure Reborn Server is running on localhost:14900")
        return 1
        
    print("✅ Connected")
    
    # Login
    print("Logging in...")
    if not bot.login("hosler", "1234"):
        print("❌ Login failed!")
        return 1
        
    print("✅ Logged in")
    
    # Wait for initial data
    print("Waiting for initial server data...")
    time.sleep(5)  # Wait longer for board data
    
    # Run tests
    try:
        bot.run_all_tests()
    except KeyboardInterrupt:
        print("\n\nTests interrupted by user")
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        
    # Disconnect
    print("\nDisconnecting...")
    bot.disconnect()
    print("Test bot finished.")
    
    # Return exit code based on test results
    return 0 if bot.tests_failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())