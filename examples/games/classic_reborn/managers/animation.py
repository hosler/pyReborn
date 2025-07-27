"""
Animation Manager Module - Handles player animations and animation states
"""

import time
from typing import Dict, Optional, Tuple
from pyreborn.protocol.enums import Direction
from parsers.gani import GaniManager


class AnimationState:
    """Tracks animation state for a player"""
    
    def __init__(self, gani_name: str = "idle"):
        self.gani_name = gani_name
        self.frame = 0
        self.start_time = time.time()
        self.last_frame_time = time.time()
        self.is_looping = True
        self.is_finished = False
        
    def update(self, frame_duration: float) -> bool:
        """Update animation frame
        
        Args:
            frame_duration: Time between frames in seconds
            
        Returns:
            True if frame changed
        """
        if self.is_finished and not self.is_looping:
            return False
            
        current_time = time.time()
        if current_time - self.last_frame_time >= frame_duration:
            self.last_frame_time = current_time
            self.frame += 1
            return True
        return False
        
    def reset(self):
        """Reset animation to first frame"""
        self.frame = 0
        self.start_time = time.time()
        self.last_frame_time = time.time()
        self.is_finished = False


class AnimationManager:
    """Manages animations for all players"""
    
    def __init__(self, gani_manager: GaniManager):
        """Initialize the animation manager
        
        Args:
            gani_manager: GANI file manager
        """
        self.gani_manager = gani_manager
        
        # Animation states for each player
        self.player_animations: Dict[int, AnimationState] = {}
        
        # Animation settings
        self.frame_duration = 0.02  # 20ms per frame (50 FPS animations)
        
        # Special animation durations
        self.animation_durations = {
            'sword': 0.16,      # Sword swing duration (4 frames at 40ms)
            'grab': 0.3,       # Grab duration
            'lift': 0.3,       # Lift animation duration
            'throw': 0.2,      # Throw pause duration
            'push': -1,        # Push loops forever
            'hurt': 0.5,       # Hurt animation duration
        }
        
    def get_player_animation(self, player_id: int) -> AnimationState:
        """Get or create animation state for a player
        
        Args:
            player_id: Player ID
            
        Returns:
            AnimationState for the player
        """
        if player_id not in self.player_animations:
            # Default to "idle" for new players
            self.player_animations[player_id] = AnimationState("idle")
        return self.player_animations[player_id]
        
    def set_player_animation(self, player_id: int, gani_name: str, reset: bool = True):
        """Set animation for a player
        
        Args:
            player_id: Player ID
            gani_name: GANI animation name
            reset: Whether to reset to frame 0
        """
        anim_state = self.get_player_animation(player_id)
        
        # Only reset if changing animation
        if anim_state.gani_name != gani_name:
            anim_state.gani_name = gani_name
            if reset:
                anim_state.reset()
                
            # Set looping based on animation type
            anim_state.is_looping = gani_name in ['idle', 'walk', 'carry', 'sit']
            
    def update_player_animation(self, player_id: int) -> Tuple[str, int]:
        """Update and get current animation frame for a player
        
        Args:
            player_id: Player ID
            
        Returns:
            Tuple of (gani_name, frame_number)
        """
        anim_state = self.get_player_animation(player_id)
        
        # Get GANI data
        gani = self.gani_manager.load_gani(anim_state.gani_name)
        if not gani:
            return (anim_state.gani_name, 0)
            
        # Use different frame rates for different animations
        frame_duration = self.frame_duration
        if anim_state.gani_name == 'sword':
            frame_duration = 0.04  # Sword runs at half speed (40ms per frame)
            
        # Update frame
        if anim_state.update(frame_duration):
            # Check frame bounds
            max_frames = len(gani.animation_frames)
            if anim_state.frame >= max_frames:
                if anim_state.is_looping:
                    anim_state.frame = 0
                else:
                    anim_state.frame = max_frames - 1
                    anim_state.is_finished = True
                    
        return (anim_state.gani_name, anim_state.frame)
        
    def is_animation_finished(self, player_id: int, gani_name: str) -> bool:
        """Check if a specific animation has finished
        
        Args:
            player_id: Player ID
            gani_name: Animation to check
            
        Returns:
            True if the animation finished playing
        """
        anim_state = self.get_player_animation(player_id)
        
        # Check if it's the right animation
        if anim_state.gani_name != gani_name:
            return False
            
        # For timed animations, check duration
        if gani_name in self.animation_durations:
            duration = self.animation_durations[gani_name]
            if duration > 0:
                # Calculate time since animation started
                elapsed = time.time() - anim_state.start_time
                return elapsed >= duration
                
        # Otherwise check if animation reached end
        return anim_state.is_finished
        
    def get_animation_progress(self, player_id: int) -> float:
        """Get progress through current animation (0.0 to 1.0)
        
        Args:
            player_id: Player ID
            
        Returns:
            Progress from 0.0 to 1.0
        """
        anim_state = self.get_player_animation(player_id)
        gani = self.gani_manager.load_gani(anim_state.gani_name)
        
        if not gani or len(gani.animation_frames) == 0:
            return 0.0
            
        return anim_state.frame / float(len(gani.animation_frames) - 1)
        
    def predict_player_movement(self, player_id: int, x: float, y: float, 
                              direction: Direction, gani: str) -> Tuple[float, float]:
        """Predict player position for smooth movement
        
        Args:
            player_id: Player ID
            x: Current X position
            y: Current Y position
            direction: Movement direction
            gani: Current GANI animation
            
        Returns:
            Tuple of (predicted_x, predicted_y)
        """
        # Only predict for walking/carrying animations
        if gani not in ['walk', 'carry']:
            return (x, y)
            
        # Get animation progress
        progress = self.get_animation_progress(player_id)
        
        # Calculate predicted offset based on direction
        move_distance = 0.5 * progress  # Half tile movement
        
        dx = dy = 0
        if direction == Direction.LEFT:
            dx = -move_distance
        elif direction == Direction.RIGHT:
            dx = move_distance
        elif direction == Direction.UP:
            dy = -move_distance
        elif direction == Direction.DOWN:
            dy = move_distance
            
        return (x + dx, y + dy)
        
    def cleanup_player(self, player_id: int):
        """Remove animation state for a player who left
        
        Args:
            player_id: Player ID to remove
        """
        if player_id in self.player_animations:
            del self.player_animations[player_id]
            
    def set_animation(self, player_id: int, animation: str, direction: Direction = None):
        """Set animation for a player (convenience method)
        
        Args:
            player_id: Player ID
            animation: Animation name (e.g., 'walk', 'idle')
            direction: Direction (optional, for directional animations)
        """
        # For now, just use the base animation name
        self.set_player_animation(player_id, animation)
        
    def has_animation(self, player_id: int) -> bool:
        """Check if a player has an animation state
        
        Args:
            player_id: Player ID
            
        Returns:
            True if player has animation state
        """
        return player_id in self.player_animations
        
    def update(self, dt: float):
        """Update all animations
        
        Args:
            dt: Delta time in seconds
        """
        # Update all player animations
        for player_id in list(self.player_animations.keys()):
            self.update_player_animation(player_id)
            
    def get_animation_state(self, player_id: int) -> Optional[object]:
        """Get animation state for rendering
        
        Args:
            player_id: Player ID
            
        Returns:
            Animation state with current_frame and gani_name attributes
        """
        if player_id not in self.player_animations:
            return None
            
        anim_state = self.player_animations[player_id]
        
        # Create a simple object with the required attributes
        class AnimState:
            def __init__(self, frame, gani):
                self.current_frame = frame
                self.gani_name = gani
                
        return AnimState(anim_state.frame, anim_state.gani_name)