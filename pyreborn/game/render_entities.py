"""EntityRenderMixin — players, NPCs, speech bubbles, animated sprites.

Split from render.py; methods operate on the GameClient instance."""

import math
import time
from typing import Any, List, NamedTuple, Optional, Tuple

import pygame

from reborn_protocol.coords import local_to_world, segment_origin

from ..gani import AnimationState
from ..npc_handler import CHARACTER_IMAGE
from ..player import Player
from ..sprites import palette_name_to_index
from .assets import render_outlined_text
from .frame_context import FrameContext, FrameContextMixin
from .constants import (
    TILE_SIZE, parse_npc_visual_effects,
    PLAYER_COLLISION_LEFT, PLAYER_COLLISION_RIGHT,
    PLAYER_COLLISION_TOP, PLAYER_COLLISION_BOTTOM,
    PLAYER_STAND_X, PLAYER_STAND_Y,
)


class _Entity(NamedTuple):
    """One drawable collected by an entity pass, before depth sorting.

    `depth` is the image's bottom edge in world tiles (_depth_sort_key), so a
    single stable sort across every kind reproduces the old per-kind draw
    order for ties. `key` is the collection's id -- player id, npc id, baddy
    id, horse key -- and is None for the local player, which has no entry."""

    kind: str
    depth: float
    x: float
    y: float
    data: Any
    key: Any = None


def _c255(v: float) -> int:
    """Clamp a 0..1 GS1 colour/alpha multiplier to a 0..255 byte."""
    return max(0, min(255, int(float(v) * 255)))


# findimg(i).red/.green/.blue/.alpha — the GS2 way of tinting a scripted
# layer. GS1's changeimgcolors packs all four into rec['colors'] at once;
# GS2 scripts instead assign the channels one at a time on the image object
# (gs2_client._LayerImage passes unknown property names straight through to
# the same record), so the values land as separate keys that no renderer
# read. Zelda's -Player/Movement puts up its hurt-flash quad that way:
#
#     showpoly(2000, {0,0,screenwidth,0,screenwidth,screenheight,0,screenheight});
#     findimg(2000).red = 1; findimg(2000).blue = findimg(2000).green = 0;
#     findimg(2000).alpha = 0;                    // invisible until hurt
#
# (Preagonal/graal-lttp weapons/weapon-Player_Movement.txt:155-160, and it
# ramps .alpha up in onTimeout when the player takes damage).
# With the channels ignored the quad fell back to opaque white and filled the canvas.
_LAYER_COLOR_KEYS = ("red", "green", "blue", "alpha")

# ATTRn sprite-layer slots a character gani can address (ATTR1..ATTR5, fed by
# PLPROP_GATTRIB1..5 / #P1..#P5).
ATTR_SLOTS = 5


def _layer_colors(rec: dict):
    """(r, g, b, a) 0..1 multipliers for a scripted layer, or None if the
    script never coloured it.

    changeimgcolors' packed rec['colors'] wins when present; otherwise any
    per-channel findimg() assignment is honoured, with the engine's default
    of 1.0 for the channels the script left alone."""
    colors = rec.get('colors')
    if colors:
        return colors
    if not any(k in rec for k in _LAYER_COLOR_KEYS):
        return None
    out = []
    for k in _LAYER_COLOR_KEYS:
        try:
            out.append(float(rec.get(k, 1.0)))
        except (TypeError, ValueError):
            out.append(1.0)
    return tuple(out)


# Perceptual attenuation for changeimgmode-2 (subtractive) showimg layers.
# 1.0 = arithmetically faithful subtraction, which black-clamps the scene
# under opaque near-white smoke textures (the bomber lobby's
# eye_bomb_blackhole* 5x5 grid subtracts ~(163,222,213) from a ~129-lum
# scene, clamping ~half the smoke region to 0). 0.4 keeps the level dim but
# readable; taste band is 0.3 (brighter) .. 0.5 (moodier).
SUBTRACT_SMOKE_SCALE = 0.4


# Baddy mode (BDMODE) -> gani animation name. Mirrors GServer-v2's BaddyMode
# enum. The C# client renders baddies as gani entities rather than blitting a raw
# sprite sheet, so we drive the animation from the server-reported mode: they
# walk while hunting, recoil when hurt, and flop over when dead.
_BADDY_MODE_GANI = {
    0: "walk",   # WALK
    1: "idle",   # LOOK
    2: "walk",   # HUNT
    3: "hurt",   # HURT
    4: "hurt",   # BUMPED
    5: "dead",   # DIE
    6: "walk",   # SWAMPSHOT
    7: "walk",   # HAREJUMP
    8: "walk",   # OCTOSHOT
    9: "dead",   # DEAD
}

# Per-type head over body.png, the way the C# client's classic_baddy_graanch ganis
# dress a baddy as a humanoid (head19.png + body.png). Keyed by the canonical
# GServer-v2 BaddyType so the ten stock baddies read as distinct enemies.
# NOTE: this table (and the gani-based render path below it) is now only a
# last-resort fallback for when a baddy's own sprite sheet (see _BADDY_IMAGES
# / BaddySheet) can't be loaded at all - real classic baddies are NOT
# humanoids dressed in head/body.png (verified by inspecting the actual
# sheets: baddygray.png etc. are an armored roll-up creature, baddyoctopus.png
# an octopus, baddyhare.png a frog/hare face - nothing like a soldier).
_BADDY_HEADS = {
    0: "head19.png",  # graysoldier
    1: "head20.png",  # bluesoldier
    2: "head22.png",  # redsoldier
    3: "head20.png",  # shootingsoldier
    4: "head17.png",  # swampsoldier
    5: "head14.png",  # frog / hare
    6: "head9.png",   # octopus
    7: "head23.png",  # goldenwarrior
    8: "head24.png",  # lizardon
    9: "head25.png",  # dragon
}
_BADDY_DEFAULT_HEAD = "head19.png"

# Type -> default sprite sheet (GServer-v2 BaddyType), used when the server
# doesn't send an explicit BDPROP_POWERIMAGE image name. Ships in
# assets/baddies/ (see game/setup.py _setup_asset_paths); a server-downloaded
# copy of the same filename still wins if the server streams one (SpriteManager
# caches by filename regardless of which search path it came from).
_BADDY_IMAGES = {
    0: "baddygray.png",     # graysoldier
    1: "baddyblue.png",     # bluesoldier
    2: "baddyred.png",      # redsoldier
    3: "baddyblue.png",     # shootingsoldier
    4: "baddygray.png",     # swampsoldier
    5: "baddyhare.png",     # frog / hare
    6: "baddyoctopus.png",  # octopus
    7: "baddygold.png",     # goldenwarrior
    8: "baddylizardon.png", # lizardon
    9: "baddydragon.png",   # dragon
}
_BADDY_DEFAULT_IMAGE = "baddygray.png"

# BDMODE (see packets.parse_baddy_props) grouped into the three sheet rows a
# classic baddy PNG actually carries (see BaddySheet below): walking modes
# animate between the sheet's two walk frames, hurt/bumped hold a single
# recoil frame, die/dead hold a single "final" frame.
_BADDY_HURT_MODES = frozenset({3, 4})   # HURT, BUMPED
_BADDY_DEAD_MODES = frozenset({5, 9})   # DIE, DEAD
# Everything else (WALK, LOOK, HUNT, SWAMPSHOT, HAREJUMP, OCTOSHOT) animates
# the walk frames - classic baddy art doesn't dedicate a distinct pose to
# those per-type "special attack" modes (confirmed empirically: the row that
# would hold one, e.g. baddyoctopus.png's row 2, is really just a 3rd walk
# variant only drawn for the left/right columns - see the recon contact
# sheets), so treating them identically to WALK is both simpler and correct.

# Row indices within a BaddySheet 4x4 grid (see BaddySheet's docstring for how
# these were derived empirically from the actual PNGs).
_BADDY_ROW_HURT = 2
_BADDY_ROW_DEAD = 3


class BaddySheet:
    """Slices a classic baddy PNG (baddygray.png, baddyoctopus.png, ...) into
    per-direction/mode frames.

    Derived empirically (see the contact-sheet recon this task's evidence is
    based on - every 128-wide sheet sliced cleanly into a 4x4 grid of the same
    aspect once GServer-v2's own body.png convention - column = direction, in
    the standard up/left/down/right order - was applied): 4 columns of
    `width/4` px, 4 rows of `height/4` px. baddyhare.png (32x32) is the
    exception: a single frame reused for every mode/direction.

    Row semantics (see the module-level _BADDY_HURT_MODES/_BADDY_DEAD_MODES
    comment): row 0/1 are the two walk frames, row 2 is a hurt/recoil pose,
    row 3 is a final "dead" pose (for baddygray-style sheets this is a
    fully-curled ball; for baddyoctopus it's often blank for the up/down
    columns, since front/back needed no distinct death art - handled by
    _frame_for climbing back down to a populated row).

    The RIGHT direction's sheet column is unreliable across sheets - some
    (baddygray/gold/lizardon) reuse it in rows 1-2 for an unrelated vertical
    blood-decal asset rather than a right-facing pose - so RIGHT is always
    synthesized by horizontally flipping the LEFT column instead of reading
    column 3 (confirmed safe: where column 3 IS genuine right-facing art,
    e.g. baddyoctopus row 0, it's already a mirror of column 1).

    Background pixels: the classic PNGs carry a palette transparency index
    (verified per-file with PIL - each has its own `transparency` index, not
    a fixed RGB) that SpriteManager/pygame already resolves into alpha=0 via
    convert_alpha() in load_sheet()/get_sprite() - no extra colorkey handling
    needed here.
    """

    _DIRECTION_COLS = {0: 0, 1: 1, 2: 2}  # up, left, down -> sheet column
    _BLANK_ALPHA_FRACTION = 0.92  # frame is "no art" if >=92% transparent

    def __init__(self, sprite_mgr, image: str):
        self.sprite_mgr = sprite_mgr
        self.image = image
        self._blank_cache: dict = {}
        self._mirror_cache: dict = {}

    def _sheet_layout(self, sheet):
        """(frame_w, frame_h, single) for the loaded sheet surface."""
        w, h = sheet.get_size()
        if w <= 32 and h <= 32:
            return w, h, True
        return w // 4, h // 4, False

    def _raw_frame(self, row: int, col: int):
        sheet = self.sprite_mgr.load_sheet(self.image)
        if sheet is None:
            return None
        fw, fh, single = self._sheet_layout(sheet)
        if single:
            row = col = 0
        return self.sprite_mgr.get_sprite(self.image, col * fw, row * fh, fw, fh)

    def _is_blank(self, row: int, col: int) -> bool:
        key = (row, col)
        cached = self._blank_cache.get(key)
        if cached is not None:
            return cached
        sprite = self._raw_frame(row, col)
        if sprite is None:
            return True
        w, h = sprite.get_size()
        step = 2 if w * h > 256 else 1
        total = transparent = 0
        for py in range(0, h, step):
            for px in range(0, w, step):
                total += 1
                if sprite.get_at((px, py))[3] == 0:
                    transparent += 1
        blank = total == 0 or (transparent / total) >= self._BLANK_ALPHA_FRACTION
        self._blank_cache[key] = blank
        return blank

    def frame(self, row: int, direction: int):
        """The frame for `row` (0-3) and `direction` (0-3, up/left/down/right),
        falling back to the nearest populated row above it (see class
        docstring) and synthesizing RIGHT by flipping LEFT. None if the sheet
        itself hasn't loaded (caller should request it and stay invisible)."""
        sheet = self.sprite_mgr.load_sheet(self.image)
        if sheet is None:
            return None
        _, _, single = self._sheet_layout(sheet)
        if single:
            return self._raw_frame(0, 0)

        mirror = direction == 3
        col = 1 if mirror else self._DIRECTION_COLS.get(direction, 1)
        r = max(0, min(row, 3))
        while r > 0 and self._is_blank(r, col):
            r -= 1

        if mirror:
            key = (r, col)
            flipped = self._mirror_cache.get(key)
            if flipped is None:
                base = self._raw_frame(r, col)
                if base is None:
                    return None
                flipped = pygame.transform.flip(base, True, False)
                self._mirror_cache[key] = flipped
            return flipped
        return self._raw_frame(r, col)


class EntityRenderMixin(FrameContextMixin):
    """Mixin providing the above methods for GameClient."""

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
        entities.sort(key=lambda e: e.depth)

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
                    vy, self._npc_height_tiles(npc)), sx, sy, npc, npc_id))
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
        fold in that segment's gmap offset to line them up with the world."""
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

    def _render_baddy(self, x: float, y: float, baddy: dict, baddy_id: int):
        """Render a baddy from its own classic sprite sheet (baddygray.png,
        baddyoctopus.png, ...) - see BaddySheet. The server-reported mode
        picks walk/hurt/dead, direction picks the column, and the type (or an
        explicit BDPROP_POWERIMAGE image) picks which sheet. Falls back to the
        old gani head-over-body composite only if the sheet can't be loaded."""
        mode = baddy.get('mode', 2)
        direction = baddy.get('direction', 2)
        btype = baddy.get('type', 0)
        image = baddy.get('image') or _BADDY_IMAGES.get(btype, _BADDY_DEFAULT_IMAGE)

        sheet = self.baddy_sheets.get(image)
        if sheet is None:
            sheet = BaddySheet(self.sprite_mgr, image)
            self.baddy_sheets[image] = sheet

        if mode in _BADDY_DEAD_MODES:
            row = _BADDY_ROW_DEAD
        elif mode in _BADDY_HURT_MODES:
            row = _BADDY_ROW_HURT
        else:
            # Walk family: alternate the sheet's 2 walk frames. Prefer the
            # server's own BDPROP_ANI index (so it stays in lockstep with
            # whatever pace the server animates at); fall back to a local
            # ~4fps clock for servers that never send it.
            ani = baddy.get('animation')
            row = int(ani) % 2 if ani is not None else int(time.time() * 4) % 2

        frame = sheet.frame(row, direction)
        if frame is not None:
            # Hurt baddies blink so a hit reads even when the mode reverts fast
            # (mirrors the old gani path's behavior).
            if mode == 3 and int(time.time() * 10) % 2 == 0:
                return
            self.screen.blit(frame, (x, y))
            return

        # The sheet isn't available at all (missing from assets/baddies/ and
        # never streamed by the server) - ask for it, and fall back to the
        # legacy gani head-over-body composite as a last resort rather than
        # leaving the baddy invisible.
        self._request_asset(image)

        gani_name = (baddy.get('gani') or baddy.get('ani')
                     or _BADDY_MODE_GANI.get(mode, "walk"))
        anim = self.baddy_anims.get(baddy_id)
        if anim is None:
            anim = AnimationState(self.gani_parser)
            self.baddy_anims[baddy_id] = anim
        anim.set_animation(gani_name, direction)

        if anim.gani is not None:
            if mode == 3 and int(time.time() * 10) % 2 == 0:
                return
            head = _BADDY_HEADS.get(btype, _BADDY_DEFAULT_HEAD)
            # This legacy composite borrows player character ganis (walk/
            # hurt/dead), which centre the body at canvas x+8; the sheet path
            # above blits the baddy at raw (x, y). Shift the canvas 8px left
            # so the fallback body lands where the sheet frames would.
            self._render_animated_entity(x - (48 - TILE_SIZE * 2) // 2, y, anim,
                                         {'head_image': head, 'body_image': 'body.png'})
            return

        self._request_asset(gani_name + '.gani')
    def _render_horse(self, x: float, y: float, horse: dict, key):
        """Render a horse placed by another player (PLO_HORSEADD). Uses the
        shared 'horse' gani if it's available (see assets search path in
        game/setup.py); falls back to the raw image sheet, then a placeholder
        rect so a horse is never silently invisible."""
        anim = self.horse_anims.get(key)
        if anim is None:
            anim = AnimationState(self.gani_parser)
            self.horse_anims[key] = anim
        direction = horse.get('direction', 2)
        anim.set_animation('horse', direction)

        image = horse.get('image') or 'horse.png'
        if anim.gani is not None:
            self._render_animated_entity(x, y, anim, {'horse_image': image})
            return

        sprite = self.sprite_mgr.load_sheet(image)
        if sprite:
            self.screen.blit(sprite, (x, y))
        else:
            self._request_asset(image)
            if self.debug_mode:
                self.screen.blit(self.npc_placeholder, (x, y))

    # _render_speech_bubble centres its bubble at x+16 (one tile), which fits
    # a 2-tile-wide NPC anchored at x. The player's sprite is honestly 3
    # tiles wide per the classic-engine spec (48px GANI canvas == 3 tiles),
    # so its true visual centre is x+1.5 tiles (+24px) — shift the bubble
    # anchor +8px (TILE_SIZE // 2) at player call sites only. NOTE: this no
    # longer feeds _render_animated_entity — gani sprites anchor the frame
    # canvas at the entity's own (x, y) for every entity type (see the
    # anchor note inside _render_animated_entity).
    _PLAYER_ANCHOR_FIX = TILE_SIZE // 2  # 8px: bubble centring for 3-tile-wide players

    # Classic v2.31 draws NPC nicknames in blue (players get white); tunable
    # against a fresh real-client reference if the shade looks off.
    _NPC_NICK_COLOR = (0, 0, 255)

    @staticmethod
    def _attr_equipment(gattribs) -> dict:
        """attr1_image..attr5_image for a player whose gani attributes we know.

        Always returns all five keys, empty string included: an entity whose
        attributes are known owns those slots outright, so an unset attribute
        must draw nothing rather than falling back to the gani's
        DEFAULTATTRn (see _resolve_gani_layers). A value that names no image
        - Bomber stores room-editor data in #P1 - resolves to a missing file
        and draws nothing, which is what the real client does with it.
        """
        return {f'attr{i}_image': str((gattribs or {}).get(i) or '')
                for i in range(1, ATTR_SLOTS + 1)}

    def _render_player(self, x: float, y: float, player: Player,
                       anim: AnimationState,
                       frame: Optional[FrameContext] = None):
        """Render the local player with animation."""
        frame = self._frame_context() if frame is None else frame
        anchor_x = x + self._PLAYER_ANCHOR_FIX  # speech-bubble anchor only
        base_alpha = 115 if self.client.ghost_mode else 255
        alpha = self.combat_presentation.player_alpha(time.monotonic(), base_alpha)
        equip = {
            'body_image': player.body_image or 'body.png',
            'head_image': player.head_image or 'head0.png',
            'sword_image': player.sword_image or 'sword1.png',
            'shield_image': player.shield_image or 'shield1.png',
            # Tier 2a: PLPROP_COLORS (prop 13), parsed into player.colors
            # by packets.py/player.py, drives the body palette-swap in
            # get_sprite_recolored() (sprites.py).
            'colors': player.colors,
        }
        equip.update(self._attr_equipment(player.gattribs))
        self._render_animated_entity(x, y, anim, equip, alpha=alpha)

        # Render carried object above player's head
        if player.is_carrying():
            self._render_carried_object(x, y, player)

        self._render_player_chat(anchor_x, y)

        # Render nickname below local player
        nickname = player.nickname or player.account
        status_label = self._status_label(player.status)
        if status_label:
            nickname = f"{nickname} [{status_label}]" if nickname else f"[{status_label}]"
        if nickname:
            name_surf = self._render_text_outlined_cached(self.font_small, nickname, (255, 255, 255))
            # Centre on the box/sprite's true horizontal centre, x+1.5 tiles
            # (24px) — the sprite is 3 tiles wide, top-left anchored at x.
            name_x = x - name_surf.get_width() // 2 + int(TILE_SIZE * 1.5)
            name_y = y + 48
            name_x, name_y = self._place_nameplate(name_x, name_y,
                                                   name_surf.get_size(), frame)
            self.screen.blit(name_surf, (name_x, name_y))

        # Debug visualization (feet marker, collision box, tile grid) - F1 only
        if self.debug_mode:
            # Entity position (x, y) is TOP-LEFT of the 3x3-tile sprite.
            # Ground-sample point is the standing point between the feet:
            # +1.5 tiles right, +2.5 tiles down (collision.py's
            # PLAYER_FEET_DX/DY — the point chairs/pickups/signs interact
            # against and swim/grass/etc are sampled at), not the box's
            # bottom edge.
            feet_x = x + TILE_SIZE * PLAYER_STAND_X
            feet_y = y + TILE_SIZE * PLAYER_STAND_Y

            # Current position marker (red dot at the ground-sample centre)
            pygame.draw.circle(self.screen, (255, 0, 0), (int(feet_x), int(feet_y)), 4)

            # True collision box: 2x2 tiles centred above the standing point,
            # spanning x+0.5..x+2.5 by y+1.0..y+3.0 (collision.py's
            # _FEET_LEFT/_FEET_RIGHT/_FEET_TOP/_FEET_BOTTOM).
            box_left = x + TILE_SIZE * PLAYER_COLLISION_LEFT
            box_right = x + TILE_SIZE * PLAYER_COLLISION_RIGHT
            box_top = y + TILE_SIZE * PLAYER_COLLISION_TOP
            box_bottom = y + TILE_SIZE * PLAYER_COLLISION_BOTTOM
            collision_rect = pygame.Rect(
                int(box_left), int(box_top),
                int(box_right - box_left), int(box_bottom - box_top)
            )
            pygame.draw.rect(self.screen, (0, 255, 0), collision_rect, 2)

            # Tile grid around player feet
            feet_world_x = self.client.x + PLAYER_STAND_X
            feet_world_y = self.client.y + PLAYER_STAND_Y
            tile_offset_x = (feet_world_x - int(feet_world_x)) * TILE_SIZE
            tile_offset_y = (feet_world_y - int(feet_world_y)) * TILE_SIZE
            for ty in range(-3, 2):
                for tx in range(-2, 3):
                    grid_x = int(feet_x - tile_offset_x + tx * TILE_SIZE)
                    grid_y = int(feet_y - tile_offset_y + ty * TILE_SIZE)
                    grid_rect = pygame.Rect(grid_x, grid_y, TILE_SIZE, TILE_SIZE)
                    pygame.draw.rect(self.screen, (255, 255, 255, 128), grid_rect, 1)
    def _render_carried_object(self, x: float, y: float, player: Player):
        """Render the 2x2 object the player is carrying above their head."""
        if not player.carried_tile_ids:
            return

        tile_ids = player.carried_tile_ids
        # Render 2x2 tiles above player's head
        # Each tile is TILE_SIZE, so 2x2 = 2*TILE_SIZE x 2*TILE_SIZE
        obj_width = TILE_SIZE * 2
        obj_height = TILE_SIZE * 2

        # (x, y) is the sprite's top-left; the sprite is 3 tiles wide (true
        # centre at x + TILE_SIZE * 1.5) with the head near the top. Hold the
        # object centered over the head, resting just above it, so the carry
        # gani's raised hands read as holding each side of the object.
        # (Verified centered against dusty's bush by pixel measurement — an
        # apparent lean there is the art's asymmetric transparency letting
        # the head show through one quadrant, not a placement offset.)
        obj_x = (x + TILE_SIZE * 1.5) - obj_width // 2
        obj_y = y - obj_height + 8

        # Render the 4 tiles
        positions = [(0, 0), (1, 0), (0, 1), (1, 1)]
        for i, (dx, dy) in enumerate(positions):
            if i < len(tile_ids):
                tile_id = tile_ids[i]
                tile_surf = self.tileset_mgr.get_tile_or_color(tile_id)
                tile_x = obj_x + dx * TILE_SIZE
                tile_y = obj_y + dy * TILE_SIZE
                self.screen.blit(tile_surf, (tile_x, tile_y))

    def _split_other_player_anim(self, player_anim: str) -> Tuple[str, List[str]]:
        """Split a `setani ani,param1,param2` comma-joined string into
        (name, params), memoized on the raw string. Other players' anim
        string is static between server updates, so re-splitting it every
        frame per remote player (the original inline code here) is wasted
        work at any real player count; re-parse only when the raw string
        actually changes."""
        cache = getattr(self, '_other_anim_split_cache', None)
        if cache is None:
            cache = self._other_anim_split_cache = {}
        result = cache.get(player_anim)
        if result is None:
            if ',' in player_anim:
                parts = [p.strip() for p in player_anim.split(',')]
                name = parts[0] or 'idle'
                params = parts[1:]
            else:
                name = player_anim
                params = []
            result = (name, params)
            if len(cache) > 300:
                cache.clear()
            cache[player_anim] = result
        return result

    def _render_player_chat(self, anchor_x: float, y: float) -> None:
        """Render or expire the optimistic local CURCHAT bubble."""
        # The server clears other players with a later empty CURCHAT, but does
        # not echo that lifecycle to the setter, so mirror the clear locally.
        if self.local_chat_text:
            chat_text = self.local_chat_text
            if time.time() - self.local_chat_time < self.chat_bubble_duration:
                self._render_speech_bubble(anchor_x, y, chat_text)
            else:
                self.local_chat_text = ""
                # Do not erase a newer chat value installed by another path.
                if self.client.player.chat == chat_text:
                    self.client.player.chat = ""

    def _render_other_player(self, x: float, y: float, pdata: dict, pid: int,
                             frame: Optional[FrameContext] = None):
        """Render another player."""
        frame = self._frame_context() if frame is None else frame
        # Get animation name - could be 'ani' or 'animation'. Tier 2d: a
        # `setani ani,param1,param2` server prop keeps its params comma-joined
        # onto the gani name here; split them off so param images can drive
        # ATTR1-5 layers (e.g. a scripted hat) instead of being discarded.
        player_anim = pdata.get('ani') or pdata.get('animation') or 'idle'
        player_anim, gani_params = self._split_other_player_anim(player_anim)
        # Get direction from sprite prop (lower 2 bits) or direction field
        direction = pdata.get('direction', 2)
        if 'sprite' in pdata:
            direction = pdata['sprite'] & 0x03  # Lower 2 bits = direction

        # Get or create animation state
        if pid not in self.other_player_anims:
            anim = AnimationState(self.gani_parser)
            anim.set_animation(player_anim, direction, params=gani_params)
            self.other_player_anims[pid] = anim

        anim = self.other_player_anims[pid]

        # Update animation if changed. The params are part of "changed": a
        # PARAMn PLAYSOUND (`setani sen_piano_note2,<note>.wav`) re-issues the
        # SAME gani name with a new sound file, and skipping the call here
        # meant the second note never sounded.
        current_name = anim.gani.name if anim.gani else ''
        if (player_anim != current_name or anim.direction != direction
                or anim.params != gani_params):
            anim.set_animation(player_anim, direction, params=gani_params)

        equip = {
            'body_image': pdata.get('body_image', 'body.png'),
            'head_image': pdata.get('head_image', 'head0.png'),
            'sword_image': pdata.get('sword_image', 'sword1.png'),
            'shield_image': pdata.get('shield_image', 'shield1.png'),
            # Tier 2a: PLPROP_COLORS (prop 13), populated by parse_other_player.
            'colors': pdata.get('colors'),
        }
        equip.update(self._attr_equipment(
            {i: pdata.get(f'gattrib{i}') for i in range(1, 6)}))
        for i, p in enumerate(gani_params[:5], start=1):
            if p:
                equip[f'attr{i}_image'] = p
        hidden = bool(int(pdata.get('status') or 0) & 0x02)
        # See _render_player's _PLAYER_ANCHOR_FIX comment: other players are
        # the same honestly-3-tile-wide sprite as the local player, so their
        # speech bubble needs the same +8px anchor shift. The sprite itself
        # anchors at raw (x, y) like every other gani entity.
        anchor_x = x + self._PLAYER_ANCHOR_FIX
        self._render_animated_entity(x, y, anim, equip,
                                     alpha=115 if hidden else 255)

        # Render chat bubble above player (if they have chat text)
        chat_text = pdata.get('chat', '')
        if chat_text:
            self._render_speech_bubble(anchor_x, y, chat_text)

        # Render nickname below player
        nickname = pdata.get('nick') or pdata.get('nickname') or pdata.get('account') or ''
        status_label = self._status_label(pdata.get('status'))
        if status_label:
            nickname = f"{nickname} [{status_label}]" if nickname else f"[{status_label}]"
        if nickname:
            name_surf = self._render_text_outlined_cached(self.font_small, nickname, (255, 255, 255))
            # Center name below player (player sprite is ~48 pixels tall).
            # True horizontal centre is x+1.5 tiles (24px), same as the local
            # player (see _render_player).
            name_x = x - name_surf.get_width() // 2 + int(TILE_SIZE * 1.5)
            name_y = y + 48
            name_x, name_y = self._place_nameplate(name_x, name_y,
                                                   name_surf.get_size(), frame)
            self.screen.blit(name_surf, (name_x, name_y))
    def _place_nameplate(self, name_x: float, name_y: float,
                          size: Tuple[int, int],
                          frame: Optional[FrameContext] = None
                          ) -> Tuple[float, float]:
        """Stagger a nameplate vertically if it would overlap one already
        placed this frame. Two players (or an NPC and a player) standing on
        or near the same tile otherwise draw their nickname at the same
        y-offset, producing garbled overlapping text; nudge each subsequent
        overlapper straight down by one box-height until it clears. The
        already-placed rects live on the frame, so they reset with it."""
        rects = (self._frame_context() if frame is None else frame).nameplate_rects
        w, h = size
        rect = pygame.Rect(int(name_x), int(name_y), int(w), int(h))
        while any(rect.colliderect(r) for r in rects):
            rect.y += h + 2
        rects.append(rect)
        return rect.x, rect.y

    def _render_text_cached(self, font: pygame.font.Font, text: str,
                             color: Tuple[int, int, int]) -> pygame.Surface:
        """Render (and cache) a plain (unoutlined) text surface. Speech
        bubbles re-render the same handful of strings every frame otherwise;
        keying on (font identity, text, color) lets every caller share one
        cache. Cleared wholesale once it grows large so a chat-heavy session
        doesn't leak memory. Fine as-is for bubble text, which already sits on
        a solid white plate -- text drawn straight over the level (nameplates,
        showtext) wants `_render_text_outlined_cached` instead, below."""
        cache = getattr(self, '_text_surf_cache', None)
        if cache is None:
            cache = self._text_surf_cache = {}
        key = (id(font), text, color)
        surf = cache.get(key)
        if surf is None:
            if len(cache) > 500:
                cache.clear()
            surf = cache[key] = font.render(text, True, color)
        return surf

    def _render_text_outlined_cached(self, font: pygame.font.Font, text: str,
                                      color: Tuple[int, int, int],
                                      outline_color: Tuple[int, int, int] = (0, 0, 0)
                                      ) -> pygame.Surface:
        """Outlined sibling of `_render_text_cached`, for text drawn straight
        over the level (nameplates, NPC showtext) rather than inside a
        solid-colour bubble/box -- a flat fill (even with a 1px drop shadow)
        all but vanishes against busy/dark level art. See
        assets.render_outlined_text for the actual stamping."""
        cache = getattr(self, '_text_outline_cache', None)
        if cache is None:
            cache = self._text_outline_cache = {}
        key = (id(font), text, color, outline_color)
        surf = cache.get(key)
        if surf is None:
            if len(cache) > 500:
                cache.clear()
            surf = cache[key] = render_outlined_text(font, text, color, outline_color)
        return surf

    def _wrapped_lines(self, text: str) -> List[str]:
        """Word-wrap speech-bubble text into up to 3 lines under ~120px.
        Recomputing this (with a font.render() per word) every frame for the
        same message is wasteful, so cache the wrap result keyed by the full
        text - messages are static once received."""
        cache = getattr(self, '_wrap_cache', None)
        if cache is None:
            cache = self._wrap_cache = {}
        lines = cache.get(text)
        if lines is not None:
            return lines

        max_width = 120
        words = text.split()
        lines = []
        current_line = ""
        for word in words:
            test_line = current_line + (" " if current_line else "") + word
            test_surf = self._render_text_cached(self.font_small, test_line, (0, 0, 0))
            if test_surf.get_width() > max_width and current_line:
                lines.append(current_line)
                current_line = word
            else:
                current_line = test_line
        if current_line:
            lines.append(current_line)
        lines = lines[:3]  # Limit to 3 lines max

        if len(cache) > 300:
            cache.clear()
        cache[text] = lines
        return lines

    def _render_speech_bubble(self, x: float, y: float, text: str):
        """Render a speech bubble above an entity."""
        if not text:
            return

        lines = self._wrapped_lines(text)
        if not lines:
            # Whitespace-only text wraps to no words; nothing to show. Without
            # this guard the max() below crashes the whole render loop, which a
            # remote player sending an all-space chat could trigger for everyone.
            return

        # Calculate bubble dimensions
        line_height = 14
        padding = 4
        bubble_height = len(lines) * line_height + padding * 2
        bubble_width = max(self._render_text_cached(self.font_small, line, (0, 0, 0)).get_width()
                           for line in lines) + padding * 2

        # Position bubble above entity (centered, above head)
        bubble_x = x + 16 - bubble_width // 2
        bubble_y = y - bubble_height - 8

        # Draw bubble background (white with black border)
        pygame.draw.rect(self.screen, (255, 255, 255),
                        (bubble_x, bubble_y, bubble_width, bubble_height))
        pygame.draw.rect(self.screen, (0, 0, 0),
                        (bubble_x, bubble_y, bubble_width, bubble_height), 1)

        # Draw small triangle pointer
        pointer_x = x + 16
        pygame.draw.polygon(self.screen, (255, 255, 255), [
            (pointer_x - 4, bubble_y + bubble_height),
            (pointer_x + 4, bubble_y + bubble_height),
            (pointer_x, bubble_y + bubble_height + 6)
        ])
        pygame.draw.lines(self.screen, (0, 0, 0), False, [
            (pointer_x - 4, bubble_y + bubble_height),
            (pointer_x, bubble_y + bubble_height + 6),
            (pointer_x + 4, bubble_y + bubble_height)
        ], 1)

        # Draw text lines
        for i, line in enumerate(lines):
            text_surf = self._render_text_cached(self.font_small, line, (0, 0, 0))
            text_x = bubble_x + padding
            text_y = bubble_y + padding + i * line_height
            self.screen.blit(text_surf, (text_x, text_y))
    def _request_asset(self, filename: str):
        """Request a missing image/file from the server exactly once."""
        if (not filename or filename in self._requested_assets or
                filename in self.client.failed_files):
            return
        try:
            if self.client.request_file(filename):
                self._requested_assets.add(filename)
        except Exception:
            pass
    def _status_label(self, status) -> str:
        """Tier 3c: resolve a numeric PLPROP_STATUS to a selectable label from
        client.status_list (PLO_STATUSLIST), when it's being used as an index
        into that list. STATUS is more commonly a bitmask (hidden/paused/...)
        on most servers than a status-list index, so an out-of-range value is
        just treated as "no status" rather than guessed at."""
        status_list = self.client.status_list
        if not status_list or status is None:
            return ""
        try:
            idx = int(status)
        except (TypeError, ValueError):
            return ""
        if 0 <= idx < len(status_list):
            return status_list[idx]
        return ""

    def _npc_character_colors(self, npc: dict):
        """Tier 2a for character NPCs: setcharprop #C0-#C4 (gs1_client.py's
        _CHARPROP_NPC) stores 5 palette-index strings on npc['color0'..'4'];
        assemble them into the [skin, coat, sleeves, shoes, belt] list
        recolor_body() expects. Unlike the player-colors path, this one is
        live today (no protocol-layer dependency) - it just had no reader
        until this render wiring."""
        raw = npc.get('colors')
        if raw:
            return [self._palette_slot(v) for v in list(raw)[:5]]
        have_any = False
        vals = []
        for i in range(5):
            v = npc.get(f'color{i}')
            if v is not None:
                have_any = True
            vals.append(self._palette_slot(v))
        return vals if have_any else None

    @staticmethod
    def _palette_slot(v) -> int:
        """A single COLORS slot as a palette index. Wire props carry ints,
        but script writes (GS2 `colors[0] = "orange";`, GS1 setcharprop with
        a name) carry palette NAMES — resolve those through REBORN_PALETTE
        so recolor_body gets the index it expects."""
        try:
            return int(v)
        except (TypeError, ValueError):
            pass
        try:
            return palette_name_to_index(v)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _npc_image(npc: dict, new_key: str, wire_key: str, default: str) -> str:
        """Resolve a character NPC's head/body image, preferring the
        setcharprop-style key (`new_key`, set by the client-side GS1 path -
        gs1_client.py's _CHARPROP_NPC) over the raw wire prop the modern
        server-run GS1 sends instead (`wire_key` - see
        packets.parse_npc_props' HEADIMAGE/_NPC_STRING_KEYS handling). The
        wire prop can rarely be a bare preset-id int rather than a filename
        (HEADIMAGE's marker<100 case); treat that like a missing value."""
        v = npc.get(new_key) or npc.get(wire_key)
        return v if isinstance(v, str) and v else default

    def _split_npc_gani(self, gani_name: str) -> Tuple[str, List[str]]:
        """Split a `setcharani/setani ani,param1,...` comma-joined string into
        (name, params), memoized on the raw string - same rationale as
        _split_other_player_anim, mirrored here since a level can carry
        dozens of NPCs re-splitting the same static string every frame."""
        cache = getattr(self, '_npc_gani_split_cache', None)
        if cache is None:
            cache = self._npc_gani_split_cache = {}
        result = cache.get(gani_name)
        if result is None:
            parts = [p.strip() for p in gani_name.split(',')]
            name = parts[0].strip()
            params = parts[1:]
            result = (name, params)
            if len(cache) > 300:
                cache.clear()
            cache[gani_name] = result
        return result

    def _render_npc(self, x: float, y: float, npc: dict, npc_id: int,
                    frame: Optional[FrameContext] = None):
        """Render an NPC."""
        # destroy / hide make the NPC (and its layers) vanish entirely.
        if npc.get('visible') is False:
            return

        frame = self._frame_context() if frame is None else frame
        nick_anchor = None  # set below when the NPC actually draws a body/sprite

        # GS1 showimg/showtext layers this NPC painted (lights, signs, text).
        # Split around the base sprite by their changeimgvis layer.
        imgs = npc.get('imgs')
        if imgs:
            self._render_npc_layers(imgs, over=False)

        gani_name = npc.get('gani', npc.get('animation'))
        gani_params: List[str] = []
        if gani_name:
            # setcharani/setani keep their `,param1,param2,...` args joined to
            # the ani name; split them off (Tier 2d) instead of discarding
            # them, so a scripted hat/prop image can drive the ATTR1-5 layers.
            # Memoized on the raw string (see _split_npc_gani) since it's
            # static between server updates and there can be dozens of NPCs.
            gani_name, gani_params = self._split_npc_gani(gani_name)
        image_name = npc.get('image')
        is_character = npc.get('is_character')
        if not is_character and image_name == CHARACTER_IMAGE:
            # A server that runs `showcharacter` itself streams the literal
            # image "#c#" as the character marker (GS1Commands.cpp:3049 writes
            # the prop, NPC.h:484-487 isCharacter; pygserver mirrors it). The
            # marker is truthy, so without this the static-sprite branch below
            # tried to load a sheet literally named "#c#" and the NPC stayed
            # invisible. npc_handler.py keys touch geometry off the same
            # marker (_is_character_npc).
            is_character = True
        if not is_character and not image_name and (npc.get('headimage') or npc.get('bodyimage')):
            # is_character is normally set by the client-side GS1 showcharacter
            # builtin (gs1_client.py), but pygserver now runs level scripts
            # SERVER-side and just streams the look as plain NPC props
            # (headimage/bodyimage - packets.parse_npc_props), with no
            # showcharacter call for the client to see. An NPC with a face but
            # no plain sprite image (guards, villagers, ...) is a character
            # either way, so infer it the same as an explicit showcharacter.
            is_character = True
        if is_character and not gani_name:
            gani_name = 'idle'  # a showcharacter with no ani idles

        # Parse and cache visual effects from NPC script and image. Keyed on
        # (image, script length), not just id: slow servers stream NPC props
        # incrementally, so image/script often arrive AFTER the first draw and
        # a once-only parse would lock in "no effects" (light2.png lamps drew
        # as opaque boxes forever).
        script = npc.get('script', '')
        effects_key = (image_name or '', len(script))
        effects = self.npc_effects.get(npc_id)
        if effects is None or effects.get('_key') != effects_key:
            effects = parse_npc_visual_effects(script, image_name or '')
            effects['_key'] = effects_key
            self.npc_effects[npc_id] = effects
        is_light = (npc.get('effect_mode') == 2
                    or effects.get('drawaslight', False))
        coloreffect = npc.get('coloreffect', effects.get('coloreffect'))

        if gani_name:
            # Use animation
            if npc_id not in self.npc_anims:
                anim = AnimationState(self.gani_parser)
                anim.set_animation(gani_name, npc.get('direction', 2),
                                   params=gani_params)
                self.npc_anims[npc_id] = anim

            anim = self.npc_anims[npc_id]
            # Params go with the name: a gani's PLAYSOUND is routinely a PARAMn
            # token (`setani sen_piano_note2,<note>.wav`), and the split above
            # means set_animation can no longer recover them from the name.
            # Still a cheap no-op when neither name nor params changed
            # (gani.py:624).
            anim.set_animation(gani_name, npc.get('direction', 2),
                               params=gani_params)
            if anim.gani is None:
                # The gani isn't downloaded yet — ask for it and stay invisible
                # (like the missing-image path), rather than drawing the magenta
                # placeholder. It pops in once on_file caches it.
                self._request_asset(gani_name + '.gani')
            elif anim.gani.is_movie and anim.movie is not None:
                self._render_movie(x, y, anim)
                nick_anchor = (x + TILE_SIZE, y + 48)
            else:
                # A character NPC composites head/body/colours like a player.
                equip = {}
                if is_character:
                    equip = {
                        'body_image': self._npc_image(npc, 'body_image', 'bodyimage', 'body.png'),
                        'head_image': self._npc_image(npc, 'head_image', 'headimage', 'head0.png'),
                        'sword_image': npc.get('sword_image') or 'sword1.png',
                        'shield_image': npc.get('shield_image') or 'shield1.png',
                        # Tier 2a: live via setcharprop #C0-#C4 (see
                        # _npc_character_colors); dormant for anything that
                        # only ever sets a raw 'colors' list.
                        'colors': self._npc_character_colors(npc),
                    }
                for i, p in enumerate(gani_params[:5], start=1):
                    if p:
                        equip[f'attr{i}_image'] = p
                self._render_animated_entity(x, y, anim, equip)
                # Gani canvas anchors at raw (x, y); for a typical 2-tile NPC
                # sprite: body centre = x + TILE_SIZE, feet row = y + 48
                # (the 48px gani canvas).
                nick_anchor = (x + TILE_SIZE, y + 48)

        elif image_name and not is_character:
            # Static sprite - position at top-left of NPC coords (no offset).
            # Classic "object" NPCs share a tilesheet (pics1.png etc.) and carry
            # an IMAGEPART rect selecting their sub-region; honor it so we don't
            # blit the whole sheet.
            part = npc.get('imagepart')
            if part and part[2] > 0 and part[3] > 0:
                sprite = self.sprite_mgr.get_sprite(image_name, *part)
            else:
                sprite = self.sprite_mgr.load_sheet(image_name)
            if sprite:
                # setzoomeffect: scale the image draw, centred on the unzoomed
                # footprint (the bomber's lamp bulbs crop a slice of
                # light2.png and zoom it 2-5x into a shaft of light). Only
                # safe now that additive lights are DEFERRED past the tint —
                # under the old tint-eraser scheme a zoomed glow erased a huge
                # rectangle of ambience instead.
                zoom = npc.get('zoom_effect', effects.get('zoom'))
                if zoom and zoom > 0 and zoom != 1.0:
                    zcache = getattr(self, '_npc_zoom_cache', None)
                    if zcache is None:
                        zcache = self._npc_zoom_cache = {}
                    zkey = (image_name, part, zoom)
                    zoomed = zcache.get(zkey)
                    if zoomed is None:
                        zw = max(1, int(sprite.get_width() * zoom))
                        zh = max(1, int(sprite.get_height() * zoom))
                        zoomed = pygame.transform.smoothscale(
                            sprite.convert_alpha(), (zw, zh))
                        # The bulb crops slice light2.png mid-gradient, so the
                        # scaled glow has bright hard borders; fade its edges
                        # out so the shaft of light dissolves into the scene
                        # instead of ending in a visible rectangle.
                        self._fade_surface_edges(zoomed)
                        if len(zcache) > 100:
                            zcache.clear()
                        zcache[zkey] = zoomed
                    x -= (zoomed.get_width() - sprite.get_width()) / 2.0
                    y -= (zoomed.get_height() - sprite.get_height()) / 2.0
                    sprite = zoomed
                # Apply visual effects for light NPCs
                if is_light or coloreffect:
                    self._render_light_sprite(sprite, x, y, is_light,
                                              coloreffect, frame)
                else:
                    self.screen.blit(sprite, (x, y))
                # Label under the drawn extent (x/y/sprite already zoom-adjusted).
                nick_anchor = (x + sprite.get_width() / 2, y + sprite.get_height())
            else:
                # Not cached locally — ask the server for it (once). Stay
                # INVISIBLE until it arrives (real Reborn does), rather than
                # littering the level with green blobs; on_file caches it and it
                # pops in. Show the marker only in debug mode.
                self._request_asset(image_name)
                if self.debug_mode:
                    self.screen.blit(self.npc_placeholder, (x, y))
        elif self.debug_mode:
            # No image and no gani: a script-only NPC (trigger/controller) that
            # is meant to be invisible. Only flag it in debug mode.
            self.screen.blit(self.npc_placeholder, (x, y))

        if imgs:
            self._render_npc_layers(imgs, over=True)

        # NPC nickname (setcharprop #n / setnick / NPCPROP 20 -> npc['nickname']):
        # a floating label centred under the NPC — classic draws it in blue,
        # players in white. Reuses the outlined-text helper so it stays readable
        # over dark/busy art, and _place_nameplate so it staggers against player
        # nameplates on the same tile. nick_anchor is None for undrawn / invisible
        # NPCs, so they get no label (matching the classic client).
        nickname = npc.get('nickname')
        if nickname and nick_anchor:
            name_surf = self._render_text_outlined_cached(
                self.font_small, nickname, self._NPC_NICK_COLOR)
            name_x = nick_anchor[0] - name_surf.get_width() // 2
            name_x, name_y = self._place_nameplate(name_x, nick_anchor[1],
                                                   name_surf.get_size(), frame)
            self.screen.blit(name_surf, (name_x, name_y))

        # Render NPC chat bubble if active (and not timed out)
        if npc_id in self.npc_chat_texts:
            text, chat_time = self.npc_chat_texts[npc_id]
            if time.time() - chat_time < self.chat_bubble_duration:
                self._render_speech_bubble(x, y, text)

    def _render_movie(self, x: float, y: float, anim: AnimationState):
        """Render the visible cast of a movie gani around its owning NPC."""
        for actor in anim.movie.visible_actors():
            actor_x = x + actor.dx
            actor_y = y + actor.dy
            if actor.kind == 'CHAR':
                if actor.animation is None:
                    continue
                equipment = {
                    'body_image': actor.body,
                    'head_image': actor.head,
                    'sword_image': actor.sword,
                    'shield_image': actor.shield,
                    'horse_image': actor.horse,
                    'attr1_image': actor.attr1,
                    'colors': [self._palette_slot(value)
                               for value in actor.colors],
                }
                for key, value in actor.params.items():
                    equipment[key] = value
                    suffix = key[5:]
                    if suffix.isdigit():
                        equipment[f'attr{suffix}_image'] = value
                self._render_animated_entity(
                    actor_x, actor_y, actor.animation, equipment)
                if actor.chat:
                    self._render_speech_bubble(actor_x, actor_y, actor.chat)
            elif actor.kind == 'SPRITE' and actor.sprite is not None:
                sprite_def = anim.gani.sprites.get(actor.sprite)
                if sprite_def is None:
                    continue
                layer = sprite_def.layer
                image = (layer.lower() if '.' in layer else
                         anim.gani.defaults.get(layer, 'sprites.png'))
                sprite = self.sprite_mgr.get_sprite(
                    image, sprite_def.x, sprite_def.y,
                    sprite_def.width, sprite_def.height)
                if sprite is not None:
                    self.screen.blit(sprite, (actor_x, actor_y))
                else:
                    self._request_asset(image)

    # -- GS1 showimg / showtext layers -------------------------------------
    def _render_npc_layers(self, imgs: dict, over: bool,
                           on_screen_only: bool = False,
                           gui: bool = False):
        """Draw an NPC's GS1 image/text layers. ``changeimgvis`` (vis) is the
        depth: layers at vis>=2 draw in front of the NPC sprite, the rest behind.
        GUI-band layers (_layer_is_gui) are excluded from the world passes and
        drawn by _render_gui_layers after the seteffect tint; pass gui=True to
        draw exactly that band instead.

        Stacking within a pass is by (vis, index): vis is the layer STRATUM
        (higher draws on top), the showimg index only breaks ties within one
        stratum. Index-only ordering buried the v6 bomber's -GraalUI HUD
        lettering: it draws white A/S/D/Q glyphs at vis 6 (indices 237-241)
        and their black drop-shadow copies at vis 5 on HIGHER indices
        (242-246), so the shadows painted over the white text and the HUD
        read as unlit black-on-red (live-verified 2026-07-24; the C# client
        strata-sorts, same as its world bands).

        Takes no frame: it carries none of the cross-pass state itself, and
        the one layer type that does (an additive showimg, deferred past the
        tint) reads the ambient `_frame_context()` — which is the same object
        the caller holds. Harnesses stub `_render_showimg_rec` with a bare
        one-argument recorder (tests/unit/test_showimg_rotation.py), and the
        per-layer `except Exception` below would swallow the arity error."""
        for idx in sorted(imgs, key=lambda i: (imgs[i].get('vis', 4), i)):
            rec = imgs[idx]
            # findimg(i).visible = false (gs2_client._LayerImage writes the
            # rec key) hides the layer without destroying it; unset means
            # visible, so only an explicit False skips.
            if rec.get('visible') is False:
                continue
            if self._layer_is_gui(rec) != gui:
                continue
            if not gui and (rec.get('vis', 4) >= 2) != over:
                continue
            if on_screen_only and not self._layer_is_gui(rec):
                # Cull by the layer's full drawn extent, not just its top-left
                # point. A showimg can be far bigger than a sprite (the lobby
                # smoke NPC tiles 400px cloud textures around the player);
                # top-left-only culling dropped every tile whose origin sat
                # above/left of the viewport even though it covered the
                # screen, leaving an undarkened band that read as a hard dark
                # rectangle whenever the owner NPC itself was off-screen
                # (large window + camera clamped away from the NPC's corner).
                if rec.get('poly'):
                    if not self._poly_layer_on_screen(rec):
                        continue
                else:
                    sx, sy = self._layer_pos(rec)
                    lw, lh = self._layer_draw_size(rec)
                    if rec.get('rotation'):
                        side = max(lw, lh) * 1.415
                        sx -= (side - lw) / 2
                        sy -= (side - lh) / 2
                        lw = lh = side
                    if not self._entity_on_screen(sx, sy, margin=0,
                                                  width=lw, height=lh):
                        continue
            try:
                if rec.get('text_is'):
                    self._render_showtext_rec(rec)
                elif rec.get('gani'):
                    self._render_showani_rec(rec)
                elif rec.get('image'):
                    self._render_showimg_rec(rec)
                elif rec.get('poly'):
                    self._render_showpoly_rec(rec)
                emitter = rec.get('emitter')
                if emitter is not None:
                    # live particles ride their layer's pass/stratum
                    # (render_effects._render_layer_emitter)
                    self._render_layer_emitter(rec, emitter)
            except Exception:
                pass  # a bad layer must never break the frame

    @staticmethod
    def _fade_surface_edges(surf: pygame.Surface, frac: float = 0.35):
        """In-place: multiply RGB toward 0 near the surface's edges, so an
        additive glow blit fades out instead of ending in a hard rectangle.
        The ramp is a tiny white-centre bitmap smoothscaled up (bilinear =
        linear edge ramps), multiplied in — no numpy needed. Runs once per
        cached (image, part, zoom) surface."""
        w, h = surf.get_size()
        # 5x5 with a 3x3 white core -> after smoothscale the outer ~1/4 on
        # each side ramps 0..255; close enough to `frac` for a glow fade.
        core = pygame.Surface((5, 5))
        core.fill((0, 0, 0))
        core.fill((255, 255, 255), pygame.Rect(1, 1, 3, 3))
        mask = pygame.transform.smoothscale(core, (w, h))
        surf.blit(mask, (0, 0), special_flags=pygame.BLEND_RGB_MULT)

    def _render_deferred_lights(self, frame: Optional[FrameContext] = None):
        """Flush this frame's additive light draws (queued by
        _render_light_sprite / additive showimg layers) on top of the
        seteffect/day-night tint — the classic client's effect-mode-2 glows
        brighten the tinted scene rather than punching holes in the tint."""
        draws = (self._frame_context() if frame is None else frame).light_draws
        if not draws:
            return
        for surf, x, y in draws:
            self.screen.blit(surf, (int(x), int(y)),
                             special_flags=pygame.BLEND_ADD)
        draws.clear()

    def _render_gui_layers(self, frame: Optional[FrameContext] = None):
        """Draw every GUI-band layer (explicit vis>=4 / showimg2-family) from
        current-level NPCs and weapon scripts. Called from the render loop
        AFTER _render_screen_tint so scripted menus, captions and countdowns
        stay visible over a seteffect curtain (the arena's `seteffect 0,0,0,1`
        + "Joining..." flow), matching the classic client's GUI stratum.

        This band runs past the point where deferred lights were flushed, so
        it marks the frame: an additive layer drawn here has to blit now
        (FrameContext.defer_light)."""
        frame = self._frame_context() if frame is None else frame
        frame.gui_pass = True
        try:
            self._render_gui_layers_inner()
        finally:
            frame.gui_pass = False

    def _render_gui_layers_inner(self):
        client = getattr(self, 'client', None)
        npcs = getattr(client, 'npcs', {}) if client else {}
        for npc_id in sorted(npcs):
            npc = npcs[npc_id]
            if not isinstance(npc, dict) or npc.get('visible') is False:
                continue
            npc_level = npc.get('_level')
            if (npc_level and not getattr(client, 'in_gmap_segment', False)
                    and npc_level != getattr(client, '_current_level_name', None)):
                continue
            imgs = npc.get('imgs')
            if imgs:
                self._render_npc_layers(imgs, over=True, gui=True)
        wimgs = getattr(getattr(self, 'gs1', None), '_weapon_imgs', None)
        if wimgs:
            for store in list(wimgs.values()):
                self._render_npc_layers(store, over=True, gui=True)

    @staticmethod
    def _layer_is_gui(rec) -> bool:
        """True for layers in the classic GUI band: an EXPLICIT
        changeimgvis >= 4. GUI layers use screen-pixel coordinates (the
        bomber's shop/menus position them from screenwidth/mousescreenx math)
        and draw above the world + seteffect tint — that's how a scripted
        "Joining..." caption stays readable over a black curtain. Layers that
        never called changeimgvis keep world-tile coords even though their
        default band value is 4 (vis_set gates that).

        The "2"-suffixed commands (showimg2/showani2/showtext2) do NOT mean
        screen-space — GServer-v2's own fn_showimg2 says "Displays an image
        ON THE LEVEL at the specified coordinates" (identical wording to
        showimg's); per the docs, "2" only adds a z/zoom parameter, and the
        UI layer is reachable "by using changeimgvis" — nothing to do with
        the command name. gs1_client.py already gets this right for
        showani2 (unconditionally screen=False) but showimg2/showtext2 were
        flagged screen-space by mistake, which sent the bomber lobby's
        room-editor walls/furniture (drawn via showimg2 at vis 1-3, a world
        layer) to raw world-tile numbers read as SCREEN pixels — stuck near
        the canvas's top-left corner instead of following the camera. Rather
        than trust that per-record flag, gate purely on the documented
        vis>=4 signal (this file doesn't own gs1_client.py, but this is the
        only reader of rec['screen'] — see the grep before this fix)."""
        return bool(rec.get('vis_set') and rec.get('vis', 4) >= 4)

    def _layer_pos(self, rec):
        """Screen position of a layer: GUI-band layers (explicit vis>=4) are
        already in screen pixels; otherwise the coords are world tiles."""
        if self._layer_is_gui(rec):
            return rec.get('x', 0.0), rec.get('y', 0.0)
        return self.camera.world_to_screen(rec.get('x', 0.0), rec.get('y', 0.0))

    def _layer_draw_size(self, rec) -> Tuple[float, float]:
        """Approximate on-screen pixel extent of a GS1 layer, for the
        culled-owner on_screen_only pass in _render_npc_layers. Image layers
        use the (cached) sheet or imagepart size scaled the same way
        _render_showimg_rec will draw them; anything without a resolvable
        image (gani/text layers, not-yet-downloaded sheets) falls back to a
        4-tile footprint — the same fallback _npc_draw_size uses."""
        factor = (self.camera.scale / float(TILE_SIZE)) * (rec.get('zoom') or 1.0)
        part = rec.get('part')
        if part and len(part) >= 4 and part[2] > 0 and part[3] > 0:
            return part[2] * factor, part[3] * factor
        image = rec.get('image')
        if image:
            sheet = self.sprite_mgr.load_sheet(image)
            if sheet is not None:
                return sheet.get_width() * factor, sheet.get_height() * factor
        extent = self.camera.scale * 4
        return extent, extent

    def _poly_layer_on_screen(self, rec) -> bool:
        """Visibility test for a world-band showpoly layer: its footprint is
        its vertex bounding box (vertices are level-tile coords — see
        _render_showpoly_rec), not the rec's x/y, which polys never set."""
        pts = rec.get('poly') or ()
        stride = 3 if rec.get('poly_dim') == 3 else 2
        if len(pts) < stride * 3:
            return False
        xs = [pts[i] for i in range(0, len(pts) - stride + 1, stride)]
        ys = [pts[i + 1] for i in range(0, len(pts) - stride + 1, stride)]
        left, top = self.camera.world_to_screen(min(xs), min(ys))
        right, bottom = self.camera.world_to_screen(max(xs), max(ys))
        return self._entity_on_screen(left, top, margin=0,
                                      width=right - left, height=bottom - top)

    def _render_showimg_rec(self, rec: dict):
        image = rec['image']
        part = rec.get('part')
        if part and part[2] > 0 and part[3] > 0:
            sprite = self.sprite_mgr.get_sprite(image, *part)
        else:
            sprite = self.sprite_mgr.load_sheet(image)
        if not sprite:
            self._request_asset(image)
            return
        # Image pixels are 1:1 with the world at base zoom (16 px/tile); the
        # showimg `zoom` arg multiplies on top of the camera scale.
        factor = (self.camera.scale / float(TILE_SIZE)) * (rec.get('zoom') or 1.0)
        if factor <= 0:
            return
        w = max(1, int(sprite.get_width() * factor))
        h = max(1, int(sprite.get_height() * factor))

        colors = _layer_colors(rec)
        # changeimgmode / wire drawMode share one numbering (GServer-v2
        # object/ShowImg.h prop 8): 0 = additive, 1 = replace (normal alpha
        # blend), 2 = subtractive, 3 = daynight. The bomber leans on this:
        # mode 2 draws its dark smoke (eye_bomb_blackhole*) and white-block
        # shadows by SUBTRACTING the image from the scene — treating it as a
        # normal blit painted the raw 400px black/white cloud textures as an
        # opaque player-centred blob with a hard square edge. No explicit
        # mode keeps the legacy light2.png-style additive heuristic.
        mode = rec.get('mode')
        additive = mode == 0 or (mode is None and 'light' in image.lower())
        subtractive = mode == 2
        colors_key = tuple(colors) if colors else None

        # Rescaling every frame (even at factor==1) and recoloring every frame
        # is wasted work for a layer that's usually static between server
        # updates - cache the finished (scaled + recolored) surface keyed by
        # everything that can change its pixels.
        cache = getattr(self, '_showimg_cache', None)
        if cache is None:
            cache = self._showimg_cache = {}
        cache_key = (image, part, w, h, colors_key, additive, subtractive)
        out = cache.get(cache_key)
        if out is None:
            out = sprite if (w, h) == sprite.get_size() else pygame.transform.scale(sprite, (w, h))
            if additive or subtractive:
                # BLEND_ADD/BLEND_RGB_SUB ignore alpha entirely, so both the
                # layer's colour-alpha AND the image's own per-pixel alpha
                # must be folded into RGB first — otherwise a transparent
                # pixel's hidden RGB bleeds into the blend (a fully
                # transparent border would still add/subtract, re-creating
                # the hard square edge these modes exist to avoid).
                out = out.convert_alpha().premul_alpha()
                r, g, b, a = colors if colors else (1.0, 1.0, 1.0, 1.0)
                if subtractive:
                    # Subtractive layers are smoke/shadow, not blackout: a
                    # faithful subtraction of an opaque near-white cloud (the
                    # bomber lobby's eye_bomb_blackhole grid) exceeds the
                    # scene's whole dynamic range and clamps it to black.
                    # Attenuate so the darkness reads as translucent smoke
                    # over a still-legible level. See SUBTRACT_SMOKE_SCALE.
                    a *= SUBTRACT_SMOKE_SCALE
                if colors or subtractive:
                    mult = (_c255(r * a), _c255(g * a), _c255(b * a), 255)
                    out.fill(mult, special_flags=pygame.BLEND_RGB_MULT)
            elif colors:
                r, g, b, a = colors
                out = out.copy()
                out.fill((_c255(r), _c255(g), _c255(b), 255),
                          special_flags=pygame.BLEND_RGB_MULT)
                out.set_alpha(_c255(a))
            if len(cache) > 300:
                cache.clear()
            cache[cache_key] = out

        sx, sy = self._layer_pos(rec)
        rot = rec.get('rotation')
        if rot:
            # findimg(i).rotation is radians, positive = counter-clockwise,
            # pivot = the drawn image's centre (the C# client's Drawing.cs
            # passes origin = centre and negates the angle for MonoGame's
            # clockwise convention; pygame's rotate() is already CCW). The
            # v6 bomber lobby's cogs spin by nudging this every 0.01s, so
            # memoize the rotated surface per rec keyed by (base, angle) and
            # re-anchor the blit so the centre stays put. rotate() pads the
            # corners transparent, so additive/subtractive blends see zero
            # there instead of a hard square.
            try:
                deg = math.degrees(float(rot))
            except (TypeError, ValueError):
                deg = 0.0
            rot_key = (cache_key, round(deg, 1))
            if rec.get('_rot_key') != rot_key:
                rec['_rot_key'] = rot_key
                rec['_rot_surf'] = pygame.transform.rotate(out, deg)
            rotated = rec['_rot_surf']
            sx -= (rotated.get_width() - out.get_width()) / 2.0
            sy -= (rotated.get_height() - out.get_height()) / 2.0
            out = rotated
        if additive:
            # Additive layers are lights: defer them to after the seteffect
            # tint (same treatment as _render_light_sprite) unless we're
            # already in the post-tint GUI pass or outside the frame loop.
            if not self._frame_context().defer_light(out, sx, sy):
                self.screen.blit(out, (int(sx), int(sy)),
                                 special_flags=pygame.BLEND_ADD)
            return
        flags = pygame.BLEND_RGB_SUB if subtractive else 0
        self.screen.blit(out, (int(sx), int(sy)), special_flags=flags)

    def _render_showani_rec(self, rec: dict):
        """Draw a showani layer (an animated gani at a level/screen position) —
        the arena paints bombs, vases and explosions this way. Each layer keeps
        its own AnimationState so it advances independently."""
        gani = rec.get('gani')
        if not gani:
            return
        # gs1_client.py splits the ani name from its trailing params before
        # storing 'gani', but strip defensively in case a caller ever stores
        # the raw comma-joined form.
        gani = gani.split(',')[0].strip()
        anim = rec.get('_anim')
        if anim is None:
            anim = rec['_anim'] = AnimationState(self.gani_parser)
            anim.set_animation(gani, 0)
        else:
            # Face the layer's current direction (pets/emotes update 'dir' as
            # they move) — but only when that direction actually has frames.
            # Forcing a script-set dir onto a gani that only animates in
            # direction 0 (the mini-pet ganis) lands on an empty direction and
            # freezes the sprite, so fall back to the working direction 0.
            want_dir = int(rec.get('dir', 0) or 0)
            if anim.gani is not None and anim.gani.get_frame_count(want_dir) > 0:
                anim.set_direction(want_dir)
        if anim.gani is None and self.gani_parser.cache.get(gani.replace('.gani', '')) is not None:
            # The gani streamed in after this layer's AnimationState was
            # created (arena vases + lobby seat-cushion showani2 layers are
            # drawn ONCE, before their gani downloads on this slow server; the
            # rec and its blank AnimationState persist, and nothing else
            # re-resolves them, so they stay invisible all match). Retry the
            # resolve once the file is in the parser cache — cache-gated so a
            # still-missing gani costs a dict lookup, not a per-frame parse.
            anim.set_animation(gani, int(rec.get('dir', 0) or 0))
        if anim.gani is None:
            self._request_asset(gani + '.gani')
            return

        # An embedded-SCRIPT gani (Bomber Arena's explosion, various light/
        # particle effects) draws its real visual via GS1 showimg calls this
        # engine doesn't execute; its own ANI frames are a near-blank
        # placeholder. Substitute a generic burst so it still reads visually
        # instead of vanishing.
        if anim.gani.has_script:
            self._render_scripted_gani_fallback(rec)
            return

        anim.update(getattr(self, '_frame_dt', 0.05))
        sx, sy = self._layer_pos(rec)
        equip = self._showani_param_equip(rec.get('params'))
        self._render_animated_entity(int(sx), int(sy), anim, equip)

    @staticmethod
    def _showani_param_equip(params) -> dict:
        """Build an equipment dict from a showani call's trailing params, so
        PARAMn frame tokens and PARAMn-layer sprite sources resolve (Bomber
        Arena's bomb gani picks its body/decal this way - see
        _render_animated_entity and gani.py's _parse_frame_line)."""
        equip: dict = {}
        if not params:
            return equip
        for i, p in enumerate(params, start=1):
            equip[f'param{i}'] = p
            if isinstance(p, str):
                equip[f'param{i}_image'] = p
        return equip

    def _render_scripted_gani_fallback(self, rec: dict):
        """Synthesize an expanding/fading burst for a showani whose gani has
        an embedded SCRIPT we don't run. Bomber Arena's eye_bomber_expl.gani
        passes an intensity/trigger as its first param — but the arena only
        issues the showani ONCE with that param frozen at layer creation and
        never hides burnt-out non-wall cells, so the renderer can't watch a
        live countdown. Drive the burst's lifetime from a per-rec clock
        instead, so it expands, fades, and clears itself (a re-shown layer
        restarts because gs1_client pops '_fx_t' on a fresh showani)."""
        params = rec.get('params') or []
        try:
            on = float(params[0]) if params else 0.0
        except (TypeError, ValueError):
            on = 0.0
        if on <= 0:
            return
        t = rec['_fx_t'] = rec.get('_fx_t', 0.0) + getattr(self, '_frame_dt', 0.05)
        LIFE = 0.6  # matches the script's explosion burn timer
        if t >= LIFE:
            return
        progress = t / LIFE
        radius = int(10 + 22 * progress)
        alpha = int(255 * (1.0 - progress))
        if radius <= 0 or alpha <= 0:
            return
        sx, sy = self._layer_pos(rec)
        cx, cy = int(sx) + TILE_SIZE // 2, int(sy) + TILE_SIZE // 2
        surf = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        pygame.draw.circle(surf, (255, 150, 50, alpha), (radius, radius), radius)
        pygame.draw.circle(surf, (255, 220, 120, alpha), (radius, radius), max(1, int(radius * 0.55)))
        self.screen.blit(surf, (cx - radius, cy - radius))

    def _render_showtext_rec(self, rec: dict):
        text = rec.get('text', '')
        if not text:
            return
        style = rec.get('style', '') or ''
        is_gui = self._layer_is_gui(rec)
        if is_gui:
            # GUI-band text lives in raw screen pixels; the C# client's
            # TextDrawing renders it at a fixed 24*zoom px font with NO
            # camera factor. Multiplying by camera.scale here blew the
            # arena's changeimgzoom-5 "Joining..." caption up to ~200px
            # glyphs (5 * scale instead of 24 * 5 = 120px).
            size = max(8, int(24 * (rec.get('zoom') or 1.0)))
        else:
            size = max(8, int(16 * (rec.get('zoom') or 1.0) * (self.camera.scale / float(TILE_SIZE))))
        font = self._showtext_font(rec.get('font', '') or 'Arial', size, 'b' in style)
        colors = _layer_colors(rec)
        col = (_c255(colors[0]), _c255(colors[1]), _c255(colors[2])) if colors else (255, 255, 255)
        # Showtext (NPC name/sign labels) is drawn straight over the level,
        # not on a plate, so it needs the same outline nameplates get.
        surf = self._render_text_outlined_cached(font, text, col)
        if colors and len(colors) > 3:
            # set_alpha mutates the surface in place, so operate on our own
            # copy rather than the shared cached one.
            surf = surf.copy()
            surf.set_alpha(_c255(colors[3]))
        sx, sy = self._layer_pos(rec)
        if 'c' in style:  # horizontally centred on the anchor
            sx -= surf.get_width() / 2.0
            if is_gui:
                # The C# client's centred style centres BOTH axes (its draw
                # origin is the text centre); scripts anchor full-screen
                # captions at screenheight/2 expecting that. World-band
                # labels keep the historical x-only centring (nameplate
                # positions were live-tuned against it).
                sy -= surf.get_height() / 2.0
        self.screen.blit(surf, (int(sx), int(sy)))

    def _showtext_font(self, name: str, size: int, bold: bool):
        cache = getattr(self, '_showtext_fonts', None)
        if cache is None:
            cache = self._showtext_fonts = {}
        key = (name.lower(), size, bold)
        font = cache.get(key)
        if font is None:
            try:
                font = pygame.font.SysFont(name, size, bold=bold)
            except Exception:
                font = pygame.font.Font(None, size)
            cache[key] = font
        return font

    def _render_showpoly_rec(self, rec: dict):
        """Draw a showpoly/showpoly2 layer: `rec['poly']` is a flat
        `[x1,y1,x2,y2,...]` (dim 2) or `[x1,y1,z1,x2,y2,z2,...]` (dim 3, e.g.
        showpoly2's per-vertex height) list of level-tile coordinates. z is
        dropped for our top-down view — the same treatment showani2/showtext2
        give their z/zoom component. Filled with the layer's `colors` (set via
        changeimgcolors on the same index, like any other layer type) or
        opaque white if none was ever set."""
        pts = rec['poly']
        stride = 3 if rec.get('poly_dim') == 3 else 2
        if len(pts) < stride * 3:  # need at least 3 vertices
            return
        if self._layer_is_gui(rec):
            # GUI-band poly (explicit vis>=4): vertices are screen pixels
            # (npc190's full-screen {0,0,screenwidth,0,...} fade quad).
            points = [(int(pts[i]), int(pts[i + 1]))
                      for i in range(0, len(pts) - stride + 1, stride)]
        else:
            points = [self.camera.world_to_screen(pts[i], pts[i + 1])
                      for i in range(0, len(pts) - stride + 1, stride)]
        colors = _layer_colors(rec)
        col = (_c255(colors[0]), _c255(colors[1]), _c255(colors[2]),
               _c255(colors[3]) if len(colors) > 3 else 255) if colors else (255, 255, 255, 255)
        if col[3] == 0:
            # Fully transparent: skip the surface allocation entirely. Scripts
            # park a hurt/fade quad at alpha 0 for the whole session and only
            # ramp it up on damage (see _layer_colors), so this is the common
            # case for a full-screen poly, once per frame.
            return

        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        min_x, min_y = min(xs), min(ys)
        w = max(1, max(xs) - min_x)
        h = max(1, max(ys) - min_y)
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        local_points = [(px - min_x, py - min_y) for px, py in points]
        pygame.draw.polygon(surf, col, local_points)  # width=0 -> filled
        self.screen.blit(surf, (min_x, min_y))

    # Additive-blitting a light sprite reads as a blown-out white blob rather
    # than a glow. GS1 scripts commonly pass an "on" alpha around 0.99 (see
    # _render_scripted_gani_fallback's arenaGUI note), which looks like it
    # should dim the light almost to nothing... except pygame's BLEND_ADD
    # blit onto a plain (non-SRCALPHA) destination - which self.screen always
    # is here - IGNORES alpha entirely, both the surface-level alpha the
    # original code set via set_alpha() and the sprite's own per-pixel alpha
    # channel (verified empirically: an alpha=0 source still adds its full
    # RGB). So the *actual* additive contribution has always been the
    # sprite's raw, unscaled RGB regardless of coloreffect's alpha - that's
    # the real source of the wash-out, and set_alpha() never touched it.
    # Fixed the same way _render_showimg_rec already handles this exact
    # problem (see its "fold alpha into the colour so additive blending dims
    # it" comment): pre-scale the sprite's RGB via BLEND_RGB_MULT before the
    # additive blit, so the alpha (capped) actually reduces brightness.
    _LIGHT_ADDITIVE_ALPHA_CAP = 140  # out of 255

    def _render_light_sprite(self, sprite: pygame.Surface, x: float, y: float,
                              is_light: bool, coloreffect: Optional[Tuple[float, float, float, float]],
                              frame: Optional[FrameContext] = None):
        """Render a sprite with light effects (additive blending, alpha).

        Args:
            sprite: The sprite surface to render
            x, y: Position (top-left of NPC tile, like other NPC images)
            is_light: If True, use additive blending
            coloreffect: (r, g, b, a) multipliers - r,g,b typically 1.0, a is alpha (0-1)
            frame: the frame whose deferred-light queue an additive glow joins
        """
        # copy()+recolor/set_alpha() every frame per light NPC is wasted work
        # since the same (sprite, mult) pair repeats frame to frame - cache
        # the result.
        cache = getattr(self, '_light_sprite_cache', None)
        if cache is None:
            cache = self._light_sprite_cache = {}

        if is_light:
            # See the class-level comment above: alpha is folded into the RGB
            # via BLEND_RGB_MULT (not set_alpha(), which BLEND_ADD ignores),
            # capped so the additive contribution can't wash the scene out.
            alpha_frac = coloreffect[3] if coloreffect else 1.0
            mult = _c255(min(alpha_frac, self._LIGHT_ADDITIVE_ALPHA_CAP / 255.0))
            key = (id(sprite), mult, True)
            light_sprite = cache.get(key)
            if light_sprite is None:
                light_sprite = sprite.copy()
                light_sprite.fill((mult, mult, mult, 255), special_flags=pygame.BLEND_RGB_MULT)
                if len(cache) > 300:
                    cache.clear()
                cache[key] = light_sprite
            # Position - place light sprite with top-left at NPC position.
            # User testing confirmed this positioning is correct for light
            # effects. The additive blit is DEFERRED to after the seteffect/
            # day-night tint (render.py's _render_deferred_lights) so the
            # glow brightens the tinted scene the way the classic client's
            # effect-mode-2 lights do — no tint-eraser holes (see
            # FrameContext.light_draws). Direct callers outside the frame loop
            # (render smoke/tests) just blit now.
            ctx = self._frame_context() if frame is None else frame
            if not ctx.defer_light(light_sprite, x, y):
                self.screen.blit(light_sprite, (x, y),
                                 special_flags=pygame.BLEND_ADD)
        else:
            # Non-additive path: a plain blit DOES respect set_alpha(), so
            # this one is unaffected by the BLEND_ADD alpha quirk above.
            alpha = int(coloreffect[3] * 255) if coloreffect else None
            key = (id(sprite), alpha, False)
            light_sprite = cache.get(key)
            if light_sprite is None:
                light_sprite = sprite.copy()
                if alpha is not None:
                    light_sprite.set_alpha(alpha)
                if len(cache) > 300:
                    cache.clear()
                cache[key] = light_sprite
            self.screen.blit(light_sprite, (x, y))

    def _resolve_gani_layers(self, anim: AnimationState, frame, equipment: dict) -> list:
        """Resolve frame.sprites -> (image, sprite-rect) per layer, memoized
        per (gani, direction, frame, equipment). This is the expensive part
        of _render_animated_entity (a dict.get/isinstance/startswith/isdigit
        chain per sprite, per entity, per frame - ~80 entities/frame adds up
        fast) but its result only changes when the animation moves to a new
        frame/direction or the equipment dict changes, both far rarer than
        "every frame" - most entities hold the same gani/frame/equipment
        across many consecutive frames, so this cache is normally a hit.

        Returns a list of entries, either:
          ('shadow', ox, oy) - blit self.shadow_sprite there, or
          ('sprite', img, sprite_def, ox, oy, recolor) - recolor is True if
          the caller should draw it through get_sprite_recolored using the
          CALLER's *current* equipment['colors'] (not baked into the cache -
          only the resolved (img, sprite_def) needs memoizing; re-reading
          colors from the live equipment dict at blit time is just as cheap
          as a plain get_sprite lookup and avoids ever holding a stale
          reference to an old colors list).
        """
        cache = getattr(self, '_gani_layer_cache', None)
        if cache is None:
            cache = self._gani_layer_cache = {}

        # A hashable snapshot of the equipment dict - small (a handful of
        # keys), so building this every call is cheap; it's re-walking
        # frame.sprites with it that's expensive, and that's what gets cached.
        equipment_key = tuple(sorted(
            (k, tuple(v) if isinstance(v, (list, tuple)) else v)
            for k, v in equipment.items()
        ))
        # Direction is part of the key even though it's not called out
        # explicitly in the finding, because the same frame index can hold
        # different sprite layouts per direction (facing up vs down) - the
        # important thing being memoized is (gani, direction, frame index).
        key = (id(anim.gani), anim.direction, anim.frame, equipment_key)
        resolved = cache.get(key)
        if resolved is not None:
            return resolved

        resolved = []
        for raw_sprite_id, ox, oy in frame.sprites:
            sprite_id = raw_sprite_id
            if isinstance(sprite_id, str):
                # A "PARAM1".."PARAM5" frame token - the real sprite id is
                # whatever the showani/setani call passed as that positional
                # extra arg (see _showani_param_equip / gani.py's
                # _parse_frame_line), falling back to the gani's own
                # DEFAULTPARAMn (e.g. eye_bomber_bomb.gani's DEFAULTPARAM1 50)
                # when the caller didn't pass one.
                pval = equipment.get(sprite_id.lower())
                if pval is None:
                    pval = anim.gani.defaults.get(sprite_id)
                if pval is None:
                    continue
                try:
                    sprite_id = int(float(pval))
                except (TypeError, ValueError):
                    continue
            sprite_def = anim.gani.sprites.get(sprite_id)
            if not sprite_def:
                continue

            # Determine which image to use
            layer = sprite_def.layer
            if layer == "BODY":
                img = equipment.get('body_image', anim.gani.defaults.get('BODY', 'body.png'))
            elif layer == "HEAD":
                img = equipment.get('head_image', anim.gani.defaults.get('HEAD', 'head0.png'))
            elif layer == "SWORD":
                img = equipment.get('sword_image', anim.gani.defaults.get('SWORD', 'sword1.png'))
            elif layer == "SHIELD":
                img = equipment.get('shield_image', anim.gani.defaults.get('SHIELD', 'shield1.png'))
            elif layer.startswith("ATTR") and layer[4:].isdigit():
                # An ATTRn sprite layer draws the WEARER's gani attribute n
                # (PLPROP_GATTRIB1.. on the wire, #P1.. in script), not the
                # gani's own text. The reference client resolves the two
                # separately - `case Attr` indexes the object's attr table and
                # `case Param` the setani argument list
                # (Preagonal/FourPlay/quattroplay/src/TGaniObject.cpp:1974-1994)
                # - and its gani parser has no DEFAULTATTRn directive at all
                # (same tree, TGraalAni.cpp:425-495: SPRITE / ATTACHSPRITE /
                # ANI / LOOP / SETBACKTO / DEFAULTHEAD / DEFAULTBODY / ZOOM /
                # ACTOR / PARAMn / ATTRn, and nothing else).
                #
                # So a caller that knows the entity's attributes passes them
                # (empty string included) and owns the slot; only a caller
                # that supplies no attrN_image key at all still falls back to
                # DEFAULTATTRn. Falling back unconditionally drew Bomber's
                # `DEFAULTATTR1 hat0.png` (cache/bomber_arena/
                # eye_bomber_idle0.gani) on every player, hat or no hat, while
                # the real client drew none.
                img = equipment.get(f'{layer.lower()}_image')
                if img is None:
                    img = anim.gani.defaults.get(layer, '')
                if not img:
                    continue
            elif layer == "SPRITES":
                # Shadow and effects - use defaults
                # Special case: shadow sprite (id 0) - render our shadow
                if sprite_id == 0:
                    resolved.append(('shadow', ox, oy))
                    continue
                img = anim.gani.defaults.get('SPRITES', 'sprites.png')
            else:
                # A sprite whose source is a literal image filename (e.g.
                # itsasign2's SIGN1.GIF) uses it directly; only keyword layers
                # (no extension) resolve through the gani defaults. Falling back
                # to sprites.png here drew signs/furniture as garbled characters.
                equip_key = f"{layer.lower()}_image"
                if '.' in layer:
                    img = layer.lower()
                elif equip_key in equipment:
                    # Generic equipment-driven layer (e.g. HORSE -> horse_image)
                    # so callers can drive any named gani layer without a
                    # dedicated elif branch here.
                    img = equipment[equip_key]
                else:
                    img = anim.gani.defaults.get(layer, 'sprites.png')

            # BODY goes through the palette-swap path when a colors prop is
            # available (Tier 2a - see sprites.py and PLPROP_COLORS parsing
            # in packets.py/player.py).
            recolor = layer == "BODY" and bool(equipment.get('colors'))
            resolved.append(('sprite', img, sprite_def, ox, oy, recolor))

        if len(cache) > 2000:
            cache.clear()
        cache[key] = resolved
        return resolved

    def _render_animated_entity(self, x: float, y: float, anim: AnimationState,
                                  equipment: dict, alpha: int = 255):
        """Render an entity using gani animation.

        The gani offsets position sprites within a bounding box.
        Position (x, y) is the top-left of the entity's tile position.
        """
        frame = anim.get_frame() if anim.gani else None
        requested = getattr(anim, 'requested_name', None)
        if requested and anim.gani is not None and anim.gani.name != requested:
            # A switch to a not-yet-downloaded gani: keep playing the old one
            # (set_animation retries each frame) but get the download going.
            self._request_asset(f"{requested}.gani")

        if not frame:
            # The requested gani isn't downloaded yet: ask for it and draw
            # nothing (real-client behavior), instead of a placeholder box —
            # GTA's cutscene `setani hiddenstill,` drew the player as a
            # magenta rectangle until the file arrived.
            if requested:
                self._request_asset(f"{requested}.gani")
                return
            sprite = self._sprite_with_alpha(self.placeholder_sprite, alpha)
            self.screen.blit(sprite, (x, y))
            return

        # Gani frame offsets are relative to a logical canvas whose ORIGIN is
        # the entity's world (x, y) — the real client applies them as-is with
        # no centring (classic-client spec: the player is a 3x3-tile sprite
        # anchored top-left; idle.gani putting the body at canvas x=8 is
        # exactly why the collision rect starts at x+0.5). Ground truth from
        # server content: itsasign2.gani places its 32x32 sign sprite at
        # frame offset (0,0) and the NPC script pairs it with
        # `setshape 1,32,32` at the same (x, y); sen_piano.gani encodes its
        # own placement as negative offsets (-3,-30). A former blanket
        # -(48-32)//2 = -8px "centre the canvas on a 2-tile box" shift here
        # drew every gani NPC half a tile left (Bomber lobby signs bug);
        # players had it cancelled with a +8 at their call sites — both
        # halves are gone now.
        base_offset_x = 0
        base_offset_y = 0

        # Render each sprite in the frame, from the memoized layer resolution
        for entry in self._resolve_gani_layers(anim, frame, equipment):
            if entry[0] == 'shadow':
                _, ox, oy = entry
                screen_x = x + base_offset_x + ox
                screen_y = y + base_offset_y + oy
                self.screen.blit(self.shadow_sprite, (screen_x, screen_y))
                continue

            _, img, sprite_def, ox, oy, recolor = entry
            if recolor:
                sprite = self.sprite_mgr.get_sprite_recolored(
                    img, equipment['colors'],
                    sprite_def.x, sprite_def.y,
                    sprite_def.width, sprite_def.height
                )
            else:
                sprite = self.sprite_mgr.get_sprite(
                    img,
                    sprite_def.x, sprite_def.y,
                    sprite_def.width, sprite_def.height
                )

            if sprite:
                sprite = self._sprite_with_alpha(sprite, alpha)
                # Calculate screen position: base offset + gani sprite offset
                screen_x = x + base_offset_x + ox
                screen_y = y + base_offset_y + oy
                self.screen.blit(sprite, (screen_x, screen_y))
            elif isinstance(img, str) and '.' in img:
                # The gani parsed fine but its referenced sprite SHEET (e.g.
                # sen_piano.png, sign1.gif) isn't downloaded yet, so get_sprite
                # returned nothing and the NPC drew blank. Ask the server for
                # it — _request_asset dedups, so this is a one-shot per file.
                # (BODY/HEAD/etc. resolve to real filenames upstream; a bare
                # layer name with no extension is skipped by the '.' guard.)
                self._request_asset(img)

    def _sprite_with_alpha(self, sprite: pygame.Surface,
                           alpha: int) -> pygame.Surface:
        """Return a cached alpha copy without mutating a shared sprite.

        The entry pins the source surface (strong ref) and re-checks
        identity on hit: a bare id()-keyed cache serves stale pixels once
        the sprite-manager LRUs evict and CPython reuses the freed
        surface's address for a new same-size sprite."""
        if alpha >= 255:
            return sprite
        cache = getattr(self, '_entity_alpha_cache', None)
        if cache is None:
            cache = self._entity_alpha_cache = {}
        key = (id(sprite), alpha)
        entry = cache.get(key)
        if entry is not None and entry[0] is sprite:
            return entry[1]
        result = sprite.copy()
        result.set_alpha(alpha)
        if len(cache) > 600:
            cache.clear()
        cache[key] = (sprite, result)
        return result
