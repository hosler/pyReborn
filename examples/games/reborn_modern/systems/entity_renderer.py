"""
Entity Renderer
===============

Handles rendering of players, NPCs, and other entities.
"""

import pygame
import logging
from typing import Optional, Dict, List, Tuple

from pyreborn import Client
from pyreborn.models import Player
from .camera import Camera
from .gani_animation_system import GANIAnimationSystem


logger = logging.getLogger(__name__)


class EntityRenderer:
    """Renders players, NPCs, and other entities"""
    
    def __init__(self, screen: pygame.Surface, assets_path: Optional[str] = None):
        """Initialize entity renderer
        
        Args:
            screen: Pygame screen surface
            assets_path: Optional path to game assets for GANI animations
        """
        logger.debug("EntityRenderer initialized")
        self.screen = screen
        self.tile_size = 16  # Standard tile size in pixels
        
        # Entity colors (fallback when no GANI)
        self.LOCAL_PLAYER_COLOR = (0, 255, 0)      # Green
        self.OTHER_PLAYER_COLOR = (100, 150, 255)  # Light blue
        self.NPC_COLOR = (255, 200, 100)          # Orange
        self.PROJECTILE_COLOR = (255, 100, 100)    # Red
        self.COLLISION_BOX_COLOR = (255, 0, 255)   # Magenta for collision boxes
        
        # Fonts for names
        self.name_font = pygame.font.Font(None, 14)
        self.name_shadow_offset = 1
        
        # Debug settings
        self.show_hitboxes = False
        self.show_coordinates = False
        self.show_collision_boxes = False
        
        # Physics system reference (set externally)
        self.physics_system = None
        
        # Performance
        self.entities_rendered = 0
        self.batch_render = True  # Enable batch rendering
        
        # GANI animation system
        self.gani_system = None
        if assets_path:
            try:
                self.gani_system = GANIAnimationSystem(assets_path)
                logger.info("GANI animation system initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize GANI animations: {e}")
        
        # Track entity animations
        self.entity_animations: Dict[int, str] = {}  # entity_id -> animation_name
        
    def set_physics_system(self, physics_system):
        """Set the physics system for debug rendering
        
        Args:
            physics_system: Physics system instance
        """
        self.physics_system = physics_system
        logger.info("Physics system connected to entity renderer")
    
    def render(self, client: Client, camera: Camera):
        """Render all entities
        
        Args:
            client: PyReborn client instance
            camera: Camera for viewport transformation
        """
        if not client:
            return
            
        self.entities_rendered = 0
        
        # Update GANI animations if available
        if self.gani_system:
            self._update_entity_animations(client)
        
        # Get visible bounds for culling
        left, top, right, bottom = camera.get_visible_bounds()
        
        # Render other players first
        self._render_players(client, camera, left, top, right, bottom)
        
        # Render NPCs
        self._render_npcs(client, camera, left, top, right, bottom)
        
        # Render projectiles
        self._render_projectiles(client, camera, left, top, right, bottom)
        
        # Render local player on top and get their position for collision box
        player_world_x, player_world_y = self._render_local_player(client, camera)
        
        # Render collision boxes if debug mode is enabled
        if self.show_collision_boxes and player_world_x is not None:
            self._render_collision_boxes(client, camera, player_world_x, player_world_y)
        
    def _render_players(self, client: Client, camera: Camera,
                       left: float, top: float, right: float, bottom: float):
        """Render other players
        
        Args:
            client: PyReborn client
            camera: Camera instance
            left, top, right, bottom: Visible bounds in world coordinates
        """
        # Get session manager
        session_manager = client.get_manager('session')
        if not session_manager:
            return
            
        # Get all players
        players = session_manager.get_all_players()
        if not players:
            return
            
        # Get local player ID to skip
        local_player = session_manager.get_player()
        local_player_id = local_player.id if local_player else None
        
        # Render each player
        for player_id, player in players.items():
            # Skip local player
            if player_id == local_player_id:
                continue
                
            # Get player position
            player_x, player_y = self._get_entity_position(player, client)
            
            # Cull if outside view
            if not self._is_in_view(player_x, player_y, left, top, right, bottom):
                continue
                
            # Render player
            self._render_player_entity(player, player_x, player_y, camera, False)
            self.entities_rendered += 1
            
    def _render_npcs(self, client: Client, camera: Camera,
                    left: float, top: float, right: float, bottom: float):
        """Render NPCs
        
        Args:
            client: PyReborn client
            camera: Camera instance
            left, top, right, bottom: Visible bounds
        """
        # Get NPC manager
        npc_manager = client.get_manager('npc')
        if not npc_manager or not hasattr(npc_manager, 'get_visible_npcs'):
            return
            
        # Render each NPC
        for npc in npc_manager.get_visible_npcs():
            # Cull if outside view
            if not self._is_in_view(npc.x, npc.y, left, top, right, bottom):
                continue
                
            # Render NPC
            self._render_npc_entity(npc, camera)
            self.entities_rendered += 1
            
    def _render_projectiles(self, client: Client, camera: Camera,
                           left: float, top: float, right: float, bottom: float):
        """Render projectiles (arrows, bombs, etc.)
        
        Args:
            client: PyReborn client
            camera: Camera instance
            left, top, right, bottom: Visible bounds
        """
        # Get combat manager
        combat_manager = client.get_manager('combat')
        if not combat_manager or not hasattr(combat_manager, 'get_active_projectiles'):
            return
            
        # Render each projectile
        for projectile in combat_manager.get_active_projectiles():
            # Cull if outside view
            if not self._is_in_view(projectile.x, projectile.y, left, top, right, bottom):
                continue
                
            # Convert to screen position
            screen_x, screen_y = camera.world_to_screen(projectile.x, projectile.y)
            
            # Draw projectile
            size = max(2, int(4 * camera.zoom))
            pygame.draw.circle(self.screen, self.PROJECTILE_COLOR,
                             (int(screen_x), int(screen_y)), size)
            self.entities_rendered += 1
            
    def _render_local_player(self, client: Client, camera: Camera):
        """Render the local player
        
        Args:
            client: PyReborn client
            camera: Camera instance
            
        Returns:
            (player_x, player_y) tuple of world position, or (None, None) if no player
        """
        # Get local player
        session_manager = client.get_manager('session')
        if not session_manager:
            return None, None
            
        player = session_manager.get_player()
        if not player:
            return None, None
            
        # Get player position
        # Special handling: If we're using a camera that's following local coords,
        # use local coords for the player too
        if hasattr(camera, '_following_local_coords') and camera._following_local_coords:
            player_x = player.x
            player_y = player.y
        else:
            player_x, player_y = self._get_entity_position(player, client)
        
        # Render player
        self._render_player_entity(player, player_x, player_y, camera, True)
        self.entities_rendered += 1
        
        # Return position for collision box rendering
        return player_x, player_y
        
    def _render_player_entity(self, player: Player, world_x: float, world_y: float,
                             camera: Camera, is_local: bool):
        """Render a single player entity
        
        Args:
            player: Player object
            world_x: World X position
            world_y: World Y position
            camera: Camera instance
            is_local: True if this is the local player
        """
        # Use interpolated render position ONLY for other players, not local player
        # Local player should have direct, responsive movement
        if not is_local and hasattr(player, 'render_x') and hasattr(player, 'render_y'):
            # Calculate offset from actual position
            offset_x = player.render_x - player.x
            offset_y = player.render_y - player.y
            # Apply offset to world position
            render_world_x = world_x + offset_x
            render_world_y = world_y + offset_y
        else:
            # For local player or when no interpolation available, use actual position
            render_world_x = world_x
            render_world_y = world_y
            
        # Convert to screen position
        # Player position represents top-left of sprite tile
        screen_x, screen_y = camera.world_to_screen(render_world_x, render_world_y)
        
        # DEBUG: Log sprite position
        if is_local:
            logger.debug(f"SPRITE: World ({render_world_x:.1f}, {render_world_y:.1f}) -> Screen ({screen_x}, {screen_y})")
        
        # Try to render with GANI animation first
        rendered_with_gani = False
        if self.gani_system and hasattr(player, 'id'):
            entity_id = player.id if player.id is not None else -1 if is_local else id(player)
            
            # Check if entity has GANI animation
            if entity_id in self.gani_system.entity_states:
                # Render GANI animation at actual position (no offset)
                self.gani_system.render_entity(entity_id, self.screen, 
                                             int(screen_x), int(screen_y), 
                                             0, 0)  # No camera offset needed, already in screen coords
                rendered_with_gani = True
        
        # Fallback to simple rendering if no GANI
        if not rendered_with_gani:
            # Choose color
            color = self.LOCAL_PLAYER_COLOR if is_local else self.OTHER_PLAYER_COLOR
            
            # Calculate size based on zoom
            base_size = 16
            size = max(4, int(base_size * camera.zoom))
            half_size = size // 2
            
            # Draw player sprite (simple circle for now) at actual position
            if size >= 4:
                # Draw player circle at actual position (no offset)
                pygame.draw.circle(self.screen, color,
                                 (int(screen_x + half_size), int(screen_y + half_size)),
                                 half_size)
                
                # Draw direction indicator
                if hasattr(player, 'sprite'):
                    direction = player.sprite % 4  # 0=up, 1=left, 2=down, 3=right
                    self._draw_direction_indicator(screen_x + half_size, screen_y + half_size,
                                                 half_size, direction)
            else:
                # Very zoomed out - just draw a pixel
                self.screen.set_at((int(screen_x), int(screen_y)), color)
            
        # Draw player name above sprite
        if camera.zoom >= 0.5 and hasattr(player, 'nickname') and player.nickname:
            # Calculate tile size
            tile_size = int(16 * camera.zoom)
            # Name should appear above the sprite
            name_y = screen_y - 5
            if rendered_with_gani:
                name_y -= 20  # Extra offset for GANI sprites
            self._render_entity_name(player.nickname, int(screen_x + tile_size // 2),
                                   name_y, is_local)
            
        # Debug features
        if self.show_hitboxes:
            # Draw hitbox around the actual sprite
            tile_size = int(16 * camera.zoom)
            pygame.draw.rect(self.screen, (255, 0, 0),
                           (int(screen_x), int(screen_y), tile_size, tile_size), 1)
            
        if self.show_coordinates:
            # Show coordinates below sprite
            coord_text = f"({world_x:.1f}, {world_y:.1f})"
            coord_surface = self.name_font.render(coord_text, True, (255, 255, 0))
            tile_size = int(16 * camera.zoom)
            self.screen.blit(coord_surface, (int(screen_x), int(screen_y + tile_size + 5)))
            
    def _render_npc_entity(self, npc, camera: Camera):
        """Render a single NPC entity
        
        Args:
            npc: NPC object
            camera: Camera instance
        """
        # Convert to screen position
        screen_x, screen_y = camera.world_to_screen(npc.x, npc.y)
        
        # Calculate size
        size = max(4, int(16 * camera.zoom))
        
        # Draw NPC (simple rectangle for now)
        if size >= 4:
            pygame.draw.rect(self.screen, self.NPC_COLOR,
                           (int(screen_x), int(screen_y), size, size))
        else:
            self.screen.set_at((int(screen_x), int(screen_y)), self.NPC_COLOR)
            
        # Draw NPC name if available
        if camera.zoom >= 0.5 and hasattr(npc, 'name') and npc.name:
            self._render_entity_name(npc.name, screen_x + size // 2,
                                   screen_y - 5, False)
            
    def _draw_direction_indicator(self, center_x: int, center_y: int,
                                 radius: int, direction: int):
        """Draw direction indicator on entity
        
        Args:
            center_x: Center X position
            center_y: Center Y position
            radius: Entity radius
            direction: Direction (0=up, 1=left, 2=down, 3=right)
        """
        indicator_color = (255, 255, 255)
        indicator_size = max(3, radius // 2)
        
        if direction == 0:  # Up
            points = [(center_x, center_y - radius),
                     (center_x - indicator_size, center_y - radius + indicator_size),
                     (center_x + indicator_size, center_y - radius + indicator_size)]
        elif direction == 1:  # Left
            points = [(center_x - radius, center_y),
                     (center_x - radius + indicator_size, center_y - indicator_size),
                     (center_x - radius + indicator_size, center_y + indicator_size)]
        elif direction == 2:  # Down
            points = [(center_x, center_y + radius),
                     (center_x - indicator_size, center_y + radius - indicator_size),
                     (center_x + indicator_size, center_y + radius - indicator_size)]
        else:  # Right (3)
            points = [(center_x + radius, center_y),
                     (center_x + radius - indicator_size, center_y - indicator_size),
                     (center_x + radius - indicator_size, center_y + indicator_size)]
                     
        pygame.draw.polygon(self.screen, indicator_color, points)
        
    def _render_entity_name(self, name: str, x: int, y: int, is_local: bool):
        """Render entity name with shadow
        
        Args:
            name: Entity name
            x: Center X position
            y: Y position (above entity)
            is_local: True if local player
        """
        # Choose color
        text_color = (255, 255, 100) if is_local else (255, 255, 255)
        shadow_color = (0, 0, 0)
        
        # Render text
        text_surface = self.name_font.render(name, True, text_color)
        text_rect = text_surface.get_rect(center=(x, y))
        
        # Draw shadow
        shadow_surface = self.name_font.render(name, True, shadow_color)
        shadow_rect = shadow_surface.get_rect(center=(x + self.name_shadow_offset,
                                                     y + self.name_shadow_offset))
        self.screen.blit(shadow_surface, shadow_rect)
        
        # Draw text
        self.screen.blit(text_surface, text_rect)
        
    def _get_entity_position(self, entity, client: Client) -> Tuple[float, float]:
        """Get entity position in world coordinates
        
        Args:
            entity: Entity object
            client: PyReborn client
            
        Returns:
            (world_x, world_y) tuple
        """
        # Check for world coordinates (x2/y2) first
        if hasattr(entity, 'x2') and entity.x2 is not None and hasattr(entity, 'y2') and entity.y2 is not None:
            return entity.x2, entity.y2
            
        # Check if we're in GMAP mode
        if client.is_gmap_mode() and hasattr(entity, 'gmaplevelx') and entity.gmaplevelx is not None:
            # Calculate world position from segment + local
            world_x = entity.gmaplevelx * 64 + entity.x
            world_y = entity.gmaplevely * 64 + entity.y
            return world_x, world_y
            
        # Default to local coordinates
        return entity.x, entity.y
        
    def _is_in_view(self, x: float, y: float, left: float, top: float,
                   right: float, bottom: float) -> bool:
        """Check if position is in view
        
        Args:
            x, y: World position
            left, top, right, bottom: View bounds
            
        Returns:
            True if in view
        """
        margin = 2.0  # Extra margin in tiles
        return (x >= left - margin and x <= right + margin and
                y >= top - margin and y <= bottom + margin)
                
    def toggle_hitboxes(self):
        """Toggle hitbox display"""
        self.show_hitboxes = not self.show_hitboxes
        
    def toggle_coordinates(self):
        """Toggle coordinate display"""
        self.show_coordinates = not self.show_coordinates
        
    def get_render_stats(self) -> dict:
        """Get rendering statistics"""
        return {
            'entities_rendered': self.entities_rendered,
            'show_hitboxes': self.show_hitboxes,
            'show_coordinates': self.show_coordinates
        }
    
    def _update_entity_animations(self, client: Client):
        """Update GANI animations based on entity states
        
        Args:
            client: PyReborn client
        """
        if not self.gani_system:
            return
        
        # Get session manager
        session_manager = client.get_manager('session')
        if not session_manager:
            return
        
        # Update local player animation
        local_player = session_manager.get_player()
        if local_player:
            self._update_player_animation(local_player, True)
        
        # Update other players
        players = session_manager.get_all_players()
        if players:
            local_id = local_player.id if local_player else None
            for player_id, player in players.items():
                if player_id != local_id:
                    self._update_player_animation(player, False)
    
    def _update_player_animation(self, player: Player, is_local: bool):
        """Update animation for a player
        
        Args:
            player: Player object
            is_local: True if local player
        """
        if not self.gani_system or not player:
            return
        
        # Determine entity ID
        entity_id = player.id if hasattr(player, 'id') and player.id is not None else (-1 if is_local else id(player))
        
        # Determine animation based on state
        animation_name = "idle"  # Default
        
        # Check if moving
        if hasattr(player, 'is_moving') and player.is_moving:
            animation_name = "walk"
        # Check for other states
        elif hasattr(player, 'is_sitting') and player.is_sitting:
            animation_name = "sit"
        elif hasattr(player, 'is_swimming') and player.is_swimming:
            animation_name = "swim"
        elif hasattr(player, 'is_hurt') and player.is_hurt:
            animation_name = "hurt"
        elif hasattr(player, 'is_dead') and player.is_dead:
            animation_name = "dead"
        elif hasattr(player, 'is_carrying') and player.is_carrying:
            animation_name = "carry"
        elif hasattr(player, 'sword_out') and player.sword_out:
            animation_name = "sword"
        
        # Get direction
        direction = 2  # Default down
        if hasattr(player, 'sprite'):
            direction = player.sprite % 4
            # Debug log for local player only
            if is_local and hasattr(self, '_last_logged_sprite') and self._last_logged_sprite != player.sprite:
                logger.debug(f"Player sprite changed: {self._last_logged_sprite} -> {player.sprite}, direction: {direction}")
                self._last_logged_sprite = player.sprite
            elif is_local and not hasattr(self, '_last_logged_sprite'):
                self._last_logged_sprite = player.sprite
                logger.debug(f"Player initial sprite: {player.sprite}, direction: {direction}")
        elif hasattr(player, 'direction'):
            direction = player.direction
        
        # Check if we need to change animation
        current_anim = self.entity_animations.get(entity_id)
        if current_anim != animation_name:
            self.gani_system.set_entity_animation(entity_id, animation_name, direction)
            self.entity_animations[entity_id] = animation_name
        else:
            # Just update direction
            self.gani_system.set_entity_direction(entity_id, direction)
            if is_local:
                logger.debug(f"Updating local player direction to {direction} (sprite={player.sprite if hasattr(player, 'sprite') else 'N/A'})")
    
    def _render_collision_boxes(self, client: Client, camera: Camera, 
                                player_x: float, player_y: float):
        """Render collision boxes for debug visualization
        
        Args:
            client: PyReborn client instance
            camera: Camera instance
            player_x: Player world X position (same as used for sprite)
            player_y: Player world Y position (same as used for sprite)
        """
        # Check if physics system is available
        if not self.physics_system:
            logger.warning("Physics system not connected for collision box rendering")
            return
        
        # Calculate tile size based on zoom
        tile_size = int(16 * camera.zoom)
        
        # Get the physics body for the player (entity_id=-1 for local player)
        if -1 not in self.physics_system.bodies:
            logger.debug("No physics body found for player")
            return
        
        body = self.physics_system.bodies[-1]
        
        # Get the actual physics AABB which includes the collision offsets
        aabb = body.get_aabb()
        
        # IMPORTANT: Draw the collision box EXACTLY where it is for physics
        # No visual adjustments! What you see is what you get for collision detection
        visual_collision_x = aabb.x
        visual_collision_y = aabb.y
        
        # Convert to screen coordinates using the SAME method as sprite rendering
        collision_screen_x, collision_screen_y = camera.world_to_screen(visual_collision_x, visual_collision_y)
        collision_screen_x = int(collision_screen_x)
        collision_screen_y = int(collision_screen_y)
        screen_width = int(aabb.width * tile_size)
        screen_height = int(aabb.height * tile_size)
        
        # DEBUG: Log collision box position
        logger.debug(f"COLLISION: Physics body at ({body.x:.1f}, {body.y:.1f})")
        logger.debug(f"COLLISION: Visual box at ({visual_collision_x:.1f}, {visual_collision_y:.1f})")
        logger.debug(f"COLLISION: Screen coords ({collision_screen_x}, {collision_screen_y}), size {screen_width}x{screen_height}")
        
        # Draw the collision box with semi-transparent fill
        collision_surface = pygame.Surface((screen_width, screen_height))
        collision_surface.set_alpha(50)  # Semi-transparent
        collision_surface.fill(self.COLLISION_BOX_COLOR)  # Magenta
        self.screen.blit(collision_surface, (collision_screen_x, collision_screen_y))
        
        # Draw the collision box outline
        pygame.draw.rect(self.screen, self.COLLISION_BOX_COLOR,
                       (collision_screen_x, collision_screen_y, screen_width, screen_height), 2)
        
        # Draw a small dot at the collision center (where feet touch ground)
        # Yellow dot at center of the visual collision box
        # Collision box is 1.0 wide, 0.5 high
        feet_world_x = visual_collision_x + 0.5  # Center of 1.0 wide box
        feet_world_y = visual_collision_y + 0.25  # Center of 0.5 high box
        feet_screen_x, feet_screen_y = camera.world_to_screen(feet_world_x, feet_world_y)
        feet_screen_x = int(feet_screen_x)
        feet_screen_y = int(feet_screen_y)
        pygame.draw.circle(self.screen, (255, 255, 0), 
                         (feet_screen_x, feet_screen_y), 4)
        
        # Draw a small cross at the feet for clarity
        pygame.draw.line(self.screen, (255, 255, 0),
                        (feet_screen_x - 6, feet_screen_y),
                        (feet_screen_x + 6, feet_screen_y), 2)
        pygame.draw.line(self.screen, (255, 255, 0),
                        (feet_screen_x, feet_screen_y - 6),
                        (feet_screen_x, feet_screen_y + 6), 2)
        
        # Debug logging
        logger.debug(f"Feet position: ({player_x:.1f}, {player_y:.1f}), "
                    f"Visual collision at: ({visual_collision_x:.1f}, {visual_collision_y:.1f}), "
                    f"Size: {body.width}x{body.height} tiles")
    
    def update(self, dt: float):
        """Update animations
        
        Args:
            dt: Delta time in seconds
        """
        if self.gani_system:
            self.gani_system.update(dt)