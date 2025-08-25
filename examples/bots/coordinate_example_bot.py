#!/usr/bin/env python3
"""
Coordinate Validation Bot
=========================

Specialized bot to validate your_username's specific position in chicken1.nw.
Tests coordinate calculations, segment detection, and world position accuracy.

Expected State:
- Level: chicken1.nw
- Segment: (1, 1) in chicken.gmap
- Local coords: (30, 30)
- Expected world coords: (94, 94) = (1*64 + 30, 1*64 + 30)
"""

import sys
import logging
import time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

# Add pyReborn to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [COORDINATE_VALIDATION_BOT] %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

logger = logging.getLogger(__name__)


class CoordinateValidationBot:
    """Specialized bot to validate coordinate calculations for your_username"""
    
    def __init__(self):
        self.client = None
        self.gmap_api = None
        self.test_results = {
            'connection': False,
            'login': False,
            'gmap_mode_active': False,
            'expected_level': False,
            'expected_segment': False,
            'expected_local_coords': False,
            'expected_world_coords': False,
            'coordinate_consistency': False,
            'segment_calculation': False,
            'api_data_quality': False
        }
        self.test_start_time = None
        
        # Expected values for your_username (dynamically determined from account file)
        self.expected_level = "chicken1.nw"
        self.expected_segment = (1, 1)
        
        # Read current position from account file instead of hardcoded values
        self.expected_local_coords = self._read_account_position()
        if self.expected_local_coords:
            # Calculate world coordinates from actual position
            self.expected_world_coords = (
                self.expected_segment[0] * 64 + self.expected_local_coords[0],
                self.expected_segment[1] * 64 + self.expected_local_coords[1]
            )
        else:
            # Fallback to original values
            self.expected_local_coords = (30.0, 30.0)
            self.expected_world_coords = (94.0, 94.0)
        
        # Tolerance for coordinate comparisons
        self.coord_tolerance = 1.0
    
    def run_tests(self, username: str, password: str, 
                  host: str = "localhost", port: int = 14900) -> Dict[str, bool]:
        """Run comprehensive coordinate validation tests
        
        Args:
            username: Test account username (should be your_username)
            password: Test account password
            host: Server host
            port: Server port
            
        Returns:
            Dictionary of test results
        """
        logger.info("🔍 Coordinate Validation Bot starting tests...")
        logger.info(f"   Target: {username} in {self.expected_level}")
        logger.info(f"   Expected segment: {self.expected_segment}")
        logger.info(f"   Expected local coords: {self.expected_local_coords}")
        logger.info(f"   Expected world coords: {self.expected_world_coords}")
        
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
                    
                    # Test 3: GMAP mode activation
                    if self._test_gmap_mode():
                        logger.info("✅ GMAP mode active")
                        self.test_results['gmap_mode_active'] = True
                        
                        # Test 4: Expected level verification
                        if self._test_expected_level():
                            logger.info("✅ In expected level")
                            self.test_results['expected_level'] = True
                            
                            # Test 5: Coordinate validation tests
                            self._run_coordinate_tests()
                            
                            # Test 6: API data quality
                            if self._test_api_data_quality():
                                logger.info("✅ API data quality good")
                                self.test_results['api_data_quality'] = True
            
            # Always disconnect
            if self.client:
                self.client.disconnect()
            
        except Exception as e:
            logger.error(f"❌ Coordinate Validation Bot test failed: {e}")
            import traceback
            traceback.print_exc()
        
        # Print comprehensive results
        self._print_test_summary()
        return self.test_results
    
    def _test_gmap_mode(self) -> bool:
        """Test if GMAP mode is active"""
        try:
            render_data = self.gmap_api.get_gmap_render_data()
            if render_data and render_data.active:
                logger.info(f"📊 GMAP active: {render_data.gmap_name}")
                logger.info(f"   Dimensions: {render_data.gmap_dimensions}")
                return True
            else:
                logger.warning("⚠️ GMAP mode not active")
                return False
        except Exception as e:
            logger.error(f"❌ GMAP mode test failed: {e}")
            return False
    
    def _test_expected_level(self) -> bool:
        """Test if we're in the expected level"""
        try:
            # Check session manager for current level
            session_manager = getattr(self.client, 'session_manager', None)
            if not session_manager:
                logger.error("❌ No session manager available")
                return False
            
            # Get effective level name (actual level, not GMAP file)
            current_level = None
            if hasattr(session_manager, 'get_effective_level_name'):
                current_level = session_manager.get_effective_level_name()
            
            if not current_level and hasattr(session_manager, 'current_level_name'):
                tracked_level = session_manager.current_level_name
                if tracked_level and not tracked_level.endswith('.gmap'):
                    current_level = tracked_level
            
            logger.info(f"📍 Current level: {current_level}")
            logger.info(f"   Expected level: {self.expected_level}")
            
            if current_level == self.expected_level:
                return True
            else:
                logger.warning(f"⚠️ Level mismatch: got {current_level}, expected {self.expected_level}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Expected level test failed: {e}")
            return False
    
    def _run_coordinate_tests(self):
        """Run all coordinate validation tests"""
        try:
            render_data = self.gmap_api.get_gmap_render_data()
            if not render_data:
                logger.error("❌ No render data for coordinate tests")
                return
            
            logger.info("📐 Running coordinate validation tests...")
            
            # Test segment coordinates
            current_segment = render_data.current_segment
            logger.info(f"   Current segment: {current_segment}")
            logger.info(f"   Expected segment: {self.expected_segment}")
            
            if current_segment == self.expected_segment:
                logger.info("✅ Segment coordinates match")
                self.test_results['expected_segment'] = True
            else:
                logger.warning(f"⚠️ Segment mismatch: got {current_segment}, expected {self.expected_segment}")
            
            # Test local coordinates
            local_coords = render_data.player_local_position
            logger.info(f"   Local coords: ({local_coords[0]:.1f}, {local_coords[1]:.1f})")
            logger.info(f"   Expected local: {self.expected_local_coords}")
            
            local_x_match = abs(local_coords[0] - self.expected_local_coords[0]) <= self.coord_tolerance
            local_y_match = abs(local_coords[1] - self.expected_local_coords[1]) <= self.coord_tolerance
            
            if local_x_match and local_y_match:
                logger.info("✅ Local coordinates match")
                self.test_results['expected_local_coords'] = True
            else:
                logger.warning(f"⚠️ Local coordinate mismatch")
                logger.warning(f"   X diff: {abs(local_coords[0] - self.expected_local_coords[0]):.1f}")
                logger.warning(f"   Y diff: {abs(local_coords[1] - self.expected_local_coords[1]):.1f}")
            
            # Test world coordinates
            world_coords = render_data.player_world_position
            logger.info(f"   World coords: ({world_coords[0]:.1f}, {world_coords[1]:.1f})")
            logger.info(f"   Expected world: {self.expected_world_coords}")
            
            world_x_match = abs(world_coords[0] - self.expected_world_coords[0]) <= self.coord_tolerance
            world_y_match = abs(world_coords[1] - self.expected_world_coords[1]) <= self.coord_tolerance
            
            if world_x_match and world_y_match:
                logger.info("✅ World coordinates match")
                self.test_results['expected_world_coords'] = True
            else:
                logger.warning(f"⚠️ World coordinate mismatch")
                logger.warning(f"   X diff: {abs(world_coords[0] - self.expected_world_coords[0]):.1f}")
                logger.warning(f"   Y diff: {abs(world_coords[1] - self.expected_world_coords[1]):.1f}")
            
            # Test coordinate consistency (world = segment * 64 + local)
            calculated_world_x = current_segment[0] * 64 + local_coords[0]
            calculated_world_y = current_segment[1] * 64 + local_coords[1]
            
            logger.info(f"📊 Coordinate Consistency Check:")
            logger.info(f"   Calculated world: ({calculated_world_x:.1f}, {calculated_world_y:.1f})")
            logger.info(f"   Reported world: ({world_coords[0]:.1f}, {world_coords[1]:.1f})")
            
            calc_x_match = abs(calculated_world_x - world_coords[0]) <= self.coord_tolerance
            calc_y_match = abs(calculated_world_y - world_coords[1]) <= self.coord_tolerance
            
            if calc_x_match and calc_y_match:
                logger.info("✅ Coordinate consistency validated")
                self.test_results['coordinate_consistency'] = True
            else:
                logger.warning(f"⚠️ Coordinate inconsistency detected")
                logger.warning(f"   X diff: {abs(calculated_world_x - world_coords[0]):.1f}")
                logger.warning(f"   Y diff: {abs(calculated_world_y - world_coords[1]):.1f}")
            
            # Test reverse segment calculation
            reverse_seg_x = int(world_coords[0] // 64)
            reverse_seg_y = int(world_coords[1] // 64)
            
            logger.info(f"🔄 Reverse Segment Calculation:")
            logger.info(f"   From world coords: ({reverse_seg_x}, {reverse_seg_y})")
            logger.info(f"   Reported segment: {current_segment}")
            
            if (reverse_seg_x == current_segment[0] and reverse_seg_y == current_segment[1]):
                logger.info("✅ Reverse segment calculation correct")
                self.test_results['segment_calculation'] = True
            else:
                logger.warning(f"⚠️ Reverse segment calculation mismatch")
            
        except Exception as e:
            logger.error(f"❌ Coordinate tests failed: {e}")
            import traceback
            traceback.print_exc()
    
    def _test_api_data_quality(self) -> bool:
        """Test the quality of API data"""
        try:
            render_data = self.gmap_api.get_gmap_render_data()
            if not render_data:
                logger.error("❌ No render data for quality test")
                return False
            
            quality = render_data.server_data_quality
            debug_info = render_data.debug_info
            
            logger.info(f"📋 API Data Quality Assessment:")
            logger.info(f"   GMAP File: {'✅' if quality.get('has_gmap_file') else '❌'}")
            logger.info(f"   World Coordinates: {'✅' if quality.get('has_world_coordinates') else '❌'}")
            logger.info(f"   Segment Data: {'✅' if quality.get('has_segment_data') else '❌'}")
            logger.info(f"   Level Data: {'✅' if quality.get('has_level_data') else '❌'}")
            logger.info(f"   Coordinate Source: {quality.get('coordinate_source', 'unknown')}")
            
            # Check debug info
            validation = debug_info.get('validation_status', {})
            is_valid = validation.get('valid', False)
            issues = validation.get('issues', [])
            warnings = validation.get('warnings', [])
            
            logger.info(f"   Validation Status: {'✅' if is_valid else '❌'}")
            logger.info(f"   Issues: {len(issues)}")
            logger.info(f"   Warnings: {len(warnings)}")
            
            # Log any issues
            for issue in issues:
                logger.warning(f"     Issue: {issue}")
            for warning in warnings:
                logger.info(f"     Warning: {warning}")
            
            # Quality passes if we have basic data
            return (quality.get('has_segment_data', False) and 
                   quality.get('coordinate_source', 'unknown') != 'unknown')
            
        except Exception as e:
            logger.error(f"❌ API data quality test failed: {e}")
            return False
    
    def _print_test_summary(self):
        """Print comprehensive test summary"""
        elapsed_time = time.time() - self.test_start_time if self.test_start_time else 0
        
        logger.info("=" * 70)
        logger.info("🔍 COORDINATE VALIDATION BOT - TEST SUMMARY")
        logger.info("=" * 70)
        
        passed_tests = sum(1 for result in self.test_results.values() if result)
        total_tests = len(self.test_results)
        
        logger.info(f"📊 Overall Score: {passed_tests}/{total_tests} ({(passed_tests/total_tests*100):.1f}%)")
        logger.info(f"⏱️ Test Duration: {elapsed_time:.1f}s")
        logger.info("")
        logger.info("📋 Detailed Results:")
        
        for test_name, passed in self.test_results.items():
            status = "✅ PASS" if passed else "❌ FAIL"
            logger.info(f"   {test_name:<25}: {status}")
        
        logger.info("")
        
        # Specific assessment for coordinate accuracy
        coordinate_tests = [
            'expected_segment', 'expected_local_coords', 
            'expected_world_coords', 'coordinate_consistency', 'segment_calculation'
        ]
        coordinate_passed = sum(1 for test in coordinate_tests if self.test_results.get(test, False))
        coordinate_total = len(coordinate_tests)
        
        logger.info(f"🎯 Coordinate Accuracy: {coordinate_passed}/{coordinate_total} ({(coordinate_passed/coordinate_total*100):.1f}%)")
        
        if coordinate_passed == coordinate_total:
            logger.info("🎉 PERFECT COORDINATE ACCURACY - All calculations correct!")
        elif coordinate_passed >= coordinate_total * 0.8:
            logger.info("⚠️ GOOD coordinate accuracy with minor issues")
        else:
            logger.error("❌ POOR coordinate accuracy - Major issues detected")
        
        # Final assessment
        if passed_tests == total_tests:
            logger.info("🎉 ALL TESTS PASSED - your_username position validation complete!")
        elif passed_tests >= total_tests * 0.8:
            logger.info("⚠️ MOST TESTS PASSED - Minor position issues detected")
        else:
            logger.error("❌ MAJOR ISSUES - Position validation failed")
        
        logger.info("=" * 70)
    
    def _read_account_position(self) -> Optional[Tuple[float, float]]:
        """Read current position from account file"""
        try:
            account_file = "/home/test_user/Projects/openreborn2/funtimes/accounts/your_username.txt"
            with open(account_file, 'r') as f:
                x, y = None, None
                for line in f:
                    if line.startswith('X '):
                        x = float(line.split()[1])
                    elif line.startswith('Y '):
                        y = float(line.split()[1])
                if x is not None and y is not None:
                    return (x, y)
            return None
        except Exception as e:
            logger.warning(f"⚠️ Could not read account position: {e}")
            return None


def main():
    """Run the coordinate validation bot"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Coordinate Validation Bot for PyReborn")
    parser.add_argument("username", help="Username to login with")
    parser.add_argument("password", help="Password to login with")
    parser.add_argument("--server", default="localhost", help="Server to connect to")
    parser.add_argument("--port", type=int, default=14900, help="Port to connect to")
    
    args = parser.parse_args()
    
    bot = CoordinateValidationBot()
    results = bot.run_tests(args.username, args.password, args.server, args.port)
    
    # Exit with appropriate code
    coordinate_tests = [
        'expected_segment', 'expected_local_coords', 
        'expected_world_coords', 'coordinate_consistency', 'segment_calculation'
    ]
    coordinate_passed = sum(1 for test in coordinate_tests if results.get(test, False))
    coordinate_total = len(coordinate_tests)
    
    if coordinate_passed == coordinate_total:
        exit(0)  # Perfect coordinate accuracy
    else:
        exit(1)  # Issues detected


if __name__ == "__main__":
    main()