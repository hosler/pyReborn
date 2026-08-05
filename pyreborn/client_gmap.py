"""Client GmapMixin methods."""

from __future__ import annotations

import logging
from typing import List

from reborn_protocol.coords import (
    LEVEL_SIZE, local_to_world, segment_at, segment_origin,
)

logger = logging.getLogger(__name__)



class GmapMixin:
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
        self._pending_level_name = level_name

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
        if self.gmap_width or spawn_level not in self._known_gmap_segments:
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
        self._known_gmap_segments.update(level_names)


        # With GMAP-relative coordinates, there's no offset needed
        # player.x and player.y are directly in GMAP tile coordinates
        # grid position = segment_at(player.x, player.y)
        self._gmap_offset_x = 0
        self._gmap_offset_y = 0

        # Set current level based on spawn grid position from PLO_PLAYERWARP2
        # (which is received before GMAP file, so we can't use gmap_grid at that time)
        # If we have a spawn grid position, use it; otherwise fall back to calculating from coords
        spawn_pos = None
        if spawn_level:
            for grid_pos, seg in self.gmap_grid.items():
                if seg == spawn_level:
                    spawn_pos = grid_pos
                    break
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
            if self.player.x < LEVEL_SIZE and self.player.y < LEVEL_SIZE:
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
        """Update NPC world coordinates based on their level's grid position.

        Runs after load_gmap builds the grid, fixing up NPCs that arrived
        BEFORE the .gmap file download finished. NPCs carrying GMAPLEVELX/
        GMAPLEVELY props (gs2emu gmap streams - see the PLO_NPCPROPS handler)
        are re-attributed from those. At stream time the grid was empty so
        they were stamped with the .gmap name and local-as-world coords."""
        for npc_id, npc in self.npcs.items():
            gx = npc.get('gmaplevelx')
            gy = npc.get('gmaplevely')
            if gx is not None and gy is not None and (gx, gy) in self.gmap_grid:
                npc['_level'] = self.gmap_grid[(gx, gy)]
                seg_ox, seg_oy = segment_origin(gx, gy)
                if 'x' in npc:
                    raw_x = npc['x']
                    npc['world_x'] = (raw_x if (raw_x >= LEVEL_SIZE or raw_x < 0)
                                       else raw_x + seg_ox)
                if 'y' in npc:
                    raw_y = npc['y']
                    npc['world_y'] = (raw_y if (raw_y >= LEVEL_SIZE or raw_y < 0)
                                       else raw_y + seg_oy)
                # Re-attribution, not movement: the NPC didn't actually walk,
                # we just learned its real world position now that the grid
                # is built. Snap the renderer's visual position (see
                # _mark_npc_pos_snap) instead of letting it lerp across the
                # jump from the interim local-as-world guess.
                self._mark_npc_pos_snap(npc)
                continue
            npc_level = npc.get('_level')
            if not npc_level:
                continue  # No level info
            # Find the level's grid position
            for (gx, gy), level_name in self.gmap_grid.items():
                if level_name == npc_level:
                    # Same guard as the PLO_NPCPROPS handler (BUG 4): only
                    # fold in the segment offset for a still-local value, so
                    # a re-run of this (e.g. gmap grid arriving/reloading
                    # after an NPC's coords were already normalized to
                    # world) can't double-offset it.
                    seg_ox, seg_oy = segment_origin(gx, gy)
                    if 'x' in npc:
                        raw_x = npc['x']
                        npc['world_x'] = (raw_x if (raw_x >= LEVEL_SIZE or raw_x < 0)
                                           else raw_x + seg_ox)
                    if 'y' in npc:
                        raw_y = npc['y']
                        npc['world_y'] = (raw_y if (raw_y >= LEVEL_SIZE or raw_y < 0)
                                           else raw_y + seg_oy)
                    # Re-attribution, not movement - see the snap comment on
                    # the gmaplevelx/y branch above.
                    self._mark_npc_pos_snap(npc)
                    break

    def get_adjacent_levels(self, level_name: str) -> List[str]:
        """
        Get names of levels adjacent to the given level.

        Args:
            level_name: Current level name

        Returns:
            List of adjacent level names
        """
        # Find current level's grid position
        current_pos = None
        for pos, name in self.gmap_grid.items():
            if name == level_name:
                current_pos = pos
                break

        if not current_pos:
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
            if (level_name not in self.levels
                    and level_name not in self._adjacent_level_requests):
                self.request_level(level_name)
                count += 1

        return count
