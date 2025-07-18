"""
Audio Manager Module - Handles sound effects and music for Classic Graal
"""

import pygame
import os
from typing import Dict, Optional


class AudioManager:
    """Manages sound effects and music playback"""
    
    def __init__(self):
        """Initialize the audio system"""
        pygame.mixer.init()
        
        # Sound channels
        self.sound_channels = {i: pygame.mixer.Channel(i) for i in range(8)}
        
        # Sound cache
        self.sound_cache: Dict[str, pygame.mixer.Sound] = {}
        
        # Classic sound mappings
        self.sound_map = {
            'pickup': 'item.wav',
            'heart': 'heart.wav',
            'rupee': 'rupee.wav',
            'bomb': 'bomb.wav',
            'arrow': 'arrow.wav',
            'key': 'get_key.wav',
            'heart_container': 'fanfare.wav',
            'sword': 'sword.wav',
            'sword_hit': 'hit.wav',
            'hurt': 'hurt.wav',
            'die': 'die.wav',
            'grass_cut': 'grass.wav',
            'chest_open': 'chest.wav',
            'bush_lift': 'pickup2.wav',
            'bush_throw': 'throw.wav',
            'swim': 'swim.wav',
            'step': 'step.wav',
            'text': 'text.wav',
            'secret': 'secret.wav'
        }
        
        # Sound directories to search
        self.sound_paths = [
            os.path.join(os.path.dirname(__file__), "assets", "sounds"),
            os.path.join(os.path.dirname(__file__), "assets", "levels", "sounds"),
            os.path.join(os.path.dirname(__file__), "assets"),
        ]
        
    def load_sound(self, filename: str) -> Optional[pygame.mixer.Sound]:
        """Load a sound file into cache
        
        Args:
            filename: Name of the sound file
            
        Returns:
            pygame.mixer.Sound object or None if not found
        """
        if filename in self.sound_cache:
            return self.sound_cache[filename]
            
        # Try different paths
        for base_path in self.sound_paths:
            path = os.path.join(base_path, filename)
            if os.path.exists(path):
                try:
                    sound = pygame.mixer.Sound(path)
                    self.sound_cache[filename] = sound
                    return sound
                except Exception as e:
                    print(f"Failed to load sound {filename}: {e}")
                    
        return None
        
    def play_classic_sound(self, sound_name: str, volume: float = 0.7):
        """Play a Classic Graal sound effect
        
        Args:
            sound_name: Name of the sound (without .wav extension)
            volume: Volume from 0.0 to 1.0
        """
        # Get the actual filename
        filename = self.sound_map.get(sound_name, f"{sound_name}.wav")
        
        # Load and play the sound
        sound = self.load_sound(filename)
        if sound:
            # Find a free channel
            for channel_id, channel in self.sound_channels.items():
                if not channel.get_busy():
                    sound.set_volume(volume)
                    channel.play(sound)
                    break
                    
    def play_gani_sound(self, sound_file: str, volume: float, channel: int):
        """Play a sound from GANI animation
        
        Args:
            sound_file: Sound filename from GANI
            volume: Volume level
            channel: Channel number to play on
        """
        sound = self.load_sound(sound_file)
        if sound and channel in self.sound_channels:
            sound.set_volume(min(1.0, volume))
            self.sound_channels[channel].play(sound)
            
    def play_item_pickup_sound(self, item_type: str):
        """Play the appropriate sound for picking up an item
        
        Args:
            item_type: Type of item picked up
        """
        sound_map = {
            'heart': 'heart',
            'rupee': 'rupee',
            'bomb': 'bomb',
            'arrow': 'arrow',
            'key': 'key',
            'heart_container': 'heart_container'
        }
        
        sound_name = sound_map.get(item_type, 'pickup')
        self.play_classic_sound(sound_name)
        
    def stop_all_sounds(self):
        """Stop all currently playing sounds"""
        pygame.mixer.stop()
        
    def set_master_volume(self, volume: float):
        """Set the master volume for all sounds
        
        Args:
            volume: Volume from 0.0 to 1.0
        """
        for channel in self.sound_channels.values():
            channel.set_volume(volume)