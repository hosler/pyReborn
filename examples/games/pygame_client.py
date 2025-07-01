#!/usr/bin/env python3
"""
Pygame Client - A visual client for PyReborn using Pygame
Arrow keys to move, Tab to chat, Escape to quit
"""

import sys
import pygame
import threading
import time
import queue
from pyreborn import RebornClient
from pyreborn.protocol.enums import Direction

# Constants
SCREEN_WIDTH = 1024
SCREEN_HEIGHT = 768
TILE_SIZE = 16
VIEWPORT_TILES_X = SCREEN_WIDTH // TILE_SIZE
VIEWPORT_TILES_Y = SCREEN_HEIGHT // TILE_SIZE

# Colors
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GREEN = (0, 255, 0)
RED = (255, 0, 0)
BLUE = (0, 0, 255)
GRAY = (128, 128, 128)
DARK_GREEN = (0, 128, 0)

class PygameClient:
    def __init__(self):
        # Initialize Pygame
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption("PyReborn Pygame Client")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 24)
        self.small_font = pygame.font.Font(None, 16)
        
        # Client
        self.client = RebornClient("localhost", 14900)
        self.connected = False
        self.running = True
        
        # Camera
        self.camera_x = 0
        self.camera_y = 0
        
        # Input
        self.keys_pressed = set()
        self.chat_mode = False
        self.chat_buffer = ""
        
        # Game state
        self.players = {}
        self.current_level = None
        self.event_queue = queue.Queue()
        
        # Movement
        self.move_speed = 0.5  # Half tile per move
        self.last_move_time = 0
        self.move_cooldown = 0.02  # 20ms between moves (smoother movement)
        self.is_moving = False
        self.last_direction = Direction.DOWN
        
        # Setup event handlers
        self._setup_events()
        
    def _setup_events(self):
        """Setup PyReborn event handlers"""
        self.client.events.subscribe('player_joined', self._on_player_joined)
        self.client.events.subscribe('player_left', self._on_player_left)
        self.client.events.subscribe('player_moved', self._on_player_moved)
        self.client.events.subscribe('player_chat', self._on_player_chat)
        self.client.events.subscribe('level_changed', self._on_level_changed)
        
    def _on_player_joined(self, event):
        """Handle player join"""
        self.event_queue.put(('player_joined', event))
        
    def _on_player_left(self, event):
        """Handle player leave"""
        self.event_queue.put(('player_left', event))
        
    def _on_player_moved(self, event):
        """Handle player movement"""
        self.event_queue.put(('player_moved', event))
        
    def _on_player_chat(self, event):
        """Handle player chat"""
        self.event_queue.put(('player_chat', event))
        
    def _on_level_changed(self, event):
        """Handle level change"""
        self.event_queue.put(('level_changed', event))
        
    def connect_and_login(self, username, password):
        """Connect to server and login"""
        if not self.client.connect():
            return False
            
        if not self.client.login(username, password):
            self.client.disconnect()
            return False
            
        self.connected = True
        self.client.set_nickname("PygamePlayer")
        
        # Reduce packet send rate for smoother gameplay
        self.client.set_packet_send_rate(0.02)  # 20ms between packets
        
        # Set initial idle animation
        self.client.set_gani("idle")
        
        # Center camera on player
        self.camera_x = self.client.local_player.x - VIEWPORT_TILES_X // 2
        self.camera_y = self.client.local_player.y - VIEWPORT_TILES_Y // 2
        
        return True
        
    def handle_events(self):
        """Handle pygame events"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                
            elif event.type == pygame.KEYDOWN:
                if self.chat_mode:
                    # Chat input
                    if event.key == pygame.K_RETURN:
                        if self.chat_buffer:
                            self.client.set_chat(self.chat_buffer)
                            self.chat_buffer = ""
                        self.chat_mode = False
                    elif event.key == pygame.K_ESCAPE:
                        self.chat_buffer = ""
                        self.chat_mode = False
                    elif event.key == pygame.K_BACKSPACE:
                        self.chat_buffer = self.chat_buffer[:-1]
                    else:
                        if event.unicode and len(self.chat_buffer) < 200:
                            self.chat_buffer += event.unicode
                else:
                    # Normal input
                    if event.key == pygame.K_TAB:
                        self.chat_mode = True
                    elif event.key == pygame.K_ESCAPE:
                        self.running = False
                    elif event.key == pygame.K_SPACE:
                        # Swing sword
                        self.client.set_gani("sword")
                    else:
                        self.keys_pressed.add(event.key)
                        
            elif event.type == pygame.KEYUP:
                self.keys_pressed.discard(event.key)
                
    def process_game_events(self):
        """Process events from the game"""
        while not self.event_queue.empty():
            try:
                event_type, event_data = self.event_queue.get_nowait()
                
                if event_type == 'player_joined':
                    player = event_data['player']
                    self.players[player.id] = player
                    
                elif event_type == 'player_left':
                    player = event_data['player']
                    self.players.pop(player.id, None)
                    
                elif event_type == 'player_moved':
                    player = event_data['player']
                    if player.id in self.players:
                        self.players[player.id] = player
                        
                elif event_type == 'level_changed':
                    self.current_level = self.client.level_manager.get_current_level()
                    # Update player list
                    self.players = {}
                    for player in self.client.session.get_current_level_players():
                        self.players[player.id] = player
                            
            except queue.Empty:
                break
                
    def handle_movement(self):
        """Handle player movement based on input
        
        Note: move_to() sets absolute position, so we move in small increments
        to create smooth movement rather than teleporting.
        """
        if self.chat_mode:
            return
            
        current_time = time.time()
        if current_time - self.last_move_time < self.move_cooldown:
            return
            
        dx, dy = 0, 0
        direction = None
        
        if pygame.K_LEFT in self.keys_pressed:
            dx -= self.move_speed
            direction = Direction.LEFT
        if pygame.K_RIGHT in self.keys_pressed:
            dx += self.move_speed
            direction = Direction.RIGHT
        if pygame.K_UP in self.keys_pressed:
            dy -= self.move_speed
            direction = Direction.UP
        if pygame.K_DOWN in self.keys_pressed:
            dy += self.move_speed
            direction = Direction.DOWN
            
        if dx != 0 or dy != 0:
            # Calculate new position based on small increments
            new_x = self.client.local_player.x + dx
            new_y = self.client.local_player.y + dy
            
            # Determine final direction (prioritize last pressed)
            if direction is None:
                direction = self.last_direction
            
            self.client.move_to(new_x, new_y, direction)
            self.last_move_time = current_time
            self.last_direction = direction
            
            # Set walking animation if not already moving
            if not self.is_moving:
                self.client.set_gani("walk")
                self.is_moving = True
        else:
            # Set idle animation when stopped
            if self.is_moving:
                self.client.set_gani("idle")
                self.is_moving = False
                
        # Always update camera to follow player
        self.camera_x = self.client.local_player.x - VIEWPORT_TILES_X // 2
        self.camera_y = self.client.local_player.y - VIEWPORT_TILES_Y // 2
            
    def draw_level(self):
        """Draw the current level"""
        if not self.current_level:
            return
            
        # Get tile data
        tiles_2d = self.current_level.get_board_tiles_2d()
        
        # Calculate visible range
        start_x = max(0, int(self.camera_x))
        start_y = max(0, int(self.camera_y))
        end_x = min(64, start_x + VIEWPORT_TILES_X + 1)
        end_y = min(64, start_y + VIEWPORT_TILES_Y + 1)
        
        # Draw tiles
        for y in range(start_y, end_y):
            for x in range(start_x, end_x):
                tile_id = tiles_2d[y][x]
                
                # Simple tile coloring based on ID
                if tile_id == 0:
                    color = DARK_GREEN  # Grass
                elif tile_id < 100:
                    color = GREEN
                elif tile_id < 500:
                    color = GRAY
                else:
                    # Generate color from tile ID
                    r = (tile_id * 7) % 256
                    g = (tile_id * 13) % 256
                    b = (tile_id * 23) % 256
                    color = (r, g, b)
                    
                # Draw tile
                screen_x = (x - self.camera_x) * TILE_SIZE
                screen_y = (y - self.camera_y) * TILE_SIZE
                pygame.draw.rect(self.screen, color, 
                               (screen_x, screen_y, TILE_SIZE, TILE_SIZE))
                               
    def draw_players(self):
        """Draw all players"""
        # Draw other players
        for player_id, player in self.players.items():
            if player_id == self.client.local_player.id:
                continue  # Draw local player last
                
            screen_x = (player.x - self.camera_x) * TILE_SIZE
            screen_y = (player.y - self.camera_y) * TILE_SIZE
            
            # Draw player as circle
            pygame.draw.circle(self.screen, BLUE, 
                             (int(screen_x + TILE_SIZE/2), 
                              int(screen_y + TILE_SIZE/2)), 
                             TILE_SIZE//2)
                             
            # Draw nickname
            name_text = self.small_font.render(player.nickname, True, WHITE)
            name_rect = name_text.get_rect(center=(screen_x + TILE_SIZE/2, screen_y - 5))
            self.screen.blit(name_text, name_rect)
            
            # Draw chat
            if player.chat:
                chat_text = self.small_font.render(player.chat, True, WHITE)
                chat_rect = chat_text.get_rect(center=(screen_x + TILE_SIZE/2, screen_y - 20))
                # Chat bubble background
                pygame.draw.rect(self.screen, BLACK, chat_rect.inflate(4, 2))
                self.screen.blit(chat_text, chat_rect)
                
        # Draw local player
        local_player = self.client.local_player
        screen_x = (local_player.x - self.camera_x) * TILE_SIZE
        screen_y = (local_player.y - self.camera_y) * TILE_SIZE
        
        pygame.draw.circle(self.screen, GREEN, 
                         (int(screen_x + TILE_SIZE/2), 
                          int(screen_y + TILE_SIZE/2)), 
                         TILE_SIZE//2)
                         
        # Draw local player name
        name_text = self.small_font.render(local_player.nickname, True, WHITE)
        name_rect = name_text.get_rect(center=(screen_x + TILE_SIZE/2, screen_y - 5))
        self.screen.blit(name_text, name_rect)
        
        # Draw local player chat
        if local_player.chat:
            chat_text = self.small_font.render(local_player.chat, True, WHITE)
            chat_rect = chat_text.get_rect(center=(screen_x + TILE_SIZE/2, screen_y - 20))
            pygame.draw.rect(self.screen, BLACK, chat_rect.inflate(4, 2))
            self.screen.blit(chat_text, chat_rect)
            
    def draw_ui(self):
        """Draw UI elements"""
        # Position info
        pos_text = self.font.render(f"Position: ({self.client.local_player.x:.1f}, {self.client.local_player.y:.1f})", 
                                   True, WHITE)
        self.screen.blit(pos_text, (10, 10))
        
        # Level info
        if self.current_level:
            level_text = self.font.render(f"Level: {self.current_level.name}", True, WHITE)
            self.screen.blit(level_text, (10, 35))
            
        # Player count
        player_text = self.font.render(f"Players: {len(self.players) + 1}", True, WHITE)
        self.screen.blit(player_text, (10, 60))
        
        # Chat mode
        if self.chat_mode:
            chat_prompt = self.font.render(f"Chat: {self.chat_buffer}_", True, WHITE)
            chat_rect = chat_prompt.get_rect(bottom=SCREEN_HEIGHT - 10, left=10)
            pygame.draw.rect(self.screen, BLACK, chat_rect.inflate(10, 5))
            self.screen.blit(chat_prompt, chat_rect)
        else:
            help_text = self.small_font.render("Arrow keys: Move | Space: Sword | Tab: Chat | Esc: Quit", 
                                             True, WHITE)
            self.screen.blit(help_text, (10, SCREEN_HEIGHT - 20))
            
    def run(self):
        """Main game loop"""
        # Get initial level
        self.current_level = self.client.level_manager.get_current_level()
        
        while self.running and self.connected and self.client.connected:
            # Handle events
            self.handle_events()
            self.process_game_events()
            
            # Update
            self.handle_movement()
            
            # Draw
            self.screen.fill(BLACK)
            self.draw_level()
            self.draw_players()
            self.draw_ui()
            
            # Update display
            pygame.display.flip()
            self.clock.tick(60)  # 60 FPS
            
        # Cleanup
        self.client.disconnect()
        pygame.quit()

def main():
    """Main entry point"""
    print("PyReborn Pygame Client")
    print("=====================")
    print()
    
    # Get login credentials
    username = input("Username (default: pygameplayer): ").strip() or "pygameplayer"
    password = input("Password (default: 1234): ").strip() or "1234"
    
    # Create client
    game = PygameClient()
    
    print("\nConnecting to server...")
    if not game.connect_and_login(username, password):
        print("Failed to connect or login!")
        return 1
        
    print("Connected! Starting game...")
    print("\nControls:")
    print("- Arrow keys: Move")
    print("- Space: Swing sword")
    print("- Tab: Enter chat mode")
    print("- Escape: Quit")
    print()
    
    # Wait for initial data
    time.sleep(2)
    
    # Run game
    game.run()
    
    print("\nThanks for playing!")
    return 0

if __name__ == "__main__":
    sys.exit(main())