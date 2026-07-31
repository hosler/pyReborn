"""
pyreborn - Sound manager.

The sound manager loads, caches, and plays sound effects.
Works with pygame.mixer.
"""

import io
import math
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from .asset_paths import normalize_asset_name
from .sprites import find_asset_file

# Pygame import is optional - only needed when actually used
try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False


class SoundManager:
    """The sound manager loads and plays sound effects."""

    def __init__(self, search_paths: Optional[List[Path]] = None, enabled: bool = True):
        """
        Create the sound manager.

        Args:
            search_paths: List of paths to search for sound files
            enabled: Whether sound is enabled (can be toggled)
        """
        self.search_paths = search_paths or []
        self.enabled = enabled
        self.volume = 1.0  # Master volume (0.0 - 1.0)
        # Separate gate for streamed background music (see play_music below) --
        # `enabled` above only ever gated one-shot Sound effects, not
        # mixer.music, so the settings overlay's "Music" toggle needs its own
        # flag (game/settings_ui.py).
        self.music_enabled = True
        self.sound_cache: Dict[str, pygame.mixer.Sound] = {}
        self._initialized = False

        # Streaming background music (MIDI/OGG/MP3) goes through mixer.music,
        # not mixer.Sound. Track the current track + temp files for downloaded
        # music (SDL_mixer's MIDI backend needs a real file path) + names that
        # failed to load so we don't spam retries.
        self._current_music: Optional[str] = None
        self._music_files: Dict[str, str] = {}
        self._music_failed = set()

        # Names that failed to resolve/load, so play() doesn't re-walk every
        # search path on each call (e.g. a missing footstep sound fired once
        # per step). Mirrors _music_failed above. load_bytes() clears a name
        # from here, so a sound that arrives from the server later is not
        # permanently written off by the miss that requested it.
        self._sound_failed = set()
        # One missed trigger per filename, retried if its downloaded sample
        # arrives promptly. Entries are (monotonic time, replay kind, args).
        self._pending_samples = {}
        self.pending_sample_ttl = 10.0

        # Optional "fetch this from the server" hook, called at most once per
        # missing name (see load). Servers publish their sound folder as
        # downloadable files (`file sounds/*.wav` in foldersconfig), and a
        # server's custom sounds exist nowhere on disk until asked for, so
        # without this every NPC/weapon sound outside the bundled set is
        # silent forever. Wire it to the same one-shot request path the
        # renderer uses for images/ganis; the bytes come back through
        # load_bytes().
        self.file_requester: Optional[Callable[[str], object]] = None
        self._requested = set()

        # Subdirectories to search
        self.subdirs = ['', 'sounds', 'sfx', 'audio']

    def initialize(self):
        """If the pygame mixer is not active, start it."""
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

    def find_file(self, name: str) -> Optional[Path]:
        """Find a sound file by name in search paths."""
        return find_asset_file(self.search_paths, self.subdirs, name)

    def load(self, name: str) -> Optional[pygame.mixer.Sound]:
        """
        Load a sound by name.

        Args:
            name: Filename of the sound (e.g., 'sword.wav')

        Returns:
            pygame.mixer.Sound or None if not found
        """
        name = normalize_asset_name(name)
        if not self.enabled or not name:
            return None

        if name in self._sound_failed:
            # Still worth one request: preload_common_sounds() runs before the
            # game client can wire file_requester, so the names it wrote off
            # would otherwise never be fetched.
            self._request(name)
            return None

        self.initialize()

        # Check cache
        if name in self.sound_cache:
            return self.sound_cache[name]

        # Find file
        file_path = self.find_file(name)
        if not file_path:
            self._request(name)
            self._sound_failed.add(name)
            return None

        # Load sound
        try:
            sound = self._decode(open(file_path, "rb").read())
            self.sound_cache[name] = sound
            return sound
        except Exception as e:
            print(f"Error loading sound {name}: {e}")
            self._sound_failed.add(name)
            return None

    @staticmethod
    def _decode(data: bytes) -> "pygame.mixer.Sound":
        """Decode sound bytes, unwrapping MPEG-in-WAV.

        Servers ship .wav files whose RIFF fmt tag is MPEG Layer 3
        (wFormatTag 0x0055). SDL_mixer's WAV parser rejects those with
        "MPEG formats not supported" even though it decodes the same
        payload as a raw MP3 stream, so hand it the bare data chunk.
        """
        if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
            pos, fmt_tag, payload = 12, None, None
            while pos + 8 <= len(data):
                cid = data[pos:pos + 4]
                size = int.from_bytes(data[pos + 4:pos + 8], "little")
                body = data[pos + 8:pos + 8 + size]
                if cid == b"fmt " and size >= 2:
                    fmt_tag = int.from_bytes(body[:2], "little")
                elif cid == b"data":
                    payload = body
                pos += 8 + size + (size & 1)
            if fmt_tag in (0x0050, 0x0055) and payload:
                return pygame.mixer.Sound(io.BytesIO(payload))
        return pygame.mixer.Sound(io.BytesIO(data))

    def _request(self, name: str):
        """Ask the server for a sound we do not have, once per name."""
        name = normalize_asset_name(name)
        if self.file_requester is None or name in self._requested:
            return
        self._requested.add(name)
        try:
            self.file_requester(name)
        except Exception:
            pass

    def load_bytes(self, name: str, data: bytes) -> Optional["pygame.mixer.Sound"]:
        """Cache a sound that arrived from the server as bytes.

        Mirrors SpriteManager.load_bytes for images. Clears any earlier
        failed-lookup record for the name, which is what the request that
        fetched these bytes left behind.
        """
        name = normalize_asset_name(name)
        if not self.enabled or not name or not data:
            return None
        self.initialize()
        if not self._initialized:
            return None
        try:
            sound = self._decode(data)
        except Exception as e:
            print(f"Error loading sound {name}: {e}")
            self._sound_failed.add(name)
            return None
        self._sound_failed.discard(name)
        self.sound_cache[name] = sound
        pending = self._pending_samples.pop(name, None)
        if pending is not None:
            requested_at, kind, args = pending
            if time.monotonic() - requested_at <= self.pending_sample_ttl:
                if kind == 'play':
                    self.play(name, *args)
                else:
                    self.play_positional(*args)
        return sound

    def _remember_pending(self, name: str, kind: str, args: tuple) -> None:
        """Remember only the first recent missed trigger for each filename."""
        name = normalize_asset_name(name)
        now = time.monotonic()
        pending = self._pending_samples.get(name)
        if pending is None or now - pending[0] > self.pending_sample_ttl:
            self._pending_samples[name] = (now, kind, args)

    def play(self, name: str, volume: float = 1.0, pitch: float = 1.0) -> bool:
        """
        Play a sound effect.

        Args:
            name: Sound filename
            volume: Volume multiplier (0.0 - 2.0, relative to master)
            pitch: Pitch multiplier (currently ignored - pygame does not support pitch)

        Returns:
            True if sound was played, False otherwise
        """
        if not self.enabled:
            return False

        sound = self.load(name)
        if not sound:
            self._remember_pending(name, 'play', (volume, pitch))
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
        """Play a gani sound emitted by the LOCAL player.

        sound_info is (filename, x_offset, y_offset) in tiles — see GaniFrame.
        The listener is the local player, so the piece's own offset is the
        whole listener-relative displacement. Routing it through
        play_positional keeps one interpretation of the tuple for every
        emitter, and the sub-sprite distances involved barely attenuate.
        """
        return self.play_positional(sound_info, 0.0, 0.0)

    # Tiles from the listener at which a positional sound fades to silence.
    # The viewport shows ~40x30 tiles (half-width 20, half-height 15), so the
    # falloff needs to reach the corners (hypot(20, 15) ~= 25) or entities near
    # the screen edge play silently — same idea as the C# client's SfxSystem
    # distance falloff.
    POSITIONAL_FALLOFF = 26.0

    def play_positional(self, sound_info: Tuple[str, float, float],
                        dx: float, dy: float) -> bool:
        """Play a gani sound attenuated and panned by a listener-relative offset.

        Args:
            sound_info: (filename, x_offset, y_offset) from a GaniFrame — the
                piece's offset in tiles from its emitter's origin.
            dx, dy: emitter position minus the local player, in tiles.

        Volume falls off linearly with distance and the sound pans left/right,
        so other players' and NPCs' sounds feel located in the world instead
        of all firing at full volume in the center.
        """
        if not self.enabled:
            return False

        filename, off_x, off_y = sound_info
        # The piece's own offset rides on top of the emitter's displacement.
        dx += off_x
        dy += off_y
        dist = math.hypot(dx, dy)
        atten = 1.0 - dist / self.POSITIONAL_FALLOFF
        if atten <= 0.0:
            return False

        sound = self.load(filename)
        if not sound:
            self._remember_pending(
                filename, 'positional', (sound_info, dx - off_x, dy - off_y))
            return False

        try:
            # A gani sound piece carries no per-sound volume (the two numbers
            # are its position), so distance is the only attenuation.
            effective = min(1.0, self.volume) * atten
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
        was downloaded from the server. Otherwise the file is looked up on disk.
        Downloaded music is written to a temp file because SDL_mixer's MIDI
        backend loads by path, not from a file object.
        """
        name = normalize_asset_name(name)
        if not self.enabled or not self.music_enabled or not name:
            return False
        self.initialize()
        if not self._initialized:
            return False
        if name == self._current_music:
            return True   # same track already selected — ignore (don't restart).
            # Scripts re-request the current track every frame (e.g. bomber NPC
            # 75's radio); only a different track or stop_music() reloads. (Don't
            # gate on get_busy(): a momentary gap at a loop boundary must not
            # cause a reload/restart.)
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
        """Set master volume (0.0 - 1.0).

        Also pushed to mixer.music immediately if it is already
        initialized/playing: unlike Sound.set_volume (applied fresh on every
        play()), mixer.music has one persistent volume that play_music()
        only sets at load time, so a live volume change (e.g. the settings
        overlay's slider) would otherwise not affect a track already
        streaming.
        """
        self.volume = max(0.0, min(1.0, volume))
        if PYGAME_AVAILABLE and self._initialized:
            try:
                pygame.mixer.music.set_volume(self.volume)
            except Exception:
                pass

    def set_music_enabled(self, enabled: bool):
        """Enable or disable streamed background music (see music_enabled
        above). Disabling stops whatever's currently playing immediately."""
        self.music_enabled = enabled
        if not enabled:
            self.stop_music()

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
    'hurt.wav',
    'beep.wav',
    'extra.wav',
    'goal.wav',
    'jump.wav',
    'horse.wav',
    'horse2.wav',
]


def preload_common_sounds(sound_manager: SoundManager):
    """Preload commonly used sounds."""
    sound_manager.preload(COMMON_SOUNDS)
