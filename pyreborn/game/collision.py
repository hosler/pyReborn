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

    # Ground-sample point (swim/grass/chair/bed/shallow-water/lava) and default
    # touch point, per the classic-engine spec: the CENTRE of the player's 2x2
    # collision box, which is itself centred on (x+1.5, y+2.5) — NOT the
    # sprite's top-left corner. (Character sprite is 3x3 tiles, top-left
    # anchored at (x, y); the collision/ground-sample geometry is the
    # narrower box below.) Corroborated by GServer-v2's touchTest tables
    # (PlayerClient.cpp:1825 testForLinks, :1760 testForTouch), which probe
    # around the same x+1.5 horizontal centre — see _feet_samples below.
    PLAYER_FEET_DX = 1.5
    PLAYER_FEET_DY = 2.5
    def _player_feet(self) -> Tuple[float, float]:
        """World-tile coordinates of the ground-sample centre point."""
        return (self.client.x + self.PLAYER_FEET_DX,
                self.client.y + self.PLAYER_FEET_DY)

    # Per-facing interaction offsets — the original Reborn client's Player._touchtestd
    # idea. Each entry lists the (dx, dy) tile offsets from the sprite's TOP-LEFT to
    # the point(s) probed when grabbing / lifting / reading something in that
    # direction. Reach is derived from the spec collision box's edges/centre
    # (_FEET_LEFT/_FEET_RIGHT/_FEET_TOP/_FEET_BOTTOM below: 0.5/2.5/1.5/3.5),
    # NOT the wider 3-tile visual sprite — up/down probe the box's two
    # half-width columns (x+1.0, x+2.0) one row beyond the box's top/bottom
    # edge; left/right probe one column beyond the box's left/right edge at
    # feet- and torso-height (unchanged from before: the box's vertical
    # centre/DY didn't move). This replaces a single feet point plus a
    # symmetric unit delta, which only ever probed the feet row and —
    # because the feet point sits on the box's right edge — probed the
    # player's own left column instead of the tile to its left.
    TOUCH_OFFSETS = {
        0: [(1.0, 1.0), (2.0, 1.0)],    # up:    both box columns, row above the box
        1: [(0.0, 2.5), (0.0, 1.5)],    # left:  adjacent column, feet + torso
        2: [(1.0, 4.0), (2.0, 4.0)],    # down:  both box columns, row below the box
        3: [(3.0, 2.5), (3.0, 1.5)],    # right: adjacent column, feet + torso
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

    def _world_to_level_local(self, x: float, y: float) -> Tuple[int, int]:
        """Floor (x, y) to the level-local tile frame (0-63) that per-level
        state (tiles, chests, ...) is keyed by. Only GMAP world coords get
        the %64 localization — on a standalone level an off-board probe must
        read as out-of-world, not wrap to the far column the way
        floor(-1.5) % 64 == 63 would (edge lifts/touches sampled the
        opposite side of the board)."""
        tx = math.floor(x)
        ty = math.floor(y)
        if self.client.in_gmap_segment:
            tx %= 64
            ty %= 64
        return tx, ty

    def _get_tile_at(self, x: float, y: float) -> int:
        """Get the tile ID at a given position (in tile coordinates)."""
        _, tiles = self._level_tiles_at(x, y)
        if not tiles:
            # No tile data resolves here. A gmap cell with no known segment
            # at all (a hole in the grid, or straight off its edge) is
            # genuinely outside the world and must block, matching the
            # in-board OOB path below -- treating it as walkable let players
            # walk clean through unstreamed/absent segments. A *known*
            # segment (or a standalone level) whose board simply hasn't
            # streamed in yet is different: that's exactly the window right
            # after connect/warp before PLO_BOARDPACKET arrives, and
            # blocking it would freeze movement dead at spawn -- stay
            # walkable there.
            if self.client.in_gmap_segment:
                grid = (math.floor(x / 64), math.floor(y / 64))
                if grid not in self.client.gmap_grid:
                    return -1  # out of world: blocking, not water/liftable
            return 0  # Default to walkable

        # Convert to tile indices (floor, not int(): int() truncates toward
        # zero and mis-tiles fractional negatives).
        tx, ty = self._world_to_level_local(x, y)
        if tx < 0 or tx >= 64 or ty < 0 or ty >= 64:
            return -1  # out of world: blocking, not water/liftable

        tile_idx = ty * 64 + tx
        if tile_idx >= len(tiles):
            return -1

        return tiles[tile_idx]
    def _is_position_blocked(self, x: float, y: float, dx: int = 0, dy: int = 0) -> bool:
        """Check if a destination position is blocked.

        Uses corrected tile types from user edits.

        Player world position (x, y) is the TOP-LEFT of the 3x3-tile sprite.
        Collision is checked against the classic-engine spec's 2x2-tile box
        CENTRED on (x+1.5, y+2.5): it spans x+0.5..x+2.5 horizontally and
        y+1.5..y+3.5 vertically (see _feet_samples). (dx, dy) is the movement
        direction.
        """
        for cx, cy in self._feet_samples(x, y):
            if self._is_blocked_at(cx, cy):
                return True

        return False

    # Collision box geometry, per the classic-engine spec: a 2x2-tile box
    # centred on (x+1.5, y+2.5) — x+0.5..x+2.5 horizontally, y+1.5..y+3.5
    # vertically. (Previously this was a narrower, off-centre "feet" box
    # (x+0.4..x+1.6, y+2.0..y+3.0) that put the horizontal centre at x+1.0
    # instead of x+1.5 — exactly the "lands 0.5 tiles left of doorways" bug.)
    # The box is half-open: its right/bottom edge sitting exactly on a tile
    # boundary does NOT occupy the next tile. Without the epsilon, an edge
    # flush against a wall (e.g. 35.0) floors into the wall tile and the
    # player stops a step (~4px) short. Inset the far edges so you can move
    # flush against walls.
    _FEET_EPS = 1e-3
    _FEET_LEFT, _FEET_RIGHT = 0.5, 2.5
    _FEET_TOP, _FEET_BOTTOM = 1.5, 3.5

    def _feet_samples(self, x: float, y: float):
        """Sample points covering the collision box at player position (x, y).

        Three x-samples AND three y-samples: the box is 2.0 tiles wide/tall
        on both axes, so an unaligned position can span 3 tile columns *and*
        3 tile rows (e.g. box top/bottom at y+1.8/y+3.8 covers rows y+1,
        y+2, y+3) — corner-only sampling would miss the middle row/column.
        (The old box was only 1.0 tile tall, which by construction can never
        span more than 2 rows, so 2 y-samples used to be enough; growing the
        box to the spec's 2x2 size reopened that same class of tunneling gap
        on the y-axis, so the fix is mirrored here too.)
        """
        for cx in (x + self._FEET_LEFT, x + 1.5, x + self._FEET_RIGHT - self._FEET_EPS):
            for cy in (y + self._FEET_TOP, y + 2.5, y + self._FEET_BOTTOM - self._FEET_EPS):
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
        # Chest keys are level-local (0-63; see client.py's PLO_LEVELCHEST
        # handler), but (x, y) is world-frame in a GMAP — fold it to the
        # current segment's local frame the same way tile lookups do, or
        # chests off the origin segment are never solid.
        tx, ty = self._world_to_level_local(x, y)
        level_name, _ = self._level_tiles_at(x, y)
        if not level_name:
            return False
        chests = self.client.chests_in_level(level_name)
        for (cx, cy) in chests:
            if cx <= tx <= cx + 1 and cy <= ty <= cy + 1:
                return True
        return False
    def _check_water_at_position(self, x: float, y: float) -> bool:
        """Check if the position is in water."""
        tile_id = self._get_tile_at(x, y)
        return self._is_tile_water(tile_id)
