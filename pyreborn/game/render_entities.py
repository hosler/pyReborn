"""EntityRenderMixin — players, NPCs, speech bubbles, animated sprites.

Split from render.py; methods operate on the GameClient instance."""

import time
from typing import List, Optional, Tuple

import pygame

from ..gani import AnimationState
from ..npc_handler import CHARACTER_IMAGE
from ..player import Player
from ..sprites import palette_name_to_index
from .frame_context import FrameContext, FrameContextMixin
from .constants import (
    TILE_SIZE, parse_npc_visual_effects,
    PLAYER_COLLISION_LEFT, PLAYER_COLLISION_RIGHT,
    PLAYER_COLLISION_TOP, PLAYER_COLLISION_BOTTOM,
    PLAYER_STAND_X, PLAYER_STAND_Y,
)


# ATTRn sprite-layer slots a character gani can address (ATTR1..ATTR5, fed by
# PLPROP_GATTRIB1..5 / #P1..#P5).
ATTR_SLOTS = 5


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


from .render_shared import (
    BaddySheet, _BADDY_DEFAULT_IMAGE, _BADDY_IMAGES, _Entity,
    _layer_colors,
)
from .render_collect import EntityCollectMixin
from .render_gani import GaniRenderMixin
from .render_layers import LayerRenderMixin
from .render_text import RenderTextMixin


class EntityRenderMixin(
        EntityCollectMixin, RenderTextMixin, LayerRenderMixin, GaniRenderMixin,
        FrameContextMixin):
    """Mixin providing the above methods for GameClient."""

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

    @staticmethod
    def _gani_drawn_sprite_ids(gani, defaults) -> set:
        """The sprite ids some frame of `gani` actually places.

        PARAMn frame tokens resolve against the gani's own DEFAULTPARAMn, the
        same fallback _resolve_frame_sprites uses when the showani/setani call
        passed no value for that slot; a caller-supplied param is unknowable
        here and stays on the lazy blit-time path.
        """
        ids = set()
        directions = getattr(gani, 'directions', ())
        if not isinstance(directions, (list, tuple)):
            return ids
        for frames in directions:
            if not isinstance(frames, (list, tuple)):
                continue
            for frame in frames:
                for placement in getattr(frame, 'sprites', None) or ():
                    try:
                        raw = placement[0]
                    except (TypeError, IndexError, KeyError):
                        continue
                    if isinstance(raw, str):
                        raw = defaults.get(raw)
                    try:
                        ids.add(int(float(raw)))
                    except (TypeError, ValueError):
                        continue
        return ids

    def _prefetch_gani_assets(self, gani) -> None:
        """Request the static sprite sheets a parsed animation actually draws.

        Only layers reached by a sprite that some frame places are requested.
        A gani's DEFAULT* block routinely names sheets no frame ever uses (and
        SPRITE lines routinely define sprites no frame ever places), so asking
        for the whole block made the server log a refusal per name it doesn't
        have - which is what trips --behaviour's no_new_warnings invariant -
        for art that would never have been blitted anyway.
        """
        try:
            name = getattr(gani, 'name', None)
            prefetched = getattr(self, '_prefetched_gani_names', None)
            if prefetched is None:
                prefetched = self._prefetched_gani_names = set()
            guardable_name = isinstance(name, str)
            if guardable_name and name in prefetched:
                return

            defaults = getattr(gani, 'defaults', None)
            if not isinstance(defaults, dict):
                defaults = {}
            sprites = getattr(gani, 'sprites', None)
            if not isinstance(sprites, dict):
                sprites = {}

            filenames = set()
            for sprite_id in self._gani_drawn_sprite_ids(gani, defaults):
                layer = getattr(sprites.get(sprite_id), 'layer', None)
                if not isinstance(layer, str):
                    continue
                if '.' in layer:
                    # A literal-filename layer (itsasign2's SIGN1.GIF) is used
                    # directly by the renderer; defaults are not consulted.
                    filenames.add(layer.lower())
                    continue
                filename = defaults.get(layer)
                if isinstance(filename, str) and '.' in filename:
                    filenames.add(filename)

            if guardable_name:
                prefetched.add(name)
            # These are exactly the static filenames the frame blit fallback
            # eventually discovers, but requesting the set here avoids
            # serializing one server round trip behind each frame/direction.
            # Entity-owned equipment images stay at their existing call sites.
            for filename in filenames:
                self._request_asset(filename)
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
        depth: vis 0 draws behind the NPC, vis 1 joins the live frame's entity
        depth sort, and vis>=2 draws in front of the NPC sprite.
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
            if (not gui and rec.get('vis', 4) == 1
                    and self._frame_context().sorts_world_layers()):
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
            self._render_layer_rec(rec)

    def _render_layer_rec(self, rec: dict) -> None:
        """Render one image, animation, text or polygon layer safely."""
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
                # Live particles ride their layer's pass/stratum.
                self._render_layer_emitter(rec, emitter)
        except Exception:
            pass  # A bad layer must never break the frame.
