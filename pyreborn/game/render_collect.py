"""Entity collection and interpolation mixin."""

from __future__ import annotations

from typing import List, Optional, Tuple

from reborn_protocol.coords import local_to_world, segment_origin

from ..npc_handler import CHARACTER_IMAGE
from .constants import TILE_SIZE
from .frame_context import FrameContext
from .render_shared import (
    BaddySheet, _BADDY_DEFAULT_IMAGE, _BADDY_IMAGES, _Entity,
)


def _npc_draw_band(draw_layer) -> int:
    """Translate script-facing NPC layers into renderer bands.

    The C# client stores over as +1 and under as -1; renderer bands shift
    those values by one so all keys stay non-negative:
    Preagonal/FourPlay/quattroplay/src/TServerNPCProperties.cpp:450
    Preagonal/FourPlay/quattroplay/src/TServerNPCProperties.cpp:451
    """
    if draw_layer == 'under':
        return 0
    if draw_layer == 'over':
        return 2
    return 1


class EntityCollectMixin:
    @staticmethod
    def _depth_sort_key(world_y: float, height_tiles: float) -> float:
        """Bottom edge of an entity image in world-tile coordinates."""
        return world_y + height_tiles

    def _npc_height_tiles(self, npc: dict) -> float:
        """Best-known rendered height for an NPC, in tiles."""
        part = npc.get('imagepart')
        if part and len(part) >= 4 and part[3] > 0:
            return part[3] / TILE_SIZE
        image = npc.get('image')
        if (image and image != CHARACTER_IMAGE
                and not npc.get('gani', npc.get('animation'))):
            # CHARACTER_IMAGE ('#c#') is the showcharacter marker, not a
            # sheet; a character is the default 3-tile gani canvas below.
            sprite = self.sprite_mgr.load_sheet(image)
            if sprite is not None:
                return sprite.get_height() / TILE_SIZE
        return 3.0

    def _baddy_height_tiles(self, baddy: dict) -> float:
        image = baddy.get('image') or _BADDY_IMAGES.get(
            baddy.get('type', 0), _BADDY_DEFAULT_IMAGE)
        sheet = self.sprite_mgr.load_sheet(image)
        if sheet is not None:
            _, height, _ = BaddySheet(self.sprite_mgr, image)._sheet_layout(sheet)
            return height / TILE_SIZE
        return 3.0

    def _horse_height_tiles(self, horse: dict) -> float:
        sprite = self.sprite_mgr.load_sheet(horse.get('image') or 'horse.png')
        return sprite.get_height() / TILE_SIZE if sprite is not None else 3.0

    def _entity_on_screen(self, px: float, py: float, margin: int = 96,
                           width: float = 0.0, height: float = 0.0,
                           screen_size: Optional[Tuple[int, int]] = None) -> bool:
        """True if a sprite at screen pixel (px, py) is near enough the canvas to
        be worth drawing. Levels can carry dozens of NPCs spread across 64x64;
        culling the off-screen ones skips their load_sheet/blit work entirely.
        Bounds come from self.screen so it adapts to the zoom scene surface.
        `screen_size` lets a hot per-frame caller hoist self.screen.get_size()
        out of a per-entity loop (see _render_entities, which calls this once
        per entity at up to ~80 entities/frame); callers that don't pass it
        (render_effects.py) still get it looked up here, unchanged."""
        w, h = screen_size if screen_size is not None else self.screen.get_size()
        return (px + width >= -margin and px <= w + margin and
                py + height >= -margin and py <= h + margin)

    def _npc_draw_size(self, npc: dict) -> Tuple[float, float]:
        part = npc.get('imagepart')
        if part and len(part) >= 4 and part[2] > 0 and part[3] > 0:
            return float(part[2]), float(part[3])
        image = npc.get('image')
        if (image and image != CHARACTER_IMAGE
                and not npc.get('gani', npc.get('animation'))):
            # CHARACTER_IMAGE ('#c#') is the showcharacter marker, not a
            # sheet — a character composites on the default gani canvas, so
            # the fallback extent below is the right size for it.
            sprite = self.sprite_mgr.load_sheet(image)
            if sprite is not None:
                return sprite.get_size()
        extent = self.camera.scale * 4
        return extent, extent

    def _render_entities(self, frame: Optional[FrameContext] = None):
        """Render all entities (players, NPCs) sorted by Y position.

        Three phases: collect a snapshot of what is drawable, with each
        entity's world position already resolved and interpolated; sort that
        by depth; dispatch each entry through _ENTITY_RENDERERS. Cross-pass
        scratch (nameplate rects, deferred light draws) lives on `frame`, not
        on self, so render_effects.py's consumers take it as an argument
        instead of depending on this having run first."""
        frame = self._begin_frame() if frame is None else frame
        # Resolved when the pass starts rather than at frame start: while
        # zoomed the scene is drawn into a SMALLER scratch surface
        # (render.py's _render_scene_zoomed swaps self.screen), and culling
        # must use that surface's bounds. Hoisted out of the per-entity loop
        # either way - see _entity_on_screen.
        frame.screen_size = self.screen.get_size()
        self._resolve_frame_gmap(frame)

        entities: List[_Entity] = []
        for _kind, collect, _render in self._ENTITY_PASSES:
            collect(self, entities, frame)

        # Every key is the image's bottom edge in the same world-tile frame.
        # The sort is stable, so equal keys keep _ENTITY_PASSES order.
        entities.sort(key=lambda e: (e.band, e.depth))

        renderers = self._ENTITY_RENDERERS
        for ent in entities:
            renderers[ent.kind](self, ent, frame)

        self._render_weapon_layers()

    # -- entity pass: resolve ------------------------------------------------

    def _resolve_frame_gmap(self, frame: FrameContext) -> None:
        """Snapshot the gmap lookups the collectors need: level name -> grid
        cell (which the remote-player loop used to rescan per player), and the
        current segment's world origin (which local-coord entities fold in).

        The two are derived separately on purpose. If one level name occupies
        two cells of a gmap grid, the name lookup resolves to the LAST and the
        segment origin to the FIRST - what the inline code did."""
        grid = self.client.gmap_grid
        if not grid:
            return
        frame.level_to_grid = {name: cell for cell, name in grid.items()}
        seg = next((cell for cell, name in grid.items()
                    if name == self.client._current_level_name), None)
        if seg:
            frame.segment_offset = segment_origin(*seg)

    def _world_pos_for_level(self, local_x: float, local_y: float,
                             level_name: str, frame: FrameContext):
        """World position of a wire (level-local) position in `level_name`.
        Prefer the entity's own level; if that's unset or unknown, assume the
        same sub-level as the local player. Off a gmap there is no grid and
        the local coords already are world coords."""
        grid = frame.level_to_grid.get(level_name) if level_name else None
        if grid is None:
            grid = frame.level_to_grid.get(self.client._current_level_name)
        if grid is None:
            return local_x, local_y
        return local_to_world(local_x, local_y, *grid)

    def _lerp_toward(self, previous, target_x: float, target_y: float,
                     dt: float):
        """One frame of the shared remote-entity position chase."""
        vx, vy = previous
        lerp = min(1.0, self.lerp_speed * dt)
        return vx + (target_x - vx) * lerp, vy + (target_y - vy) * lerp

    def _interpolate_other_player(self, pid, world_x: float, world_y: float,
                                  frame: FrameContext):
        """Smoothed world position of a remote player: chase the authoritative
        position, or snap the first time this pid is seen."""
        previous = self.other_player_visual.get(pid)
        position = (self._lerp_toward(previous, world_x, world_y, frame.dt)
                    if previous is not None else (world_x, world_y))
        self.other_player_visual[pid] = position
        return position

    def _interpolate_npc(self, npc_id, npc: dict, nx: float, ny: float,
                         frame: FrameContext):
        """Smoothed world position of an NPC, EXCEPT when client.py just
        re-stamped its world_x/world_y for a reason other than it actually
        moving (gmap re-attribution, cache restore on level re-entry, initial
        stream - see client.py's _mark_npc_pos_snap/_pos_epoch). Lerping
        across one of those jumps is what made lights visibly "swoop into
        position" on level entry; snap instead, same as a brand-new npc_id.

        epoch_seen mirrors npc_visual (same lifetime - both keyed by npc_id
        and only needing to outlive the NPCs the client knows about), but is
        lazily created rather than added to pygame_game.py's __init__ since
        it's purely an implementation detail of this interpolation. A stale
        leftover entry for a since-removed npc_id is harmless: client.py's
        epoch counter only increases and is never reused, so it can never
        collide with a future npc_id's real epoch and suppress a snap."""
        epoch_seen = getattr(self, '_npc_visual_epoch', None)
        if epoch_seen is None:
            epoch_seen = self._npc_visual_epoch = {}
        epoch = npc.get('_pos_epoch')
        previous = self.npc_visual.get(npc_id)
        position = (self._lerp_toward(previous, nx, ny, frame.dt)
                    if previous is not None and epoch == epoch_seen.get(npc_id)
                    else (nx, ny))
        self.npc_visual[npc_id] = position
        epoch_seen[npc_id] = epoch
        if len(epoch_seen) > 2000:
            epoch_seen.clear()
        return position

    # -- entity pass: collect ----------------------------------------------

    def _collect_chests(self, out: List["_Entity"],
                        frame: FrameContext) -> None:
        level_name, origin_x, origin_y = self._current_segment_info()
        chests = self.client.chests_in_level(level_name)
        if not chests:
            return
        surf_w, surf_h = frame.screen_size
        # Chest keys are level-local while the camera and every depth key use
        # world coordinates. Add this segment's origin to both operations so
        # the sprite and its sorting bottom remain in the same frame.
        for (cx, cy), opened in chests.items():
            sprite = self._get_chest_sprite(bool(opened))
            if sprite is None:
                continue
            world_x, world_y = cx + origin_x, cy + origin_y
            sx, sy = self._world_to_screen(world_x, world_y)
            if sx < -sprite.get_width() or sx > surf_w or \
               sy < -sprite.get_height() or sy > surf_h:
                continue
            out.append(_Entity('chest', self._depth_sort_key(
                world_y, sprite.get_height() / TILE_SIZE), sx, sy, sprite))

    def _collect_items(self, out: List["_Entity"],
                       frame: FrameContext) -> None:
        level_name, origin_x, origin_y = self._current_segment_info()
        items = self.client.items_in_level(level_name)
        if not items:
            return
        surf_w, surf_h = frame.screen_size
        # Item keys are level-local while the camera and every depth key use
        # world coordinates. Folding only the blit reproduces the live failure
        # where an item draws beside the player but sorts as if in segment zero.
        for (ix, iy), item_type in items.items():
            sprite = self._get_item_sprite(item_type)
            world_x, world_y = ix + origin_x, iy + origin_y
            sx, sy = self._world_to_screen(world_x, world_y)
            if sx < -TILE_SIZE or sx > surf_w or \
               sy < -TILE_SIZE or sy > surf_h:
                continue
            out.append(_Entity('item', self._depth_sort_key(
                world_y, sprite.get_height() / TILE_SIZE), sx, sy, sprite))

    def _collect_local_player(self, out: List["_Entity"],
                              frame: FrameContext) -> None:
        """The local player, drawn through the camera at its true render-frame
        top-left (set by _sync_camera) — the same transform every other entity
        uses — so it stays correct under zoom and the camera can aim at the
        body centre without dragging the sprite off its real position. Never
        culled."""
        if getattr(self.client, '_local_level_transition', ''):
            return
        # Depth-sort key must be in the SAME frame as every other entity
        # (world tiles). visual_y is already world-frame.
        px, py = self.camera.world_to_screen(*self._player_render_pos)
        out.append(_Entity('player', self._depth_sort_key(self.visual_y, 3.0),
                           px, py, self.client.player))

    def _collect_other_players(self, out: List["_Entity"],
                               frame: FrameContext) -> None:
        for pid, pdata in self.client.players.items():
            ox = pdata.get('x')
            oy = pdata.get('y')
            if ox is None or oy is None:
                continue
            world_x, world_y = self._world_pos_for_level(
                ox, oy, pdata.get('level', ''), frame)
            vx, vy = self._interpolate_other_player(pid, world_x, world_y, frame)
            sx, sy = self.camera.world_to_screen(vx, vy)
            if self._entity_on_screen(sx, sy, screen_size=frame.screen_size):
                out.append(_Entity('other', self._depth_sort_key(vy, 3.0),
                                   sx, sy, pdata, pid))

    def _collect_npcs(self, out: List["_Entity"],
                      frame: FrameContext) -> None:
        for npc_id, npc in self.client.npcs.items():
            npc_level = npc.get('_level')
            if (npc_level and not self.client.in_gmap_segment and
                    npc_level != self.client._current_level_name):
                continue
            # Prefer world coords (converted from local + grid offset)
            nx = npc.get('world_x', npc.get('x'))
            ny = npc.get('world_y', npc.get('y'))
            if nx is None or ny is None:
                continue
            vx, vy = self._interpolate_npc(npc_id, npc, nx, ny, frame)
            sx, sy = self.camera.world_to_screen(vx, vy)
            draw_w, draw_h = self._npc_draw_size(npc)
            if self._entity_on_screen(sx, sy, width=draw_w, height=draw_h,
                                      screen_size=frame.screen_size):
                out.append(_Entity('npc', self._depth_sort_key(
                    vy, self._npc_height_tiles(npc)), sx, sy, npc, npc_id,
                    _npc_draw_band(npc.get('draw_layer'))))
                continue
            # A culled NPC's own sprite is skipped but its showimg layers are
            # not: one layer can be far bigger than the sprite and still cover
            # the screen from an off-screen owner (see _render_npc_layers'
            # on_screen_only note). Drawn HERE, during collection, so they
            # land under every depth-sorted entity - where they were before
            # this pass was split.
            imgs = npc.get('imgs')
            if imgs and npc.get('visible') is not False:
                self._render_npc_layers(imgs, over=False, on_screen_only=True)
                self._render_npc_layers(imgs, over=True, on_screen_only=True)

    def _collect_baddies(self, out: List["_Entity"],
                         frame: FrameContext) -> None:
        """Baddies (enemies). Their x/y are local to the current segment, so
        fold in that segment's gmap offset to line them up with the world.

        Unlike items and chests, this store is flat: it holds no level, so the
        fold assumes every baddy belongs to the player's own segment. Two
        server-side facts keep that true today, and a gmap world with a BADDY
        line under pygserver would break it. CLAUDE.md "Per-level stores, and
        the two that are not" records both, and what the fix costs."""
        off_x, off_y = frame.segment_offset
        for bid, baddy in self.client.baddies.items():
            bx = baddy.get('x')
            by = baddy.get('y')
            if bx is None or by is None:
                continue
            wx, wy = bx + off_x, by + off_y
            sx, sy = self.camera.world_to_screen(wx, wy)
            if self._entity_on_screen(sx, sy, screen_size=frame.screen_size):
                out.append(_Entity('baddy', self._depth_sort_key(
                    wy, self._baddy_height_tiles(baddy)), sx, sy, baddy, bid))

    def _collect_horses(self, out: List["_Entity"],
                        frame: FrameContext) -> None:
        """Horses (Tier 1a) - other players' PLI_HORSEADD mounts. Local coords
        like baddies, so fold in the current segment's gmap offset."""
        off_x, off_y = frame.segment_offset
        for hkey, horse in self.client.horses.items():
            hx = horse.get('x')
            hy = horse.get('y')
            if hx is None or hy is None:
                continue
            wx, wy = hx + off_x, hy + off_y
            sx, sy = self.camera.world_to_screen(wx, wy)
            if self._entity_on_screen(sx, sy, screen_size=frame.screen_size):
                out.append(_Entity('horse', self._depth_sort_key(
                    wy, self._horse_height_tiles(horse)), sx, sy, horse, hkey))

    # -- entity pass: draw --------------------------------------------------

    def _draw_chest_entity(self, ent: "_Entity", frame: FrameContext) -> None:
        self.screen.blit(ent.data, (int(ent.x), int(ent.y)))

    def _draw_item_entity(self, ent: "_Entity", frame: FrameContext) -> None:
        self.screen.blit(ent.data, (int(ent.x), int(ent.y)))

    def _draw_player_entity(self, ent: "_Entity", frame: FrameContext) -> None:
        self._render_player(ent.x, ent.y, ent.data, self.player_anim, frame)

    def _draw_other_player_entity(self, ent: "_Entity",
                                  frame: FrameContext) -> None:
        self._render_other_player(ent.x, ent.y, ent.data, ent.key, frame)

    def _draw_npc_entity(self, ent: "_Entity", frame: FrameContext) -> None:
        self._render_npc(ent.x, ent.y, ent.data, ent.key, frame)

    def _draw_baddy_entity(self, ent: "_Entity", frame: FrameContext) -> None:
        self._render_baddy(ent.x, ent.y, ent.data, ent.key)

    def _draw_horse_entity(self, ent: "_Entity", frame: FrameContext) -> None:
        self._render_horse(ent.x, ent.y, ent.data, ent.key)

    # kind -> (collector, renderer) in COLLECTION order, which the stable
    # depth sort also makes the tie-break between two entities whose image
    # bottoms land on the same world row. A new entity kind is one row here
    # plus its two methods, not an edit to _render_entities.
    _ENTITY_PASSES = (
        ('chest', _collect_chests, _draw_chest_entity),
        ('item', _collect_items, _draw_item_entity),
        ('player', _collect_local_player, _draw_player_entity),
        ('other', _collect_other_players, _draw_other_player_entity),
        ('npc', _collect_npcs, _draw_npc_entity),
        ('baddy', _collect_baddies, _draw_baddy_entity),
        ('horse', _collect_horses, _draw_horse_entity),
    )
    _ENTITY_RENDERERS = {kind: render
                         for kind, _collect, render in _ENTITY_PASSES}

    def _render_weapon_layers(self) -> None:
        """Weapon image layers — the arena bombs/vases/explosions (world
        coords) and HUD (screen coords) are painted by the arenaGUI/arenaSYS
        weapons, which have no NPC/player anchor. Draw the under-player band,
        then the over-player band (vis>=2), so the floor/bombs sit below and
        the HUD on top. (Depth-sorting world bombs against players is a later
        refinement.)"""
        wimgs = getattr(getattr(self, 'gs1', None), '_weapon_imgs', None)
        if not wimgs:
            return
        for store in list(wimgs.values()):
            self._render_npc_layers(store, over=False)
        for store in list(wimgs.values()):
            self._render_npc_layers(store, over=True)
