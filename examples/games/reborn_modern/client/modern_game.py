"""
Simplified Modern Reborn Game
=============================

Refactored main game class using modular managers.
Reduced from 766 lines to ~250 lines.
"""

import pygame
import logging
from typing import Optional, Tuple
from pathlib import Path

from pyreborn.core.modular_client import ModularRebornClient
from pyreborn.api.outgoing_packets import OutgoingPacketAPI
from pyreborn.core.events import EventType
from pyreborn.config.client_config import ClientConfig as PyRebornConfig

from .config import GameConfig
from .game_state import GameState, GameStateManager
from .event_manager import EventManager
from .systems_manager import SystemsManager
from ui import ServerBrowserUI, HUD, ChatUI
from ui.debug_overlay_simple import SimplifiedDebugOverlay

logger = logging.getLogger(__name__)


class ModernGame:
    """Simplified main game class with modular architecture"""
    
    def __init__(self, config: dict):
        # Parse configuration
        self.config = GameConfig.from_dict(config)
        
        # Initialize Pygame
        pygame.init()
        pygame.display.set_caption(self.config.window.title)
        
        # Create display
        flags = pygame.DOUBLEBUF
        if self.config.graphics.vsync:
            flags |= pygame.HWSURFACE
            
        self.screen = pygame.display.set_mode(
            (self.config.window.width, self.config.window.height),
            flags
        )
        
        # Core components
        self.clock = pygame.time.Clock()
        self.running = False
        self.auto_login: Optional[Tuple[str, str]] = None
        
        # PyReborn client (created on connection)
        self.client: Optional[ModularRebornClient] = None
        self.packet_api: Optional[OutgoingPacketAPI] = None
        
        # Managers
        self.state_manager = GameStateManager()
        self.event_manager = None  # Created on connection
        self.systems_manager = SystemsManager(self.screen, config)
        
        # UI Components
        self.server_browser = ServerBrowserUI(
            self.screen,
            self.config.window.width,
            self.config.window.height
        )
        self.hud = None
        self.chat_ui = None
        self.debug_overlay = None
        
        logger.info("Simplified Modern Game initialized")
        
    def set_auto_login(self, username: str, password: str):
        """Set credentials for automatic login"""
        self.auto_login = (username, password)
        logger.info(f"Auto-login set for user: {username}")
        
    def connect_to_server(self, host: str, port: int, version: str) -> bool:
        """Connect to a game server"""
        try:
            # Create PyReborn client
            pyreborn_config = PyRebornConfig(host=host, port=port, version=version)
            self.client = ModularRebornClient(config=pyreborn_config)
            self.packet_api = OutgoingPacketAPI(self.client)
            
            # Setup event manager
            self.event_manager = EventManager(self.client)
            self.event_manager.setup_callbacks({
                EventType.LOGIN_SUCCESS: self._on_login_success,
                EventType.LOGIN_FAILED: self._on_login_failed,
                EventType.DISCONNECTED: self._on_disconnected,
                EventType.LEVEL_TRANSITION: self._on_level_changed,
                EventType.CHAT_MESSAGE: self._on_chat_message
            })
            self.event_manager.subscribe_all()
            
            # Connect
            if not self.client.connect():
                logger.error(f"Failed to connect to {host}:{port}")
                return False
                
            logger.info(f"Connected to {host}:{port}")
            
            # Initialize systems
            self.systems_manager.initialize(self.client, self.packet_api)
            
            # Initialize UI
            self.hud = HUD(self.screen, self.client)
            self.chat_ui = ChatUI(self.screen, self.packet_api)
            self.debug_overlay = SimplifiedDebugOverlay(self.screen, self.client)
            
            return True
            
        except Exception as e:
            logger.error(f"Connection error: {e}")
            return False
            
    def run(self):
        """Main game loop"""
        self.running = True
        
        # Handle auto-login
        if self.auto_login:
            if self.connect_to_server(
                self.config.client.host,
                self.config.client.port,
                self.config.client.version
            ):
                username, password = self.auto_login
                if self.client.login(username, password):
                    self.state_manager.transition_to(GameState.PLAYING)
                    
        # Main loop
        while self.running:
            dt = self.clock.tick(self.config.window.fps) / 1000.0
            
            self._handle_events()
            self._update(dt)
            self._render()
            
            pygame.display.flip()
            
        self._cleanup()
        
    def _handle_events(self):
        """Handle pygame events"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                
            # Handle based on state
            if self.state_manager.is_menu():
                self.server_browser.handle_event(event)
                
            elif self.state_manager.is_playing():
                # Chat UI priority
                chat_handled = self.chat_ui.handle_event(event) if self.chat_ui else False
                
                # Input system if chat didn't handle
                if not chat_handled:
                    self.systems_manager.handle_event(event)
                    
                # Debug controls
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_d and self.debug_overlay:
                        self.debug_overlay.cycle_mode()
                    elif event.key == pygame.K_ESCAPE:
                        self.state_manager.transition_to(GameState.PAUSED)
                        
    def _update(self, dt: float):
        """Update game logic"""
        # Update based on state
        if self.state_manager.is_menu():
            result = self.server_browser.update(dt)
            if result:
                host, port = result
                self.state_manager.transition_to(GameState.CONNECTING)
                if self.connect_to_server(host, port, self.config.client.version):
                    # Use test credentials for now
                    if self.client.login("your_username", "your_password"):
                        self.state_manager.transition_to(GameState.PLAYING)
                    else:
                        self.state_manager.transition_to(GameState.MENU)
                        
        elif self.state_manager.is_playing():
            # Update systems
            self.systems_manager.update(dt, self.client)
            
            # Update UI
            if self.hud:
                self.hud.update(dt)
            if self.chat_ui:
                self.chat_ui.update(dt)
            if self.debug_overlay:
                self.debug_overlay.update(dt)
                
    def _render(self):
        """Render the game"""
        self.screen.fill((40, 60, 80))
        
        # Render based on state
        if self.state_manager.is_menu():
            self.server_browser.render()
            
        elif self.state_manager.is_playing():
            # Render world
            self.systems_manager.render()
            
            # Render UI
            if self.hud:
                self.hud.render()
            if self.chat_ui:
                self.chat_ui.render()
            if self.debug_overlay:
                self.debug_overlay.render()
                
    def _cleanup(self):
        """Clean up resources"""
        logger.info("Shutting down...")
        
        # Unsubscribe events
        if self.event_manager:
            self.event_manager.unsubscribe_all()
            
        # Disconnect
        if self.client and self.client.is_connected():
            self.client.disconnect()
            
        # Cleanup systems
        self.systems_manager.cleanup()
        
        pygame.quit()
        
    # Event callbacks
    def _on_login_success(self, event):
        logger.info("Login successful")
        self.state_manager.transition_to(GameState.PLAYING)
        
    def _on_login_failed(self, event):
        logger.error(f"Login failed: {event.get('reason', 'Unknown')}")
        self.state_manager.transition_to(GameState.MENU)
        
    def _on_disconnected(self, event):
        logger.warning("Disconnected from server")
        self.state_manager.transition_to(GameState.MENU)
        
    def _on_level_changed(self, event):
        logger.info(f"Level changed: {event.get('old_level')} -> {event.get('new_level')}")
        
    def _on_chat_message(self, event):
        if self.chat_ui:
            self.chat_ui.add_message(event.get('message', ''), event.get('player_id'))