"""
pyreborn - Sound manager.

Handles loading, caching, and playing sound effects.
Works with pygame.mixer.
"""

import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Pygame import is optional - only needed when actually used
try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False


class SoundManager:
    """Manages loading and playing sound effects."""

    def __init__(self, search_paths: Optional[List[Path]] = None, enabled: bool = True):
        """
        Initialize sound manager.

        Args:
            search_paths: List of paths to search for sound files
            enabled: Whether sound is enabled (can be toggled)
        """
        self.search_paths = search_paths or []
        self.enabled = enabled
        self.volume = 1.0  # Master volume (0.0 - 1.0)
        self.sound_cache: Dict[str, pygame.mixer.Sound] = {}
        self._initialized = False

        # Streaming background music (MIDI/OGG/MP3) goes through mixer.music,
        # not mixer.Sound. Track the current track + temp files for downloaded
        # music (SDL_mixer's MIDI backend needs a real file path) + names that
        # failed to load so we don't spam retries.
        self._current_music: Optional[str] = None
        self._music_files: Dict[str, str] = {}
        self._music_failed = set()

        # Subdirectories to search
        self.subdirs = ['', 'sounds', 'sfx', 'audio']

    def initialize(self):
        """Initialize pygame mixer if not already done."""
        if not PYGAME_AVAILABLE:
            print("Warning: pygame not available, sound disabled")
            self.enabled = False
            return

        if self._initialized:
            return

        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
            self._initialized = True
        except Exception as e:
            print(f"Warning: Could not initialize sound mixer: {e}")
            self.enabled = False

    def add_search_path(self, path: Path):
        """Add a search path for finding sound files."""
        if path not in self.search_paths:
            self.search_paths.append(path)

    def find_file(self, name: str) -> Optional[Path]:
        """Find a sound file by name in search paths."""
        for search_path in self.search_paths:
            # Check direct path
            full_path = search_path / name
            if full_path.exists():
                return full_path

            # Check subdirectories
            for subdir in self.subdirs:
                if subdir:
                    sub_path = search_path / subdir / name
                else:
                    sub_path = search_path / name
                if sub_path.exists():
                    return sub_path

        return None

    def load(self, name: str) -> Optional[pygame.mixer.Sound]:
        """
        Load a sound by name.

        Args:
            name: Filename of the sound (e.g., 'sword.wav')

        Returns:
            pygame.mixer.Sound or None if not found
        """
        if not self.enabled:
            return None

        self.initialize()

        # Check cache
        if name in self.sound_cache:
            return self.sound_cache[name]

        # Find file
        file_path = self.find_file(name)
        if not file_path:
            return None

        # Load sound
        try:
            sound = pygame.mixer.Sound(str(file_path))
            self.sound_cache[name] = sound
            return sound
        except Exception as e:
            print(f"Error loading sound {name}: {e}")
            return None

    def play(self, name: str, volume: float = 1.0, pitch: float = 1.0) -> bool:
        """
        Play a sound effect.

        Args:
            name: Sound filename
            volume: Volume multiplier (0.0 - 2.0, relative to master)
            pitch: Pitch multiplier (currently ignored - pygame doesn't support pitch)

        Returns:
            True if sound was played, False otherwise
        """
        if not self.enabled:
            return False

        sound = self.load(name)
        if not sound:
            return False

        try:
            # Calculate effective volume
            effective_volume = min(1.0, self.volume * volume)
            sound.set_volume(effective_volume)

            # Play sound
            sound.play()
            return True
        except Exception as e:
            print(f"Error playing sound {name}: {e}")
            return False

    def play_from_gani(self, sound_info: Tuple[str, float, float]) -> bool:
        """
        Play a sound from gani animation data.

        Args:
            sound_info: Tuple of (filename, volume, pitch) from GaniFrame

        Returns:
            True if sound was played
        """
        filename, volume, pitch = sound_info
        return self.play(filename, volume, pitch)

    # Tiles from the listener at which a positional sound fades to silence.
    # The viewport shows ~40x30 tiles, so a sound dies a little past the edge
    # of what's on screen — same idea as Preagonal's SfxSystem distance falloff.
    POSITIONAL_FALLOFF = 18.0

    def play_positional(self, sound_info: Tuple[str, float, float],
                        dx: float, dy: float) -> bool:
        """Play a gani sound attenuated and panned by a listener-relative offset.

        Args:
            sound_info: (filename, volume, pitch) from a GaniFrame.
            dx, dy: entity position minus the local player, in tiles.

        Volume falls off linearly with distance and the sound pans left/right
        with dx, so other players' and NPCs' sounds feel located in the world
        instead of all firing at full volume in the centre.
        """
        if not self.enabled:
            return False

        filename, volume, pitch = sound_info
        dist = math.hypot(dx, dy)
        atten = 1.0 - dist / self.POSITIONAL_FALLOFF
        if atten <= 0.0:
            return False

        sound = self.load(filename)
        if not sound:
            return False

        try:
            effective = min(1.0, self.volume * volume) * atten
            sound.set_volume(effective)
            channel = sound.play()
            # Stereo pan: full left at -falloff, full right at +falloff.
            if channel is not None:
                pan = max(-1.0, min(1.0, dx / self.POSITIONAL_FALLOFF))
                left = effective * (1.0 - max(0.0, pan))
                right = effective * (1.0 + min(0.0, pan))
                channel.set_volume(left, right)
            return True
        except Exception as e:
            print(f"Error playing positional sound {filename}: {e}")
            return False

    # Formats handled as streaming music rather than one-shot samples.
    MUSIC_EXTS = ('.mid', '.midi', '.ogg', '.mp3', '.mod', '.it', '.xm', '.s3m')

    @classmethod
    def is_music(cls, name: str) -> bool:
        return name.lower().endswith(cls.MUSIC_EXTS)

    def play_music(self, name: str, data: Optional[bytes] = None,
                   loop: bool = True) -> bool:
        """Stream background music (MIDI/OGG/MP3/tracker) via pygame.mixer.music.

        Only one music track plays at a time. `data` is the file's bytes when it
        was downloaded from the server; otherwise the file is looked up on disk.
        Downloaded music is written to a temp file because SDL_mixer's MIDI
        backend loads by path, not from a file object.
        """
        if not self.enabled:
            return False
        self.initialize()
        if not self._initialized:
            return False
        if name == self._current_music and pygame.mixer.music.get_busy():
            return True   # already playing this track
        if name in self._music_failed:
            return False

        try:
            if data is not None:
                src = self._music_files.get(name)
                if src is None:
                    import os
                    import tempfile
                    ext = os.path.splitext(name)[1] or '.mid'
                    fd, src = tempfile.mkstemp(suffix=ext, prefix='pyreborn_mus_')
                    with os.fdopen(fd, 'wb') as f:
                        f.write(data)
                    self._music_files[name] = src
            else:
                found = self.find_file(name)
                if not found:
                    return False
                src = str(found)

            pygame.mixer.music.load(src)
            pygame.mixer.music.set_volume(self.volume)
            pygame.mixer.music.play(-1 if loop else 0)
            self._current_music = name
            return True
        except Exception as e:
            # MIDI needs SDL_mixer built with timidity/fluidsynth; if it isn't,
            # log once and give up on that track rather than retrying every call.
            print(f"Could not play music {name}: {e}")
            self._music_failed.add(name)
            return False

    def stop_music(self):
        if PYGAME_AVAILABLE and self._initialized:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
        self._current_music = None

    def preload(self, names: List[str]):
        """Preload multiple sounds."""
        for name in names:
            self.load(name)

    def set_volume(self, volume: float):
        """Set master volume (0.0 - 1.0)."""
        self.volume = max(0.0, min(1.0, volume))

    def set_enabled(self, enabled: bool):
        """Enable or disable sound."""
        self.enabled = enabled

    def stop_all(self):
        """Stop all currently playing sounds."""
        if PYGAME_AVAILABLE and self._initialized:
            try:
                pygame.mixer.stop()
            except:
                pass

    def clear_cache(self):
        """Clear all cached sounds."""
        self.sound_cache.clear()

    def get_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        return {
            'sounds_cached': len(self.sound_cache),
            'enabled': self.enabled,
        }


# Common sound names used in Reborn
COMMON_SOUNDS = [
    'sword.wav',
    'swordon.wav',
    'steps.wav',
    'steps2.wav',
    'bomb.wav',
    'item.wav',
    'item2.wav',
    'lift.wav',
    'lift2.wav',
    'put.wav',
    'chest.wav',
    'arrow.wav',
    'arrowon.wav',
    'dead.wav',
    'extra.wav',
    'goal.wav',
    'jump.wav',
    'horse.wav',
    'horse2.wav',
]


def preload_common_sounds(sound_manager: SoundManager):
    """Preload commonly used sounds."""
    sound_manager.preload(COMMON_SOUNDS)
