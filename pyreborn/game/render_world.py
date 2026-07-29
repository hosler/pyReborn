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
the C# client's Maps.cs Draw, which walks the camera AABB rather than the whole
map). A bounded LRU keeps long exploration sessions from accumulating an
unbounded number of cached segments.
"""

import time
from collections import OrderedDict
from typing import List, Optional, Tuple

import pygame

from reborn_protocol.coords import segment_index, segment_origin

from ..tiletypes import TileType, get_tile_type
from . import theme
from .assets import render_outlined_text
from .constants import TILE_SIZE

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

        tile_range = self.camera.visible_tile_range()

        if in_gmap and c.gmap_grid:
            min_tx, min_ty, max_tx, max_ty = tile_range
            min_gx, max_gx = segment_index(min_tx), segment_index(max_tx)
            min_gy, max_gy = segment_index(min_ty), segment_index(max_ty)
            segments = []
            for gy in range(min_gy, max_gy + 1):
                for gx in range(min_gx, max_gx + 1):
                    level_name = c.gmap_grid.get((gx, gy))
                    if level_name:  # else segment not part of this gmap - stays black
                        segments.append((level_name, *segment_origin(gx, gy)))
        else:
            level_name = c._current_level_name or c._tiles_level_name or _STANDALONE_KEY
            segments = [(level_name, 0, 0)]

        for (level_name, grid_ox, grid_oy) in segments:
            self._blit_segment(level_name, grid_ox, grid_oy)

        # Sample the four-step ramp once so this pass and the later animated
        # draw use the same phase even if the clock crosses a cadence boundary.
        # Phase zero uses the base tile already baked into the segment.
        self._shimmer_step_this_frame = self._shimmer_ramp_step()
        self._shimmer_draw_this_frame = self._shimmer_step_this_frame != 0
        if self._shimmer_draw_this_frame:
            self._refresh_animated_tiles_cache(segments, tile_range)

    def _blit_segment(self, level_name: str, grid_ox: int, grid_oy: int):
        """Draw one segment's cached surface at its grid-tile offset."""
        surf = self._get_segment_surface(level_name)
        if surf is None:
            return  # not loaded yet - leave black, matches pre-refactor behavior
        self.screen.blit(surf, self.camera.world_to_screen(grid_ox, grid_oy))

    def _refresh_animated_tiles_cache(self, segments, tile_range):
        """Rebuild self._animated_tiles (the per-frame world-coord fold of
        every visible segment's water/lava index) only if the visible segment
        set, the underlying segment surfaces, or the camera's visible tile
        range actually changed since the last rebuild - a no-op while
        standing still looking at the same segments.

        Each segment's contribution is culled against `tile_range` (the exact
        tile-space rect the camera can see) up front - a segment is 64x64
        tiles but the viewport only ever shows a fraction of one, so this
        keeps the fold to the tiles that are actually going to be drawn
        instead of folding the whole segment and re-culling per-tile with
        `camera.world_to_screen` later in `_render_animated_tiles`.
        """
        min_tx, min_ty, max_tx, max_ty = tile_range
        cache = self._segments()
        key = (tile_range, tuple(
            (level_name, grid_ox, grid_oy,
             id(cache[level_name]['surface']) if level_name in cache else None)
            for (level_name, grid_ox, grid_oy) in segments
        ))
        if key == self._animated_tiles_key:
            return
        self._animated_tiles_key = key

        animated = []
        for (level_name, grid_ox, grid_oy) in segments:
            entry = cache.get(level_name)
            if not entry or not entry['animated']:
                continue
            lo_x, hi_x = min_tx - grid_ox, max_tx - grid_ox
            lo_y, hi_y = min_ty - grid_oy, max_ty - grid_oy
            for (tx, ty, tile_id) in entry['animated']:
                if lo_x <= tx <= hi_x and lo_y <= ty <= hi_y:
                    animated.append((grid_ox + tx, grid_oy + ty, tile_id))
        self._animated_tiles = animated

    def _render_level_loading(self):
        """Brief overlay shown while a newly-entered level's board streams in.

        Styled as a themed interstitial: navy field, the leaf emblem, and
        outlined text (drawn *when* the old code drew — only the look changed).
        """
        self.screen.fill(theme.NIGHT)
        cx, cy = self.screen_w // 2, self.screen_h // 2
        logo = theme.emblem(2)
        if logo is not None:
            self.screen.blit(logo, logo.get_rect(midbottom=(cx, cy - 14)))
        text = render_outlined_text(self.font, "Loading level...",
                                    theme.MINT_PALE, theme.NIGHT_DEEP)
        self.screen.blit(text, text.get_rect(midtop=(cx, cy + 14)))

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
        # Drop every animated-index entry inside the patched rect up front -
        # simpler than diffing per-cell, and the rect is re-populated below
        # from the freshly-patched tile data so nothing is lost.
        animated = entry['animated']
        animated[:] = [(atx, aty, aid) for (atx, aty, aid) in animated
                        if not (x <= atx < x + w and y <= aty < y + h)]
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
                if get_tile_type(tile_id) in self._ANIMATED_TILE_TYPES:
                    animated.append((tx, ty, tile_id))

        # _refresh_animated_tiles_cache keys off id(entry['surface']), which
        # doesn't change for an in-place patch like this one - force it to
        # re-fold so the animated-index edit above actually reaches the
        # per-frame shimmer list instead of being masked by a stale key hit.
        self._animated_tiles_key = None

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

        # Resolve each DISTINCT tile id once. A 64x64 board is 4096 cells but
        # only a few hundred distinct ids (259 on the live zlttp segments
        # measured 2026-07-25), and get_tile_or_color is not a plain dict hit:
        # with a tiledef active it re-evaluates `any(_applies(prefix))` over
        # the definition list on every call. Memoising halves the bake even
        # with no tiledefs (7.7 -> 3.8 ms/segment), and this bake is the frame
        # cost that shows up as a stutter when a level change drops the
        # segment cache and several segments re-bake in one frame.
        resolved = {}
        get_tile = self.tileset_mgr.get_tile_or_color
        animated_types = self._ANIMATED_TILE_TYPES
        blits = []
        for ty in range(64):
            row = ty * 64
            for tx in range(64):
                tile_id = tiles[row + tx]
                entry = resolved.get(tile_id)
                if entry is None:
                    entry = (get_tile(tile_id),
                             get_tile_type(tile_id) in animated_types)
                    resolved[tile_id] = entry
                blits.append((entry[0], (tx * TILE_SIZE, ty * TILE_SIZE)))
                # Tier 4a: index water/lava tiles (segment-local coords) for
                # the per-frame shimmer pass - cheap here since we're already
                # iterating every tile once for the base composite.
                if entry[1]:
                    animated_out.append((tx, ty, tile_id))
        surface.blits(blits, doreturn=False)

    def _get_shimmer_tile(self, tile_id: int, step: int) -> pygame.Surface:
        """Tier 4a fallback animation: a subtle brightness-pulsed copy of a
        water/lava tile. No verified multi-frame pics1.png animation-index
        table exists in this repo (unlike chests, nothing here was hand-picked
        against a live server for this), so per the task's documented
        fallback this uses a palette-shift shimmer instead of guessing real
        alternate-frame tile ids."""
        cache = getattr(self, '_shimmer_cache', None)
        if cache is None:
            cache = self._shimmer_cache = {}
        # Normal zoomed rendering uses a 1:1 scratch camera and scales the
        # finished scene, while direct/debug rendering can use a zoomed camera
        # here. Key by the effective camera zoom and make the tile match that
        # camera's pixel footprint so both paths remain aligned.
        zoom = round(self.camera.zoom, 6)
        key = (tile_id, zoom)
        variants = cache.get(key)
        if variants is not None:
            return variants[step - 1]

        base = self.tileset_mgr.get_tile_or_color(tile_id)
        footprint = max(1, round(self.camera.scale))
        if base.get_size() != (footprint, footprint):
            base = pygame.transform.scale(base, (footprint, footprint))

        # Build every non-base ramp variant together on the first cache miss;
        # animated tiles only perform dictionary lookups and blits per frame.
        made = []
        for bump in ((9, 13, 17), (18, 26, 34)):
            shimmer = base.copy()
            overlay = pygame.Surface(shimmer.get_size())
            overlay.fill(bump)
            shimmer.blit(overlay, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
            made.append(shimmer)
        # Steps 1 and 3 are the same half-bright frame in off/half/full/half.
        variants = (made[0], made[1], made[0])
        cache[key] = variants
        return variants[step - 1]

    _SHIMMER_PERIOD = 0.3

    def _shimmer_ramp_step(self) -> int:
        """Return the current off/half/full/half ramp step at 300ms cadence."""
        return int(time.time() / self._SHIMMER_PERIOD) % 4

    def _render_animated_tiles(self):
        """Tier 4a: redraw just the indexed water/lava tiles every ~300ms with
        a shimmer variant, on top of the already-composited world_surface."""
        if not self._shimmer_draw_this_frame:
            return  # base tile (already baked into world_surface) is frame 0
        tiles = self._animated_tiles
        if not tiles:
            return
        # tiles is already culled to the camera's visible tile range (see
        # _refresh_animated_tiles_cache), so no per-tile screen-bounds check
        # is needed here beyond the world->screen conversion for the blit.
        for (tx, ty, tile_id) in tiles:
            sx, sy = self.camera.world_to_screen(tx, ty)
            tile = self._get_shimmer_tile(tile_id, self._shimmer_step_this_frame)
            self.screen.blit(tile, (int(sx), int(sy)))
