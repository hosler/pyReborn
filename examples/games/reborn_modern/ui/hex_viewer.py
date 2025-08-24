#!/usr/bin/env python3
"""
Enhanced Hex Viewer Component
=============================

A professional hex viewer widget for packet inspection with features like:
- Proper spacing and formatting
- ASCII sidebar
- Byte highlighting
- Selection support
- Multiple view modes
"""

import pygame
from typing import Optional, Tuple, List, Dict
import math


class HexViewer:
    """Professional hex viewer for packet data analysis"""
    
    def __init__(self, x: int, y: int, width: int, height: int):
        """Initialize hex viewer
        
        Args:
            x, y: Position on screen
            width, height: Dimensions of viewer
        """
        self.rect = pygame.Rect(x, y, width, height)
        
        # Data
        self.data: bytes = b''
        self.offset: int = 0
        self.bytes_per_row: int = 16
        
        # Selection
        self.selection_start: Optional[int] = None
        self.selection_end: Optional[int] = None
        self.hovered_byte: Optional[int] = None
        
        # Display settings
        self.show_ascii: bool = True
        self.show_offset: bool = True
        self.highlight_changes: bool = False
        self.previous_data: Optional[bytes] = None
        
        # Colors
        self.bg_color = (25, 30, 35)
        self.text_color = (200, 200, 220)
        self.offset_color = (100, 100, 120)
        self.hex_color = (150, 200, 150)
        self.ascii_color = (200, 200, 100)
        self.selection_bg = (60, 80, 120)
        self.hover_bg = (50, 60, 80)
        self.changed_color = (255, 150, 150)
        self.grid_color = (40, 45, 50)
        self.header_bg = (35, 40, 45)
        
        # Fonts
        self.mono_font = pygame.font.Font(pygame.font.match_font('monospace'), 12)
        self.header_font = pygame.font.Font(pygame.font.match_font('monospace'), 11)
        
        # Calculate layout
        self._calculate_layout()
        
        # Scroll
        self.scroll_offset = 0
        self.max_scroll = 0
        
        # Field mapping (offset -> field_name)
        self.field_map: Dict[int, str] = {}
        
    def _calculate_layout(self):
        """Calculate layout dimensions based on font size"""
        # Get character dimensions
        char_surface = self.mono_font.render('0', True, self.text_color)
        self.char_width = char_surface.get_width()
        self.char_height = char_surface.get_height()
        
        # Available width for content (minus scrollbar)
        available_width = self.rect.width - 20  # Leave space for scrollbar
        
        # Calculate how many bytes we can fit per row
        # Each byte needs: 3 chars for hex + 1 char for ASCII + spacing
        min_bytes_per_row = 8
        max_bytes_per_row = 16
        
        # Calculate space needed
        offset_space = self.char_width * 6 if self.show_offset else 0  # "0000: "
        
        # Default to 16 bytes per row, or 8 if space is tight
        if available_width > 600:
            self.bytes_per_row = 16
        else:
            self.bytes_per_row = 8
        
        # Recalculate with chosen bytes_per_row
        self.offset_width = offset_space
        self.hex_width = self.char_width * (self.bytes_per_row * 3 + self.bytes_per_row // 4)
        self.ascii_width = self.char_width * self.bytes_per_row if self.show_ascii else 0
        
        # Position content
        self.content_x = self.rect.x + self.offset_width + 10
        self.content_width = self.hex_width
        
        # Make sure ASCII doesn't go off screen
        max_ascii_x = self.rect.x + self.rect.width - self.ascii_width - 20
        self.ascii_x = min(self.content_x + self.hex_width + 20, max_ascii_x)
        
        # Header height
        self.header_height = 25
        self.content_y = self.rect.y + self.header_height
        self.content_height = self.rect.height - self.header_height
        
        # Visible rows
        self.visible_rows = self.content_height // (self.char_height + 2)
        
    def set_data(self, data: bytes, field_map: Optional[Dict[int, str]] = None):
        """Set data to display
        
        Args:
            data: Bytes to display
            field_map: Optional mapping of offset to field names
        """
        self.previous_data = self.data if self.highlight_changes else None
        self.data = data
        self.field_map = field_map or {}
        
        # Calculate max scroll
        total_rows = math.ceil(len(data) / self.bytes_per_row)
        self.max_scroll = max(0, total_rows - self.visible_rows)
        self.scroll_offset = min(self.scroll_offset, self.max_scroll)
        
    def handle_event(self, event: pygame.event.Event) -> bool:
        """Handle pygame events
        
        Returns:
            True if event was handled
        """
        if event.type == pygame.MOUSEMOTION:
            if self.rect.collidepoint(event.pos):
                self._update_hover(event.pos)
                return True
                
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if self.rect.collidepoint(event.pos):
                if event.button == 1:  # Left click
                    self._start_selection(event.pos)
                elif event.button == 4:  # Scroll up
                    self.scroll(-3)
                elif event.button == 5:  # Scroll down
                    self.scroll(3)
                return True
                
        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1 and self.selection_start is not None:
                self._end_selection(event.pos)
                return True
                
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_c and pygame.key.get_mods() & pygame.KMOD_CTRL:
                self._copy_selection()
                return True
                
        return False
        
    def _update_hover(self, mouse_pos: Tuple[int, int]):
        """Update hovered byte based on mouse position"""
        byte_index = self._get_byte_at_pos(mouse_pos)
        self.hovered_byte = byte_index
        
    def _get_byte_at_pos(self, pos: Tuple[int, int]) -> Optional[int]:
        """Get byte index at screen position"""
        x, y = pos
        
        # Check if in hex area
        if x < self.content_x or x > self.content_x + self.hex_width:
            return None
            
        # Calculate row
        row = (y - self.content_y) // (self.char_height + 2) + self.scroll_offset
        if row < 0 or row >= math.ceil(len(self.data) / self.bytes_per_row):
            return None
            
        # Calculate column in hex area
        rel_x = x - self.content_x
        
        # Account for spacing between bytes
        byte_width = self.char_width * 3  # 2 hex chars + space
        col = rel_x // byte_width
        
        if col >= self.bytes_per_row:
            return None
            
        byte_index = row * self.bytes_per_row + col
        if byte_index >= len(self.data):
            return None
            
        return byte_index
        
    def _start_selection(self, pos: Tuple[int, int]):
        """Start selecting bytes"""
        byte_index = self._get_byte_at_pos(pos)
        if byte_index is not None:
            self.selection_start = byte_index
            self.selection_end = byte_index
            
    def _end_selection(self, pos: Tuple[int, int]):
        """End selecting bytes"""
        byte_index = self._get_byte_at_pos(pos)
        if byte_index is not None and self.selection_start is not None:
            self.selection_end = byte_index
            
    def _copy_selection(self):
        """Copy selected bytes to clipboard"""
        if self.selection_start is not None and self.selection_end is not None:
            start = min(self.selection_start, self.selection_end)
            end = max(self.selection_start, self.selection_end) + 1
            selected_data = self.data[start:end]
            
            # Format as hex string
            hex_str = ' '.join(f'{b:02x}' for b in selected_data)
            pygame.scrap.put(pygame.SCRAP_TEXT, hex_str.encode())
            
    def scroll(self, delta: int):
        """Scroll the view"""
        self.scroll_offset = max(0, min(self.scroll_offset + delta, self.max_scroll))
        
    def render(self, screen: pygame.Surface):
        """Render the hex viewer"""
        # Background
        pygame.draw.rect(screen, self.bg_color, self.rect)
        pygame.draw.rect(screen, self.grid_color, self.rect, 1)
        
        # Set clipping to prevent overflow
        screen.set_clip(self.rect)
        
        # Header
        self._render_header(screen)
        
        # Content
        self._render_content(screen)
        
        # Scrollbar
        self._render_scrollbar(screen)
        
        # Reset clipping
        screen.set_clip(None)
        
    def _render_header(self, screen: pygame.Surface):
        """Render column headers"""
        # Header background
        header_rect = pygame.Rect(self.rect.x, self.rect.y, self.rect.width, self.header_height)
        pygame.draw.rect(screen, self.header_bg, header_rect)
        pygame.draw.line(screen, self.grid_color, 
                        (self.rect.x, self.rect.y + self.header_height),
                        (self.rect.x + self.rect.width, self.rect.y + self.header_height))
        
        y = self.rect.y + 5
        
        # Offset header
        if self.show_offset:
            offset_text = self.header_font.render("Offset", True, self.offset_color)
            screen.blit(offset_text, (self.rect.x + 5, y))
            
        # Hex headers (00 01 02 ... 0F)
        x = self.content_x
        for i in range(self.bytes_per_row):
            if i > 0 and i % 4 == 0:
                x += self.char_width  # Extra space every 4 bytes
            hex_header = self.header_font.render(f"{i:02X}", True, self.offset_color)
            screen.blit(hex_header, (x, y))
            x += self.char_width * 3
            
        # ASCII header
        if self.show_ascii:
            ascii_text = self.header_font.render("ASCII", True, self.offset_color)
            screen.blit(ascii_text, (self.ascii_x, y))
            
    def _render_content(self, screen: pygame.Surface):
        """Render hex content"""
        if not self.data:
            return
            
        # Calculate visible range
        start_row = self.scroll_offset
        end_row = min(start_row + self.visible_rows,
                     math.ceil(len(self.data) / self.bytes_per_row))
        
        # Render each row
        for row_idx in range(start_row, end_row):
            self._render_row(screen, row_idx)
            
    def _render_row(self, screen: pygame.Surface, row_idx: int):
        """Render a single row of hex data"""
        y = self.content_y + (row_idx - self.scroll_offset) * (self.char_height + 2)
        
        # Calculate byte range for this row
        start_byte = row_idx * self.bytes_per_row
        end_byte = min(start_byte + self.bytes_per_row, len(self.data))
        
        # Render offset
        if self.show_offset:
            offset_text = self.mono_font.render(f"{start_byte:04X}: ", True, self.offset_color)
            screen.blit(offset_text, (self.rect.x + 5, y))
            
        # Render hex bytes
        x = self.content_x
        ascii_chars = []
        
        for i, byte_idx in enumerate(range(start_byte, end_byte)):
            byte_val = self.data[byte_idx]
            
            # Add spacing every 4 bytes
            if i > 0 and i % 4 == 0:
                x += self.char_width
                
            # Determine color
            color = self.hex_color
            bg_color = None
            
            # Selection highlighting
            if self.selection_start is not None and self.selection_end is not None:
                sel_start = min(self.selection_start, self.selection_end)
                sel_end = max(self.selection_start, self.selection_end)
                if sel_start <= byte_idx <= sel_end:
                    bg_color = self.selection_bg
                    
            # Hover highlighting
            if byte_idx == self.hovered_byte:
                bg_color = self.hover_bg
                
            # Change highlighting
            if self.previous_data and byte_idx < len(self.previous_data):
                if self.data[byte_idx] != self.previous_data[byte_idx]:
                    color = self.changed_color
                    
            # Draw background if needed
            if bg_color:
                bg_rect = pygame.Rect(x - 2, y - 1, self.char_width * 2 + 4, self.char_height + 2)
                pygame.draw.rect(screen, bg_color, bg_rect)
                
            # Draw hex value
            hex_text = self.mono_font.render(f"{byte_val:02x}", True, color)
            screen.blit(hex_text, (x, y))
            x += self.char_width * 3
            
            # Collect ASCII character
            if 32 <= byte_val < 127:
                ascii_chars.append(chr(byte_val))
            else:
                ascii_chars.append('.')
                
        # Render ASCII
        if self.show_ascii:
            # ASCII separator
            pygame.draw.line(screen, self.grid_color,
                           (self.ascii_x - 10, self.content_y),
                           (self.ascii_x - 10, self.content_y + self.content_height))
            
            ascii_text = ''.join(ascii_chars)
            ascii_surface = self.mono_font.render(ascii_text, True, self.ascii_color)
            screen.blit(ascii_surface, (self.ascii_x, y))
            
    def _render_scrollbar(self, screen: pygame.Surface):
        """Render scrollbar if needed"""
        if self.max_scroll <= 0:
            return
            
        # Scrollbar dimensions
        scrollbar_width = 10
        scrollbar_x = self.rect.x + self.rect.width - scrollbar_width - 2
        scrollbar_y = self.content_y
        scrollbar_height = self.content_height
        
        # Background
        scrollbar_rect = pygame.Rect(scrollbar_x, scrollbar_y, scrollbar_width, scrollbar_height)
        pygame.draw.rect(screen, self.grid_color, scrollbar_rect)
        
        # Thumb
        thumb_height = max(20, scrollbar_height * self.visible_rows // (self.visible_rows + self.max_scroll))
        thumb_y = scrollbar_y + (scrollbar_height - thumb_height) * self.scroll_offset // self.max_scroll
        
        thumb_rect = pygame.Rect(scrollbar_x, thumb_y, scrollbar_width, thumb_height)
        pygame.draw.rect(screen, self.offset_color, thumb_rect)