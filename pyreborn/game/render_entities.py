"""EntityRenderMixin — players, NPCs, speech bubbles, animated sprites.

Split from render.py; methods operate on the GameClient instance."""

import time
from typing import List, Optional, Tuple

import pygame

from ..gani import AnimationState
from ..player import Player
from .constants import TILE_SIZE, parse_npc_visual_effects


def _c255(v: float) -> int:
    """Clamp a 0..1 GS1 colour/alpha multiplier to a 0..255 byte."""
    return max(0, min(255, int(float(v) * 255)))


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


class EntityRenderMixin:
    """Mixin providing the above methods for GameClient."""

    def _entity_on_screen(self, px: float, py: float, margin: int = 96,
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
        return -margin <= px <= w + margin and -margin <= py <= h + margin

    def _render_entities(self):
        """Render all entities (players, NPCs) sorted by Y position."""
        entities = []
        # Computed once per frame (not per entity - see _entity_on_screen).
        screen_size = self.screen.get_size()
        # Nameplates placed this frame, so overlapping players/NPCs standing
        # on/near the same tile stagger instead of drawing on top of each
        # other (see _place_nameplate).
        self._frame_nameplate_rects = []
        # drawaslight NPCs drawn this frame (eraser mask + screen pos), so
        # render_effects.py's _render_screen_tint can punch their footprint
        # out of the ambient darkness/tint overlay after every entity has
        # drawn (see _render_light_sprite).
        self._frame_light_sources = []

        # Add local player. Draw it through the camera at its true render-frame
        # top-left (set by _sync_camera) — same transform every other entity
        # uses — so it stays correct under zoom and the camera can aim at the
        # body centre without dragging the sprite off its real position.
        player = self.client.player
        # Depth-sort key must be in the SAME frame as every other entity (world
        # tiles). Other players/NPCs use world Y, so taking the local player's
        # %64 here made them sort behind everyone in a gmap. visual_y is already
        # world-frame.
        px, py = self.camera.world_to_screen(*self._player_render_pos)
        entities.append(('player', self.visual_y, px, py, player))

        # Reverse lookup (level_name -> grid pos), built once per frame instead
        # of rescanning client.gmap_grid for every remote player below (mirrors
        # the baddy segment-offset hoist further down).
        level_to_grid = {}
        if self.client.gmap_grid:
            for (gx, gy), level_name in self.client.gmap_grid.items():
                level_to_grid[level_name] = (gx, gy)

        # Add other players - convert their local coords to world coords
        for pid, pdata in self.client.players.items():
            if 'x' in pdata and 'y' in pdata:
                ox = pdata.get('x')
                oy = pdata.get('y')

                if ox is None or oy is None:
                    continue

                # Convert to world coords based on their level in GMAP
                player_level = pdata.get('level', '')
                world_x, world_y = ox, oy

                # Prefer the player's own level; if unset or unknown, assume
                # the same sub-level as the local player.
                grid = level_to_grid.get(player_level) if player_level else None
                if grid is None:
                    grid = level_to_grid.get(self.client._current_level_name)
                if grid is not None:
                    gx, gy = grid
                    world_x = ox + gx * 64
                    world_y = oy + gy * 64

                # Smooth interpolation for other players
                if pid in self.other_player_visual:
                    vx, vy = self.other_player_visual[pid]
                    # Interpolate toward target position
                    lerp = min(1.0, self.lerp_speed * self._frame_dt)
                    vx += (world_x - vx) * lerp
                    vy += (world_y - vy) * lerp
                    self.other_player_visual[pid] = (vx, vy)
                else:
                    # First time seeing this player, snap to position
                    vx, vy = world_x, world_y
                    self.other_player_visual[pid] = (vx, vy)

                opx, opy = self.camera.world_to_screen(vx, vy)
                if self._entity_on_screen(opx, opy, screen_size=screen_size):
                    entities.append(('other', vy, opx, opy, pdata, pid))

        # Add NPCs - use world coords if available (for GMAP), else local.
        # epoch_seen mirrors npc_visual (same lifetime - both are keyed by
        # npc_id and only ever need to outlive the NPCs currently known to
        # the client), but is lazily created rather than added to
        # pygame_game.py's __init__ since it's purely an implementation
        # detail of this interpolation loop (see _light_sprite_cache above
        # for the same local-cache idiom). A stale leftover entry for a
        # since-removed npc_id is harmless: client.py's epoch counter is
        # monotonically increasing and never reused, so it can never collide
        # with a *future* npc_id's real epoch and accidentally suppress a
        # snap.
        epoch_seen = getattr(self, '_npc_visual_epoch', None)
        if epoch_seen is None:
            epoch_seen = self._npc_visual_epoch = {}
        for npc_id, npc in self.client.npcs.items():
            # Prefer world coords (converted from local + grid offset)
            nx = npc.get('world_x', npc.get('x'))
            ny = npc.get('world_y', npc.get('y'))
            if nx is not None and ny is not None:
                # Interpolate NPC position for smooth movement, UNLESS
                # client.py just re-stamped this NPC's world_x/world_y for a
                # reason other than it actually moving (gmap re-attribution,
                # cache restore on level re-entry, initial stream - see
                # client.py's _mark_npc_pos_snap/_pos_epoch). Lerping across
                # one of those jumps is what made lights visibly "swoop into
                # position" on level entry; snap instead, same as a
                # brand-new npc_id.
                epoch = npc.get('_pos_epoch')
                if npc_id in self.npc_visual and epoch == epoch_seen.get(npc_id):
                    vx, vy = self.npc_visual[npc_id]
                    lerp = min(1.0, self.lerp_speed * self._frame_dt)
                    vx += (nx - vx) * lerp
                    vy += (ny - vy) * lerp
                else:
                    vx, vy = nx, ny
                self.npc_visual[npc_id] = (vx, vy)
                epoch_seen[npc_id] = epoch
                if len(epoch_seen) > 2000:
                    epoch_seen.clear()

                npx, npy = self.camera.world_to_screen(vx, vy)
                if self._entity_on_screen(npx, npy, screen_size=screen_size):
                    entities.append(('npc', vy, npx, npy, npc, npc_id))

        # Add baddies (enemies). Their x/y are local to the current segment, so
        # fold in that segment's gmap offset to line them up with the world.
        seg_off_x = seg_off_y = 0
        if self.client.gmap_grid:
            seg = next((g for g, n in self.client.gmap_grid.items()
                        if n == self.client._current_level_name), None)
            if seg:
                seg_off_x, seg_off_y = seg[0] * 64, seg[1] * 64
        for bid, baddy in self.client.baddies.items():
            bx = baddy.get('x')
            by = baddy.get('y')
            if bx is None or by is None:
                continue
            wx, wy = bx + seg_off_x, by + seg_off_y
            sx, sy = self.camera.world_to_screen(wx, wy)
            if self._entity_on_screen(sx, sy, screen_size=screen_size):
                entities.append(('baddy', wy, sx, sy, baddy, bid))

        # Add horses (Tier 1a) - other players' PLI_HORSEADD mounts. Local coords
        # like baddies, so fold in the current segment's gmap offset.
        for hkey, horse in self.client.horses.items():
            hx = horse.get('x')
            hy = horse.get('y')
            if hx is None or hy is None:
                continue
            whx, why = hx + seg_off_x, hy + seg_off_y
            hsx, hsy = self.camera.world_to_screen(whx, why)
            if self._entity_on_screen(hsx, hsy, screen_size=screen_size):
                entities.append(('horse', why, hsx, hsy, horse, hkey))

        # Sort by Y for depth
        entities.sort(key=lambda e: e[1])

        # Render each entity
        for entity in entities:
            if entity[0] == 'player':
                self._render_player(entity[2], entity[3], entity[4], self.player_anim)
            elif entity[0] == 'other':
                self._render_other_player(entity[2], entity[3], entity[4], entity[5])
            elif entity[0] == 'npc':
                self._render_npc(entity[2], entity[3], entity[4], entity[5])
            elif entity[0] == 'baddy':
                self._render_baddy(entity[2], entity[3], entity[4], entity[5])
            elif entity[0] == 'horse':
                self._render_horse(entity[2], entity[3], entity[4], entity[5])

        # Weapon image layers — the arena bombs/vases/explosions (world coords)
        # and HUD (screen coords) are painted by the arenaGUI/arenaSYS weapons,
        # which have no NPC/player anchor. Draw the under-player band, then the
        # over-player band (vis>=2), so the floor/bombs sit below and the HUD on
        # top. (Depth-sorting world bombs against players is a later refinement.)
        wimgs = getattr(getattr(self, 'gs1', None), '_weapon_imgs', None)
        if wimgs:
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
            self._render_animated_entity(x, y, anim,
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

    # _render_animated_entity/_render_speech_bubble are shared with NPC/baddy/
    # horse/showani rendering and bake in a canvas shift (-8px) / centre
    # offset (+16px) that assume a 2-tile-wide entity — correct for those
    # other callers, which this task doesn't touch. The player's sprite is
    # honestly 3 tiles wide per the classic-engine spec (48px GANI canvas ==
    # 3 tiles, no fudge), so its true visual centre is x+1.5 tiles (+24px),
    # half a tile right of what those shared helpers assume. Compensate ONLY
    # at these player call sites by shifting the x they see +8px (TILE_SIZE
    # // 2) so their internal -8/+16 math lands on the honest x+24 centre,
    # without changing behavior for any other entity type.
    _PLAYER_ANCHOR_FIX = TILE_SIZE // 2  # 8px: cancels the shared -8px/+16px assumption

    def _render_player(self, x: float, y: float, player: Player, anim: AnimationState):
        """Render the local player with animation."""
        # Check if player should flash (hurt effect)
        hurt_elapsed = time.time() - self.hurt_flash_time
        hurt_visible = True
        if hurt_elapsed < 0.5:  # Flash for 0.5 seconds
            # Blink every 0.1 seconds
            hurt_visible = int(hurt_elapsed * 10) % 2 == 0

        anchor_x = x + self._PLAYER_ANCHOR_FIX
        if hurt_visible:
            self._render_animated_entity(anchor_x, y, anim, {
                'body_image': player.body_image or 'body.png',
                'head_image': player.head_image or 'head0.png',
                'sword_image': player.sword_image or 'sword1.png',
                'shield_image': player.shield_image or 'shield1.png',
                # Tier 2a: PLPROP_COLORS (prop 13), parsed into player.colors
                # by packets.py/player.py, drives the body palette-swap in
                # get_sprite_recolored() (sprites.py).
                'colors': player.colors,
            }, alpha=115 if self.client.ghost_mode else 255)

        # Render carried object above player's head
        if player.is_carrying():
            self._render_carried_object(x, y, player)

        # Render local player's chat bubble (if active and not timed out)
        if self.local_chat_text and time.time() - self.local_chat_time < self.chat_bubble_duration:
            self._render_speech_bubble(anchor_x, y, self.local_chat_text)

        # Render nickname below local player
        nickname = player.nickname or player.account
        status_label = self._status_label(player.status)
        if status_label:
            nickname = f"{nickname} [{status_label}]" if nickname else f"[{status_label}]"
        if nickname:
            name_surf = self._render_text_cached(self.font_small, nickname, (255, 255, 255))
            # Centre on the box/sprite's true horizontal centre, x+1.5 tiles
            # (24px) — the sprite is 3 tiles wide, top-left anchored at x.
            name_x = x - name_surf.get_width() // 2 + int(TILE_SIZE * 1.5)
            name_y = y + 48
            name_x, name_y = self._place_nameplate(name_x, name_y, name_surf.get_size())
            shadow_surf = self._render_text_cached(self.font_small, nickname, (0, 0, 0))
            self.screen.blit(shadow_surf, (name_x + 1, name_y + 1))
            self.screen.blit(name_surf, (name_x, name_y))

        # Debug visualization (feet marker, collision box, tile grid) - F1 only
        if self.debug_mode:
            # Entity position (x, y) is TOP-LEFT of the 3x3-tile sprite.
            # Ground-sample point is the classic-engine spec's collision-box
            # CENTRE: +1.5 tiles right, +2.5 tiles down (collision.py's
            # PLAYER_FEET_DX/DY — the point chairs/pickups/signs interact
            # against and swim/grass/etc are sampled at), not the box's
            # bottom edge.
            feet_x = x + TILE_SIZE * 1.5
            feet_y = y + TILE_SIZE * 2.5

            # Current position marker (red dot at the ground-sample centre)
            pygame.draw.circle(self.screen, (255, 0, 0), (int(feet_x), int(feet_y)), 4)

            # True collision box: 2x2 tiles centred on (feet_x, feet_y),
            # spanning x+0.5..x+2.5 by y+1.5..y+3.5 (collision.py's
            # _FEET_LEFT/_FEET_RIGHT/_FEET_TOP/_FEET_BOTTOM).
            box_left = x + TILE_SIZE * 0.5
            box_right = x + TILE_SIZE * 2.5
            box_top = y + TILE_SIZE * 1.5
            box_bottom = y + TILE_SIZE * 3.5
            collision_rect = pygame.Rect(
                int(box_left), int(box_top),
                int(box_right - box_left), int(box_bottom - box_top)
            )
            pygame.draw.rect(self.screen, (0, 255, 0), collision_rect, 2)

            # Tile grid around player feet
            feet_world_x = self.client.x + 1.5
            feet_world_y = self.client.y + 2.5
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

    def _render_other_player(self, x: float, y: float, pdata: dict, pid: int):
        """Render another player."""
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
            anim.set_animation(player_anim, direction)
            self.other_player_anims[pid] = anim

        anim = self.other_player_anims[pid]

        # Update animation if changed
        current_name = anim.gani.name if anim.gani else ''
        if player_anim != current_name or anim.direction != direction:
            anim.set_animation(player_anim, direction)

        equip = {
            'body_image': pdata.get('body_image', 'body.png'),
            'head_image': pdata.get('head_image', 'head0.png'),
            'sword_image': pdata.get('sword_image', 'sword1.png'),
            'shield_image': pdata.get('shield_image', 'shield1.png'),
            # Tier 2a: PLPROP_COLORS (prop 13), populated by parse_other_player.
            'colors': pdata.get('colors'),
        }
        for i, p in enumerate(gani_params[:5], start=1):
            if p:
                equip[f'attr{i}_image'] = p
        hidden = bool(int(pdata.get('status') or 0) & 0x02)
        # See _render_player's _PLAYER_ANCHOR_FIX comment: the shared
        # animated-entity/speech-bubble helpers assume a 2-tile-wide entity;
        # other players are the same honestly-3-tile-wide sprite as the
        # local player, so cancel that assumption the same way.
        anchor_x = x + self._PLAYER_ANCHOR_FIX
        self._render_animated_entity(anchor_x, y, anim, equip,
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
            name_surf = self._render_text_cached(self.font_small, nickname, (255, 255, 255))
            # Center name below player (player sprite is ~48 pixels tall).
            # True horizontal centre is x+1.5 tiles (24px), same as the local
            # player (see _render_player).
            name_x = x - name_surf.get_width() // 2 + int(TILE_SIZE * 1.5)
            name_y = y + 48
            name_x, name_y = self._place_nameplate(name_x, name_y, name_surf.get_size())
            # Add shadow for readability
            shadow_surf = self._render_text_cached(self.font_small, nickname, (0, 0, 0))
            self.screen.blit(shadow_surf, (name_x + 1, name_y + 1))
            self.screen.blit(name_surf, (name_x, name_y))
    def _place_nameplate(self, name_x: float, name_y: float,
                          size: Tuple[int, int]) -> Tuple[float, float]:
        """Stagger a nameplate vertically if it would overlap one already
        placed this frame. Two players (or an NPC and a player) standing on
        or near the same tile otherwise draw their nickname at the same
        y-offset, producing garbled overlapping text; nudge each subsequent
        overlapper straight down by one box-height until it clears. Reset
        per-frame by _render_entities via self._frame_nameplate_rects."""
        rects = getattr(self, '_frame_nameplate_rects', None)
        if rects is None:
            rects = self._frame_nameplate_rects = []
        w, h = size
        rect = pygame.Rect(int(name_x), int(name_y), int(w), int(h))
        while any(rect.colliderect(r) for r in rects):
            rect.y += h + 2
        rects.append(rect)
        return rect.x, rect.y

    def _render_text_cached(self, font: pygame.font.Font, text: str,
                             color: Tuple[int, int, int]) -> pygame.Surface:
        """Render (and cache) a text surface. Nicknames, speech bubbles and
        showtext layers (_render_showtext_rec) all re-render the same handful
        of strings every frame otherwise; keying on (font identity, text,
        color) lets every caller share one cache. Cleared wholesale once it
        grows large so a chat-heavy session doesn't leak memory."""
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
        if not filename or filename in self._requested_assets:
            return
        self._requested_assets.add(filename)
        try:
            self.client.request_file(filename)
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
        if npc.get('colors'):
            return npc['colors']
        have_any = False
        vals = []
        for i in range(5):
            v = npc.get(f'color{i}')
            if v is not None:
                have_any = True
            try:
                vals.append(int(v))
            except (TypeError, ValueError):
                vals.append(0)
        return vals if have_any else None

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

    def _render_npc(self, x: float, y: float, npc: dict, npc_id: int):
        """Render an NPC."""
        # destroy / hide make the NPC (and its layers) vanish entirely.
        if npc.get('visible') is False:
            return

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

        # Parse and cache visual effects from NPC script and image
        if npc_id not in self.npc_effects:
            script = npc.get('script', '')
            self.npc_effects[npc_id] = parse_npc_visual_effects(script, image_name or '')

        effects = self.npc_effects[npc_id]
        is_light = effects.get('drawaslight', False)
        coloreffect = effects.get('coloreffect')  # (r, g, b, a)

        if gani_name:
            # Use animation
            if npc_id not in self.npc_anims:
                anim = AnimationState(self.gani_parser)
                anim.set_animation(gani_name, npc.get('direction', 2))
                self.npc_anims[npc_id] = anim

            anim = self.npc_anims[npc_id]
            anim.set_animation(gani_name, npc.get('direction', 2))  # cheap no-op if unchanged
            if anim.gani is None:
                # The gani isn't downloaded yet — ask for it and stay invisible
                # (like the missing-image path), rather than drawing the magenta
                # placeholder. It pops in once on_file caches it.
                self._request_asset(gani_name + '.gani')
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
                # Apply visual effects for light NPCs
                if is_light or coloreffect:
                    self._render_light_sprite(sprite, x, y, is_light, coloreffect)
                else:
                    self.screen.blit(sprite, (x, y))
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

        # Render NPC chat bubble if active (and not timed out)
        if npc_id in self.npc_chat_texts:
            text, chat_time = self.npc_chat_texts[npc_id]
            if time.time() - chat_time < self.chat_bubble_duration:
                self._render_speech_bubble(x, y, text)

    # -- GS1 showimg / showtext layers -------------------------------------
    def _render_npc_layers(self, imgs: dict, over: bool):
        """Draw an NPC's GS1 image/text layers. ``changeimgvis`` (vis) is the
        depth: layers at vis>=2 draw in front of the NPC sprite, the rest behind.
        Drawn in index order within each band so overlapping layers stack right."""
        for idx in sorted(imgs):
            rec = imgs[idx]
            if (rec.get('vis', 4) >= 2) != over:
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
            except Exception:
                pass  # a bad layer must never break the frame

    def _layer_pos(self, rec):
        """Screen position of a layer: showimg2/showtext2 are already in screen
        pixels; otherwise the coords are world tiles."""
        if rec.get('screen'):
            return rec.get('x', 0.0), rec.get('y', 0.0)
        return self.camera.world_to_screen(rec.get('x', 0.0), rec.get('y', 0.0))

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

        colors = rec.get('colors')
        additive = rec.get('mode') == 1 or 'light' in image.lower()
        colors_key = tuple(colors) if colors else None

        # Rescaling every frame (even at factor==1) and recoloring every frame
        # is wasted work for a layer that's usually static between server
        # updates - cache the finished (scaled + recolored) surface keyed by
        # everything that can change its pixels.
        cache = getattr(self, '_showimg_cache', None)
        if cache is None:
            cache = self._showimg_cache = {}
        cache_key = (image, part, w, h, colors_key, additive)
        out = cache.get(cache_key)
        if out is None:
            out = sprite if (w, h) == sprite.get_size() else pygame.transform.scale(sprite, (w, h))
            if colors:
                r, g, b, a = colors
                out = out.copy()
                if additive:
                    # fold alpha into the colour so additive blending dims it
                    mult = (_c255(r * a), _c255(g * a), _c255(b * a), 255)
                    out.fill(mult, special_flags=pygame.BLEND_RGB_MULT)
                else:
                    out.fill((_c255(r), _c255(g), _c255(b), 255),
                              special_flags=pygame.BLEND_RGB_MULT)
                    out.set_alpha(_c255(a))
            if len(cache) > 300:
                cache.clear()
            cache[cache_key] = out

        sx, sy = self._layer_pos(rec)
        flags = pygame.BLEND_ADD if additive else 0
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
        passes its 'on' fade timer (counting down from ~2 to 0, see
        arenaGUI.gs1's DrawExpl/CreateExpl) as the first param; use it to
        drive the burst's lifetime instead of a fixed local clock, so it
        stays in sync with the server-driven explosion spread."""
        params = rec.get('params') or []
        try:
            on = float(params[0]) if params else 0.0
        except (TypeError, ValueError):
            on = 0.0
        if on <= 0:
            return
        progress = max(0.0, min(1.0, 1.0 - on / 2.0))
        radius = int(10 + 22 * progress)
        alpha = int(255 * min(1.0, on))
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
        size = max(8, int(16 * (rec.get('zoom') or 1.0) * (self.camera.scale / float(TILE_SIZE))))
        font = self._showtext_font(rec.get('font', '') or 'Arial', size, 'b' in style)
        colors = rec.get('colors')
        col = (_c255(colors[0]), _c255(colors[1]), _c255(colors[2])) if colors else (255, 255, 255)
        surf = self._render_text_cached(font, text, col)
        if colors and len(colors) > 3:
            # set_alpha mutates the surface in place, so operate on our own
            # copy rather than the shared cached one.
            surf = surf.copy()
            surf.set_alpha(_c255(colors[3]))
        sx, sy = self._layer_pos(rec)
        if 'c' in style:  # horizontally centred on the anchor
            sx -= surf.get_width() / 2.0
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
        points = [self.camera.world_to_screen(pts[i], pts[i + 1])
                  for i in range(0, len(pts) - stride + 1, stride)]
        colors = rec.get('colors')
        col = (_c255(colors[0]), _c255(colors[1]), _c255(colors[2]),
               _c255(colors[3]) if len(colors) > 3 else 255) if colors else (255, 255, 255, 255)

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
                              is_light: bool, coloreffect: Optional[Tuple[float, float, float, float]]):
        """Render a sprite with light effects (additive blending, alpha).

        Args:
            sprite: The sprite surface to render
            x, y: Position (top-left of NPC tile, like other NPC images)
            is_light: If True, use additive blending
            coloreffect: (r, g, b, a) multipliers - r,g,b typically 1.0, a is alpha (0-1)
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
            # effects. Render with additive blending for light effect.
            self.screen.blit(light_sprite, (x, y), special_flags=pygame.BLEND_ADD)

            # A light source should also punch through the ambient darkness/
            # tint overlay, not just glow additively on top of an otherwise
            # unchanged dark scene. Queue an erase mask (see
            # _light_tint_eraser) for render_effects.py's _render_screen_tint
            # to subtract from this frame's overlay once every entity has
            # drawn. Only queued when the caller actually reset the list this
            # frame (_render_entities) - render smoke/tests that call this
            # directly without going through the full entity loop just skip
            # the tint-punching side effect.
            sources = getattr(self, '_frame_light_sources', None)
            if sources is not None:
                strength = _c255(alpha_frac)
                sources.append((self._light_tint_eraser(sprite, strength), x, y))
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

    def _light_tint_eraser(self, sprite: pygame.Surface, strength: int) -> pygame.Surface:
        """Cached alpha-only erase mask for punching a drawaslight NPC's
        footprint out of the ambient darkness/tint overlay (consumed by
        render_effects.py's _render_screen_tint via BLEND_RGBA_SUB).

        RGB is zeroed with BLEND_RGBA_MULT so the subtraction only ever
        reduces the overlay's alpha (brightening that spot) without shifting
        its tint color - only the sprite's own alpha channel does the
        erasing, which gives the hole the light's natural soft-edged shape
        instead of a hard rectangle. `strength` scales that alpha down for a
        dim/fading coloreffect, same intensity source as the additive glow
        above.

        Keyed by (sprite identity, strength) and identity-checked like
        _sprite_with_alpha: a bare id()-keyed cache would serve a stale mask
        once the sprite manager's LRU evicts and CPython reuses the freed
        surface's address for an unrelated same-size sprite."""
        cache = getattr(self, '_light_eraser_cache', None)
        if cache is None:
            cache = self._light_eraser_cache = {}
        key = (id(sprite), strength)
        entry = cache.get(key)
        if entry is not None and entry[0] is sprite:
            return entry[1]
        eraser = sprite.copy()
        eraser.fill((0, 0, 0, strength), special_flags=pygame.BLEND_RGBA_MULT)
        if len(cache) > 300:
            cache.clear()
        cache[key] = (sprite, eraser)
        return eraser

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
                # Tier 2b/2d: ATTR1-5 are the gani "PARAM" slots - a hat/prop
                # image supplied either by a `setani ani,param1,param2` call
                # (equipment['attrN_image'], plumbed through by callers from
                # the raw NPC/other-player gani string - see _render_npc /
                # _render_other_player) or, failing that, the gani's own
                # DEFAULTATTRn. Per the reference client (the C# client's
                # Animation.cs), DEFAULTATTRn is purely opt-in per-gani text -
                # there's no universal "hat0.png" fallback when a gani defines
                # an ATTR1 sprite layer without a DEFAULTATTR1 line, so render
                # nothing rather than inventing a hat.
                img = equipment.get(f'{layer.lower()}_image') or anim.gani.defaults.get(layer, '')
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

        if not frame:
            # Fallback to placeholder - position at top-left
            sprite = self._sprite_with_alpha(self.placeholder_sprite, alpha)
            self.screen.blit(sprite, (x, y))
            return

        # Gani sprite positions are relative to a 48px-wide frame canvas with
        # the character CENTERED in it (idle.gani places body/head at x=8,
        # shadow center 23.5 — canvas center 24). Entity position (x, y) is
        # the top-left of the 2-tile (32px) logical box, so anchor the canvas
        # 8px left to line the character up with its box: body center lands
        # at x+15.5, matching the collision feet box, the nametag, and the
        # carried-object blit (all of which center on the box). Vertical
        # needs no shift — body y=16..47 already puts feet in the y+2..y+3
        # collision rows.
        base_offset_x = -(48 - TILE_SIZE * 2) // 2
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
