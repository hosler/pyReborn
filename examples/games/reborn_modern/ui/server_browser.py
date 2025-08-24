"""
Server Browser UI
=================

Modern server browser with search and filtering capabilities.
"""

import pygame
import logging
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass
import socket


logger = logging.getLogger(__name__)


@dataclass
class ServerInfo:
    """Server information"""
    name: str
    host: str
    port: int
    players: int = 0
    max_players: int = 0
    description: str = ""
    version: str = ""
    ping: int = -1


class ServerBrowserUI:
    """Modern server browser interface"""
    
    def __init__(self, screen: pygame.Surface, width: int, height: int):
        """Initialize server browser
        
        Args:
            screen: Pygame surface to render to
            width: Browser width
            height: Browser height
        """
        self.screen = screen
        self.width = width
        self.height = height
        
        # UI configuration
        self.margin = 20
        self.padding = 10
        self.row_height = 40
        self.header_height = 60
        
        # Colors
        self.bg_color = (20, 20, 30)
        self.panel_color = (30, 30, 45)
        self.header_color = (40, 40, 60)
        self.text_color = (200, 200, 220)
        self.selected_color = (60, 90, 120)
        self.highlight_color = (80, 110, 140)
        
        # Fonts
        self.title_font = pygame.font.Font(None, 36)
        self.header_font = pygame.font.Font(None, 24)
        self.server_font = pygame.font.Font(None, 20)
        self.info_font = pygame.font.Font(None, 16)
        
        # Server list
        self.servers: List[ServerInfo] = []
        self.filtered_servers: List[ServerInfo] = []
        self.selected_index = 0
        self.scroll_offset = 0
        
        # Search
        self.search_text = ""
        self.search_active = False
        
        # Buttons
        self.refresh_button = pygame.Rect(width - 120, 20, 100, 30)
        self.connect_button = pygame.Rect(width - 120, height - 50, 100, 30)
        
        # Add some default servers
        self._add_default_servers()
        
        logger.info("Server browser UI initialized")
    
    def _add_default_servers(self):
        """Add default server entries"""
        self.servers = [
            ServerInfo(
                name="Local Development Server",
                host="localhost",
                port=14900,
                players=0,
                max_players=100,
                description="Local Docker instance",
                version="6.037"
            ),
            ServerInfo(
                name="Hastur Classic",
                host="hastur.hastur2.com",
                port=14900,
                players=5,
                max_players=200,
                description="Classic gameplay server with GMAP support",
                version="6.037"
            ),
            ServerInfo(
                name="Test Server",
                host="test.example.com",
                port=14900,
                players=2,
                max_players=50,
                description="Testing and development",
                version="2.22"
            )
        ]
        
        self.filtered_servers = self.servers.copy()
    
    def handle_event(self, event: pygame.event.Event):
        """Handle input event"""
        if event.type == pygame.KEYDOWN:
            if self.search_active:
                self._handle_search_input(event)
            else:
                self._handle_navigation(event)
                
        elif event.type == pygame.MOUSEBUTTONDOWN:
            self._handle_mouse_click(event.pos)
            
        elif event.type == pygame.MOUSEWHEEL:
            self._handle_scroll(event.y)
    
    def _handle_search_input(self, event: pygame.event.Event):
        """Handle search text input"""
        if event.key == pygame.K_ESCAPE or event.key == pygame.K_RETURN:
            self.search_active = False
            self._apply_search_filter()
        elif event.key == pygame.K_BACKSPACE:
            self.search_text = self.search_text[:-1]
        else:
            char = event.unicode
            if char and char.isprintable():
                self.search_text += char
    
    def _handle_navigation(self, event: pygame.event.Event):
        """Handle navigation keys"""
        if event.key == pygame.K_UP:
            self.selected_index = max(0, self.selected_index - 1)
            self._ensure_visible()
        elif event.key == pygame.K_DOWN:
            self.selected_index = min(len(self.filtered_servers) - 1, self.selected_index + 1)
            self._ensure_visible()
        elif event.key == pygame.K_RETURN:
            if 0 <= self.selected_index < len(self.filtered_servers):
                self._connect_to_selected()
        elif event.key == pygame.K_f and pygame.key.get_mods() & pygame.KMOD_CTRL:
            self.search_active = True
        elif event.key == pygame.K_F5:
            self._refresh_servers()
    
    def _handle_mouse_click(self, pos: Tuple[int, int]):
        """Handle mouse click"""
        x, y = pos
        
        # Check buttons
        if self.refresh_button.collidepoint(pos):
            self._refresh_servers()
            return
            
        if self.connect_button.collidepoint(pos):
            self._connect_to_selected()
            return
        
        # Check server list
        list_y = self.header_height + self.margin
        if self.margin <= x <= self.width - self.margin and list_y <= y:
            # Calculate which server was clicked
            relative_y = y - list_y
            index = int(relative_y / self.row_height) + self.scroll_offset
            
            if 0 <= index < len(self.filtered_servers):
                self.selected_index = index
    
    def _handle_scroll(self, delta: int):
        """Handle mouse wheel scroll"""
        self.scroll_offset = max(0, self.scroll_offset - delta)
        max_scroll = max(0, len(self.filtered_servers) - self._visible_rows())
        self.scroll_offset = min(max_scroll, self.scroll_offset)
    
    def _ensure_visible(self):
        """Ensure selected server is visible"""
        if self.selected_index < self.scroll_offset:
            self.scroll_offset = self.selected_index
        elif self.selected_index >= self.scroll_offset + self._visible_rows():
            self.scroll_offset = self.selected_index - self._visible_rows() + 1
    
    def _visible_rows(self) -> int:
        """Calculate number of visible server rows"""
        list_height = self.height - self.header_height - self.margin * 2 - 100
        return int(list_height / self.row_height)
    
    def _apply_search_filter(self):
        """Apply search filter to server list"""
        if not self.search_text:
            self.filtered_servers = self.servers.copy()
        else:
            search_lower = self.search_text.lower()
            self.filtered_servers = [
                server for server in self.servers
                if (search_lower in server.name.lower() or
                    search_lower in server.description.lower() or
                    search_lower in server.host.lower())
            ]
        
        # Reset selection
        self.selected_index = 0
        self.scroll_offset = 0
    
    def _refresh_servers(self):
        """Refresh server list"""
        logger.info("Refreshing server list...")
        # TODO: Implement actual server list fetching
        # For now, just ping existing servers
        for server in self.servers:
            server.ping = self._ping_server(server.host, server.port)
    
    def _ping_server(self, host: str, port: int) -> int:
        """Ping server and return latency in ms"""
        # Simple TCP connect test
        import time
        try:
            start = time.time()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            result = sock.connect_ex((host, port))
            sock.close()
            
            if result == 0:
                return int((time.time() - start) * 1000)
            else:
                return -1
        except:
            return -1
    
    def _connect_to_selected(self):
        """Connect to selected server"""
        if 0 <= self.selected_index < len(self.filtered_servers):
            server = self.filtered_servers[self.selected_index]
            logger.info(f"Connecting to {server.name} at {server.host}:{server.port}")
            # Set connection request flag
            self._connect_requested = True
            self._connect_result = (server.host, server.port)
            return (server.host, server.port)
        return None
    
    def update(self, dt: float) -> Optional[Tuple[str, int]]:
        """Update server browser
        
        Returns:
            (host, port) tuple if connecting, None otherwise
        """
        # Check if we have a pending connection request
        if hasattr(self, '_connect_requested') and self._connect_requested:
            self._connect_requested = False
            return self._connect_result
        return None
    
    def render(self):
        """Render server browser"""
        # Background
        self.screen.fill(self.bg_color)
        
        # Title
        title_text = self.title_font.render("Server Browser", True, self.text_color)
        title_rect = title_text.get_rect(centerx=self.width // 2, y=20)
        self.screen.blit(title_text, title_rect)
        
        # Search bar
        self._render_search_bar()
        
        # Server list panel
        list_rect = pygame.Rect(
            self.margin,
            self.header_height + self.margin,
            self.width - self.margin * 2,
            self.height - self.header_height - self.margin * 2 - 100
        )
        pygame.draw.rect(self.screen, self.panel_color, list_rect)
        pygame.draw.rect(self.screen, self.text_color, list_rect, 2)
        
        # Server list
        self._render_server_list(list_rect)
        
        # Buttons
        self._render_buttons()
        
        # Selected server info
        self._render_server_info()
    
    def _render_search_bar(self):
        """Render search bar"""
        search_rect = pygame.Rect(
            self.margin,
            self.header_height - 35,
            self.width - self.margin * 2 - 120,
            30
        )
        
        # Background
        color = self.highlight_color if self.search_active else self.panel_color
        pygame.draw.rect(self.screen, color, search_rect)
        pygame.draw.rect(self.screen, self.text_color, search_rect, 1)
        
        # Search text
        display_text = self.search_text
        if self.search_active:
            display_text += "_"
        
        if not display_text and not self.search_active:
            display_text = "Search servers... (Ctrl+F)"
            text_color = (100, 100, 120)
        else:
            text_color = self.text_color
        
        text = self.info_font.render(display_text, True, text_color)
        text_rect = text.get_rect(midleft=(search_rect.x + 10, search_rect.centery))
        self.screen.blit(text, text_rect)
    
    def _render_server_list(self, list_rect: pygame.Rect):
        """Render list of servers"""
        clip_rect = self.screen.get_clip()
        self.screen.set_clip(list_rect)
        
        # Headers
        header_y = list_rect.y + 5
        headers = [
            ("Server Name", list_rect.x + 10),
            ("Players", list_rect.x + list_rect.width - 200),
            ("Ping", list_rect.x + list_rect.width - 100),
            ("Version", list_rect.x + list_rect.width - 50)
        ]
        
        for text, x in headers:
            header_text = self.info_font.render(text, True, (150, 150, 170))
            self.screen.blit(header_text, (x, header_y))
        
        # Server rows
        y = header_y + 25
        visible_end = min(len(self.filtered_servers), self.scroll_offset + self._visible_rows())
        
        for i in range(self.scroll_offset, visible_end):
            server = self.filtered_servers[i]
            row_rect = pygame.Rect(list_rect.x, y, list_rect.width, self.row_height)
            
            # Highlight selected
            if i == self.selected_index:
                pygame.draw.rect(self.screen, self.selected_color, row_rect)
            elif row_rect.collidepoint(pygame.mouse.get_pos()):
                pygame.draw.rect(self.screen, self.highlight_color, row_rect)
            
            # Server name
            name_text = self.server_font.render(server.name, True, self.text_color)
            self.screen.blit(name_text, (list_rect.x + 10, y + 10))
            
            # Player count
            player_text = f"{server.players}/{server.max_players}"
            players = self.info_font.render(player_text, True, self.text_color)
            self.screen.blit(players, (list_rect.x + list_rect.width - 200, y + 12))
            
            # Ping
            if server.ping >= 0:
                ping_text = f"{server.ping}ms"
                ping_color = (100, 200, 100) if server.ping < 100 else (200, 200, 100)
            else:
                ping_text = "???"
                ping_color = (200, 100, 100)
                
            ping = self.info_font.render(ping_text, True, ping_color)
            self.screen.blit(ping, (list_rect.x + list_rect.width - 100, y + 12))
            
            # Version
            version = self.info_font.render(server.version, True, (150, 150, 170))
            self.screen.blit(version, (list_rect.x + list_rect.width - 50, y + 12))
            
            y += self.row_height
        
        self.screen.set_clip(clip_rect)
    
    def _render_buttons(self):
        """Render UI buttons"""
        # Refresh button
        self._render_button(self.refresh_button, "Refresh", self.refresh_button.collidepoint(pygame.mouse.get_pos()))
        
        # Connect button
        enabled = 0 <= self.selected_index < len(self.filtered_servers)
        self._render_button(self.connect_button, "Connect", 
                          self.connect_button.collidepoint(pygame.mouse.get_pos()),
                          enabled)
    
    def _render_button(self, rect: pygame.Rect, text: str, hover: bool, enabled: bool = True):
        """Render a button"""
        if not enabled:
            color = (40, 40, 50)
            text_color = (100, 100, 120)
        elif hover:
            color = self.highlight_color
            text_color = self.text_color
        else:
            color = self.panel_color
            text_color = self.text_color
        
        pygame.draw.rect(self.screen, color, rect)
        pygame.draw.rect(self.screen, self.text_color if enabled else text_color, rect, 1)
        
        button_text = self.info_font.render(text, True, text_color)
        text_rect = button_text.get_rect(center=rect.center)
        self.screen.blit(button_text, text_rect)
    
    def _render_server_info(self):
        """Render selected server information"""
        if not (0 <= self.selected_index < len(self.filtered_servers)):
            return
        
        server = self.filtered_servers[self.selected_index]
        
        # Info panel
        info_rect = pygame.Rect(
            self.margin,
            self.height - 90,
            self.width - self.margin * 2 - 130,
            70
        )
        pygame.draw.rect(self.screen, self.panel_color, info_rect)
        pygame.draw.rect(self.screen, self.text_color, info_rect, 1)
        
        # Server details
        y = info_rect.y + 10
        
        # Host info
        host_text = f"Host: {server.host}:{server.port}"
        host = self.info_font.render(host_text, True, self.text_color)
        self.screen.blit(host, (info_rect.x + 10, y))
        
        # Description
        desc = self.info_font.render(server.description, True, (150, 150, 170))
        self.screen.blit(desc, (info_rect.x + 10, y + 20))
        
        # Status
        if server.ping >= 0:
            status = f"Online ({server.ping}ms)"
            status_color = (100, 200, 100)
        else:
            status = "Offline"
            status_color = (200, 100, 100)
            
        status_text = self.info_font.render(status, True, status_color)
        self.screen.blit(status_text, (info_rect.x + 10, y + 40))