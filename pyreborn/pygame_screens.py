"""
Pygame UI screens for pyreborn client.

Contains login screen, server selection screen, and loading screen utilities.
"""

import pygame
from pygame.locals import QUIT, KEYDOWN, MOUSEBUTTONDOWN, K_ESCAPE, K_TAB, K_RETURN, K_BACKSPACE, K_F1, K_UP, K_DOWN, K_SPACE, KMOD_SHIFT
from typing import Optional

from .listserver import ServerEntry

# Screen constants
SCREEN_WIDTH = 640
SCREEN_HEIGHT = 480


class LoginScreen:
    """Pygame login screen for entering credentials."""

    # Layout constants
    FIELD_X = 180
    FIELD_WIDTH = 380
    LABEL_X = 70

    def __init__(self):
        # Initialize pygame if not already
        if not pygame.get_init():
            pygame.init()

        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption("pyreborn - Login")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 28)
        self.font_small = pygame.font.Font(None, 22)
        self.font_title = pygame.font.Font(None, 42)

        # Input fields
        self.username = ""
        self.password = ""
        self.host = "localhost"
        self.port = "14900"
        self.listserver_host = "listserver.example.com"

        # Which field is active
        self.active_field = "username"  # username, password, host, port, listserver
        self.fields = ["username", "password", "host", "port", "listserver"]

        # Connection mode
        self.use_listserver = True  # Default to listserver mode

        # Error message
        self.error_message = ""

        # Store clickable regions
        self.field_rects = {}
        self.mode_toggle_rect = None
        self.connect_btn_rect = None

    def _try_connect(self) -> dict:
        """Attempt to connect and return credentials dict or None."""
        if self.username and self.password:
            return {
                "username": self.username,
                "password": self.password,
                "use_listserver": self.use_listserver,
                "host": self.host,
                "port": int(self.port) if self.port.isdigit() else 14900,
                "listserver_host": self.listserver_host,
            }
        else:
            self.error_message = "Username and password required"
            return None

    def run(self) -> dict:
        """Run the login screen. Returns dict with credentials or None if cancelled."""
        running = True

        while running:
            for event in pygame.event.get():
                if event.type == QUIT:
                    return None

                elif event.type == KEYDOWN:
                    if event.key == K_ESCAPE:
                        return None

                    elif event.key == K_TAB:
                        # Cycle through visible fields only
                        visible_fields = ["username", "password"]
                        if self.use_listserver:
                            visible_fields.append("listserver")
                        else:
                            visible_fields.extend(["host", "port"])

                        if self.active_field not in visible_fields:
                            self.active_field = visible_fields[0]
                        else:
                            idx = visible_fields.index(self.active_field)
                            if pygame.key.get_mods() & KMOD_SHIFT:
                                self.active_field = visible_fields[(idx - 1) % len(visible_fields)]
                            else:
                                self.active_field = visible_fields[(idx + 1) % len(visible_fields)]

                    elif event.key == K_RETURN:
                        result = self._try_connect()
                        if result:
                            return result

                    elif event.key == K_BACKSPACE:
                        self._handle_backspace()

                    elif event.key == K_F1:
                        self.use_listserver = not self.use_listserver

                    elif event.unicode and event.unicode.isprintable():
                        self._handle_char(event.unicode)

                elif event.type == MOUSEBUTTONDOWN:
                    if event.button == 1:
                        result = self._handle_click(event.pos)
                        if result:
                            return result

            self._render()
            self.clock.tick(60)

        return None

    def _handle_backspace(self):
        """Handle backspace key."""
        if self.active_field == "username":
            self.username = self.username[:-1]
        elif self.active_field == "password":
            self.password = self.password[:-1]
        elif self.active_field == "host":
            self.host = self.host[:-1]
        elif self.active_field == "port":
            self.port = self.port[:-1]
        elif self.active_field == "listserver":
            self.listserver_host = self.listserver_host[:-1]
        self.error_message = ""

    def _handle_char(self, char: str):
        """Handle character input."""
        self.error_message = ""
        if self.active_field == "username" and len(self.username) < 30:
            self.username += char
        elif self.active_field == "password" and len(self.password) < 30:
            self.password += char
        elif self.active_field == "host" and len(self.host) < 50:
            self.host += char
        elif self.active_field == "port" and len(self.port) < 5 and char.isdigit():
            self.port += char
        elif self.active_field == "listserver" and len(self.listserver_host) < 50:
            self.listserver_host += char

    def _handle_click(self, pos) -> dict:
        """Handle mouse click. Returns credentials dict if connect clicked, else None."""
        x, y = pos

        # Check field clicks
        for field_name, rect in self.field_rects.items():
            if rect.collidepoint(pos):
                self.active_field = field_name
                self.error_message = ""
                return None

        # Check mode toggle button
        if self.mode_toggle_rect and self.mode_toggle_rect.collidepoint(pos):
            self.use_listserver = not self.use_listserver
            return None

        # Check connect button
        if self.connect_btn_rect and self.connect_btn_rect.collidepoint(pos):
            return self._try_connect()

        return None

    def _render(self):
        """Render the login screen."""
        # Clear clickable regions
        self.field_rects = {}

        # Background
        self.screen.fill((25, 35, 55))

        # Draw decorative panel
        panel_rect = pygame.Rect(60, 60, SCREEN_WIDTH - 120, SCREEN_HEIGHT - 120)
        pygame.draw.rect(self.screen, (35, 50, 75), panel_rect, border_radius=12)
        pygame.draw.rect(self.screen, (60, 90, 130), panel_rect, 2, border_radius=12)

        # Title
        title = self.font_title.render("pyreborn", True, (100, 180, 255))
        self.screen.blit(title, (SCREEN_WIDTH // 2 - title.get_width() // 2, 85))

        subtitle = self.font_small.render("Reborn Client", True, (150, 150, 180))
        self.screen.blit(subtitle, (SCREEN_WIDTH // 2 - subtitle.get_width() // 2, 125))

        # Layout Y positions with proper spacing
        y_username = 165
        y_password = 215
        y_mode_toggle = 265
        y_server_field = 305
        y_connect_btn = 365
        y_error = 420
        y_help = 440

        # Username field
        self._render_field("Username:", self.username, y_username, "username")

        # Password field
        self._render_field("Password:", "*" * len(self.password), y_password, "password")

        # Connection mode toggle
        mode_text = "Listserver Mode" if self.use_listserver else "Direct Connection"
        mode_color = (100, 200, 150) if self.use_listserver else (200, 150, 100)

        self.mode_toggle_rect = pygame.Rect(self.FIELD_X, y_mode_toggle, 200, 28)
        pygame.draw.rect(self.screen, (40, 55, 80), self.mode_toggle_rect, border_radius=5)
        hover = self.mode_toggle_rect.collidepoint(pygame.mouse.get_pos())
        border_col = (100, 150, 200) if hover else (60, 80, 110)
        pygame.draw.rect(self.screen, border_col, self.mode_toggle_rect, 2, border_radius=5)

        mode_label = self.font_small.render("[F1]", True, (120, 120, 140))
        self.screen.blit(mode_label, (self.LABEL_X, y_mode_toggle + 5))
        mode_surf = self.font_small.render(mode_text, True, mode_color)
        self.screen.blit(mode_surf, (self.FIELD_X + 10, y_mode_toggle + 5))

        # Host/port or listserver field
        if self.use_listserver:
            self._render_field("Listserver:", self.listserver_host, y_server_field, "listserver")
        else:
            self._render_field("Host:", self.host, y_server_field, "host", width=220)
            self._render_field("Port:", self.port, y_server_field, "port", x_offset=240, width=80, label_offset=220)

        # Connect button
        btn_width = 180
        btn_x = SCREEN_WIDTH // 2 - btn_width // 2
        self.connect_btn_rect = pygame.Rect(btn_x, y_connect_btn, btn_width, 42)

        has_creds = bool(self.username and self.password)
        btn_hover = self.connect_btn_rect.collidepoint(pygame.mouse.get_pos())

        if has_creds:
            btn_color = (80, 180, 120) if btn_hover else (60, 140, 100)
        else:
            btn_color = (50, 50, 60)

        pygame.draw.rect(self.screen, btn_color, self.connect_btn_rect, border_radius=8)
        border_col = (120, 220, 160) if (has_creds and btn_hover) else (80, 120, 90)
        pygame.draw.rect(self.screen, border_col, self.connect_btn_rect, 2, border_radius=8)

        btn_text = self.font.render("Connect", True, (255, 255, 255) if has_creds else (100, 100, 100))
        self.screen.blit(btn_text, (self.connect_btn_rect.centerx - btn_text.get_width() // 2,
                                     self.connect_btn_rect.centery - btn_text.get_height() // 2))

        # Error message
        if self.error_message:
            error_surf = self.font_small.render(self.error_message, True, (255, 100, 100))
            self.screen.blit(error_surf, (SCREEN_WIDTH // 2 - error_surf.get_width() // 2, y_error))

        # Help text
        help_text = "Tab: Next field  |  Enter: Connect  |  F1: Toggle mode  |  Esc: Quit"
        help_surf = self.font_small.render(help_text, True, (90, 90, 110))
        self.screen.blit(help_surf, (SCREEN_WIDTH // 2 - help_surf.get_width() // 2, y_help))

        pygame.display.flip()

    def _render_field(self, label: str, value: str, y: int, field_name: str,
                      x_offset: int = 0, width: int = None, label_offset: int = 0):
        """Render an input field."""
        if width is None:
            width = self.FIELD_WIDTH

        x = self.FIELD_X + x_offset

        # Label
        label_surf = self.font_small.render(label, True, (180, 180, 200))
        self.screen.blit(label_surf, (self.LABEL_X + label_offset, y + 6))

        # Input box
        is_active = self.active_field == field_name
        box_color = (50, 70, 100) if is_active else (35, 45, 65)
        border_color = (100, 150, 255) if is_active else (60, 80, 110)

        box_rect = pygame.Rect(x, y, width, 32)
        self.field_rects[field_name] = box_rect

        # Hover effect
        if box_rect.collidepoint(pygame.mouse.get_pos()) and not is_active:
            border_color = (80, 120, 180)

        pygame.draw.rect(self.screen, box_color, box_rect, border_radius=5)
        pygame.draw.rect(self.screen, border_color, box_rect, 2, border_radius=5)

        # Text (truncate if too long)
        display_text = value
        max_chars = (width - 20) // 10  # Rough estimate
        if len(display_text) > max_chars:
            display_text = "..." + display_text[-(max_chars - 3):]

        text_surf = self.font.render(display_text, True, (255, 255, 255))
        self.screen.blit(text_surf, (x + 8, y + 5))

        # Blinking cursor
        if is_active:
            cursor_x = x + 8 + text_surf.get_width() + 2
            if cursor_x < x + width - 5:  # Don't draw cursor outside box
                if pygame.time.get_ticks() % 1000 < 500:
                    pygame.draw.line(self.screen, (255, 255, 255),
                                   (cursor_x, y + 6), (cursor_x, y + 24), 2)


class ServerSelectScreen:
    """Pygame screen for selecting a server from the listserver."""

    def __init__(self, servers: list, username: str):
        self.servers = servers
        self.username = username
        self.selected_index = 0
        self.scroll_offset = 0
        self.max_visible = 10

        # Initialize pygame if not already
        if not pygame.get_init():
            pygame.init()

        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption("pyreborn - Server Select")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 28)
        self.font_small = pygame.font.Font(None, 22)
        self.font_title = pygame.font.Font(None, 42)

    def run(self) -> Optional[ServerEntry]:
        """Run the server selection screen. Returns selected server or None."""
        running = True

        while running:
            for event in pygame.event.get():
                if event.type == QUIT:
                    return None

                elif event.type == KEYDOWN:
                    if event.key == K_ESCAPE:
                        return None

                    elif event.key == K_UP:
                        self.selected_index = max(0, self.selected_index - 1)
                        # Scroll up if needed
                        if self.selected_index < self.scroll_offset:
                            self.scroll_offset = self.selected_index

                    elif event.key == K_DOWN:
                        self.selected_index = min(len(self.servers) - 1, self.selected_index + 1)
                        # Scroll down if needed
                        if self.selected_index >= self.scroll_offset + self.max_visible:
                            self.scroll_offset = self.selected_index - self.max_visible + 1

                    elif event.key == K_RETURN or event.key == K_SPACE:
                        if self.servers:
                            return self.servers[self.selected_index]

                elif event.type == MOUSEBUTTONDOWN:
                    if event.button == 1:  # Left click
                        # Check if clicked on a server entry
                        mouse_y = event.pos[1]
                        entry_start_y = 120
                        entry_height = 50

                        for i in range(min(self.max_visible, len(self.servers) - self.scroll_offset)):
                            entry_y = entry_start_y + i * entry_height
                            if entry_y <= mouse_y < entry_y + entry_height:
                                clicked_index = self.scroll_offset + i
                                if clicked_index == self.selected_index:
                                    # Double-click effect - select
                                    return self.servers[self.selected_index]
                                else:
                                    self.selected_index = clicked_index
                                break

            self._render()
            self.clock.tick(60)

        return None

    def _render(self):
        """Render the server selection screen."""
        # Background
        self.screen.fill((20, 30, 50))

        # Title
        title = self.font_title.render("Select Server", True, (255, 255, 255))
        self.screen.blit(title, (SCREEN_WIDTH // 2 - title.get_width() // 2, 20))

        # User info
        user_text = self.font_small.render(f"Logged in as: {self.username}", True, (150, 200, 255))
        self.screen.blit(user_text, (SCREEN_WIDTH // 2 - user_text.get_width() // 2, 60))

        # Server count
        count_text = self.font_small.render(f"{len(self.servers)} servers available", True, (150, 150, 150))
        self.screen.blit(count_text, (SCREEN_WIDTH // 2 - count_text.get_width() // 2, 85))

        # Server list
        y = 120
        visible_servers = self.servers[self.scroll_offset:self.scroll_offset + self.max_visible]

        for i, server in enumerate(visible_servers):
            actual_index = self.scroll_offset + i
            is_selected = actual_index == self.selected_index

            # Background for entry
            bg_color = (50, 70, 100) if is_selected else (30, 40, 60)
            pygame.draw.rect(self.screen, bg_color, (20, y, SCREEN_WIDTH - 40, 45), border_radius=5)

            if is_selected:
                # Selection border
                pygame.draw.rect(self.screen, (100, 150, 255), (20, y, SCREEN_WIDTH - 40, 45), 2, border_radius=5)

            # Server type indicator
            type_colors = {
                "": (100, 100, 100),      # Normal
                "H ": (205, 127, 50),     # Bronze
                "P ": (255, 215, 0),      # Gold
                "3 ": (100, 200, 255),    # G3D
                "U ": (100, 100, 100),    # Hidden
            }
            type_color = type_colors.get(server.type_prefix, (100, 100, 100))

            # Type badge
            if server.type_prefix.strip():
                badge_text = server.type_prefix.strip()
                badge = self.font_small.render(badge_text, True, type_color)
                pygame.draw.rect(self.screen, (20, 25, 35), (30, y + 5, 25, 18), border_radius=3)
                self.screen.blit(badge, (35, y + 6))

            # Server name
            name_x = 65 if server.type_prefix.strip() else 30
            name = self.font.render(server.name, True, (255, 255, 255))
            self.screen.blit(name, (name_x, y + 5))

            # Server info line
            info = f"{server.player_count} players  |  {server.language}  |  {server.ip}:{server.port}"
            info_text = self.font_small.render(info, True, (150, 150, 150))
            self.screen.blit(info_text, (30, y + 26))

            y += 50

        # Scroll indicators
        if self.scroll_offset > 0:
            arrow_up = self.font.render("More servers above", True, (100, 150, 200))
            self.screen.blit(arrow_up, (SCREEN_WIDTH // 2 - arrow_up.get_width() // 2, 100))

        if self.scroll_offset + self.max_visible < len(self.servers):
            arrow_down = self.font.render("More servers below", True, (100, 150, 200))
            self.screen.blit(arrow_down, (SCREEN_WIDTH // 2 - arrow_down.get_width() // 2, SCREEN_HEIGHT - 60))

        # Instructions
        help_text = "Up/Down: Navigate  |  Enter: Connect  |  Esc: Cancel"
        help_surf = self.font_small.render(help_text, True, (100, 100, 100))
        self.screen.blit(help_surf, (SCREEN_WIDTH // 2 - help_surf.get_width() // 2, SCREEN_HEIGHT - 30))

        pygame.display.flip()


def show_loading_screen(message: str):
    """Show a simple loading screen."""
    if not pygame.get_init():
        pygame.init()

    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("pyreborn")
    font = pygame.font.Font(None, 36)

    screen.fill((20, 30, 50))
    text = font.render(message, True, (255, 255, 255))
    screen.blit(text, (SCREEN_WIDTH // 2 - text.get_width() // 2, SCREEN_HEIGHT // 2 - 20))
    pygame.display.flip()

    # Process events to prevent "not responding"
    pygame.event.pump()
