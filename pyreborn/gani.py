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
    """A single animation frame with sprite placements and optional sounds."""
    # [(sprite_id, offset_x, offset_y), ...]. sprite_id is normally an int,
    # but may be a "PARAM1".."PARAM5" string token (see _parse_frame_line).
    sprites: List[Tuple[Union[int, str], int, int]]
    # (filename, x_offset, y_offset) per PLAYSOUND -- the offsets are the sound
    # piece's position in TILES relative to the gani's own origin, not
    # volume/pitch: the editor writes them as `xoffset / 16.0`
    # (Preagonal/TilesEditor/src/AniEditor/Ani.cpp:911) and reads them back as
    # `* 16` (:717-718). They are routinely negative, which is why reading them
    # as a volume silenced the sound outright. A frame may carry more than one
    # (the editor's own model is a list: Ani.cpp:721 `frame->sounds.push_back`).
    sounds: List[Tuple[str, float, float]] = field(default_factory=list)

    @property
    def sound(self) -> Optional[Tuple[str, float, float]]:
        """The frame's first sound, or None."""
        return self.sounds[0] if self.sounds else None


@dataclass
class MovieKeyframe:
    """One actor update at a movie tick."""
    tick: int
    values: Dict[str, object]


@dataclass
class MovieActor:
    """A named cast member and its ordered timeline updates."""
    kind: str
    name: str
    keyframes: List[MovieKeyframe] = field(default_factory=list)


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
    is_movie: bool = False
    movie_length: int = 0
    actors: List[MovieActor] = field(default_factory=list)

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

        GANI format notes (ANI section grammar, per two independent oracles:
        Preagonal/TilesEditor/src/AniEditor/Ani.cpp:600-730 and the C# client's
        Preagonal.Common/.../Animations/Animation.cs:76-160):
        - One frame is N sprite-placement lines, one per direction: 4 normally,
          but exactly 1 when the file declares SINGLEDIRECTION.
        - Those lines are followed by a TRAILER of command lines -- PLAYSOUND
          and WAIT -- that belong to the frame just read, not to the next one
          (Animation.cs:142 assigns `newFrame.PlaySound` to the frame it has
          already built; Ani.cpp:721 pushes onto that same `frame->sounds`).
        - The trailer ends at a blank line, at ANIEND, or at the next
          sprite-placement line (Animation.cs:145-159 keeps consuming only
          blank/WAIT/PLAYSOUND lines), so blank separators are optional.
        """
        gani = Gani(name=name)
        lines = content.split('\n')

        in_ani = False
        in_script = False
        in_movie = False
        movie_actor: Optional[MovieActor] = None
        frame_lines: List[str] = []  # Sprite lines of the frame being collected
        # PLAYSOUNDs of the frame being collected (its trailer).
        frame_sounds: List[Tuple[str, float, float]] = []

        # We'll collect frames per direction
        direction_frames: Dict[int, List[GaniFrame]] = {0: [], 1: [], 2: [], 3: []}

        def dirs_per_frame() -> int:
            return 1 if gani.single_dir else 4

        def process_frame_group():
            """Emit the collected frame: one GaniFrame per direction line."""
            nonlocal frame_lines, frame_sounds

            if not frame_lines:
                # A stray trailer with no sprite line of its own (e.g. a
                # PLAYSOUND before the first frame). Hold it for the frame
                # that does arrive rather than discarding it.
                return

            for dir_idx, line in enumerate(frame_lines[:dirs_per_frame()]):
                frame = self._parse_frame_line(line)
                if frame:
                    # A gani only ever plays one direction at a time, so give
                    # every direction's frame the same sounds -- they fire no
                    # matter which way the emitter is facing.
                    frame.sounds = list(frame_sounds)
                    direction_frames[dir_idx].append(frame)

            frame_lines = []
            frame_sounds = []

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

            if line.startswith('FRAMES '):
                try:
                    gani.movie_length = int(line.split(None, 1)[1])
                except (ValueError, IndexError):
                    pass
                continue

            if line == 'MOVIE':
                gani.is_movie = True
                in_movie = True
                continue
            if line == 'MOVIEEND':
                in_movie = False
                movie_actor = None
                continue
            if in_movie:
                if line.startswith('ACTOR '):
                    parts = line.split(None, 2)
                    if len(parts) == 3:
                        movie_actor = MovieActor(
                            kind=parts[1].upper(), name=parts[2].strip())
                        gani.actors.append(movie_actor)
                    continue
                if line == 'ACTOREND':
                    movie_actor = None
                    continue
                if line.startswith('FRAME ') and movie_actor is not None:
                    keyframe = self._parse_movie_frame(line)
                    if keyframe is not None:
                        movie_actor.keyframes.append(keyframe)
                    continue
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
            if line == 'SINGLEDIRECTION':
                # One sprite line per frame instead of four (Ani.cpp:684's
                # `if (ani->m_singleDir) break;`). Was unhandled, so every
                # single-direction gani (the majority of real content) had its
                # consecutive FRAMES read as the four DIRECTIONS of one frame.
                gani.single_dir = True
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
                # Sound effect - part of the CURRENT frame's trailer.
                if line.upper().startswith('PLAYSOUND'):
                    sound = self._parse_playsound_line(line)
                    if sound is not None:
                        frame_sounds.append(sound)
                    continue

                # WAIT <n> holds the current frame for n extra ticks. We don't
                # model per-frame duration yet, but it MUST NOT fall through to
                # the sprite-line branch below: doing so consumed a direction
                # slot and (worse) flushed the frame group, discarding the
                # PLAYSOUND that shares the trailer with it. That silenced 728
                # of the ~1500 PLAYSOUNDs in the reference content.
                if line.upper().startswith('WAIT'):
                    continue

                # Blank line = end of this frame (sprite lines + trailer).
                if not line:
                    process_frame_group()
                    continue

                # A sprite-placement line. Reaching one when the frame already
                # has its full set of directions means the next frame started
                # without a blank separator, so close the current one first --
                # after its trailer has been collected, not before.
                if len(frame_lines) >= dirs_per_frame():
                    process_frame_group()
                frame_lines.append(line)

        # Check if all directions have same frame count. A file that declared
        # SINGLEDIRECTION keeps that flag even if its ANI section was empty.
        frame_counts = [len(direction_frames[i]) for i in range(4)]
        gani.single_dir = gani.single_dir or (
            all(c == 0 for c in frame_counts[1:]) and frame_counts[0] > 0)

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

    @staticmethod
    def _parse_movie_frame(line: str) -> Optional[MovieKeyframe]:
        """Parse ``FRAME tick key=value,...`` without treating commas in
        unkeyed text as fields."""
        parts = line.split(None, 2)
        if len(parts) < 2:
            return None
        try:
            tick = int(parts[1])
        except ValueError:
            return None
        values: Dict[str, object] = {}
        if len(parts) == 3:
            for item in parts[2].split(','):
                if '=' not in item:
                    continue
                key, value = item.split('=', 1)
                key = key.strip().lower()
                value = value.strip()
                if key in {'dx', 'dy', 'dir', 'layer', 'sprite #'}:
                    try:
                        values['sprite' if key == 'sprite #' else key] = int(value)
                    except ValueError:
                        continue
                elif key == 'visible':
                    values[key] = value.lower() == 'true'
                else:
                    values[key] = value
        return MovieKeyframe(tick=tick, values=values)

    @staticmethod
    def _parse_playsound_line(line: str) -> Optional[Tuple[str, float, float]]:
        """``PLAYSOUND <file> [<x> <y>]`` -> (file, x, y) offsets in tiles.

        Both numbers are optional in the wild -- weapon/NPC ganis write a bare
        ``PLAYSOUND PARAM1`` -- and some content (written by a locale where the
        decimal separator is a comma) writes them as ``1,5 2``. Neither may
        cost us the sound: the filename is the part that matters, so an
        unparseable offset falls back to the gani's origin rather than
        discarding the line.
        """
        parts = line.split()
        if len(parts) < 2:
            return None

        def offset(index: int) -> float:
            if len(parts) <= index:
                return 0.0
            try:
                return float(parts[index].replace(',', '.'))
            except ValueError:
                return 0.0

        return (parts[1], offset(2), offset(3))

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
        self.requested_name: Optional[str] = None  # last set_animation ask
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
        self.movie: Optional["MoviePlaybackState"] = None
        # The setani/setcharani call's trailing params (`setani ani,p1,p2`),
        # 0-based, so PARAM1 is params[0]. A gani's PLAYSOUND filename is
        # routinely a PARAMn token rather than a literal (`PLAYSOUND PARAM1`
        # with `DEFAULTPARAM1 sword.wav`), which is the whole point of the
        # stock "play a sound" ganis — see _resolve_sound.
        self.params: List[str] = []

    _PARAM_TOKEN = re.compile(r'^PARAM(\d+)$', re.IGNORECASE)

    def _resolve_sound(self, sound: Tuple[str, float, float]
                       ) -> Optional[Tuple[str, float, float]]:
        """Substitute a PARAMn sound filename for the real one.

        A PARAMn token resolves against this call's params, falling back to the
        gani's own DEFAULTPARAMn (parsed into Gani.defaults) — the same
        precedence the sprite-layer path uses for PARAMn frame tokens
        (game/render_entities.py's _resolve_gani_layers). An unresolved token
        yields None: passing "PARAM1" to the sound manager as a filename is a
        guaranteed miss that also poisons its failed-name cache.
        """
        match = self._PARAM_TOKEN.match(sound[0])
        if match is None:
            return sound
        index = int(match.group(1))
        value = None
        if 1 <= index <= len(self.params):
            value = self.params[index - 1]
        if not value and self.gani is not None:
            value = self.gani.defaults.get(f'PARAM{index}')
        if not value:
            return None
        return (value, sound[1], sound[2])

    def set_animation(self, name: str, direction: Optional[int] = None,
                      force: bool = False, params: Optional[List[str]] = None):
        """Set the current animation by name.

        `name` may be the raw comma-joined `ani,param1,param2` form; the params
        are split off (and override `params`) so PARAMn sound/sprite tokens
        resolve. They are refreshed on EVERY call, including the
        same-animation early return below, because a script re-issues the same
        gani with different params (a piano key's note, a weapon's sound).
        """
        if self.name_resolver is not None:
            try:
                name = self.name_resolver(name) or name
            except Exception:
                pass
        if ',' in name:
            parts = [p.strip() for p in name.split(',')]
            name = parts[0]
            params = parts[1:]
        params_changed = False
        if params is not None:
            params = list(params)
            params_changed = params != self.params
            self.params = params
        # GS1 scripts set `dir` as a float (e.g. `dir = 2` -> 2.0); the frame
        # tables are indexed by int, so coerce here for every caller.
        if direction is not None:
            try:
                direction = int(direction) & 3
            except (TypeError, ValueError):
                direction = 0
        # Remember what the caller asked for even if the gani file isn't
        # cached yet — the renderer uses this to request the download and
        # hide the entity instead of drawing a placeholder (GTA's cutscene
        # `setani hiddenstill,` drew a magenta box until the file arrived).
        self.requested_name = name
        # Don't restart the same animation unless forced -- the render path
        # re-asserts an entity's current gani every frame, so restarting on a
        # repeat would freeze it on frame 0. New PARAMS with the same name are
        # a genuinely new call though (`setani sen_piano_note2,<note>.wav` per
        # key pressed), and must restart or the second note never sounds.
        if not force and self.gani and self.gani.name == name and not params_changed:
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
            self.movie = MoviePlaybackState(gani, self.parser) if gani.is_movie else None
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
                self._queue_frame_sounds(self.gani.get_frame(self.direction, 0))

    def _queue_frame_sounds(self, frame_data: Optional[GaniFrame]):
        """Queue a frame's resolved sounds for the next update() to hand out."""
        if frame_data is None:
            return
        for sound in frame_data.sounds:
            resolved = self._resolve_sound(sound)
            if resolved is not None:
                self._pending_sounds.append(resolved)

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
            List of (filename, x_offset, y_offset) tuples -- the offsets are the
            sound's position in tiles relative to the emitter (see GaniFrame),
            and any PARAMn filename has already been substituted.
        """
        sounds = list(self._pending_sounds)
        self._pending_sounds.clear()

        if not self.gani or not self.playing or self.finished:
            return sounds

        if self.movie is not None:
            self.movie.update(dt)
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

            # Check if animation ended. Only LOOP repeats: CONTINUOUS alone
            # (classic cn_dead) means "resume where it left off when re-set",
            # NOT "loop" — looping ganis declare both (cn_walk/carry/swim are
            # LOOP+CONTINUOUS). Treating CONTINUOUS as looping replayed the
            # death spin forever.
            if self.frame >= frame_count:
                if self.gani.loops:
                    self.frame = 0
                else:
                    self.frame = frame_count - 1
                    self.finished = True
                    self.playing = False
                    break

            # Get sound for new frame
            if self.frame != old_frame:
                self._queue_frame_sounds(
                    self.gani.get_frame(self.direction, self.frame))
                sounds.extend(self._pending_sounds)
                self._pending_sounds.clear()

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
        if self.movie is not None:
            self.movie.reset()


@dataclass
class MovieActorState:
    """Resolved state of one cast member at the current movie time."""
    kind: str
    name: str
    dx: float
    dy: float
    direction: int
    layer: int
    ani: str
    animation: Optional[AnimationState]
    body: str
    head: str
    sword: str
    shield: str
    horse: str
    attr1: str
    colors: Tuple[str, ...]
    chat: str
    params: Dict[str, str]
    sprite: Optional[int] = None
    file: str = ""


class MoviePlaybackState:
    """Advances and resolves the independent actors in a movie gani."""

    FRAME_DURATION = 0.05

    def __init__(self, gani: Gani, gani_parser: GaniParser):
        if not gani.is_movie:
            raise ValueError("MoviePlaybackState requires a movie gani")
        self.gani = gani
        self.parser = gani_parser
        self.elapsed = 0.0
        self._actor_anims: Dict[int, AnimationState] = {}
        self._actor_ani_keys: Dict[int, Tuple[str, int]] = {}

    @property
    def tick(self) -> float:
        return min(self.elapsed / self.FRAME_DURATION,
                   float(self.gani.movie_length))

    def reset(self):
        self.elapsed = 0.0
        self._actor_anims.clear()
        self._actor_ani_keys.clear()

    def update(self, dt: float):
        dt = max(0.0, dt)
        self.elapsed = min(
            self.elapsed + dt,
            self.gani.movie_length * self.FRAME_DURATION)
        for animation in self._actor_anims.values():
            animation.update(dt)

    def visible_actors(self) -> List[MovieActorState]:
        """Return visible cast members, ordered by layer then source order."""
        resolved = []
        for index, actor in enumerate(self.gani.actors):
            state = self._resolve_actor(index, actor, self.tick, with_animation=True)
            if state is not None:
                resolved.append((state.layer, index, state))
        resolved.sort(key=lambda item: (item[0], item[1]))
        return [item[2] for item in resolved]

    def actor_state(self, name: str, tick: float) -> Optional[MovieActorState]:
        """Resolve a named actor at an arbitrary tick, primarily for tooling."""
        for index, actor in enumerate(self.gani.actors):
            if actor.name == name:
                return self._resolve_actor(index, actor, tick, with_animation=False)
        return None

    def _resolve_actor(self, index: int, actor: MovieActor, tick: float,
                       with_animation: bool) -> Optional[MovieActorState]:
        if not actor.keyframes or tick < actor.keyframes[0].tick:
            return None
        tick = min(max(0.0, tick), float(self.gani.movie_length))
        values: Dict[str, object] = {}
        ani_tick = 0
        for keyframe in actor.keyframes:
            if keyframe.tick > tick:
                break
            values.update(keyframe.values)
            if 'ani' in keyframe.values:
                ani_tick = keyframe.tick
        if values.get('visible', True) is False:
            return None

        dx = self._interpolated_axis(actor, tick, 'dx', values.get('dx', 0))
        dy = self._interpolated_axis(actor, tick, 'dy', values.get('dy', 0))
        direction = int(values.get('dir', 2))
        ani_name = str(values.get('ani', ''))
        animation = None
        if with_animation and actor.kind == 'CHAR' and ani_name:
            animation = self._actor_anims.get(index)
            ani_key = (ani_name, ani_tick)
            if animation is None:
                animation = self._actor_anims[index] = AnimationState(self.parser)
            if self._actor_ani_keys.get(index) != ani_key:
                animation.set_animation(ani_name, direction, force=True)
                if animation.gani is not None:
                    animation.update(max(0.0, tick - ani_tick) * self.FRAME_DURATION)
                self._actor_ani_keys[index] = ani_key
            else:
                was_missing = animation.gani is None
                animation.set_animation(ani_name, direction)
                if was_missing and animation.gani is not None:
                    animation.update(
                        max(0.0, tick - ani_tick) * self.FRAME_DURATION)
                animation.set_direction(direction)

        colors = tuple(str(values.get(
            f'color{i}', 'white')) for i in range(5))
        params = {
            key: str(value) for key, value in values.items()
            if key.startswith('param')
        }
        return MovieActorState(
            kind=actor.kind, name=actor.name, dx=dx, dy=dy,
            direction=direction, layer=int(values.get('layer', 1)),
            ani=ani_name, animation=animation, body=str(values.get(
                'body', self.gani.defaults.get('BODY', 'body.png'))),
            head=str(values.get(
                'head', self.gani.defaults.get('HEAD', 'head0.png'))),
            sword=str(values.get('sword', 'sword1.png')),
            shield=str(values.get('shield', 'shield1.png')),
            horse=str(values.get('horse', '')),
            attr1=str(values.get(
                'attr1', self.gani.defaults.get('ATTR1', ''))),
            colors=colors, chat=str(values.get('chat', '')),
            params=params,
            sprite=values.get('sprite') if isinstance(values.get('sprite'), int) else None,
            file=str(values.get('file', '')),
        )

    @staticmethod
    def _interpolated_axis(actor: MovieActor, tick: float, key: str,
                           current: object) -> float:
        try:
            start_value = float(current)
        except (TypeError, ValueError):
            start_value = 0.0
        start_tick = actor.keyframes[0].tick
        for keyframe in actor.keyframes:
            if keyframe.tick <= tick and key in keyframe.values:
                start_tick = keyframe.tick
                start_value = float(keyframe.values[key])
            elif keyframe.tick > tick and key in keyframe.values:
                span = keyframe.tick - start_tick
                if span <= 0:
                    return float(keyframe.values[key])
                fraction = (tick - start_tick) / span
                return start_value + (
                    float(keyframe.values[key]) - start_value) * fraction
        return start_value


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
