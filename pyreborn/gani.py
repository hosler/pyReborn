"""
pyreborn - GANI animation parser and animation system.

Parses GANI animation (.gani) files and provides an animation state machine
for rendering animated sprites.
"""

from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union, Callable
import re

# Bound on GaniParser.cache - same LRU-eviction idea as render_world.py's
# per-segment surface cache and sprites.py's sheet/sprite caches. A real
# session's distinct ganis (player/NPC/baddy/weapon animations) rarely
# exceeds a few hundred, but nothing stops a long crawl through many custom
# NPCs/weapons from growing this unbounded otherwise.
_MAX_CACHED_GANIS = 500


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
    # [(sprite_id, offset_x, offset_y), ...]. sprite_id is normally an int,
    # but may be a "PARAM1".."PARAM5" string token (see _parse_frame_line).
    sprites: List[Tuple[Union[int, str], int, int]]
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
    # True if the file has an embedded SCRIPT...SCRIPTEND block (the classic
    # Graal "special-effect gani" convention: an NPC-like script drives the
    # real visual via showimg, and the ANI section itself is a near-blank
    # placeholder). This engine doesn't run gani-embedded scripts, so callers
    # that show one of these (see _render_showani_rec) fall back to a
    # synthesized effect rather than the frame data, which draws almost
    # nothing on its own.
    has_script: bool = False

    def get_frame(self, direction: int, frame_index: int) -> Optional[GaniFrame]:
        """Get a specific frame for a direction."""
        if not self.directions:
            return None
        # Handle single-direction animations (direction may arrive as a float
        # from GS1 `dir=N`; it indexes a list, so force int)
        dir_idx = 0 if self.single_dir else min(int(direction), len(self.directions) - 1)
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
        self.cache: "OrderedDict[str, Gani]" = OrderedDict()

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

    def put_cache(self, name: str, gani: Optional[Gani]):
        """Store a parsed gani under `name` (bare, no .gani suffix expected)
        and evict the least-recently-used entry if that pushes the cache over
        _MAX_CACHED_GANIS. Used both by parse() below and by callers that
        parse server-streamed gani bytes directly (game/setup.py's on_file)."""
        self.cache[name] = gani
        while len(self.cache) > _MAX_CACHED_GANIS:
            self.cache.popitem(last=False)

    def parse(self, name: str) -> Optional[Gani]:
        """Parse a gani file by name, using cache if available."""
        # Check cache
        cache_key = name.replace('.gani', '')
        if cache_key in self.cache:
            self.cache.move_to_end(cache_key)
            return self.cache[cache_key]

        # Find file
        file_path = self.find_file(name)
        if not file_path:
            return None

        # Parse file
        gani = self.parse_file(file_path)
        if gani:
            self.put_cache(cache_key, gani)
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
        in_script = False
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
                    # PLAYSOUND applies to this whole frame group. Since a gani
                    # only ever plays one direction at a time, attach the sound
                    # to every direction's frame so it fires no matter which way
                    # the player is facing (not just direction 0 / up).
                    if pending_sound:
                        frame.sound = pending_sound
                    direction_frames[dir_idx].append(frame)

            frame_lines = []
            pending_sound = None

        for line in lines:
            line = line.strip()

            # Skip empty lines outside ANI section
            if not line and not in_ani:
                continue

            # An embedded SCRIPT...SCRIPTEND block (lights, particle effects,
            # etc. drive their real visual this way, with the ANI section
            # left as a near-blank placeholder). We don't execute gani-embedded
            # scripts, so just flag the gani and skip the body wholesale -
            # its GS1-ish syntax would otherwise be misread as ANI/SPRITE data.
            if line == 'SCRIPT':
                in_script = True
                gani.has_script = True
                continue
            if line == 'SCRIPTEND':
                in_script = False
                continue
            if in_script:
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

        # An embedded SCRIPT usually means the ANI section is a near-blank
        # placeholder and the script paints the real visual via showimg (we
        # don't run gani scripts, so _render_showani_rec substitutes a
        # synthesized effect for has_script ganis). But some stock ganis
        # carry REAL art in their frames and use the script only for
        # decoration — the classic pet ganis (pet-minichoc*/pet-eye-*) draw
        # the pet body in ANI frames and script only the floating nickname
        # text. Keep has_script (=> fallback) only when the frames place
        # nothing visually meaningful: the largest placed sprite below 8x8 px
        # (eye_bomber_expl's whole ANI is one 2x2 credits pixel) reads as
        # blank; anything bigger is real art that must win over the fallback.
        if gani.has_script:
            biggest = 0
            for frames in gani.directions:
                for fr in frames:
                    for sid, _ox, _oy in fr.sprites:
                        spr = gani.sprites.get(sid) if isinstance(sid, int) else None
                        if spr is not None:
                            biggest = max(biggest, spr.width * spr.height)
            if biggest >= 64:
                gani.has_script = False

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
                    sprite_id: object = int(tokens[0])
                except ValueError:
                    # Not a literal id - a "PARAMn" token substitutes whatever
                    # sprite id the showani/setani call passed as its Nth extra
                    # arg (e.g. Bomber Arena's bomb gani picks its body/decal
                    # this way so DrawBomb() can recolor/animate it per-bomb).
                    # Keep the token itself; resolved against the caller's
                    # params dict at render time (see _render_animated_entity).
                    if re.match(r'^PARAM\d+$', tokens[0], re.IGNORECASE):
                        sprite_id = tokens[0].upper()
                    else:
                        continue
                try:
                    offset_x = int(tokens[1])
                    offset_y = int(tokens[2])
                except ValueError:
                    continue
                sprites.append((sprite_id, offset_x, offset_y))

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
        # Tier 2c: per-INSTANCE memory of where a CONTINUOUS gani was left off,
        # so switching away (e.g. "walk" -> "sword") and back resumes the walk
        # cycle instead of restarting it at frame 0. Keyed by gani name; kept
        # on the AnimationState instance itself (never shared across entities)
        # to avoid the shared-playback-state bug the C# client has.
        self._continuous_state: Dict[str, Tuple[int, float]] = {}
        # Optional name mapper applied to every set_animation() call — the
        # local player's state wires this to GS1 `replaceani` (walk ->
        # eye_bomber_walk0 etc.); NPC/other-player states leave it None.
        self.name_resolver = None

    def set_animation(self, name: str, direction: Optional[int] = None, force: bool = False):
        """Set the current animation by name."""
        if self.name_resolver is not None:
            try:
                name = self.name_resolver(name) or name
            except Exception:
                pass
        # GS1 scripts set `dir` as a float (e.g. `dir = 2` -> 2.0); the frame
        # tables are indexed by int, so coerce here for every caller.
        if direction is not None:
            try:
                direction = int(direction) & 3
            except (TypeError, ValueError):
                direction = 0
        # Don't restart same animation unless forced
        if not force and self.gani and self.gani.name == name:
            if direction is not None and direction != self.direction:
                self.direction = direction
            return

        # Leaving a CONTINUOUS gani for a different one: remember where it was
        # so resuming it later (below) doesn't snap back to frame 0.
        if self.gani is not None and self.gani.continuous and self.gani.name != name:
            self._continuous_state[self.gani.name] = (self.frame, self.frame_time)

        gani = self.parser.parse(name)
        if gani:
            self.gani = gani
            if direction is not None:
                self.direction = direction
            resumed = False
            if gani.continuous and not force:
                saved = self._continuous_state.get(name)
                if saved is not None:
                    frame_count = gani.get_frame_count(self.direction)
                    self.frame = saved[0] % frame_count if frame_count else 0
                    self.frame_time = saved[1]
                    resumed = True
            if not resumed:
                self.frame = 0
                self.frame_time = 0.0
            self.playing = True
            self.finished = False
            # Check for sound on first frame (only for a fresh start - a
            # resumed continuous gani shouldn't replay its intro sound).
            if not resumed:
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
