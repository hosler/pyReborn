"""MinimapMixin — Minimap surface construction and palette.

Split from pygame_game.py; methods operate on the GameClient instance."""

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


class MinimapMixin:
    """Mixin providing the above methods for GameClient."""

    def _build_minimap_surface(self):
        """Build minimap surface from data."""
        if not self.minimap_data:
            return

        # Minimap data is typically a 64x64 or 128x128 grid of color indices
        # Each byte represents a tile's color (0-255 palette index)
        data_len = len(self.minimap_data)

        # Determine minimap grid size
        if data_len >= 128 * 128:
            grid_size = 128
        elif data_len >= 64 * 64:
            grid_size = 64
        else:
            grid_size = int(data_len ** 0.5)
            if grid_size * grid_size != data_len:
                return  # Invalid data size

        # Create surface at native resolution
        self.minimap_surface = pygame.Surface((grid_size, grid_size))

        # Simple color palette for minimap
        palette = self._get_minimap_palette()

        # Fill pixels
        for y in range(grid_size):
            for x in range(grid_size):
                idx = y * grid_size + x
                if idx < len(self.minimap_data):
                    color_idx = self.minimap_data[idx]
                    color = palette[color_idx % len(palette)]
                    self.minimap_surface.set_at((x, y), color)

        # Scale to display size
        self.minimap_surface = pygame.transform.scale(
            self.minimap_surface, self.minimap_size
        )
    def _get_minimap_palette(self) -> List[Tuple[int, int, int]]:
        """Get color palette for minimap rendering."""
        # Common tile type colors
        palette = [(0, 0, 0)] * 256  # Default black

        # Grass/ground tones
        for i in range(0, 32):
            palette[i] = (34 + i * 2, 139 + i, 34)  # Green tones

        # Water tones
        for i in range(32, 64):
            palette[i] = (30, 100 + i, 200 + min(55, i))  # Blue tones

        # Rock/wall tones
        for i in range(64, 96):
            palette[i] = (100 + i - 64, 100 + i - 64, 100 + i - 64)  # Gray tones

        # Sand tones
        for i in range(96, 128):
            palette[i] = (194, 178, 128 + i - 96)  # Tan tones

        # Building/road tones
        for i in range(128, 160):
            palette[i] = (139 + i - 128, 90 + i - 128, 43)  # Brown tones

        # Special markers
        palette[255] = (255, 0, 0)  # Player position / important markers
        palette[254] = (255, 255, 0)  # NPCs / points of interest
        palette[253] = (0, 255, 255)  # Warps / doors

        return palette
