"""
pyreborn - Inventory UI overlay.

Provides a simple inventory/equipment management UI for the pygame client.
"""

from typing import List, Mapping, Optional, Tuple, Union

from .sprites import PLAYER_EQUIPMENT_PREVIEW_RECTS

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False


def resolve_weapon_indicator(weapons, selected_index, sprite_mgr=None):
    """Return ``(name, image_name, surface)`` for the equipped D-key weapon.

    This is shared by the inventory grid and the compact HUD slot so both
    apply the same filtering, index clamping, and image-loading rules.
    """
    entries = InventoryUI._visible_weapon_entries(weapons)
    if not entries:
        return None, "", None
    index = max(0, min(int(selected_index), len(entries) - 1))
    name, data = entries[index]
    image = data.get('image', '')
    surface = sprite_mgr.load_sheet(image) if image and sprite_mgr else None
    return name, image, surface


class InventoryUI:
    """Inventory and equipment overlay UI."""

    # UI Colors
    BG_COLOR = (20, 20, 40, 220)
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
    WEAPON_COLS = 5
    WEAPON_ROWS = 4
    WEAPON_SLOT = 58
    WEAPON_GAP = 8

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
        # selected_weapon_idx is the equipped/D-key index.  The cursor is
        # deliberately separate: browsing the grid must not equip by accident.
        self.selected_weapon_idx = 0
        self.cursor_weapon_idx = 0
        self.hovered_weapon_idx: Optional[int] = None
        self._last_click_idx: Optional[int] = None
        self._last_click_time = 0

        # Fonts
        self.font_large = pygame.font.Font(None, 28)
        self.font_medium = pygame.font.Font(None, 22)
        self.font_small = pygame.font.Font(None, 18)

        self._weapon_grid_rect = pygame.Rect(0, 0, 0, 0)
        self._last_weapon_entries: List[Tuple[str, dict]] = []

        # UI panel size is fixed; position is derived from the screen size at
        # render time (see render()) so a window resize keeps it centered -
        # the game only ever reassigns .screen, it never recreates this UI.
        self.ui_width = 400
        self.ui_height = 500
        self.ui_x = 0
        self.ui_y = 0

        # Pre-create overlay surface (fixed size, doesn't depend on screen size).
        self.overlay = pygame.Surface((self.ui_width, self.ui_height), pygame.SRCALPHA)

        # Cache keys include stable asset names/rects, and values pin source
        # surfaces alongside derived surfaces. Never key a cache by bare id().
        self._text_cache = {}
        self._sprite_scale_cache = {}
        self._stats_hearts = HeartDisplay(0, 0)

    def _cached_text(self, font, text: str, color) -> 'pygame.Surface':
        """Render text through a cache keyed by (font, text, color).

        Cleared wholesale once it grows large: hearts/rupees strings change
        constantly during play, so an uncapped cache leaks one surface per
        distinct value seen over a session."""
        key = (font, text, color)
        surf = self._text_cache.get(key)
        if surf is None:
            if len(self._text_cache) > 300:
                self._text_cache.clear()
            surf = font.render(text, True, color)
            self._text_cache[key] = surf
        return surf

    def toggle(self):
        """Toggle visibility."""
        if self.visible:
            self.hide()
        else:
            self.show()

    def show(self):
        """Show the inventory UI."""
        self.visible = True
        self.cursor_weapon_idx = self.selected_weapon_idx

    def hide(self):
        """Hide the inventory UI."""
        self.visible = False

    @staticmethod
    def _visible_weapon_entries(
            weapons: Optional[Union[List[str], Mapping[str, dict]]]
    ) -> List[Tuple[str, dict]]:
        """Return player-facing weapons while retaining their display data."""
        if isinstance(weapons, Mapping):
            entries = [(str(name), data if isinstance(data, dict) else {})
                       for name, data in weapons.items()]
        else:
            entries = [(str(name), {}) for name in (weapons or [])]
        return [(name, data) for name, data in entries
                if not name.startswith('-')]

    def render(self, player: 'Player',
               weapons: Optional[Union[List[str], Mapping[str, dict]]] = None):
        """
        Render the inventory UI.

        Args:
            player: Player object with equipment and stats
            weapons: Live weapon mapping (or a list of weapon names)
        """
        if not self.visible:
            return

        weapon_entries = self._visible_weapon_entries(weapons)
        self._last_weapon_entries = weapon_entries
        self._clamp_indices(len(weapon_entries))

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
        y += 12

        # Compact summary row: stats on the left, equipment on the right.
        self._render_stats(y, player)
        self._render_equipment(y, player)

        self._render_weapons(178, weapon_entries)

        # Footer stays inside the panel so it remains readable over a busy
        # world and is included in the panel border/background.
        help_text = self._cached_text(self.font_small,
                                       "Arrows: Move  Enter/Space: Equip  Q/Esc: Close",
                                       self.LABEL_COLOR)
        help_x = (self.ui_width - help_text.get_width()) // 2
        help_y = self.ui_height - self.PADDING - help_text.get_height()
        self.overlay.blit(help_text, (help_x, help_y))

        # Blit overlay to screen
        self.screen.blit(self.overlay, (self.ui_x, self.ui_y))

    def _render_stats(self, y: int, player: 'Player') -> int:
        """Render player stats section."""
        header = self._cached_text(self.font_medium, "STATS", self.LABEL_COLOR)
        self.overlay.blit(header, (self.PADDING, y))
        y += header.get_height() + 5

        # Reuse the exact vector heart renderer used by the HUD.
        self._stats_hearts.x, self._stats_hearts.y = self.PADDING, y
        self._stats_hearts.render(self.overlay, player.hearts, player.max_hearts)
        heart_rows = max(1, (int(player.max_hearts) + HeartDisplay.HEARTS_PER_ROW - 1)
                         // HeartDisplay.HEARTS_PER_ROW)
        y += heart_rows * (HeartDisplay.HEART_SIZE + HeartDisplay.HEART_SPACING) + 5
        rupees = self._cached_text(self.font_medium, f"Rupees  {player.rupees}",
                                   self.STAT_RUPEE_COLOR)
        self.overlay.blit(rupees, (self.PADDING, y))
        y += rupees.get_height() + 4
        for x, label, count in ((self.PADDING, "Bombs", player.bombs),
                                (self.PADDING + 82, "Arrows", player.arrows)):
            label_surf = self._cached_text(self.font_small, label, self.LABEL_COLOR)
            count_surf = self._cached_text(self.font_medium, str(count), self.TEXT_COLOR)
            self.overlay.blit(label_surf, (x, y))
            self.overlay.blit(count_surf, (x, y + label_surf.get_height()))
        y += self.font_small.get_height() + self.font_medium.get_height()

        return y

    def _render_equipment(self, y: int, player: 'Player') -> int:
        """Render equipment section."""
        start_x = 166
        header = self._cached_text(self.font_medium, "EQUIPMENT", self.LABEL_COLOR)
        self.overlay.blit(header, (start_x, y))
        y += header.get_height() + 5

        # Equipment slots in a row
        equipment = [
            ("Sword", "sword", player.sword_image or
             (f"sword{player.sword_power}.png" if player.sword_power > 0 else ""),
             player.sword_power),
            ("Shield", "shield", player.shield_image or
             (f"shield{player.shield_power}.png" if player.shield_power > 0 else ""),
             player.shield_power),
            ("Glove", "glove", "", player.glove_power),
            ("Player", "player", "", None),
        ]

        slot_x = start_x
        target_size = (self.SLOT_SIZE - 4, self.SLOT_SIZE - 4)
        for name, layer, image, power in equipment:
            # Draw slot background
            pygame.draw.rect(self.overlay, (40, 40, 60),
                           (slot_x, y, self.SLOT_SIZE, self.SLOT_SIZE))
            pygame.draw.rect(self.overlay, self.BORDER_COLOR,
                           (slot_x, y, self.SLOT_SIZE, self.SLOT_SIZE), 1)

            if layer == "player" and self.sprite_mgr:
                # Character preview is layered from the two verified crops.
                for preview_layer, preview_image in (("body", player.body_image),
                                                     ("head", player.head_image)):
                    self._blit_equipment_sprite(slot_x, y, preview_layer,
                                                preview_image, target_size)
            elif image and self.sprite_mgr:
                self._blit_equipment_sprite(slot_x, y, layer, image, target_size)
            elif layer == "glove":
                # No verified glove crop exists: use an honest vector fallback.
                pygame.draw.circle(self.overlay, (190, 135, 75),
                                   (slot_x + 24, y + 25), 12, 3)

            # Draw label below
            label = self._cached_text(self.font_small, name, self.LABEL_COLOR)
            label_x = slot_x + (self.SLOT_SIZE - label.get_width()) // 2
            self.overlay.blit(label, (label_x, y + self.SLOT_SIZE + 2))

            # Draw power if applicable
            if power is not None and power > 0:
                power_text = self._cached_text(self.font_small, f"Lv{power}", self.SELECTED_COLOR)
                self.overlay.blit(power_text, (slot_x + 2, y + 2))

            slot_x += self.SLOT_SIZE + self.SLOT_SPACING

        return y + self.SLOT_SIZE + 20

    def _blit_equipment_sprite(self, slot_x, y, layer, image, target_size):
        if not image:
            return
        rect = PLAYER_EQUIPMENT_PREVIEW_RECTS[layer]
        sprite = self.sprite_mgr.get_sprite(image, *rect)
        if not sprite:
            return
        key = ('equipment', image, rect, target_size)
        entry = self._sprite_scale_cache.get(key)
        if entry is None:
            fit = min(target_size[0] / sprite.get_width(),
                      target_size[1] / sprite.get_height())
            size = (max(1, round(sprite.get_width() * fit)),
                    max(1, round(sprite.get_height() * fit)))
            entry = (sprite, pygame.transform.scale(sprite, size))
            self._sprite_scale_cache[key] = entry
        scaled = entry[1]
        self.overlay.blit(scaled, (slot_x + (self.SLOT_SIZE - scaled.get_width()) // 2,
                                   y + (self.SLOT_SIZE - scaled.get_height()) // 2))

    def _render_weapons(self, y: int,
                        weapons: List[Tuple[str, dict]]) -> int:
        """Render weapons section."""
        header = self._cached_text(self.font_medium, "WEAPONS", self.LABEL_COLOR)
        self.overlay.blit(header, (self.PADDING, y))
        y += header.get_height() + 5
        grid_w = self.WEAPON_COLS * self.WEAPON_SLOT + (self.WEAPON_COLS - 1) * self.WEAPON_GAP
        self._weapon_grid_rect = pygame.Rect((self.ui_width - grid_w) // 2, y,
                                             grid_w, self.WEAPON_ROWS * self.WEAPON_SLOT +
                                             (self.WEAPON_ROWS - 1) * self.WEAPON_GAP)

        if not weapons:
            no_weapons = self._cached_text(self.font_medium, "(no weapons)", self.LABEL_COLOR)
            self.overlay.blit(no_weapons, (self.PADDING + 10, y))
            return y + no_weapons.get_height()

        icon_size = 40
        for i, (weapon, data) in enumerate(weapons[:self.WEAPON_COLS * self.WEAPON_ROWS]):
            col, row = i % self.WEAPON_COLS, i // self.WEAPON_COLS
            slot = pygame.Rect(self._weapon_grid_rect.x + col * (self.WEAPON_SLOT + self.WEAPON_GAP),
                               y + row * (self.WEAPON_SLOT + self.WEAPON_GAP),
                               self.WEAPON_SLOT, self.WEAPON_SLOT)
            pygame.draw.rect(self.overlay, (36, 38, 58), slot, border_radius=4)
            border = self.SELECTED_COLOR if i == self.cursor_weapon_idx else self.BORDER_COLOR
            pygame.draw.rect(self.overlay, border, slot, 3 if i == self.cursor_weapon_idx else 1,
                             border_radius=4)
            icon_x = slot.x + (slot.width - icon_size) // 2
            icon_y = slot.y + 5
            _, image, sprite = resolve_weapon_indicator(
                {weapon: data}, 0, self.sprite_mgr)
            if sprite:
                scale_key = ('weapon', image, (icon_size, icon_size))
                entry = self._sprite_scale_cache.get(scale_key)
                if entry is None:
                    fit = min(icon_size / sprite.get_width(),
                              icon_size / sprite.get_height())
                    size = (max(1, round(sprite.get_width() * fit)),
                            max(1, round(sprite.get_height() * fit)))
                    entry = (sprite, pygame.transform.scale(sprite, size))
                    self._sprite_scale_cache[scale_key] = entry
                scaled = entry[1]
                self.overlay.blit(scaled, (icon_x, icon_y))
            else:
                pygame.draw.rect(self.overlay, (35, 35, 50),
                                 (icon_x, icon_y, icon_size, icon_size))
                initials = self._cached_text(self.font_small,
                                             weapon[:2].upper(), self.TEXT_COLOR)
                self.overlay.blit(initials,
                                  (icon_x + (icon_size - initials.get_width()) // 2,
                                   icon_y + (icon_size - initials.get_height()) // 2))

            if i == self.selected_weapon_idx:
                marker = self._cached_text(self.font_small, "D", (30, 20, 0))
                pygame.draw.circle(self.overlay, self.SELECTED_COLOR,
                                   (slot.right - 8, slot.top + 8), 7)
                self.overlay.blit(marker, (slot.right - 8 - marker.get_width() // 2,
                                           slot.top + 8 - marker.get_height() // 2))

        focus = self.hovered_weapon_idx
        if focus is None:
            focus = self.cursor_weapon_idx
        name = weapons[focus][0] if 0 <= focus < len(weapons) else ""
        label = self._cached_text(self.font_medium, name, self.TEXT_COLOR)
        self.overlay.blit(label, ((self.ui_width - label.get_width()) // 2,
                                  self.ui_height - 52))
        return self._weapon_grid_rect.bottom

    def cycle_weapon(self, weapons: List[str], direction: int = 1):
        """
        Cycle through weapons.

        Args:
            weapons: List of available weapons
            direction: 1 for next, -1 for previous
        """
        if not weapons:
            return

        entries = self._visible_weapon_entries(weapons)
        if not entries:
            return
        self.selected_weapon_idx = (self.selected_weapon_idx + direction) % len(entries)
        self.cursor_weapon_idx = self.selected_weapon_idx

    def get_selected_weapon(self, weapons: List[str]) -> Optional[str]:
        """Get the currently selected weapon name."""
        entries = self._visible_weapon_entries(weapons)
        if not entries or self.selected_weapon_idx >= len(entries):
            return None
        return entries[self.selected_weapon_idx][0]

    def _clamp_indices(self, count: int):
        maximum = min(count, self.WEAPON_COLS * self.WEAPON_ROWS) - 1
        self.selected_weapon_idx = max(0, min(self.selected_weapon_idx, max(0, maximum)))
        self.cursor_weapon_idx = max(0, min(self.cursor_weapon_idx, max(0, maximum)))

    def move_selector(self, dx: int, dy: int, weapons) -> int:
        entries = self._visible_weapon_entries(weapons)
        count = min(len(entries), self.WEAPON_COLS * self.WEAPON_ROWS)
        if not count:
            return self.cursor_weapon_idx
        self._clamp_indices(count)
        row, col = divmod(self.cursor_weapon_idx, self.WEAPON_COLS)
        col = max(0, min(self.WEAPON_COLS - 1, col + dx))
        row = max(0, min(self.WEAPON_ROWS - 1, row + dy))
        self.cursor_weapon_idx = min(row * self.WEAPON_COLS + col, count - 1)
        return self.cursor_weapon_idx

    def equip_cursor(self, weapons) -> Optional[str]:
        entries = self._visible_weapon_entries(weapons)
        if not entries:
            return None
        self._clamp_indices(len(entries))
        self.selected_weapon_idx = self.cursor_weapon_idx
        return entries[self.selected_weapon_idx][0]

    def handle_key(self, key: int, weapons) -> bool:
        if key in (pygame.K_ESCAPE, pygame.K_q):
            self.hide()
        elif key == pygame.K_LEFT:
            self.move_selector(-1, 0, weapons)
        elif key == pygame.K_RIGHT:
            self.move_selector(1, 0, weapons)
        elif key == pygame.K_UP:
            self.move_selector(0, -1, weapons)
        elif key == pygame.K_DOWN:
            self.move_selector(0, 1, weapons)
        elif key in (pygame.K_RETURN, pygame.K_SPACE):
            self.equip_cursor(weapons)
        else:
            return False
        return True

    def _weapon_index_at(self, pos: Tuple[int, int]) -> Optional[int]:
        rel = (pos[0] - self.ui_x, pos[1] - self.ui_y)
        for i in range(min(len(self._last_weapon_entries),
                           self.WEAPON_COLS * self.WEAPON_ROWS)):
            col, row = i % self.WEAPON_COLS, i // self.WEAPON_COLS
            rect = pygame.Rect(self._weapon_grid_rect.x + col * (self.WEAPON_SLOT + self.WEAPON_GAP),
                               self._weapon_grid_rect.y + row * (self.WEAPON_SLOT + self.WEAPON_GAP),
                               self.WEAPON_SLOT, self.WEAPON_SLOT)
            if rect.collidepoint(rel):
                return i
        return None

    def handle_mouse_motion(self, pos: Tuple[int, int]):
        self.hovered_weapon_idx = self._weapon_index_at(pos) if self.visible else None
        if self.hovered_weapon_idx is not None:
            self.cursor_weapon_idx = self.hovered_weapon_idx

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

        idx = self._weapon_index_at(pos)
        if idx is None:
            return None
        self.cursor_weapon_idx = idx
        now = pygame.time.get_ticks()
        if idx == self._last_click_idx and now - self._last_click_time <= 400:
            result = self.equip_cursor(weapons)
        else:
            entries = self._visible_weapon_entries(weapons)
            result = entries[idx][0] if idx < len(entries) else None
        self._last_click_idx, self._last_click_time = idx, now
        return result


class HeartDisplay:
    """Displays player hearts as heart icons."""

    HEART_SIZE = 16
    HEART_SPACING = 2
    HEART_COLOR = (255, 50, 50)
    HEART_EMPTY_COLOR = (80, 30, 30)
    HEART_HALF_COLOR = (200, 50, 50)
    HEARTS_PER_ROW = 10

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

            columns = min(self.HEARTS_PER_ROW, max(1, total_hearts))
            rows = max(1, (total_hearts + self.HEARTS_PER_ROW - 1) // self.HEARTS_PER_ROW)
            w = max(1, columns * (self.HEART_SIZE + self.HEART_SPACING))
            h = rows * (self.HEART_SIZE + self.HEART_SPACING)
            row = pygame.Surface((w, h), pygame.SRCALPHA)
            for i in range(total_hearts):
                x = (i % self.HEARTS_PER_ROW) * (self.HEART_SIZE + self.HEART_SPACING)
                y = (i // self.HEARTS_PER_ROW) * (self.HEART_SIZE + self.HEART_SPACING)
                if i < full_hearts:
                    fill = 'full'
                elif i == full_hearts and has_half:
                    fill = 'half'
                else:
                    fill = 'empty'
                self._draw_heart(row, x, y, fill)
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
