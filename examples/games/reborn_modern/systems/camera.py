"""
Camera System
=============

Handles viewport transformations and smooth camera movement.
"""

import pygame
from typing import Tuple, Optional
import math
import logging

logger = logging.getLogger(__name__)


class Camera:
    """Camera for 2D world view with smooth following"""
    
    def __init__(self, width: int, height: int):
        """Initialize camera
        
        Args:
            width: Viewport width in pixels
            height: Viewport height in pixels
        """
        self.width = width
        self.height = height
        
        # Camera position (world coordinates in tiles)
        self.x = 0.0
        self.y = 0.0
        
        # Target position for smooth following (in world coordinates)
        self.target_x = 0.0
        self.target_y = 0.0
        
        # Target follow position (what we're following)
        self.follow_x = 0.0
        self.follow_y = 0.0
        
        # Camera settings
        self.smoothing = 0.1  # Lower = smoother, Higher = snappier
        self.zoom = 1.0      # Zoom level (1.0 = normal)
        self.min_zoom = 0.25
        self.max_zoom = 4.0
        
        # Screen shake
        self.shake_intensity = 0.0
        self.shake_duration = 0.0
        
    def update(self, dt: float):
        """Update camera position and effects
        
        Args:
            dt: Delta time in seconds
        """
        # Smooth camera following with delta-time independence
        if self.smoothing > 0:
            # Use exponential smoothing for frame-rate independent behavior
            # This ensures consistent smoothing regardless of framerate
            factor = 1.0 - pow(1.0 - self.smoothing, dt * 60.0)  # Normalized to 60 FPS
            self.x += (self.target_x - self.x) * factor
            self.y += (self.target_y - self.y) * factor
        else:
            self.x = self.target_x
            self.y = self.target_y
            
        # Update screen shake
        if self.shake_duration > 0:
            self.shake_duration -= dt
            if self.shake_duration <= 0:
                self.shake_intensity = 0.0
                
    def follow(self, x: float, y: float):
        """Set target position to follow
        
        Args:
            x: Target X position in world tiles
            y: Target Y position in world tiles
        """
        # Store what we're following
        self.follow_x = x
        self.follow_y = y
        
        # Calculate camera position to center on target (zoom-independent)
        self._update_camera_target()
        
    def set_position(self, x: float, y: float):
        """Immediately set camera position
        
        Args:
            x: X position in world tiles
            y: Y position in world tiles
        """
        self.x = x
        self.y = y
        self.target_x = x
        self.target_y = y
        
    def world_to_screen(self, world_x: float, world_y: float) -> Tuple[int, int]:
        """Convert world position to screen position
        
        Args:
            world_x: X position in world tiles
            world_y: Y position in world tiles
            
        Returns:
            (screen_x, screen_y) in pixels
        """
        # Apply zoom and camera offset
        screen_x = int((world_x - self.x) * 16 * self.zoom)
        screen_y = int((world_y - self.y) * 16 * self.zoom)
        
        # Apply screen shake if active
        if self.shake_intensity > 0:
            import random
            screen_x += random.randint(-self.shake_intensity, self.shake_intensity)
            screen_y += random.randint(-self.shake_intensity, self.shake_intensity)
            
        return screen_x, screen_y
        
    def screen_to_world(self, screen_x: int, screen_y: int) -> Tuple[float, float]:
        """Convert screen position to world position
        
        Args:
            screen_x: X position in pixels
            screen_y: Y position in pixels
            
        Returns:
            (world_x, world_y) in tiles
        """
        world_x = screen_x / (16 * self.zoom) + self.x
        world_y = screen_y / (16 * self.zoom) + self.y
        return world_x, world_y
        
    def get_visible_bounds(self) -> Tuple[float, float, float, float]:
        """Get the visible world bounds
        
        Returns:
            (left, top, right, bottom) in world tiles
        """
        left = self.x
        top = self.y
        right = self.x + self.width / (16 * self.zoom)
        bottom = self.y + self.height / (16 * self.zoom)
        return left, top, right, bottom
        
    def _update_camera_target(self):
        """Update camera target based on follow position and current zoom"""
        # Safety check for None values
        if self.follow_x is None or self.follow_y is None:
            logger.warning(f"Camera follow position is None: x={self.follow_x}, y={self.follow_y}")
            return
            
        # Camera position should be such that follow position appears at screen center
        # Screen center in tiles = camera position + (screen_size / 2) / (tile_size * zoom)
        # So: follow_pos = camera_pos + (screen_size / 2) / (16 * zoom)
        # Therefore: camera_pos = follow_pos - (screen_size / 2) / (16 * zoom)
        tiles_to_center_x = (self.width / 2) / (16 * self.zoom)
        tiles_to_center_y = (self.height / 2) / (16 * self.zoom)
        
        self.target_x = self.follow_x - tiles_to_center_x
        self.target_y = self.follow_y - tiles_to_center_y
        
    def set_zoom(self, zoom: float):
        """Set zoom level
        
        Args:
            zoom: Zoom level (1.0 = normal)
        """
        old_zoom = self.zoom
        self.zoom = max(self.min_zoom, min(self.max_zoom, zoom))
        
        # Keep the follow target at the same screen position during zoom
        # This makes it appear that we're zooming "onto" the target
        if old_zoom != self.zoom and old_zoom > 0:
            # Calculate screen position of follow target with old zoom
            screen_x = (self.follow_x - self.x) * 16 * old_zoom
            screen_y = (self.follow_y - self.y) * 16 * old_zoom
            
            # Calculate what camera position would put follow target at same screen position with new zoom
            if self.zoom > 0:
                new_world_x_at_screen_pos = screen_x / (16 * self.zoom)
                new_world_y_at_screen_pos = screen_y / (16 * self.zoom)
                
                # Set camera position to maintain follow target at same screen position
                self.x = self.follow_x - new_world_x_at_screen_pos
                self.y = self.follow_y - new_world_y_at_screen_pos
                self.target_x = self.x
                self.target_y = self.y
            else:
                # Fallback to normal centering if zoom is invalid
                self._update_camera_target()
        else:
            # Update camera target when zoom changes to keep player centered (first zoom or invalid old zoom)
            self._update_camera_target()
        
    def zoom_in(self, factor: float = 1.2):
        """Zoom in by a factor"""
        self.set_zoom(self.zoom * factor)
        
    def zoom_out(self, factor: float = 1.2):
        """Zoom out by a factor"""
        self.set_zoom(self.zoom / factor)
        
    def shake(self, intensity: int, duration: float):
        """Apply screen shake effect
        
        Args:
            intensity: Shake intensity in pixels
            duration: Shake duration in seconds
        """
        self.shake_intensity = intensity
        self.shake_duration = duration
        
    def get_tile_size(self) -> int:
        """Get the current tile size in pixels based on zoom"""
        return int(16 * self.zoom)