"""
Configuration Management
"""

from dataclasses import dataclass, field
from typing import Dict, Any
import pygame


@dataclass
class WindowConfig:
    """Window configuration"""
    width: int = 1600
    height: int = 900
    title: str = "Reborn Modern"
    fps: int = 60
    

@dataclass
class ClientConfig:
    """PyReborn client configuration"""
    host: str = "localhost"
    port: int = 14900
    version: str = "6.037"


@dataclass
class DebugConfig:
    """Debug settings"""
    enabled: bool = True  # Master debug toggle
    show_fps: bool = True
    packet_inspector: bool = False
    coordinate_overlay: bool = False


@dataclass
class AudioConfig:
    """Audio settings"""
    enabled: bool = True
    master_volume: float = 0.7
    music_volume: float = 0.5
    sfx_volume: float = 0.8


@dataclass
class GraphicsConfig:
    """Graphics settings"""
    vsync: bool = True
    smooth_scaling: bool = True
    tile_size: int = 16


@dataclass 
class GameConfig:
    """Complete game configuration"""
    window: WindowConfig = field(default_factory=WindowConfig)
    client: ClientConfig = field(default_factory=ClientConfig)
    debug: DebugConfig = field(default_factory=DebugConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    graphics: GraphicsConfig = field(default_factory=GraphicsConfig)
    keybindings: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'GameConfig':
        """Create config from dictionary"""
        config = cls()
        
        # Window config
        if 'window' in data:
            config.window = WindowConfig(**data['window'])
            
        # Client config
        if 'client' in data:
            config.client = ClientConfig(**data['client'])
            
        # Debug config
        if 'debug' in data:
            config.debug = DebugConfig(**data['debug'])
            
        # Audio config
        if 'audio' in data:
            config.audio = AudioConfig(**data['audio'])
            
        # Graphics config
        if 'graphics' in data:
            config.graphics = GraphicsConfig(**data['graphics'])
            
        # Keybindings
        if 'keybindings' in data:
            config.keybindings = cls._parse_keybindings(data['keybindings'])
            
        return config
    
    @staticmethod
    def _parse_keybindings(bindings: dict) -> Dict[str, int]:
        """Parse keybinding strings to pygame constants"""
        parsed = {}
        
        for action, key in bindings.items():
            if isinstance(key, str):
                # Single character keys
                if len(key) == 1:
                    parsed[action] = ord(key)
                # Arrow keys
                elif key == 'up':
                    parsed[action] = pygame.K_UP
                elif key == 'down':
                    parsed[action] = pygame.K_DOWN
                elif key == 'left':
                    parsed[action] = pygame.K_LEFT
                elif key == 'right':
                    parsed[action] = pygame.K_RIGHT
                # Special keys
                elif key == 'space':
                    parsed[action] = pygame.K_SPACE
                elif key == 'enter' or key == 'return':
                    parsed[action] = pygame.K_RETURN
                elif key == 'ctrl':
                    parsed[action] = pygame.K_LCTRL
                elif key.startswith('f'):
                    # Function keys
                    try:
                        f_num = int(key[1:])
                        parsed[action] = getattr(pygame, f'K_F{f_num}')
                    except (ValueError, AttributeError):
                        pass
                        
        return parsed