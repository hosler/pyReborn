"""
GANI Animation Parser
====================

Parses Reborn Animation (.gani) files into structured data.
GANI files define sprite-based animations with multiple layers.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SpriteDefinition:
    """Definition of a sprite region in a sprite sheet"""
    id: int
    image_file: str
    x: int
    y: int
    width: int
    height: int
    description: str = ""


@dataclass
class AnimationFrame:
    """Single frame of animation with sprite positions"""
    sprites: List[Tuple[int, int, int]]  # List of (sprite_id, x, y)
    sounds: List[Tuple[str, float, float]] = field(default_factory=list)  # (sound_file, volume, pitch)
    duration: float = 0.05  # Default frame duration


@dataclass
class GANIAnimation:
    """Parsed GANI animation data"""
    name: str
    sprites: Dict[int, SpriteDefinition]  # sprite_id -> definition
    default_images: Dict[str, str]  # layer -> image file
    frames: List[List[AnimationFrame]]  # frames per direction (4 directions)
    loop: bool = False
    continuous: bool = False
    
    def get_direction_frames(self, direction: int) -> List[AnimationFrame]:
        """Get frames for specific direction (0=up, 1=left, 2=down, 3=right)"""
        if 0 <= direction < len(self.frames):
            frames = self.frames[direction]
            # If no frames for this direction, try to use down (2) as default
            if not frames and direction != 2 and len(self.frames) > 2:
                frames = self.frames[2]
            # If still no frames, try any direction that has frames
            if not frames:
                for d in range(len(self.frames)):
                    if self.frames[d]:
                        frames = self.frames[d]
                        break
            return frames if frames else []
        return []


class GANIParser:
    """Parser for GANI animation files"""
    
    def __init__(self):
        """Initialize GANI parser"""
        self.parsed_animations: Dict[str, GANIAnimation] = {}
    
    def parse_file(self, filepath: str) -> Optional[GANIAnimation]:
        """Parse a GANI file
        
        Args:
            filepath: Path to GANI file
            
        Returns:
            Parsed animation or None on error
        """
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            animation_name = Path(filepath).stem
            animation = self._parse_lines(lines, animation_name)
            
            if animation:
                self.parsed_animations[animation_name] = animation
                logger.info(f"Parsed GANI animation: {animation_name}")
            
            return animation
            
        except Exception as e:
            logger.error(f"Failed to parse GANI file {filepath}: {e}")
            return None
    
    def _parse_lines(self, lines: List[str], name: str) -> Optional[GANIAnimation]:
        """Parse GANI file lines
        
        Args:
            lines: File lines
            name: Animation name
            
        Returns:
            Parsed animation
        """
        sprites = {}
        default_images = {}
        frames = [[], [], [], []]  # 4 directions
        loop = False
        continuous = False
        
        current_section = None
        current_direction = 0
        current_frame_sprites = []
        current_frame_sounds = []
        
        for line in lines:
            line = line.strip()
            
            if not line:
                continue
            
            # Parse sprite definitions
            if line.startswith("SPRITE"):
                parts = line.split(None, 7)
                if len(parts) >= 7:
                    sprite = SpriteDefinition(
                        id=int(parts[1]),
                        image_file=parts[2],
                        x=int(parts[3]),
                        y=int(parts[4]),
                        width=int(parts[5]),
                        height=int(parts[6]),
                        description=parts[7] if len(parts) > 7 else ""
                    )
                    sprites[sprite.id] = sprite
            
            # Parse default images
            elif line.startswith("DEFAULT"):
                parts = line.split(None, 1)
                if len(parts) == 2:
                    layer = parts[0].replace("DEFAULT", "")
                    default_images[layer] = parts[1]
            
            # Parse animation flags
            elif line == "LOOP":
                loop = True
            elif line == "CONTINUOUS":
                continuous = True
            
            # Parse animation section
            elif line == "ANI":
                current_section = "ANI"
                current_direction = 0
                current_frame_sprites = []
            elif line == "ANIEND":
                current_section = None
                # Save last frame if any
                if current_frame_sprites:
                    frames[current_direction].append(AnimationFrame(
                        sprites=current_frame_sprites,
                        sounds=current_frame_sounds
                    ))
            
            # Parse animation frames
            elif current_section == "ANI":
                if line.startswith("PLAYSOUND"):
                    # Parse sound command
                    parts = line.split()
                    if len(parts) >= 2:
                        sound_file = parts[1]
                        volume = float(parts[2]) if len(parts) > 2 else 1.0
                        pitch = float(parts[3]) if len(parts) > 3 else 1.0
                        current_frame_sounds.append((sound_file, volume, pitch))
                else:
                    # Parse sprite positions
                    sprite_entries = self._parse_sprite_line(line)
                    
                    if sprite_entries:
                        # Check if this starts a new frame
                        if current_frame_sprites and len(sprite_entries) >= 3:
                            # Save current frame
                            frames[current_direction].append(AnimationFrame(
                                sprites=current_frame_sprites,
                                sounds=current_frame_sounds
                            ))
                            current_frame_sprites = []
                            current_frame_sounds = []
                        
                        current_frame_sprites.extend(sprite_entries)
                        
                        # Detect direction change based on sprite IDs
                        # Directions cycle through body sprites: 
                        # Up: 200-series, Left: 201-series, Down: 202-series, Right: 203-series
                        for sprite_id, _, _ in sprite_entries:
                            if sprite_id in [200, 204, 208, 212, 216, 220]:  # Up sprites
                                current_direction = 0
                            elif sprite_id in [201, 205, 209, 213, 217, 221]:  # Left sprites
                                current_direction = 1
                            elif sprite_id in [202, 206, 210, 214, 218, 222]:  # Down sprites
                                current_direction = 2
                            elif sprite_id in [203, 207, 211, 215, 219, 223]:  # Right sprites
                                current_direction = 3
        
        return GANIAnimation(
            name=name,
            sprites=sprites,
            default_images=default_images,
            frames=frames,
            loop=loop,
            continuous=continuous
        )
    
    def _parse_sprite_line(self, line: str) -> List[Tuple[int, int, int]]:
        """Parse a line containing sprite positions
        
        Args:
            line: Line with sprite data
            
        Returns:
            List of (sprite_id, x, y) tuples
        """
        sprites = []
        
        # Remove trailing comma
        line = line.rstrip(',')
        
        # Split by comma to get sprite entries
        entries = line.split(',')
        
        for entry in entries:
            entry = entry.strip()
            if not entry:
                continue
            
            # Parse sprite entry: "sprite_id x y"
            parts = entry.split()
            if len(parts) >= 3:
                try:
                    sprite_id = int(parts[0])
                    x = int(parts[1])
                    y = int(parts[2])
                    sprites.append((sprite_id, x, y))
                except ValueError:
                    continue
        
        return sprites
    
    def get_animation(self, name: str) -> Optional[GANIAnimation]:
        """Get parsed animation by name
        
        Args:
            name: Animation name
            
        Returns:
            Animation or None
        """
        return self.parsed_animations.get(name)
    
    def clear_cache(self):
        """Clear parsed animation cache"""
        self.parsed_animations.clear()


# Example usage
if __name__ == "__main__":
    parser = GANIParser()
    
    # Test parsing
    test_files = ["idle.gani", "walk.gani", "sword.gani"]
    base_path = Path(__file__).parent.parent / "assets" / "levels" / "ganis"
    
    for filename in test_files:
        filepath = base_path / filename
        if filepath.exists():
            animation = parser.parse_file(str(filepath))
            if animation:
                logger.info(f"\nAnimation: {animation.name}")
                logger.info(f"  Sprites: {len(animation.sprites)}")
                logger.info(f"  Loop: {animation.loop}")
                logger.info(f"  Continuous: {animation.continuous}")
                for i, direction_frames in enumerate(animation.frames):
                    if direction_frames:
                        logger.info(f"  Direction {i}: {len(direction_frames)} frames")