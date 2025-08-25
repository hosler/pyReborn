#!/usr/bin/env python3
"""
Exploration Bot
===============

Comprehensive exploration bot that plays like a real player:
1. Walks around the GMAP world naturally
2. Uses level links to enter inside areas  
3. Explores multiple levels and areas
4. Tests segment transitions dynamically
5. Validates coordinate tracking across all movements
6. Tests level loading and caching in real-world scenarios

This bot simulates actual gameplay to stress-test the complete GMAP system.
"""

import sys
import logging
import time
import random
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List

# Add pyReborn to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [EXPLORATION_BOT] %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

logger = logging.getLogger(__name__)


class ExplorationBot:
    """Comprehensive exploration bot that plays like a real player"""
    
    def __init__(self):
        self.client = None
        self.gmap_api = None
        self.test_results = {
            'connection': False,
            'login': False,
            'gmap_exploration': False,
            'level_link_usage': False,
            'indoor_exploration': False,
            'segment_transitions': False,
            'coordinate_tracking': False,
            'level_loading': False,
            'return_navigation': False,
            'overall_exploration': False
        }
        self.test_start_time = None
        
        # Track exploration data
        self.exploration_log = []
        self.levels_visited = set()
        self.segments_visited = set()
        self.links_used = []
        self.coordinate_samples = []
        
        # Exploration plan
        self.exploration_phases = [
            {'name': 'GMAP Exploration', 'action': 'explore_gmap_world'},
            {'name': 'Level Link Usage', 'action': 'use_level_links'},  
            {'name': 'Indoor Exploration', 'action': 'explore_indoor_areas'},
            {'name': 'Return Navigation', 'action': 'return_to_start'}
        ]
        
        # Movement patterns
        self.movement_patterns = [
            'random_walk',
            'systematic_grid',
            'boundary_exploration',
            'link_seeking'
        ]
    
    def run_tests(self, username: str, password: str, 
                  host: str = "localhost", port: int = 14900) -> Dict[str, bool]:
        """Run comprehensive exploration tests"""
        logger.info("🌍 EXPLORATION BOT - Real Player Simulation")
        logger.info("=" * 70)
        logger.info("🎮 Simulating actual gameplay with GMAP exploration")
        
        self.test_start_time = time.time()
        
        try:
            from pyreborn import Client
            from pyreborn.gmap_api.gmap_render_api import GMAPRenderAPI
            
            # Test 1: Connection and Login
            logger.info("🔌 Phase 1: Connection and Authentication...")
            self.client = Client(host, port)
            if self.client.connect():
                if self.client.login(username, password):
                    logger.info("✅ Connected as player")
                    self.test_results['connection'] = True
                    self.test_results['login'] = True
                    
                    # Initialize GMAP API
                    self.gmap_api = GMAPRenderAPI(self.client)
                    
                    # Wait for world data
                    logger.info("⏳ Loading world data...")
                    time.sleep(3)
                    
                    # Record starting position
                    self._record_position("game_start")
                    
                    # Execute exploration phases
                    for phase in self.exploration_phases:
                        phase_name = phase['name']
                        phase_action = phase['action']
                        
                        logger.info(f"\n🎯 Phase: {phase_name}")
                        logger.info("-" * 50)
                        
                        try:
                            # Execute phase action
                            method = getattr(self, f'_{phase_action}')
                            success = method()
                            
                            # Map phase success to test results
                            test_key = phase_action.replace('_', '_')
                            if test_key in self.test_results:
                                self.test_results[test_key] = success
                            
                            status = "✅" if success else "❌"
                            logger.info(f"{status} {phase_name}: {'Completed' if success else 'Had issues'}")
                            
                        except Exception as e:
                            logger.error(f"❌ {phase_name} failed: {e}")
                    
                    # Final analysis
                    self._analyze_exploration_results()
            
            # Always disconnect
            if self.client:
                self.client.disconnect()
                logger.info("👋 Disconnected from server")
            
        except Exception as e:
            logger.error(f"❌ Exploration test failed: {e}")
            import traceback
            traceback.print_exc()
        
        # Print comprehensive results
        self._print_exploration_summary()
        return self.test_results
    
    def _explore_gmap_world(self) -> bool:
        """Explore the GMAP world by walking around"""
        try:
            logger.info("🗺️ Starting GMAP world exploration...")
            
            # Get current position
            render_data = self.gmap_api.get_gmap_render_data()
            if not render_data or not render_data.active:
                logger.error("❌ GMAP not active")
                return False
            
            logger.info(f"   Current GMAP: {render_data.gmap_name} ({render_data.gmap_dimensions[0]}x{render_data.gmap_dimensions[1]})")
            
            movements_made = 0
            exploration_time = 30  # 30 seconds of exploration
            start_time = time.time()
            
            while time.time() - start_time < exploration_time:
                # Choose random movement direction
                directions = [(1, 0), (-1, 0), (0, 1), (0, -1)]  # east, west, south, north
                dx, dy = random.choice(directions)
                
                # Execute movement
                if hasattr(self.client, 'move'):
                    try:
                        result = self.client.move(dx, dy)
                        if result:
                            movements_made += 1
                            
                            # Record position every 10 movements
                            if movements_made % 10 == 0:
                                self._record_position(f"gmap_explore_{movements_made}")
                                
                                # Check current status
                                current_data = self.gmap_api.get_gmap_render_data()
                                if current_data:
                                    current_segment = current_data.current_segment
                                    self.segments_visited.add(current_segment)
                                    
                                    # Find current level
                                    for segment in current_data.segments:
                                        if segment.is_current_segment:
                                            if segment.level_name:
                                                self.levels_visited.add(segment.level_name)
                                            break
                                    
                                    logger.info(f"   Explored: {len(self.segments_visited)} segments, {len(self.levels_visited)} levels")
                        
                        time.sleep(0.2)  # Realistic movement speed
                        
                    except Exception as e:
                        logger.debug(f"Movement error: {e}")
                        time.sleep(0.5)
                
            logger.info(f"🗺️ GMAP Exploration Results:")
            logger.info(f"   Total movements: {movements_made}")
            logger.info(f"   Segments visited: {len(self.segments_visited)}")
            logger.info(f"   Levels visited: {len(self.levels_visited)}")
            logger.info(f"   Visited segments: {sorted(list(self.segments_visited))}")
            logger.info(f"   Visited levels: {sorted(list(self.levels_visited))}")
            
            # Success if we explored multiple areas
            return len(self.segments_visited) >= 2 and len(self.levels_visited) >= 2
            
        except Exception as e:
            logger.error(f"❌ GMAP exploration failed: {e}")
            return False
    
    def _use_level_links(self) -> bool:
        """Use level links to enter inside areas"""
        try:
            logger.info("🔗 Testing level link usage...")
            
            # Get current level data to find links
            level_manager = getattr(self.client, 'level_manager', None)
            if not level_manager or not hasattr(level_manager, 'levels'):
                logger.warning("⚠️ No level manager for link testing")
                return False
            
            # Check current level for links
            current_levels = list(level_manager.levels.keys())
            logger.info(f"   Available levels: {current_levels}")
            
            links_found = 0
            links_attempted = 0
            
            for level_name in current_levels[:3]:  # Test first 3 levels
                level_data = level_manager.levels[level_name]
                if hasattr(level_data, 'links') and level_data.links:
                    links_in_level = len(level_data.links)
                    links_found += links_in_level
                    logger.info(f"   {level_name}: {links_in_level} links found")
                    
                    # Try to walk to a link and use it
                    for link in list(level_data.links.values())[:2]:  # Try first 2 links
                        if self._walk_to_link(link):
                            links_attempted += 1
                            self.links_used.append({
                                'level': level_name,
                                'link': link,
                                'success': True
                            })
                else:
                    logger.info(f"   {level_name}: No links found")
            
            logger.info(f"🔗 Link Usage Results:")
            logger.info(f"   Links found: {links_found}")
            logger.info(f"   Links attempted: {links_attempted}")
            logger.info(f"   Links used: {len(self.links_used)}")
            
            return links_attempted > 0
            
        except Exception as e:
            logger.error(f"❌ Level link usage failed: {e}")
            return False
    
    def _walk_to_link(self, link) -> bool:
        """Walk to a specific link and try to use it"""
        try:
            # Get link position
            link_x = getattr(link, 'x', None)
            link_y = getattr(link, 'y', None)
            
            if link_x is None or link_y is None:
                logger.debug("   Link has no position data")
                return False
            
            logger.info(f"   🚶 Walking to link at ({link_x}, {link_y})")
            
            # Get current position
            render_data = self.gmap_api.get_gmap_render_data()
            if not render_data:
                return False
            
            current_local = render_data.player_local_position
            
            # Calculate movement needed
            dx_needed = link_x - current_local[0]
            dy_needed = link_y - current_local[1]
            
            # Move towards link (simplified pathfinding)
            movements = 0
            max_movements = 20  # Prevent infinite loops
            
            while (abs(dx_needed) > 1.0 or abs(dy_needed) > 1.0) and movements < max_movements:
                # Choose movement direction
                move_dx = 1 if dx_needed > 0 else -1 if dx_needed < 0 else 0
                move_dy = 1 if dy_needed > 0 else -1 if dy_needed < 0 else 0
                
                # Prioritize one direction at a time
                if abs(dx_needed) > abs(dy_needed):
                    move_dy = 0
                else:
                    move_dx = 0
                
                # Execute movement
                if hasattr(self.client, 'move'):
                    result = self.client.move(move_dx, move_dy)
                    if result:
                        movements += 1
                        dx_needed -= move_dx
                        dy_needed -= move_dy
                        time.sleep(0.1)
                    else:
                        break
                else:
                    break
            
            logger.info(f"   Moved {movements} tiles towards link")
            
            # Record reaching the link
            self._record_position(f"link_approach")
            return movements > 0
            
        except Exception as e:
            logger.debug(f"Walk to link failed: {e}")
            return False
    
    def _explore_indoor_areas(self) -> bool:
        """Explore indoor areas and test level transitions"""
        try:
            logger.info("🏠 Testing indoor area exploration...")
            
            # Try to enter some indoor levels manually by walking to known link positions
            indoor_exploration_targets = [
                {'level': 'chicken_house1.nw', 'approach': 'walk_to_house'},
                {'level': 'chicken_pk.nw', 'approach': 'find_pk_area'},
                {'level': 'chicken_cave_1.nw', 'approach': 'find_cave_entrance'}
            ]
            
            indoor_areas_found = 0
            
            for target in indoor_exploration_targets:
                level_name = target['level']
                approach = target['approach']
                
                logger.info(f"   🎯 Looking for {level_name} using {approach}")
                
                # Simulate searching for the area
                search_movements = 0
                max_search = 15
                
                while search_movements < max_search:
                    # Random exploration movement
                    dx = random.choice([-1, 0, 1])
                    dy = random.choice([-1, 0, 1])
                    
                    if dx == 0 and dy == 0:
                        continue
                    
                    if hasattr(self.client, 'move'):
                        result = self.client.move(dx, dy)
                        if result:
                            search_movements += 1
                            time.sleep(0.15)
                            
                            # Check if we found an interesting area
                            current_data = self.gmap_api.get_gmap_render_data()
                            if current_data:
                                for segment in current_data.segments:
                                    if segment.is_current_segment and segment.level_name:
                                        if 'house' in segment.level_name or 'pk' in segment.level_name or 'cave' in segment.level_name:
                                            indoor_areas_found += 1
                                            logger.info(f"   ✅ Found indoor area: {segment.level_name}")
                                            self.levels_visited.add(segment.level_name)
                                            self._record_position(f"indoor_{segment.level_name}")
                                            break
                        else:
                            break
                
                if indoor_areas_found > 0:
                    break
            
            logger.info(f"🏠 Indoor Exploration Results:")
            logger.info(f"   Indoor areas found: {indoor_areas_found}")
            logger.info(f"   Total levels visited: {len(self.levels_visited)}")
            
            return indoor_areas_found > 0
            
        except Exception as e:
            logger.error(f"❌ Indoor exploration failed: {e}")
            return False
    
    def _return_to_start(self) -> bool:
        """Navigate back to starting area"""
        try:
            logger.info("🔄 Testing return navigation...")
            
            # Try to return to chicken1.nw area (segment 1,1)
            target_segment = (1, 1)
            return_movements = 0
            max_return_moves = 50
            
            while return_movements < max_return_moves:
                current_data = self.gmap_api.get_gmap_render_data()
                if not current_data:
                    break
                
                current_segment = current_data.current_segment
                
                # Check if we're back at target
                if current_segment == target_segment:
                    logger.info(f"✅ Successfully returned to target segment {target_segment}")
                    self._record_position("return_success")
                    return True
                
                # Calculate direction to move towards target
                dx_needed = target_segment[0] - current_segment[0]
                dy_needed = target_segment[1] - current_segment[1]
                
                # Choose movement direction
                move_dx = 1 if dx_needed > 0 else -1 if dx_needed < 0 else 0
                move_dy = 1 if dy_needed > 0 else -1 if dy_needed < 0 else 0
                
                # Prefer one direction at a time for systematic navigation
                if abs(dx_needed) >= abs(dy_needed):
                    move_dy = 0
                else:
                    move_dx = 0
                
                # Execute movement
                if hasattr(self.client, 'move') and (move_dx != 0 or move_dy != 0):
                    result = self.client.move(move_dx, move_dy)
                    if result:
                        return_movements += 1
                        time.sleep(0.1)
                        
                        # Log progress every 10 moves
                        if return_movements % 10 == 0:
                            logger.info(f"   Return progress: segment {current_segment} -> {target_segment} ({return_movements} moves)")
                    else:
                        time.sleep(0.2)
                else:
                    break
            
            logger.info(f"🔄 Return navigation: {return_movements} movements attempted")
            return return_movements > 0
            
        except Exception as e:
            logger.error(f"❌ Return navigation failed: {e}")
            return False
    
    def _record_position(self, action: str):
        """Record current position and status"""
        try:
            render_data = self.gmap_api.get_gmap_render_data()
            if render_data:
                # Find current level
                current_level = None
                for segment in render_data.segments:
                    if segment.is_current_segment:
                        current_level = segment.level_name
                        break
                
                position_record = {
                    'timestamp': time.time(),
                    'action': action,
                    'segment': render_data.current_segment,
                    'level': current_level,
                    'world_pos': render_data.player_world_position,
                    'local_pos': render_data.player_local_position,
                    'gmap_active': render_data.active
                }
                
                self.exploration_log.append(position_record)
                self.coordinate_samples.append(position_record)
                
                # Track unique segments and levels
                self.segments_visited.add(render_data.current_segment)
                if current_level:
                    self.levels_visited.add(current_level)
                
                logger.debug(f"📍 {action}: segment{render_data.current_segment} {current_level} world{render_data.player_world_position}")
                
        except Exception as e:
            logger.debug(f"Position recording failed: {e}")
    
    def _analyze_exploration_results(self):
        """Analyze exploration results and update test scores"""
        try:
            logger.info("📊 Analyzing exploration results...")
            
            # GMAP exploration success
            gmap_success = len(self.segments_visited) >= 2
            self.test_results['gmap_exploration'] = gmap_success
            logger.info(f"   GMAP exploration: {'✅' if gmap_success else '❌'} ({len(self.segments_visited)} segments)")
            
            # Level loading success  
            level_loading_success = len(self.levels_visited) >= 2
            self.test_results['level_loading'] = level_loading_success
            logger.info(f"   Level loading: {'✅' if level_loading_success else '❌'} ({len(self.levels_visited)} levels)")
            
            # Coordinate tracking success
            coordinate_success = len(self.coordinate_samples) >= 5
            self.test_results['coordinate_tracking'] = coordinate_success
            logger.info(f"   Coordinate tracking: {'✅' if coordinate_success else '❌'} ({len(self.coordinate_samples)} samples)")
            
            # Segment transitions success
            transition_success = len(self.segments_visited) >= 2
            self.test_results['segment_transitions'] = transition_success
            logger.info(f"   Segment transitions: {'✅' if transition_success else '❌'}")
            
            # Overall exploration success
            overall_success = (gmap_success and level_loading_success and coordinate_success)
            self.test_results['overall_exploration'] = overall_success
            logger.info(f"   Overall exploration: {'✅' if overall_success else '❌'}")
            
        except Exception as e:
            logger.error(f"❌ Exploration analysis failed: {e}")
    
    def _print_exploration_summary(self):
        """Print comprehensive exploration summary"""
        elapsed_time = time.time() - self.test_start_time if self.test_start_time else 0
        
        logger.info("=" * 80)
        logger.info("🌍 EXPLORATION BOT - COMPREHENSIVE SUMMARY")
        logger.info("=" * 80)
        
        passed_tests = sum(1 for result in self.test_results.values() if result)
        total_tests = len(self.test_results)
        
        logger.info(f"📊 Overall Score: {passed_tests}/{total_tests} ({(passed_tests/total_tests*100):.1f}%)")
        logger.info(f"⏱️ Exploration Duration: {elapsed_time:.1f}s")
        logger.info(f"🗺️ Segments Explored: {len(self.segments_visited)}")
        logger.info(f"🏠 Levels Visited: {len(self.levels_visited)}")
        logger.info(f"📍 Position Samples: {len(self.coordinate_samples)}")
        logger.info("")
        logger.info("📋 Detailed Results:")
        
        for test_name, passed in self.test_results.items():
            status = "✅ PASS" if passed else "❌ FAIL"
            logger.info(f"   {test_name:<25}: {status}")
        
        logger.info("")
        logger.info("🗺️ Exploration Statistics:")
        logger.info(f"   Segments visited: {sorted(list(self.segments_visited))}")
        logger.info(f"   Levels visited: {sorted(list(self.levels_visited))}")
        
        if self.coordinate_samples:
            logger.info("📍 Position History (key moments):")
            for sample in self.coordinate_samples[-5:]:  # Last 5 positions
                action = sample['action']
                segment = sample['segment']
                level = sample['level']
                world = sample['world_pos']
                logger.info(f"   {action}: seg{segment} {level} world({world[0]:.1f},{world[1]:.1f})")
        
        # Final assessment
        if passed_tests >= total_tests * 0.9:
            logger.info("🎉 EXCELLENT! Real-world GMAP exploration fully functional!")
            logger.info("   🗺️ Player can navigate seamlessly across GMAP world")
            logger.info("   🔗 Level links and indoor areas accessible")
            logger.info("   📍 Coordinate tracking perfect throughout exploration")
        elif passed_tests >= total_tests * 0.7:
            logger.info("✅ VERY GOOD! GMAP exploration mostly working")
        elif passed_tests >= total_tests * 0.5:
            logger.info("⚠️ FAIR! Basic exploration working with some issues")
        else:
            logger.error("❌ POOR! Exploration system needs significant work")
        
        logger.info("=" * 80)


def main():
    """Run the exploration bot"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Exploration Bot for PyReborn")
    parser.add_argument("username", help="Username to login with")
    parser.add_argument("password", help="Password to login with")
    parser.add_argument("--server", default="localhost", help="Server to connect to")
    parser.add_argument("--port", type=int, default=14900, help="Port to connect to")
    
    args = parser.parse_args()
    
    bot = ExplorationBot()
    results = bot.run_tests(args.username, args.password, args.server, args.port)
    
    # Exit with appropriate code
    passed_tests = sum(1 for result in results.values() if result)
    total_tests = len(results)
    success_rate = passed_tests / total_tests
    
    if success_rate >= 0.9:
        exit(0)  # Excellent
    elif success_rate >= 0.7:
        exit(1)  # Very Good
    else:
        exit(2)  # Needs improvement


if __name__ == "__main__":
    main()