"""
GANI Animation System
====================

Manages GANI-based animations with sprite sheet loading and multi-layer rendering.
"""

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

import pygame

from .gani_parser import GANIParser, GANIAnimation, SpriteDefinition

logger = logging.getLogger(__name__)


@dataclass
class LoadedSprite:
    """A sprite loaded from a sprite sheet"""
    surface: pygame.Surface
    source_rect: pygame.Rect
    sprite_def: SpriteDefinition


@dataclass
class GANIAnimationState:
    """Current state of a GANI animation"""
    animation: GANIAnimation
    direction: int = 2  # 0=up, 1=left, 2=down, 3=right
    current_frame: int = 0
    frame_time: float = 0.0
    is_playing: bool = True
    loaded_sprites: Dict[int, LoadedSprite] = None
    
    def __post_init__(self):
        if self.loaded_sprites is None:
            self.loaded_sprites = {}


class GANIAnimationSystem:
    """System for managing GANI animations"""
    
    def __init__(self, assets_path: str):
        """Initialize GANI animation system
        
        Args:
            assets_path: Base path to game assets
        """
        self.assets_path = Path(assets_path)
        self.ganis_path = self.assets_path / "levels" / "ganis"
        
        # Parsers and caches
        self.parser = GANIParser()
        self.loaded_animations: Dict[str, GANIAnimation] = {}
        self.sprite_sheets: Dict[str, pygame.Surface] = {}
        
        # Entity animation states
        self.entity_states: Dict[int, GANIAnimationState] = {}
        
        # Default frame duration in seconds
        self.default_frame_duration = 0.05
        
        logger.info(f"GANI animation system initialized with assets at {assets_path}")
    
    def load_animation(self, animation_name: str) -> Optional[GANIAnimation]:
        """Load a GANI animation
        
        Args:
            animation_name: Name of animation (without .gani extension)
            
        Returns:
            Loaded animation or None
        """
        # Check cache first
        if animation_name in self.loaded_animations:
            return self.loaded_animations[animation_name]
        
        # Parse GANI file
        gani_path = self.ganis_path / f"{animation_name}.gani"
        if not gani_path.exists():
            logger.warning(f"GANI file not found: {gani_path}")
            return None
        
        animation = self.parser.parse_file(str(gani_path))
        if animation:
            self.loaded_animations[animation_name] = animation
            
        return animation
    
    def load_sprite_sheet(self, image_file: str) -> Optional[pygame.Surface]:
        """Load a sprite sheet image
        
        Args:
            image_file: Image filename
            
        Returns:
            Loaded surface or None
        """
        # Check cache first
        if image_file in self.sprite_sheets:
            return self.sprite_sheets[image_file]
        
        # Try different paths
        search_paths = [
            self.assets_path / "levels" / "bodies" / image_file,
            self.assets_path / "levels" / "heads" / image_file,
            self.assets_path / "levels" / "shields" / image_file,
            self.assets_path / "levels" / "hats" / image_file,
            self.assets_path / "levels" / "ganis" / image_file,
            self.assets_path / image_file,
        ]
        
        # Special handling for some common sprite sheets that might be layer names
        if image_file.upper() == "SPRITES":
            search_paths.insert(0, self.assets_path / "sprites.png")
        elif image_file.upper() == "SHIELD":
            # Try to find a default shield image (no-shield for unequipped)
            search_paths.insert(0, self.assets_path / "levels" / "shields" / "no-shield.png")
        elif image_file.upper() == "SWORD":
            # Try to find a default sword image
            search_paths.insert(0, self.assets_path / "levels" / "swords" / "sword1.png")
        
        logger.debug(f"Searching for sprite sheet: {image_file}")
        for path in search_paths:
            if path.exists():
                try:
                    surface = pygame.image.load(str(path)).convert_alpha()
                    self.sprite_sheets[image_file] = surface
                    logger.info(f"Loaded sprite sheet: {image_file} from {path}")
                    return surface
                except Exception as e:
                    logger.error(f"Failed to load sprite sheet {path}: {e}")
        
        logger.warning(f"Sprite sheet not found: {image_file} (searched {len(search_paths)} paths)")
        return None
    
    def set_entity_animation(self, entity_id: int, animation_name: str, 
                           direction: Optional[int] = None, force: bool = False):
        """Set animation for an entity
        
        Args:
            entity_id: Entity ID
            animation_name: Animation name
            direction: Optional direction override
            force: Force restart animation
        """
        # Check if already playing same animation
        if entity_id in self.entity_states:
            state = self.entity_states[entity_id]
            if (state.animation.name == animation_name and 
                not force and direction is None):
                return
        
        # Load animation
        animation = self.load_animation(animation_name)
        if not animation:
            return
        
        # Create or update state
        if entity_id in self.entity_states:
            state = self.entity_states[entity_id]
            state.animation = animation
            state.current_frame = 0
            state.frame_time = 0.0
            state.is_playing = True
            if direction is not None:
                state.direction = direction
        else:
            state = GANIAnimationState(
                animation=animation,
                direction=direction if direction is not None else 2
            )
            self.entity_states[entity_id] = state
        
        # Load sprites for this animation
        self._load_animation_sprites(state)
        
        logger.debug(f"Set animation {animation_name} for entity {entity_id}")
    
    def _load_animation_sprites(self, state: GANIAnimationState):
        """Load all sprites needed for an animation
        
        Args:
            state: Animation state to load sprites for
        """
        state.loaded_sprites.clear()
        
        # Map layer names to their default images
        layer_to_image = {}
        for layer, image_file in state.animation.default_images.items():
            layer_to_image[layer] = image_file
        
        # Get unique image files from sprite definitions
        # The sprite_def.image_file is actually the layer name (e.g., "HEAD", "BODY")
        # We need to map it to the actual image file using the default images
        image_files = set()
        for sprite_def in state.animation.sprites.values():
            # Get the actual image file from the layer name
            layer_name = sprite_def.image_file
            if layer_name in layer_to_image:
                actual_image = layer_to_image[layer_name]
                image_files.add(actual_image)
            else:
                # Some layers like "SPRITES" might not have a default image
                # Skip these for now
                logger.debug(f"No default image for layer: {layer_name}")
        
        # Load sprite sheets
        sprite_sheets = {}
        layer_to_sheet = {}  # Map layer names to loaded sheets
        
        for image_file in image_files:
            sheet = self.load_sprite_sheet(image_file)
            if sheet:
                sprite_sheets[image_file] = sheet
                # Map each layer to its loaded sheet
                for layer, img in layer_to_image.items():
                    if img == image_file:
                        layer_to_sheet[layer] = sheet
        
        # Extract sprites from sheets
        for sprite_id, sprite_def in state.animation.sprites.items():
            # Get the sheet for this sprite's layer
            layer_name = sprite_def.image_file
            sheet = None
            
            if layer_name in layer_to_sheet:
                sheet = layer_to_sheet[layer_name]
            elif layer_name in sprite_sheets:
                sheet = sprite_sheets[layer_name]
            
            if sheet:
                # Extract sprite region
                rect = pygame.Rect(
                    sprite_def.x, sprite_def.y,
                    sprite_def.width, sprite_def.height
                )
                
                # Create sprite surface
                sprite_surface = pygame.Surface(
                    (sprite_def.width, sprite_def.height),
                    pygame.SRCALPHA
                )
                sprite_surface.blit(sheet, (0, 0), rect)
                
                state.loaded_sprites[sprite_id] = LoadedSprite(
                    surface=sprite_surface,
                    source_rect=rect,
                    sprite_def=sprite_def
                )
    
    def set_entity_direction(self, entity_id: int, direction: int):
        """Set entity facing direction
        
        Args:
            entity_id: Entity ID
            direction: 0=up, 1=left, 2=down, 3=right
        """
        if entity_id in self.entity_states:
            state = self.entity_states[entity_id]
            if state.direction != direction:
                logger.info(f"Entity {entity_id} direction changed: {state.direction} -> {direction}")
                state.direction = direction
                # Reset to first frame of new direction
                state.current_frame = 0
                state.frame_time = 0.0
    
    def update(self, dt: float):
        """Update all animations
        
        Args:
            dt: Delta time in seconds
        """
        for entity_id, state in self.entity_states.items():
            if not state.is_playing:
                continue
            
            # Get frames for current direction
            frames = state.animation.get_direction_frames(state.direction)
            if not frames:
                continue
            
            # Update frame time
            state.frame_time += dt
            
            # Check if we need to advance frame
            frame_duration = self.default_frame_duration
            if state.frame_time >= frame_duration:
                state.frame_time -= frame_duration
                state.current_frame += 1
                
                # Check if animation finished
                if state.current_frame >= len(frames):
                    if state.animation.loop or state.animation.continuous:
                        state.current_frame = 0
                    else:
                        state.current_frame = len(frames) - 1
                        state.is_playing = False
                
                # Play frame sounds if any
                current_frame = frames[state.current_frame]
                for sound_file, volume, pitch in current_frame.sounds:
                    # TODO: Integrate with audio system
                    logger.debug(f"Play sound: {sound_file} (volume={volume}, pitch={pitch})")
    
    def render_entity(self, entity_id: int, screen: pygame.Surface, 
                     x: int, y: int, camera_x: int = 0, camera_y: int = 0):
        """Render entity animation
        
        Args:
            entity_id: Entity to render
            screen: Surface to render to
            x: Entity X position
            y: Entity Y position
            camera_x: Camera X offset
            camera_y: Camera Y offset
        """
        if entity_id not in self.entity_states:
            return
        
        state = self.entity_states[entity_id]
        frames = state.animation.get_direction_frames(state.direction)
        if not frames or state.current_frame >= len(frames):
            return
        
        # Get current frame
        frame = frames[state.current_frame]
        
        # Render each sprite in the frame
        for sprite_id, offset_x, offset_y in frame.sprites:
            if sprite_id in state.loaded_sprites:
                sprite = state.loaded_sprites[sprite_id]
                
                # Calculate render position
                render_x = x + offset_x - camera_x
                render_y = y + offset_y - camera_y
                
                # Render sprite
                screen.blit(sprite.surface, (render_x, render_y))
    
    def get_entity_bounds(self, entity_id: int) -> Optional[pygame.Rect]:
        """Get bounding box for entity animation
        
        Args:
            entity_id: Entity ID
            
        Returns:
            Bounding rectangle or None
        """
        if entity_id not in self.entity_states:
            return None
        
        state = self.entity_states[entity_id]
        frames = state.animation.get_direction_frames(state.direction)
        if not frames or state.current_frame >= len(frames):
            return None
        
        # Calculate bounds from all sprites in current frame
        min_x, min_y = float('inf'), float('inf')
        max_x, max_y = float('-inf'), float('-inf')
        
        frame = frames[state.current_frame]
        for sprite_id, offset_x, offset_y in frame.sprites:
            if sprite_id in state.loaded_sprites:
                sprite = state.loaded_sprites[sprite_id]
                min_x = min(min_x, offset_x)
                min_y = min(min_y, offset_y)
                max_x = max(max_x, offset_x + sprite.sprite_def.width)
                max_y = max(max_y, offset_y + sprite.sprite_def.height)
        
        if min_x == float('inf'):
            return None
        
        return pygame.Rect(min_x, min_y, max_x - min_x, max_y - min_y)
    
    def remove_entity(self, entity_id: int):
        """Remove entity from animation system
        
        Args:
            entity_id: Entity to remove
        """
        if entity_id in self.entity_states:
            del self.entity_states[entity_id]
    
    def clear_cache(self):
        """Clear all cached data"""
        self.loaded_animations.clear()
        self.sprite_sheets.clear()
        self.parser.clear_cache()