"""
Rendering System
================

Handles all visual rendering for the Modern Reborn game.
Uses a clean, modular architecture with separate renderers for different concerns.
"""

import pygame
import logging
from typing import Optional
from pathlib import Path
import time

from pyreborn import Client
from pyreborn.events import EventType

from .render_mode import RenderMode
from .camera import Camera
from .level_renderer import LevelRenderer
from .gmap_renderer import GMAPRenderer
from .entity_renderer import EntityRenderer

logger = logging.getLogger(__name__)


class RenderingSystem:
    """Main rendering system with modular architecture"""
    
    def __init__(self, screen: pygame.Surface, client: Client, config: dict):
        """Initialize rendering system
        
        Args:
            screen: Pygame screen surface
            client: PyReborn client instance
            config: Graphics configuration
        """
        self.screen = screen
        self.client = client
        self.config = config
        
        # Initialize components
        self.camera = Camera(screen.get_width(), screen.get_height())
        self.level_renderer = LevelRenderer(screen)
        self.gmap_renderer = GMAPRenderer(screen, self.level_renderer)
        
        # Get assets path for entity renderer
        game_root = Path(__file__).parent.parent
        assets_path = str(game_root / "assets")
        self.entity_renderer = EntityRenderer(screen, assets_path)
        
        # Rendering state
        self.render_mode = RenderMode.LOADING
        self.transition_progress = 0.0
        
        # Try to load tileset
        self._load_tileset()
        
        # Subscribe to events
        self._subscribe_events()
        
        # Debug settings
        self.show_stats = False
        self.show_minimap = False
        self.show_level_links = True  # Show level links by default
        
        # Physics system reference (for level links)
        self.physics_system = None
        
        logger.info("Rendering system initialized with modular architecture")
        
    def set_physics_system(self, physics_system):
        """Set reference to physics system for level link rendering"""
        self.physics_system = physics_system
        logger.info("Physics system reference set in renderer")
        
    def toggle_level_links(self):
        """Toggle level link visualization"""
        self.show_level_links = not self.show_level_links
        logger.info(f"Level link visualization: {'ON' if self.show_level_links else 'OFF'}")
        return self.show_level_links
        
    def _load_tileset(self):
        """Load tileset for tile rendering"""
        try:
            # Try to find tileset in assets
            game_root = Path(__file__).parent.parent
            assets_dir = game_root / "assets"
            
            tileset_names = ['pics1.png', 'tileset.png', 'tiles.png']
            
            for name in tileset_names:
                tileset_path = assets_dir / name
                if tileset_path.exists():
                    tileset = pygame.image.load(str(tileset_path)).convert()
                    self.level_renderer.tileset = tileset
                    logger.info(f"Loaded tileset: {name}")
                    return
                    
            logger.warning("No tileset found in assets")
            
        except Exception as e:
            logger.error(f"Failed to load tileset: {e}")
            
    def _subscribe_events(self):
        """Subscribe to PyReborn events"""
        if not self.client:
            return
            
        events = self.client.events
        
        # Level events
        events.subscribe(EventType.LEVEL_BOARD_LOADED, self._on_level_loaded)
        events.subscribe(EventType.LEVEL_DATA_UPDATED, self._on_level_data_updated)
        events.subscribe(EventType.LEVEL_TRANSITION, self._on_level_changed)
        
        # GMAP events
        events.subscribe(EventType.GMAP_LOADED, self._on_gmap_loaded)
        events.subscribe(EventType.GMAP_MODE_CHANGED, self._on_gmap_mode_changed)
        
        # Player events
        events.subscribe(EventType.PLAYER_MOVED, self._on_player_moved)
        events.subscribe(EventType.PLAYER_ADDED, self._on_player_added)
        events.subscribe(EventType.PLAYER_REMOVED, self._on_player_removed)
        
    def render(self):
        """Main render method"""
        # Clear screen
        self.screen.fill((20, 30, 40))  # Dark blue background
        
        # Update render mode
        self._update_render_mode()
        
        # Update camera
        self._update_camera()
        
        # Render based on mode
        if self.render_mode == RenderMode.LOADING:
            self._render_loading_screen()
        elif self.render_mode == RenderMode.SINGLE_LEVEL:
            self._render_single_level()
        elif self.render_mode == RenderMode.GMAP:
            self._render_gmap()
        elif self.render_mode == RenderMode.TRANSITIONING:
            self._render_transition()
            
        # Always render entities on top (use the same camera as the level)
        render_camera = getattr(self, '_current_render_camera', self.camera)
        self.entity_renderer.render(self.client, render_camera)
        
        # Debug: Log collision box state after entity rendering
        if self.entity_renderer.show_collision_boxes:
            logger.debug(f"Collision boxes should be rendered (show={self.entity_renderer.show_collision_boxes}, physics={self.entity_renderer.physics_system is not None})")
        
        # Render level links if available
        if self.show_level_links:
            self._render_level_links()
        
        # Render UI overlays
        if self.show_stats:
            self._render_stats()
            
        # Render debug info (always show for now, can toggle with F5)
        # if hasattr(self.config, 'show_debug') and self.config.show_debug:
        #     self._render_debug_info()
            
    def _update_render_mode(self):
        """Update rendering mode based on client state"""
        if not self.client or not self.client.is_connected():
            self.render_mode = RenderMode.LOADING
            return
            
        # Check if we're in GMAP mode
        if self.client.is_gmap_mode():
            if self.render_mode != RenderMode.GMAP:
                logger.info("Switching to GMAP render mode")
                self.render_mode = RenderMode.GMAP
        else:
            # Check if we have a current level
            if self.client.level_manager and self.client.level_manager.get_current_level():
                if self.render_mode != RenderMode.SINGLE_LEVEL:
                    logger.info("Switching to single level render mode")
                    self.render_mode = RenderMode.SINGLE_LEVEL
            else:
                self.render_mode = RenderMode.LOADING
                
    def _update_camera(self):
        """Update camera to follow player"""
        if not self.client:
            return
            
        # Use PyReborn's coordinate manager to get the correct position
        # It handles all the complexity of GMAP vs single-level modes internally
        position = self.client.get_player_render_position()
        if position:
            player_x, player_y = position
            self.camera.follow(player_x, player_y)
            logger.debug(f"Camera following player at ({player_x:.1f}, {player_y:.1f})")
        else:
            logger.debug("No player position available for camera")
            
        self.camera.update(0.016)  # Assume 60 FPS for now
        
    def _render_loading_screen(self):
        """Render loading screen"""
        font = pygame.font.Font(None, 48)
        text = font.render("Connecting...", True, (255, 255, 255))
        text_rect = text.get_rect(center=(self.screen.get_width() // 2,
                                         self.screen.get_height() // 2))
        self.screen.blit(text, text_rect)
        
        # Show connection status if available
        if self.client:
            status_font = pygame.font.Font(None, 24)
            if self.client.is_connected():
                status = "Connected - Waiting for level data..."
            else:
                status = "Connecting to server..."
            status_text = status_font.render(status, True, (200, 200, 200))
            status_rect = status_text.get_rect(center=(self.screen.get_width() // 2,
                                                      self.screen.get_height() // 2 + 40))
            self.screen.blit(status_text, status_rect)
            
    def _render_single_level(self):
        """Render single level mode"""
        if not self.client or not self.client.level_manager:
            return
            
        level = self.client.level_manager.get_current_level()
        self.level_renderer.render_single(level, self.camera)
        self._current_render_camera = self.camera
        
    def _render_gmap(self):
        """Render GMAP mode"""
        # Use the full GMAP renderer now that level name mismatch is fixed
        self.gmap_renderer.render(self.client, self.camera)
        self._current_render_camera = self.camera
        
    def _render_transition(self):
        """Render transition between modes"""
        # For now, just render the target mode
        if self.render_mode == RenderMode.TRANSITIONING:
            self.render_mode = RenderMode.SINGLE_LEVEL
        self._render_single_level()
        
    def _render_stats(self):
        """Render performance statistics"""
        font = pygame.font.Font(None, 20)
        y_offset = 10
        x_pos = self.screen.get_width() - 200
        
        stats = []
        stats.append(f"Render Mode: {self.render_mode.name}")
        stats.append(f"Camera: ({self.camera.x:.1f}, {self.camera.y:.1f})")
        stats.append(f"Zoom: {self.camera.zoom:.2f}x")
        
        # Get stats from renderers
        level_stats = self.level_renderer.get_cache_stats()
        stats.append(f"Level Cache: {level_stats['cache_size']}/{level_stats['max_size']}")
        stats.append(f"Cache Hit Rate: {level_stats['hit_rate']:.1%}")
        
        if self.render_mode == RenderMode.GMAP:
            gmap_stats = self.gmap_renderer.get_render_stats()
            stats.append(f"Levels: {gmap_stats['levels_rendered']}/{gmap_stats['levels_in_view']}")
            
        entity_stats = self.entity_renderer.get_render_stats()
        stats.append(f"Entities: {entity_stats['entities_rendered']}")
        
        # Render stats
        for stat in stats:
            text = font.render(stat, True, (255, 255, 100))
            shadow = font.render(stat, True, (0, 0, 0))
            self.screen.blit(shadow, (x_pos + 1, y_offset + 1))
            self.screen.blit(text, (x_pos, y_offset))
            y_offset += 22
            
    def _render_debug_info(self):
        """Render debug information"""
        font = pygame.font.Font(None, 24)
        debug_info = []
        
        # Current level info
        if self.client and self.client.level_manager:
            level = self.client.level_manager.get_current_level()
            if level:
                debug_info.append(f"Level: {level.name}")
                debug_info.append(f"Size: {level.width}x{level.height}")
                
        # Player info
        if self.client and self.client.session_manager:
            player = self.client.session_manager.get_player()
            if player:
                if hasattr(player, 'x2') and player.x2 is not None:
                    debug_info.append(f"Player World: ({player.x2:.1f}, {player.y2:.1f})")
                debug_info.append(f"Player Local: ({player.x:.1f}, {player.y:.1f})")
                
        # Render debug info
        y_offset = 10
        for line in debug_info:
            text = font.render(line, True, (255, 255, 0))
            shadow = font.render(line, True, (0, 0, 0))
            for dx, dy in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
                self.screen.blit(shadow, (10 + dx, y_offset + dy))
            self.screen.blit(text, (10, y_offset))
            y_offset += 26
            
        # Draw center crosshair
        center_x = self.screen.get_width() // 2
        center_y = self.screen.get_height() // 2
        pygame.draw.line(self.screen, (255, 0, 0),
                        (center_x - 10, center_y),
                        (center_x + 10, center_y), 2)
        pygame.draw.line(self.screen, (255, 0, 0),
                        (center_x, center_y - 10),
                        (center_x, center_y + 10), 2)
                        
    # Event handlers
    def _on_level_loaded(self, event):
        """Handle level loaded event"""
        level = event.get('level')
        if level:
            logger.info(f"Level loaded: {level.name}")
            # Invalidate cache for this level
            self.level_renderer.invalidate_cache(level.name)
            
    def _on_level_data_updated(self, event):
        """Handle level data updated event"""
        level_name = event.get('level_name')
        if level_name:
            logger.info(f"Level data updated: {level_name}")
            # Invalidate cache for this level
            self.level_renderer.invalidate_cache(level_name)
            
    def _on_level_changed(self, event):
        """Handle level change"""
        logger.debug("Level changed")
        
    def _on_gmap_loaded(self, event):
        """Handle GMAP loaded"""
        gmap_file = event.get('gmap_file')
        logger.info(f"GMAP loaded: {gmap_file}")
        
    def _on_gmap_mode_changed(self, event):
        """Handle GMAP mode change"""
        logger.debug("GMAP mode changed")
        
    def _on_player_moved(self, event):
        """Handle player movement"""
        # Camera follows player automatically
        pass
        
    def _on_player_added(self, event):
        """Handle new player"""
        pass
        
    def _on_player_removed(self, event):
        """Handle player removal"""
        pass
        
    def _render_level_links(self):
        """Render level link visualization"""
        # Note: We don't need physics system or level_link_manager for visualization
        # Those are only needed for actual warp functionality
        
        # Get current level from client
        if not self.client or not self.client.level_manager:
            return
            
        # In GMAP mode, we need to get links from ALL loaded levels and render
        # only those that are visible. Links are stored per-level.
        levels_to_check = []
        
        if self.client.is_gmap_mode():
            # In GMAP mode, get all loaded levels
            level_manager = self.client.level_manager
            # Try both attribute names for compatibility
            level_cache = None
            if hasattr(level_manager, '_level_cache'):
                level_cache = level_manager._level_cache
            elif hasattr(level_manager, 'levels'):
                level_cache = level_manager.levels
                
            if level_cache:
                # Get all cached levels
                for level_name, level in level_cache.items():
                    if level and hasattr(level, 'links') and level.links:
                        levels_to_check.append(level)
                        logger.debug(f"[LINKS] Found {len(level.links)} links in GMAP level {level_name}")
            logger.debug(f"[LINKS] GMAP mode: checking {len(levels_to_check)} levels for links")
            # Debug: Log which levels we're checking
            if levels_to_check:
                level_names = [level.name for level in levels_to_check[:3]]
                logger.debug(f"[LINKS] First 3 levels: {level_names}")
        else:
            # Single level mode - just get current level
            current_level = self.client.level_manager.get_current_level()
            if current_level:
                levels_to_check.append(current_level)
                if hasattr(current_level, 'links'):
                    logger.debug(f"[LINKS] Single level mode: {current_level.name} has {len(current_level.links)} links")
        
        if not levels_to_check:
            logger.warning("[LINKS] No levels to check for link rendering")
            return
            
        # Calculate tile size based on zoom
        tile_size = int(16 * self.camera.zoom)
        
        # Draw links from all relevant levels
        for level in levels_to_check:
            links = level.links if hasattr(level, 'links') else []
            if not links:
                continue
                
            # Debug: Show level position in GMAP
            level_position = None
            if self.client.is_gmap_mode():
                level_manager = self.client.level_manager
                if hasattr(level_manager, '_gmap_data') and level_manager._gmap_data:
                    for gmap_name, gmap_info in level_manager._gmap_data.items():
                        if 'position_map' in gmap_info:
                            # Normalize level name for comparison (add .nw if missing)
                            normalized_name = level.name if level.name.endswith('.nw') else f"{level.name}.nw"
                            for pos, lvl_name in gmap_info['position_map'].items():
                                if lvl_name == normalized_name or lvl_name == level.name:
                                    level_position = pos
                                    break
                        if level_position:
                            break
            logger.debug(f"[LINKS] Rendering {len(links)} links from level {level.name} at GMAP pos {level_position}")
            
            # Draw each link
            for i, link in enumerate(links):
                # Get link coordinates - in GMAP mode, convert to world coordinates
                if self.client.is_gmap_mode():
                    # Convert local coordinates to world coordinates
                    level_manager = self.client.level_manager
                    position = None
                    
                    # Try to find level position in GMAP data
                    if hasattr(level_manager, '_gmap_data') and level_manager._gmap_data:
                        # Get the current GMAP data
                        for gmap_name, gmap_info in level_manager._gmap_data.items():
                            if 'position_map' in gmap_info:
                                # Normalize level name for comparison (add .nw if missing)
                                normalized_name = level.name if level.name.endswith('.nw') else f"{level.name}.nw"
                                # position_map maps (x,y) -> level_name, so we need to reverse lookup
                                for pos, level_name in gmap_info['position_map'].items():
                                    if level_name == normalized_name or level_name == level.name:
                                        position = pos
                                        break
                            if position:
                                break
                    
                    if position:
                        # Convert to world coordinates
                        link_x = position[0] * 64 + link.x
                        link_y = position[1] * 64 + link.y
                    else:
                        # Level not in GMAP or position not found, use local coordinates
                        link_x = link.x
                        link_y = link.y
                        logger.debug(f"[LINKS] No GMAP position found for {level.name}, using local coords")
                else:
                    # Single level mode - use local coordinates
                    link_x = link.x
                    link_y = link.y
                
                # Convert to screen coordinates
                screen_x = int((link_x - self.camera.x) * tile_size)
                screen_y = int((link_y - self.camera.y) * tile_size)
                
                # Debug first link from each level
                if i == 0:
                    logger.debug(f"[LINKS] Link 0 from {level.name}: world({link_x},{link_y}) -> screen({screen_x},{screen_y})")
                
                # Calculate link dimensions
                link_width = int(link.width * tile_size)
                link_height = int(link.height * tile_size)
                
                # Check if link is visible on screen
                if (screen_x + link_width < 0 or screen_x > self.screen.get_width() or
                    screen_y + link_height < 0 or screen_y > self.screen.get_height()):
                    continue
                    
                # Draw link rectangle
                # Use different colors for different link types
                # Check if it's a GMAP edge link
                is_gmap_edge_link = False
                destination = getattr(link, 'destination', '')
                if self.client.is_gmap_mode() and destination.endswith('.nw'):
                    # Check if the destination is another GMAP level and this is an edge link
                    if (link.x == 0 and link.width == 1 and link.height == 64) or \
                       (link.y == 0 and link.height == 1 and link.width == 64) or \
                       (link.x == 63 and link.width == 1 and link.height == 64) or \
                       (link.y == 63 and link.height == 1 and link.width == 64):
                        # Check if destination is a GMAP level
                        # The level manager has integrated GMAP functionality
                        level_manager = self.client.level_manager
                        if level_manager and hasattr(level_manager, '_gmap_data') and level_manager._gmap_data:
                            # Check if destination is in any GMAP
                            for gmap_name, gmap_info in level_manager._gmap_data.items():
                                if 'position_map' in gmap_info:
                                    # Check if destination is one of the GMAP levels
                                    if destination in gmap_info['position_map'].values():
                                        is_gmap_edge_link = True
                                        break
                
                if is_gmap_edge_link:
                    # GMAP edge links - red (these are filtered out in GMAP mode)
                    color = (255, 0, 0)
                    alpha = 100
                elif str(getattr(link, 'dest_x', '')) == 'playerx' or str(getattr(link, 'dest_y', '')) == 'playery':
                    # Links with player coordinates - yellow
                    color = (255, 255, 0)
                    alpha = 150
                else:
                    # Normal links - green
                    color = (0, 255, 0)
                    alpha = 150
                    
                # Create transparent surface for the link
                link_surface = pygame.Surface((link_width, link_height))
                link_surface.set_alpha(alpha)
                link_surface.fill(color)
                self.screen.blit(link_surface, (screen_x, screen_y))
                
                # Draw border
                pygame.draw.rect(self.screen, color, 
                               (screen_x, screen_y, link_width, link_height), 2)
                
                # Draw destination text
                font = pygame.font.Font(None, 16)
                dest_text = f"{destination[:20]}"  # Truncate long names
                dest_x = getattr(link, 'dest_x', 'playerx')
                dest_y = getattr(link, 'dest_y', 'playery')
                if str(dest_x) != 'playerx' or str(dest_y) != 'playery':
                    dest_text += f" ({dest_x},{dest_y})"
                
                text_surface = font.render(dest_text, True, (255, 255, 255))
                text_bg = pygame.Surface((text_surface.get_width() + 4, text_surface.get_height() + 2))
                text_bg.fill((0, 0, 0))
                text_bg.set_alpha(200)
                
                text_x = screen_x + 2
                text_y = screen_y + 2
                
                self.screen.blit(text_bg, (text_x - 2, text_y - 1))
                self.screen.blit(text_surface, (text_x, text_y))
        
    def toggle_stats(self):
        """Toggle statistics display"""
        self.show_stats = not self.show_stats
        
    def toggle_minimap(self):
        """Toggle minimap display"""
        self.gmap_renderer.toggle_minimap()
        
    def zoom_in(self):
        """Zoom in"""
        self.camera.zoom_in()
        
    def zoom_out(self):
        """Zoom out"""
        self.camera.zoom_out()
        
    def toggle_debug_hitboxes(self):
        """Toggle hitbox display"""
        self.entity_renderer.toggle_hitboxes()
        
    def toggle_debug_coordinates(self):
        """Toggle coordinate display"""
        self.entity_renderer.toggle_coordinates()