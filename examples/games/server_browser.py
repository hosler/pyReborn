"""
Server Browser Module - Handles server selection UI for PyReborn
"""

import pygame
import threading
import time
from pyreborn import RebornClient, ServerInfo
from typing import List, Optional, Tuple

# UI Colors - Green theme
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GRAY = (128, 128, 128)
GREEN = (0, 255, 0)
DARK_GREEN = (0, 128, 0)
LIGHT_GREEN = (144, 238, 144)
RED = (255, 0, 0)
YELLOW = (255, 255, 0)
UI_BG = (10, 30, 10)  # Dark green background
UI_BORDER = (50, 200, 50)  # Bright green border
UI_TEXT = (200, 255, 200)  # Light green text
UI_HIGHLIGHT = (20, 60, 20)  # Dark green highlight


class ServerBrowserState:
    """Server browser UI state"""
    
    def __init__(self, screen):
        self.screen = screen
        self.font = pygame.font.Font(None, 24)
        self.title_font = pygame.font.Font(None, 36)
        self.small_font = pygame.font.Font(None, 18)
        
        # Server list
        self.servers = []
        self.selected_index = 0
        self.scroll_offset = 0
        self.max_visible = 10  # Further reduced to fit in box properly
        
        # Walking character animation
        self.character_x = 0
        self.character_y = 50
        self.character_frame = 0
        self.character_direction = 1  # 1 = right, -1 = left
        self.last_animation_time = time.time()
        self.animation_speed = 0.1  # 100ms per frame
        
        # Server list state
        self.loading = False
        self.error_message = ""
        
        # Login info
        self.username = ""
        self.password = ""
        self.username_active = True
        self.password_active = False
        
    def connect_to_serverlist(self):
        """Connect to server list and fetch servers"""
        self.loading = True
        self.error_message = ""
        
        try:
            # Use PyReborn's static method to get server list
            servers, status_info = RebornClient.get_server_list(self.username, self.password)
            
            if servers:
                self.servers = servers
                # Sort by player count
                self.servers.sort(key=lambda s: s.players, reverse=True)
            else:
                self.error_message = status_info.get('error', 'No servers found')
                
        except Exception as e:
            self.error_message = f"Error: {str(e)}"
        
        self.loading = False
    
    def handle_event(self, event) -> Optional[str]:
        """Handle input events
        
        Returns:
            'connect' if user wants to connect to selected server
            'quit' if user wants to quit
            None otherwise
        """
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # Handle mouse clicks
            mouse_x, mouse_y = event.pos
            
            # Check username field
            username_rect = pygame.Rect(150, 98, 200, 28)
            if username_rect.collidepoint(mouse_x, mouse_y):
                self.username_active = True
                self.password_active = False
            
            # Check password field  
            password_rect = pygame.Rect(500, 98, 200, 28)
            if password_rect.collidepoint(mouse_x, mouse_y):
                self.username_active = False
                self.password_active = True
            
            # Check fetch button
            fetch_rect = pygame.Rect(750, 98, 100, 28)
            if fetch_rect.collidepoint(mouse_x, mouse_y) and not self.loading:
                if self.username and self.password:
                    threading.Thread(target=self.connect_to_serverlist, daemon=True).start()
            
            # Check server list clicks
            if self.servers:
                headers_y = 140 + 40  # Match the drawing position
                for i in range(self.scroll_offset, min(self.scroll_offset + self.max_visible, len(self.servers))):
                    y = headers_y + 20 + (i - self.scroll_offset) * 25
                    rect = pygame.Rect(50, y, 800, 20)
                    if rect.collidepoint(mouse_x, mouse_y):
                        self.selected_index = i
                        # Deactivate input fields
                        self.username_active = False
                        self.password_active = False
                        # Double-click to connect
                        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                            if hasattr(event, 'double') and event.double:
                                return 'connect'
                                
            # Click elsewhere deselects input fields
            if not username_rect.collidepoint(mouse_x, mouse_y) and not password_rect.collidepoint(mouse_x, mouse_y):
                self.username_active = False
                self.password_active = False
                                
        elif event.type == pygame.KEYDOWN:
            if self.username_active or self.password_active:
                # Text input
                if event.key == pygame.K_RETURN:
                    if self.servers and not self.loading:
                        return 'connect'
                    elif not self.loading and self.username and self.password:
                        threading.Thread(target=self.connect_to_serverlist, daemon=True).start()
                elif event.key == pygame.K_TAB:
                    self.username_active = not self.username_active
                    self.password_active = not self.password_active
                elif event.key == pygame.K_BACKSPACE:
                    if self.username_active:
                        self.username = self.username[:-1]
                    else:
                        self.password = self.password[:-1]
                elif event.unicode:
                    if self.username_active and len(self.username) < 20:
                        self.username += event.unicode
                    elif self.password_active and len(self.password) < 20:
                        self.password += event.unicode
            else:
                # Server list navigation - only when we have servers
                if self.servers:
                    # Deactivate input fields when navigating servers
                    self.username_active = False
                    self.password_active = False
                    
                if event.key == pygame.K_UP and self.servers and self.selected_index > 0:
                    self.selected_index -= 1
                    if self.selected_index < self.scroll_offset:
                        self.scroll_offset = self.selected_index
                elif event.key == pygame.K_DOWN and self.servers and self.selected_index < len(self.servers) - 1:
                    self.selected_index += 1
                    if self.selected_index >= self.scroll_offset + self.max_visible:
                        self.scroll_offset = self.selected_index - self.max_visible + 1
                elif event.key == pygame.K_PAGEUP:
                    self.selected_index = max(0, self.selected_index - self.max_visible)
                    self.scroll_offset = max(0, self.scroll_offset - self.max_visible)
                elif event.key == pygame.K_PAGEDOWN:
                    self.selected_index = min(len(self.servers) - 1, self.selected_index + self.max_visible)
                    self.scroll_offset = min(max(0, len(self.servers) - self.max_visible), 
                                           self.scroll_offset + self.max_visible)
                elif event.key == pygame.K_RETURN:
                    if self.servers and not self.loading:
                        return 'connect'
                elif event.key == pygame.K_ESCAPE:
                    return 'quit'
                        
        elif event.type == pygame.MOUSEWHEEL:
            # Scroll with mouse wheel
            if self.servers:
                self.scroll_offset = max(0, min(self.scroll_offset - event.y * 3, 
                                               max(0, len(self.servers) - self.max_visible)))
                
        return None
                        
    def draw(self):
        """Draw the server browser UI"""
        # Background with gradient effect
        self.screen.fill(UI_BG)
        
        # Draw decorative border
        pygame.draw.rect(self.screen, UI_BORDER, self.screen.get_rect(), 3)
        
        # Animated walking character
        self._update_character_animation()
        self._draw_character()
        
        # Title with shadow effect
        title_text = "Classic Reborn Server Browser"
        # Shadow
        shadow = self.title_font.render(title_text, True, BLACK)
        shadow_rect = shadow.get_rect(center=(self.screen.get_width() // 2 + 2, 32))
        self.screen.blit(shadow, shadow_rect)
        # Main title
        title = self.title_font.render(title_text, True, LIGHT_GREEN)
        title_rect = title.get_rect(center=(self.screen.get_width() // 2, 30))
        self.screen.blit(title, title_rect)
        
        # Login section with green theme
        login_y = 75
        login_label = self.font.render("Account Login", True, LIGHT_GREEN)
        self.screen.blit(login_label, (50, login_y))
        
        # Username field
        username_label = self.font.render("Username:", True, UI_TEXT)
        self.screen.blit(username_label, (50, 100))
        username_rect = pygame.Rect(150, 98, 200, 28)
        border_color = LIGHT_GREEN if self.username_active else DARK_GREEN
        pygame.draw.rect(self.screen, UI_HIGHLIGHT, username_rect)
        pygame.draw.rect(self.screen, border_color, username_rect, 2)
        username_text = self.font.render(self.username, True, LIGHT_GREEN)
        self.screen.blit(username_text, (155, 102))
        
        # Password field
        password_label = self.font.render("Password:", True, UI_TEXT)
        self.screen.blit(password_label, (400, 100))
        password_rect = pygame.Rect(500, 98, 200, 28)
        border_color = LIGHT_GREEN if self.password_active else DARK_GREEN
        pygame.draw.rect(self.screen, UI_HIGHLIGHT, password_rect)
        pygame.draw.rect(self.screen, border_color, password_rect, 2)
        password_text = self.font.render("*" * len(self.password), True, LIGHT_GREEN)
        self.screen.blit(password_text, (505, 102))
        
        # Fetch button with green theme
        fetch_rect = pygame.Rect(750, 98, 100, 28)
        button_color = DARK_GREEN if self.loading else GREEN
        pygame.draw.rect(self.screen, button_color, fetch_rect)
        pygame.draw.rect(self.screen, LIGHT_GREEN, fetch_rect, 2)
        fetch_text = self.font.render("Fetch" if not self.loading else "Loading...", True, BLACK if not self.loading else WHITE)
        text_rect = fetch_text.get_rect(center=fetch_rect.center)
        self.screen.blit(fetch_text, text_rect)
        
        # Server list section
        list_y = 140  # Moved up to make more room
        server_label = self.font.render("Server List", True, LIGHT_GREEN)
        self.screen.blit(server_label, (50, list_y))
        
        # Server list box - adjust to fit window and content
        screen_width = self.screen.get_width()
        screen_height = self.screen.get_height()
        list_width = min(810, screen_width - 90)  # Leave 45px margin on each side
        list_height = min(320, screen_height - list_y - 100)  # Dynamic height
        list_rect = pygame.Rect(45, list_y + 30, list_width, list_height)
        pygame.draw.rect(self.screen, UI_HIGHLIGHT, list_rect)
        pygame.draw.rect(self.screen, UI_BORDER, list_rect, 2)
        
        # Draw servers
        if self.servers:
            # Headers with green theme - inside the box
            headers_y = list_y + 40  # Move headers inside the box
            self.screen.blit(self.small_font.render("Server Name", True, LIGHT_GREEN), (60, headers_y))
            self.screen.blit(self.small_font.render("Type", True, LIGHT_GREEN), (300, headers_y))
            self.screen.blit(self.small_font.render("Players", True, LIGHT_GREEN), (450, headers_y))
            self.screen.blit(self.small_font.render("Language", True, LIGHT_GREEN), (550, headers_y))
            self.screen.blit(self.small_font.render("Version", True, LIGHT_GREEN), (650, headers_y))
            self.screen.blit(self.small_font.render("Address", True, LIGHT_GREEN), (720, headers_y))
            
            # Set clipping to keep servers within the box
            old_clip = self.screen.get_clip()
            self.screen.set_clip(list_rect)
            
            # Server entries - start below headers
            max_servers_in_view = min(self.max_visible, (list_height - 60) // 25)  # Calculate based on box height
            for i in range(self.scroll_offset, min(self.scroll_offset + max_servers_in_view, len(self.servers))):
                server = self.servers[i]
                y = headers_y + 20 + (i - self.scroll_offset) * 25  # Start below headers
                
                # Only draw if within the box
                if y + 25 > list_rect.bottom:
                    break
                
                # Highlight selected with green glow
                if i == self.selected_index:
                    highlight_rect = pygame.Rect(50, y - 2, list_width - 10, 24)
                    pygame.draw.rect(self.screen, DARK_GREEN, highlight_rect)
                    pygame.draw.rect(self.screen, GREEN, highlight_rect, 2)
                
                # Server info
                color = LIGHT_GREEN if i == self.selected_index else UI_TEXT
                self.screen.blit(self.small_font.render(server.name[:30], True, color), (60, y + 2))
                self.screen.blit(self.small_font.render(server.type_name[:15], True, color), (300, y + 2))
                self.screen.blit(self.small_font.render(f"{server.players}", True, color), (450, y + 2))
                self.screen.blit(self.small_font.render(server.language[:10], True, color), (550, y + 2))
                self.screen.blit(self.small_font.render(server.version[:8], True, color), (650, y + 2))
                self.screen.blit(self.small_font.render(server.address, True, color), (720, y + 2))
                
            # Restore clipping
            self.screen.set_clip(old_clip)
        elif self.error_message:
            error_text = self.font.render(self.error_message, True, RED)
            self.screen.blit(error_text, (60, list_y + 50))
        else:
            hint_text = self.font.render("Enter username and password, then click Fetch to get server list", True, GRAY)
            self.screen.blit(hint_text, (60, list_y + 50))
            
        # Instructions
        inst_y = self.screen.get_height() - 40
        instructions = "Arrow Keys/Mouse: Navigate | Enter: Connect | Tab: Switch fields | Escape: Quit"
        inst_text = self.small_font.render(instructions, True, GRAY)
        inst_rect = inst_text.get_rect(centerx=self.screen.get_width() // 2, y=inst_y)
        self.screen.blit(inst_text, inst_rect)
            
    def get_selected_server(self) -> Optional[Tuple[str, int]]:
        """Get the currently selected server info
        
        Returns:
            Tuple of (host, port) or None if no server selected
        """
        if self.servers and 0 <= self.selected_index < len(self.servers):
            server = self.servers[self.selected_index]
            return (server.ip, server.port)
        return None
        
    def _update_character_animation(self):
        """Update the walking character animation"""
        current_time = time.time()
        
        # Update animation frame
        if current_time - self.last_animation_time > self.animation_speed:
            self.last_animation_time = current_time
            self.character_frame = (self.character_frame + 1) % 4
            
        # Update position
        self.character_x += self.character_direction * 2
        
        # Bounce off edges
        if self.character_x > self.screen.get_width() - 32:
            self.character_direction = -1
        elif self.character_x < 0:
            self.character_direction = 1
            
    def _draw_character(self):
        """Draw a simple animated character"""
        # Character position
        x = self.character_x
        y = self.character_y
        
        # Simple character made of rectangles
        # Body
        body_color = DARK_GREEN if self.character_frame % 2 == 0 else GREEN
        pygame.draw.rect(self.screen, body_color, (x + 8, y + 12, 16, 12))
        
        # Head
        pygame.draw.circle(self.screen, LIGHT_GREEN, (x + 16, y + 8), 6)
        
        # Eyes
        eye_offset = 2 if self.character_direction > 0 else -2
        pygame.draw.circle(self.screen, BLACK, (x + 16 + eye_offset, y + 7), 2)
        
        # Legs (animated)
        leg_offset = 4 if self.character_frame < 2 else -4
        pygame.draw.rect(self.screen, DARK_GREEN, (x + 10, y + 20, 4, 8))
        pygame.draw.rect(self.screen, DARK_GREEN, (x + 18 + leg_offset // 2, y + 20, 4, 8))
        
        # Arms
        arm_swing = 2 if self.character_frame % 2 == 0 else -2
        pygame.draw.rect(self.screen, DARK_GREEN, (x + 6 + arm_swing, y + 14, 3, 6))
        pygame.draw.rect(self.screen, DARK_GREEN, (x + 23 - arm_swing, y + 14, 3, 6))