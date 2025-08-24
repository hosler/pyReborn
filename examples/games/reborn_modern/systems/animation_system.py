"""
Animation System
================

Manages sprite animations for all game entities.
Uses PyReborn's event system to trigger animations.
"""

import logging
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

import pygame


logger = logging.getLogger(__name__)


class AnimationType(Enum):
    """Types of animations"""
    IDLE = "idle"
    WALK = "walk"
    ATTACK = "attack"
    HURT = "hurt"
    GRAB = "grab"
    CARRY = "carry"
    SHOOT = "shoot"
    DEATH = "death"


@dataclass
class AnimationFrame:
    """Single frame of animation"""
    image: pygame.Surface
    duration: float  # Seconds
    offset_x: int = 0
    offset_y: int = 0


@dataclass
class Animation:
    """Complete animation sequence"""
    name: str
    frames: List[AnimationFrame]
    loop: bool = True
    
    def get_total_duration(self) -> float:
        """Get total animation duration"""
        return sum(frame.duration for frame in self.frames)


@dataclass
class AnimationState:
    """Current animation state for an entity"""
    entity_id: int
    current_animation: Optional[Animation] = None
    current_frame: int = 0
    frame_time: float = 0.0
    direction: int = 2  # 0=up, 1=left, 2=down, 3=right
    is_playing: bool = True
    queued_animation: Optional[str] = None


class AnimationSystem:
    """Manages all entity animations"""
    
    def __init__(self):
        """Initialize animation system"""
        # Animation definitions
        self.animations: Dict[str, Dict[int, Animation]] = {}  # {type: {direction: animation}}
        
        # Entity animation states
        self.entity_states: Dict[int, AnimationState] = {}
        
        # Animation callbacks
        self.animation_callbacks: Dict[str, List] = {}
        
        # Create default animations
        self._create_default_animations()
        
        logger.info("Animation system initialized")
    
    def _create_default_animations(self):
        """Create placeholder animations"""
        # For now, we'll use colored rectangles
        # In a real implementation, these would load from sprite sheets
        
        # Define colors for different animations
        colors = {
            AnimationType.IDLE: (100, 100, 200),
            AnimationType.WALK: (100, 200, 100),
            AnimationType.ATTACK: (200, 100, 100),
            AnimationType.HURT: (200, 50, 50),
            AnimationType.GRAB: (200, 200, 100),
            AnimationType.CARRY: (150, 200, 150),
            AnimationType.SHOOT: (200, 150, 100),
            AnimationType.DEATH: (100, 50, 50)
        }
        
        # Create animations for each type and direction
        for anim_type in AnimationType:
            self.animations[anim_type.value] = {}
            
            for direction in range(4):
                frames = []
                
                # Create frames based on animation type
                if anim_type == AnimationType.IDLE:
                    # Single frame for idle
                    frame = self._create_placeholder_frame(colors[anim_type], direction)
                    frames.append(AnimationFrame(frame, 1.0))
                    
                elif anim_type == AnimationType.WALK:
                    # 4 frames for walking
                    for i in range(4):
                        frame = self._create_placeholder_frame(colors[anim_type], direction, i)
                        frames.append(AnimationFrame(frame, 0.15))
                        
                elif anim_type == AnimationType.ATTACK:
                    # 3 frames for attack
                    for i in range(3):
                        frame = self._create_placeholder_frame(colors[anim_type], direction, i)
                        frames.append(AnimationFrame(frame, 0.1))
                        
                else:
                    # Default 2 frames
                    for i in range(2):
                        frame = self._create_placeholder_frame(colors[anim_type], direction, i)
                        frames.append(AnimationFrame(frame, 0.2))
                
                # Create animation
                animation = Animation(
                    name=f"{anim_type.value}_{direction}",
                    frames=frames,
                    loop=(anim_type in [AnimationType.IDLE, AnimationType.WALK, AnimationType.CARRY])
                )
                
                self.animations[anim_type.value][direction] = animation
    
    def _create_placeholder_frame(self, color: Tuple[int, int, int], direction: int, frame: int = 0) -> pygame.Surface:
        """Create a placeholder sprite frame"""
        surface = pygame.Surface((16, 24), pygame.SRCALPHA)
        
        # Base rectangle
        pygame.draw.rect(surface, color, (0, 0, 16, 24))
        
        # Direction indicator
        if direction == 0:  # Up
            pygame.draw.polygon(surface, (255, 255, 255), [(8, 2), (4, 6), (12, 6)])
        elif direction == 1:  # Left
            pygame.draw.polygon(surface, (255, 255, 255), [(2, 12), (6, 8), (6, 16)])
        elif direction == 2:  # Down
            pygame.draw.polygon(surface, (255, 255, 255), [(8, 22), (4, 18), (12, 18)])
        elif direction == 3:  # Right
            pygame.draw.polygon(surface, (255, 255, 255), [(14, 12), (10, 8), (10, 16)])
        
        # Frame indicator for multi-frame animations
        if frame > 0:
            pygame.draw.circle(surface, (255, 255, 255), (8, 12), 2 + frame)
        
        return surface
    
    def add_entity(self, entity_id: int, initial_animation: str = "idle", direction: int = 2):
        """Add entity to animation system
        
        Args:
            entity_id: Unique entity identifier
            initial_animation: Starting animation
            direction: Initial facing direction
        """
        state = AnimationState(
            entity_id=entity_id,
            direction=direction
        )
        
        self.entity_states[entity_id] = state
        self.play_animation(entity_id, initial_animation)
        
        logger.debug(f"Added entity {entity_id} to animation system")
    
    def remove_entity(self, entity_id: int):
        """Remove entity from animation system"""
        if entity_id in self.entity_states:
            del self.entity_states[entity_id]
            logger.debug(f"Removed entity {entity_id} from animation system")
    
    def play_animation(self, entity_id: int, animation_name: str, force: bool = False):
        """Play animation for entity
        
        Args:
            entity_id: Entity to animate
            animation_name: Name of animation to play
            force: Force restart even if same animation
        """
        if entity_id not in self.entity_states:
            return
        
        state = self.entity_states[entity_id]
        
        # Check if we need to change animation
        if (state.current_animation and 
            state.current_animation.name.startswith(animation_name) and 
            not force):
            return
        
        # Get animation for current direction
        if animation_name in self.animations:
            direction_anims = self.animations[animation_name]
            if state.direction in direction_anims:
                animation = direction_anims[state.direction]
                
                # Set new animation
                state.current_animation = animation
                state.current_frame = 0
                state.frame_time = 0.0
                state.is_playing = True
                
                logger.debug(f"Playing animation {animation_name} for entity {entity_id}")
                
                # Trigger callbacks
                self._trigger_callbacks(entity_id, animation_name, 'start')
    
    def stop_animation(self, entity_id: int):
        """Stop animation for entity"""
        if entity_id in self.entity_states:
            self.entity_states[entity_id].is_playing = False
    
    def set_direction(self, entity_id: int, direction: int):
        """Set entity facing direction
        
        Args:
            entity_id: Entity ID
            direction: 0=up, 1=left, 2=down, 3=right
        """
        if entity_id not in self.entity_states:
            return
        
        state = self.entity_states[entity_id]
        if state.direction != direction:
            state.direction = direction
            
            # Update animation for new direction
            if state.current_animation:
                anim_type = state.current_animation.name.split('_')[0]
                self.play_animation(entity_id, anim_type)
    
    def update(self, dt: float):
        """Update all animations
        
        Args:
            dt: Delta time in seconds
        """
        for entity_id, state in self.entity_states.items():
            if not state.is_playing or not state.current_animation:
                continue
            
            # Update frame time
            state.frame_time += dt
            
            # Check if we need to advance frame
            current_frame_obj = state.current_animation.frames[state.current_frame]
            if state.frame_time >= current_frame_obj.duration:
                state.frame_time -= current_frame_obj.duration
                state.current_frame += 1
                
                # Check if animation finished
                if state.current_frame >= len(state.current_animation.frames):
                    if state.current_animation.loop:
                        state.current_frame = 0
                        self._trigger_callbacks(entity_id, state.current_animation.name, 'loop')
                    else:
                        state.current_frame = len(state.current_animation.frames) - 1
                        state.is_playing = False
                        self._trigger_callbacks(entity_id, state.current_animation.name, 'end')
                        
                        # Play queued animation if any
                        if state.queued_animation:
                            next_anim = state.queued_animation
                            state.queued_animation = None
                            self.play_animation(entity_id, next_anim)
    
    def get_current_frame(self, entity_id: int) -> Optional[pygame.Surface]:
        """Get current animation frame for entity
        
        Returns:
            Current frame surface or None
        """
        if entity_id not in self.entity_states:
            return None
        
        state = self.entity_states[entity_id]
        if not state.current_animation or not state.current_animation.frames:
            return None
        
        frame_obj = state.current_animation.frames[state.current_frame]
        return frame_obj.image
    
    def get_frame_offset(self, entity_id: int) -> Tuple[int, int]:
        """Get current frame offset for entity
        
        Returns:
            (offset_x, offset_y) tuple
        """
        if entity_id not in self.entity_states:
            return (0, 0)
        
        state = self.entity_states[entity_id]
        if not state.current_animation or not state.current_animation.frames:
            return (0, 0)
        
        frame_obj = state.current_animation.frames[state.current_frame]
        return (frame_obj.offset_x, frame_obj.offset_y)
    
    def queue_animation(self, entity_id: int, animation_name: str):
        """Queue animation to play after current one finishes"""
        if entity_id in self.entity_states:
            self.entity_states[entity_id].queued_animation = animation_name
    
    def register_callback(self, animation_name: str, event: str, callback):
        """Register callback for animation events
        
        Args:
            animation_name: Animation to watch
            event: 'start', 'end', or 'loop'
            callback: Function to call (entity_id, animation_name)
        """
        key = f"{animation_name}_{event}"
        if key not in self.animation_callbacks:
            self.animation_callbacks[key] = []
        self.animation_callbacks[key].append(callback)
    
    def _trigger_callbacks(self, entity_id: int, animation_name: str, event: str):
        """Trigger callbacks for animation event"""
        key = f"{animation_name}_{event}"
        if key in self.animation_callbacks:
            for callback in self.animation_callbacks[key]:
                try:
                    callback(entity_id, animation_name)
                except Exception as e:
                    logger.error(f"Animation callback error: {e}")
    
    def load_sprite_sheet(self, filename: str, frame_width: int, frame_height: int) -> List[pygame.Surface]:
        """Load sprites from a sprite sheet
        
        Args:
            filename: Path to sprite sheet
            frame_width: Width of each frame
            frame_height: Height of each frame
            
        Returns:
            List of sprite surfaces
        """
        # TODO: Implement sprite sheet loading
        # This would load a sprite sheet and split it into frames
        return []