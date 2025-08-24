"""
Audio System
============

Manages game audio including music and sound effects.
Integrates with PyReborn events for reactive audio.
"""

import pygame
import logging
from typing import Dict, Optional
from pathlib import Path

from pyreborn.events import EventType


logger = logging.getLogger(__name__)


class AudioSystem:
    """Handles all game audio"""
    
    def __init__(self, config):
        """Initialize audio system
        
        Args:
            config: Audio configuration
        """
        self.config = config
        self.enabled = config.enabled
        
        if not self.enabled:
            logger.info("Audio system disabled")
            return
        
        # Initialize pygame mixer
        try:
            pygame.mixer.init(
                frequency=44100,
                size=-16,
                channels=2,
                buffer=512
            )
            logger.info("Audio system initialized")
        except pygame.error as e:
            logger.error(f"Failed to initialize audio: {e}")
            self.enabled = False
            return
        
        # Volume settings
        self.master_volume = config.master_volume
        self.music_volume = config.music_volume
        self.sfx_volume = config.sfx_volume
        
        # Sound cache
        self.sounds: Dict[str, pygame.mixer.Sound] = {}
        self.music_tracks: Dict[str, str] = {}
        
        # Current state
        self.current_music = None
        self.music_paused = False
        
        # Channels for different sound types
        self.channels = {
            'ui': pygame.mixer.Channel(0),
            'player': pygame.mixer.Channel(1),
            'combat': pygame.mixer.Channel(2),
            'ambient': pygame.mixer.Channel(3)
        }
        
        # Load default sounds
        self._load_default_sounds()
    
    def _load_default_sounds(self):
        """Load default sound effects"""
        # Define default sounds to load
        default_sounds = {
            'menu_select': 'ui/select.wav',
            'menu_back': 'ui/back.wav',
            'player_hurt': 'player/hurt.wav',
            'sword_swing': 'combat/sword.wav',
            'item_pickup': 'player/pickup.wav',
            'chat_message': 'ui/message.wav'
        }
        
        # Try to load each sound
        for name, filename in default_sounds.items():
            # For now, we'll skip loading since we don't have assets yet
            # self.load_sound(name, filename)
            pass
    
    def load_sound(self, name: str, filename: str) -> bool:
        """Load a sound effect
        
        Args:
            name: Name to reference the sound
            filename: Path to sound file
            
        Returns:
            True if loaded successfully
        """
        if not self.enabled:
            return False
        
        try:
            sound_path = Path(filename)
            if sound_path.exists():
                sound = pygame.mixer.Sound(str(sound_path))
                sound.set_volume(self.sfx_volume * self.master_volume)
                self.sounds[name] = sound
                logger.debug(f"Loaded sound: {name}")
                return True
            else:
                logger.warning(f"Sound file not found: {filename}")
                return False
        except Exception as e:
            logger.error(f"Failed to load sound {name}: {e}")
            return False
    
    def play_sound(self, name: str, channel: str = 'player', volume: float = 1.0):
        """Play a sound effect
        
        Args:
            name: Name of the sound to play
            channel: Channel to play on
            volume: Volume multiplier (0.0 to 1.0)
        """
        if not self.enabled or name not in self.sounds:
            return
        
        try:
            sound = self.sounds[name]
            ch = self.channels.get(channel, self.channels['player'])
            
            # Set volume for this playback
            final_volume = self.sfx_volume * self.master_volume * volume
            sound.set_volume(final_volume)
            
            ch.play(sound)
        except Exception as e:
            logger.error(f"Failed to play sound {name}: {e}")
    
    def load_music(self, name: str, filename: str):
        """Load a music track
        
        Args:
            name: Name to reference the track
            filename: Path to music file
        """
        if not self.enabled:
            return
        
        music_path = Path(filename)
        if music_path.exists():
            self.music_tracks[name] = str(music_path)
            logger.debug(f"Registered music track: {name}")
        else:
            logger.warning(f"Music file not found: {filename}")
    
    def play_music(self, name: str, loops: int = -1, fade_ms: int = 0):
        """Play background music
        
        Args:
            name: Name of the music track
            loops: Number of loops (-1 for infinite)
            fade_ms: Fade in duration in milliseconds
        """
        if not self.enabled or name not in self.music_tracks:
            return
        
        try:
            # Stop current music if playing
            if self.current_music:
                pygame.mixer.music.stop()
            
            # Load and play new music
            pygame.mixer.music.load(self.music_tracks[name])
            pygame.mixer.music.set_volume(self.music_volume * self.master_volume)
            
            if fade_ms > 0:
                pygame.mixer.music.play(loops, fade_ms=fade_ms)
            else:
                pygame.mixer.music.play(loops)
            
            self.current_music = name
            self.music_paused = False
            logger.debug(f"Playing music: {name}")
            
        except Exception as e:
            logger.error(f"Failed to play music {name}: {e}")
    
    def stop_music(self, fade_ms: int = 0):
        """Stop background music
        
        Args:
            fade_ms: Fade out duration in milliseconds
        """
        if not self.enabled:
            return
        
        try:
            if fade_ms > 0:
                pygame.mixer.music.fadeout(fade_ms)
            else:
                pygame.mixer.music.stop()
            self.current_music = None
            self.music_paused = False
        except Exception as e:
            logger.error(f"Failed to stop music: {e}")
    
    def pause_music(self):
        """Pause background music"""
        if not self.enabled or not self.current_music:
            return
        
        pygame.mixer.music.pause()
        self.music_paused = True
    
    def resume_music(self):
        """Resume background music"""
        if not self.enabled or not self.music_paused:
            return
        
        pygame.mixer.music.unpause()
        self.music_paused = False
    
    def set_master_volume(self, volume: float):
        """Set master volume (0.0 to 1.0)"""
        self.master_volume = max(0.0, min(1.0, volume))
        self._update_volumes()
    
    def set_music_volume(self, volume: float):
        """Set music volume (0.0 to 1.0)"""
        self.music_volume = max(0.0, min(1.0, volume))
        if self.enabled:
            pygame.mixer.music.set_volume(self.music_volume * self.master_volume)
    
    def set_sfx_volume(self, volume: float):
        """Set sound effects volume (0.0 to 1.0)"""
        self.sfx_volume = max(0.0, min(1.0, volume))
        self._update_volumes()
    
    def _update_volumes(self):
        """Update all sound volumes"""
        if not self.enabled:
            return
        
        # Update music volume
        pygame.mixer.music.set_volume(self.music_volume * self.master_volume)
        
        # Update all loaded sounds
        for sound in self.sounds.values():
            sound.set_volume(self.sfx_volume * self.master_volume)
    
    def cleanup(self):
        """Clean up audio system"""
        if self.enabled:
            pygame.mixer.quit()
            logger.info("Audio system shut down")
    
    # Integration with PyReborn events
    def subscribe_to_events(self, event_manager):
        """Subscribe to game events for reactive audio
        
        Args:
            event_manager: PyReborn event manager
        """
        if not self.enabled:
            return
        
        # Subscribe to relevant events
        event_manager.subscribe(EventType.LEVEL_TRANSITION, self._on_level_changed)
        # Note: PLAYER_HURT, WEAPON_FIRED, ITEM_COLLECTED may not exist
        # event_manager.subscribe(EventType.PLAYER_HURT, self._on_player_hurt)
        # event_manager.subscribe(EventType.WEAPON_FIRED, self._on_weapon_fired)
        # event_manager.subscribe(EventType.ITEM_COLLECTED, self._on_item_collected)
        event_manager.subscribe(EventType.CHAT_MESSAGE, self._on_chat_message)
    
    def _on_level_changed(self, old_level: str, new_level: str, **kwargs):
        """Handle level change - might change music"""
        # TODO: Implement level-specific music
        pass
    
    def _on_player_hurt(self, damage: int, **kwargs):
        """Handle player taking damage"""
        self.play_sound('player_hurt', 'player')
    
    def _on_weapon_fired(self, weapon_type: str, **kwargs):
        """Handle weapon being used"""
        if weapon_type == 'sword':
            self.play_sound('sword_swing', 'combat')
    
    def _on_item_collected(self, item_type: str, **kwargs):
        """Handle item pickup"""
        self.play_sound('item_pickup', 'player')
    
    def _on_chat_message(self, **kwargs):
        """Handle chat message received"""
        self.play_sound('chat_message', 'ui', volume=0.5)