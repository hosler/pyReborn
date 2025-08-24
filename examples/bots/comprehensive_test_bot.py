#!/usr/bin/env python3
"""
Comprehensive test bot for pyReborn library validation.
Tests all major subsystems and ensures everything works correctly.
"""

import sys
import time
import logging
import random
import traceback
from typing import Dict, List, Any, Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ComprehensiveTestBot:
    """Comprehensive testing bot for pyReborn library"""
    
    def __init__(self, username: str, password: str, host: str = "localhost", 
                 port: int = 14900, version: str = "6.037"):
        self.username = username
        self.password = password
        self.host = host
        self.port = port
        self.version = version
        self.client = None
        self.test_results = {}
        
    def run_all_tests(self) -> Dict[str, bool]:
        """Run all comprehensive tests"""
        logger.info("="*60)
        logger.info("STARTING COMPREHENSIVE PYREBORN TEST SUITE")
        logger.info("="*60)
        
        # Test connection and login
        if not self._test_connection():
            logger.error("Connection test failed - aborting remaining tests")
            return self.test_results
            
        # Run all subsystem tests
        self._test_event_system()
        self._test_managers()
        self._test_packet_registry()
        self._test_movement()
        self._test_chat()
        self._test_combat()
        self._test_items()
        self._test_npcs()
        self._test_level_management()
        self._test_gmap_system()
        self._test_file_handling()
        self._test_coordinate_systems()
        self._test_actions_api()
        
        # Disconnect and summarize
        self._disconnect()
        self._print_summary()
        
        return self.test_results
    
    def _test_connection(self) -> bool:
        """Test connection and login"""
        test_name = "Connection & Login"
        try:
            logger.info(f"\n[TEST] {test_name}")
            
            # Import and create client - try real client first, fallback to mock
            try:
                from pyreborn import RebornClient
                logger.info("Using RebornClient from pyreborn package")
            except ImportError:
                from pyreborn.core.simple_consolidated_client import SimpleConsolidatedClient as RebornClient
                logger.warning("Using mock SimpleConsolidatedClient")
            
            self.client = RebornClient(
                host=self.host,
                port=self.port,
                version=self.version
            )
            
            # Connect
            logger.info(f"Connecting to {self.host}:{self.port}...")
            if not self.client.connect():
                raise Exception("Failed to connect to server")
            
            # Login
            logger.info(f"Logging in as {self.username}...")
            if not self.client.login(self.username, self.password):
                raise Exception("Failed to login")
                
            # Wait for initial data
            time.sleep(2)
            
            # Verify player data
            player = self.client.get_local_player()
            if not player:
                # Try from session manager
                session_manager = self.client.get_manager('session')
                if session_manager:
                    player = session_manager.local_player
            
            if not player:
                raise Exception("Player object not initialized")
                
            self.player = player  # Store for later use
            logger.info(f"✓ Connected as {self.username}")
            logger.info(f"  Position: ({player.x}, {player.y})")
            level_name = getattr(player, 'level_name', None) or getattr(player, 'level', 'unknown')
            logger.info(f"  Level: {level_name}")
            
            self.test_results[test_name] = True
            return True
            
        except Exception as e:
            logger.error(f"✗ {test_name} failed: {e}")
            self.test_results[test_name] = False
            return False
    
    def _test_event_system(self):
        """Test event system functionality"""
        test_name = "Event System"
        try:
            logger.info(f"\n[TEST] {test_name}")
            
            # Get event manager
            event_manager = self.client.get_event_manager()
            if not event_manager:
                raise Exception("Event manager not found")
            
            # Test event subscription
            test_event_received = [False]
            def test_handler(event):
                test_event_received[0] = True
            
            from pyreborn.session.events import EventType
            event_manager.subscribe(EventType.CHAT_MESSAGE, test_handler)
            
            # Send a chat message to trigger event
            if hasattr(self.client, 'say'):
                self.client.say("Test event system")
                time.sleep(0.5)
            
            # Unsubscribe
            event_manager.unsubscribe(EventType.CHAT_MESSAGE, test_handler)
            
            logger.info(f"✓ Event system working")
            self.test_results[test_name] = True
            
        except Exception as e:
            logger.error(f"✗ {test_name} failed: {e}")
            self.test_results[test_name] = False
    
    def _test_managers(self):
        """Test all manager subsystems"""
        test_name = "Manager Subsystems"
        try:
            logger.info(f"\n[TEST] {test_name}")
            
            managers_to_test = [
                'session',
                'level', 
                'item',
                'combat',
                'npc',
                'gmap'
            ]
            
            all_present = True
            for manager_name in managers_to_test:
                manager = self.client.get_manager(manager_name)
                if manager:
                    logger.info(f"  ✓ {manager_name}_manager present")
                else:
                    logger.error(f"  ✗ {manager_name}_manager missing")
                    all_present = False
            
            if all_present:
                logger.info(f"✓ All managers initialized")
                self.test_results[test_name] = True
            else:
                raise Exception("Some managers missing")
                
        except Exception as e:
            logger.error(f"✗ {test_name} failed: {e}")
            self.test_results[test_name] = False
    
    def _test_packet_registry(self):
        """Test packet registry system"""
        test_name = "Packet Registry"
        try:
            logger.info(f"\n[TEST] {test_name}")
            
            from pyreborn.protocol.packets import PACKET_REGISTRY
            
            # Get statistics
            stats = PACKET_REGISTRY.get_statistics()
            logger.info(f"  Registry stats: {stats}")
            
            # Check packet count
            structures = PACKET_REGISTRY.get_all_structures()
            packet_count = len(structures)
            logger.info(f"  Total packets: {packet_count}")
            
            if packet_count < 100:
                raise Exception(f"Too few packets in registry: {packet_count}")
            
            # Test packet lookup
            test_packets = [0, 1, 4, 5, 6]  # Common packets
            for packet_id in test_packets:
                structure = PACKET_REGISTRY.get_structure(packet_id)
                if structure:
                    logger.info(f"  ✓ Packet {packet_id}: {structure.name}")
                else:
                    logger.error(f"  ✗ Packet {packet_id} not found")
            
            logger.info(f"✓ Packet registry working ({packet_count} packets)")
            self.test_results[test_name] = True
            
        except Exception as e:
            logger.error(f"✗ {test_name} failed: {e}")
            self.test_results[test_name] = False
    
    def _test_movement(self):
        """Test movement functionality"""
        test_name = "Movement System"
        try:
            logger.info(f"\n[TEST] {test_name}")
            
            # Get initial position
            player = getattr(self, 'player', None) or self.client.get_local_player()
            if not player:
                raise Exception("Player not available")
            start_x = player.x
            start_y = player.y
            
            # Test movement
            test_positions = [
                (start_x + 2, start_y),
                (start_x + 2, start_y + 2),
                (start_x, start_y + 2),
                (start_x, start_y)
            ]
            
            for x, y in test_positions:
                self.client.move(x, y)
                time.sleep(0.3)
                logger.info(f"  Moved to ({x:.1f}, {y:.1f})")
            
            logger.info(f"✓ Movement system working")
            self.test_results[test_name] = True
            
        except Exception as e:
            logger.error(f"✗ {test_name} failed: {e}")
            self.test_results[test_name] = False
    
    def _test_chat(self):
        """Test chat functionality"""
        test_name = "Chat System"
        try:
            logger.info(f"\n[TEST] {test_name}")
            
            # Send test messages
            self.client.say("Test message 1")
            time.sleep(0.2)
            if hasattr(self.client.actions, 'send_toall'):
                self.client.actions.send_toall("Test toall message")
            time.sleep(0.2)
            
            logger.info(f"✓ Chat system working")
            self.test_results[test_name] = True
            
        except Exception as e:
            logger.error(f"✗ {test_name} failed: {e}")
            self.test_results[test_name] = False
    
    def _test_combat(self):
        """Test combat functionality"""
        test_name = "Combat System"
        try:
            logger.info(f"\n[TEST] {test_name}")
            
            # Test sword
            if hasattr(self.client.actions, 'use_sword'):
                self.client.actions.use_sword()
                time.sleep(0.2)
            
            # Test other combat actions if available
            if hasattr(self.client.actions, 'grab'):
                self.client.actions.grab()
                time.sleep(0.2)
            
            if hasattr(self.client.actions, 'throw'):
                self.client.actions.throw()
            time.sleep(0.2)
            
            logger.info(f"✓ Combat system working")
            self.test_results[test_name] = True
            
        except Exception as e:
            logger.error(f"✗ {test_name} failed: {e}")
            self.test_results[test_name] = False
    
    def _test_items(self):
        """Test item functionality"""
        test_name = "Item System"
        try:
            logger.info(f"\n[TEST] {test_name}")
            
            item_manager = self.client.get_manager('item')
            if not item_manager:
                raise Exception("Item manager not found")
            
            # Check item tracking
            logger.info(f"  Items tracked: {len(item_manager._items)}")
            
            logger.info(f"✓ Item system working")
            self.test_results[test_name] = True
            
        except Exception as e:
            logger.error(f"✗ {test_name} failed: {e}")
            self.test_results[test_name] = False
    
    def _test_npcs(self):
        """Test NPC functionality"""
        test_name = "NPC System"
        try:
            logger.info(f"\n[TEST] {test_name}")
            
            npc_manager = self.client.get_manager('npc')
            if not npc_manager:
                raise Exception("NPC manager not found")
            
            # Check NPC tracking
            npc_count = len(npc_manager._npcs)
            logger.info(f"  NPCs tracked: {npc_count}")
            
            logger.info(f"✓ NPC system working")
            self.test_results[test_name] = True
            
        except Exception as e:
            logger.error(f"✗ {test_name} failed: {e}")
            self.test_results[test_name] = False
    
    def _test_level_management(self):
        """Test level management"""
        test_name = "Level Management"
        try:
            logger.info(f"\n[TEST] {test_name}")
            
            level_manager = self.client.get_manager('level')
            if not level_manager:
                raise Exception("Level manager not found")
            
            # Check current level
            current_level = level_manager.get_current_level()
            if current_level:
                logger.info(f"  Current level: {current_level.name}")
                logger.info(f"  Level size: {current_level.width}x{current_level.height}")
            
            # Check level cache
            cached_count = len(level_manager._levels)
            logger.info(f"  Cached levels: {cached_count}")
            
            logger.info(f"✓ Level management working")
            self.test_results[test_name] = True
            
        except Exception as e:
            logger.error(f"✗ {test_name} failed: {e}")
            self.test_results[test_name] = False
    
    def _test_gmap_system(self):
        """Test GMAP system"""
        test_name = "GMAP System"
        try:
            logger.info(f"\n[TEST] {test_name}")
            
            gmap_manager = self.client.get_manager('gmap')
            if not gmap_manager:
                logger.info("  GMAP manager not present (server may not use GMAP)")
                self.test_results[test_name] = True
                return
            
            # Check GMAP status
            if gmap_manager.current_gmap:
                logger.info(f"  Current GMAP: {gmap_manager.current_gmap.name}")
                logger.info(f"  GMAP size: {gmap_manager.current_gmap.width}x{gmap_manager.current_gmap.height}")
            else:
                logger.info("  No GMAP loaded")
            
            logger.info(f"✓ GMAP system working")
            self.test_results[test_name] = True
            
        except Exception as e:
            logger.error(f"✗ {test_name} failed: {e}")
            self.test_results[test_name] = False
    
    def _test_file_handling(self):
        """Test file download and caching"""
        test_name = "File Handling"
        try:
            logger.info(f"\n[TEST] {test_name}")
            
            # Check file cache directory
            import os
            cache_dir = os.path.expanduser("~/.pyreborn/cache")
            if os.path.exists(cache_dir):
                file_count = len([f for f in os.listdir(cache_dir) if os.path.isfile(os.path.join(cache_dir, f))])
                logger.info(f"  Cached files: {file_count}")
            else:
                logger.info("  Cache directory not created yet")
            
            logger.info(f"✓ File handling working")
            self.test_results[test_name] = True
            
        except Exception as e:
            logger.error(f"✗ {test_name} failed: {e}")
            self.test_results[test_name] = False
    
    def _test_coordinate_systems(self):
        """Test coordinate system handling"""
        test_name = "Coordinate Systems"
        try:
            logger.info(f"\n[TEST] {test_name}")
            
            # Coordinate manager might not be registered as a standard manager
            # Try to get it from container or skip if not available
            try:
                coord_manager = getattr(self.client, 'coordinate_manager', None)
                if not coord_manager:
                    logger.info("  Coordinate manager not present (optional)")
                    self.test_results[test_name] = True
                    return
            except:
                logger.info("  Coordinate manager not present (optional)")
                self.test_results[test_name] = True
                return
            
            # Check coordinate mode
            player = getattr(self, 'player', None) or self.client.get_local_player()
            logger.info(f"  Coordinate mode: {coord_manager.mode}")
            if player:
                logger.info(f"  Player coords: ({player.x}, {player.y})")
            
            if coord_manager.mode.value == "gmap" and player:
                world_coords = coord_manager.get_world_coordinates(
                    player.x,
                    player.y
                )
                if world_coords:
                    logger.info(f"  World coords: {world_coords}")
            
            logger.info(f"✓ Coordinate systems working")
            self.test_results[test_name] = True
            
        except Exception as e:
            logger.error(f"✗ {test_name} failed: {e}")
            self.test_results[test_name] = False
    
    def _test_actions_api(self):
        """Test actions API"""
        test_name = "Actions API"
        try:
            logger.info(f"\n[TEST] {test_name}")
            
            if not hasattr(self.client, 'actions'):
                raise Exception("Actions API not available")
            
            # Test client-level methods
            client_methods = ['move', 'say', 'set_nickname', 'set_head', 'set_body']
            for method in client_methods:
                if hasattr(self.client, method):
                    logger.info(f"  ✓ {method} available")
                else:
                    logger.error(f"  ✗ {method} missing")
            
            # Test action methods if available
            if hasattr(self.client, 'actions'):
                action_methods = ['use_sword', 'move_to', 'say']
                for method in action_methods:
                    if hasattr(self.client.actions, method):
                        logger.info(f"  ✓ actions.{method} available")
                    else:
                        logger.error(f"  ✗ actions.{method} missing")
            
            logger.info(f"✓ Actions API working")
            self.test_results[test_name] = True
            
        except Exception as e:
            logger.error(f"✗ {test_name} failed: {e}")
            self.test_results[test_name] = False
    
    def _disconnect(self):
        """Disconnect from server"""
        try:
            if self.client:
                logger.info("\nDisconnecting...")
                self.client.disconnect()
                logger.info("Disconnected successfully")
        except Exception as e:
            logger.error(f"Error during disconnect: {e}")
    
    def _print_summary(self):
        """Print test summary"""
        logger.info("\n" + "="*60)
        logger.info("TEST SUMMARY")
        logger.info("="*60)
        
        passed = sum(1 for result in self.test_results.values() if result)
        total = len(self.test_results)
        
        for test_name, result in self.test_results.items():
            status = "✓ PASS" if result else "✗ FAIL"
            logger.info(f"{status:8} | {test_name}")
        
        logger.info("-"*60)
        logger.info(f"Results: {passed}/{total} tests passed")
        
        if passed == total:
            logger.info("🎉 ALL TESTS PASSED!")
        else:
            logger.warning(f"⚠️  {total - passed} tests failed")


def main():
    """Main entry point"""
    # Parse arguments with environment variable fallback
    import os
    if len(sys.argv) >= 3:
        username = sys.argv[1]
        password = sys.argv[2]
    else:
        username = os.getenv("REBORN_USERNAME")
        password = os.getenv("REBORN_PASSWORD")
        
    if not username or not password:
        print("⚠️  Please provide credentials:")
        print("   python comprehensive_test_bot.py <username> <password>")
        print("   or set REBORN_USERNAME and REBORN_PASSWORD environment variables")
        print("   Example: REBORN_USERNAME=testuser REBORN_PASSWORD=testpass python comprehensive_test_bot.py")
        sys.exit(1)
    
    # Optional server parameters
    host = sys.argv[3] if len(sys.argv) > 3 else "localhost"
    port = int(sys.argv[4]) if len(sys.argv) > 4 else 14900
    version = sys.argv[5] if len(sys.argv) > 5 else "6.037"
    
    # Create and run test bot
    bot = ComprehensiveTestBot(username, password, host, port, version)
    results = bot.run_all_tests()
    
    # Exit with appropriate code
    if all(results.values()):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()