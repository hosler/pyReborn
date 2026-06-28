"""WorldRenderMixin — level/tile world surface composition.

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


class WorldRenderMixin:
    """Mixin providing the above methods for GameClient."""

    def _render_world(self):
        """Render the tile world."""
        c = self.client
        # On a first-visit (non-GMAP) level, the board streams in a few frames
        # after the warp. Until it arrives, self.tiles still holds the OLD
        # level's board — drawing it puts the player over the wrong tiles (the
        # "warped before the new tiles render" glitch). Show a loading state
        # instead. Cached levels are repopulated synchronously in warp_to_level,
        # so this only triggers on genuinely-new levels.
        in_gmap = c._current_level_name in c.gmap_grid.values()
        if (not in_gmap and c._current_level_name
                and c._tiles_level_name != c._current_level_name):
            self._render_level_loading()
            return

        world_surf = self._get_world_surface()
        if not world_surf:
            return

        # The world surface is indexed from render-frame tile (0, 0), so its
        # blit position is simply where the camera maps that tile.
        self.screen.blit(world_surf, self.camera.world_to_screen(0, 0))

    def _render_level_loading(self):
        """Brief overlay shown while a newly-entered level's board streams in."""
        text = self.font.render("Loading level...", True, (235, 235, 235))
        self.screen.blit(text, (self.screen_w // 2 - text.get_width() // 2,
                                self.screen_h // 2 - text.get_height() // 2))
    def _get_world_surface(self) -> Optional[pygame.Surface]:
        """Get or create the world surface."""
        if not self.client.levels and not self.client.tiles:
            return None

        # Check if we need to invalidate cache
        current_count = len(self.client.levels) + (1 if self.client.tiles else 0)
        current_level = self.client._current_level_name
        current_level_keys = set(self.client.levels.keys())

        # Invalidate if: count changed, level changed, or new levels appeared
        needs_redraw = (
            current_count != self.last_level_count or
            current_level != self.last_level_name or
            not current_level_keys.issubset(self.known_levels)
        )

        if not needs_redraw and self.world_surface:
            return self.world_surface

        # Update tracking
        self.last_level_count = current_count
        self.last_level_name = current_level
        self.known_levels.update(current_level_keys)

        # Check if current level is in GMAP
        in_gmap = self.client._current_level_name in self.client.gmap_grid.values()

        if in_gmap and self.client.gmap_grid:
            world_w = max(1, self.client.gmap_width) * 64 * TILE_SIZE
            world_h = max(1, self.client.gmap_height) * 64 * TILE_SIZE
        else:
            world_w = 64 * TILE_SIZE
            world_h = 64 * TILE_SIZE

        self.world_surface = pygame.Surface((world_w, world_h))
        self.world_surface.fill((0, 0, 0))

        # Render tiles
        if not in_gmap or not self.client.gmap_grid:
            self._render_single_level(self.world_surface, self.client.tiles, 0, 0)
        else:
            for (gx, gy), level_name in self.client.gmap_grid.items():
                if level_name in self.client.levels:
                    level_tiles = self.client.levels[level_name]
                    offset_x = gx * 64 * TILE_SIZE
                    offset_y = gy * 64 * TILE_SIZE
                    self._render_single_level(self.world_surface, level_tiles, offset_x, offset_y)

        return self.world_surface
    def _render_single_level(self, surface: pygame.Surface, tiles: List[int],
                              offset_x: int, offset_y: int):
        """Render a single level's tiles."""
        if not tiles:
            return

        for ty in range(64):
            for tx in range(64):
                tile_id = tiles[ty * 64 + tx]
                dest_x = offset_x + tx * TILE_SIZE
                dest_y = offset_y + ty * TILE_SIZE

                tile = self.tileset_mgr.get_tile_or_color(tile_id)
                surface.blit(tile, (dest_x, dest_y))
