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


class EntityRenderMixin:
    """Mixin providing the above methods for GameClient."""

    def _entity_on_screen(self, px: float, py: float, margin: int = 96) -> bool:
        """True if a sprite at screen pixel (px, py) is near enough the canvas to
        be worth drawing. Levels can carry dozens of NPCs spread across 64x64;
        culling the off-screen ones skips their load_sheet/blit work entirely.
        Bounds come from self.screen so it adapts to the zoom scene surface."""
        w, h = self.screen.get_size()
        return -margin <= px <= w + margin and -margin <= py <= h + margin

    def _render_entities(self):
        """Render all entities (players, NPCs) sorted by Y position."""
        entities = []

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
                if self._entity_on_screen(opx, opy):
                    entities.append(('other', vy, opx, opy, pdata, pid))

        # Add NPCs - use world coords if available (for GMAP), else local
        for npc_id, npc in self.client.npcs.items():
            # Prefer world coords (converted from local + grid offset)
            nx = npc.get('world_x', npc.get('x'))
            ny = npc.get('world_y', npc.get('y'))
            if nx is not None and ny is not None:
                # Interpolate NPC position for smooth movement
                if npc_id in self.npc_visual:
                    vx, vy = self.npc_visual[npc_id]
                    lerp = min(1.0, self.lerp_speed * self._frame_dt)
                    vx += (nx - vx) * lerp
                    vy += (ny - vy) * lerp
                    self.npc_visual[npc_id] = (vx, vy)
                else:
                    vx, vy = nx, ny
                    self.npc_visual[npc_id] = (vx, vy)

                npx, npy = self.camera.world_to_screen(vx, vy)
                if self._entity_on_screen(npx, npy):
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
            if self._entity_on_screen(sx, sy):
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
            if self._entity_on_screen(hsx, hsy):
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
        """Render a baddy as a gani entity (the C# client's style). The server-reported
        mode picks the animation (walk/idle/hurt/dead), direction faces it, and a
        per-type head over body.png makes the enemy readable. Falls back to a red
        marker only if the gani system can't produce a frame."""
        mode = baddy.get('mode', 2)
        direction = baddy.get('direction', 2)

        # Prefer a server-supplied gani; otherwise drive one from the mode.
        gani_name = (baddy.get('gani') or baddy.get('ani')
                     or _BADDY_MODE_GANI.get(mode, "walk"))

        anim = self.baddy_anims.get(baddy_id)
        if anim is None:
            anim = AnimationState(self.gani_parser)
            self.baddy_anims[baddy_id] = anim
        # set_animation no-ops when the name is unchanged, so this is cheap to
        # call every frame; it also keeps the facing direction in sync.
        anim.set_animation(gani_name, direction)

        if anim.gani is not None:
            # Hurt baddies blink so a hit reads even when the mode reverts fast.
            if mode == 3 and int(time.time() * 10) % 2 == 0:
                return
            head = _BADDY_HEADS.get(baddy.get('type', 0), _BADDY_DEFAULT_HEAD)
            self._render_animated_entity(x, y, anim,
                                         {'head_image': head, 'body_image': 'body.png'})
            return

        # The gani isn't downloaded yet — ask for it and stay invisible,
        # matching the NPC gani-fallback convention elsewhere in this file
        # (_render_npc), rather than drawing a placeholder primitive. It pops
        # in once on_file caches it.
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

    def _render_player(self, x: float, y: float, player: Player, anim: AnimationState):
        """Render the local player with animation."""
        # Check if player should flash (hurt effect)
        hurt_elapsed = time.time() - self.hurt_flash_time
        hurt_visible = True
        if hurt_elapsed < 0.5:  # Flash for 0.5 seconds
            # Blink every 0.1 seconds
            hurt_visible = int(hurt_elapsed * 10) % 2 == 0

        if hurt_visible:
            self._render_animated_entity(x, y, anim, {
                'body_image': player.body_image or 'body.png',
                'head_image': player.head_image or 'head0.png',
                'sword_image': player.sword_image or 'sword1.png',
                'shield_image': player.shield_image or 'shield1.png',
                # Tier 2a: PLPROP_COLORS (prop 13), parsed into player.colors
                # by packets.py/player.py, drives the body palette-swap in
                # get_sprite_recolored() (sprites.py).
                'colors': player.colors,
            })

        # Render carried object above player's head
        if player.is_carrying():
            self._render_carried_object(x, y, player)

        # Render local player's chat bubble (if active and not timed out)
        if self.local_chat_text and time.time() - self.local_chat_time < self.chat_bubble_duration:
            self._render_speech_bubble(x, y, self.local_chat_text)

        # Render nickname below local player
        nickname = player.nickname or player.account
        status_label = self._status_label(player.status)
        if status_label:
            nickname = f"{nickname} [{status_label}]" if nickname else f"[{status_label}]"
        if nickname:
            name_surf = self._render_text_cached(self.font_small, nickname, (255, 255, 255))
            name_x = x - name_surf.get_width() // 2 + 16
            name_y = y + 48
            shadow_surf = self._render_text_cached(self.font_small, nickname, (0, 0, 0))
            self.screen.blit(shadow_surf, (name_x + 1, name_y + 1))
            self.screen.blit(name_surf, (name_x, name_y))

        # Debug visualization (feet marker, collision box, tile grid) - F1 only
        if self.debug_mode:
            # Entity position (x, y) is TOP-LEFT of sprite bounding box.
            # Feet/shadow are at BOTTOM-CENTER: +1 tile right, +3 tiles down.
            feet_x = x + TILE_SIZE
            feet_y = y + TILE_SIZE * 3

            # Current position marker (red dot at feet)
            pygame.draw.circle(self.screen, (255, 0, 0), (int(feet_x), int(feet_y)), 4)

            # Collision box around player feet
            box_left = feet_x - 0.3 * TILE_SIZE
            box_right = feet_x + 0.3 * TILE_SIZE
            box_top = feet_y - 0.5 * TILE_SIZE
            collision_rect = pygame.Rect(
                int(box_left), int(box_top),
                int(box_right - box_left), int(feet_y - box_top)
            )
            pygame.draw.rect(self.screen, (0, 255, 0), collision_rect, 2)

            # Tile grid around player feet
            feet_world_x = self.client.x + 1.0
            feet_world_y = self.client.y + 3.0
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

        # (x, y) is the sprite's top-left; the sprite is ~2 tiles wide (center at
        # x + TILE_SIZE) with the head near the top. Hold the object centered
        # over the head, resting just above it.
        obj_x = (x + TILE_SIZE) - obj_width // 2
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
    def _render_other_player(self, x: float, y: float, pdata: dict, pid: int):
        """Render another player."""
        # Get animation name - could be 'ani' or 'animation'. Tier 2d: a
        # `setani ani,param1,param2` server prop keeps its params comma-joined
        # onto the gani name here; split them off so param images can drive
        # ATTR1-5 layers (e.g. a scripted hat) instead of being discarded.
        player_anim = pdata.get('ani') or pdata.get('animation') or 'idle'
        gani_params: List[str] = []
        if ',' in player_anim:
            parts = [p.strip() for p in player_anim.split(',')]
            player_anim = parts[0] or 'idle'
            gani_params = parts[1:]
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
        self._render_animated_entity(x, y, anim, equip)

        # Render chat bubble above player (if they have chat text)
        chat_text = pdata.get('chat', '')
        if chat_text:
            self._render_speech_bubble(x, y, chat_text)

        # Render nickname below player
        nickname = pdata.get('nick') or pdata.get('nickname') or pdata.get('account') or ''
        status_label = self._status_label(pdata.get('status'))
        if status_label:
            nickname = f"{nickname} [{status_label}]" if nickname else f"[{status_label}]"
        if nickname:
            name_surf = self._render_text_cached(self.font_small, nickname, (255, 255, 255))
            # Center name below player (player sprite is ~48 pixels tall)
            name_x = x - name_surf.get_width() // 2 + 16
            name_y = y + 48
            # Add shadow for readability
            shadow_surf = self._render_text_cached(self.font_small, nickname, (0, 0, 0))
            self.screen.blit(shadow_surf, (name_x + 1, name_y + 1))
            self.screen.blit(name_surf, (name_x, name_y))
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
            parts = [p.strip() for p in gani_name.split(',')]
            gani_name = parts[0].strip()
            gani_params = parts[1:]
        image_name = npc.get('image')
        is_character = npc.get('is_character')
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
                        'body_image': npc.get('body_image') or 'body.png',
                        'head_image': npc.get('head_image') or 'head0.png',
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

    def _render_light_sprite(self, sprite: pygame.Surface, x: float, y: float,
                              is_light: bool, coloreffect: Optional[Tuple[float, float, float, float]]):
        """Render a sprite with light effects (additive blending, alpha).

        Args:
            sprite: The sprite surface to render
            x, y: Position (top-left of NPC tile, like other NPC images)
            is_light: If True, use additive blending
            coloreffect: (r, g, b, a) multipliers - r,g,b typically 1.0, a is alpha (0-1)
        """
        # Alpha is typically like 0.99 (99% opacity but as a light effect).
        # copy()+set_alpha() every frame per light NPC is wasted work since the
        # same (sprite, alpha) pair repeats frame to frame - cache the result.
        alpha = int(coloreffect[3] * 255) if coloreffect else None
        cache = getattr(self, '_light_sprite_cache', None)
        if cache is None:
            cache = self._light_sprite_cache = {}
        key = (id(sprite), alpha)
        light_sprite = cache.get(key)
        if light_sprite is None:
            light_sprite = sprite.copy()
            if alpha is not None:
                light_sprite.set_alpha(alpha)
            if len(cache) > 300:
                cache.clear()
            cache[key] = light_sprite

        # Position - place light sprite with top-left at NPC position
        # User testing confirmed this positioning is correct for light effects
        if is_light:
            # Render with additive blending for light effect
            self.screen.blit(light_sprite, (x, y), special_flags=pygame.BLEND_ADD)
        else:
            # Just render with alpha
            self.screen.blit(light_sprite, (x, y))
    def _render_animated_entity(self, x: float, y: float, anim: AnimationState,
                                  equipment: dict):
        """Render an entity using gani animation.

        The gani offsets position sprites within a bounding box.
        Position (x, y) is the top-left of the entity's tile position.
        """
        frame = anim.get_frame() if anim.gani else None

        if not frame:
            # Fallback to placeholder - position at top-left
            self.screen.blit(self.placeholder_sprite, (x, y))
            return

        # No base offset - gani sprite positions are relative to entity position
        # Entity position (x, y) is the top-left of the tile
        base_offset_x = 0
        base_offset_y = 0

        # Render each sprite in the frame
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
                img = anim.gani.defaults.get('SPRITES', 'sprites.png')
                # Special case: shadow sprite (id 0) - render our shadow
                if sprite_id == 0:
                    screen_x = x + base_offset_x + ox
                    screen_y = y + base_offset_y + oy
                    self.screen.blit(self.shadow_sprite, (screen_x, screen_y))
                    continue
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

            # Get sprite from sheet. BODY goes through the palette-swap path
            # when a colors prop is available (Tier 2a - see sprites.py and
            # PLPROP_COLORS parsing in packets.py/player.py).
            if layer == "BODY" and equipment.get('colors'):
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
                # Calculate screen position: base offset + gani sprite offset
                screen_x = x + base_offset_x + ox
                screen_y = y + base_offset_y + oy
                self.screen.blit(sprite, (screen_x, screen_y))
