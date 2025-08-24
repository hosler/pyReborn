"""
Physics System
==============

Client-side physics prediction and collision detection.
Works with PyReborn's server authoritative model.
"""

import logging
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass
from enum import Enum

from pyreborn import Client
from pyreborn.models import Level, Player
from .level_link_manager import LevelLinkManager
from .tile_types import TileType, get_tile_manager


logger = logging.getLogger(__name__)


class CollisionType(Enum):
    """Types of collision layers"""
    SOLID = 1      # Walls, blocking tiles
    WATER = 2      # Water tiles
    CHAIR = 3      # Sittable objects
    BED = 4        # Bed objects
    SWAMP = 5      # Slow movement
    LAVA = 6       # Damage tiles
    JUMP = 7       # Jump tiles
    LINK = 8       # Level links


@dataclass
class AABB:
    """Axis-aligned bounding box"""
    x: float
    y: float
    width: float
    height: float
    
    def intersects(self, other: 'AABB') -> bool:
        """Check if this AABB intersects another"""
        return (self.x < other.x + other.width and
                self.x + self.width > other.x and
                self.y < other.y + other.height and
                self.y + self.height > other.y)
    
    def contains_point(self, x: float, y: float) -> bool:
        """Check if point is inside AABB"""
        return (self.x <= x <= self.x + self.width and
                self.y <= y <= self.y + self.height)


@dataclass
class PhysicsBody:
    """Physics body for an entity"""
    entity_id: int
    x: float
    y: float
    width: float = 1.0  # Full tile width for player
    height: float = 0.5  # Half tile height (feet/shadow area)
    velocity_x: float = 0.0
    velocity_y: float = 0.0
    on_ground: bool = True
    collision_mask: int = CollisionType.SOLID.value
    # Collision box offset from sprite position
    # GANI sprites have their origin at the character's feet
    # The visible sprite appears above and to the right of this origin
    # We need to position the collision box at the visible character's feet
    collision_offset_x: float = 1.0  # Move collision box 1.0 tiles right (was 1.5, subtract 0.5)
    collision_offset_y: float = 2.0  # Move collision box 2 tiles down (was -1.0, add 3.0)
    
    # Collision tracking for link detection
    last_collision_x: Optional[float] = None  # Last collision point X
    last_collision_y: Optional[float] = None  # Last collision point Y
    blocked_direction: Optional[int] = None   # Direction we're blocked (0=up, 1=left, 2=down, 3=right)
    blocked_tile_x: Optional[int] = None      # X coordinate of blocking tile
    blocked_tile_y: Optional[int] = None      # Y coordinate of blocking tile
    
    def get_aabb(self) -> AABB:
        """Get axis-aligned bounding box with offsets applied"""
        # Apply offsets to position for collision box
        collision_x = self.x + self.collision_offset_x
        collision_y = self.y + self.collision_offset_y
        return AABB(collision_x, collision_y, self.width, self.height)


class PhysicsSystem:
    """Client-side physics prediction"""
    
    def __init__(self, client: Client, packet_api=None):
        """Initialize physics system
        
        Args:
            client: PyReborn client for level data
            packet_api: API for sending packets (for level links)
        """
        self.client = client
        self.packet_api = packet_api
        
        # Physics bodies
        self.bodies: Dict[int, PhysicsBody] = {}
        
        # Collision cache
        self.collision_cache: Dict[Tuple[int, int], int] = {}
        self.cache_level: Optional[str] = None
        
        # GMAP segment tracking - Initialize to None to properly detect first segment
        self.current_segment_x: Optional[int] = None
        self.current_segment_y: Optional[int] = None
        self.current_segment_level: Optional[Level] = None
        
        # Physics constants
        self.gravity = 0.0  # No gravity in 2D Reborn
        self.friction = 0.0  # No friction for instant stop (no ice-skating)
        self.player_speed = 12.0  # Tiles per second (fast movement)
        
        # Level link manager
        self.level_link_manager = None
        if packet_api:
            self.level_link_manager = LevelLinkManager(client, packet_api)
            # Give link manager access to physics system for collision box parameters
            self.level_link_manager.physics_system = self
        
        # Tile type manager
        self.tile_manager = get_tile_manager()
        
        logger.info("Physics system initialized")
    
    def move(self, entity_id: int, dx: float, dy: float, dt: float) -> Tuple[float, float]:
        """Move entity with physics simulation
        
        Args:
            entity_id: Entity ID to move
            dx: Desired X movement (-1, 0, 1)
            dy: Desired Y movement (-1, 0, 1)
            dt: Delta time in seconds
            
        Returns:
            Final (x, y) position after movement and collision
        """
        if entity_id not in self.bodies:
            logger.warning(f"No physics body for entity {entity_id}")
            return (0, 0)
        
        body = self.bodies[entity_id]
        
        # Calculate velocity based on desired movement
        body.velocity_x = dx * self.player_speed
        body.velocity_y = dy * self.player_speed
        
        # Calculate new position
        new_x = body.x + body.velocity_x * dt
        new_y = body.y + body.velocity_y * dt
        
        # Check collision and move
        final_x, final_y, collision_info = self._move_and_collide(body, new_x, new_y)
        
        # Update position
        body.x = final_x
        body.y = final_y
        
        # Stop velocity if no input (instant stop)
        if dx == 0:
            body.velocity_x = 0
        if dy == 0:
            body.velocity_y = 0
        
        return (final_x, final_y)
    
    def add_body(self, entity_id: int, x: float, y: float, 
                  width: float = None, height: float = None) -> PhysicsBody:
        """Add physics body for entity
        
        Args:
            entity_id: Entity ID
            x: X position in tiles
            y: Y position in tiles
            width: Width in tiles (default from PhysicsBody: 1.0)
            height: Height in tiles (default from PhysicsBody: 0.5)
            
        Returns:
            Created physics body
        """
        # Create body with defaults from PhysicsBody dataclass if not specified
        if width is None and height is None:
            body = PhysicsBody(
                entity_id=entity_id,
                x=x,
                y=y
                # Will use dataclass defaults: width=1.0, height=0.5
            )
        else:
            body = PhysicsBody(
                entity_id=entity_id,
                x=x,
                y=y,
                width=width if width is not None else 1.0,
                height=height if height is not None else 0.5
            )
        
        self.bodies[entity_id] = body
        logger.info(f"[PHYSICS] Added physics body for entity {entity_id} at ({x:.1f}, {y:.1f})")
        logger.info(f"[PHYSICS] Current bodies: {list(self.bodies.keys())}")
        
        return body
    
    def remove_body(self, entity_id: int):
        """Remove physics body"""
        if entity_id in self.bodies:
            del self.bodies[entity_id]
            logger.info(f"[PHYSICS] Removed physics body for entity {entity_id}")
            logger.info(f"[PHYSICS] Remaining bodies: {list(self.bodies.keys())}")
    
    def update(self, dt: float):
        """Update physics simulation
        
        Args:
            dt: Delta time in seconds
        """
        gmap_manager = self.client.gmap_manager if hasattr(self.client, 'gmap_manager') else None
        player = self.client.session_manager.get_player() if hasattr(self.client, 'session_manager') and self.client.session_manager else None
        
        if gmap_manager and gmap_manager.is_active() and player:
            # GMAP mode - track segment changes based on physics body world position
            # Get physics body position (which is in world coordinates now)
            if -1 in self.bodies:
                body = self.bodies[-1]
                # Calculate segment from world coordinates
                segment_x = int(body.x // 64)
                segment_y = int(body.y // 64)
                
                # Debug: Log what we're tracking
                logger.debug(f"Physics: Body at world ({body.x:.1f},{body.y:.1f}), segment ({segment_x},{segment_y}), tracked ({self.current_segment_x},{self.current_segment_y})")
            else:
                # Fallback to player segment if no physics body
                segment_x = getattr(player, 'gmaplevelx', 0) or 0
                segment_y = getattr(player, 'gmaplevely', 0) or 0
                logger.debug(f"Physics: No body, using player segment ({segment_x},{segment_y})")
            
            # Check if segment changed
            if segment_x != self.current_segment_x or segment_y != self.current_segment_y:
                logger.info(f"Physics: Segment change detected - from ({self.current_segment_x}, {self.current_segment_y}) to ({segment_x}, {segment_y})")
                self.current_segment_x = segment_x
                self.current_segment_y = segment_y
                
                # Get the level for this segment
                level_name = gmap_manager.get_level_at_position(segment_x, segment_y)
                if level_name and hasattr(self.client, 'level_manager') and self.client.level_manager:
                    self.current_segment_level = self.client.level_manager.get_level(level_name)
                    if self.current_segment_level:
                        # Check if level has tile data
                        tile_count = len(self.current_segment_level.board_tiles) if hasattr(self.current_segment_level, 'board_tiles') else 0
                        non_zero = sum(1 for t in self.current_segment_level.board_tiles if t > 0) if tile_count > 0 else 0
                        logger.info(f"Physics: GMAP segment changed to ({segment_x}, {segment_y}) - level {level_name}")
                        logger.info(f"Physics: Level {level_name} has {tile_count} tiles, {non_zero} non-zero")
                        
                        # CRITICAL FIX: Rebuild collision cache for new segment
                        # This ensures collision detection works in all GMAP segments
                        logger.info(f"Physics: Rebuilding collision cache for new segment level {level_name}")
                        self._rebuild_collision_cache(self.current_segment_level)
                        
                        # Test getting a few tiles
                        if tile_count > 0:
                            test_tiles = []
                            for tx, ty in [(10, 10), (30, 30), (50, 50)]:
                                tile = self.current_segment_level.get_tile(tx, ty, 0)
                                test_tiles.append(f"({tx},{ty})={tile}")
                            logger.info(f"Physics: Sample tiles from {level_name}: {', '.join(test_tiles)}")
                    else:
                        logger.warning(f"Physics: Level {level_name} not cached for segment ({segment_x}, {segment_y})")
                else:
                    logger.warning(f"Physics: No level at GMAP segment ({segment_x}, {segment_y})")
        else:
            # Non-GMAP mode - use collision cache
            if hasattr(self.client, 'level_manager') and self.client.level_manager:
                current_level = self.client.level_manager.get_current_level()
                if current_level and current_level.name != self.cache_level:
                    logger.info(f"Physics: Level changed from {self.cache_level} to {current_level.name}")
                    self._rebuild_collision_cache(current_level)
        
        # Update each body
        if len(self.bodies) == 0:
            logger.warning(f"[PHYSICS] No bodies to update!")
        else:
            logger.debug(f"[PHYSICS-DEBUG] Updating {len(self.bodies)} bodies: {list(self.bodies.keys())}")
        
        for body in self.bodies.values():
            self._update_body(body, dt)
    
    def _update_body(self, body: PhysicsBody, dt: float):
        """Update single physics body"""
        logger.debug(f"[PHYSICS-DEBUG] _update_body called for entity {body.entity_id}, velocity=({body.velocity_x:.2f}, {body.velocity_y:.2f})")
        # Track if we're blocked this frame
        was_blocked = False
        
        # Apply velocity
        if abs(body.velocity_x) > 0.01 or abs(body.velocity_y) > 0.01:
            # Calculate new position
            new_x = body.x + body.velocity_x * dt
            new_y = body.y + body.velocity_y * dt
            
            # Check collision and move
            final_x, final_y, collision_info = self._move_and_collide(body, new_x, new_y)
            
            # DEBUG: Log what _move_and_collide returned
            logger.debug(f"[PHYSICS-DEBUG] _move_and_collide returned: collision_info={collision_info is not None}, blocked={collision_info.get('blocked') if collision_info else None}")
            
            # Update position
            old_x, old_y = body.x, body.y
            body.x = final_x
            body.y = final_y
            
            # Check if we were blocked
            if collision_info:
                logger.debug(f"[PHYSICS] Collision info returned: {collision_info}")
                logger.debug(f"[PHYSICS-DEBUG] Checking blocked condition: collision_info exists, blocked={collision_info.get('blocked')}")
            if collision_info and collision_info.get('blocked'):
                was_blocked = True
                logger.debug(f"[PHYSICS-DEBUG] Setting was_blocked=True")
                # Update collision tracking
                body.last_collision_x = collision_info.get('collision_x')
                body.last_collision_y = collision_info.get('collision_y')
                body.blocked_direction = collision_info.get('direction')
                body.blocked_tile_x = collision_info.get('blocked_tile_x')
                body.blocked_tile_y = collision_info.get('blocked_tile_y')
                
                # Now handle velocity based on direction blocked
                if body.blocked_direction in [1, 3]:  # Left or right
                    body.velocity_x = 0.0
                if body.blocked_direction in [0, 2]:  # Up or down
                    body.velocity_y = 0.0
                
                logger.debug(f"[PHYSICS] 🚫 Blocked at ({body.last_collision_x:.1f}, {body.last_collision_y:.1f}) direction {body.blocked_direction}, tile ({body.blocked_tile_x}, {body.blocked_tile_y})")
            else:
                # We moved successfully without collision - clear any previous blocked state
                if body.blocked_direction is not None:
                    logger.info(f"[PHYSICS] Player moved away from wall, clearing blocked state")
                body.blocked_direction = None
                body.blocked_tile_x = None
                body.blocked_tile_y = None
                body.last_collision_x = None
                body.last_collision_y = None
                if collision_info:
                    logger.warning(f"[PHYSICS] Collision info exists but blocked not set: {collision_info}")
            
            # No friction - movement stops instantly when input stops
            # This prevents ice-skating effect
        else:
            # Not moving - don't clear collision info yet, player might still be against wall
            # We'll clear it when player moves away from the wall
            pass
        
        # Check for level links if this is the player body (entity_id == -1 for local player)
        # This runs even when stationary to detect standing on links
        logger.debug(f"[PHYSICS-DEBUG] Checking link manager for entity {body.entity_id}, was_blocked={was_blocked}")
        if body.entity_id == -1:
            logger.debug(f"[PHYSICS-DEBUG] Player body detected, link_manager exists: {self.level_link_manager is not None}")
            if self.level_link_manager:
                # Pass collision info to link manager
                # Check both current frame collision (was_blocked) and persistent blocked state
                collision_point = None
                blocking_tile = None
                
                # Use collision info if we were blocked this frame OR if we still have persistent blocked state
                condition1 = was_blocked and body.last_collision_x is not None
                condition2 = body.blocked_direction is not None and body.last_collision_x is not None
                logger.debug(f"[PHYSICS-DEBUG] Link conditions: was_blocked={was_blocked}, has_collision={body.last_collision_x is not None}, has_direction={body.blocked_direction is not None}")
                
                if condition1 or condition2:
                    collision_point = (body.last_collision_x, body.last_collision_y)
                    if body.blocked_tile_x is not None:
                        blocking_tile = (body.blocked_tile_x, body.blocked_tile_y)
                    logger.debug(f"[PHYSICS] 📍 Passing collision point to link manager: ({collision_point[0]:.1f}, {collision_point[1]:.1f}), blocking tile: {blocking_tile}")
                
                transition_triggered = self.level_link_manager.update(
                    body.x, body.y, 
                    collision_point=collision_point,
                    blocked_direction=body.blocked_direction,
                    blocking_tile=blocking_tile
                )
                if transition_triggered:
                    logger.info(f"[PHYSICS] Level transition triggered!")
                    # Stop movement on level transition
                    body.velocity_x = 0.0
                    body.velocity_y = 0.0
                    return
            else:
                logger.warning(f"[PHYSICS] No level_link_manager available!")
    
    def _move_and_collide(self, body: PhysicsBody, new_x: float, new_y: float) -> Tuple[float, float, Optional[dict]]:
        """Move body and handle collisions
        
        Returns:
            Final position after collision resolution and collision info
        """
        logger.debug(f"[MOVE_COLLIDE] Attempting to move from ({body.x:.2f}, {body.y:.2f}) to ({new_x:.2f}, {new_y:.2f})")
        
        collision_info = {}
        blocked = False
        
        # Create a temporary body at new position to test collision
        # We need to test with the offsets applied
        
        # Try moving on X axis first
        test_body = PhysicsBody(
            entity_id=body.entity_id,
            x=new_x, y=body.y,
            width=body.width, height=body.height,
            collision_offset_x=body.collision_offset_x,
            collision_offset_y=body.collision_offset_y
        )
        test_aabb = test_body.get_aabb()
        x_collision, blocking_tile = self._check_tile_collision(test_aabb, body.collision_mask)
        if not x_collision:
            final_x = new_x
        else:
            # Collision on X axis - record collision point and blocking tile
            logger.debug(f"[PHYSICS] X-axis collision detected at ({new_x:.2f}, {body.y:.2f})")
            final_x = body.x
            # DON'T modify velocity here - let _update_body handle it
            blocked = True
            
            # Store blocking tile coordinates in collision_info only
            if blocking_tile:
                collision_info['blocked_tile_x'] = blocking_tile[0]
                collision_info['blocked_tile_y'] = blocking_tile[1]
            
            # Calculate collision point (edge of collision box that hit the wall)
            collision_aabb = body.get_aabb()
            if new_x > body.x:  # Moving right
                collision_info['collision_x'] = collision_aabb.x + collision_aabb.width
                collision_info['direction'] = 3  # Right
            else:  # Moving left
                collision_info['collision_x'] = collision_aabb.x
                collision_info['direction'] = 1  # Left
            collision_info['collision_y'] = collision_aabb.y + collision_aabb.height / 2
            logger.debug(f"[PHYSICS] Collision point calculated: ({collision_info['collision_x']:.1f}, {collision_info['collision_y']:.1f}), blocking tile: {blocking_tile}")
        
        # Then try Y axis
        test_body.x = final_x
        test_body.y = new_y
        test_aabb = test_body.get_aabb()
        y_collision, blocking_tile = self._check_tile_collision(test_aabb, body.collision_mask)
        if not y_collision:
            final_y = new_y
        else:
            # Collision on Y axis - record collision point and blocking tile
            logger.debug(f"[PHYSICS] Y-axis collision detected at ({final_x:.2f}, {new_y:.2f})")
            final_y = body.y
            # DON'T modify velocity here - let _update_body handle it
            blocked = True
            
            # Store blocking tile coordinates in collision_info if not already set
            if blocking_tile and 'blocked_tile_x' not in collision_info:
                collision_info['blocked_tile_x'] = blocking_tile[0]
                collision_info['blocked_tile_y'] = blocking_tile[1]
            
            # Calculate collision point (edge of collision box that hit the wall)
            collision_aabb = body.get_aabb()
            if new_y > body.y:  # Moving down
                collision_info['collision_y'] = collision_aabb.y + collision_aabb.height
                collision_info['direction'] = 2  # Down
            else:  # Moving up
                collision_info['collision_y'] = collision_aabb.y
                collision_info['direction'] = 0  # Up
            
            # If not already set from X collision
            if 'collision_x' not in collision_info:
                collision_info['collision_x'] = collision_aabb.x + collision_aabb.width / 2
            
            logger.debug(f"[PHYSICS] Collision point calculated: ({collision_info.get('collision_x', 0):.1f}, {collision_info['collision_y']:.1f}), blocking tile: {blocking_tile}")
        
        # Debug log if any collision occurred
        if x_collision or y_collision:
            logger.debug(f"Collision: tried ({new_x:.2f}, {new_y:.2f}) -> final ({final_x:.2f}, {final_y:.2f})")
        
        if blocked:
            collision_info['blocked'] = True
            logger.debug(f"[PHYSICS] Returning collision_info with blocked=True: {collision_info}")
            return final_x, final_y, collision_info
        else:
            return final_x, final_y, None
    
    def _check_tile_collision(self, aabb: AABB, collision_mask: int) -> Tuple[bool, Optional[Tuple[int, int]]]:
        """Check if AABB collides with any solid tiles
        
        Args:
            aabb: Bounding box to test (in world coordinates for GMAP mode)
            collision_mask: Types of tiles to collide with
            
        Returns:
            (collision_detected, (tile_x, tile_y)) - tile coordinates if collision detected
        """
        logger.debug(f"[COLLISION_CHECK] Checking AABB: x={aabb.x:.2f}, y={aabb.y:.2f}, w={aabb.width:.2f}, h={aabb.height:.2f}")
        
        # No special boundary handling needed!
        # The _get_tile_collision_type function already handles cross-segment collision detection correctly
        # It automatically determines which segment each tile is in and checks the appropriate level
        
        # Get tile bounds - AABB is in world coordinates for GMAP mode
        min_x = int(aabb.x)
        max_x = int(aabb.x + aabb.width) + 1
        min_y = int(aabb.y)
        max_y = int(aabb.y + aabb.height) + 1
        
        logger.debug(f"[COLLISION_CHECK] Tile range: x=[{min_x}, {max_x}), y=[{min_y}, {max_y})")
        
        # Check each tile - pass WORLD coordinates to _get_tile_collision_type
        tiles_checked = 0
        for y in range(min_y, max_y):
            for x in range(min_x, max_x):
                tiles_checked += 1
                # Pass world coordinates (as integers) to _get_tile_collision_type
                tile_type = self._get_tile_collision_type(x, y)
                if tiles_checked <= 3:  # Log first few tiles for debugging
                    logger.debug(f"[COLLISION_CHECK] Tile at world ({x}, {y}) -> type={tile_type}")
                if tile_type & collision_mask:
                    # Create tile AABB (in world coordinates)
                    tile_aabb = AABB(x, y, 1, 1)
                    if aabb.intersects(tile_aabb):
                        # Debug log what tile blocked movement
                        logger.debug(f"[COLLISION_CHECK] *** COLLISION *** at world ({x}, {y}) - type: {tile_type}")
                        return True, (x, y)
        
        logger.debug(f"[COLLISION_CHECK] Checked {tiles_checked} tiles, no collision")
        
        return False, None
    
    def _get_tile_collision_type(self, x: int, y: int) -> int:
        """Get collision type for tile at position
        
        In GMAP mode, x and y are WORLD coordinates.
        We need to determine which segment the tile is in and check that level.
        
        Returns:
            Collision type flags
        """
        # Check if we're in GMAP mode
        gmap_manager = self.client.gmap_manager if hasattr(self.client, 'gmap_manager') else None
        
        if gmap_manager and gmap_manager.is_active():
            logger.debug(f"[GET_TILE_TYPE] GMAP mode active, checking tile at world ({x}, {y})")
            # GMAP mode - determine segment from world coordinates
            segment_x = int(x // 64)
            segment_y = int(y // 64)
            
            # Calculate local coordinates within the segment
            local_x = x - (segment_x * 64)
            local_y = y - (segment_y * 64)
            
            # Get the level for this segment
            level_name = gmap_manager.get_level_at_position(segment_x, segment_y)
            logger.debug(f"[GET_TILE_TYPE] Segment ({segment_x},{segment_y}), level: {level_name}, local tile: ({local_x},{local_y})")
            
            if level_name and hasattr(self.client, 'level_manager') and self.client.level_manager:
                # Get the level from cache
                level = self.client.level_manager.get_level(level_name)
                if level:
                    # Check tile in level
                    logger.debug(f"[GET_TILE_TYPE] Found level {level_name}, checking tile at local ({local_x},{local_y})")
                    return self._calculate_tile_collision_type(level, local_x, local_y)
                else:
                    logger.warning(f"[GET_TILE_TYPE] Level {level_name} not in cache!")
                    return 0
            else:
                # No level in that segment - treat as solid
                logger.debug(f"[GET_TILE_TYPE] No level at segment ({segment_x},{segment_y}), returning SOLID")
                return CollisionType.SOLID.value
        else:
            # Non-GMAP mode - use collision cache if available
            if not hasattr(self.client, 'level_manager') or not self.client.level_manager:
                return 0
            level = self.client.level_manager.get_current_level()
            if not level:
                return 0
            
            # Check bounds
            if x < 0 or x >= level.width or y < 0 or y >= level.height:
                return CollisionType.SOLID.value
            
            # Use collision cache if it's for the current level
            if self.cache_level == level.name:
                cache_key = (x, y)
                if cache_key in self.collision_cache:
                    return self.collision_cache[cache_key]
            
            # Fallback to calculating if not in cache
            return self._calculate_tile_collision_type(level, x, y)
    
    def _calculate_tile_collision_type(self, level: Level, x: int, y: int) -> int:
        """Calculate collision type for a tile in a specific level
        
        Args:
            level: The level to check
            x: X coordinate in tiles
            y: Y coordinate in tiles
            
        Returns:
            Collision type flags
        """
        logger.debug(f"[CALC_COLLISION] Calculating for tile ({x},{y}) in level {level.name}")
        
        # Bounds check
        if x < 0 or x >= level.width or y < 0 or y >= level.height:
            logger.debug(f"[CALC_COLLISION] Tile ({x},{y}) out of bounds for {level.name} ({level.width}x{level.height})")
            return CollisionType.SOLID.value
        
        # Check if level has tile data
        if not hasattr(level, 'board_tiles') or not level.board_tiles:
            logger.warning(f"[CALC_COLLISION] Level {level.name} has no board_tiles!")
            return 0
        
        # Get tile index from the specific level
        tile_index = level.get_tile(x, y, 0)
        if x == 30 and y == 30:  # Debug specific tile
            logger.info(f"[CALC_COLLISION] DEBUG: Tile at (30,30) in {level.name}: tile_index={tile_index}")
        else:
            logger.debug(f"[CALC_COLLISION] Tile at ({x},{y}) in {level.name}: tile_index={tile_index}")
        
        # Use tile type manager to determine collision type
        collision_type = 0
        
        # Check if tile is blocking
        if self.tile_manager.is_blocking(tile_index):
            collision_type = CollisionType.SOLID.value
            logger.debug(f"[CALC_COLLISION] *** BLOCKING *** tile {tile_index} at ({x},{y}) in {level.name}")
        # Check if tile is water
        elif self.tile_manager.is_water(tile_index):
            collision_type = CollisionType.WATER.value
        # Check if tile is sittable
        elif self.tile_manager.is_sittable(tile_index):
            collision_type = CollisionType.CHAIR.value
        # Check if tile is lava (damaging)
        elif self.tile_manager.get_tile_type(tile_index) == TileType.LAVA:
            collision_type = CollisionType.LAVA.value
        # Check if tile is swamp (slowing)
        elif self.tile_manager.get_tile_type(tile_index) in {TileType.SWAMP, TileType.LAVA_SWAMP}:
            collision_type = CollisionType.SWAMP.value
        # Check if tile is jump stone
        elif self.tile_manager.is_jumpable(tile_index):
            collision_type = CollisionType.JUMP.value
        
        logger.debug(f"[CALC_COLLISION] Final collision type for tile {tile_index}: {collision_type}")
        return collision_type
    
    
    def _rebuild_collision_cache(self, level: Level):
        """Rebuild collision cache for new level"""
        logger.info(f"Rebuilding collision cache for level {level.name} ({level.width}x{level.height})")
        
        # Clear the old cache completely
        self.collision_cache.clear()
        self.cache_level = level.name
        
        # Pre-cache tiles for the new level
        # This ensures we're using the correct level's tile data
        cached_count = 0
        for y in range(level.height):
            for x in range(level.width):
                # Force fresh calculation for this level
                cache_key = (x, y)
                # Don't use cached value, calculate fresh
                collision_type = self._calculate_tile_collision_type(level, x, y)
                self.collision_cache[cache_key] = collision_type
                if collision_type != 0:
                    cached_count += 1
        
        logger.info(f"Cached {cached_count} blocking tiles for {level.name}")
        
        # Debug: Show a sample of blocking tiles
        if cached_count > 0:
            sample_blocking = []
            count = 0
            for (x, y), collision_type in self.collision_cache.items():
                if collision_type == CollisionType.SOLID.value and count < 5:
                    sample_blocking.append(f"({x},{y})")
                    count += 1
            logger.info(f"Sample blocking tiles: {', '.join(sample_blocking)}")
    
    def set_velocity(self, entity_id: int, vx: float, vy: float):
        """Set entity velocity
        
        Args:
            entity_id: Entity to update
            vx: X velocity in tiles/second
            vy: Y velocity in tiles/second
        """
        if entity_id in self.bodies:
            self.bodies[entity_id].velocity_x = vx
            self.bodies[entity_id].velocity_y = vy
    
    def apply_impulse(self, entity_id: int, ix: float, iy: float):
        """Apply impulse to entity
        
        Args:
            entity_id: Entity to update
            ix: X impulse
            iy: Y impulse
        """
        if entity_id in self.bodies:
            self.bodies[entity_id].velocity_x += ix
            self.bodies[entity_id].velocity_y += iy
    
    def get_position(self, entity_id: int) -> Optional[Tuple[float, float]]:
        """Get entity position
        
        Returns:
            (x, y) tuple or None
        """
        if entity_id in self.bodies:
            body = self.bodies[entity_id]
            return (body.x, body.y)
        return None
    
    def set_position(self, entity_id: int, x: float, y: float):
        """Set entity position (teleport)"""
        if entity_id in self.bodies:
            self.bodies[entity_id].x = x
            self.bodies[entity_id].y = y
            # Clear velocity on teleport
            self.bodies[entity_id].velocity_x = 0.0
            self.bodies[entity_id].velocity_y = 0.0
    
    def raycast(self, start_x: float, start_y: float, 
                end_x: float, end_y: float,
                collision_mask: int = CollisionType.SOLID.value) -> Optional[Tuple[float, float]]:
        """Cast ray and find first collision
        
        Args:
            start_x, start_y: Ray start position
            end_x, end_y: Ray end position
            collision_mask: Types to collide with
            
        Returns:
            Collision point or None
        """
        # Simple DDA line algorithm
        dx = end_x - start_x
        dy = end_y - start_y
        distance = max(abs(dx), abs(dy))
        
        if distance < 0.01:
            return None
        
        # Step size
        step_x = dx / distance
        step_y = dy / distance
        
        # Walk along ray
        x = start_x
        y = start_y
        
        for i in range(int(distance * 16)):  # 16 steps per tile
            # Check collision at current position
            tile_x = int(x)
            tile_y = int(y)
            
            if self._get_tile_collision_type(tile_x, tile_y) & collision_mask:
                return (x, y)
            
            # Step
            x += step_x / 16
            y += step_y / 16
        
        return None
    
    def get_nearby_bodies(self, x: float, y: float, radius: float) -> List[PhysicsBody]:
        """Get all bodies within radius of position
        
        Args:
            x, y: Center position
            radius: Search radius in tiles
            
        Returns:
            List of nearby bodies
        """
        nearby = []
        radius_sq = radius * radius
        
        for body in self.bodies.values():
            dx = body.x - x
            dy = body.y - y
            dist_sq = dx * dx + dy * dy
            
            if dist_sq <= radius_sq:
                nearby.append(body)
        
        return nearby
    
    def get_debug_collision_boxes(self) -> List[AABB]:
        """Get all collision boxes for debug rendering
        
        Returns:
            List of AABBs for all physics bodies
        """
        boxes = []
        for body in self.bodies.values():
            boxes.append(body.get_aabb())
        return boxes