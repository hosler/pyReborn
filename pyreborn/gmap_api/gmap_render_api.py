"""
GMAP Render API
===============

Clean API for pygame clients to get GMAP rendering data.
Handles all GMAP logic in PyReborn, provides simple interface for rendering.
"""

import logging
import time
from typing import Optional, List, Tuple, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SegmentData:
    """Data for rendering a single GMAP segment"""
    segment_coords: Tuple[int, int]  # (x, y) segment coordinates
    world_position: Tuple[float, float]  # World position to render at
    level_name: Optional[str]  # Name of level in this segment
    level_data: Optional[Any]  # Actual level data object for rendering
    is_current_segment: bool  # True if player is in this segment
    is_empty: bool  # True if segment has no level


@dataclass  
class GMAPRenderData:
    """Complete data package for GMAP rendering - fully server-driven"""
    active: bool  # True if GMAP mode is active
    gmap_name: str  # Name of current GMAP from server
    gmap_dimensions: Tuple[int, int]  # (width, height) in segments from server data
    player_world_position: Tuple[float, float]  # Player's world coordinates from server
    player_local_position: Tuple[float, float]  # Player's position within current segment
    camera_target: Tuple[float, float]  # Where camera should focus (follows player)
    current_segment: Tuple[int, int]  # Player's current segment from server data
    segments: List[SegmentData]  # All segments with server-provided level data
    server_data_quality: Dict[str, bool]  # Quality indicators for server data
    debug_info: Dict[str, Any]  # Debug information and validation data


class GMAPRenderAPI:
    """Clean API for GMAP rendering data"""
    
    def __init__(self, client):
        """Initialize with PyReborn client reference
        
        Args:
            client: PyReborn client instance
        """
        self.client = client
        self.logger = logging.getLogger(__name__)
    
    def get_gmap_render_data(self) -> Optional[GMAPRenderData]:
        """Get complete GMAP rendering data
        
        Returns:
            GMAPRenderData with everything needed for rendering, or None if not in GMAP mode
        """
        try:
            # Check if GMAP mode is active
            if not self._is_gmap_active():
                return None
            
            session_manager = getattr(self.client, 'session_manager', None)
            gmap_manager = getattr(self.client, 'gmap_manager', None)
            level_manager = getattr(self.client, 'level_manager', None)
            
            if not all([session_manager, gmap_manager, level_manager]):
                self.logger.warning("Missing required managers for GMAP rendering")
                return None
            
            # Get player information
            player = session_manager.get_player()
            if not player:
                self.logger.warning("No player data available for GMAP rendering")
                return None
            
            # Get current GMAP info - try to parse downloaded file first
            gmap_info = gmap_manager.get_gmap_info()
            if not gmap_info:
                # Check if we're in GMAP mode but data not loaded yet
                if hasattr(gmap_manager, 'is_gmap_mode') and gmap_manager.is_gmap_mode():
                    # Try to parse any downloaded GMAP file before falling back
                    current_level = getattr(session_manager, 'current_level_name', '')
                    if current_level.endswith('.gmap'):
                        # Try to parse the GMAP file
                        if hasattr(gmap_manager, 'check_and_parse_downloaded_gmap_file'):
                            if gmap_manager.check_and_parse_downloaded_gmap_file(current_level):
                                # GMAP parsed successfully - retry getting info
                                gmap_info = gmap_manager.get_gmap_info()
                                if gmap_info:
                                    self.logger.info(f"✅ GMAP file parsed successfully: {current_level}")
                                    # Continue with normal processing below
                                else:
                                    self.logger.warning("GMAP parsing claimed success but no info available")
                    
                    # If still no GMAP info, provide fallback
                    if not gmap_info:
                        # Only log fallback message once per 5 seconds to avoid spam
                        import time
                        current_time = time.time()
                        if not hasattr(self, '_last_fallback_log') or current_time - self._last_fallback_log > 5.0:
                            self.logger.info("GMAP mode active but data not loaded yet - providing basic fallback")
                            self._last_fallback_log = current_time
                        return self._create_fallback_render_data(gmap_manager, session_manager, player)
                else:
                    self.logger.debug("No GMAP info available and not in GMAP mode")
                    return None
            
            # Calculate player world position from server segment data
            player_world_pos, player_local_pos, current_segment = self._calculate_player_positions(player, gmap_manager)
            
            # Get all segment data for rendering
            segments = self._get_all_segments_data(gmap_manager, level_manager, current_segment)
            
            # Assess server data quality
            server_data_quality = {
                'has_gmap_file': bool(gmap_manager.current_gmap),
                'has_world_coordinates': bool(gmap_manager.current_world_x is not None),
                'has_segment_data': bool(current_segment[0] is not None and current_segment[1] is not None),
                'has_level_data': len([s for s in segments if s.level_data]) > 0,
                'coordinate_source': 'server' if gmap_manager.current_world_x is not None else 'resolver'
            }
            
            # Build complete render data with server-driven logic
            render_data = GMAPRenderData(
                active=True,
                gmap_name=gmap_info.get('name', 'unknown'),
                gmap_dimensions=(gmap_info.get('dimensions', {}).get('width', 3), 
                               gmap_info.get('dimensions', {}).get('height', 3)),
                player_world_position=player_world_pos,
                player_local_position=player_local_pos,
                camera_target=player_world_pos,  # Camera follows player position
                current_segment=current_segment,
                segments=segments,
                server_data_quality=server_data_quality,
                debug_info={
                    'loaded_levels': gmap_info.get('loaded_levels', []),
                    'level_count': gmap_info.get('level_count', 0),
                    'segments_with_data': len([s for s in segments if s.level_data]),
                    'total_segments': len(segments),
                    'data_source': 'server_driven',
                    'validation_status': self._validate_render_data(player_world_pos, current_segment, segments)
                }
            )
            
            return render_data
            
        except Exception as e:
            self.logger.error(f"Error getting GMAP render data: {e}")
            return None
    
    def _is_gmap_active(self) -> bool:
        """Check if GMAP mode is currently active"""
        try:
            session_manager = getattr(self.client, 'session_manager', None)
            return session_manager and hasattr(session_manager, 'is_gmap_mode') and session_manager.is_gmap_mode()
        except:
            return False
    
    def _calculate_player_positions(self, player, gmap_manager) -> Tuple[Tuple[float, float], Tuple[float, float], Tuple[int, int]]:
        """Calculate player world position, local position, and current segment from server data
        
        Returns:
            (world_position, local_position, current_segment)
        """
        try:
            # Use server-calculated world coordinates from GMAP manager if available
            if (hasattr(gmap_manager, 'current_world_x') and 
                gmap_manager.current_world_x is not None and
                hasattr(gmap_manager, 'current_world_y') and 
                gmap_manager.current_world_y is not None):
                
                # Get server-calculated world coordinates
                world_x = gmap_manager.current_world_x
                world_y = gmap_manager.current_world_y
                
                # Calculate segment from world coordinates (handle negative coords correctly)
                import math
                segment_x = math.floor(world_x / 64)
                segment_y = math.floor(world_y / 64)
                
                # Calculate local position within segment
                local_x = world_x % 64
                local_y = world_y % 64
                
                # Throttle server position debug messages (major spam source)
            import time
            if not hasattr(self, '_last_server_pos_log') or time.time() - self._last_server_pos_log > 10.0:
                self.logger.debug(f"📊 Server position: world({world_x:.1f},{world_y:.1f}) = segment({segment_x},{segment_y}) + local({local_x:.1f},{local_y:.1f})")
                self._last_server_pos_log = time.time()
                
                return (world_x, world_y), (local_x, local_y), (segment_x, segment_y)
                
            # 🎯 FIX: In GMAP mode, player coordinates are already world coordinates
            # Don't treat them as local coordinates
            world_x = float(player.x)
            world_y = float(player.y)
            
            # Calculate segment from world coordinates
            import math
            segment_x = math.floor(world_x / 64)
            segment_y = math.floor(world_y / 64)
            
            # Calculate local position within segment
            local_x = world_x % 64
            local_y = world_y % 64
            
            # Throttle fallback position debug messages
            import time
            if not hasattr(self, '_last_fallback_pos_log') or time.time() - self._last_fallback_pos_log > 10.0:
                self.logger.debug(f"📊 Fallback position: world({world_x:.1f},{world_y:.1f}) = segment({segment_x},{segment_y}) + local({local_x:.1f},{local_y:.1f})")
                self._last_fallback_pos_log = time.time()
            
            return (world_x, world_y), (local_x, local_y), (segment_x, segment_y)
                
        except Exception as e:
            self.logger.error(f"Error calculating player positions: {e}")
            # Ultimate fallback
            local_x = float(player.x)
            local_y = float(player.y)
            return (local_x, local_y), (local_x, local_y), (0, 0)
    
    def _get_all_segments_data(self, gmap_manager, level_manager, current_segment: Tuple[int, int]) -> List[SegmentData]:
        """Get rendering data for all GMAP segments using server-provided data only
        
        Args:
            gmap_manager: GMAP manager instance
            level_manager: Level manager instance
            current_segment: Player's current segment coordinates
            
        Returns:
            List of SegmentData for all segments loaded from server
        """
        segments = []
        
        try:
            # Check if we have actual GMAP data from server
            if not gmap_manager.current_gmap:
                self.logger.warning("No GMAP data available - cannot generate segment data")
                # Debug: Check what level data is available
                if hasattr(level_manager, 'levels'):
                    available_levels = list(level_manager.levels.keys())
                    self.logger.info(f"📁 Available levels in cache: {available_levels}")
                    if available_levels:
                        # Create a single segment for the current level as fallback
                        current_level_name = available_levels[0]
                        level_data = level_manager.levels[current_level_name]
                        fallback_segment = SegmentData(
                            segment_coords=(0, 0),
                            world_position=(0.0, 0.0),
                            level_name=current_level_name,
                            level_data=level_data,
                            is_current_segment=True,
                            is_empty=False
                        )
                        self.logger.info(f"📍 Created fallback segment for {current_level_name}")
                        return [fallback_segment]
                return segments
            
            width = gmap_manager.current_gmap.width
            height = gmap_manager.current_gmap.height
            
            # Throttle building segment data debug message (major spam source)
            import time
            if not hasattr(self, '_last_building_log') or time.time() - self._last_building_log > 10.0:
                self.logger.debug(f"📊 Building segment data for {width}x{height} GMAP")
                self._last_building_log = time.time()
            
            # Debug: Log available level data (throttled - major spam source)
            if hasattr(level_manager, 'levels'):
                available_levels = list(level_manager.levels.keys())
                if not hasattr(self, '_last_available_log') or time.time() - self._last_available_log > 10.0:
                    self.logger.debug(f"📁 Available levels for mapping: {available_levels}")
                    self._last_available_log = time.time()
            
            # Create segment data for all segments from server data
            segments_created = 0
            segments_with_levels = 0
            
            for segment_y in range(height):
                for segment_x in range(width):
                    # Get level name for this segment from server data
                    level_name = gmap_manager.get_level_at_segment(segment_x, segment_y)
                    
                    # Calculate world position for this segment
                    world_x = segment_x * 64.0
                    world_y = segment_y * 64.0
                    
                    # Get level data if available from server cache
                    level_data = None
                    has_level_data = False
                    if level_name:
                        segments_with_levels += 1
                        if hasattr(level_manager, 'levels') and level_name in level_manager.levels:
                            level_data = level_manager.levels[level_name]
                            has_level_data = True
                            # Throttle found level data debug message (major spam source)
                            level_log_key = f"_last_found_log_{level_name}"
                            if not hasattr(self, level_log_key) or time.time() - getattr(self, level_log_key) > 10.0:
                                self.logger.debug(f"📁 Found level data for {level_name} at segment ({segment_x},{segment_y})")
                                setattr(self, level_log_key, time.time())
                        else:
                            # Debug: Check why level data wasn't found
                            # Only log missing levels occasionally to avoid spam
                            if not hasattr(self, '_missing_level_warnings'):
                                self._missing_level_warnings = {}
                            
                            import time
                            if (level_name not in self._missing_level_warnings or 
                                time.time() - self._missing_level_warnings[level_name] > 5.0):
                                if hasattr(level_manager, 'levels'):
                                    available = list(level_manager.levels.keys())
                                    self.logger.debug(f"❌ Level {level_name} not in cache. Available: {available}")
                                else:
                                    self.logger.debug(f"❌ Level manager has no 'levels' attribute")
                                self._missing_level_warnings[level_name] = time.time()
                    
                    # Create segment data
                    segment_data = SegmentData(
                        segment_coords=(segment_x, segment_y),
                        world_position=(world_x, world_y),
                        level_name=level_name,
                        level_data=level_data,
                        is_current_segment=(segment_x == current_segment[0] and segment_y == current_segment[1]),
                        is_empty=(level_name is None or level_name == '0')
                    )
                    
                    segments.append(segment_data)
                    segments_created += 1
            
            # Throttle segment generation messages
            import time
            current_time = time.time()
            if not hasattr(self, '_last_segment_log') or current_time - self._last_segment_log > 3.0:
                self.logger.info(f"📊 Generated {segments_created} segments ({segments_with_levels} with levels) from server GMAP data")
                self._last_segment_log = current_time
            
        except Exception as e:
            self.logger.error(f"Error getting segments data: {e}")
            import traceback
            traceback.print_exc()
        
        return segments
    
    def _validate_render_data(self, player_world_pos: Tuple[float, float], 
                             current_segment: Tuple[int, int], segments: List[SegmentData]) -> Dict[str, Any]:
        """Validate server-provided render data for consistency
        
        Args:
            player_world_pos: Player's world position
            current_segment: Player's current segment
            segments: All segment data
            
        Returns:
            Dictionary with validation results
        """
        validation = {
            'valid': True,
            'issues': [],
            'warnings': []
        }
        
        try:
            # Validate player position is within expected segment
            if player_world_pos[0] is not None and player_world_pos[1] is not None:
                calculated_segment_x = int(player_world_pos[0] // 64)
                calculated_segment_y = int(player_world_pos[1] // 64)
                
                if (calculated_segment_x != current_segment[0] or 
                    calculated_segment_y != current_segment[1]):
                    validation['warnings'].append(
                        f"Position mismatch: calculated segment ({calculated_segment_x},{calculated_segment_y}) "
                        f"vs current segment {current_segment}"
                    )
            
            # Validate current segment has data
            current_segment_found = False
            for segment in segments:
                if (segment.segment_coords == current_segment):
                    current_segment_found = True
                    if segment.is_empty:
                        validation['warnings'].append(
                            f"Player in empty segment {current_segment}"
                        )
                    break
            
            if not current_segment_found:
                validation['issues'].append(f"Current segment {current_segment} not found in segments data")
                validation['valid'] = False
            
            # Check for reasonable number of segments
            if len(segments) == 0:
                validation['issues'].append("No segments data available")
                validation['valid'] = False
            elif len(segments) > 100:  # Reasonable upper limit
                validation['warnings'].append(f"Large number of segments ({len(segments)}) - may impact performance")
            
        except Exception as e:
            validation['issues'].append(f"Validation error: {e}")
            validation['valid'] = False
        
        return validation
    
    def _create_fallback_render_data(self, gmap_manager, session_manager, player) -> GMAPRenderData:
        """Create basic render data when GMAP file isn't loaded yet but we're in GMAP mode
        
        Args:
            gmap_manager: GMAP manager instance
            session_manager: Session manager instance
            player: Player data
            
        Returns:
            Basic GMAPRenderData for temporary rendering
        """
        try:
            # Get basic position data
            local_x = float(player.x)
            local_y = float(player.y)
            
            # Try to get GMAP name from session manager
            gmap_name = getattr(session_manager, 'current_level_name', 'unknown.gmap')
            
            # Use server world coordinates if available
            if (hasattr(gmap_manager, 'current_world_x') and 
                gmap_manager.current_world_x is not None):
                world_x = gmap_manager.current_world_x
                world_y = gmap_manager.current_world_y
                segment_x = int(world_x // 64)
                segment_y = int(world_y // 64)
            else:
                # Fallback to local coordinates
                world_x = local_x
                world_y = local_y
                segment_x = 0
                segment_y = 0
            
            # Get the actual current level name (not the GMAP file name)
            current_level_name = None
            level_data = None
            
            # Try to get the resolved level name from session manager
            if hasattr(session_manager, 'get_effective_level_name'):
                effective_level = session_manager.get_effective_level_name()
                if effective_level and not effective_level.endswith('.gmap'):
                    current_level_name = effective_level
            
            # If no effective level, try the tracked concrete level
            if not current_level_name and hasattr(session_manager, 'current_level_name'):
                tracked_level = session_manager.current_level_name
                if tracked_level and not tracked_level.endswith('.gmap'):
                    current_level_name = tracked_level
            
            # Try to get level data from level manager
            if current_level_name:
                level_manager = getattr(self.client, 'level_manager', None)
                if level_manager and hasattr(level_manager, 'levels') and current_level_name in level_manager.levels:
                    level_data = level_manager.levels[current_level_name]
                    # Only log once per session to avoid spam
                    if not hasattr(self, '_level_data_found_logged'):
                        self.logger.info(f"📁 Found level data for current level: {current_level_name}")
                        self._level_data_found_logged = True
                else:
                    if not hasattr(self, '_level_cache_miss_logged'):
                        self.logger.warning(f"❌ Current level {current_level_name} not in cache")
                        self._level_cache_miss_logged = True
            else:
                if not hasattr(self, '_no_level_name_logged'):
                    self.logger.warning("❌ No current level name available for fallback segment")
                    self._no_level_name_logged = True
            
            # Create minimal segment data for current position
            current_segment_data = SegmentData(
                segment_coords=(segment_x, segment_y),
                world_position=(segment_x * 64.0, segment_y * 64.0),
                level_name=current_level_name,
                level_data=level_data,
                is_current_segment=True,
                is_empty=(current_level_name is None)
            )
            
            # Create basic render data
            fallback_data = GMAPRenderData(
                active=True,
                gmap_name=gmap_name,
                gmap_dimensions=(3, 3),  # Default 3x3 until real data loads
                player_world_position=(world_x, world_y),
                player_local_position=(local_x, local_y),
                camera_target=(world_x, world_y),
                current_segment=(segment_x, segment_y),
                segments=[current_segment_data],  # Just current segment for now
                server_data_quality={
                    'has_gmap_file': False,
                    'has_world_coordinates': gmap_manager.current_world_x is not None,
                    'has_segment_data': True,
                    'has_level_data': False,
                    'coordinate_source': 'server' if gmap_manager.current_world_x is not None else 'player'
                },
                debug_info={
                    'data_source': 'fallback_mode',
                    'loading_status': 'waiting_for_gmap_file',
                    'segments_with_data': 0,
                    'total_segments': 1,
                    'validation_status': {
                        'valid': True,
                        'issues': [],
                        'warnings': ['GMAP file not loaded yet - using fallback data']
                    }
                }
            )
            
            # Only log fallback creation once per 5 seconds to avoid spam
            import time
            current_time = time.time()
            if not hasattr(self, '_last_fallback_creation_log') or current_time - self._last_fallback_creation_log > 5.0:
                self.logger.info(f"📋 Created fallback GMAP render data for {gmap_name}")
                self._last_fallback_creation_log = current_time
            
            return fallback_data
            
        except Exception as e:
            self.logger.error(f"Error creating fallback render data: {e}")
            return None