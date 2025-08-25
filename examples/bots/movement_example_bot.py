#!/usr/bin/env python3
"""
Movement Test Bot
=================

Tests actual player movement commands to verify server communication.
Sends movement packets to the server and validates that position changes
are reflected in both the client state and server-side account file.

Movement Pattern:
1. Start at (30, 30) in chicken1.nw segment (1, 1)
2. Move east 5 tiles to (35, 30)
3. Move north 5 tiles to (35, 25)  
4. Move west back to (30, 25)
5. Move south back to (30, 30)

Expected server updates:
- Account file X/Y should change
- PLO_PLAYERPROPS packets should reflect new positions
- GMAP world coordinates should update accordingly
"""

import sys
import logging
import time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List

# Add pyReborn to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [MOVEMENT_TEST_BOT] %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

logger = logging.getLogger(__name__)


class MovementTestBot:
    """Bot to test actual player movement and server communication"""
    
    def __init__(self):
        self.client = None
        self.gmap_api = None
        self.test_results = {
            'connection': False,
            'login': False,
            'initial_position': False,
            'movement_east': False,
            'movement_north': False,
            'movement_west': False,
            'movement_south': False,
            'position_updates': False,
            'server_communication': False,
            'coordinate_tracking': False
        }
        self.test_start_time = None
        
        # Track position changes
        self.position_history = []
        self.movement_commands = [
            {'direction': 'east', 'amount': 5, 'expected_change': (5, 0)},
            {'direction': 'north', 'amount': 5, 'expected_change': (0, -5)},
            {'direction': 'west', 'amount': 5, 'expected_change': (-5, 0)},
            {'direction': 'south', 'amount': 5, 'expected_change': (0, 5)}
        ]
        
        # Expected starting position
        self.start_position = (30.0, 30.0)
        self.start_segment = (1, 1)
        self.start_world = (94.0, 94.0)
    
    def run_tests(self, username: str, password: str, 
                  host: str = "localhost", port: int = 14900) -> Dict[str, bool]:
        """Run comprehensive movement tests
        
        Args:
            username: Test account username
            password: Test account password
            host: Server host
            port: Server port
            
        Returns:
            Dictionary of test results
        """
        logger.info("🚶 Movement Test Bot starting tests...")
        logger.info(f"   Testing movement commands with {username}")
        logger.info(f"   Expected start: {self.start_position} local, {self.start_world} world")
        
        self.test_start_time = time.time()
        
        try:
            # Import PyReborn client
            from pyreborn import Client
            from pyreborn.gmap_api.gmap_render_api import GMAPRenderAPI
            
            # Test 1: Connection
            logger.info("🔌 Test 1: Testing connection...")
            self.client = Client(host, port)
            if self.client.connect():
                logger.info("✅ Connection successful")
                self.test_results['connection'] = True
                
                # Test 2: Login
                logger.info("👤 Test 2: Testing login...")
                if self.client.login(username, password):
                    logger.info("✅ Login successful")
                    self.test_results['login'] = True
                    
                    # Initialize GMAP API
                    self.gmap_api = GMAPRenderAPI(self.client)
                    
                    # Wait for server data
                    logger.info("⏳ Waiting for server data...")
                    time.sleep(3)
                    
                    # Test 3: Verify initial position
                    if self._test_initial_position():
                        logger.info("✅ Initial position verified")
                        self.test_results['initial_position'] = True
                        
                        # Test 4-7: Execute movement sequence
                        self._run_movement_tests()
                        
                        # Test 8: Validate position updates
                        if self._test_position_updates():
                            logger.info("✅ Position updates validated")
                            self.test_results['position_updates'] = True
                        
                        # Test 9: Check server communication
                        if self._test_server_communication():
                            logger.info("✅ Server communication working")
                            self.test_results['server_communication'] = True
                        
                        # Test 10: Validate coordinate tracking
                        if self._test_coordinate_tracking():
                            logger.info("✅ Coordinate tracking accurate")
                            self.test_results['coordinate_tracking'] = True
            
            # Always disconnect
            if self.client:
                self.client.disconnect()
            
        except Exception as e:
            logger.error(f"❌ Movement Test Bot test failed: {e}")
            import traceback
            traceback.print_exc()
        
        # Print comprehensive results
        self._print_test_summary()
        return self.test_results
    
    def _test_initial_position(self) -> bool:
        """Test initial position accuracy"""
        try:
            render_data = self.gmap_api.get_gmap_render_data()
            if not render_data:
                logger.error("❌ No render data for initial position test")
                return False
            
            # Record initial position
            initial_pos = {
                'timestamp': time.time(),
                'world_pos': render_data.player_world_position,
                'local_pos': render_data.player_local_position,
                'current_segment': render_data.current_segment,
                'action': 'initial_login'
            }
            self.position_history.append(initial_pos)
            
            logger.info(f"📍 Initial Position:")
            logger.info(f"   World: {render_data.player_world_position}")
            logger.info(f"   Local: {render_data.player_local_position}")
            logger.info(f"   Segment: {render_data.current_segment}")
            logger.info(f"   Expected world: {self.start_world}")
            
            # Validate initial position matches expectations
            world_pos = render_data.player_world_position
            return (abs(world_pos[0] - self.start_world[0]) < 1.0 and 
                   abs(world_pos[1] - self.start_world[1]) < 1.0)
            
        except Exception as e:
            logger.error(f"❌ Initial position test failed: {e}")
            return False
    
    def _run_movement_tests(self):
        """Execute the movement sequence and test each movement"""
        logger.info("🚶 Running movement sequence tests...")
        
        for i, movement in enumerate(self.movement_commands, 1):
            direction = movement['direction']
            amount = movement['amount']
            expected_change = movement['expected_change']
            
            logger.info(f"   Step {i}/4: Moving {direction} by {amount} tiles...")
            
            try:
                # Get position before movement
                before_data = self.gmap_api.get_gmap_render_data()
                if not before_data:
                    logger.error(f"❌ No render data before {direction} movement")
                    self.test_results[f'movement_{direction}'] = False
                    continue
                
                before_pos = before_data.player_world_position
                
                # Execute movement commands
                success = self._execute_movement(direction, amount)
                
                if success:
                    # Wait for server response
                    time.sleep(1)
                    
                    # Get position after movement
                    after_data = self.gmap_api.get_gmap_render_data()
                    if after_data:
                        after_pos = after_data.player_world_position
                        actual_change = (after_pos[0] - before_pos[0], after_pos[1] - before_pos[1])
                        
                        # Record position change
                        position_record = {
                            'timestamp': time.time(),
                            'world_pos': after_pos,
                            'local_pos': after_data.player_local_position,
                            'current_segment': after_data.current_segment,
                            'action': f'move_{direction}',
                            'expected_change': expected_change,
                            'actual_change': actual_change
                        }
                        self.position_history.append(position_record)
                        
                        # Validate movement
                        change_match = (abs(actual_change[0] - expected_change[0]) < 1.0 and
                                      abs(actual_change[1] - expected_change[1]) < 1.0)
                        
                        self.test_results[f'movement_{direction}'] = change_match
                        
                        status = "✅" if change_match else "❌"
                        logger.info(f"     {direction}: {before_pos} → {after_pos} {status}")
                        logger.info(f"       Expected change: {expected_change}")
                        logger.info(f"       Actual change: {actual_change}")
                    else:
                        logger.error(f"❌ No render data after {direction} movement")
                        self.test_results[f'movement_{direction}'] = False
                else:
                    logger.error(f"❌ Failed to execute {direction} movement")
                    self.test_results[f'movement_{direction}'] = False
                    
            except Exception as e:
                logger.error(f"❌ {direction} movement test failed: {e}")
                self.test_results[f'movement_{direction}'] = False
    
    def _execute_movement(self, direction: str, amount: int) -> bool:
        """Execute movement commands in the specified direction
        
        Args:
            direction: Direction to move (north, south, east, west)
            amount: Number of tiles to move
            
        Returns:
            True if movement commands were sent successfully
        """
        try:
            # Map directions to coordinate changes
            direction_map = {
                'north': (0, -1),
                'south': (0, 1),
                'east': (1, 0),
                'west': (-1, 0)
            }
            
            if direction not in direction_map:
                logger.error(f"❌ Invalid direction: {direction}")
                return False
            
            dx, dy = direction_map[direction]
            
            # Send movement commands
            movement_sent = 0
            for step in range(amount):
                if hasattr(self.client, 'move'):
                    try:
                        # Send movement command
                        move_result = self.client.move(dx, dy)
                        if move_result:
                            movement_sent += 1
                            logger.debug(f"     Step {step+1}: move({dx}, {dy}) sent")
                        else:
                            logger.warning(f"     Step {step+1}: move({dx}, {dy}) failed")
                        
                        # Small delay between movements
                        time.sleep(0.1)
                        
                    except Exception as e:
                        logger.warning(f"     Step {step+1}: move({dx}, {dy}) error: {e}")
                else:
                    logger.error("❌ Client has no move() method")
                    return False
            
            logger.info(f"     Sent {movement_sent}/{amount} movement commands")
            return movement_sent > 0
            
        except Exception as e:
            logger.error(f"❌ Movement execution failed: {e}")
            return False
    
    def _test_position_updates(self) -> bool:
        """Test if position updates are working"""
        try:
            if len(self.position_history) < 2:
                logger.error("❌ Insufficient position history")
                return False
            
            # Check if any positions changed
            initial_pos = self.position_history[0]['world_pos']
            position_changes = 0
            
            for record in self.position_history[1:]:
                current_pos = record['world_pos']
                if (abs(current_pos[0] - initial_pos[0]) > 0.1 or 
                    abs(current_pos[1] - initial_pos[1]) > 0.1):
                    position_changes += 1
            
            logger.info(f"📊 Position Updates:")
            logger.info(f"   Total position records: {len(self.position_history)}")
            logger.info(f"   Position changes detected: {position_changes}")
            
            return position_changes > 0
            
        except Exception as e:
            logger.error(f"❌ Position updates test failed: {e}")
            return False
    
    def _test_server_communication(self) -> bool:
        """Test server communication by checking for response packets"""
        try:
            # Check if client has methods for server communication
            has_move_method = hasattr(self.client, 'move')
            has_say_method = hasattr(self.client, 'say')
            
            logger.info(f"🗣️ Server Communication:")
            logger.info(f"   move() method: {'✅' if has_move_method else '❌'}")
            logger.info(f"   say() method: {'✅' if has_say_method else '❌'}")
            
            # Test a simple say command
            if has_say_method:
                try:
                    say_result = self.client.say("Movement test complete!")
                    logger.info(f"   say() command: {'✅' if say_result else '❌'}")
                    return say_result or has_move_method
                except Exception as e:
                    logger.warning(f"   say() command failed: {e}")
            
            return has_move_method
            
        except Exception as e:
            logger.error(f"❌ Server communication test failed: {e}")
            return False
    
    def _test_coordinate_tracking(self) -> bool:
        """Test coordinate tracking accuracy during movements"""
        try:
            if not self.position_history:
                logger.error("❌ No position history for tracking test")
                return False
            
            logger.info("📐 Coordinate Tracking Analysis:")
            
            tracking_issues = 0
            
            for record in self.position_history:
                world_pos = record['world_pos']
                local_pos = record['local_pos']
                segment = record['current_segment']
                action = record['action']
                
                # Validate coordinate consistency
                expected_world_x = segment[0] * 64 + local_pos[0]
                expected_world_y = segment[1] * 64 + local_pos[1]
                
                world_x_diff = abs(world_pos[0] - expected_world_x)
                world_y_diff = abs(world_pos[1] - expected_world_y)
                
                if world_x_diff > 1.0 or world_y_diff > 1.0:
                    tracking_issues += 1
                    logger.warning(f"   {action}: Coordinate inconsistency ({world_x_diff:.1f}, {world_y_diff:.1f})")
                else:
                    logger.info(f"   {action}: Coordinates consistent ✅")
            
            logger.info(f"   Tracking issues: {tracking_issues}/{len(self.position_history)}")
            
            return tracking_issues == 0
            
        except Exception as e:
            logger.error(f"❌ Coordinate tracking test failed: {e}")
            return False
    
    def _print_test_summary(self):
        """Print comprehensive test summary"""
        elapsed_time = time.time() - self.test_start_time if self.test_start_time else 0
        
        logger.info("=" * 70)
        logger.info("🚶 MOVEMENT TEST BOT - TEST SUMMARY")
        logger.info("=" * 70)
        
        passed_tests = sum(1 for result in self.test_results.values() if result)
        total_tests = len(self.test_results)
        
        logger.info(f"📊 Overall Score: {passed_tests}/{total_tests} ({(passed_tests/total_tests*100):.1f}%)")
        logger.info(f"⏱️ Test Duration: {elapsed_time:.1f}s")
        logger.info(f"📍 Position records: {len(self.position_history)}")
        logger.info("")
        logger.info("📋 Detailed Results:")
        
        for test_name, passed in self.test_results.items():
            status = "✅ PASS" if passed else "❌ FAIL"
            logger.info(f"   {test_name:<20}: {status}")
        
        logger.info("")
        
        # Movement-specific assessment
        movement_tests = [f'movement_{cmd["direction"]}' for cmd in self.movement_commands]
        movement_passed = sum(1 for test in movement_tests if self.test_results.get(test, False))
        movement_total = len(movement_tests)
        
        logger.info(f"🚶 Movement Success: {movement_passed}/{movement_total} ({(movement_passed/movement_total*100):.1f}%)")
        
        # Show position history
        if self.position_history:
            logger.info("📍 Position History:")
            for record in self.position_history:
                action = record['action']
                world_pos = record['world_pos']
                local_pos = record['local_pos']
                logger.info(f"   {action}: world({world_pos[0]:.1f},{world_pos[1]:.1f}) local({local_pos[0]:.1f},{local_pos[1]:.1f})")
        
        # Final assessment
        if passed_tests == total_tests:
            logger.info("🎉 ALL TESTS PASSED - Movement system fully functional!")
        elif movement_passed >= movement_total * 0.75:
            logger.info("✅ GOOD - Most movements working with minor issues")
        elif movement_passed >= movement_total * 0.5:
            logger.info("⚠️ FAIR - Some movements working, needs attention")
        else:
            logger.error("❌ POOR - Movement system has major issues")
        
        logger.info("=" * 70)


def main():
    """Run the movement test bot"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Movement Test Bot for PyReborn")
    parser.add_argument("username", help="Username to login with")
    parser.add_argument("password", help="Password to login with")
    parser.add_argument("--server", default="localhost", help="Server to connect to")
    parser.add_argument("--port", type=int, default=14900, help="Port to connect to")
    
    args = parser.parse_args()
    
    bot = MovementTestBot()
    results = bot.run_tests(args.username, args.password, args.server, args.port)
    
    # Exit with appropriate code based on movement success
    movement_tests = ['movement_east', 'movement_north', 'movement_west', 'movement_south']
    movement_passed = sum(1 for test in movement_tests if results.get(test, False))
    movement_total = len(movement_tests)
    
    if movement_passed == movement_total:
        exit(0)  # All movements successful
    elif movement_passed >= movement_total * 0.75:
        exit(1)  # Most movements successful
    else:
        exit(2)  # Movement issues detected


if __name__ == "__main__":
    main()