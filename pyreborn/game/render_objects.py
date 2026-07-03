"""LevelObjectsRenderMixin — chests and signs (client-side level overlays).

Split from render.py; methods operate on the GameClient instance."""

import time
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pygame
from pygame.locals import (
    QUIT, KEYDOWN, MOUSEBUTTONDOWN,
    K_ESCAPE, K_RETURN, K_q, K_a, K_s, K_d, K_SPACE, K_m, K_h,
    K_UP, K_DOWN, K_LEFT, K_RIGHT,
    K_F1, K_F2, K_1, K_2, K_3, K_4, K_5, K_6, K_7
)

from .. import Client
from ..gani import GaniParser, AnimationState, direction_from_delta
from ..sprites import SpriteManager, TilesetManager, create_placeholder_sprite, create_shadow_sprite
from ..sounds import SoundManager, preload_common_sounds
from ..inventory_ui import InventoryUI, HeartDisplay
from ..npc_handler import NPCHandler
from ..player import Player
from ..tiletypes import TileType, get_tile_type
from .constants import (
    TILE_CORRECTIONS_FILE, TILE_SIZE, SCREEN_WIDTH, SCREEN_HEIGHT,
    TILESET_COLS, TILESET_ROWS, MOVE_STEP, parse_npc_visual_effects,
)


_ITEM_COLORS = {
    'greenrupee': (60, 220, 90), 'bluerupee': (70, 140, 230), 'redrupee': (230, 70, 70),
    'goldrupee': (230, 200, 60),
    'bombs': (60, 60, 70), 'bomb': (60, 60, 70), 'superbomb': (120, 60, 140),
    'joltbomb': (230, 230, 80), 'darts': (200, 200, 200),
    'heart': (230, 60, 90), 'fullheart': (230, 60, 90),
    'glove1': (150, 110, 70), 'glove2': (110, 80, 50),
    'bow': (200, 160, 90), 'shield': (150, 150, 200), 'mirrorshield': (220, 220, 255),
    'lizardshield': (90, 200, 90), 'sword': (210, 210, 220), 'battleaxe': (180, 120, 80),
    'goldensword': (230, 200, 60), 'lizardsword': (90, 200, 90),
    'fireball': (250, 140, 40), 'fireblast': (250, 90, 20), 'nukeshot': (255, 255, 120),
    'spinattack': (200, 80, 220),
}
_DEFAULT_ITEM_COLOR = (220, 220, 100)


class LevelObjectsRenderMixin:
    """Mixin providing the above methods for GameClient."""

    def _get_item_sprite(self, item_type: str) -> pygame.Surface:
        """Build (and cache) a ground-item icon.

        No verified pics1.png tile-position table for item sprites exists in
        this repo (chests were hand-picked against a live server with
        tools/chest_picker.py; items never were), so rather than guess wrong
        tile coordinates - which would render authentic-looking garbage -
        items are drawn as small colour/shape-coded vector icons, matching the
        style already used for the HUD's rupee/bomb/arrow counters
        (game/hud.py StatsPanel._stat_icon). Type-correct and pop on pickup;
        just not pixel-authentic Graal art."""
        cache = getattr(self, "_item_sprite_cache", None)
        if cache is None:
            cache = self._item_sprite_cache = {}
        if item_type in cache:
            return cache[item_type]

        surf = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
        color = _ITEM_COLORS.get(item_type, _DEFAULT_ITEM_COLOR)
        cx, cy = TILE_SIZE // 2, TILE_SIZE // 2
        outline = tuple(max(0, c - 90) for c in color)

        if 'rupee' in item_type:
            pts = [(cx, 1), (TILE_SIZE - 2, cy), (cx, TILE_SIZE - 1), (2, cy)]
            pygame.draw.polygon(surf, color, pts)
            pygame.draw.polygon(surf, outline, pts, 1)
        elif 'heart' in item_type:
            pygame.draw.circle(surf, color, (cx - 3, cy - 1), 4)
            pygame.draw.circle(surf, color, (cx + 3, cy - 1), 4)
            pygame.draw.polygon(surf, color, [(2, cy), (TILE_SIZE - 2, cy), (cx, TILE_SIZE - 2)])
        elif 'bomb' in item_type or item_type == 'darts':
            pygame.draw.circle(surf, color, (cx, cy + 2), 6)
            pygame.draw.circle(surf, outline, (cx, cy + 2), 6, 1)
            pygame.draw.line(surf, (200, 150, 60), (cx + 3, cy - 3), (cx + 5, cy - 7), 2)
        elif 'sword' in item_type or item_type == 'battleaxe':
            pygame.draw.line(surf, color, (cx, 1), (cx, TILE_SIZE - 5), 3)
            pygame.draw.line(surf, outline, (3, 5), (TILE_SIZE - 3, 5), 2)
        elif 'shield' in item_type:
            pygame.draw.polygon(surf, color, [(2, 2), (TILE_SIZE - 2, 2),
                                              (TILE_SIZE - 2, cy), (cx, TILE_SIZE - 1), (2, cy)])
            pygame.draw.polygon(surf, outline, [(2, 2), (TILE_SIZE - 2, 2),
                                                (TILE_SIZE - 2, cy), (cx, TILE_SIZE - 1), (2, cy)], 1)
        elif item_type == 'bow':
            pygame.draw.arc(surf, color, (2, 1, TILE_SIZE - 4, TILE_SIZE - 2), -1.4, 1.4, 2)
        else:
            pygame.draw.rect(surf, color, (3, 3, TILE_SIZE - 6, TILE_SIZE - 6), border_radius=3)
            pygame.draw.rect(surf, outline, (3, 3, TILE_SIZE - 6, TILE_SIZE - 6), 1, border_radius=3)

        cache[item_type] = surf
        return surf

    def _render_items(self):
        """Draw ground items from client state (PLO_ITEMADD/PLO_ITEMDEL). Reads
        client.items live each frame, like baddies/chests - pickup already
        removes the entry client-side so it just stops being drawn."""
        items = getattr(self.client, "items", None)
        if not items:
            return
        surf_w, surf_h = self.screen.get_size()
        for (ix, iy), item_type in items.items():
            sprite = self._get_item_sprite(item_type)
            sx, sy = self._world_to_screen(ix, iy)
            if sx < -TILE_SIZE or sx > surf_w or sy < -TILE_SIZE or sy > surf_h:
                continue
            self.screen.blit(sprite, (int(sx), int(sy)))

    def _get_chest_sprite(self, opened: bool) -> Optional[pygame.Surface]:
        """Build (and cache) the chest sprite from tileset tiles.

        Chests are a client-side overlay (not baked into the level board), so we
        composite the chest graphic from the tileset here, using distinct tiles
        for the open vs closed state.
        """
        cache = getattr(self, "_chest_sprite_cache", None)
        if cache is None:
            cache = {}
            self._chest_sprite_cache = cache
        if opened in cache:
            return cache[opened]

        layout = self.CHEST_TILES_OPEN if opened else self.CHEST_TILES_CLOSED
        rows = len(layout)
        cols = len(layout[0])
        surf = pygame.Surface((cols * TILE_SIZE, rows * TILE_SIZE), pygame.SRCALPHA)

        drew_any = False
        for ry, row in enumerate(layout):
            for cx, tile_id in enumerate(row):
                tile = self.tileset_mgr.get_tile(tile_id)
                if tile:
                    surf.blit(tile, (cx * TILE_SIZE, ry * TILE_SIZE))
                    drew_any = True

        if not drew_any:
            # Tileset may not be ready yet — don't cache the miss, retry later.
            return None

        cache[opened] = surf
        return surf
    def _render_chests(self):
        """Draw level chests from client state, reflecting open/closed."""
        chests = getattr(self.client, "chests", None)
        if not chests:
            return

        # Cull against the actual draw surface — while zoomed that's the smaller
        # offscreen scene, not the full canvas, so SCREEN_WIDTH/HEIGHT are wrong.
        surf_w, surf_h = self.screen.get_size()
        for (cx, cy), opened in chests.items():
            sprite = self._get_chest_sprite(bool(opened))
            if sprite is None:
                continue
            # Chest tile (cx, cy) is the top-left of its 2x2 footprint, and the
            # sprite is exactly 2 tiles wide, so it maps straight to that tile.
            sx, sy = self._world_to_screen(cx, cy)
            if sx < -sprite.get_width() or sx > surf_w or \
               sy < -sprite.get_height() or sy > surf_h:
                continue
            self.screen.blit(sprite, (int(sx), int(sy)))
    def _check_and_render_signs(self):
        """Check if player is near a sign in the current level and show popup."""
        signs = self.client.signs.get(self.client._current_level_name)
        if not signs:
            return

        # Sign coords are LOCAL (0-63); compare against the player's local feet
        # position so it works in a GMAP (where player.x/y are world coords).
        px = (self.client.player.x + 1.0) % 64
        py = (self.client.player.y + 2.5) % 64

        for (sx, sy), text in signs.items():
            if abs(px - sx) < 2 and abs(py - sy) < 2:
                self._render_sign_popup(text)
                break  # Only show one sign at a time
    def _render_sign_popup(self, text: str):
        """Render sign text as popup overlay."""
        if not text:
            return

        # Render sign text in a box at bottom of screen
        font = getattr(self, '_sign_font', None)
        if font is None:
            try:
                self._sign_font = pygame.font.Font(None, 24)
            except:
                self._sign_font = pygame.font.SysFont('monospace', 20)
            font = self._sign_font

        # Split text into lines
        lines = text.split('\n')
        line_height = font.get_linesize()
        max_width = 0
        rendered_lines = []

        for line in lines:
            rendered = font.render(line, True, (0, 0, 0))
            rendered_lines.append(rendered)
            max_width = max(max_width, rendered.get_width())

        # Create background box
        box_width = max_width + 20
        box_height = len(rendered_lines) * line_height + 20
        box_x = (self.screen_w - box_width) // 2
        box_y = self.screen_h - box_height - 60  # Above the UI bar

        # Draw box with border
        pygame.draw.rect(self.screen, (240, 230, 200), (box_x, box_y, box_width, box_height))
        pygame.draw.rect(self.screen, (100, 80, 50), (box_x, box_y, box_width, box_height), 2)

        # Draw text
        y = box_y + 10
        for rendered in rendered_lines:
            x = box_x + (box_width - rendered.get_width()) // 2
            self.screen.blit(rendered, (x, y))
            y += line_height
