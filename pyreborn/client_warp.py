"""Client WarpMixin methods."""

from __future__ import annotations

import logging
import math
import re
import time
from typing import Optional, Tuple

from reborn_protocol.coords import (
    local_to_world, world_to_local,
)

from .packets import PacketID, build_level_warp

logger = logging.getLogger(__name__)

# LEVELWARP encodes coords as gchar half-tiles: byte = int(coord*2)+32, which
# must stay in [0, 255]. That bounds the warp target to [-16, 111.5] tiles.
WARP_COORD_MIN = -16.0
WARP_COORD_MAX = 111.5


def _eval_warp_coord(expr, player_x: float, player_y: float) -> Optional[float]:
    """Resolve a level-link destination coordinate.

    It is a plain number for most doors, but edge links use Reborn expressions
    that reference the player's current coordinate so a crossing is seamless:
    "playerx", "playery", "playery-4", "playerx+0.5", etc. Returns the resolved
    float, or None if it cannot be parsed.
    """
    s = str(expr).strip().lower()
    # Server-controlled input (level link destination) — cap length and reject
    # '**' (power operator) before it ever reaches eval. Without this, a link
    # like "9**9**9**9" builds a tower-of-exponents that hangs the client (DoS).
    if len(s) > 64 or '**' in s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    s = s.replace('playerx', repr(float(player_x))).replace('playery', repr(float(player_y)))
    if len(s) > 64 or '**' in s:
        return None
    # Only allow arithmetic over the substituted numbers — no names/calls.
    if re.fullmatch(r'[-+*/0-9.eE() ]+', s):
        try:
            return float(eval(s, {'__builtins__': {}}, {}))
        except Exception:
            return None
    return None


class WarpMixin:
    def warp_to_level(self, level_name: str, x: float = 30.0,
                      y: float = 30.0,
                      transition_direction: Optional[int] = None) -> bool:
        """
        Warp to a different level.

        Args:
            level_name: Name of the level to warp to (e.g., "level.nw")
            x: Destination X position in tiles (default 30.0 = center)
            y: Destination Y position in tiles (default 30.0 = center)

        Returns:
            True if packet sent successfully
        """
        if not self.connected or not self._authenticated:
            return False

        # Guard BEFORE mutating any state: everything below (level reset, roster
        # clear, tile-cache swap) is irreversible, and build_level_warp encodes
        # x/y as gchar half-tiles (byte = int(coord*2)+32). A missing level name
        # or an off-map coordinate makes that build throw, leaving the client
        # desynced at a phantom level/position it can't recover from. Reject up
        # front instead — same graceful path a bogus level name already takes.
        if not level_name:
            logger.warning("warp_to_level: empty level name ignored")
            return False
        if not (WARP_COORD_MIN <= x <= WARP_COORD_MAX
                and WARP_COORD_MIN <= y <= WARP_COORD_MAX):
            logger.warning(
                "warp_to_level: (%s, %s) outside encodable range "
                "[%s, %s]; ignored", x, y, WARP_COORD_MIN, WARP_COORD_MAX)
            return False

        # Snapshot the authoritative pre-warp state BEFORE the optimistic
        # flip below, so a PLO_WARPFAILED rejection can restore it.
        pre_warp_state = (self._current_level_name, self.player.x, self.player.y)
        self._local_level_transition_direction = None

        # Update local state
        if level_name != self._current_level_name:
            self._reset_level_state()
        elif self.gs2_host is not None:
            self.gs2_host.begin_level_visit()
        # Warping back out of an interior into a segment of a world we already
        # downloaded: rebuild the grid now, so the coordinate conversion below
        # lands in the world frame and the renderer never has to sit frozen
        # waiting for the server to re-announce the .gmap.
        self.restore_known_gmap(level_name)
        # On a gmap, store WORLD coords (grid*64 + local) for the target segment
        # so position stays consistent with the world-coordinate model. A fresh
        # gmap entry (grid not loaded yet) relies on the server's PLAYERPROPS to
        # supply world coords; a re-warp between already-loaded segments does not
        # get those, so convert here. Non-segment targets keep their local coords.
        self.player.x = x
        self.player.y = y
        if self.gmap_width > 0:
            for (gx, gy), seg in self.gmap_grid.items():
                if seg == level_name:
                    self.player.x, self.player.y = local_to_world(x, y, gx, gy)
                    break
        # Leaving a standalone (non-GMAP) level: drop the other players from it.
        # The server streams the new level's players fresh; without this, players
        # from old levels linger and inflate playerscount (e.g. the Bomber arena
        # host then thinks the room is full and never settles to host it). GMAP
        # segment hops keep the roster (you see players across the whole gmap).
        if (level_name != self._current_level_name
                and level_name not in self.gmap_grid.values()):
            self.players.clear()

        self._current_level_name = level_name
        self._pending_level_name = level_name
        # Keep player.level (the source of client.level and GS1 #L) in step
        # with the optimistic flip: it is otherwise only assigned on
        # PLO_PLAYERWARP, which a client-initiated warp may not receive before
        # level scripts re-run — weapon playerenters then read the OLD level
        # via #L (the Bomber arena weapon re-armed its "Joining..." curtain in
        # the lobby that way). Gmap convention keeps player.level = .gmap name,
        # so segment hops don't touch it.
        if level_name not in self.gmap_grid.values():
            self.player.level = level_name

        # If we've visited this level before, repopulate its board from cache
        # immediately so the renderer doesn't draw the OLD level's tiles under
        # the player while the server re-streams the board (the "warped before
        # the new tiles render" glitch). First-visit levels stay flagged stale
        # (tiles_level_name != current) so the client can show a loading state.
        if level_name in self.levels:
            self.tiles = self.levels[level_name]
            self._tiles_level_name = level_name

        # Restore any NPCs we cached for this level (and, for a gmap segment,
        # its sibling segments) on a previous visit. If the server re-streams
        # them, the fresh PLO_NPCPROPS just overwrites these.
        self._restore_cached_npcs(level_name)

        # Mark the warp as awaiting the server's authoritative confirmation.
        # We flipped _current_level_name above optimistically (for instant
        # tile/board display), but that also makes incoming NPC/chest props
        # get stamped with the new level — so old-level props still in transit
        # from before the server processed this warp would be mis-attributed
        # to the new level. On the confirming PLO_LEVELNAME we re-reset to
        # purge them (TCP order guarantees they arrive before it).
        if level_name not in self.gmap_grid.values():
            self._awaiting_warp_confirm = level_name
            self._warp_fallback = pre_warp_state
            if level_name != pre_warp_state[0]:
                self._local_level_transition = level_name
                self._local_level_transition_started = time.monotonic()
                if self.player.hearts > 0 and transition_direction in range(4):
                    self._local_level_transition_direction = transition_direction

        # The LEVELWARP packet carries LOCAL coords within the target segment.
        data = build_level_warp(x, y, level_name)
        sent = self._protocol.send_packet(PacketID.PLI_LEVELWARP, data)
        if not sent:
            self._restore_failed_warp("send_failed")
            return False
        self.note_client_warp(level_name)
        # Everything the renderer needs may already be in hand: a destination
        # we've visited this session had its board re-pointed synchronously
        # above. Offer the release now instead of waiting for the server's
        # announcement to call it - _maybe_release_local_transition's own
        # guards (active board, gmap frame) make this a no-op for a
        # first-visit level, and on a re-entry they turn a full round trip of
        # frozen frames (measured 180 ms on hastur, worse on a slow link) into
        # an immediate cut to a view we could already draw.
        self._maybe_release_local_transition()
        return True

    def _release_local_transition(self) -> None:
        """Unconditionally end a held local level transition (rollback,
        renderer fail-open timeout). Bumps the epoch so the renderer snaps."""
        if self._local_level_transition:
            self._local_level_transition = ""
            self._local_level_transition_epoch += 1
        self._local_level_transition_direction = None

    def _maybe_release_local_transition(self) -> None:
        """End the held transition once the destination is genuinely
        presentable. Called from every packet handler that advances a warp
        (LEVELNAME confirm, BOARDPACKET, PLAYERWARP2, load_gmap).

        Two conditions, both learned from live traces (funtimes, house/gmap
        links):
        - The destination's board must be the ACTIVE render board.
        - If the destination is a segment of a gmap seen this session, the
          gmap frame must be re-established (grid reloaded and the segment
          current). Releasing on the bare board - the old behavior - landed
          the camera in the standalone LOCAL interim frame of a gmap
          re-entry (edge-clamped, wrong bounds), then the .gmap reload
          flipped coordinates to the world frame and the camera visibly
          jumped a second time."""
        lvl = self._local_level_transition
        if not lvl:
            return
        if self._current_level_name != lvl:
            return
        if self._tiles_level_name != lvl:
            return
        if lvl in self._known_gmap_segments and not self.in_gmap_segment:
            return
        self._local_level_transition = ""
        self._local_level_transition_epoch += 1

    def warp_names_pending_destination(self, level: str) -> bool:
        """Does a server warp packet naming `level` refer to the destination
        of the warp we are waiting on?

        A server-side warp INTO a gmap is announced by the world's name
        (`zlttp.gmap`), never by the destination segment's file name — so
        a plain `level != _awaiting_warp_confirm` test reads the confirmation
        of a legitimate warp as a rejection. Live-traced on hastur
        2026-07-25: walking out of `zlttp-linkshouse.nw` produced
        `PLO_PLAYERWARP2 (5, 6) "zlttp.gmap"` against a pending
        `zlttp-linkshouse.nw`->`zlttp-d6.nw` warp, and the bogus rollback
        killed the transition hold that exists precisely to stop the camera
        rendering a gmap re-entry in the interim standalone frame.
        """
        pending = self._awaiting_warp_confirm
        if not pending or not level:
            return False
        if level == pending:
            return True
        # `.gmap` names the world; it confirms any destination known to be one
        # of that world's segments. _known_gmap_segments (not gmap_grid) is the
        # right table: the grid is cleared while we're inside the interior.
        return level.endswith('.gmap') and pending in self._known_gmap_segments

    def note_client_warp(self, level_name: str) -> None:
        """Record a level change WE told the server about (a seam crossing via
        `enter_gmap_segment`, or a door/script warp via `warp_to_level`).

        Both send PLI_LEVELWARP, and the server answers one round trip later
        with a PLO_PLAYERWARP/PLAYERWARP2 whose coordinates are the ones we
        sent, re-quantised to half-tiles by `build_level_warp` on the way out.
        The packet therefore carries no position the client does not already
        have — but it arrives after the player has kept walking, so adopting
        it rewinds them by walk_speed x RTT. Measured on hastur (180 ms base
        RTT): 1.8 tiles / 29 px at a gmap seam (5.1 tiles on a slower sample)
        and 3.3 tiles / 53 px walking out of a door. See
        handlers/level.handle_player_warp2.
        """
        self._warp_echo = (level_name, time.monotonic())

    #: How long a recorded client warp stays eligible to absorb the server's
    #: echo. Comfortably above any playable round trip, far below the interval
    #: at which a stale entry could shadow a genuine server reposition into
    #: the same level.
    WARP_ECHO_MAX_AGE_S = 5.0

    def consume_warp_echo(self, level: str,
                          grid_pos: Optional[Tuple[int, int]] = None) -> bool:
        """True if a server warp packet is the echo of the level change we
        announced (see `note_client_warp`), and so should not move the player.

        Matches on any of the three names the server may use for the same
        destination: the level itself, the grid cell it occupies, or the
        world (`.gmap`) it belongs to. Consumes the record either way once a
        name matches, so only the FIRST warp for a destination is absorbed —
        a genuine later reposition to the same level still teleports.
        """
        echo = self._warp_echo
        if not echo:
            return False
        target, sent_at = echo
        matched = (level == target
                   or (grid_pos is not None
                       and self.gmap_grid.get(grid_pos) == target)
                   or (level.endswith('.gmap')
                       and target in self._known_gmap_segments))
        if not matched:
            return False
        self._warp_echo = None
        return time.monotonic() - sent_at <= self.WARP_ECHO_MAX_AGE_S

    def _restore_failed_warp(self, reason: str) -> None:
        """Roll back the optimistic state flip from warp_to_level after the
        server rejected the warp. The server's authoritative state never
        changed (we are still in the pre-warp level), so restore the snapshot
        taken in warp_to_level: level name, position, render board, and any
        cached NPCs for that level."""
        fallback = self._warp_fallback
        target = self._awaiting_warp_confirm
        self._awaiting_warp_confirm = ""
        self._warp_fallback = None
        self._release_local_transition()
        if not fallback:
            return
        prev_level, prev_x, prev_y = fallback
        logger.info("Warp to %r rejected by server (%s); restoring %r",
                    target, reason, prev_level)
        self._current_level_name = prev_level
        self._pending_level_name = prev_level
        # Mirror warp_to_level's optimistic player.level flip on rollback
        # (same gmap-name convention: only plain levels are stored there).
        if prev_level and prev_level not in self.gmap_grid.values():
            self.player.level = prev_level
        self.player.x = prev_x
        self.player.y = prev_y
        # Re-point the render board and restore cached NPCs; the server-side
        # state never changed, so the cached data is still authoritative.
        if prev_level in self.levels:
            self.tiles = self.levels[prev_level]
            self._tiles_level_name = prev_level
        cached_npcs = self._npc_cache.get(prev_level)
        if cached_npcs:
            self.npcs.update({nid: npc.copy()
                              for nid, npc in cached_npcs.items()})

    def _reset_level_state(self, cache_npcs: bool = True):
        """Clear per-level state on a full level change so ground items,
        baddies, horses and NPCs from the old level do not leak into the new
        one.

        Not called on seamless GMAP segment crossing (that goes through move(),
        not warp_to_level), so the stitched world keeps its entities.

        cache_npcs=False skips the per-level NPC snapshot: on a client-warp
        confirmation the NPCs present may be transit-window leaks stamped with
        the WRONG (optimistically-flipped) level, so caching them would poison
        _npc_cache for that level.

        Signs/chests/chest_items are NOT cleared: they are keyed by level name
        (no cross-level leakage possible) and gs2emu keeps a per-session
        level cache (PlayerClient.cpp sendStaticLevelData) - signs are only
        streamed on the FIRST entry of a level each session, so wiping them
        here made every sign in the world go dead after the first re-entered
        level (live-verified: re-warping into chicken_house1.nw streamed no
        PLO_LEVELSIGN at all). They mirror the server's own session cache."""
        self._reset_file_transfer_state(full_reset=False)
        self.items.clear()
        self.baddies.clear()
        self.horses.clear()
        self.board_layers.clear()
        self._board_layers_level_name = ""
        # PLO_ISLEADER (GServer-v2 PlayerClient.cpp checkAndInformIfLevelLeader)
        # is only ever sent to (re-)CONFIRM leadership on a level - there's no
        # "you are NOT the leader" packet, so is_leader must default back to
        # False on every real level change and wait to be reconfirmed, or a
        # client that was ever a level's leader (even briefly alone on its
        # spawn level before another player joined) stays stuck reporting
        # is_leader=True forever afterward on levels it doesn't actually lead
        # - which would make _leader_apply_baddy_damage fire on every such
        # client at once. Live-verified against real gs2emu: without this
        # reset, a second bot that had ever been alone on a level kept
        # is_leader=True after warping onto a level someone else already led.
        self.is_leader = False
        # Snapshot NPCs per level before clearing so we can restore them if we
        # come back and the server doesn't re-stream them (see _npc_cache).
        if cache_npcs:
            for nid, npc in self.npcs.items():
                lvl = npc.get('_level')
                if lvl:
                    self._npc_cache.setdefault(lvl, {})[nid] = npc.copy()
        self.npcs.clear()

    def _mark_npc_pos_snap(self, npc: dict) -> None:
        """Stamp `npc` with a fresh _pos_epoch so the renderer snaps its
        visual position instead of lerping to it. Call this whenever
        world_x/world_y is set/changed for a reason OTHER than the NPC
        actually moving during play (new NPC streamed in, gmap
        re-attribution, cache restore on level re-entry) - see the
        _npc_pos_epoch comment in __init__."""
        self._npc_pos_epoch += 1
        npc['_pos_epoch'] = self._npc_pos_epoch

    def _restore_cached_npcs(self, level_name: str) -> None:
        """Repopulate self.npcs from _npc_cache for level_name - and, when
        it is a segment of the loaded gmap, for EVERY segment of that gmap
        (the stitched world renders neighbors too, and gs2emu's per-session
        level cache means none of them get re-streamed on re-entry). Fresh
        PLO_NPCPROPS from the server simply overwrite these afterwards."""
        if not level_name:
            return
        names = [level_name]
        if self.gmap_grid and level_name in self.gmap_grid.values():
            names = list(self.gmap_grid.values())
        for name in names:
            cached = self._npc_cache.get(name)
            if cached:
                # Restored NPCs reappear at their last-known position - the
                # renderer must snap to it, not lerp from wherever a
                # same-numbered NPC happened to be visually parked before
                # (see _mark_npc_pos_snap).
                restored = {nid: npc.copy() for nid, npc in cached.items()}
                for npc in restored.values():
                    self._mark_npc_pos_snap(npc)
                self.npcs.update(restored)
    def check_link_collision(self) -> Optional[dict]:
        """
        Check if player is standing on a door/warp link.
        Returns the link dict if on a door link, None otherwise.

        Edge links (at level borders for GMAP adjacency) are ignored.
        Only "interior" links like doors/caves trigger warps.
        """
        # Use the current level (set at login, stable)
        if not self._current_level_name:
            return None

        links = self.links.get(self._current_level_name, [])
        if not links:
            return None

        # The reference engine tests one whole-tile directional probe, not
        # collision-box overlap. These offsets are GServer-v2
        # PlayerClient.cpp testForLinks()'s touchTest table; Level.cpp
        # getLink() then performs an inclusive point-in-bounding-box test.
        # Floor the world point before folding it into a 64-tile segment so
        # the probe wraps coherently when it crosses a GMAP seam.
        px, py = self.player.x, self.player.y
        probe_offsets = ((1.5, 1.0), (0.0, 2.0),
                         (1.5, 3.5), (3.0, 2.0))
        dx, dy = probe_offsets[int(self.player.direction) & 3]
        tile_x, tile_y = world_to_local(math.floor(px + dx), math.floor(py + dy))

        for link in links:
            lx = link.get('x', 0)
            ly = link.get('y', 0)
            lw = link.get('width', 1)
            lh = link.get('height', 1)

            # Check if this is an edge link (GMAP adjacency, ignore)
            is_edge = (lx <= 1 or lx + lw >= 63 or ly <= 1 or ly + lh >= 63)

            # Also check if destination is an adjacent GMAP level
            dest_level = link.get('dest_level', '')
            is_adjacent = dest_level in self.get_adjacent_levels(self._current_level_name)

            # Skip edge links to adjacent levels (GMAP seamless walking)
            if is_edge and is_adjacent:
                continue

            if lx <= tile_x <= lx + lw and ly <= tile_y <= ly + lh:
                return link

        return None

    def use_link(self, link: dict) -> bool:
        """
        Warp through a link (door/cave entrance).

        Args:
            link: Link dict from check_link_collision()

        Returns:
            True if warp initiated
        """
        if not link:
            return False

        dest_level = link.get('dest_level', '')
        dest_x = link.get('dest_x', '0')
        dest_y = link.get('dest_y', '0')

        # Destination coords (LOCAL within the destination level) may be a number
        # OR a Reborn expression referencing playerx/playery — used by edge links
        # to keep the player's coordinate across a seamless crossing (e.g.
        # "playery", "playerx-4"). Plain float() throws on those and the old code
        # fell back to (0,0), so every such warp dumped the player in the corner.
        px, py = world_to_local(self.player.x, self.player.y)
        new_x = _eval_warp_coord(dest_x, px, py)
        new_y = _eval_warp_coord(dest_y, px, py)
        # If an expression can't be evaluated, keep the current coordinate rather
        # than slamming to 0 (much closer to correct for an edge crossing).
        if new_x is None:
            new_x = px
        if new_y is None:
            new_y = py

        # Warp through warp_to_level so the SERVER is notified (PLI_LEVELWARP)
        # and the destination's coordinate frame is handled correctly: a GMAP
        # segment gets world coords, a standalone interior level (house/cave
        # reached via a door) keeps local coords. Without the server warp the
        # server keeps streaming our old GMAP position and yanks us around.
        transition_direction = self._edge_transition_direction(
            link, new_x, new_y)
        return self.warp_to_level(
            dest_level, new_x, new_y,
            transition_direction=transition_direction)

    def _edge_transition_direction(self, link: dict, dest_x: float,
                                   dest_y: float) -> Optional[int]:
        """Return the walk direction for an unambiguous boundary crossing.

        Direction values are the protocol/player convention: up, left, down,
        right. A qualifying link must touch the boundary being walked through
        and land on the opposite boundary of a standalone destination.
        """
        if (self.in_gmap_segment
                or link.get('dest_level', '') in self._known_gmap_segments):
            return None
        try:
            x = float(link.get('x', 0))
            y = float(link.get('y', 0))
            width = float(link.get('width', 1))
            height = float(link.get('height', 1))
            direction = int(self.player.direction) & 3
        except (TypeError, ValueError):
            return None

        source_edges = (y <= 1, x <= 1, y + height >= 63,
                        x + width >= 63)
        destination_edges = (dest_y >= 60, dest_x >= 60,
                             dest_y <= 1, dest_x <= 1)
        if source_edges[direction] and destination_edges[direction]:
            return direction
        return None
