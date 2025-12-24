"""
pyreborn - GANI animation parser and animation system.

Parses GANI animation (.gani) files and provides an animation state machine
for rendering animated sprites.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Callable
import re


@dataclass
class GaniSprite:
    """Definition of a sprite within a sprite sheet."""
    id: int
    layer: str  # BODY, HEAD, SWORD, SHIELD, ATTR1, SPRITES, etc.
    x: int      # Source X in sprite sheet
    y: int      # Source Y in sprite sheet
    width: int
    height: int
    description: str = ""


@dataclass
class GaniFrame:
    """A single animation frame with sprite placements and optional sound."""
    sprites: List[Tuple[int, int, int]]  # [(sprite_id, offset_x, offset_y), ...]
    sound: Optional[Tuple[str, float, float]] = None  # (filename, volume, pitch)


@dataclass
class Gani:
    """Parsed GANI animation data."""
    name: str
    sprites: Dict[int, GaniSprite] = field(default_factory=dict)
    defaults: Dict[str, str] = field(default_factory=dict)  # layer -> image filename
    directions: List[List[GaniFrame]] = field(default_factory=list)  # [direction][frame]
    loops: bool = False
    continuous: bool = False
    setback: Optional[str] = None
    single_dir: bool = False  # True if only one direction defined

    def get_frame(self, direction: int, frame_index: int) -> Optional[GaniFrame]:
        """Get a specific frame for a direction."""
        if not self.directions:
            return None
        # Handle single-direction animations
        dir_idx = 0 if self.single_dir else min(direction, len(self.directions) - 1)
        if dir_idx >= len(self.directions):
            return None
        frames = self.directions[dir_idx]
        if not frames:
            return None
        frame_idx = frame_index % len(frames) if self.loops else min(frame_index, len(frames) - 1)
        return frames[frame_idx]

    def get_frame_count(self, direction: int = 0) -> int:
        """Get number of frames for a direction."""
        if not self.directions:
            return 0
        dir_idx = 0 if self.single_dir else min(direction, len(self.directions) - 1)
        if dir_idx >= len(self.directions):
            return 0
        return len(self.directions[dir_idx])


class GaniParser:
    """Parser for GANI animation files."""

    def __init__(self, search_paths: Optional[List[Path]] = None):
        """Initialize parser with optional search paths for gani files."""
        self.search_paths = search_paths or []
        self.cache: Dict[str, Gani] = {}

    def add_search_path(self, path: Path):
        """Add a search path for finding gani files."""
        if path not in self.search_paths:
            self.search_paths.append(path)

    def find_file(self, name: str) -> Optional[Path]:
        """Find a gani file by name in search paths."""
        # Add .gani extension if not present
        if not name.endswith('.gani'):
            name = name + '.gani'

        for search_path in self.search_paths:
            # Check direct path
            full_path = search_path / name
            if full_path.exists():
                return full_path
            # Check in ganis subdirectory
            ganis_path = search_path / "ganis" / name
            if ganis_path.exists():
                return ganis_path

        return None

    def parse(self, name: str) -> Optional[Gani]:
        """Parse a gani file by name, using cache if available."""
        # Check cache
        cache_key = name.replace('.gani', '')
        if cache_key in self.cache:
            return self.cache[cache_key]

        # Find file
        file_path = self.find_file(name)
        if not file_path:
            return None

        # Parse file
        gani = self.parse_file(file_path)
        if gani:
            self.cache[cache_key] = gani
        return gani

    def parse_file(self, file_path: Path) -> Optional[Gani]:
        """Parse a gani file from a path."""
        try:
            with open(file_path, 'r', encoding='latin-1') as f:
                content = f.read()
            return self.parse_content(content, file_path.stem)
        except Exception as e:
            print(f"Error parsing gani {file_path}: {e}")
            return None

    def parse_content(self, content: str, name: str = "unknown") -> Gani:
        """
        Parse gani content from a string.

        GANI format notes:
        - In the ANI section, lines are grouped by direction (4 lines = 4 directions)
        - Each group of 4 lines represents all directions for one frame
        - Blank lines separate frame groups
        - PLAYSOUND applies to the NEXT frame group
        """
        gani = Gani(name=name)
        lines = content.split('\n')

        in_ani = False
        frame_lines: List[str] = []  # Collect lines for current frame group
        pending_sound: Optional[Tuple[str, float, float]] = None

        # We'll collect frames per direction
        direction_frames: Dict[int, List[GaniFrame]] = {0: [], 1: [], 2: [], 3: []}

        def process_frame_group():
            """Process collected frame lines as one frame for each direction."""
            nonlocal frame_lines, pending_sound

            if not frame_lines:
                return

            # Each line in the group is one direction (0, 1, 2, 3)
            for dir_idx, line in enumerate(frame_lines[:4]):  # Max 4 directions
                frame = self._parse_frame_line(line)
                if frame:
                    # First frame in group gets the pending sound
                    if dir_idx == 0 and pending_sound:
                        frame.sound = pending_sound
                    direction_frames[dir_idx].append(frame)

            frame_lines = []
            pending_sound = None

        for line in lines:
            line = line.strip()

            # Skip empty lines outside ANI section
            if not line and not in_ani:
                continue

            # Parse SPRITE definitions
            if line.startswith('SPRITE'):
                sprite = self._parse_sprite_line(line)
                if sprite:
                    gani.sprites[sprite.id] = sprite
                continue

            # Parse DEFAULT layer mappings
            if line.startswith('DEFAULT'):
                match = re.match(r'DEFAULT(\w+)\s+(.+)', line)
                if match:
                    layer = match.group(1).upper()
                    filename = match.group(2).strip()
                    gani.defaults[layer] = filename
                continue

            # Parse animation flags
            if line == 'LOOP':
                gani.loops = True
                continue
            if line == 'CONTINUOUS':
                gani.continuous = True
                continue
            if line.startswith('SETBACKTO'):
                parts = line.split(None, 1)
                if len(parts) > 1:
                    gani.setback = parts[1].strip()
                continue

            # Start of animation data
            if line == 'ANI':
                in_ani = True
                frame_lines = []
                direction_frames = {0: [], 1: [], 2: [], 3: []}
                continue

            # End of animation data
            if line == 'ANIEND':
                in_ani = False
                # Process any remaining frame lines
                process_frame_group()
                # Convert to direction list
                gani.directions = [direction_frames[i] for i in range(4)]
                continue

            # Parse content inside ANI section
            if in_ani:
                # Sound effect - applies to next frame group
                if line.startswith('PLAYSOUND'):
                    parts = line.split()
                    if len(parts) >= 4:
                        try:
                            sound_file = parts[1]
                            volume = float(parts[2])
                            pitch = float(parts[3])
                            pending_sound = (sound_file, volume, pitch)
                        except (ValueError, IndexError):
                            pass
                    continue

                # Blank line = frame group separator
                if not line:
                    process_frame_group()
                    continue

                # Collect frame line
                frame_lines.append(line)

                # If we have 4 lines, process them as a complete frame group
                if len(frame_lines) == 4:
                    process_frame_group()

        # Check if all directions have same frame count
        frame_counts = [len(direction_frames[i]) for i in range(4)]
        gani.single_dir = all(c == 0 for c in frame_counts[1:]) and frame_counts[0] > 0

        return gani

    def _parse_sprite_line(self, line: str) -> Optional[GaniSprite]:
        """Parse a SPRITE definition line."""
        # SPRITE <id> <layer> <x> <y> <w> <h> [description]
        parts = line.split()
        if len(parts) < 7:
            return None
        try:
            sprite_id = int(parts[1])
            layer = parts[2].upper()
            x = int(parts[3])
            y = int(parts[4])
            width = int(parts[5])
            height = int(parts[6])
            description = ' '.join(parts[7:]) if len(parts) > 7 else ""
            return GaniSprite(sprite_id, layer, x, y, width, height, description)
        except (ValueError, IndexError):
            return None

    def _parse_frame_line(self, line: str) -> Optional[GaniFrame]:
        """Parse a frame line with sprite placements."""
        # Format: <sprite_id> <offset_x> <offset_y>[, <sprite_id> <offset_x> <offset_y>]...
        sprites = []

        # Split by comma for multiple sprite placements
        parts = line.split(',')
        for part in parts:
            part = part.strip()
            if not part:
                continue

            # Parse individual sprite placement
            tokens = part.split()
            if len(tokens) >= 3:
                try:
                    sprite_id = int(tokens[0])
                    offset_x = int(tokens[1])
                    offset_y = int(tokens[2])
                    sprites.append((sprite_id, offset_x, offset_y))
                except ValueError:
                    continue

        if sprites:
            return GaniFrame(sprites=sprites)
        return None


class AnimationState:
    """Manages the state of an animation for an entity."""

    FRAME_DURATION = 0.05  # 20 FPS animation rate

    def __init__(self, gani_parser: GaniParser):
        self.parser = gani_parser
        self.gani: Optional[Gani] = None
        self.direction: int = 2  # Default facing down
        self.frame: int = 0
        self.frame_time: float = 0.0
        self.playing: bool = True
        self.finished: bool = False
        self._pending_sounds: List[Tuple[str, float, float]] = []

    def set_animation(self, name: str, direction: Optional[int] = None, force: bool = False):
        """Set the current animation by name."""
        # Don't restart same animation unless forced
        if not force and self.gani and self.gani.name == name:
            if direction is not None and direction != self.direction:
                self.direction = direction
            return

        gani = self.parser.parse(name)
        if gani:
            self.gani = gani
            self.frame = 0
            self.frame_time = 0.0
            self.playing = True
            self.finished = False
            if direction is not None:
                self.direction = direction
            # Check for sound on first frame
            frame_data = self.gani.get_frame(self.direction, 0)
            if frame_data and frame_data.sound:
                self._pending_sounds.append(frame_data.sound)

    def set_direction(self, direction: int):
        """Set the facing direction (0=up, 1=left, 2=down, 3=right)."""
        if 0 <= direction <= 3:
            self.direction = direction

    def update(self, dt: float) -> List[Tuple[str, float, float]]:
        """
        Update animation state, returns list of sounds to play.

        Args:
            dt: Delta time in seconds

        Returns:
            List of (sound_file, volume, pitch) tuples
        """
        sounds = list(self._pending_sounds)
        self._pending_sounds.clear()

        if not self.gani or not self.playing or self.finished:
            return sounds

        self.frame_time += dt
        frame_count = self.gani.get_frame_count(self.direction)

        if frame_count == 0:
            return sounds

        # Advance frames based on time
        while self.frame_time >= self.FRAME_DURATION:
            self.frame_time -= self.FRAME_DURATION
            old_frame = self.frame
            self.frame += 1

            # Check if animation ended
            if self.frame >= frame_count:
                if self.gani.loops or self.gani.continuous:
                    self.frame = 0
                else:
                    self.frame = frame_count - 1
                    self.finished = True
                    self.playing = False
                    break

            # Get sound for new frame
            if self.frame != old_frame:
                frame_data = self.gani.get_frame(self.direction, self.frame)
                if frame_data and frame_data.sound:
                    sounds.append(frame_data.sound)

        return sounds

    def get_frame(self) -> Optional[GaniFrame]:
        """Get the current frame data."""
        if not self.gani:
            return None
        return self.gani.get_frame(self.direction, self.frame)

    def get_setback(self) -> Optional[str]:
        """Get the setback animation name if animation is finished."""
        if self.finished and self.gani and self.gani.setback:
            return self.gani.setback
        return None

    def is_finished(self) -> bool:
        """Check if a non-looping animation has finished."""
        return self.finished

    def reset(self):
        """Reset animation to first frame."""
        self.frame = 0
        self.frame_time = 0.0
        self.finished = False
        self.playing = True


# Utility functions for common animation needs

def direction_from_delta(dx: float, dy: float) -> int:
    """Convert movement delta to direction (0=up, 1=left, 2=down, 3=right)."""
    if abs(dy) > abs(dx):
        return 0 if dy < 0 else 2
    elif dx != 0:
        return 1 if dx < 0 else 3
    return 2  # Default to down


def direction_name(direction: int) -> str:
    """Get human-readable direction name."""
    return ["up", "left", "down", "right"][direction] if 0 <= direction <= 3 else "unknown"
