"""WorldRenderMixin — level/tile world surface composition.

Split from render.py; methods operate on the GameClient instance.

Scalability note: this used to build ONE pygame surface sized to the entire
GMAP (gmap_width*64*TILE_SIZE square) and rebuild the whole thing on any
change. An 8x8-segment GMAP is an 8192x8192px surface (~256MB); a 16x16+
classic GMAP would be gigabytes, and every redraw repainted the lot.

Instead each 64x64-tile level segment (a single non-GMAP level counts as one
segment) gets its own small cached surface, built lazily the first time it's
visible and reused until its tile data actually changes. Per frame, only the
segments intersecting the camera's visible tile range are blitted (mirrors
Preagonal's Maps.cs Draw, which walks the camera AABB rather than the whole
map). A bounded LRU keeps long exploration sessions from accumulating an
unbounded number of cached segments.
"""

import time
import json
import re
from collections import OrderedDict
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

# Key used for a standalone (non-GMAP) level when neither _current_level_name
# nor _tiles_level_name is set yet (shouldn't normally happen - _render_world
# bails out before this if there's no board data at all - but keeps
# _get_segment_surface total).
_STANDALONE_KEY = "__standalone__"

# Bounds how many segment surfaces stay cached across a play session,
# independent of how big the GMAP is. Generous relative to any single
# viewport (a 21x15-tile screen at 64 tiles/segment touches at most ~2x2-3x3
# segments) so nearby recently-visited segments stay warm, but firmly capped
# so a long crawl across a large classic GMAP (16x16+ segments) never holds
# more than _MAX_CACHED_SEGMENTS * (64*TILE_SIZE)^2 px - megabytes, not the
# gigabytes a monolithic whole-GMAP surface would cost.
_MAX_CACHED_SEGMENTS = 25


class WorldRenderMixin:
    """Mixin providing the above methods for GameClient."""

    def _render_world(self):
        """Render the tile world: blit every cached (or freshly built)
        segment surface intersecting the camera's visible tile range."""
        c = self.client
        # On a first-visit (non-GMAP) level, the board streams in a few frames
        # after the warp. Until it arrives, self.tiles still holds the OLD
        # level's board — drawing it puts the player over the wrong tiles (the
        # "warped before the new tiles render" glitch). Show a loading state
        # instead. Cached levels are repopulated synchronously in warp_to_level,
        # so this only triggers on genuinely-new levels.
        in_gmap = c._current_level_name in c.gmap_grid.values()
        if (not in_gmap and c._current_level_name
                and c._tiles_level_name != c._current_level_name):
            self._render_level_loading()
            return

        if not c.levels and not c.tiles:
            return

        self._apply_pending_full_invalidate()

        # Tier 4a: the water/lava shimmer index is rebuilt this frame from
        # whichever segments actually get blitted below (folded from each
        # segment's own cached, segment-local index into world tile coords).
        self._animated_tiles = []

        if in_gmap and c.gmap_grid:
            min_tx, min_ty, max_tx, max_ty = self.camera.visible_tile_range()
            min_gx, max_gx = min_tx // 64, max_tx // 64
            min_gy, max_gy = min_ty // 64, max_ty // 64
            for gy in range(min_gy, max_gy + 1):
                for gx in range(min_gx, max_gx + 1):
                    level_name = c.gmap_grid.get((gx, gy))
                    if not level_name:
                        continue  # segment not part of this gmap - stays black
                    self._blit_segment(level_name, gx * 64, gy * 64)
        else:
            level_name = c._current_level_name or c._tiles_level_name or _STANDALONE_KEY
            self._blit_segment(level_name, 0, 0)

    def _blit_segment(self, level_name: str, grid_ox: int, grid_oy: int):
        """Draw one segment's cached surface at its grid-tile offset, and fold
        its (segment-local) animated-tile index into this frame's world coords."""
        surf = self._get_segment_surface(level_name)
        if surf is None:
            return  # not loaded yet - leave black, matches pre-refactor behavior
        self.screen.blit(surf, self.camera.world_to_screen(grid_ox, grid_oy))
        entry = self._segments().get(level_name)
        if entry:
            for (tx, ty, tile_id) in entry['animated']:
                self._animated_tiles.append((grid_ox + tx, grid_oy + ty, tile_id))

    def _render_level_loading(self):
        """Brief overlay shown while a newly-entered level's board streams in."""
        text = self.font.render("Loading level...", True, (235, 235, 235))
        self.screen.blit(text, (self.screen_w // 2 - text.get_width() // 2,
                                self.screen_h // 2 - text.get_height() // 2))

    # -- per-segment cache --------------------------------------------------

    def _segments(self) -> "OrderedDict[str, dict]":
        """Lazily-initialized level_name -> segment cache entry map.

        Each entry: {'surface', 'tiles_id', 'layers_snapshot', 'animated'}.
        An OrderedDict so recently-used segments can be pushed to the end and
        stale ones evicted from the front once _MAX_CACHED_SEGMENTS is exceeded.
        """
        cache = getattr(self, '_segment_cache', None)
        if cache is None:
            cache = self._segment_cache = OrderedDict()
        return cache

    def _apply_pending_full_invalidate(self):
        """Several call sites (level warps, tile-editor corrections, lift/throw
        tile swaps, board-layer streams — setup.py/actions.py/tile_editor.py)
        still poke `self.world_surface = None` as a holdover from the old
        single-surface design, to force a full redraw. Honor that as "drop
        every cached segment"; segments simply rebuild lazily as they re-enter
        view, so this stays a cheap (if coarser-than-necessary) fallback.
        `self.world_surface` is no longer a real surface - just a sentinel
        those call sites flip to None; we flip it back to a truthy marker so
        this only fires once per invalidation instead of every frame."""
        if self.world_surface is None:
            self._segments().clear()
        self.world_surface = True

    def _segment_tiles(self, level_name: str) -> Optional[List[int]]:
        """The authoritative tile list backing a segment, mirroring how
        client.py itself resolves "current" tiles vs the per-level cache."""
        c = self.client
        tiles = c.levels.get(level_name)
        if tiles is None and level_name == c._tiles_level_name:
            tiles = c.tiles
        return tiles

    def _get_segment_surface(self, level_name: str) -> Optional[pygame.Surface]:
        """Get (building/rebuilding only if stale) the cached surface for one
        64x64-tile level segment.

        Cache key: level_name. Invalidation: the tiles list is replaced
        wholesale (new id()) whenever fresh board data streams in for that
        level (client.py always assigns a new list on PLO_BOARDPACKET), so an
        identity check is enough to detect that case cheaply; boardmodify
        deltas patch the same list object in place (see
        _patch_world_surface_for_modify) and are intentionally invisible to
        this check, since they patch the cached surface directly instead of
        forcing a rebuild. Extra board layers (client.board_layers) are only
        ever meaningful for whichever level is currently active - non-active
        segments never composite them - and are compared by value (not
        identity) since client.py mutates that dict in place.
        """
        tiles = self._segment_tiles(level_name)
        if not tiles:
            return None

        cache = self._segments()
        c = self.client
        tiles_id = id(tiles)
        is_active = (level_name == c._current_level_name)
        layers_snapshot = dict(c.board_layers) if (is_active and c.board_layers) else None

        entry = cache.get(level_name)
        if (entry is not None and entry['tiles_id'] == tiles_id
                and entry['layers_snapshot'] == layers_snapshot):
            cache.move_to_end(level_name)
            return entry['surface']

        surf = pygame.Surface((64 * TILE_SIZE, 64 * TILE_SIZE))
        surf.fill((0, 0, 0))
        animated: List[Tuple[int, int, int]] = []
        self._render_single_level(surf, tiles, animated)

        if layers_snapshot:
            for layer_id, raw in layers_snapshot.items():
                if layer_id == 0:
                    continue
                self._composite_board_layer(surf, raw, 0, 0)

        cache[level_name] = {
            'surface': surf,
            'tiles_id': tiles_id,
            'layers_snapshot': layers_snapshot,
            'animated': animated,
        }
        cache.move_to_end(level_name)
        while len(cache) > _MAX_CACHED_SEGMENTS:
            cache.popitem(last=False)  # evict the least-recently-used segment
        return surf

    def _decode_board_layer_tiles(self, raw: bytes) -> List[int]:
        """Decode a PLO_BOARDLAYER tile blob into 4096 tile ids.

        GServer always sends a full 64x64 layer (w=h=64 hardcoded - see
        Level.cpp sendBoardLayerToPlayer) as 5 header bytes (layer, x, y, w, h)
        followed by 64*64*2 raw little-endian tile bytes, same encoding as
        PLO_BOARDPACKET. packets.py's parse_board_layer only consumes 3 of
        those 5 header bytes (layer, x, y) before treating the rest as tile
        data, so what we get here as `raw` still has the w/h gchars (2 bytes)
        glued onto the front. Rather than touch the shared parser, detect and
        strip that known-length leftover here.
        """
        data = raw
        if len(data) >= 8192 + 2:
            data = data[2:]
        tiles = []
        for i in range(0, min(len(data), 8192), 2):
            b1 = data[i] if i < len(data) else 0
            b2 = data[i + 1] if i + 1 < len(data) else 0
            tiles.append((b1 + (b2 << 8)) & 0xFFF)
        while len(tiles) < 4096:
            tiles.append(0)
        return tiles[:4096]

    def _composite_board_layer(self, surface: pygame.Surface, raw: bytes,
                                offset_x: int, offset_y: int):
        """Blit one decoded board layer's non-empty (tile id 0) tiles onto
        `surface` at the given pixel offset."""
        tiles = self._decode_board_layer_tiles(raw)
        for ty in range(64):
            row = ty * 64
            for tx in range(64):
                tile_id = tiles[row + tx]
                if tile_id == 0:
                    continue  # transparent - base layer shows through
                tile = self.tileset_mgr.get_tile(tile_id)
                if tile:
                    surface.blit(tile, (offset_x + tx * TILE_SIZE, offset_y + ty * TILE_SIZE))

    def _patch_world_surface_for_modify(self, info: dict):
        """Tier 1b: patch a PLO_BOARDMODIFY/BOARDMODIFY2 tile delta directly
        into the owning segment's cached surface instead of a full rebuild.

        client.tiles/client.levels are already patched by client.py by the
        time this callback fires (see Client._apply_board_modify), so this
        just re-blits the affected rect's tiles from that already-authoritative
        data. Only layer 0 (the base board) is handled here - extra layers go
        through the board_layers/on_board_layer full-rebuild path instead.
        Only the owning segment's surface is touched; every other cached
        segment (and its tiles_id fingerprint) is left exactly as-is, so
        _get_segment_surface won't rebuild them next frame.
        """
        if info.get('layer', 0) != 0:
            return
        x, y = info.get('x', 0), info.get('y', 0)
        w, h = info.get('width', 0), info.get('height', 0)
        if w <= 0 or h <= 0:
            return

        c = self.client
        if 'map_x' in info and 'map_y' in info:
            level_name = c.gmap_grid.get((info['map_x'], info['map_y']))
        else:
            level_name = c._current_level_name
        if not level_name:
            return

        entry = self._segments().get(level_name)
        if entry is None:
            return  # not cached yet - the next lazy build will include this edit

        tiles = self._segment_tiles(level_name)
        if not tiles or len(tiles) < 4096:
            return

        surf = entry['surface']
        surf_w, surf_h = surf.get_size()
        for row in range(h):
            ty = y + row
            if ty < 0 or ty >= 64:
                continue
            for col in range(w):
                tx = x + col
                if tx < 0 or tx >= 64:
                    continue
                dest_x, dest_y = tx * TILE_SIZE, ty * TILE_SIZE
                if not (0 <= dest_x < surf_w and 0 <= dest_y < surf_h):
                    continue
                tile_id = tiles[ty * 64 + tx]
                tile = self.tileset_mgr.get_tile_or_color(tile_id)
                surf.blit(tile, (dest_x, dest_y))

    # Tier 4a: tile types eligible for the water/lava shimmer.
    _ANIMATED_TILE_TYPES = (TileType.WATER, TileType.NEAR_WATER,
                            TileType.LAVA, TileType.LAVA_SWAMP)

    def _render_single_level(self, surface: pygame.Surface, tiles: List[int],
                              animated_out: List[Tuple[int, int, int]]):
        """Render one level's 64x64 tiles onto its own (segment-local, always
        0,0-based) surface, indexing water/lava tiles into animated_out using
        segment-local tile coords - the caller adds the segment's grid offset
        when folding these into the per-frame world-coord shimmer list."""
        if not tiles:
            return

        for ty in range(64):
            row = ty * 64
            for tx in range(64):
                tile_id = tiles[row + tx]
                dest_x = tx * TILE_SIZE
                dest_y = ty * TILE_SIZE

                tile = self.tileset_mgr.get_tile_or_color(tile_id)
                surface.blit(tile, (dest_x, dest_y))

                # Tier 4a: index water/lava tiles (segment-local coords) for
                # the per-frame shimmer pass - cheap here since we're already
                # iterating every tile once for the base composite.
                if get_tile_type(tile_id) in self._ANIMATED_TILE_TYPES:
                    animated_out.append((tx, ty, tile_id))

    def _get_shimmer_tile(self, tile_id: int) -> pygame.Surface:
        """Tier 4a fallback animation: a subtle brightness-pulsed copy of a
        water/lava tile. No verified multi-frame pics1.png animation-index
        table exists in this repo (unlike chests, nothing here was hand-picked
        against a live server for this), so per the task's documented
        fallback this uses a palette-shift shimmer instead of guessing real
        alternate-frame tile ids."""
        cache = getattr(self, '_shimmer_cache', None)
        if cache is None:
            cache = self._shimmer_cache = {}
        if tile_id in cache:
            return cache[tile_id]
        base = self.tileset_mgr.get_tile_or_color(tile_id)
        shimmer = base.copy()
        overlay = pygame.Surface(shimmer.get_size(), pygame.SRCALPHA)
        overlay.fill((190, 225, 255, 55))
        shimmer.blit(overlay, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)
        cache[tile_id] = shimmer
        return shimmer

    def _render_animated_tiles(self):
        """Tier 4a: redraw just the indexed water/lava tiles every ~300ms with
        a shimmer variant, on top of the already-composited world_surface."""
        tiles = self._animated_tiles
        if not tiles:
            return
        period = 0.3
        frame = int(time.time() / period) % 2
        if frame == 0:
            return  # base tile (already baked into world_surface) is frame 0
        surf_w, surf_h = self.screen.get_size()
        for (tx, ty, tile_id) in tiles:
            sx, sy = self.camera.world_to_screen(tx, ty)
            if sx < -TILE_SIZE or sx > surf_w or sy < -TILE_SIZE or sy > surf_h:
                continue
            self.screen.blit(self._get_shimmer_tile(tile_id), (int(sx), int(sy)))
