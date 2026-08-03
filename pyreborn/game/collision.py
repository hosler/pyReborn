"""CollisionMixin — Tile-type queries and position/collision checks.

Split from pygame_game.py; methods operate on the GameClient instance."""

import math
from typing import List, Optional, Tuple

from reborn_protocol.coords import (
    LEVEL_SIZE, gmap_extent, in_level_bounds, level_index, local_coord,
    segment_at,
)

from ..tiletypes import (
    TileType, get_tile_type, type_is_blocking,
)
from .constants import (
    MOVE_STEP, CORNER_ASSIST_MAX,
    PLAYER_COLLISION_LEFT, PLAYER_COLLISION_RIGHT,
    PLAYER_COLLISION_TOP, PLAYER_COLLISION_BOTTOM,
    PLAYER_BODY_CENTER_X, PLAYER_BODY_CENTER_Y,
    PLAYER_STAND_X, PLAYER_STAND_Y,
    PLAYER_GROUND_X, PLAYER_GROUND_Y,
)


class CollisionMixin:
    """Mixin providing the above methods for GameClient."""

    def _tile_type(self, tile_id: int) -> int:
        """The tile's type, straight from the loaded type table.

        There is no per-client override layer. The only thing the old
        `tile_corrections.json` overlay still encoded was which tile ids are
        liftable objects, and those are not a tile type at all in the
        reference client - see pyreborn/liftobjects.py.
        """
        return get_tile_type(tile_id)

    def _is_tile_blocking(self, tile_id: int) -> bool:
        """Check if tile is blocking.

        Uses the shared threshold predicate (the C# client's style) so the
        blocking rule lives in one place instead of being duplicated as a
        type set."""
        return type_is_blocking(self._tile_type(tile_id))

    def _is_tile_swimming_water(self, tile_id: int) -> bool:
        """Check if tile is deep enough for swimming."""
        return self._tile_type(tile_id) == TileType.WATER

    def _effective_tile_type(self, x: float, y: float) -> int:
        """Tile TYPE in force at world (x, y): a script NPC's setshape2 overlay
        first, the board's own type second.

        `TServerLevel::getTileType` (Preagonal/FourPlay/quattroplay/src/
        TServerLevel.cpp:688-708) asks the level's NPCs before the board and
        takes any NPC answer above 1. Classic Bomber's player-base rooms are
        built entirely this way: the room controller paints the whole 64x64
        room with `setshape2 64,64,obj`, so a placed chair is a type-3 cell in
        that array and NOTHING on the board says chair. Reading the board
        alone is why walking onto your own furniture did nothing."""
        gs1 = getattr(self, 'gs1', None)
        if gs1 is not None:
            try:
                ttype = int(gs1.npc_tile_type(x, y))
            except Exception:
                ttype = 0
            if ttype > 1:
                return ttype
        return self._tile_type(self._get_tile_at(x, y))
    # Ground sampling uses the standing point between the feet. It is distinct
    # from the collision box's centre after the box's half-tile upward shift.
    PLAYER_FEET_DX = PLAYER_STAND_X
    PLAYER_FEET_DY = PLAYER_STAND_Y
    def _player_feet(self) -> Tuple[float, float]:
        """World-tile coordinates of the ground-sample centre point."""
        return (self.client.x + self.PLAYER_FEET_DX,
                self.client.y + self.PLAYER_FEET_DY)

    # The point the official client asks "what am I standing on?" - see
    # PLAYER_GROUND_X/Y in constants.py for the oracle sites. Half a tile
    # ABOVE _player_feet, which is the community-described standing point.
    PLAYER_GROUND_DX = PLAYER_GROUND_X
    PLAYER_GROUND_DY = PLAYER_GROUND_Y

    def _player_ground(self) -> Tuple[float, float]:
        """World-tile coordinates the ground TYPE is sampled at (chair, and
        the water/lava/swamp tests the oracle shares this point with)."""
        return (self.client.x + self.PLAYER_GROUND_DX,
                self.client.y + self.PLAYER_GROUND_DY)

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
            grid = segment_at(x, y)
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
        floor(-1.5) % 64 == 62 would (edge lifts/touches sampled the
        opposite side of the board)."""
        tx = math.floor(x)
        ty = math.floor(y)
        if self.client.in_gmap_segment:
            tx = local_coord(tx)
            ty = local_coord(ty)
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
                if segment_at(x, y) not in self.client.gmap_grid:
                    return -1  # out of world: blocking, not water/liftable
            return 0  # Default to walkable

        # Convert to tile indices (floor, not int(): int() truncates toward
        # zero and mis-tiles fractional negatives).
        tx, ty = self._world_to_level_local(x, y)
        if not in_level_bounds(tx, ty):
            return -1  # out of world: blocking, not water/liftable

        tile_idx = level_index(tx, ty)
        if tile_idx >= len(tiles):
            return -1

        return tiles[tile_idx]
    def _is_position_blocked(self, x: float, y: float, dx: int = 0, dy: int = 0) -> bool:
        """Check if a destination position is blocked.

        Uses corrected tile types from user edits.

        Player world position (x, y) is the TOP-LEFT of the 3x3-tile sprite.
        Collision is checked against the 2x2-tile box spanning
        x+0.5..x+2.5 horizontally and y+1.0..y+3.0 vertically. (dx, dy) is
        the movement direction.
        """
        for cx, cy in self._feet_samples(x, y):
            if self._is_blocked_at(cx, cy):
                return True

        return False

    # Collision box geometry: a 2x2-tile box centred on (x+1.5, y+2.0),
    # spanning x+0.5..x+2.5 and y+1.0..y+3.0. (Previously this was a narrower, off-centre "feet" box
    # (x+0.4..x+1.6, y+2.0..y+3.0) that put the horizontal centre at x+1.0
    # instead of x+1.5 — exactly the "lands 0.5 tiles left of doorways" bug.)
    # The box is half-open: its right/bottom edge sitting exactly on a tile
    # boundary does NOT occupy the next tile. Without the epsilon, an edge
    # flush against a wall (e.g. 35.0) floors into the wall tile and the
    # player stops a step (~4px) short. Inset the far edges so you can move
    # flush against walls.
    _FEET_EPS = 1e-3
    _FEET_LEFT, _FEET_RIGHT = PLAYER_COLLISION_LEFT, PLAYER_COLLISION_RIGHT
    _FEET_TOP, _FEET_BOTTOM = PLAYER_COLLISION_TOP, PLAYER_COLLISION_BOTTOM

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
        for cx in (x + self._FEET_LEFT, x + PLAYER_BODY_CENTER_X,
                   x + self._FEET_RIGHT - self._FEET_EPS):
            for cy in (y + self._FEET_TOP, y + PLAYER_BODY_CENTER_Y,
                       y + self._FEET_BOTTOM - self._FEET_EPS):
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
            max_x, max_y = gmap_extent(self.client.gmap_width,
                                       self.client.gmap_height)
        else:
            max_x = max_y = LEVEL_SIZE
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
            max_x, max_y = gmap_extent(self.client.gmap_width,
                                       self.client.gmap_height)
            if x < 0 or x >= max_x or y < 0 or y >= max_y:
                return True
        else:
            if not in_level_bounds(x, y):
                return True

        if self._chest_blocks(x, y):
            return True

        # NPC footprints: the reference wall test asks the level's NPCs
        # before the board (TServerLevel::isOnWall -> TServerNPC::isOnNPC),
        # so a visible image NPC blocks with its image footprint until
        # dontblock, a character NPC with its 2x2 feet box, and setshape
        # cells with their published geometry. The full oracle-derived rule
        # (visibility, dontblock/blockagain, setimgpart, pixel-transparency
        # refinement) lives in gs1_client.ClientGS1.npc_blocks_at.
        gs1 = getattr(self, 'gs1', None)
        if gs1 is not None:
            try:
                if gs1.npc_blocks_at(x, y):
                    return True
            except Exception:
                pass

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
        """Check if the standing point is in deep, swimmable water."""
        tile_id = self._get_tile_at(x, y)
        return self._is_tile_swimming_water(tile_id)

    def _corner_assist_offset(self, dx: int, dy: int) -> Optional[Tuple[int, int]]:
        """Classic-engine "corner assist": for a blocked pure-cardinal press
        (dx, dy) — exactly one of the two nonzero, e.g. walking straight up
        into a doorway — find a small perpendicular nudge that would let it
        through, so walking slightly off-center through an opening slides
        you flush with it instead of stopping dead.

        Returns a one-MOVE_STEP nudge direction (ddx, ddy), each in
        {-1, 0, 1} with exactly one nonzero, to move THIS call instead of
        (dx, dy); the caller re-evaluates every subsequent frame, so a wider
        gap gets closed one step at a time until the plain cardinal move
        succeeds on its own. Returns None if no nudge within
        CORNER_ASSIST_MAX would help.

        Diagonal presses (both dx and dy nonzero) already have their own
        axis-slide in _move and don't use this. A flat wall — blocked at
        every offset within range — and a solid corner — where nudging
        doesn't unblock the destination — both correctly return None here,
        so the player stays blocked exactly like an unassisted flat wall.
        """
        if (dx != 0) == (dy != 0):
            return None  # both zero (no input) or both nonzero (diagonal)

        x, y = self.client.x, self.client.y
        step = MOVE_STEP
        max_k = max(1, round(CORNER_ASSIST_MAX / step))

        for k in range(1, max_k + 1):
            for sign in (1, -1):
                if dx != 0:
                    nudge_ddx, nudge_ddy = 0, sign
                else:
                    nudge_ddx, nudge_ddy = sign, 0

                # Every intermediate nudge position up to k steps must itself
                # be walkable — a destination that only clears at k=2 is no
                # good if the k=1 step we'd actually take this call walks
                # into a different wall.
                path_clear = True
                for j in range(1, k + 1):
                    px = x + nudge_ddx * step * j
                    py = y + nudge_ddy * step * j
                    if (self._position_out_of_bounds(px, py)
                            or self._is_position_blocked(px, py)):
                        path_clear = False
                        break
                if not path_clear:
                    continue

                # From the k-step nudge, does the ORIGINAL cardinal move clear?
                dest_x = x + nudge_ddx * step * k + dx * step
                dest_y = y + nudge_ddy * step * k + dy * step
                if self._position_out_of_bounds(dest_x, dest_y):
                    continue
                if self._is_position_blocked(dest_x, dest_y, dx, dy):
                    continue

                return (nudge_ddx, nudge_ddy)
        return None
