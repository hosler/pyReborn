"""CollisionMixin — Tile-type queries and position/collision checks.

Split from pygame_game.py; methods operate on the GameClient instance."""

import time
import json
import math
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
from ..tiletypes import TileType, get_tile_type, type_is_blocking
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
        """Check if tile is blocking, using corrections.

        Uses the shared threshold predicate (the C# client's style) so the blocking
        rule lives in one place instead of being duplicated as a type set."""
        return type_is_blocking(self._get_corrected_tile_type(tile_id))
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
        """Get required glove power to lift tile, using corrections.

        Bushes and pots lift bare-handed (power 0); rocks need a glove (power 1).
        """
        tile_type = self._get_corrected_tile_type(tile_id)
        if tile_type in (TileType.BUSH, TileType.POT):
            return 0
        elif tile_type == TileType.ROCK:
            return 1
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

    # Per-facing interaction offsets — the original Reborn client's Player._touchtestd
    # idea. Each entry lists the (dx, dy) tile offsets from the sprite's TOP-LEFT to
    # the point(s) probed when grabbing / lifting / reading something in that
    # direction. The feet footprint is the 2-wide box at columns {x, x+1}, row y+2
    # (see _check_collision). Up/down probe both feet columns one row beyond the
    # box; left/right probe the *adjacent* column at feet- and torso-height. This
    # replaces a single feet point plus a symmetric unit delta, which only ever
    # probed the feet row and — because the feet point sits on the box's right edge
    # — probed the player's own left column instead of the tile to its left.
    TOUCH_OFFSETS = {
        0: [(0.5, 1.5), (1.5, 1.5)],    # up:    both columns, row above the box
        1: [(-0.5, 2.5), (-0.5, 1.5)],  # left:  adjacent column, feet + torso
        2: [(0.5, 3.5), (1.5, 3.5)],    # down:  both columns, row below the box
        3: [(2.5, 2.5), (2.5, 1.5)],    # right: adjacent column, feet + torso
    }

    def _touch_points(self, direction: int) -> List[Tuple[float, float]]:
        """World-tile coords probed for interactions in the given facing direction
        (0=up, 1=left, 2=down, 3=right). First entry is the primary point."""
        offs = self.TOUCH_OFFSETS.get(
            direction, [(self.PLAYER_FEET_DX, self.PLAYER_FEET_DY)])
        return [(self.client.x + ox, self.client.y + oy) for ox, oy in offs]
    def _level_tiles_at(self, x: float, y: float):
        """(level_name, tiles) for the level segment containing world (x, y).

        In a GMAP the segment is derived from the world coordinates via the
        grid — using the *current* level's tiles with a %64 wrap (the old
        behavior) made every collision probe near a segment boundary test the
        wrong level's tiles, which is exactly where walls felt flaky."""
        if self.client.in_gmap_segment:
            grid = (math.floor(x / 64), math.floor(y / 64))
            seg = self.client.gmap_grid.get(grid)
            if seg:
                return seg, self.client.levels.get(seg)
            return None, None
        name = self.client._current_level_name
        return name, (self.client.levels.get(name) or self.client.tiles)

    def _get_tile_at(self, x: float, y: float) -> int:
        """Get the tile ID at a given position (in tile coordinates)."""
        _, tiles = self._level_tiles_at(x, y)
        if not tiles:
            return 0  # Default to walkable

        # Convert to tile indices (floor, not int(): int() truncates toward
        # zero and mis-tiles fractional negatives). Only GMAP world coords get
        # the %64 localization — on a standalone level an off-board probe must
        # read as out-of-world (blocking), not wrap to the far column the way
        # floor(-1.5) % 64 == 63 would (edge lifts/touches sampled the
        # opposite side of the board).
        tx = math.floor(x)
        ty = math.floor(y)
        if self.client.in_gmap_segment:
            tx %= 64
            ty %= 64
        if tx < 0 or tx >= 64 or ty < 0 or ty >= 64:
            return -1  # out of world: blocking, not water/liftable

        tile_idx = ty * 64 + tx
        if tile_idx >= len(tiles):
            return -1

        return tiles[tile_idx]
    def _is_position_blocked(self, x: float, y: float, dx: int = 0, dy: int = 0) -> bool:
        """Check if a destination position is blocked.

        Uses corrected tile types from user edits.

        Player world position (x, y) is the TOP-LEFT of the sprite. The sprite is
        2 tiles wide and 3 tall; collision is checked against the "feet" box
        covering both feet at the bottom row. The box is inset 0.4 from the
        sprite's side edges: the outer pixels of the 2-wide cell are transparent
        margin, so a full-width box (tried) stops visibly short of walls —
        "too aggressive" — while the old 0.5-inset let half of each foot clip
        into walls. (dx, dy) is the movement direction.
        """
        for cx, cy in self._feet_samples(x, y):
            if self._is_blocked_at(cx, cy):
                return True

        return False

    # Feet box geometry: left/right inset 0.4 from the 2-wide sprite's edges,
    # box covers the bottom row (y+2..y+3). The box is half-open: its
    # right/bottom edge sitting exactly on a tile boundary does NOT occupy the
    # next tile. Without the epsilon, a feet edge flush against a wall (e.g.
    # 35.0) floors into the wall tile and the player stops a step (~4px)
    # short. Inset the far edges so you can move flush against walls.
    _FEET_EPS = 1e-3
    _FEET_LEFT, _FEET_RIGHT = 0.4, 1.6
    _FEET_TOP, _FEET_BOTTOM = 2.0, 3.0

    def _feet_samples(self, x: float, y: float):
        """Sample points covering the feet box at player position (x, y).
        Three x-samples: a >1-wide box can span 3 tile columns when unaligned,
        and corner-only sampling would miss the middle one."""
        for cx in (x + self._FEET_LEFT, x + 1.0, x + self._FEET_RIGHT - self._FEET_EPS):
            for cy in (y + self._FEET_TOP, y + self._FEET_BOTTOM - self._FEET_EPS):
                yield cx, cy

    def _blocked_sample_count(self, x: float, y: float) -> int:
        """How many feet-box samples at (x, y) are blocked. Used by _move's
        stuck-escape: a move out of a bad spawn may hold or reduce this count
        but never deepen the overlap."""
        return sum(1 for cx, cy in self._feet_samples(x, y)
                   if self._is_blocked_at(cx, cy))

    def _position_out_of_bounds(self, x: float, y: float) -> bool:
        """Feet box partially outside the walkable world: the standalone 64x64
        board, or the stitched gmap rectangle when inside a segment. Enforced
        even for the stuck-escape, which bypasses tile blocking."""
        if self.client.in_gmap_segment:
            max_x = self.client.gmap_width * 64
            max_y = self.client.gmap_height * 64
        else:
            max_x = max_y = 64
        return (x + self._FEET_LEFT < 0 or x + self._FEET_RIGHT > max_x or
                y + self._FEET_TOP < 0 or y + self._FEET_BOTTOM > max_y)
    def _is_blocked_at(self, x: float, y: float) -> bool:
        """True if the single tile at world position (x, y) blocks movement.

        Outside the current level's 64x64 bounds counts as blocking unless we're
        in an actual GMAP segment (where adjacent levels are stitched in and
        provide real tiles); this stops the player from walking off the edge of
        a standalone level, including interior levels (houses/caves) reached via
        a door while a GMAP is still loaded.
        """
        # Noclip escape hatch: nothing blocks (used to walk out of a bad spawn).
        if getattr(self, "noclip", False):
            return False

        if self.client.in_gmap_segment:
            # Clamp to the full GMAP world: inner segment boundaries stitch
            # together, but the outer perimeter has no neighbour to walk into.
            if (x < 0 or x >= self.client.gmap_width * 64 or
                    y < 0 or y >= self.client.gmap_height * 64):
                return True
        else:
            if x < 0 or x >= 64 or y < 0 or y >= 64:
                return True

        if self._chest_blocks(x, y):
            return True

        tile_id = self._get_tile_at(x, y)
        return self._is_tile_blocking(tile_id)
    def _chest_blocks(self, x: float, y: float) -> bool:
        """True if (x, y) lies inside a chest's 2x2 footprint. Chests are solid
        objects (open or closed), so they block walking like a wall."""
        chests = getattr(self.client, "chests", None)
        if not chests:
            return False
        tx, ty = math.floor(x), math.floor(y)
        for (cx, cy) in chests:
            if cx <= tx <= cx + 1 and cy <= ty <= cy + 1:
                return True
        return False
    def _check_water_at_position(self, x: float, y: float) -> bool:
        """Check if the position is in water."""
        tile_id = self._get_tile_at(x, y)
        return self._is_tile_water(tile_id)
