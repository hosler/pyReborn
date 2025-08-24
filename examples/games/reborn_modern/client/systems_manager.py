"""
Systems Manager
==============

Manages initialization and updates of all game systems.
Extracted from main game class for cleaner architecture.
"""

import logging
from typing import Optional

import pygame
from pyreborn.core.modular_client import ModularRebornClient
from pyreborn.api.outgoing_packets import OutgoingPacketAPI

from systems import (
    RenderingSystem,
    InputSystem,
    AudioSystem,
    PhysicsSystem
)

logger = logging.getLogger(__name__)


class SystemsManager:
    """Manages all game systems"""
    
    def __init__(self, screen: pygame.Surface, config: dict):
        self.screen = screen
        self.config = config
        
        # Systems (initialized on connection)
        self.renderer: Optional[RenderingSystem] = None
        self.input_system: Optional[InputSystem] = None
        self.audio_system: Optional[AudioSystem] = None
        self.physics_system: Optional[PhysicsSystem] = None
        
        # Pre-initialize audio if enabled
        if config.get('audio', {}).get('enabled', False):
            self.audio_system = AudioSystem(config.get('audio', {}))
            
    def initialize(self, client: ModularRebornClient, packet_api: OutgoingPacketAPI):
        """Initialize all systems with client connection"""
        # Rendering system
        self.renderer = RenderingSystem(
            self.screen,
            client,
            self.config.get('graphics', {})
        )
        
        # Physics system
        self.physics_system = PhysicsSystem(client, packet_api)
        
        # Input system
        self.input_system = InputSystem(
            packet_api,
            self.config.get('keybindings', {}),
            self.physics_system
        )
        
        # Connect physics to renderer
        if self.renderer:
            self.renderer.set_physics_system(self.physics_system)
            if self.renderer.entity_renderer:
                self.renderer.entity_renderer.set_physics_system(self.physics_system)
                
        logger.info("Game systems initialized")
        
    def update(self, dt: float, client: ModularRebornClient):
        """Update all systems"""
        # Update player interpolation
        if client:
            session_manager = client.get_manager('session')
            if session_manager:
                self._update_player_interpolation(session_manager, dt)
                
        # Update systems
        if self.physics_system:
            self.physics_system.update(dt)
            
        if self.input_system:
            self.input_system.update(dt)
            
        # Update entity renderer for animations
        if self.renderer and self.renderer.entity_renderer:
            self.renderer.entity_renderer.update(dt)
            
    def _update_player_interpolation(self, session_manager, dt: float):
        """Update interpolation for non-local players"""
        all_players = session_manager.get_all_players()
        local_player = session_manager.get_player()
        local_player_id = local_player.id if local_player else None
        
        # Update interpolation for other players only
        for player_id, player in all_players.items():
            if player_id != local_player_id:  # Not local player
                if hasattr(player, 'update_interpolation'):
                    player.update_interpolation(dt)
                if hasattr(player, 'update_movement'):
                    player.update_movement(dt)
                    
    def render(self):
        """Render using the rendering system"""
        if self.renderer:
            self.renderer.render()
            
    def cleanup(self):
        """Cleanup systems"""
        if self.audio_system:
            self.audio_system.cleanup()
            
    def handle_event(self, event):
        """Pass events to input system"""
        if self.input_system:
            return self.input_system.handle_event(event)
        return False