"""Client GmapMixin methods."""

from __future__ import annotations

import logging
from typing import Callable, List, Optional, Tuple

from reborn_protocol.coords import local_to_world, segment_at, segment_origin

from .gmap_coords import (
    fold, grid_of, has_level, in_grid, position_is_local, same_level,
    world_from_wire,
)
from .npc_handler import is_map_name, npc_cell, npc_in_range, place_npc

logger = logging.getLogger(__name__)



class GmapMixin:
    def own_level_name(self) -> str:
        """The level the player stands in, never a ``.gmap`` name.

        On a loaded gmap that is the segment under the player. With no grid
        loaded, or with the player still at the unplaced origin (0, 0) of a
        loaded grid, the position says nothing, so it is the last segment
        PLO_LEVELNAME named (`level_scope_segment`, the entry segment).
        """
        name = self.get_current_level_from_position()
        segment = self._level_scope_segment
        if (segment and self.gmap_grid and self.player.x == 0
                and self.player.y == 0 and in_grid(self.gmap_grid, segment)):
            return segment
        if is_map_name(name):
            return segment or ""
        return name

    def player_map_cell(self) -> Optional[Tuple[int, int]]:
        """The grid cell of the segment the player's level is, the
        reference's `activeplayer->mapX/mapY` (TPlayer.cpp:476-479). None
        with no grid, or while the player is in a level that is no cell."""
        return grid_of(self.gmap_grid, self._current_level_name)

    def npc_range_filter(self) -> Callable[[dict], bool]:
        """A predicate ``visible(npc)``: the NPC is inside the 3x3 the
        reference keeps visible (see `npc_in_range`). The player's cell is
        read once, so a pass over every NPC costs one grid scan. A cached
        NPC that left range is kept; it passes again when the player
        walks back, with no new packet."""
        grid = self.gmap_grid
        cell = self.player_map_cell()
        return lambda npc: npc_in_range(grid, cell, npc)

    def _level_scope_name(self) -> str:
        """The level that level-scoped packets (items, chests, signs, links,
        horses, baddies, boards, board changes) are filed under.

        The reference client keeps two level targets: PLO_LEVELNAME sets the
        level scope and PLO_SETACTIVELEVEL sets only the NPC owner
        (TClient.cpp:3224-3241 and :3777-3784). A ``.gmap`` level scope is the
        player's own level, so it resolves to the segment under the player
        (`own_level_name`). It never returns a map name.
        """
        name = self._level_scope
        if not name or is_map_name(name):
            return self.own_level_name()
        return name

    def _scope_is_own_level(self) -> bool:
        """Whether the level scope is the player's own level. The reference
        drops items and explosions otherwise (TClient.cpp:3595, :3665, :3719).
        A scope or player level that is not known yet does not drop."""
        scope = self._level_scope_name()
        own = self.own_level_name()
        return not scope or not own or same_level(scope, own)

    def _exit_gmap(self, level_name: str):
        """Leave gmap mode and become a standalone level.

        Called when the player warps from a gmap world into a level that is not
        one of its segments (e.g. an interior). Clears the grid so is_gmap is
        False and positions are treated as plain local coordinates again.
        """
        self.gmap_grid.clear()
        self.gmap_width = 0
        self.gmap_height = 0
        # Which world we just stepped out of. Unlike gmap_name this survives
        # the exit, so warping back to one of its segments can rebuild the
        # grid from the already-downloaded file (see restore_known_gmap).
        if self.gmap_name:
            self._last_gmap_name = self.gmap_name
        self.gmap_name = ""
        self._requested_gmap = ""
        self._gmap_spawn_x = 0
        self._gmap_spawn_y = 0
        self.player.level = level_name
        self._current_level_name = level_name
        self._level_scope = level_name
        self._level_scope_segment = level_name
        self._npc_level = level_name

    def restore_known_gmap(self, spawn_level: str) -> bool:
        """Rebuild the world grid for a segment we are warping back into.

        If the player walks out of an interior, `_exit_gmap` drops the grid.
        If the player walks back in, the client stays in the local frame until
        the server re-announces the .gmap and the file download completes.
        The transition hold correctly refuses to release into that interim
        frame (see `_maybe_release_local_transition`), so the screen stays
        frozen for the whole round trip - measured at 240 ms on hastur for a
        door we had already used. The .gmap file is unchanged and already in
        `_received_files`, so rebuild from it now instead.

        Returns True if the grid was restored.
        """
        if self.gmap_width or fold(spawn_level) not in self._known_gmap_segments:
            return False
        blob = self._received_files.get(self._last_gmap_name)
        if not blob:
            return False
        try:
            self.load_gmap(blob.decode('latin-1', errors='replace'),
                           spawn_level=spawn_level)
        except Exception:
            logger.warning("cached %s failed to parse on gmap re-entry",
                           self._last_gmap_name)
            return False
        self.gmap_name = self._last_gmap_name
        self._requested_gmap = self._last_gmap_name
        return bool(self.gmap_width)

    def load_gmap(self, gmap_data: str, spawn_level: str = ""):
        """
        Parse GMAP data to build the level grid.

        Args:
            gmap_data: Contents of .gmap file
            spawn_level: Segment the player is entering, when the caller knows
                it. Normally the grid cell comes from the PLO_PLAYERWARP2 that
                precedes the download. A client-driven re-entry
                (`restore_known_gmap`) has no such packet and names the
                destination directly instead.
        """
        self.gmap_grid.clear()
        lines = gmap_data.strip().split('\n')

        in_levelnames = False
        level_names = []

        for line in lines:
            line = line.strip()
            if line.startswith('WIDTH'):
                self.gmap_width = int(line.split()[1])
            elif line.startswith('HEIGHT'):
                self.gmap_height = int(line.split()[1])
            elif line == 'LEVELNAMES':
                in_levelnames = True
            elif line == 'LEVELNAMESEND':
                in_levelnames = False
            elif in_levelnames:
                # Parse level names from CSV format
                parts = line.replace('"', '').rstrip(',').split(',')
                for name in parts:
                    name = name.strip()
                    if name:
                        level_names.append(name)

        # Build grid mapping
        for i, name in enumerate(level_names):
            x = i % self.gmap_width
            y = i // self.gmap_width
            self.gmap_grid[(x, y)] = name
        # Remember segment membership across _exit_gmap (see __init__).
        self._known_gmap_segments.update(fold(name) for name in level_names)


        # With GMAP-relative coordinates, there's no offset needed
        # player.x and player.y are directly in GMAP tile coordinates
        # grid position = segment_at(player.x, player.y)
        self._gmap_offset_x = 0
        self._gmap_offset_y = 0

        # Set current level based on spawn grid position from PLO_PLAYERWARP2
        # (which is received before GMAP file, so we can't use gmap_grid at that time)
        # If we have a spawn grid position, use it; otherwise fall back to calculating from coords
        spawn_pos = grid_of(self.gmap_grid, spawn_level)
        if spawn_pos is not None:
            pass
        elif self._gmap_spawn_x != 0 or self._gmap_spawn_y != 0:
            spawn_pos = (self._gmap_spawn_x, self._gmap_spawn_y)
        else:
            spawn_pos = segment_at(self.player.x, self.player.y)

        if spawn_pos in self.gmap_grid:
            self._current_level_name = self.gmap_grid[spawn_pos]

            # Convert player coords to world coords if they're still local
            # (PLAYERWARP2 arrives before GMAP, so coords are local at that point)
            if position_is_local(self.player.x, self.player.y):
                self.player.x, self.player.y = local_to_world(
                    self.player.x, self.player.y, *spawn_pos)

        # Re-entering a gmap from an interior level: the warp-time restore in
        # warp_to_level/_handle_packet only saw the target segment (the grid
        # was cleared by _exit_gmap), so now that the grid is rebuilt, pull
        # the sibling segments' cached NPCs back in too - gs2emu's session
        # cache won't re-stream any of them.
        self._restore_cached_npcs(self._current_level_name)

        # Update existing NPC coords to world coords now that we have the GMAP grid
        self._update_npc_world_coords()

        # A transition held across a gmap re-entry (interior -> segment) was
        # waiting for exactly this: the grid is rebuilt and coordinates are
        # world again, so the destination view is finally presentable.
        self._maybe_release_local_transition()

    def _update_npc_world_coords(self):
        """Place every NPC again once load_gmap has built the grid.

        NPCs can arrive before the .gmap file does; they then hold their
        local position as world. Each NPC's cell is its stored cell (props
        41/42, or the cell of the segment that owned it), else the cell of
        the segment its level names, which it now also stores: the
        reference client stamps a segment's cell on that segment's NPCs
        when it learns the segment is part of a map
        (FourPlay quattroplay/src/TServerLevel.cpp:945-953). World is
        recomputed from the local x/y, so a second run changes nothing."""
        for npc in self.npcs.values():
            cell = npc_cell(self.gmap_grid, npc)
            if cell is None:
                continue  # a plain level: its local frame is the world
            npc['gmaplevelx'], npc['gmaplevely'] = cell
            segment = self.gmap_grid.get(cell)
            if segment is not None:
                npc['_level'] = segment
            place_npc(self.gmap_grid, npc)
            # Re-attribution, not movement: the NPC did not walk, we just
            # learned its world position. Snap the renderer's visual
            # position (see _mark_npc_pos_snap) instead of letting it lerp
            # across the jump from the interim local-as-world guess.
            self._mark_npc_pos_snap(npc)

    def get_adjacent_levels(self, level_name: str) -> List[str]:
        """
        Get names of levels adjacent to the given level.

        Args:
            level_name: Current level name

        Returns:
            List of adjacent level names
        """
        current_pos = grid_of(self.gmap_grid, level_name)
        if current_pos is None:
            return []

        # Get all 8 adjacent positions
        x, y = current_pos
        adjacent = []
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                if dx == 0 and dy == 0:
                    continue
                adj_pos = (x + dx, y + dy)
                if adj_pos in self.gmap_grid:
                    adjacent.append(self.gmap_grid[adj_pos])

        return adjacent

    def request_adjacent_levels(self) -> int:
        """
        Request all adjacent levels based on current position.

        Returns:
            Number of levels requested
        """
        if not self._current_level_name:
            return 0

        adjacent = self.get_adjacent_levels(self._current_level_name)
        count = 0
        for level_name in adjacent:
            if (not has_level(self.levels, level_name)
                    and level_name not in self._adjacent_level_requests):
                self.request_level(level_name)
                count += 1

        return count
