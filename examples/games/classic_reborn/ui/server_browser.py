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
        self.character_x = 100
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
        
        # Version selection - show all tested and working versions
        self.supported_versions = [
            "2.17", "2.19", "2.21", "2.22", "3.0", 
            "5.07", "5.12", "6.015", "6.034", "6.037"
        ]
        self.selected_version = "6.037"  # Default to latest tested version
        self.version_dropdown_open = False
        
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
            
            # Calculate centered positions (match drawing code)
            screen_center_x = self.screen.get_width() // 2
            total_width = 550
            start_x = screen_center_x - total_width // 2
            input_y = 100
            version_y = 130
            
            # Check username field
            username_rect = pygame.Rect(start_x + 100, input_y - 2, 180, 28)
            if username_rect.collidepoint(mouse_x, mouse_y):
                self.username_active = True
                self.password_active = False
            
            # Check password field  
            password_rect = pygame.Rect(start_x + 400, input_y - 2, 150, 28)
            if password_rect.collidepoint(mouse_x, mouse_y):
                self.username_active = False
                self.password_active = True
            
            # Check fetch button
            fetch_rect = pygame.Rect(screen_center_x + 120, version_y - 2, 100, 28)
            if fetch_rect.collidepoint(mouse_x, mouse_y) and not self.loading:
                if self.username and self.password:
                    threading.Thread(target=self.connect_to_serverlist, daemon=True).start()
            
            # Check version dropdown
            version_rect = pygame.Rect(screen_center_x + 10, version_y - 2, 100, 28)
            if version_rect.collidepoint(mouse_x, mouse_y):
                self.version_dropdown_open = not self.version_dropdown_open
            elif self.version_dropdown_open:
                # Check dropdown items
                item_height = 30
                dropdown_height = len(self.supported_versions) * item_height
                max_height = self.screen.get_height() - version_rect.bottom - 50
                if dropdown_height > max_height:
                    dropdown_height = max_height
                dropdown_rect = pygame.Rect(version_rect.x, version_rect.bottom, 100, dropdown_height)
                if dropdown_rect.collidepoint(mouse_x, mouse_y):
                    item_index = (mouse_y - dropdown_rect.y) // item_height
                    if 0 <= item_index < len(self.supported_versions):
                        self.selected_version = self.supported_versions[item_index]
                        self.version_dropdown_open = False
                else:
                    # Click outside dropdown closes it
                    self.version_dropdown_open = False
            
            # Check server list clicks
            if self.servers:
                list_y = 170
                headers_y = list_y + 40  # Match the drawing position
                list_width = min(900, self.screen.get_width() - 100)
                list_x = screen_center_x - list_width // 2
                for i in range(self.scroll_offset, min(self.scroll_offset + self.max_visible, len(self.servers))):
                    y = headers_y + 20 + (i - self.scroll_offset) * 25
                    rect = pygame.Rect(list_x, y, list_width - 10, 20)
                    if rect.collidepoint(mouse_x, mouse_y):
                        self.selected_index = i
                        # Deactivate input fields
                        self.username_active = False
                        self.password_active = False
                        # Double-click to connect
                        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                            if hasattr(event, 'double') and event.double:
                                return 'connect'
                                
            # Click elsewhere deselects input fields (recalculate rects)
            username_rect = pygame.Rect(start_x + 100, input_y - 2, 180, 28)
            password_rect = pygame.Rect(start_x + 400, input_y - 2, 150, 28)
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
        
        # Center the main UI content
        screen_center_x = self.screen.get_width() // 2
        
        # Login section with green theme - centered
        login_y = 75
        login_label = self.font.render("Account Login", True, LIGHT_GREEN)
        login_label_rect = login_label.get_rect(centerx=screen_center_x, y=login_y)
        self.screen.blit(login_label, login_label_rect)
        
        # Username field - centered layout
        input_y = 100
        total_width = 550  # Total width of login controls
        start_x = screen_center_x - total_width // 2
        
        username_label = self.font.render("Username:", True, UI_TEXT)
        self.screen.blit(username_label, (start_x, input_y))
        username_rect = pygame.Rect(start_x + 100, input_y - 2, 180, 28)
        border_color = LIGHT_GREEN if self.username_active else DARK_GREEN
        pygame.draw.rect(self.screen, UI_HIGHLIGHT, username_rect)
        pygame.draw.rect(self.screen, border_color, username_rect, 2)
        username_text = self.font.render(self.username, True, LIGHT_GREEN)
        self.screen.blit(username_text, (username_rect.x + 5, username_rect.y + 4))
        
        # Password field
        password_label = self.font.render("Password:", True, UI_TEXT)
        self.screen.blit(password_label, (start_x + 300, input_y))
        password_rect = pygame.Rect(start_x + 400, input_y - 2, 150, 28)
        border_color = LIGHT_GREEN if self.password_active else DARK_GREEN
        pygame.draw.rect(self.screen, UI_HIGHLIGHT, password_rect)
        pygame.draw.rect(self.screen, border_color, password_rect, 2)
        password_text = self.font.render("*" * len(self.password), True, LIGHT_GREEN)
        self.screen.blit(password_text, (password_rect.x + 5, password_rect.y + 4))
        
        # Version dropdown
        version_y = 130
        version_label = self.font.render("Client Version:", True, UI_TEXT)
        version_label_rect = version_label.get_rect(centerx=screen_center_x - 80, y=version_y)
        self.screen.blit(version_label, version_label_rect)
        version_rect = pygame.Rect(screen_center_x + 10, version_y - 2, 100, 28)
        pygame.draw.rect(self.screen, UI_HIGHLIGHT, version_rect)
        pygame.draw.rect(self.screen, LIGHT_GREEN if self.version_dropdown_open else DARK_GREEN, version_rect, 2)
        version_text = self.font.render(self.selected_version, True, LIGHT_GREEN)
        self.screen.blit(version_text, (version_rect.x + 8, version_rect.y + 5))
        
        # Fetch button with green theme
        fetch_rect = pygame.Rect(screen_center_x + 120, version_y - 2, 100, 28)
        button_color = DARK_GREEN if self.loading else GREEN
        pygame.draw.rect(self.screen, button_color, fetch_rect)
        pygame.draw.rect(self.screen, LIGHT_GREEN, fetch_rect, 2)
        fetch_text = self.font.render("Fetch" if not self.loading else "Loading...", True, BLACK if not self.loading else WHITE)
        text_rect = fetch_text.get_rect(center=fetch_rect.center)
        self.screen.blit(fetch_text, text_rect)
        
        
        # Version dropdown menu - improved visibility
        if self.version_dropdown_open:
            # Calculate height to show all versions
            item_height = 30  # Taller items for better readability
            dropdown_height = len(self.supported_versions) * item_height
            max_height = self.screen.get_height() - version_rect.bottom - 50  # Leave room at bottom
            
            if dropdown_height > max_height:
                dropdown_height = max_height
                # Add scroll capability if needed
            
            dropdown_rect = pygame.Rect(version_rect.x, version_rect.bottom, 100, dropdown_height)
            
            # Draw dropdown background with dark border
            pygame.draw.rect(self.screen, (5, 15, 5), dropdown_rect)  # Darker background
            pygame.draw.rect(self.screen, LIGHT_GREEN, dropdown_rect, 2)
            
            # Draw all versions
            y_offset = 0
            for i, version in enumerate(self.supported_versions):
                if y_offset + item_height <= dropdown_height:
                    item_rect = pygame.Rect(dropdown_rect.x, dropdown_rect.y + y_offset, 100, item_height)
                    
                    # Highlight hovered item
                    if item_rect.collidepoint(pygame.mouse.get_pos()):
                        pygame.draw.rect(self.screen, UI_HIGHLIGHT, item_rect)
                        pygame.draw.rect(self.screen, GREEN, item_rect, 1)
                    
                    # Draw version text with better font
                    text_color = WHITE if item_rect.collidepoint(pygame.mouse.get_pos()) else LIGHT_GREEN
                    text = self.font.render(version, True, text_color)
                    text_rect = text.get_rect(centerx=item_rect.centerx, centery=item_rect.centery)
                    self.screen.blit(text, text_rect)
                    
                    y_offset += item_height
        
        # Server list section - centered
        list_y = 170  # More space for version dropdown
        server_label = self.font.render("Server List", True, LIGHT_GREEN)
        server_label_rect = server_label.get_rect(centerx=screen_center_x, y=list_y)
        self.screen.blit(server_label, server_label_rect)
        
        # Server list box - centered and properly sized
        screen_width = self.screen.get_width()
        screen_height = self.screen.get_height()
        list_width = min(900, screen_width - 100)  # Leave 50px margin on each side
        list_height = min(350, screen_height - list_y - 80)  # Dynamic height
        list_x = screen_center_x - list_width // 2
        list_rect = pygame.Rect(list_x, list_y + 30, list_width, list_height)
        pygame.draw.rect(self.screen, UI_HIGHLIGHT, list_rect)
        pygame.draw.rect(self.screen, UI_BORDER, list_rect, 2)
        
        # Draw servers
        if self.servers:
            # Headers with green theme - inside the box, centered
            headers_y = list_y + 40  # Move headers inside the box
            header_x = list_x + 15  # Offset from left edge of box
            self.screen.blit(self.small_font.render("Server Name", True, LIGHT_GREEN), (header_x, headers_y))
            self.screen.blit(self.small_font.render("Type", True, LIGHT_GREEN), (header_x + 250, headers_y))
            self.screen.blit(self.small_font.render("Players", True, LIGHT_GREEN), (header_x + 350, headers_y))
            self.screen.blit(self.small_font.render("Language", True, LIGHT_GREEN), (header_x + 420, headers_y))
            self.screen.blit(self.small_font.render("Version", True, LIGHT_GREEN), (header_x + 520, headers_y))
            self.screen.blit(self.small_font.render("Address", True, LIGHT_GREEN), (header_x + 620, headers_y))
            
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
                    highlight_rect = pygame.Rect(list_x + 5, y - 2, list_width - 15, 24)
                    pygame.draw.rect(self.screen, DARK_GREEN, highlight_rect)
                    pygame.draw.rect(self.screen, GREEN, highlight_rect, 2)
                
                # Server info - aligned with headers
                color = LIGHT_GREEN if i == self.selected_index else UI_TEXT
                row_x = list_x + 15
                self.screen.blit(self.small_font.render(server.name[:30], True, color), (row_x, y + 2))
                self.screen.blit(self.small_font.render(server.type_name[:15], True, color), (row_x + 250, y + 2))
                self.screen.blit(self.small_font.render(f"{server.players}", True, color), (row_x + 350, y + 2))
                self.screen.blit(self.small_font.render(server.language[:10], True, color), (row_x + 420, y + 2))
                self.screen.blit(self.small_font.render(server.version[:8], True, color), (row_x + 520, y + 2))
                self.screen.blit(self.small_font.render(server.address, True, color), (row_x + 620, y + 2))
                
            # Restore clipping
            self.screen.set_clip(old_clip)
        elif self.error_message:
            error_text = self.font.render(self.error_message, True, RED)
            error_rect = error_text.get_rect(centerx=screen_center_x, y=list_y + 60)
            self.screen.blit(error_text, error_rect)
        else:
            hint_text = self.font.render("Enter username and password, then click Fetch to get server list", True, GRAY)
            hint_rect = hint_text.get_rect(centerx=screen_center_x, y=list_y + 60)
            self.screen.blit(hint_text, hint_rect)
            
        # Instructions
        inst_y = self.screen.get_height() - 40
        instructions = "Arrow Keys/Mouse: Navigate | Enter: Connect | Tab: Switch fields | Escape: Quit"
        inst_text = self.small_font.render(instructions, True, GRAY)
        inst_rect = inst_text.get_rect(centerx=self.screen.get_width() // 2, y=inst_y)
        self.screen.blit(inst_text, inst_rect)
            
    def get_selected_server(self) -> Optional[Tuple[str, int, str]]:
        """Get the currently selected server info with version
        
        Returns:
            Tuple of (host, port, version) or None if no server selected
        """
        if self.servers and 0 <= self.selected_index < len(self.servers):
            server = self.servers[self.selected_index]
            return (server.ip, server.port, self.selected_version)
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
        """Draw a Graal-style character"""
        # Character position
        x = self.character_x
        y = self.character_y
        
        # Graal-style character (16x16 sprite size)
        char_size = 16
        
        # Body (tunic style)
        body_color = (0, 100, 50) if self.character_frame % 2 == 0 else (0, 120, 60)
        pygame.draw.rect(self.screen, body_color, (x + 4, y + 8, 8, 10))
        
        # Head (flesh tone)
        head_color = (255, 220, 177)
        pygame.draw.rect(self.screen, head_color, (x + 5, y + 2, 6, 6))
        
        # Hair (blonde)
        hair_color = (255, 215, 0)
        pygame.draw.rect(self.screen, hair_color, (x + 5, y + 1, 6, 3))
        
        # Eyes (facing direction)
        eye_color = BLACK
        if self.character_direction > 0:  # Facing right
            pygame.draw.rect(self.screen, eye_color, (x + 8, y + 4, 1, 1))
        else:  # Facing left  
            pygame.draw.rect(self.screen, eye_color, (x + 7, y + 4, 1, 1))
        
        # Legs (animated walking)
        leg_color = (139, 69, 19)  # Brown pants
        if self.character_frame < 2:
            # Left leg forward
            pygame.draw.rect(self.screen, leg_color, (x + 5, y + 16, 2, 6))
            pygame.draw.rect(self.screen, leg_color, (x + 9, y + 18, 2, 4))
        else:
            # Right leg forward
            pygame.draw.rect(self.screen, leg_color, (x + 5, y + 18, 2, 4))
            pygame.draw.rect(self.screen, leg_color, (x + 9, y + 16, 2, 6))
        
        # Arms (swinging)
        arm_color = head_color  # Same as skin
        arm_swing = 1 if self.character_frame % 2 == 0 else -1
        
        if self.character_direction > 0:  # Facing right
            # Left arm (back)
            pygame.draw.rect(self.screen, arm_color, (x + 3 - arm_swing, y + 9, 2, 5))
            # Right arm (front)
            pygame.draw.rect(self.screen, arm_color, (x + 11 + arm_swing, y + 9, 2, 5))
        else:  # Facing left
            # Right arm (back)
            pygame.draw.rect(self.screen, arm_color, (x + 11 + arm_swing, y + 9, 2, 5))
            # Left arm (front)
            pygame.draw.rect(self.screen, arm_color, (x + 3 - arm_swing, y + 9, 2, 5))
        
        # Sword (on back)
        sword_color = (192, 192, 192)  # Silver
        sword_handle = (139, 69, 19)  # Brown handle
        pygame.draw.rect(self.screen, sword_color, (x + 1, y + 6, 1, 8))
        pygame.draw.rect(self.screen, sword_handle, (x + 1, y + 12, 1, 2))
        
        # Shield (small, on arm)
        shield_color = (160, 82, 45)  # Brown shield
        if self.character_direction > 0:
            pygame.draw.rect(self.screen, shield_color, (x + 2, y + 10, 2, 3))
        else:
            pygame.draw.rect(self.screen, shield_color, (x + 12, y + 10, 2, 3))