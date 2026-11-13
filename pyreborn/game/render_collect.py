"""Entity collection and interpolation mixin."""

from __future__ import annotations

from typing import List, Optional, Tuple

import pygame

from reborn_protocol.coords import local_to_world, segment_origin

from .. import ground_items
from ..gmap_coords import grid_index
from ..attachments import sync_attachment, npc_position, attachment_z
from ..classic_sprites import draw_sprite
from ..npc_handler import CHARACTER_IMAGE
from .constants import TILE_SIZE
from .frame_context import FrameContext
from .render_shared import (
    BaddySheet, _BADDY_DEFAULT_IMAGE, _BADDY_IMAGES, _Entity,
)
from .clocked import ClockedMixin


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


class EntityCollectMixin(ClockedMixin):
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
        # TLevelObject.cpp:64; unsorted.cpp:2248: equal ground depth sorts by z.
        entities.sort(key=lambda e: (e.band, e.depth, e.z))

        renderers = self._ENTITY_RENDERERS
        for ent in entities:
            renderers[ent.kind](self, ent, frame)

        self._render_weapon_layers()

    # -- entity pass: resolve ------------------------------------------------

    def _resolve_frame_gmap(self, frame: FrameContext) -> None:
        """Snapshot the gmap lookups the collectors need: level name -> grid
        cell (which the remote-player loop used to rescan per player), and the
        current segment's world origin (which local-coord entities fold in).
        A name that occupies two cells resolves to the first, like every
        other lookup (see gmap_coords.grid_of)."""
        grid = self.client.gmap_grid
        if not grid:
            return
        frame.level_to_grid = grid_index(grid)
        seg = frame.level_to_grid.get(self.client.current_level_name)
        if seg is not None:
            frame.segment_offset = segment_origin(*seg)

    def _world_pos_for_level(self, local_x: float, local_y: float,
                             level_name: str, frame: FrameContext):
        """World position of a wire (level-local) position in `level_name`.
        Prefer the entity's own level; if that's unset or unknown, assume the
        same sub-level as the local player. Off a gmap there is no grid and
        the local coords already are world coords."""
        grid = frame.level_to_grid.get(level_name) if level_name else None
        if grid is None:
            grid = frame.level_to_grid.get(self.client.current_level_name)
        if grid is None:
            return local_x, local_y
        return local_to_world(local_x, local_y, *grid)

    def _interpolated(self, key, x: float, y: float, *, snap: bool = False,
                      owner=None):
        """Draw position of `key` between the last two ticks (presentation
        only; game/interpolation.py). Without an interpolator (a light test
        harness) the live position."""
        interpolator = self.interpolator
        if interpolator is None:
            return x, y
        return interpolator.position(key, (x, y), self.clock.tick,
                                     self.clock.alpha, snap=snap, owner=owner)

    def _interpolate_other_player(self, pid, world_x: float, world_y: float,
                                  frame: FrameContext):
        """Draw position of a remote player between the last two ticks; the
        first time a pid is seen, where it is."""
        position = self._interpolated(('player', pid), world_x, world_y)
        self.other_player_visual[pid] = position
        return position

    def _interpolate_npc(self, npc_id, npc: dict, nx: float, ny: float,
                         frame: FrameContext):
        """Draw position of an NPC between the last two ticks, EXCEPT when
        client.py just re-stamped its world_x/world_y for a reason other than
        it actually moving (gmap re-attribution, cache restore on level
        re-entry, initial stream - see client.py's _mark_npc_pos_snap/
        _pos_epoch). Sliding across one of those jumps is what made lights
        visibly "swoop into position" on level entry; snap instead, same as a
        brand-new npc_id.

        A stale leftover epoch entry for a since-removed npc_id is harmless:
        client.py's epoch counter only increases and is never reused, so it
        can never collide with a future npc_id's real epoch and suppress a
        snap."""
        if npc_id in frame.npc_positions:
            return frame.npc_positions[npc_id]
        epoch_seen = self._npc_visual_epoch
        if epoch_seen is None:
            epoch_seen = self._npc_visual_epoch = {}
        epoch = npc.get('_pos_epoch')
        snap = npc_id in epoch_seen and epoch != epoch_seen.get(npc_id)
        position = self._interpolated(('npc', npc_id), nx, ny, snap=snap)
        self.npc_visual[npc_id] = position
        epoch_seen[npc_id] = epoch
        if len(epoch_seen) > 2000:
            epoch_seen.clear()
        frame.npc_positions[npc_id] = position
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
        ages = ground_items.item_ages(self, level_name, items, self.clock.sim_now())
        shadow = draw_sprite(self.sprite_mgr, 0x2a)
        # Item keys are level-local while the camera and every depth key use
        # world coordinates. Folding only the blit reproduces the live failure
        # where an item draws beside the player but sorts as if in segment zero.
        for (ix, iy), item_type in items.items():
            age = ages[(ix, iy)]
            # Presentation only (TServerExtra::draw): the server still owns
            # removal, so an expired or blink-off item is just not drawn.
            if ground_items.item_expired(age) or ground_items.item_blink_hidden(age):
                continue
            sprite = self._get_item_sprite(item_type)
            world_x, world_y = ix + origin_x, iy + origin_y
            # Item stores carry no Z, so yBase = world_y + 1. Native sprite
            # dimensions set both offsets; the shadow stays on the ground:
            # Preagonal/FourPlay/quattroplay/src/TServerExtra.cpp:41-74.
            width, height = sprite.get_size()
            half_height = height / (2 * TILE_SIZE)
            y_base = world_y + 1.0
            sx, sy = self._world_to_screen(
                world_x + 1.0 - width / (2 * TILE_SIZE),
                y_base - half_height - ground_items.item_bob_tiles(age))
            shadow_x, shadow_y = self._world_to_screen(
                world_x + 0.5, y_base + half_height - 0.5)
            zoom = getattr(self.camera, 'zoom', 1.0)
            bounds = [(sx, sy, width * zoom, height * zoom)]
            if shadow is not None:
                bounds.append((shadow_x, shadow_y,
                               shadow.get_width() * zoom, shadow.get_height() * zoom))
            if not any(x + w >= 0 and x <= surf_w and y + h >= 0 and y <= surf_h
                       for x, y, w, h in bounds):
                continue
            # The order point is ground y+2, independent of bob/sprite size:
            # Preagonal/FourPlay/quattroplay/src/TServerExtra.cpp:20-28.
            out.append(_Entity('item', self._depth_sort_key(
                world_y, 2.0), sx, sy, (sprite, shadow, shadow_x, shadow_y)))

    def _collect_local_player(self, out: List["_Entity"],
                              frame: FrameContext) -> None:
        """The local player, drawn through the camera at its true render-frame
        top-left (set by _sync_camera) — the same transform every other entity
        uses — so it stays correct under zoom and the camera can aim at the
        body centre without dragging the sprite off its real position. Never
        culled."""
        # TPlayer.cpp:8097: only mode 2 suppresses the player's draw object.
        if getattr(self.client, 'ghost_mode', 0) == 2 or getattr(self.client, 'local_level_transition', ''):
            return
        # Depth-sort key must be in the SAME frame as every other entity
        # (world tiles). visual_y is already world-frame.
        npc = sync_attachment(self.client, self.client.player)
        if npc is not None:
            vx, vy = self._attached_visual(self.client.player, npc, frame)
            px, py = self.camera.world_to_screen(vx, vy - attachment_z(self.client, self.client.player))
            depth = vy
        else:
            px, py = self.camera.world_to_screen(*self._player_render_pos)
            depth = self.visual_y
        out.append(_Entity('player', self._depth_sort_key(depth, 3.0),
                           px, py, self.client.player,
                           z=attachment_z(self.client, self.client.player)))

    def _attached_visual(self, player, npc, frame):
        data = player if isinstance(player, dict) else vars(player)
        npc_id = data['_attachment']['npc_id']
        nx, ny = npc_position(npc)
        vx, vy = self._interpolate_npc(npc_id, npc, nx, ny, frame)
        return vx + data['x'] - nx, vy + data['y'] - ny

    def _collect_other_players(self, out: List["_Entity"],
                               frame: FrameContext) -> None:
        for pid, pdata in self.client.players.items():
            npc = sync_attachment(self.client, pdata)
            ox, oy = pdata.get('x'), pdata.get('y')
            if ox is None or oy is None:
                continue
            if npc is not None:
                vx, vy = self._attached_visual(pdata, npc, frame)
                self.other_player_visual[pid] = (vx, vy)
            else:
                # world_x/world_y: local + that player's own segment, set
                # by the PLO_OTHERPLPROPS handler once the segment is known.
                world_x, world_y = pdata.get('world_x'), pdata.get('world_y')
                if world_x is None or world_y is None:
                    world_x, world_y = self._world_pos_for_level(
                        ox, oy, pdata.get('level', ''), frame)
                vx, vy = self._interpolate_other_player(pid, world_x, world_y, frame)
            z = attachment_z(self.client, pdata)
            # TGaniObject.cpp:2270: all attached gani parts use the raised base.
            sx, sy = self.camera.world_to_screen(vx, vy - z)
            draw_y = sy if npc is not None else sy - pdata.get('z', 0) * self.camera.scale
            if self._entity_on_screen(sx, draw_y, screen_size=frame.screen_size):
                out.append(_Entity('other', self._depth_sort_key(vy, 3.0),
                                   sx, sy, pdata, pid, z=z))

    def _collect_npcs(self, out: List["_Entity"],
                      frame: FrameContext) -> None:
        for npc_id, npc in self.client.npcs.items():
            npc_level = npc.get('_level')
            if (npc_level and not self.client.in_gmap_segment and
                    npc_level != self.client.current_level_name):
                continue
            # Prefer world coords (converted from local + grid offset)
            nx = npc.get('world_x', npc.get('x'))
            ny = npc.get('world_y', npc.get('y'))
            if nx is None or ny is None:
                continue
            vx, vy = self._interpolate_npc(npc_id, npc, nx, ny, frame)
            sx, sy = self.camera.world_to_screen(vx, vy)
            draw_w, draw_h = self._npc_draw_size(npc)
            draw_y = sy - npc.get('z', 0) * self.camera.scale
            if self._entity_on_screen(sx, draw_y, width=draw_w, height=draw_h,
                                      screen_size=frame.screen_size):
                out.append(_Entity('npc', self._depth_sort_key(
                    vy, self._npc_height_tiles(npc)), sx, sy, npc, npc_id,
                    _npc_draw_band(npc.get('draw_layer')), npc.get('z', 0)))
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
        """Collect the current level's baddies in folded world coordinates."""
        level_name, origin_x, origin_y = self._current_segment_info()
        for bid, baddy in self.client.baddies_in_level(level_name).items():
            bx = baddy.get('x')
            by = baddy.get('y')
            if bx is None or by is None:
                continue
            wx, wy = self._interpolated(('baddy', level_name, bid),
                                        bx + origin_x, by + origin_y)
            sx, sy = self.camera.world_to_screen(wx, wy)
            if self._entity_on_screen(sx, sy, screen_size=frame.screen_size):
                out.append(_Entity('baddy', self._depth_sort_key(
                    wy, self._baddy_height_tiles(baddy)), sx, sy, baddy, bid))

    def _collect_horses(self, out: List["_Entity"],
                        frame: FrameContext) -> None:
        """Collect the current level's horses in folded world coordinates."""
        level_name, origin_x, origin_y = self._current_segment_info()
        for hkey, horse in self.client.horses_in_level(level_name).items():
            hx = horse.get('x')
            hy = horse.get('y')
            if hx is None or hy is None:
                continue
            wx, wy = hx + origin_x, hy + origin_y
            sx, sy = self.camera.world_to_screen(wx, wy)
            if self._entity_on_screen(sx, sy, screen_size=frame.screen_size):
                out.append(_Entity('horse', self._depth_sort_key(
                    wy, self._horse_height_tiles(horse)), sx, sy, horse, hkey))

    def _collect_deferred_world(self, out: List["_Entity"],
                                frame: FrameContext) -> None:
        """Move bombs, arrows, thrown objects and explosions into layer 1 so
        their world depth competes with characters, instead of covering the
        whole entity pass. Each entry is the deferred draw call itself; the
        screen position is already inside it, so x/y here go unused."""
        for draw, depth in frame.world_draws:
            out.append(_Entity('deferred_world', depth, 0.0, 0.0, draw))
        frame.world_draws.clear()

    def _collect_showimg_layers(self, out: List["_Entity"],
                                frame: FrameContext) -> None:
        """Collect the vis-1 world layers into the character depth band.

        A layer object inherits the level-object base
        (Preagonal/FourPlay/quattroplay/src/TShowImg.cpp:49) and NPC
        collection appends each one to the SAME draw list the player, the NPC
        bodies and the baddies live in (TServerNPC.cpp:1949-1955,
        TShowImg.cpp:710, TPlayer.cpp:3550). That list is sorted once, whole
        (TPlayer.cpp:3640-3642, 3651-3670) - there is no nested per-NPC pass.
        setLayer maps vis 1 onto layer 0, the body layer (TShowImg.cpp:321-344,
        TLevelObject.cpp:17, TServerPlayer.cpp:524, TServerNPC.cpp:1110), and a
        layer's order point is its own bottom edge (TShowImg.cpp:124-125). So a
        vis-1 layer competes with the player by its own Y instead of riding its
        owner's slot."""
        stores = []
        for npc in self.client.npcs.values():
            npc_level = npc.get('_level')
            if (npc_level and not self.client.in_gmap_segment and
                    npc_level != self.client.current_level_name):
                continue  # the level filter _collect_npcs applies to bodies
            imgs = npc.get('imgs')
            if imgs and npc.get('visible') is not False:
                stores.append(imgs)
        for player in self.client.players.values():
            if player.get('imgs') and player.get('level', self.client.level) == self.client.level:
                stores.append(player['imgs'])
        weapon_imgs = getattr(getattr(self, 'gs1', None), '_weapon_imgs', None)
        if weapon_imgs:
            stores.extend(list(weapon_imgs.values()))

        for imgs in stores:
            # The (vis, index) walk _render_npc_layers uses. The depth sort is
            # stable, so two layers whose bottoms land on one world row keep
            # that stratum order.
            for idx in sorted(imgs,
                              key=lambda i: (imgs[i].get('vis', 4), i)):
                rec = imgs[idx]
                if (rec.get('vis', 4) != 1
                        or rec.get('visible') is False
                        or self._layer_is_gui(rec)):
                    continue
                placed = self._layer_place_for_sort(rec, frame.screen_size)
                if placed is None:
                    continue
                depth, sx, sy = placed
                out.append(_Entity('showimg', depth, sx, sy, rec))

    # -- entity pass: draw --------------------------------------------------

    def _draw_chest_entity(self, ent: "_Entity", frame: FrameContext) -> None:
        self.screen.blit(ent.data, (int(ent.x), int(ent.y)))

    def _draw_item_entity(self, ent: "_Entity", frame: FrameContext) -> None:
        sprite, shadow, shadow_x, shadow_y = ent.data
        zoom = getattr(self.camera, 'zoom', 1.0)
        # Shadow first, then item: TServerExtra.cpp:63-74.
        for surface, x, y in ((shadow, shadow_x, shadow_y),
                              (sprite, ent.x, ent.y)):
            if surface is None:
                continue
            if zoom != 1.0:
                surface = pygame.transform.scale(surface, (
                    max(1, round(surface.get_width() * zoom)),
                    max(1, round(surface.get_height() * zoom))))
            self.screen.blit(surface, (int(x), int(y)))

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

    def _draw_deferred_world_entity(self, ent: "_Entity",
                                    frame: FrameContext) -> None:
        ent.data()

    def _draw_showimg_entity(self, ent: "_Entity",
                             frame: FrameContext) -> None:
        self._render_layer_rec(ent.data)

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
        ('showimg', _collect_showimg_layers, _draw_showimg_entity),
        ('deferred_world', _collect_deferred_world,
         _draw_deferred_world_entity),
    )
    _ENTITY_RENDERERS = {kind: render
                         for kind, _collect, render in _ENTITY_PASSES}

    def _render_weapon_layers(self) -> None:
        """Weapon image layers — the arena bombs/vases/explosions (world
        coords) and HUD (screen coords) are painted by the arenaGUI/arenaSYS
        weapons, which have no NPC/player anchor. Draw the under-player band,
        then the over-player band (vis>=2), so vis 0 stays below and the HUD
        stays on top. Vis 1 is drawn by the entity depth sort."""
        wimgs = getattr(getattr(self, 'gs1', None), '_weapon_imgs', None)
        if not wimgs:
            return
        for store in list(wimgs.values()):
            self._render_npc_layers(store, over=False)
        for store in list(wimgs.values()):
            self._render_npc_layers(store, over=True)
