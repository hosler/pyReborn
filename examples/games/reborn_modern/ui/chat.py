"""
Chat UI
========

Modern chat interface with history and commands.
"""

import pygame
import logging
from typing import List, Optional, Tuple
from dataclasses import dataclass
from collections import deque
import time

from pyreborn.api.outgoing_packets import OutgoingPacketAPI


logger = logging.getLogger(__name__)


@dataclass
class ChatMessage:
    """Single chat message"""
    text: str
    player_id: Optional[int] = None
    player_name: Optional[str] = None
    timestamp: float = 0.0
    color: Tuple[int, int, int] = (200, 200, 220)
    message_type: str = "chat"  # chat, system, private, guild


class ChatUI:
    """Modern chat interface"""
    
    def __init__(self, screen: pygame.Surface, packet_api: OutgoingPacketAPI):
        """Initialize chat UI
        
        Args:
            screen: Pygame surface to render to
            packet_api: API for sending chat messages
        """
        self.screen = screen
        self.packet_api = packet_api
        
        # UI configuration
        self.margin = 10
        self.padding = 5
        self.line_height = 18
        self.max_visible_lines = 10
        self.max_history = 100
        
        # Position and size
        self.width = 400
        self.height = self.line_height * self.max_visible_lines + self.padding * 2 + 30
        self.x = self.margin
        self.y = self.screen.get_height() - self.height - self.margin
        
        # Colors
        self.bg_color = (20, 20, 30, 180)
        self.input_bg_color = (30, 30, 45, 200)
        self.border_color = (100, 100, 120)
        self.text_color = (200, 200, 220)
        self.system_color = (150, 150, 200)
        self.private_color = (200, 150, 200)
        self.guild_color = (150, 200, 150)
        
        # Fonts
        self.chat_font = pygame.font.Font(None, 16)
        self.input_font = pygame.font.Font(None, 18)
        
        # Chat state
        self.messages: deque[ChatMessage] = deque(maxlen=self.max_history)
        self.input_text = ""
        self.input_active = False
        self.cursor_pos = 0
        self.scroll_offset = 0
        
        # Command history
        self.command_history: List[str] = []
        self.history_index = -1
        
        # Chat modes
        self.chat_mode = "all"  # all, guild, private
        self.private_target = None
        
        # Add welcome message
        self.add_system_message("Welcome to Reborn Modern! Press Enter to chat.")
        
        logger.info("Chat UI initialized")
    
    def handle_event(self, event: pygame.event.Event):
        """Handle input event"""
        if not self.input_active:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
                self.input_active = True
                return True
            return False
        
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                # Cancel input
                self.input_active = False
                self.input_text = ""
                self.cursor_pos = 0
                
            elif event.key == pygame.K_RETURN:
                # Send message
                if self.input_text.strip():
                    self._send_message()
                self.input_active = False
                self.input_text = ""
                self.cursor_pos = 0
                
            elif event.key == pygame.K_BACKSPACE:
                # Delete character
                if self.cursor_pos > 0:
                    self.input_text = (self.input_text[:self.cursor_pos-1] + 
                                     self.input_text[self.cursor_pos:])
                    self.cursor_pos -= 1
                    
            elif event.key == pygame.K_DELETE:
                # Delete forward
                if self.cursor_pos < len(self.input_text):
                    self.input_text = (self.input_text[:self.cursor_pos] + 
                                     self.input_text[self.cursor_pos+1:])
                    
            elif event.key == pygame.K_LEFT:
                # Move cursor left
                self.cursor_pos = max(0, self.cursor_pos - 1)
                
            elif event.key == pygame.K_RIGHT:
                # Move cursor right
                self.cursor_pos = min(len(self.input_text), self.cursor_pos + 1)
                
            elif event.key == pygame.K_HOME:
                # Move to start
                self.cursor_pos = 0
                
            elif event.key == pygame.K_END:
                # Move to end
                self.cursor_pos = len(self.input_text)
                
            elif event.key == pygame.K_UP:
                # Command history up
                if self.command_history and self.history_index < len(self.command_history) - 1:
                    self.history_index += 1
                    self.input_text = self.command_history[-(self.history_index + 1)]
                    self.cursor_pos = len(self.input_text)
                    
            elif event.key == pygame.K_DOWN:
                # Command history down
                if self.history_index > -1:
                    self.history_index -= 1
                    if self.history_index == -1:
                        self.input_text = ""
                    else:
                        self.input_text = self.command_history[-(self.history_index + 1)]
                    self.cursor_pos = len(self.input_text)
                    
            else:
                # Type character
                char = event.unicode
                if char and char.isprintable() and len(self.input_text) < 200:
                    self.input_text = (self.input_text[:self.cursor_pos] + 
                                     char + 
                                     self.input_text[self.cursor_pos:])
                    self.cursor_pos += 1
        
        elif event.type == pygame.MOUSEWHEEL:
            # Scroll chat history
            if event.y > 0:
                self.scroll_offset = min(self.scroll_offset + 1, 
                                       max(0, len(self.messages) - self.max_visible_lines))
            else:
                self.scroll_offset = max(self.scroll_offset - 1, 0)
        
        return True
    
    def update(self, dt: float):
        """Update chat UI"""
        # Remove old messages (optional fade out)
        # For now, keep all messages
        pass
    
    def render(self):
        """Render chat UI"""
        # Create chat surface
        chat_surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        
        # Background
        chat_surface.fill(self.bg_color)
        pygame.draw.rect(chat_surface, self.border_color, chat_surface.get_rect(), 1)
        
        # Chat messages
        self._render_messages(chat_surface)
        
        # Input box
        self._render_input(chat_surface)
        
        # Mode indicator
        if self.chat_mode != "all":
            self._render_mode_indicator(chat_surface)
        
        # Blit to screen
        self.screen.blit(chat_surface, (self.x, self.y))
    
    def _render_messages(self, surface: pygame.Surface):
        """Render chat messages"""
        y = self.padding
        
        # Calculate visible messages
        start_idx = max(0, len(self.messages) - self.max_visible_lines - self.scroll_offset)
        end_idx = len(self.messages) - self.scroll_offset
        visible_messages = list(self.messages)[start_idx:end_idx]
        
        # Render each message
        for message in visible_messages:
            # Format message
            if message.player_name:
                text = f"{message.player_name}: {message.text}"
            else:
                text = message.text
            
            # Render with word wrap
            lines = self._wrap_text(text, self.width - self.padding * 2)
            for line in lines:
                if y + self.line_height > self.height - 35:
                    break
                    
                text_surface = self.chat_font.render(line, True, message.color)
                surface.blit(text_surface, (self.padding, y))
                y += self.line_height
    
    def _render_input(self, surface: pygame.Surface):
        """Render input box"""
        input_y = self.height - 30
        input_rect = pygame.Rect(self.padding, input_y, 
                               self.width - self.padding * 2, 25)
        
        # Background
        color = self.input_bg_color if self.input_active else (30, 30, 40, 150)
        pygame.draw.rect(surface, color, input_rect)
        pygame.draw.rect(surface, self.border_color, input_rect, 1)
        
        # Input text
        if self.input_text or self.input_active:
            # Create text with cursor
            display_text = self.input_text
            if self.input_active:
                # Insert cursor
                display_text = (display_text[:self.cursor_pos] + "|" + 
                              display_text[self.cursor_pos:])
            
            text_surface = self.input_font.render(display_text, True, self.text_color)
            
            # Clip to input box
            text_rect = text_surface.get_rect(midleft=(input_rect.x + 5, input_rect.centery))
            if text_rect.width > input_rect.width - 10:
                # Scroll text to keep cursor visible
                cursor_x = self.input_font.size(self.input_text[:self.cursor_pos])[0]
                if cursor_x > input_rect.width - 20:
                    text_rect.x = input_rect.x + 5 - (cursor_x - input_rect.width + 20)
            
            # Clip and render
            clip_rect = surface.get_clip()
            surface.set_clip(input_rect)
            surface.blit(text_surface, text_rect)
            surface.set_clip(clip_rect)
        else:
            # Placeholder text
            placeholder = "Press Enter to chat..."
            text_surface = self.input_font.render(placeholder, True, (100, 100, 120))
            text_rect = text_surface.get_rect(midleft=(input_rect.x + 5, input_rect.centery))
            surface.blit(text_surface, text_rect)
    
    def _render_mode_indicator(self, surface: pygame.Surface):
        """Render chat mode indicator"""
        mode_text = f"[{self.chat_mode.upper()}]"
        if self.chat_mode == "private" and self.private_target:
            mode_text = f"[PM: {self.private_target}]"
            
        mode_surface = self.chat_font.render(mode_text, True, self.private_color)
        surface.blit(mode_surface, (self.width - mode_surface.get_width() - 5, 5))
    
    def _wrap_text(self, text: str, max_width: int) -> List[str]:
        """Wrap text to fit width"""
        words = text.split(' ')
        lines = []
        current_line = []
        
        for word in words:
            test_line = ' '.join(current_line + [word])
            if self.chat_font.size(test_line)[0] <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]
        
        if current_line:
            lines.append(' '.join(current_line))
        
        return lines if lines else [""]
    
    def _send_message(self):
        """Send chat message"""
        message = self.input_text.strip()
        if not message:
            return
        
        # Add to command history
        self.command_history.append(message)
        if len(self.command_history) > 50:
            self.command_history.pop(0)
        self.history_index = -1
        
        # Check for commands
        if message.startswith('/'):
            self._handle_command(message)
        else:
            # Send chat message
            try:
                self.packet_api.send_chat(message)
                # Local echo (server will send back the actual message)
                # self.add_message(message, player_name="You")
            except Exception as e:
                logger.error(f"Failed to send chat message: {e}")
                self.add_system_message(f"Failed to send message: {e}")
    
    def _handle_command(self, command: str):
        """Handle chat command"""
        parts = command[1:].split(' ', 1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        
        if cmd == "help":
            self.add_system_message("Available commands:")
            self.add_system_message("/help - Show this help")
            self.add_system_message("/pm <player> <message> - Send private message")
            self.add_system_message("/guild <message> - Send guild message")
            self.add_system_message("/clear - Clear chat history")
            
        elif cmd == "pm" or cmd == "whisper":
            if args:
                parts = args.split(' ', 1)
                if len(parts) >= 2:
                    target = parts[0]
                    message = parts[1]
                    try:
                        self.packet_api.send_private_message(target, message)
                        self.add_message(message, player_name=f"You -> {target}", 
                                       color=self.private_color)
                    except Exception as e:
                        self.add_system_message(f"Failed to send PM: {e}")
                else:
                    self.add_system_message("Usage: /pm <player> <message>")
            else:
                self.add_system_message("Usage: /pm <player> <message>")
                
        elif cmd == "guild":
            if args:
                # TODO: Implement guild chat
                self.add_system_message("Guild chat not yet implemented")
            else:
                self.add_system_message("Usage: /guild <message>")
                
        elif cmd == "clear":
            self.messages.clear()
            self.add_system_message("Chat cleared")
            
        else:
            self.add_system_message(f"Unknown command: {cmd}")
    
    def add_message(self, text: str, player_id: Optional[int] = None,
                   player_name: Optional[str] = None,
                   color: Optional[Tuple[int, int, int]] = None):
        """Add chat message
        
        Args:
            text: Message text
            player_id: ID of player who sent message
            player_name: Name of player
            color: Message color
        """
        message = ChatMessage(
            text=text,
            player_id=player_id,
            player_name=player_name,
            timestamp=time.time(),
            color=color or self.text_color,
            message_type="chat"
        )
        
        self.messages.append(message)
        
        # Auto-scroll to bottom if not scrolled up
        if self.scroll_offset == 0:
            self.scroll_offset = 0
    
    def add_system_message(self, text: str):
        """Add system message"""
        message = ChatMessage(
            text=text,
            timestamp=time.time(),
            color=self.system_color,
            message_type="system"
        )
        self.messages.append(message)
    
    def is_active(self) -> bool:
        """Check if chat input is active"""
        return self.input_active
    
    def set_position(self, x: int, y: int):
        """Set chat UI position"""
        self.x = x
        self.y = y