"""Client MovementMixin methods."""

from __future__ import annotations

from typing import Optional

from reborn_protocol.coords import segment_at, world_to_local

from .packets import PacketID, build_level_warp, build_movement



class MovementMixin:
    # =========================================================================
    # Actions
    # =========================================================================

    def move(self, dx: int, dy: int, step: float = 0.25,
             face_direction: Optional[int] = None) -> bool:
        """
        Move the player.

        Args:
            dx: X direction (-1=left, 0=none, 1=right)
            dy: Y direction (-1=up, 0=none, 1=down)
            step: Movement step size in tiles (default 0.5 for half-tile precision)
            face_direction: Override the facing direction sent/stored instead
                of the one inferred from (dx, dy). Used by the pygame
                client's corner-assist (game/actions.py's _move): a
                perpendicular nudge around a doorway/corner moves the
                player sideways for a frame, but they should keep facing
                whichever cardinal direction was actually pressed, not
                whichever way the assist nudged them.

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        # Server froze us (PLO_FREEZEPLAYER2): movement is a no-op until
        # PLO_UNFREEZEPLAYER, matching real client behavior.
        if self.frozen:
            return False

        # Calculate new position using step size
        new_x = self.player.x + dx * step
        new_y = self.player.y + dy * step

        # Determine direction
        if face_direction is not None:
            direction = face_direction
        elif dx > 0:
            direction = 3  # right
        elif dx < 0:
            direction = 1  # left
        elif dy > 0:
            direction = 2  # down
        elif dy < 0:
            direction = 0  # up
        else:
            direction = self.player.direction

        # Check if we're crossing into a different GMAP level BEFORE sending packet
        crossing_boundary = False
        new_level_name = None
        if self.is_gmap:
            # Calculate which grid cell the new position is in
            new_grid = segment_at(new_x, new_y)

            # If we're changing grid cells, we need to notify the server
            if new_grid != segment_at(self.player.x, self.player.y):
                # Look up the new level name from the GMAP grid
                new_level = self.gmap_grid.get(new_grid)
                if new_level:
                    new_level_name = new_level
                    crossing_boundary = True

        # Build and send movement packet
        # Always send LOCAL coordinates (0-63) - server tracks level separately
        local_x, local_y = world_to_local(new_x, new_y)
        # v2.30+/v6 clients report position via the high-precision X2/Y2
        # props (78/79); classic servers only understand X/Y (15/16).
        data = build_movement(local_x, local_y, direction,
                              use_new_format=self._use_pixel_props)
        if self._protocol.send_packet(PacketID.PLI_PLAYERPROPS, data):
            # Update local state
            self.player.x = new_x
            self.player.y = new_y
            self.player.direction = direction
            self._note_position_sent()

            # If crossing GMAP boundary, send a level warp to notify server
            if crossing_boundary and new_level_name:
                self.enter_gmap_segment(new_level_name, local_x, local_y)

            return True

        return False

    def enter_gmap_segment(self, level_name: str, local_x: float,
                           local_y: float) -> bool:
        """Tell the server we walked into gmap segment `level_name`.

        A seam crossing is NOT a warp: no level-state reset, no roster drop —
        just PLI_LEVELWARP so the server re-homes us, plus a request for the
        newly-adjacent segments. Factored out of move_to() so scripted
        movement (which never calls move_to; see
        ActionsMixin._check_scripted_gmap_segment) announces crossings the
        exact same way."""
        if not self.connected or not self._authenticated:
            return False
        warp_data = build_level_warp(local_x, local_y, level_name)
        if not self._protocol.send_packet(PacketID.PLI_LEVELWARP, warp_data):
            return False
        self._current_level_name = level_name
        # Point the ACTIVE board at the segment we just walked into. The
        # neighbour's board is already in self.levels (preloaded by
        # request_adjacent_levels on an earlier crossing), and gs2emu will not
        # re-stream it - its per-session level cache only sends a board the
        # first time - so nothing else ever updates _tiles_level_name for a
        # re-crossing. Live-traced on hastur 2026-07-25: walking e6 -> d6 left
        # the active board naming e6 for the remaining 2.4 s of the session.
        cached_board = self.levels.get(level_name)
        if cached_board:
            self.tiles = cached_board
            self._tiles_level_name = level_name
        self.note_client_warp(level_name)
        self.request_adjacent_levels()
        return True

    def send_position(self) -> bool:
        """Re-broadcast the player's current position without moving.

        The server only tells other players our position when it changes, so a
        stationary player is invisible (position-wise) to anyone who joins after
        us. Calling this pushes our current X/Y so others can place us. Useful
        for tests and for an initial position announce after entering a level.
        """
        if not self.connected or not self._authenticated:
            return False
        local_x, local_y = world_to_local(self.player.x, self.player.y)
        data = build_movement(local_x, local_y, self.player.direction,
                              use_new_format=self._use_pixel_props)
        if not self._protocol.send_packet(PacketID.PLI_PLAYERPROPS, data):
            return False
        self._note_position_sent()
        return True

    # -- last-transmitted position -----------------------------------------
    #
    # Every path that puts our position on the wire records it here, so
    # script-driven movement can tell whether the server has actually been
    # told where we are (see gs2_client._sync_script_position). Rounded to
    # the wire's own precision would still leave a stale-by-a-hair snapshot
    # re-sending forever, so this is the exact value the sender used.
    def _note_position_sent(self) -> None:
        self._last_sent_position = (round(float(self.player.x), 4),
                                    round(float(self.player.y), 4),
                                    int(self.player.direction or 0))

    @property
    def position_matches_wire(self) -> bool:
        """True when player.x/y/direction are what we last told the server."""
        last = getattr(self, '_last_sent_position', None)
        return last == (round(float(self.player.x), 4),
                        round(float(self.player.y), 4),
                        int(self.player.direction or 0))
