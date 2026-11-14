"""Client MovementMixin methods."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Optional

from reborn_protocol import PLPROP
from reborn_protocol.coords import segment_at, segment_origin, world_to_local
from reborn_protocol.props import PLAYER_PROPS, payload_len

from .gmap_coords import get_ci, grid_of, has_level, same_level
from .packets import PacketID, build_movement

#: Asset and file requests do not depend on where we stand, so they do not
#: send a tick's held position first (see movement_batch): a gani or sound
#: fetched mid-walk must not split the tick's one position packet in two.
#: Every other packet keeps its call order relative to our position.
_ORDER_FREE_PACKETS = frozenset(int(p) for p in (
    PacketID.PLI_WANTFILE, PacketID.PLI_UPDATEFILE, PacketID.PLI_VERIFYWANTSEND,
    PacketID.PLI_UPDATEGANI, PacketID.PLI_UPDATESCRIPT, PacketID.PLI_UPDATECLASS,
    PacketID.PLI_UPDATEPACKAGEREQUESTFILE, PacketID.PLI_REQUESTTEXT))


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
        if self.tick_movement_ended:
            return False

        from .attachments import sends_attachment, stored_position, sync_attachment
        sync_attachment(self, self.player)

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
        home_grid = None
        if self.is_gmap:
            # Calculate which grid cell the new position is in
            new_grid = segment_at(new_x, new_y)

            # If we're changing grid cells, we need to notify the server.
            # Compare against the segment the server homes us in (our level),
            # not the one our position falls in: a server-set local just past
            # the edge (70.25) puts us beyond our own segment without moving
            # us to the next one.
            home_grid = grid_of(self.gmap_grid, self._current_level_name)
            old_grid = home_grid
            if old_grid is None:
                old_grid = segment_at(self.player.x, self.player.y)
            if new_grid != old_grid:
                # Look up the new level name from the GMAP grid
                new_level = self.gmap_grid.get(new_grid)
                if new_level:
                    new_level_name = new_level
                    crossing_boundary = True

        # Build and send movement packet
        # Attached axes are NPC-relative; other axes are level-local.
        if sends_attachment(self):
            local_x, local_y = stored_position(self, new_x, new_y)
        elif home_grid is not None:
            # Local to the segment the server still homes us in, unwrapped,
            # like the reference client's getlocalx() (world - (mapX << 6)).
            # A step that crosses a seam INTO another segment of the loaded
            # gmap is not sent this way: it goes out below as a map hop in the
            # new segment's own frame. A step off the grid's edge keeps the
            # unwrapped form (64.0 or -0.5 on the old segment).
            origin_x, origin_y = segment_origin(*home_grid)
            local_x, local_y = new_x - origin_x, new_y - origin_y
        else:
            local_x, local_y = world_to_local(new_x, new_y)
        # v2.30+/v6 clients report position via the high-precision X2/Y2
        # props (78/79); classic servers only understand X/Y (15/16).
        data = build_movement(local_x, local_y, direction,
                              use_new_format=self._use_pixel_props)
        hop = (crossing_boundary and new_level_name
               and not sends_attachment(self)
               and self._is_gmap_hop(self._current_level_name, new_level_name))
        if hop:
            sent = self._send_gmap_hop(self._current_level_name,
                                       new_level_name,
                                       *world_to_local(new_x, new_y),
                                       direction)
        else:
            sent = self._send_position_props(data)
        if sent:
            # Update local state
            self.player.x = new_x
            self.player.y = new_y
            self.player.direction = direction
            self._note_position_sent()

            # Crossing into another segment of the gmap: the hop props above
            # told the server; follow it locally.
            if hop:
                self._arrive_in_gmap_segment(new_level_name)
            # Crossing out of the grid's known cells: a level warp re-homes us.
            elif crossing_boundary and new_level_name:
                self.enter_gmap_segment(new_level_name, *world_to_local(new_x, new_y))

            return True

        return False

    # -- gmap hops ----------------------------------------------------------
    #
    # The reference client sends no warp when it walks into a neighbouring
    # level of the gmap it has loaded: it tests the target against the map's
    # level-name list (TClient.cpp:1354-1358, the list is built from the .gmap
    # file, TServerLevel.cpp:2112-2132), enters the level locally, and its
    # next property packet carries the changed GMAPLEVELX / GMAPLEVELY
    # (TPlayer.cpp:7794-7811) plus the position in the new level's frame, all
    # in ascending prop id order (TPlayer.cpp:2462-2468). The server learns
    # the hop from those props (GServer-v2 PlayerProps.cpp:906-973).

    def _is_gmap_hop(self, from_level: str, to_level: str) -> bool:
        """True when both levels are cells of the loaded gmap, differ, and we
        hold the target's board. The reference falls back to a plain warp
        when the target is not held locally (no loaded level and no cached
        file with a mod time, TClient.cpp:1323-1347), because a hop sends no
        level data back; the same test applies to a walked seam and to a
        door or script."""
        return (not same_level(from_level, to_level)
                and has_level(self.levels, to_level)
                and grid_of(self.gmap_grid, from_level) is not None
                and grid_of(self.gmap_grid, to_level) is not None)

    def _send_gmap_hop(self, from_level: str, to_level: str, local_x: float,
                       local_y: float, direction: int) -> bool:
        """Send the props of a hop from `from_level` into `to_level`: the
        position in `to_level`'s frame and the GMAPLEVELX/Y that changed.

        The cell comes from the level NAME, first grid match (`grid_of`), not
        from the position: the reference sends setMapX(serverLevel->mapX)
        (TPlayer.cpp:465-490, 7794-7811) and a level's mapX is its first match
        in the map's name list (TServerLevel::updateMapPos, TServerLevel.cpp:
        930-960, TStringList indexOf). A gmap that lists one name in two cells
        therefore always reports the first."""
        old = grid_of(self.gmap_grid, from_level)
        new = grid_of(self.gmap_grid, to_level)
        data = build_movement(local_x, local_y, direction,
                              use_new_format=self._use_pixel_props)
        props = {}
        pos = 0
        while pos < len(data):
            pid = data[pos] - 32
            end = pos + 1 + payload_len(PLAYER_PROPS[pid], data, pos + 1)
            props[pid] = data[pos + 1:end]
            pos = end
        if new[0] != old[0]:
            props[int(PLPROP.GMAPLEVELX)] = bytes([new[0] + 32])
        if new[1] != old[1]:
            props[int(PLPROP.GMAPLEVELY)] = bytes([new[1] + 32])
        return self._send_position_props(b''.join(
            bytes([pid + 32]) + props[pid] for pid in sorted(props)))

    def _arrive_in_gmap_segment(self, level_name: str) -> None:
        """Local state after walking into segment `level_name`: no level
        reset, no roster drop, no warp echo to expect (none was sent)."""
        self._current_level_name = level_name
        # Point the ACTIVE board at the segment we just walked into. The
        # neighbour's board is already in self.levels (preloaded by
        # request_adjacent_levels on an earlier crossing), and gs2emu will not
        # re-stream it - its per-session level cache only sends a board the
        # first time - so nothing else ever updates _tiles_level_name for a
        # re-crossing. Live-traced on hastur 2026-07-25: walking e6 -> d6 left
        # the active board naming e6 for the remaining 2.4 s of the session.
        cached_board = get_ci(self.levels, level_name)
        if cached_board:
            self.tiles = cached_board
            self._tiles_level_name = level_name
        self.request_adjacent_levels()

    def enter_gmap_segment(self, level_name: str, local_x: float,
                           local_y: float) -> bool:
        """Tell the server we walked into gmap segment `level_name`.

        A seam crossing is NOT a warp: no level-state reset, no roster drop.
        Inside the loaded gmap it sends only our props (see _send_gmap_hop),
        like the reference client, and no warp. From outside the grid's known
        cells (the current level is no cell, or `level_name` is not one) it
        is the PLI_LEVELWARP that re-homes us. Either way the newly-adjacent
        segments are requested. Factored out of move() so scripted movement
        (which never calls move_to. See
        ActionsMixin._check_scripted_gmap_segment) announces crossings the
        exact same way."""
        if not self.connected or not self._authenticated:
            return False
        if self._is_gmap_hop(self._current_level_name, level_name):
            if not self._send_gmap_hop(self._current_level_name, level_name,
                                       local_x, local_y,
                                       self.player.direction):
                return False
            self._note_position_sent()
            self._arrive_in_gmap_segment(level_name)
            return True
        if not self._send_level_warp(local_x, local_y, level_name,
                                     same_map=True):
            return False
        self._arrive_in_gmap_segment(level_name)
        self.note_client_warp(level_name)
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
        if self.tick_movement_ended:
            return False
        from .attachments import sends_attachment, stored_position, sync_attachment
        sync_attachment(self, self.player)
        local_x, local_y = (stored_position(self, self.player.x, self.player.y)
                            if sends_attachment(self)
                            else world_to_local(self.player.x, self.player.y))
        data = build_movement(local_x, local_y, self.player.direction,
                              use_new_format=self._use_pixel_props)
        if not self._send_position_props(data):
            return False
        self._note_position_sent()
        return True

    # -- one movement packet per tick ----------------------------------------
    #
    # The reference sends its outgoing player props once per timer call
    # (TAdventure.cpp:496 sendOutgoing). move() and send_position() decide
    # what goes on the wire when they are called (coordinate frame, seam
    # crossing and its PLI_LEVELWARP, attachment), exactly as without a tick;
    # inside movement_batch() the finished props are held instead of sent,
    # and a later position in the same tick replaces the held values prop by
    # prop. The held props go out before any other packet (so the wire order
    # is the call order) and when the batch ends. Nothing is re-read from the
    # player at that point. A warp (warp_to_level) ends the tick's movement:
    # move() and send_position() do nothing more until the batch ends.

    @contextmanager
    def movement_batch(self) -> Iterator[None]:
        """Hold this block's position packets and send them as one. Re-entrant."""
        if self.__dict__.get('_movement_hold') is not None:
            yield
            return
        proto = self._protocol
        had_own = 'send_packet' in vars(proto)
        original = proto.send_packet
        hold = {'props': {}, 'warped': False}

        def flush() -> None:
            props, hold['props'] = hold['props'], {}
            if props:
                original(PacketID.PLI_PLAYERPROPS, b''.join(
                    bytes([pid + 32]) + props[pid] for pid in sorted(props)))

        def send_packet(packet_id, *args, **kwargs):
            if int(packet_id) not in _ORDER_FREE_PACKETS:
                flush()
            return original(packet_id, *args, **kwargs)

        self._movement_hold = hold
        proto.send_packet = send_packet
        try:
            yield
        finally:
            self._movement_hold = None
            if had_own:
                proto.send_packet = original
            else:
                try:
                    del proto.send_packet
                except AttributeError:
                    pass
            flush()

    def _send_position_props(self, data: bytes) -> bool:
        """Send a finished position PLI_PLAYERPROPS, or hold it for the
        tick's one packet (merged with what the tick already holds)."""
        hold = self.__dict__.get('_movement_hold')
        if hold is None:
            return self._protocol.send_packet(PacketID.PLI_PLAYERPROPS, data)
        held = hold['props']
        pos = 0
        while pos < len(data):
            pid = data[pos] - 32
            end = pos + 1 + payload_len(PLAYER_PROPS[pid], data, pos + 1)
            held[pid] = data[pos + 1:end]
            pos = end
        return True

    @property
    def tick_movement_ended(self) -> bool:
        """True after a warp inside the current tick (see movement_batch)."""
        hold = self.__dict__.get('_movement_hold')
        return hold is not None and hold['warped']

    def end_tick_movement(self) -> None:
        """A warp happened: no more walking or position packets this tick."""
        hold = self.__dict__.get('_movement_hold')
        if hold is not None:
            hold['warped'] = True

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
