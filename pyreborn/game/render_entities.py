"""EntityRenderMixin — players, NPCs, speech bubbles, animated sprites.

Split from render.py; methods operate on the GameClient instance."""

import time
import json
import re
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


def _c255(v: float) -> int:
    """Clamp a 0..1 GS1 colour/alpha multiplier to a 0..255 byte."""
    return max(0, min(255, int(float(v) * 255)))


# Baddy mode (BDMODE) -> gani animation name. Mirrors GServer-v2's BaddyMode
# enum. Preagonal renders baddies as gani entities rather than blitting a raw
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

# Per-type head over body.png, the way Preagonal's classic_baddy_graanch ganis
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

                if self.client.gmap_grid:
                    found = False
                    if player_level:
                        for (gx, gy), level_name in self.client.gmap_grid.items():
                            if level_name == player_level:
                                world_x = ox + gx * 64
                                world_y = oy + gy * 64
                                found = True
                                break

                    # If no level set, assume same sub-level as local player
                    if not found and self.client._current_level_name:
                        for (gx, gy), level_name in self.client.gmap_grid.items():
                            if level_name == self.client._current_level_name:
                                world_x = ox + gx * 64
                                world_y = oy + gy * 64
                                break

                # Smooth interpolation for other players
                if pid in self.other_player_visual:
                    vx, vy = self.other_player_visual[pid]
                    # Interpolate toward target position
                    lerp = min(1.0, self.lerp_speed * 0.033)  # Assume ~30fps
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
                    lerp = min(1.0, self.lerp_speed * 0.033)
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
    def _render_baddy(self, x: float, y: float, baddy: dict, baddy_id: int):
        """Render a baddy as a gani entity (Preagonal style). The server-reported
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

        # Fallback marker: a red body so the enemy is visible.
        body = pygame.Surface((24, 24), pygame.SRCALPHA)
        pygame.draw.circle(body, (200, 40, 40), (12, 12), 11)
        pygame.draw.circle(body, (90, 0, 0), (12, 12), 11, 2)
        pygame.draw.circle(body, (255, 230, 230), (8, 9), 2)
        pygame.draw.circle(body, (255, 230, 230), (16, 9), 2)
        self.screen.blit(body, (int(x), int(y)))
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
            })

        # Render carried object above player's head
        if player.is_carrying():
            self._render_carried_object(x, y, player)

        # Render local player's chat bubble (if active and not timed out)
        if self.local_chat_text and time.time() - self.local_chat_time < self.chat_bubble_duration:
            self._render_speech_bubble(x, y, self.local_chat_text)

        # Render nickname below local player
        nickname = player.nickname or player.account
        if nickname:
            name_surf = self.font_small.render(nickname, True, (255, 255, 255))
            name_x = x - name_surf.get_width() // 2 + 16
            name_y = y + 48
            shadow_surf = self.font_small.render(nickname, True, (0, 0, 0))
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
        # Get animation name - could be 'ani' or 'animation'
        player_anim = pdata.get('ani') or pdata.get('animation') or 'idle'
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

        self._render_animated_entity(x, y, anim, {
            'body_image': pdata.get('body_image', 'body.png'),
            'head_image': pdata.get('head_image', 'head0.png'),
            'sword_image': pdata.get('sword_image', 'sword1.png'),
            'shield_image': pdata.get('shield_image', 'shield1.png'),
        })

        # Render chat bubble above player (if they have chat text)
        chat_text = pdata.get('chat', '')
        if chat_text:
            self._render_speech_bubble(x, y, chat_text)

        # Render nickname below player
        nickname = pdata.get('nick') or pdata.get('account') or ''
        if nickname:
            name_surf = self.font_small.render(nickname, True, (255, 255, 255))
            # Center name below player (player sprite is ~48 pixels tall)
            name_x = x - name_surf.get_width() // 2 + 16
            name_y = y + 48
            # Add shadow for readability
            shadow_surf = self.font_small.render(nickname, True, (0, 0, 0))
            self.screen.blit(shadow_surf, (name_x + 1, name_y + 1))
            self.screen.blit(name_surf, (name_x, name_y))
    def _render_speech_bubble(self, x: float, y: float, text: str):
        """Render a speech bubble above an entity."""
        if not text:
            return

        # Render text with word wrapping (max ~15 chars per line)
        max_width = 120
        words = text.split()
        lines = []
        current_line = ""

        for word in words:
            test_line = current_line + (" " if current_line else "") + word
            test_surf = self.font_small.render(test_line, True, (0, 0, 0))
            if test_surf.get_width() > max_width and current_line:
                lines.append(current_line)
                current_line = word
            else:
                current_line = test_line

        if current_line:
            lines.append(current_line)

        # Limit to 3 lines max
        lines = lines[:3]

        # Calculate bubble dimensions
        line_height = 14
        padding = 4
        bubble_height = len(lines) * line_height + padding * 2
        bubble_width = max(self.font_small.render(line, True, (0, 0, 0)).get_width() for line in lines) + padding * 2

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
            text_surf = self.font_small.render(line, True, (0, 0, 0))
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
        if gani_name:
            gani_name = gani_name.split(',')[0].strip()  # setcharani arg keeps a ','
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
                    }
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
                # INVISIBLE until it arrives (real Graal does), rather than
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
                elif rec.get('image'):
                    self._render_showimg_rec(rec)
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
        sprite = pygame.transform.scale(sprite, (w, h))

        colors = rec.get('colors')
        additive = rec.get('mode') == 1 or 'light' in image.lower()
        if colors:
            r, g, b, a = colors
            sprite = sprite.copy()
            if additive:
                # fold alpha into the colour so additive blending dims it
                mult = (_c255(r * a), _c255(g * a), _c255(b * a), 255)
                sprite.fill(mult, special_flags=pygame.BLEND_RGB_MULT)
            else:
                sprite.fill((_c255(r), _c255(g), _c255(b), 255),
                            special_flags=pygame.BLEND_RGB_MULT)
                sprite.set_alpha(_c255(a))
        sx, sy = self._layer_pos(rec)
        flags = pygame.BLEND_ADD if additive else 0
        self.screen.blit(sprite, (int(sx), int(sy)), special_flags=flags)

    def _render_showtext_rec(self, rec: dict):
        text = rec.get('text', '')
        if not text:
            return
        style = rec.get('style', '') or ''
        size = max(8, int(16 * (rec.get('zoom') or 1.0) * (self.camera.scale / float(TILE_SIZE))))
        font = self._showtext_font(rec.get('font', '') or 'Arial', size, 'b' in style)
        colors = rec.get('colors')
        col = (_c255(colors[0]), _c255(colors[1]), _c255(colors[2])) if colors else (255, 255, 255)
        surf = font.render(text, True, col)
        if colors and len(colors) > 3:
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
    def _render_light_sprite(self, sprite: pygame.Surface, x: float, y: float,
                              is_light: bool, coloreffect: Optional[Tuple[float, float, float, float]]):
        """Render a sprite with light effects (additive blending, alpha).

        Args:
            sprite: The sprite surface to render
            x, y: Position (top-left of NPC tile, like other NPC images)
            is_light: If True, use additive blending
            coloreffect: (r, g, b, a) multipliers - r,g,b typically 1.0, a is alpha (0-1)
        """
        # Create a copy of the sprite for modification
        light_sprite = sprite.copy()

        # Apply color effect (alpha)
        if coloreffect:
            r, g, b, a = coloreffect
            # Alpha is typically like 0.99 (99% opacity but as a light effect)
            alpha = int(a * 255)
            light_sprite.set_alpha(alpha)

        # Position - place light sprite with top-left at NPC position
        # User testing confirmed this positioning is correct for light effects
        pos_x = x
        pos_y = y

        if is_light:
            # Render with additive blending for light effect
            self.screen.blit(light_sprite, (pos_x, pos_y), special_flags=pygame.BLEND_ADD)
        else:
            # Just render with alpha
            self.screen.blit(light_sprite, (pos_x, pos_y))
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
        for sprite_id, ox, oy in frame.sprites:
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
            elif layer == "ATTR1":
                img = anim.gani.defaults.get('ATTR1', 'hat0.png')
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
                if '.' in layer:
                    img = layer.lower()
                else:
                    img = anim.gani.defaults.get(layer, 'sprites.png')

            # Get sprite from sheet
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
