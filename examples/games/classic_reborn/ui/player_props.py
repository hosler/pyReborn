"""
Player Properties Debug Window
Shows current player properties and flashes when updated
"""

import pygame
import time
from typing import Dict, Tuple, Optional
from collections import defaultdict

# Colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 100, 255)
YELLOW = (255, 255, 0)
RED = (255, 50, 50)
DARK_GRAY = (40, 40, 40)
LIGHT_GRAY = (100, 100, 100)

# Flash colors
FLASH_SENT = (100, 255, 100)  # Light green for sent
FLASH_RECEIVED = (100, 150, 255)  # Light blue for received

class PlayerPropsWindow:
    """Debug window showing player properties"""
    
    def __init__(self, screen: pygame.Surface, font: pygame.font.Font):
        self.screen = screen
        self.font = font
        self.small_font = pygame.font.Font(None, 20)
        
        # Window position and size
        self.x = 10
        self.y = 100
        self.width = 300
        self.height = 400
        self.visible = False
        
        # Properties to display
        self.important_props = [
            ("NICKNAME", "nickname"),
            ("CURLEVEL", "level"),
            ("X", "x"),
            ("Y", "y"),
            ("X2", "x2"),
            ("Y2", "y2"),
            ("GMAPLEVELX", "gmaplevelx"),
            ("GMAPLEVELY", "gmaplevely"),
            ("SPRITE", "direction"),
            ("GANI", "gani"),
            ("CHAT", "chat"),
            ("STATUS", "status"),
            ("CARRY", "carry_sprite"),
            ("HP", "hearts"),
            ("MAXHP", "max_hearts"),
            ("RUPEES", "rupees"),
            ("BOMBS", "bombs"),
            ("ARROWS", "arrows"),
        ]
        
        # Flash tracking
        self.flash_timers = {}  # prop_name -> (flash_time, flash_color)
        self.flash_duration = 0.5  # seconds
        
        # Dragging
        self.dragging = False
        self.drag_offset_x = 0
        self.drag_offset_y = 0
    
    def toggle(self):
        """Toggle window visibility"""
        self.visible = not self.visible
        if self.visible:
            print("[PROPS] Player properties window opened")
        else:
            print("[PROPS] Player properties window closed")
    
    def handle_event(self, event: pygame.event.Event) -> bool:
        """Handle input events. Returns True if event was consumed."""
        if not self.visible:
            return False
            
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:  # Left click
                # Check if clicking on title bar
                mouse_x, mouse_y = event.pos
                if (self.x <= mouse_x <= self.x + self.width and 
                    self.y <= mouse_y <= self.y + 25):
                    self.dragging = True
                    self.drag_offset_x = mouse_x - self.x
                    self.drag_offset_y = mouse_y - self.y
                    return True
                    
        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                self.dragging = False
                
        elif event.type == pygame.MOUSEMOTION:
            if self.dragging:
                mouse_x, mouse_y = event.pos
                self.x = mouse_x - self.drag_offset_x
                self.y = mouse_y - self.drag_offset_y
                return True
                
        return False
    
    def flash_property_sent(self, prop_name: str):
        """Flash property green when sent to server"""
        self.flash_timers[prop_name] = (time.time(), FLASH_SENT)
    
    def flash_property_received(self, prop_name: str):
        """Flash property blue when received from server"""
        self.flash_timers[prop_name] = (time.time(), FLASH_RECEIVED)
    
    def render(self, player):
        """Render the properties window"""
        if not self.visible or not player:
            return
            
        current_time = time.time()
        
        # Window background
        window_rect = pygame.Rect(self.x, self.y, self.width, self.height)
        pygame.draw.rect(self.screen, DARK_GRAY, window_rect)
        pygame.draw.rect(self.screen, WHITE, window_rect, 2)
        
        # Title bar
        title_rect = pygame.Rect(self.x, self.y, self.width, 25)
        pygame.draw.rect(self.screen, LIGHT_GRAY, title_rect)
        pygame.draw.rect(self.screen, WHITE, title_rect, 1)
        
        # Title text
        title = self.font.render("Player Properties", True, WHITE)
        title_x = self.x + (self.width - title.get_width()) // 2
        self.screen.blit(title, (title_x, self.y + 3))
        
        # Properties
        y_offset = self.y + 30
        line_height = 22
        
        for prop_display, prop_attr in self.important_props:
            # Get property value
            if prop_attr == "direction":
                # Convert direction enum to string
                value = str(getattr(player, prop_attr, "?")).split('.')[-1]
            else:
                value = getattr(player, prop_attr, None)
                
            # Format value
            if value is None:
                value_str = "None"
                value_color = LIGHT_GRAY
            elif isinstance(value, float):
                value_str = f"{value:.2f}"
                value_color = WHITE
            else:
                value_str = str(value)
                value_color = WHITE
                
            # Check for flash
            flash_color = None
            if prop_display in self.flash_timers:
                flash_time, color = self.flash_timers[prop_display]
                if current_time - flash_time < self.flash_duration:
                    # Calculate flash intensity
                    flash_progress = (current_time - flash_time) / self.flash_duration
                    flash_intensity = 1.0 - flash_progress
                    flash_color = color
                    
            # Render property name
            prop_text = self.small_font.render(f"{prop_display}:", True, YELLOW)
            self.screen.blit(prop_text, (self.x + 5, y_offset))
            
            # Render value with flash effect
            if flash_color:
                # Create flash background
                value_text = self.small_font.render(value_str, True, BLACK)
                text_rect = value_text.get_rect()
                text_rect.x = self.x + 120
                text_rect.y = y_offset
                
                # Draw flash background with fade
                flash_rect = text_rect.inflate(4, 2)
                flash_surface = pygame.Surface((flash_rect.width, flash_rect.height))
                flash_surface.fill(flash_color)
                flash_surface.set_alpha(int(255 * flash_intensity))
                self.screen.blit(flash_surface, flash_rect)
            else:
                value_text = self.small_font.render(value_str, True, value_color)
                
            self.screen.blit(value_text, (self.x + 120, y_offset))
            
            y_offset += line_height
            
            # Stop if we're out of space
            if y_offset > self.y + self.height - 10:
                break
        
        # Clean up old flash timers
        self.flash_timers = {
            k: v for k, v in self.flash_timers.items() 
            if current_time - v[0] < self.flash_duration
        }
        
        # Legend at bottom
        legend_y = self.y + self.height - 25
        sent_text = self.small_font.render("Sent", True, FLASH_SENT)
        recv_text = self.small_font.render("Received", True, FLASH_RECEIVED)
        self.screen.blit(sent_text, (self.x + 10, legend_y))
        self.screen.blit(recv_text, (self.x + 60, legend_y))
        
    def notify_property_sent(self, prop_id: int, prop_name: Optional[str] = None):
        """Notify that a property was sent to server"""
        # Map property IDs to display names
        prop_map = {
            0: "NICKNAME",
            2: "HP",
            3: "RUPEES", 
            4: "ARROWS",
            5: "BOMBS",
            10: "GANI",
            11: "HEAD",
            12: "CHAT",
            13: "COLORS",
            15: "X",
            16: "Y",
            17: "SPRITE",
            18: "STATUS",
            19: "CARRY",
            20: "CURLEVEL",
            31: "UDPPORT",
            35: "BODY",
            75: "OSTYPE",
            76: "CODEPAGE",
            78: "X2",
            79: "Y2",
            80: "Z2",
            83: "GMAPLEVELX",
            84: "GMAPLEVELY",
        }
        
        display_name = prop_name or prop_map.get(prop_id, f"PROP_{prop_id}")
        self.flash_property_sent(display_name)
        
    def notify_property_received(self, prop_id: int, player_id: int, is_local: bool):
        """Notify that a property was received from server"""
        if not is_local:
            return  # Only track local player props
            
        # Map property IDs to display names
        prop_map = {
            0: "NICKNAME",
            2: "HP",
            3: "RUPEES",
            4: "ARROWS", 
            5: "BOMBS",
            10: "GANI",
            11: "HEAD",
            12: "CHAT",
            13: "COLORS",
            15: "X",
            16: "Y",
            17: "SPRITE",
            18: "STATUS",
            19: "CARRY",
            20: "CURLEVEL",
            78: "X2",
            79: "Y2",
            80: "Z2",
            83: "GMAPLEVELX",
            84: "GMAPLEVELY",
        }
        
        display_name = prop_map.get(prop_id, f"PROP_{prop_id}")
        self.flash_property_received(display_name)