"""
Modern Reborn Game - Updated for Consolidated Architecture
===========================================================

Uses the new consolidated PyReborn architecture with:
- Clean internal module organization
- Unified managers for each domain
- Event-driven updates
"""

import pygame
import logging
import time
from pathlib import Path
from typing import Optional

# Use the new consolidated PyReborn Client
from pyreborn import Client, EventType
from pyreborn.models import Player, Level

# Import local systems from this example's systems folder
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from systems.warp_manager import WarpManager
from systems.renderer import Renderer
from systems.physics_system import PhysicsSystem
from systems.camera import Camera

logger = logging.getLogger(__name__)


class ModernRebornGame:
    """Simplified game using unified systems"""
    
    def __init__(self, config: dict = None):
        """Initialize simplified game
        
        Args:
            config: Configuration dictionary
        """
        # Default config
        if config is None:
            config = {
                'window': {'width': 800, 'height': 600, 'title': 'Modern Reborn'},
                'server': {'host': 'localhost', 'port': 14900, 'version': '6.037'}
            }
        
        # Extract window settings
        width = config.get('window', {}).get('width', 800)
        height = config.get('window', {}).get('height', 600)
        title = config.get('window', {}).get('title', 'Modern Reborn')
        
        # Initialize Pygame
        pygame.init()
        self.screen = pygame.display.set_mode((width, height))
        pygame.display.set_caption(title)
        self.clock = pygame.time.Clock()
        
        # Store config
        self.config = config
        
        # Game state
        self.running = False
        self.client: Optional[Client] = None
        
        # Auto-login credentials
        self.auto_username = None
        self.auto_password = None
        
        # Simplified systems (will be initialized after connection)
        self.warp_manager = None
        self.renderer = None
        self.physics = None
        self.camera = None
        
        logger.info("Simplified game initialized")
    
    def set_auto_login(self, username: str, password: str):
        """Set credentials for auto-login
        
        Args:
            username: Account username
            password: Account password
        """
        self.auto_username = username
        self.auto_password = password
        logger.info(f"Auto-login set for user: {username}")
    
    def connect(self, host: str, port: int, username: str, password: str) -> bool:
        """Connect to server
        
        Args:
            host: Server hostname
            port: Server port
            username: Account username
            password: Account password
            
        Returns:
            True if connected and logged in
        """
        # Create simplified client
        self.client = Client(host, port, "6.037")
        
        # Connect
        if not self.client.connect():
            logger.error("Failed to connect")
            return False
        
        # Login
        if not self.client.login(username, password):
            logger.error("Failed to login")
            return False
        
        logger.info(f"Connected as {username}")
        
        # Initialize simplified systems
        self._init_systems()
        
        return True
    
    def _init_systems(self):
        """Initialize simplified game systems"""
        # Import packet API compatibility layer
        from systems.packet_api_compat import create_packet_api
        
        # Create packet API wrapper for systems that need it
        packet_api = create_packet_api(self.client)
        
        # Initialize systems
        self.warp_manager = WarpManager(self.client, packet_api)
        self.renderer = Renderer(self.screen)
        self.physics = PhysicsSystem(self.client, packet_api)
        self.camera = Camera(self.screen.get_width(), self.screen.get_height())
        
        # Add player physics body
        if self.client.player:
            # Use the actual player ID instead of hardcoded -1
            player_id = self.client.player.id if hasattr(self.client.player, 'id') else self.client.player.player_id
            self.physics.add_body(player_id, self.client.player.x, self.client.player.y)
        
        logger.info("Simplified systems initialized")
    
    def run(self):
        """Main game loop"""
        # Auto-login if credentials are set
        if self.auto_username and self.auto_password:
            # Get server config
            server_config = self.config.get('server', {})
            host = server_config.get('host', 'localhost')
            port = server_config.get('port', 14900)
            
            # Try to connect and login
            if not self.connect(host, port, self.auto_username, self.auto_password):
                logger.error("Failed to auto-login")
                return
        
        self.running = True
        last_time = time.time()
        
        while self.running:
            # Calculate delta time
            current_time = time.time()
            delta_time = current_time - last_time
            last_time = current_time
            
            # Handle events
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN:
                    self._handle_keydown(event)
                elif event.type == pygame.KEYUP:
                    self._handle_keyup(event)
            
            # Update game
            self._update(delta_time)
            
            # Render
            self._render()
            
            # Control FPS
            self.clock.tick(60)
        
        # Cleanup
        self.cleanup()
    
    def _handle_keydown(self, event):
        """Handle key press
        
        Args:
            event: Pygame key event
        """
        if event.key == pygame.K_ESCAPE:
            self.running = False
        elif event.key == pygame.K_g:
            if self.renderer:
                self.renderer.toggle_grid()
        elif event.key == pygame.K_l:
            if self.renderer:
                self.renderer.toggle_links()
    
    def _handle_keyup(self, event):
        """Handle key release
        
        Args:
            event: Pygame key event
        """
        pass
    
    def _update(self, delta_time: float):
        """Update game state
        
        Args:
            delta_time: Time since last frame
        """
        if not self.client:
            return
        
        # Get keyboard input for movement
        keys = pygame.key.get_pressed()
        dx = dy = 0
        
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            dx = -1
        elif keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            dx = 1
        
        if keys[pygame.K_UP] or keys[pygame.K_w]:
            dy = -1
        elif keys[pygame.K_DOWN] or keys[pygame.K_s]:
            dy = 1
        
        # Move with physics
        if (dx != 0 or dy != 0) and self.physics:
            new_x, new_y = self.physics.move(-1, dx, dy, delta_time)
            
            # Update player position
            self.client.player.x = new_x
            self.client.player.y = new_y
            
            # Send to server
            self.client.move(0, 0)  # This sends current position
        
        # Check for warps
        if self.warp_manager:
            player = self.client.player
            if self.warp_manager.check_warps(player.x, player.y):
                logger.info("Warp triggered!")
        
        # Update client
        self.client.update()
    
    def _render(self):
        """Render game"""
        # Clear screen
        self.screen.fill((50, 50, 50))
        
        # Render with simplified renderer
        if self.renderer and self.client:
            self.renderer.render(self.client)
        
        # Draw HUD
        self._draw_hud()
        
        # Update display
        pygame.display.flip()
    
    def _draw_hud(self):
        """Draw heads-up display"""
        if not self.client or not self.client.player:
            return
        
        # Simple HUD with player info
        font = pygame.font.Font(None, 24)
        player = self.client.player
        
        # Position
        pos_text = f"Pos: ({player.x:.1f}, {player.y:.1f})"
        text = font.render(pos_text, True, (255, 255, 255))
        self.screen.blit(text, (10, 10))
        
        # Level
        level_text = f"Level: {player.level}"
        text = font.render(level_text, True, (255, 255, 255))
        self.screen.blit(text, (10, 35))
        
        # Hearts
        hearts_text = f"Hearts: {player.hearts}/{player.max_hearts}"
        text = font.render(hearts_text, True, (255, 100, 100))
        self.screen.blit(text, (10, 60))
        
        # FPS
        fps_text = f"FPS: {int(self.clock.get_fps())}"
        text = font.render(fps_text, True, (255, 255, 0))
        self.screen.blit(text, (10, 85))
        
        # Controls
        controls = [
            "WASD/Arrows - Move",
            "G - Toggle Grid",
            "L - Toggle Links",
            "ESC - Exit"
        ]
        y = self.screen.get_height() - 100
        small_font = pygame.font.Font(None, 18)
        for control in controls:
            text = small_font.render(control, True, (200, 200, 200))
            self.screen.blit(text, (10, y))
            y += 20
    
    def cleanup(self):
        """Clean up resources"""
        if self.client:
            self.client.disconnect()
        
        pygame.quit()
        logger.info("Game cleaned up")


def main():
    """Main entry point"""
    import sys
    
    # Parse arguments
    if len(sys.argv) < 3:
        print("Usage: python simplified_game.py <username> <password> [server] [port]")
        sys.exit(1)
    
    username = sys.argv[1]
    password = sys.argv[2]
    server = sys.argv[3] if len(sys.argv) > 3 else "localhost"
    port = int(sys.argv[4]) if len(sys.argv) > 4 else 14900
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create and run game
    game = SimplifiedGame()
    
    if game.connect(server, port, username, password):
        game.run()
    else:
        logger.error("Failed to start game")
        sys.exit(1)


if __name__ == "__main__":
    main()