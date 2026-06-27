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


class LevelObjectsRenderMixin:
    """Mixin providing the above methods for GameClient."""

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
        """Check if player is near a sign and show popup."""
        if not self.client.signs:
            return

        px = self.client.player.x
        py = self.client.player.y

        # Check each sign
        for (sx, sy), text in self.client.signs.items():
            # Check if player is within 2 tiles of sign
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
        box_x = (SCREEN_WIDTH - box_width) // 2
        box_y = SCREEN_HEIGHT - box_height - 60  # Above the UI bar

        # Draw box with border
        pygame.draw.rect(self.screen, (240, 230, 200), (box_x, box_y, box_width, box_height))
        pygame.draw.rect(self.screen, (100, 80, 50), (box_x, box_y, box_width, box_height), 2)

        # Draw text
        y = box_y + 10
        for rendered in rendered_lines:
            x = box_x + (box_width - rendered.get_width()) // 2
            self.screen.blit(rendered, (x, y))
            y += line_height
