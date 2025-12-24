"""
pyreborn - Sound manager.

Handles loading, caching, and playing sound effects.
Works with pygame.mixer.
"""

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
