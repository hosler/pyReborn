"""
pyreborn - Inventory UI overlay.

Provides a simple inventory/equipment management UI for the pygame client.
"""

from typing import List, Optional, Tuple

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False


class InventoryUI:
    """Inventory and equipment overlay UI."""

    # UI Colors
    BG_COLOR = (20, 20, 40, 200)
    BORDER_COLOR = (100, 100, 150)
    SELECTED_COLOR = (255, 200, 50)
    TEXT_COLOR = (255, 255, 255)
    LABEL_COLOR = (180, 180, 200)
    STAT_HEART_COLOR = (255, 80, 80)
    STAT_RUPEE_COLOR = (50, 255, 50)

    # Layout
    PADDING = 10
    SLOT_SIZE = 48
    SLOT_SPACING = 8

    def __init__(self, screen: 'pygame.Surface', sprite_mgr: Optional['SpriteManager'] = None):
        """
        Initialize inventory UI.

        Args:
            screen: Pygame screen surface
            sprite_mgr: Sprite manager for loading equipment images
        """
        if not PYGAME_AVAILABLE:
            raise RuntimeError("pygame is required for InventoryUI")

        self.screen = screen
        self.sprite_mgr = sprite_mgr
        self.visible = False
        self.selected_weapon_idx = 0

        # Fonts
        self.font_large = pygame.font.Font(None, 28)
        self.font_medium = pygame.font.Font(None, 22)
        self.font_small = pygame.font.Font(None, 18)

        # Track weapon section Y position for click handling. The line height
        # is derived from font_medium (not hardcoded) so the click math in
        # handle_click always matches the actual advance in _render_weapons.
        self._weapons_section_y = 0
        self._weapon_line_height = self.font_medium.get_height() + 2

        # UI panel size is fixed; position is derived from the screen size at
        # render time (see render()) so a window resize keeps it centered -
        # the game only ever reassigns .screen, it never recreates this UI.
        self.ui_width = 300
        self.ui_height = 400
        self.ui_x = 0
        self.ui_y = 0

        # Pre-create overlay surface (fixed size, doesn't depend on screen size).
        self.overlay = pygame.Surface((self.ui_width, self.ui_height), pygame.SRCALPHA)

        # Rendered-text and scaled-sprite caches, keyed by (font id, text, color)
        # and (id(sprite), target size) respectively, so static/rarely-changing
        # strings and equipment icons aren't re-rendered/rescaled every frame.
        self._text_cache = {}
        self._sprite_scale_cache = {}

    def _cached_text(self, font, text: str, color) -> 'pygame.Surface':
        """Render text through a cache keyed by (font, text, color).

        Cleared wholesale once it grows large: hearts/rupees strings change
        constantly during play, so an uncapped cache leaks one surface per
        distinct value seen over a session."""
        key = (id(font), text, color)
        surf = self._text_cache.get(key)
        if surf is None:
            if len(self._text_cache) > 300:
                self._text_cache.clear()
            surf = font.render(text, True, color)
            self._text_cache[key] = surf
        return surf

    def toggle(self):
        """Toggle visibility."""
        self.visible = not self.visible

    def show(self):
        """Show the inventory UI."""
        self.visible = True

    def hide(self):
        """Hide the inventory UI."""
        self.visible = False

    def render(self, player: 'Player', weapons: Optional[List[str]] = None):
        """
        Render the inventory UI.

        Args:
            player: Player object with equipment and stats
            weapons: List of weapon names the player has
        """
        if not self.visible:
            return

        weapons = weapons or []

        # Recompute position from the current screen size (not cached from
        # __init__) so a window resize keeps the panel centered.
        screen_w, screen_h = self.screen.get_size()
        self.ui_x = (screen_w - self.ui_width) // 2
        self.ui_y = (screen_h - self.ui_height) // 2

        # Clear overlay
        self.overlay.fill(self.BG_COLOR)

        # Draw border
        pygame.draw.rect(self.overlay, self.BORDER_COLOR,
                        (0, 0, self.ui_width, self.ui_height), 2)

        y = self.PADDING

        # Title
        title = self._cached_text(self.font_large, "INVENTORY", self.TEXT_COLOR)
        title_x = (self.ui_width - title.get_width()) // 2
        self.overlay.blit(title, (title_x, y))
        y += title.get_height() + 15

        # Separator
        pygame.draw.line(self.overlay, self.BORDER_COLOR,
                        (self.PADDING, y), (self.ui_width - self.PADDING, y))
        y += 10

        # Stats section
        y = self._render_stats(y, player)
        y += 15

        # Equipment section
        y = self._render_equipment(y, player)
        y += 15

        # Weapons section
        self._render_weapons(y, weapons)

        # Blit overlay to screen
        self.screen.blit(self.overlay, (self.ui_x, self.ui_y))

        # Draw help text below
        help_text = self._cached_text(self.font_small,
                                       "Q: Close | S+A: Cycle Weapons | D: Use",
                                       self.LABEL_COLOR)
        help_x = (self.screen.get_width() - help_text.get_width()) // 2
        help_y = self.ui_y + self.ui_height + 10
        self.screen.blit(help_text, (help_x, help_y))

    def _render_stats(self, y: int, player: 'Player') -> int:
        """Render player stats section."""
        # Section header
        header = self._cached_text(self.font_medium, "Stats", self.LABEL_COLOR)
        self.overlay.blit(header, (self.PADDING, y))
        y += header.get_height() + 5

        # Hearts
        hearts_text = f"Hearts: {player.hearts:.1f}/{player.max_hearts:.1f}"
        hearts = self._cached_text(self.font_medium, hearts_text, self.STAT_HEART_COLOR)
        self.overlay.blit(hearts, (self.PADDING + 10, y))
        y += hearts.get_height() + 3

        # Rupees
        rupees_text = f"Rupees: {player.rupees}"
        rupees = self._cached_text(self.font_medium, rupees_text, self.STAT_RUPEE_COLOR)
        self.overlay.blit(rupees, (self.PADDING + 10, y))
        y += rupees.get_height() + 3

        # Arrows and Bombs
        items_text = f"Arrows: {player.arrows}  Bombs: {player.bombs}"
        items = self._cached_text(self.font_medium, items_text, self.TEXT_COLOR)
        self.overlay.blit(items, (self.PADDING + 10, y))
        y += items.get_height() + 3

        return y

    def _render_equipment(self, y: int, player: 'Player') -> int:
        """Render equipment section."""
        # Section header
        header = self._cached_text(self.font_medium, "Equipment", self.LABEL_COLOR)
        self.overlay.blit(header, (self.PADDING, y))
        y += header.get_height() + 5

        # Equipment slots in a row
        equipment = [
            ("Sword", player.sword_image, player.sword_power),
            ("Shield", player.shield_image, player.shield_power),
            ("Head", player.head_image, None),
            ("Body", player.body_image, None),
        ]

        slot_x = self.PADDING + 10
        target_size = (self.SLOT_SIZE - 4, self.SLOT_SIZE - 4)
        for name, image, power in equipment:
            # Draw slot background
            pygame.draw.rect(self.overlay, (40, 40, 60),
                           (slot_x, y, self.SLOT_SIZE, self.SLOT_SIZE))
            pygame.draw.rect(self.overlay, self.BORDER_COLOR,
                           (slot_x, y, self.SLOT_SIZE, self.SLOT_SIZE), 1)

            # Draw equipment image if available
            if image and self.sprite_mgr:
                sprite = self.sprite_mgr.load_sheet(image)
                if sprite:
                    # Scale to fit slot (cached per sprite identity + target size)
                    scale_key = (id(sprite), target_size)
                    scaled = self._sprite_scale_cache.get(scale_key)
                    if scaled is None:
                        if len(self._sprite_scale_cache) > 100:
                            self._sprite_scale_cache.clear()
                        scaled = pygame.transform.scale(sprite, target_size)
                        self._sprite_scale_cache[scale_key] = scaled
                    self.overlay.blit(scaled, (slot_x + 2, y + 2))

            # Draw label below
            label = self._cached_text(self.font_small, name, self.LABEL_COLOR)
            label_x = slot_x + (self.SLOT_SIZE - label.get_width()) // 2
            self.overlay.blit(label, (label_x, y + self.SLOT_SIZE + 2))

            # Draw power if applicable
            if power is not None and power > 0:
                power_text = self._cached_text(self.font_small, f"Lv{power}", self.SELECTED_COLOR)
                self.overlay.blit(power_text, (slot_x + 2, y + 2))

            slot_x += self.SLOT_SIZE + self.SLOT_SPACING

        y += self.SLOT_SIZE + 20

        # Glove power
        glove_text = f"Glove Power: {player.glove_power}"
        glove = self._cached_text(self.font_medium, glove_text, self.TEXT_COLOR)
        self.overlay.blit(glove, (self.PADDING + 10, y))
        y += glove.get_height() + 3

        return y

    def _render_weapons(self, y: int, weapons: List[str]) -> int:
        """Render weapons section."""
        # Section header
        header = self._cached_text(self.font_medium, "Weapons", self.LABEL_COLOR)
        self.overlay.blit(header, (self.PADDING, y))
        y += header.get_height() + 5

        # Store Y position where weapon list starts (for click handling)
        self._weapons_section_y = y

        if not weapons:
            no_weapons = self._cached_text(self.font_medium, "(no weapons)", self.LABEL_COLOR)
            self.overlay.blit(no_weapons, (self.PADDING + 10, y))
            return y + no_weapons.get_height()

        # List weapons. Each row advances by self._weapon_line_height, the same
        # value handle_click() uses to map a click Y back to a weapon index.
        for i, weapon in enumerate(weapons):
            # Highlight selected weapon
            if i == self.selected_weapon_idx:
                # Draw selection highlight
                pygame.draw.rect(self.overlay, (60, 60, 100),
                               (self.PADDING + 5, y, self.ui_width - self.PADDING * 2 - 10,
                                self._weapon_line_height - 2))
                text_color = self.SELECTED_COLOR
                prefix = "> "
            else:
                text_color = self.TEXT_COLOR
                prefix = "  "

            weapon_text = self._cached_text(self.font_medium, f"{prefix}{weapon}", text_color)
            self.overlay.blit(weapon_text, (self.PADDING + 10, y))
            y += self._weapon_line_height

        return y

    def cycle_weapon(self, weapons: List[str], direction: int = 1):
        """
        Cycle through weapons.

        Args:
            weapons: List of available weapons
            direction: 1 for next, -1 for previous
        """
        if not weapons:
            return

        self.selected_weapon_idx = (self.selected_weapon_idx + direction) % len(weapons)

    def get_selected_weapon(self, weapons: List[str]) -> Optional[str]:
        """Get the currently selected weapon name."""
        if not weapons or self.selected_weapon_idx >= len(weapons):
            return None
        return weapons[self.selected_weapon_idx]

    def handle_click(self, pos: Tuple[int, int], weapons: List[str]) -> Optional[str]:
        """
        Handle mouse click on inventory.

        Args:
            pos: Mouse position (x, y)
            weapons: List of available weapons

        Returns:
            Selected weapon name or None
        """
        if not self.visible:
            return None

        # Convert to UI-relative coordinates
        rel_x = pos[0] - self.ui_x
        rel_y = pos[1] - self.ui_y

        # Check if click is within UI bounds
        if not (0 <= rel_x < self.ui_width and 0 <= rel_y < self.ui_height):
            return None

        # Check if click is in weapons section
        if not weapons or self._weapons_section_y == 0:
            return None

        # Check if Y is in weapons list area
        weapons_start_y = self._weapons_section_y
        weapons_end_y = weapons_start_y + len(weapons) * self._weapon_line_height

        if weapons_start_y <= rel_y < weapons_end_y:
            # Calculate which weapon was clicked
            weapon_idx = int((rel_y - weapons_start_y) / self._weapon_line_height)
            if 0 <= weapon_idx < len(weapons):
                self.selected_weapon_idx = weapon_idx
                return weapons[weapon_idx]

        return None


class HeartDisplay:
    """Displays player hearts as heart icons."""

    HEART_SIZE = 16
    HEART_SPACING = 2
    HEART_COLOR = (255, 50, 50)
    HEART_EMPTY_COLOR = (80, 30, 30)
    HEART_HALF_COLOR = (200, 50, 50)

    def __init__(self, x: int, y: int):
        """Initialize heart display at position."""
        self.x = x
        self.y = y
        # The heart row only actually changes when hearts/max_hearts do, not
        # every frame - cache the composited row and just blit it otherwise.
        self._cache: Optional['pygame.Surface'] = None
        self._cache_key = None

    def render(self, screen: 'pygame.Surface', current: float, maximum: float):
        """
        Render hearts.

        Args:
            screen: Pygame surface
            current: Current hearts (can be fractional)
            maximum: Maximum hearts
        """
        if not PYGAME_AVAILABLE:
            return

        key = (current, maximum)
        if key != self._cache_key:
            full_hearts = int(current)
            has_half = (current - full_hearts) >= 0.5
            total_hearts = int(maximum)

            w = max(1, total_hearts * (self.HEART_SIZE + self.HEART_SPACING))
            row = pygame.Surface((w, self.HEART_SIZE), pygame.SRCALPHA)
            for i in range(total_hearts):
                x = i * (self.HEART_SIZE + self.HEART_SPACING)
                if i < full_hearts:
                    fill = 'full'
                elif i == full_hearts and has_half:
                    fill = 'half'
                else:
                    fill = 'empty'
                self._draw_heart(row, x, 0, fill)
            self._cache = row
            self._cache_key = key

        screen.blit(self._cache, (self.x, self.y))

    OUTLINE_COLOR = (20, 10, 10)

    def _draw_heart(self, screen, x: int, y: int, fill: str):
        """Draw a single heart icon (fill = 'full' | 'half' | 'empty')."""
        s = self.HEART_SIZE
        cx = x + s // 2

        def heart_shapes(color):
            r = s // 4
            top = y + r
            pygame.draw.circle(screen, color, (cx - r + 1, top), r)
            pygame.draw.circle(screen, color, (cx + r - 1, top), r)
            pygame.draw.polygon(screen, color, [
                (x + 1, top), (x + s - 1, top), (cx, y + s - 1)
            ])

        # Base/empty body (always drawn so empty hearts read as outlines)
        heart_shapes(self.HEART_EMPTY_COLOR)

        if fill in ('full', 'half'):
            prev_clip = screen.get_clip()
            if fill == 'half':
                screen.set_clip(pygame.Rect(x, y, s // 2, s))
            heart_shapes(self.HEART_COLOR)
            # Small highlight
            pygame.draw.circle(screen, (255, 170, 170), (cx - s // 5, y + s // 4), max(1, s // 8))
            screen.set_clip(prev_clip)
