#!/usr/bin/env python3
"""
Clean Event-Driven Packet Inspector V2
=======================================

A completely rewritten packet inspector that:
- Uses PyReborn's event system exclusively (no manual parsing)
- Provides real-time packet stream visualization
- Shows detailed packet information with multiple views
- Includes statistics and filtering capabilities
"""

import pygame
import time
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict, deque
from enum import Enum
import logging

from pyreborn.core.events import EventType
from .hex_viewer import HexViewer

logger = logging.getLogger(__name__)


class ViewMode(Enum):
    """View modes for packet details"""
    PARSED = "parsed"
    HEX = "hex"
    TREE = "tree"
    TIMELINE = "timeline"


class PacketRecord:
    """Record of a single packet"""
    
    def __init__(self, data: Dict[str, Any]):
        self.packet_id = data.get('packet_id', 0)
        self.packet_name = data.get('packet_name', 'Unknown')
        self.direction = data.get('direction', 'unknown')
        self.timestamp = data.get('timestamp', time.time())
        self.sequence = data.get('sequence', 0)
        self.size = data.get('size', 0)
        self.raw_data = data.get('raw_data', b'')
        self.parsed_fields = data.get('parsed_fields', {})
        self.parsed_data = data.get('parsed_data', {})
        self.structured_data = data.get('structured_data', {})
        
        # For display
        self.color = (100, 200, 100) if self.direction == 'outgoing' else (100, 150, 200)
        self.selected = False


class PacketStatistics:
    """Track packet statistics"""
    
    def __init__(self):
        self.total_packets = 0
        self.total_bytes = 0
        self.packets_per_second = 0
        self.bytes_per_second = 0
        self.packet_counts = defaultdict(int)
        self.packet_sizes = defaultdict(int)
        self.error_count = 0
        
        # Time tracking
        self.start_time = time.time()
        self.last_update = time.time()
        self.recent_packets = deque(maxlen=100)  # Last 100 packets for rate calculation
    
    def update(self, packet: PacketRecord):
        """Update statistics with new packet"""
        self.total_packets += 1
        self.total_bytes += packet.size
        self.packet_counts[packet.packet_name] += 1
        self.packet_sizes[packet.packet_name] += packet.size
        
        # Track recent packets for rate calculation
        current_time = time.time()
        self.recent_packets.append((current_time, packet.size))
        
        # Calculate rates (every second)
        if current_time - self.last_update >= 1.0:
            # Remove old packets from rate calculation
            cutoff_time = current_time - 1.0
            while self.recent_packets and self.recent_packets[0][0] < cutoff_time:
                self.recent_packets.popleft()
            
            # Calculate current rates
            self.packets_per_second = len(self.recent_packets)
            self.bytes_per_second = sum(size for _, size in self.recent_packets)
            self.last_update = current_time
    
    def get_top_packets(self, limit: int = 10) -> List[Tuple[str, int]]:
        """Get most common packets"""
        return sorted(self.packet_counts.items(), key=lambda x: x[1], reverse=True)[:limit]


class PacketInspectorV2:
    """Clean event-driven packet inspector"""
    
    def __init__(self, screen: pygame.Surface, client):
        """Initialize packet inspector
        
        Args:
            screen: Pygame screen surface
            client: PyReborn client instance
        """
        self.screen = screen
        self.client = client
        self.active = False
        
        # Screen dimensions
        self.width = screen.get_width()
        self.height = screen.get_height()
        
        # Packet storage
        self.packets: List[PacketRecord] = []
        self.max_packets = 1000  # Keep last 1000 packets
        self.selected_packet: Optional[PacketRecord] = None
        
        # Statistics
        self.stats = PacketStatistics()
        
        # UI Layout (3 panels: stream, details, stats)
        self.stream_width = int(self.width * 0.3)
        self.details_width = int(self.width * 0.5)
        self.stats_width = self.width - self.stream_width - self.details_width
        
        # Scrolling
        self.stream_scroll = 0
        self.details_scroll = 0
        
        # View mode
        self.view_mode = ViewMode.PARSED
        
        # Filtering
        self.filter_text = ""
        self.filter_direction = None  # None, 'incoming', 'outgoing'
        self.paused = False
        
        # Hex viewer component
        self.hex_viewer = HexViewer(
            self.stream_width + 10,
            50,
            self.details_width - 20,
            self.height - 100
        )
        
        # Fonts
        self.title_font = pygame.font.Font(None, 24)
        self.header_font = pygame.font.Font(None, 18)
        self.text_font = pygame.font.Font(None, 14)
        self.mono_font = pygame.font.Font(pygame.font.match_font('monospace'), 12)
        
        # Colors
        self.bg_color = (20, 25, 30)
        self.panel_bg = (30, 35, 40)
        self.header_bg = (40, 45, 50)
        self.text_color = (200, 200, 220)
        self.header_color = (255, 255, 255)
        self.incoming_color = (100, 150, 200)
        self.outgoing_color = (100, 200, 100)
        self.selected_bg = (60, 80, 120)
        self.grid_color = (50, 55, 60)
        
        # Subscribe to events
        self._subscribe_to_events()
        
        logger.info("Packet Inspector V2 initialized - Press TAB to toggle")
    
    def _subscribe_to_events(self):
        """Subscribe to packet events"""
        events = self.client.events
        
        # Subscribe to new structured events
        events.subscribe(EventType.INCOMING_PACKET_STRUCTURED, self._on_incoming_packet)
        events.subscribe(EventType.OUTGOING_PACKET_STRUCTURED, self._on_outgoing_packet)
        
        # Also subscribe to raw events for completeness
        events.subscribe(EventType.RAW_PACKET_RECEIVED, self._on_raw_packet)
        events.subscribe(EventType.RAW_PACKET_SENT, self._on_raw_packet)
        
        logger.info("Subscribed to packet events")
    
    def _on_incoming_packet(self, event: Dict[str, Any]):
        """Handle incoming packet event"""
        if self.paused:
            return
        
        packet = PacketRecord(event)
        self._add_packet(packet)
    
    def _on_outgoing_packet(self, event: Dict[str, Any]):
        """Handle outgoing packet event"""
        if self.paused:
            return
        
        # Extract data from event structure
        packet_data = {
            'packet_id': event.get('packet_id', 0),
            'packet_name': event.get('packet_name', 'Unknown'),
            'direction': 'outgoing',
            'timestamp': time.time(),
            'size': event.get('size', 0),
            'raw_data': event.get('packet_data', b''),
            'structured_data': event.get('structured_data', {}),
            'parsed_fields': event.get('structured_data', {}).get('fields', {})
        }
        
        packet = PacketRecord(packet_data)
        self._add_packet(packet)
    
    def _on_raw_packet(self, event: Dict[str, Any]):
        """Handle raw packet events (fallback)"""
        # Only process if we don't have structured events
        # This ensures we don't duplicate packets
        pass
    
    def _add_packet(self, packet: PacketRecord):
        """Add packet to history and update stats"""
        self.packets.append(packet)
        
        # Limit packet history
        if len(self.packets) > self.max_packets:
            self.packets.pop(0)
        
        # Update statistics
        self.stats.update(packet)
    
    def _get_filtered_packets(self) -> List[PacketRecord]:
        """Get filtered packet list"""
        filtered = self.packets
        
        # Filter by direction
        if self.filter_direction:
            filtered = [p for p in filtered if p.direction == self.filter_direction]
        
        # Filter by text (name or ID)
        if self.filter_text:
            search = self.filter_text.lower()
            filtered = [p for p in filtered 
                       if search in p.packet_name.lower() or 
                       search == str(p.packet_id)]
        
        return filtered
    
    def toggle(self):
        """Toggle inspector visibility"""
        self.active = not self.active
    
    def handle_event(self, event: pygame.event.Event) -> bool:
        """Handle pygame events
        
        Returns:
            True if event was handled
        """
        if not self.active:
            return False
        
        if event.type == pygame.KEYDOWN:
            # Toggle views
            if event.key == pygame.K_p:
                self.view_mode = ViewMode.PARSED
                return True
            elif event.key == pygame.K_h:
                self.view_mode = ViewMode.HEX
                return True
            elif event.key == pygame.K_t:
                self.view_mode = ViewMode.TREE
                return True
            elif event.key == pygame.K_l:
                self.view_mode = ViewMode.TIMELINE
                return True
            
            # Pause/Resume
            elif event.key == pygame.K_SPACE:
                self.paused = not self.paused
                return True
            
            # Clear packets
            elif event.key == pygame.K_c:
                self.packets.clear()
                self.stats = PacketStatistics()
                return True
            
            # Filter direction
            elif event.key == pygame.K_i:
                self.filter_direction = 'incoming' if self.filter_direction != 'incoming' else None
                return True
            elif event.key == pygame.K_o:
                self.filter_direction = 'outgoing' if self.filter_direction != 'outgoing' else None
                return True
            
            # Close
            elif event.key == pygame.K_ESCAPE:
                self.active = False
                return True
        
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:  # Left click
                # Check if clicking in stream panel
                if event.pos[0] < self.stream_width:
                    self._handle_stream_click(event.pos)
                    return True
        
        elif event.type == pygame.MOUSEWHEEL:
            # Scroll based on mouse position
            if pygame.mouse.get_pos()[0] < self.stream_width:
                self.stream_scroll = max(0, self.stream_scroll - event.y * 20)
            else:
                self.details_scroll = max(0, self.details_scroll - event.y * 20)
            return True
        
        # Pass to hex viewer if in hex mode
        if self.view_mode == ViewMode.HEX and self.hex_viewer:
            return self.hex_viewer.handle_event(event)
        
        return False
    
    def _handle_stream_click(self, pos: Tuple[int, int]):
        """Handle click in stream panel"""
        y = pos[1] - 50 + self.stream_scroll
        index = y // 20
        
        filtered = self._get_filtered_packets()
        if 0 <= index < len(filtered):
            # Deselect previous
            if self.selected_packet:
                self.selected_packet.selected = False
            
            # Select new packet
            self.selected_packet = filtered[-(index + 1)]  # Reverse order (newest first)
            self.selected_packet.selected = True
            
            # Update hex viewer if needed
            if self.view_mode == ViewMode.HEX and self.hex_viewer:
                self.hex_viewer.set_data(self.selected_packet.raw_data)
    
    def render(self):
        """Render the packet inspector"""
        if not self.active:
            return
        
        # Clear screen
        self.screen.fill(self.bg_color)
        
        # Draw panels
        self._render_stream_panel()
        self._render_details_panel()
        self._render_stats_panel()
        
        # Draw borders
        pygame.draw.line(self.screen, self.grid_color, 
                        (self.stream_width, 0), 
                        (self.stream_width, self.height), 2)
        pygame.draw.line(self.screen, self.grid_color,
                        (self.stream_width + self.details_width, 0),
                        (self.stream_width + self.details_width, self.height), 2)
        
        # Draw header
        self._render_header()
    
    def _render_header(self):
        """Render top header bar"""
        header_rect = pygame.Rect(0, 0, self.width, 40)
        pygame.draw.rect(self.screen, self.header_bg, header_rect)
        
        # Title
        title = self.title_font.render("PACKET INSPECTOR V2", True, self.header_color)
        self.screen.blit(title, (10, 10))
        
        # Status
        status_text = "PAUSED" if self.paused else "LIVE"
        status_color = (255, 100, 100) if self.paused else (100, 255, 100)
        status = self.header_font.render(status_text, True, status_color)
        self.screen.blit(status, (200, 12))
        
        # View mode tabs
        x = 350
        for mode in ViewMode:
            color = self.header_color if mode == self.view_mode else (150, 150, 150)
            text = self.header_font.render(mode.value.upper(), True, color)
            self.screen.blit(text, (x, 12))
            x += 100
        
        # Filter info
        if self.filter_direction or self.filter_text:
            filter_info = f"Filter: {self.filter_direction or ''} {self.filter_text}"
            filter_surface = self.text_font.render(filter_info, True, (255, 200, 100))
            self.screen.blit(filter_surface, (self.width - 300, 14))
        
        # Instructions
        help_text = "P:Parsed H:Hex T:Tree L:Timeline | Space:Pause C:Clear I/O:Filter ESC:Close"
        help_surface = self.text_font.render(help_text, True, (150, 150, 150))
        help_rect = help_surface.get_rect(right=self.width - 10, centery=30)
        self.screen.blit(help_surface, help_rect)
    
    def _render_stream_panel(self):
        """Render packet stream panel"""
        panel_rect = pygame.Rect(0, 40, self.stream_width, self.height - 40)
        pygame.draw.rect(self.screen, self.panel_bg, panel_rect)
        
        # Header
        header_text = f"PACKET STREAM ({len(self.packets)} packets)"
        header = self.header_font.render(header_text, True, self.header_color)
        self.screen.blit(header, (10, 45))
        
        # Packet list
        y = 70 - self.stream_scroll
        filtered = self._get_filtered_packets()
        
        for packet in reversed(filtered[-50:]):  # Show last 50 packets
            if y > 40 and y < self.height - 20:
                # Selection background
                if packet.selected:
                    sel_rect = pygame.Rect(2, y - 2, self.stream_width - 4, 20)
                    pygame.draw.rect(self.screen, self.selected_bg, sel_rect)
                
                # Direction indicator
                dir_text = "→" if packet.direction == 'outgoing' else "←"
                dir_color = self.outgoing_color if packet.direction == 'outgoing' else self.incoming_color
                dir_surface = self.mono_font.render(dir_text, True, dir_color)
                self.screen.blit(dir_surface, (10, y))
                
                # Packet info
                info = f"{packet.packet_name[:20]:<20} {packet.size:>5}B"
                info_surface = self.mono_font.render(info, True, packet.color)
                self.screen.blit(info_surface, (30, y))
                
                # Timestamp
                time_str = time.strftime("%H:%M:%S", time.localtime(packet.timestamp))
                time_surface = self.mono_font.render(time_str, True, (150, 150, 150))
                self.screen.blit(time_surface, (self.stream_width - 70, y))
            
            y += 20
    
    def _render_details_panel(self):
        """Render packet details panel"""
        panel_rect = pygame.Rect(self.stream_width, 40, self.details_width, self.height - 40)
        pygame.draw.rect(self.screen, self.panel_bg, panel_rect)
        
        if not self.selected_packet:
            # No packet selected
            no_packet = self.header_font.render("Select a packet to view details", True, (150, 150, 150))
            rect = no_packet.get_rect(center=(self.stream_width + self.details_width // 2, self.height // 2))
            self.screen.blit(no_packet, rect)
            return
        
        # Render based on view mode
        if self.view_mode == ViewMode.PARSED:
            self._render_parsed_view()
        elif self.view_mode == ViewMode.HEX:
            self.hex_viewer.render(self.screen)
        elif self.view_mode == ViewMode.TREE:
            self._render_tree_view()
        elif self.view_mode == ViewMode.TIMELINE:
            self._render_timeline_view()
    
    def _render_parsed_view(self):
        """Render parsed fields view"""
        if not self.selected_packet:
            return
        
        x = self.stream_width + 10
        y = 50 - self.details_scroll
        
        # Packet header
        header = f"{self.selected_packet.packet_name} (ID: {self.selected_packet.packet_id})"
        header_surface = self.header_font.render(header, True, self.header_color)
        self.screen.blit(header_surface, (x, y))
        y += 25
        
        # Basic info
        info_lines = [
            f"Direction: {self.selected_packet.direction}",
            f"Size: {self.selected_packet.size} bytes",
            f"Timestamp: {time.strftime('%H:%M:%S.%f', time.localtime(self.selected_packet.timestamp))[:-3]}"
        ]
        
        for line in info_lines:
            if y > 40 and y < self.height - 20:
                surface = self.text_font.render(line, True, self.text_color)
                self.screen.blit(surface, (x + 10, y))
            y += 18
        
        y += 10
        
        # Parsed fields
        if self.selected_packet.parsed_fields:
            header = self.header_font.render("PARSED FIELDS", True, self.header_color)
            if y > 40 and y < self.height - 20:
                self.screen.blit(header, (x, y))
            y += 25
            
            # Handle different field types
            fields = self.selected_packet.parsed_fields
            
            # Special handling for properties (PLI_PLAYERPROPS)
            if 'properties' in fields and isinstance(fields['properties'], list):
                for prop in fields['properties']:
                    if isinstance(prop, dict):
                        name = prop.get('name', '?')
                        value = prop.get('value', '?')
                        field_text = f"  {name}: {value}"
                    else:
                        field_text = f"  {prop}"
                    
                    if y > 40 and y < self.height - 20:
                        surface = self.mono_font.render(field_text, True, (150, 200, 150))
                        self.screen.blit(surface, (x + 10, y))
                    y += 18
            else:
                # Regular fields
                for field_name, field_value in fields.items():
                    field_text = f"  {field_name}: {field_value}"
                    if len(field_text) > 60:
                        field_text = field_text[:57] + "..."
                    
                    if y > 40 and y < self.height - 20:
                        surface = self.mono_font.render(field_text, True, (150, 200, 150))
                        self.screen.blit(surface, (x + 10, y))
                    y += 18
    
    def _render_tree_view(self):
        """Render tree view (placeholder)"""
        x = self.stream_width + 10
        y = 50
        
        text = "Tree view coming soon..."
        surface = self.header_font.render(text, True, (150, 150, 150))
        self.screen.blit(surface, (x, y))
    
    def _render_timeline_view(self):
        """Render timeline view (placeholder)"""
        x = self.stream_width + 10
        y = 50
        
        text = "Timeline view coming soon..."
        surface = self.header_font.render(text, True, (150, 150, 150))
        self.screen.blit(surface, (x, y))
    
    def _render_stats_panel(self):
        """Render statistics panel"""
        panel_x = self.stream_width + self.details_width
        panel_rect = pygame.Rect(panel_x, 40, self.stats_width, self.height - 40)
        pygame.draw.rect(self.screen, self.panel_bg, panel_rect)
        
        x = panel_x + 10
        y = 50
        
        # Header
        header = self.header_font.render("STATISTICS", True, self.header_color)
        self.screen.blit(header, (x, y))
        y += 30
        
        # Overall stats
        stats_lines = [
            f"Total Packets: {self.stats.total_packets}",
            f"Total Bytes: {self._format_bytes(self.stats.total_bytes)}",
            f"Packets/sec: {self.stats.packets_per_second}",
            f"Bytes/sec: {self._format_bytes(self.stats.bytes_per_second)}",
            f"Errors: {self.stats.error_count}"
        ]
        
        for line in stats_lines:
            surface = self.text_font.render(line, True, self.text_color)
            self.screen.blit(surface, (x, y))
            y += 20
        
        y += 10
        
        # Top packets
        header = self.header_font.render("TOP PACKETS", True, self.header_color)
        self.screen.blit(header, (x, y))
        y += 25
        
        for packet_name, count in self.stats.get_top_packets(10):
            if y > self.height - 30:
                break
            
            # Truncate long names
            display_name = packet_name[:15] + "..." if len(packet_name) > 18 else packet_name
            line = f"{display_name:<20} {count:>5}"
            surface = self.mono_font.render(line, True, (150, 150, 200))
            self.screen.blit(surface, (x, y))
            y += 18
    
    def _format_bytes(self, bytes_count: int) -> str:
        """Format byte count for display"""
        if bytes_count < 1024:
            return f"{bytes_count}B"
        elif bytes_count < 1024 * 1024:
            return f"{bytes_count / 1024:.1f}KB"
        else:
            return f"{bytes_count / (1024 * 1024):.1f}MB"