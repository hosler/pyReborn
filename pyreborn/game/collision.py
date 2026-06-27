"""CollisionMixin — Tile-type queries and position/collision checks.

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


class CollisionMixin:
    """Mixin providing the above methods for GameClient."""

    def _get_corrected_tile_type(self, tile_id: int) -> int:
        """Get tile type, using corrections if available."""
        if tile_id in self.tile_corrections:
            return self.tile_corrections[tile_id]
        return get_tile_type(tile_id)
    def _is_tile_blocking(self, tile_id: int) -> bool:
        """Check if tile is blocking, using corrections."""
        tile_type = self._get_corrected_tile_type(tile_id)
        # Blocking includes solid walls and objects like bushes, rocks, pots
        return tile_type in (
            TileType.BLOCKING,
            TileType.BED_UPPER,
            TileType.BED_LOWER,
            TileType.THROW_THROUGH,
            TileType.BUSH,
            TileType.ROCK,
            TileType.POT,
        )
    def _is_tile_water(self, tile_id: int) -> bool:
        """Check if tile is water, using corrections."""
        tile_type = self._get_corrected_tile_type(tile_id)
        return tile_type in (TileType.WATER, TileType.NEAR_WATER)
    def _is_tile_chair(self, tile_id: int) -> bool:
        """Check if tile is a chair, using corrections."""
        tile_type = self._get_corrected_tile_type(tile_id)
        return tile_type == TileType.CHAIR
    def _is_tile_liftable(self, tile_id: int) -> bool:
        """Check if tile is liftable (bush/rock/pot), using corrections."""
        tile_type = self._get_corrected_tile_type(tile_id)
        return tile_type in (TileType.BUSH, TileType.ROCK, TileType.POT)
    def _get_tile_lift_power(self, tile_id: int) -> int:
        """Get required glove power to lift tile, using corrections."""
        tile_type = self._get_corrected_tile_type(tile_id)
        if tile_type == TileType.BUSH:
            return 1
        elif tile_type == TileType.POT:
            return 2
        elif tile_type == TileType.ROCK:
            return 3
        return 0
    def _get_liftable_name(self, tile_id: int) -> str:
        """Get the name of a liftable object, using corrections."""
        tile_type = self._get_corrected_tile_type(tile_id)
        if tile_type == TileType.BUSH:
            return "bush"
        elif tile_type == TileType.POT:
            return "pot"
        elif tile_type == TileType.ROCK:
            return "rock"
        return ""

    # Player feet offset from the sprite's top-left (sprite is 2 wide, 3 tall).
    # Interactions (chairs, pickups, signs) happen relative to where the player
    # visually stands, NOT the sprite's top-left corner.
    PLAYER_FEET_DX = 1.0
    PLAYER_FEET_DY = 2.5
    def _player_feet(self) -> Tuple[float, float]:
        """World-tile coordinates of the player's feet (standing point)."""
        return (self.client.x + self.PLAYER_FEET_DX,
                self.client.y + self.PLAYER_FEET_DY)
    def _get_tile_at(self, x: float, y: float) -> int:
        """Get the tile ID at a given position (in tile coordinates)."""
        # Get the current level's tiles
        if self.client.is_gmap:
            # In GMAP mode, need to find the correct level for this position
            level_name = self.client._current_level_name
            tiles = self.client.levels.get(level_name, self.client.tiles)
        else:
            tiles = self.client.tiles

        if not tiles:
            return 0  # Default to walkable

        # Convert to tile indices
        tx = int(x) % 64
        ty = int(y) % 64

        # Bounds check
        if tx < 0 or tx >= 64 or ty < 0 or ty >= 64:
            return 0

        tile_idx = ty * 64 + tx
        if tile_idx < 0 or tile_idx >= len(tiles):
            return 0

        return tiles[tile_idx]
    def _is_position_blocked(self, x: float, y: float, dx: int = 0, dy: int = 0) -> bool:
        """Check if a destination position is blocked.

        Uses corrected tile types from user edits.

        Player world position (x, y) is the TOP-LEFT of the sprite. The sprite is
        2 tiles wide and 3 tall; collision is checked against the "feet" box at
        the bottom-center of the sprite rather than a single point, so the player
        can't clip a corner into a wall. (dx, dy) is the movement direction.
        """
        # Feet hitbox, in tile offsets from the sprite's top-left. A ~1-tile-wide
        # box centered under the 2-tile-wide sprite, covering the bottom tile row.
        left, right = 0.5, 1.5
        top, bottom = 2.1, 2.9

        for cx in (x + left, x + right):
            for cy in (y + top, y + bottom):
                if self._is_blocked_at(cx, cy):
                    return True

        return False
    def _is_blocked_at(self, x: float, y: float) -> bool:
        """True if the single tile at world position (x, y) blocks movement.

        Outside the current level's 64x64 bounds counts as blocking unless we're
        in an actual GMAP segment (where adjacent levels are stitched in and
        provide real tiles); this stops the player from walking off the edge of
        a standalone level, including interior levels (houses/caves) reached via
        a door while a GMAP is still loaded.
        """
        if self.client.in_gmap_segment:
            # Clamp to the full GMAP world: inner segment boundaries stitch
            # together, but the outer perimeter has no neighbour to walk into.
            if (x < 0 or x >= self.client.gmap_width * 64 or
                    y < 0 or y >= self.client.gmap_height * 64):
                return True
        else:
            if x < 0 or x >= 64 or y < 0 or y >= 64:
                return True

        tile_id = self._get_tile_at(x, y)
        return self._is_tile_blocking(tile_id)
    def _check_water_at_position(self, x: float, y: float) -> bool:
        """Check if the position is in water."""
        tile_id = self._get_tile_at(x, y)
        return self._is_tile_water(tile_id)
