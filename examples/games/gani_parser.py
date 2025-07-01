#!/usr/bin/env python3
"""
GANI Parser - Parses Graal Animation files for sprite definitions and animations
"""

import os
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
import pygame

@dataclass
class Sprite:
    """Represents a sprite definition from GANI file"""
    id: int
    image: str
    x: int
    y: int
    width: int
    height: int
    description: str

@dataclass
class AnimationFrame:
    """Represents a single frame of animation"""
    # Each direction has its own sprite list
    sprites_by_direction: Dict[str, List[Tuple[int, int, int]]]  # direction -> [(sprite_id, x_offset, y_offset)]
    sound: Optional[Tuple[str, float, int]] = None  # (filename, volume, channel)

class GaniFile:
    """Parser for GANI animation files"""
    
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.sprites: Dict[int, Sprite] = {}
        self.animation_frames: List[AnimationFrame] = []
        self.default_images = {
            'BODY': 'body.png',
            'HEAD': 'head19.png',
            'SWORD': 'sword1.png',
            'SHIELD': 'shield1.png',
            'ATTR1': 'hat0.png',
            'SPRITES': 'sprites.png'
        }
        self.setbackto = 'idle'
        self.continuous = False
        self.loop = True
        
        self._parse()
    
    def _parse(self):
        """Parse the GANI file"""
        with open(self.filepath, 'r') as f:
            lines = f.readlines()
        
        in_ani_section = False
        current_frame_lines = []
        
        for line in lines:
            line = line.strip()
            
            if not line:
                continue
                
            if line.startswith('SPRITE'):
                # Parse sprite definition
                parts = line.split()
                if len(parts) >= 8:
                    sprite_id = int(parts[1])
                    image = parts[2]
                    x = int(parts[3])
                    y = int(parts[4])
                    width = int(parts[5])
                    height = int(parts[6])
                    description = ' '.join(parts[7:]) if len(parts) > 7 else ''
                    
                    self.sprites[sprite_id] = Sprite(
                        id=sprite_id,
                        image=image,
                        x=x,
                        y=y,
                        width=width,
                        height=height,
                        description=description
                    )
            
            elif line.startswith('DEFAULT'):
                # Parse default image assignments
                parts = line.split(None, 1)
                if len(parts) == 2:
                    key = parts[0].replace('DEFAULT', '')
                    if key == 'PARAM1':
                        key = 'SWORD'  # Special case for sword
                    self.default_images[key] = parts[1]
            
            elif line == 'ANI':
                in_ani_section = True
                
            elif line == 'ANIEND':
                in_ani_section = False
                if current_frame_lines:
                    self._parse_animation_frame(current_frame_lines)
                    current_frame_lines = []
                    
            elif in_ani_section:
                if line.startswith('PLAYSOUND'):
                    # PLAYSOUND comes after a frame, add to the frame we just parsed
                    parts = line.split()
                    if len(parts) >= 4:
                        sound_file = parts[1]
                        volume = float(parts[2])
                        channel = int(parts[3])
                        # Add to the frame we just completed
                        if self.animation_frames:
                            self.animation_frames[-1].sound = (sound_file, volume, channel)
                else:
                    # Collect lines for current frame
                    current_frame_lines.append(line)
                    # Check if this completes a frame (4 direction lines)
                    if len(current_frame_lines) == 4:
                        self._parse_animation_frame(current_frame_lines)
                        current_frame_lines = []
            
            elif line.startswith('SETBACKTO'):
                parts = line.split()
                if len(parts) >= 2:
                    self.setbackto = parts[1]
                    
            elif line == 'CONTINUOUS':
                self.continuous = True
                
            elif line == 'LOOP':
                self.loop = True
    
    def _parse_animation_frame(self, lines: List[str]):
        """Parse a single animation frame (4 direction lines)"""
        directions = ['up', 'left', 'down', 'right']
        sprites_by_direction = {}
        
        # Each line represents a direction (up, left, down, right)
        for i, line in enumerate(lines):
            if i >= len(directions):
                break
                
            direction = directions[i]
            sprites = []
            
            # Parse sprite placements
            # Format: sprite_id x y, sprite_id x y, ...
            parts = line.split(',')
            for part in parts:
                numbers = part.strip().split()
                if len(numbers) >= 3:
                    try:
                        sprite_id = int(numbers[0])
                        x_offset = int(numbers[1])
                        y_offset = int(numbers[2])
                        sprites.append((sprite_id, x_offset, y_offset))
                    except ValueError:
                        pass
                        
            sprites_by_direction[direction] = sprites
        
        frame = AnimationFrame(sprites_by_direction=sprites_by_direction)
        self.animation_frames.append(frame)
    
    def get_sprite_surface(self, sprite_id: int, image_cache: Dict[str, pygame.Surface]) -> Optional[pygame.Surface]:
        """Get a pygame surface for a specific sprite ID"""
        if sprite_id not in self.sprites:
            return None
            
        sprite = self.sprites[sprite_id]
        
        # Get the base image
        image_key = sprite.image
        if image_key in self.default_images:
            image_key = self.default_images[image_key]
            
        if image_key not in image_cache:
            return None
            
        base_image = image_cache[image_key]
        
        # Extract the sprite region
        rect = pygame.Rect(sprite.x, sprite.y, sprite.width, sprite.height)
        if (rect.right <= base_image.get_width() and 
            rect.bottom <= base_image.get_height()):
            return base_image.subsurface(rect).copy()
            
        return None
    
    def get_sprites_for_direction(self, direction: str) -> Dict[str, List[Sprite]]:
        """Get all sprites organized by type for a given direction"""
        # Map direction to sprite ID ranges based on GANI conventions
        dir_offset = {
            'up': 0,
            'left': 1,
            'down': 2,
            'right': 3
        }.get(direction.lower(), 2)
        
        result = {
            'body': [],
            'head': [],
            'sword': [],
            'shield': [],
            'hat': []
        }
        
        for sprite_id, sprite in self.sprites.items():
            # Categorize sprites by ID range
            if 200 <= sprite_id < 300:  # Body sprites
                result['body'].append(sprite)
            elif 100 <= sprite_id < 200:  # Head sprites
                result['head'].append(sprite)
            elif 20 <= sprite_id < 40:  # Sword sprites
                result['sword'].append(sprite)
            elif 10 <= sprite_id < 20:  # Shield sprites
                result['shield'].append(sprite)
            elif 40 <= sprite_id < 50:  # Hat sprites
                result['hat'].append(sprite)
                
        return result
    
    def get_frame_sprites(self, frame: int, direction: str) -> List[Tuple[int, int, int]]:
        """Get sprite placements for a specific frame and direction
        
        Returns list of (sprite_id, x_offset, y_offset) tuples
        """
        if frame >= len(self.animation_frames):
            # Loop animation or return empty
            if self.loop and self.animation_frames:
                frame = frame % len(self.animation_frames)
            else:
                return []
                
        anim_frame = self.animation_frames[frame]
        return anim_frame.sprites_by_direction.get(direction.lower(), [])


class GaniManager:
    """Manages loading and caching of GANI files"""
    
    def __init__(self, base_path: str):
        self.base_path = base_path
        self.gani_cache: Dict[str, GaniFile] = {}
        self.image_cache: Dict[str, pygame.Surface] = {}
        
    def load_gani(self, name: str) -> Optional[GaniFile]:
        """Load a GANI file by name"""
        if name in self.gani_cache:
            return self.gani_cache[name]
            
        # Try to load the file
        gani_path = os.path.join(self.base_path, 'assets', 'levels', 'ganis', f'{name}.gani')
        if os.path.exists(gani_path):
            try:
                gani = GaniFile(gani_path)
                self.gani_cache[name] = gani
                return gani
            except Exception as e:
                print(f"Failed to load GANI {name}: {e}")
                
        return None
    
    def load_image(self, filename: str) -> Optional[pygame.Surface]:
        """Load an image file"""
        if filename in self.image_cache:
            return self.image_cache[filename]
            
        # Try different paths
        search_paths = [
            os.path.join(self.base_path, 'assets', 'levels', 'bodies', filename),
            os.path.join(self.base_path, 'assets', 'levels', 'heads', filename),
            os.path.join(self.base_path, 'assets', 'levels', 'swords', filename),
            os.path.join(self.base_path, 'assets', 'levels', 'shields', filename),
            os.path.join(self.base_path, 'assets', 'levels', 'hats', filename),
            os.path.join(self.base_path, 'assets', filename),
        ]
        
        for path in search_paths:
            if os.path.exists(path):
                try:
                    image = pygame.image.load(path).convert_alpha()
                    self.image_cache[filename] = image
                    return image
                except Exception as e:
                    print(f"Failed to load image {filename}: {e}")
                    
        return None
    
    def get_sprite_surface(self, gani_name: str, sprite_id: int) -> Optional[pygame.Surface]:
        """Get a sprite surface from a GANI file"""
        gani = self.load_gani(gani_name)
        if not gani:
            return None
            
        # Ensure required images are loaded
        for image_type, image_name in gani.default_images.items():
            self.load_image(image_name)
            
        return gani.get_sprite_surface(sprite_id, self.image_cache)