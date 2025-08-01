"""
UI Manager Module - Handles HUD, menus, and UI elements for Classic Graal
"""

import pygame
import time
from typing import List, Tuple, Dict, Optional
from pyreborn.models.player import Player

# UI Colors
UI_BG = (20, 20, 30)
UI_BORDER = (100, 100, 150)
UI_TEXT = (200, 200, 255)
UI_HIGHLIGHT = (50, 50, 80)

# Standard colors
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GREEN = (0, 255, 0)
RED = (255, 0, 0)
BLUE = (0, 0, 255)
YELLOW = (255, 255, 0)
GRAY = (128, 128, 128)
DARK_GREEN = (0, 128, 0)
CYAN = (0, 255, 255)
PURPLE = (128, 0, 128)


class Message:
    """A temporary message to display"""
    def __init__(self, text: str, color: Tuple[int, int, int], duration: float = 5.0):
        self.text = text
        self.color = color
        self.timestamp = time.time()
        self.duration = duration
        
    def is_expired(self) -> bool:
        return time.time() - self.timestamp > self.duration


class UIManager:
    """Manages all UI elements and HUD"""
    
    def __init__(self, screen: pygame.Surface):
        """Initialize the UI manager
        
        Args:
            screen: Pygame screen surface
        """
        self.screen = screen
        self.screen_width = screen.get_width()
        self.screen_height = screen.get_height()
        
        # Fonts
        self.font_large = pygame.font.Font(None, 36)
        self.font_medium = pygame.font.Font(None, 24)
        self.font_small = pygame.font.Font(None, 18)
        self.font_tiny = pygame.font.Font(None, 14)
        
        # Messages
        self.messages: List[Message] = []
        self.max_messages = 5
        
        # Chat
        self.chat_history: List[Tuple[str, Tuple[int, int, int]]] = []
        self.max_chat_history = 10
        
        # Debug info
        self.debug_info: Dict[str, str] = {}
        
    def add_message(self, text: str, color: Tuple[int, int, int] = WHITE, duration: float = 5.0):
        """Add a temporary message to display
        
        Args:
            text: Message text
            color: Text color
            duration: How long to show the message
        """
        self.messages.append(Message(text, color, duration))
        
        # Limit message count
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]
            
    def add_chat_message(self, text: str, color: Tuple[int, int, int] = WHITE):
        """Add a message to chat history
        
        Args:
            text: Chat message
            color: Text color
        """
        self.chat_history.append((text, color))
        
        # Limit chat history
        if len(self.chat_history) > self.max_chat_history:
            self.chat_history = self.chat_history[-self.max_chat_history:]
            
    def update_debug_info(self, key: str, value: str):
        """Update a debug info entry
        
        Args:
            key: Debug info key
            value: Debug info value
        """
        self.debug_info[key] = value
        
    def update(self):
        """Update UI elements (remove expired messages)"""
        self.messages = [msg for msg in self.messages if not msg.is_expired()]
        
    def draw_status_bar(self, player: Player):
        """Draw the Classic Graal status bar
        
        Args:
            player: Local player
        """
        # Status bar background
        bar_height = 30
        bar_rect = pygame.Rect(0, 0, self.screen_width, bar_height)
        pygame.draw.rect(self.screen, UI_BG, bar_rect)
        pygame.draw.rect(self.screen, UI_BORDER, bar_rect, 2)
        
        # Player stats
        x_offset = 10
        y_offset = 7
        
        # Hearts
        heart_text = f"Hearts: {player.hearts:.1f}/{player.max_hearts}"
        text_surface = self.font_small.render(heart_text, True, RED)
        self.screen.blit(text_surface, (x_offset, y_offset))
        x_offset += text_surface.get_width() + 20
        
        # Rupees
        rupee_text = f"Rupees: {player.rupees}"
        text_surface = self.font_small.render(rupee_text, True, GREEN)
        self.screen.blit(text_surface, (x_offset, y_offset))
        x_offset += text_surface.get_width() + 20
        
        # Bombs
        bomb_text = f"Bombs: {player.bombs}"
        text_surface = self.font_small.render(bomb_text, True, GRAY)
        self.screen.blit(text_surface, (x_offset, y_offset))
        x_offset += text_surface.get_width() + 20
        
        # Arrows
        arrow_text = f"Arrows: {player.arrows}"
        text_surface = self.font_small.render(arrow_text, True, YELLOW)
        self.screen.blit(text_surface, (x_offset, y_offset))
        x_offset += text_surface.get_width() + 20
        
        # Keys
        if hasattr(player, 'keys'):
            key_text = f"Keys: {player.keys}"
            text_surface = self.font_small.render(key_text, True, BLUE)
            self.screen.blit(text_surface, (x_offset, y_offset))
            
    def draw_messages(self):
        """Draw temporary messages"""
        y_offset = 40  # Below status bar
        
        for msg in self.messages:
            text_surface = self.font_medium.render(msg.text, True, msg.color)
            text_rect = text_surface.get_rect(centerx=self.screen_width // 2, y=y_offset)
            
            # Draw shadow
            shadow_surface = self.font_medium.render(msg.text, True, BLACK)
            shadow_rect = text_rect.copy()
            shadow_rect.x += 2
            shadow_rect.y += 2
            self.screen.blit(shadow_surface, shadow_rect)
            
            # Draw text
            self.screen.blit(text_surface, text_rect)
            y_offset += 25
            
    def draw_chat_history(self):
        """Draw chat message history"""
        y_offset = self.screen_height - 150
        
        for text, color in self.chat_history:
            # Create chat text with shadow
            text_surface = self.font_small.render(text, True, color)
            shadow_surface = self.font_small.render(text, True, BLACK)
            
            # Draw shadow
            self.screen.blit(shadow_surface, (12, y_offset + 1))
            # Draw text
            self.screen.blit(text_surface, (10, y_offset))
            
            y_offset += 15
            
    def draw_chat_input(self, chat_buffer: str):
        """Draw chat input box
        
        Args:
            chat_buffer: Current chat input text
        """
        # Chat input background
        input_rect = pygame.Rect(5, self.screen_height - 30, 400, 25)
        pygame.draw.rect(self.screen, UI_BG, input_rect)
        pygame.draw.rect(self.screen, UI_BORDER, input_rect, 2)
        
        # Chat prompt
        prompt = "Say: " + chat_buffer
        text_surface = self.font_small.render(prompt, True, WHITE)
        self.screen.blit(text_surface, (10, self.screen_height - 27))
        
        # Cursor
        cursor_x = 10 + text_surface.get_width()
        pygame.draw.line(self.screen, WHITE, 
                        (cursor_x, self.screen_height - 25),
                        (cursor_x, self.screen_height - 8), 1)
                        
    def draw_debug_info(self, show_debug: bool):
        """Draw debug information
        
        Args:
            show_debug: Whether to show debug info
        """
        if not show_debug:
            return
            
        y_offset = 60  # Below status bar and messages
        
        # Background
        debug_height = len(self.debug_info) * 15 + 10
        debug_rect = pygame.Rect(5, y_offset - 5, 200, debug_height)
        pygame.draw.rect(self.screen, UI_BG, debug_rect)
        pygame.draw.rect(self.screen, UI_BORDER, debug_rect, 1)
        
        # Debug info
        for key, value in self.debug_info.items():
            text = f"{key}: {value}"
            text_surface = self.font_tiny.render(text, True, UI_TEXT)
            self.screen.blit(text_surface, (10, y_offset))
            y_offset += 15
            
    def draw_minimap(self, level_name: str, player_x: float, player_y: float,
                    other_players: Dict[int, Player]):
        """Draw minimap
        
        Args:
            level_name: Current level name
            player_x: Local player X position
            player_y: Local player Y position
            other_players: Dict of other players
        """
        # Minimap settings
        minimap_size = 128
        minimap_scale = minimap_size / 64.0  # 64x64 tiles
        
        # Position in top-right corner
        minimap_x = self.screen_width - minimap_size - 10
        minimap_y = 40
        
        # Background
        minimap_rect = pygame.Rect(minimap_x, minimap_y, minimap_size, minimap_size)
        pygame.draw.rect(self.screen, UI_BG, minimap_rect)
        pygame.draw.rect(self.screen, UI_BORDER, minimap_rect, 2)
        
        # Draw player position
        player_map_x = int(minimap_x + player_x * minimap_scale)
        player_map_y = int(minimap_y + player_y * minimap_scale)
        pygame.draw.circle(self.screen, GREEN, (player_map_x, player_map_y), 3)
        
        # Draw other players
        for other_player in other_players.values():
            other_x = int(minimap_x + other_player.x * minimap_scale)
            other_y = int(minimap_y + other_player.y * minimap_scale)
            pygame.draw.circle(self.screen, YELLOW, (other_x, other_y), 2)
            
        # Level name
        level_text = self.font_tiny.render(level_name, True, UI_TEXT)
        level_rect = level_text.get_rect(centerx=minimap_x + minimap_size // 2,
                                        y=minimap_y + minimap_size + 5)
        self.screen.blit(level_text, level_rect)
        
    def draw_player_list(self, players: Dict[int, Player]):
        """Draw list of online players
        
        Args:
            players: Dict of all players
        """
        # Background
        list_width = 200
        list_height = min(300, len(players) * 20 + 40)
        list_x = self.screen_width - list_width - 10
        list_y = 200
        
        list_rect = pygame.Rect(list_x, list_y, list_width, list_height)
        pygame.draw.rect(self.screen, UI_BG, list_rect)
        pygame.draw.rect(self.screen, UI_BORDER, list_rect, 2)
        
        # Title
        title_text = self.font_small.render(f"Players Online ({len(players)})", True, WHITE)
        title_rect = title_text.get_rect(centerx=list_x + list_width // 2, y=list_y + 5)
        self.screen.blit(title_text, title_rect)
        
        # Player list
        y_offset = list_y + 30
        for player in sorted(players.values(), key=lambda p: p.name):
            # Player name
            name_text = self.font_tiny.render(player.name[:20], True, UI_TEXT)
            self.screen.blit(name_text, (list_x + 10, y_offset))
            
            # Player level
            level_text = self.font_tiny.render(f"Lv.{player.level}", True, GRAY)
            self.screen.blit(level_text, (list_x + list_width - 40, y_offset))
            
            y_offset += 20
            
            # Limit display
            if y_offset > list_y + list_height - 20:
                break
                
    def draw_help_text(self, chat_mode: bool):
        """Draw help text at bottom of screen
        
        Args:
            chat_mode: Whether chat mode is active
        """
        if chat_mode:
            return
            
        help_text = "Arrow/WASD: Move | Space/S: Attack | A: Grab/Read | Tab: Chat | F1: Debug | F2: Collision | M: Map | P: Players | Esc: Quit"
        text_surface = self.font_tiny.render(help_text, True, GRAY)
        text_rect = text_surface.get_rect(centerx=self.screen_width // 2,
                                         bottom=self.screen_height - 5)
        self.screen.blit(text_surface, text_rect)