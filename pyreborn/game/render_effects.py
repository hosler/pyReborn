"""EffectsRenderMixin — damage numbers, bombs, projectiles, explosions.

Split from render.py; methods operate on the GameClient instance."""

import time
import json
import math
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
from ..prefs import Prefs
from ..tiletypes import TileType, get_tile_type
from .constants import (
    TILE_CORRECTIONS_FILE, TILE_SIZE, SCREEN_WIDTH, SCREEN_HEIGHT,
    TILESET_COLS, TILESET_ROWS, MOVE_STEP, parse_npc_visual_effects,
)


def day_night_tint(minute_of_day):
    """Return the ambient overlay tint for a minute in the daily cycle."""
    minute = minute_of_day % 1440
    night = (10, 10, 45, 110)
    day = (10, 10, 45, 0)

    if 420 <= minute < 1140:
        return None
    if 1260 <= minute or minute < 300:
        return night
    if 1140 <= minute < 1260:
        progress = (minute - 1140) / 120
        return tuple(round(start + (end - start) * progress)
                     for start, end in zip(day, night))

    progress = (minute - 300) / 120
    tint = tuple(round(start + (end - start) * progress)
                 for start, end in zip(night, day))
    return tint if tint[3] else None


class EffectsRenderMixin:
    """Mixin providing the above methods for GameClient."""

    # -- Combat-effect asset loading -----------------------------------
    # bomb/explosion/arrow/firespy used to draw as flashing/concentric
    # primitives; these load the real assets through the same
    # SpriteManager/GaniParser caches (and _request_asset, defined in
    # render_entities.py) NPCs and players already use, falling back to the
    # primitives below whenever the asset isn't downloaded (yet, or ever -
    # not every server ships these).
    def _get_effect_gani(self, name: str):
        """Look up a cached object-effect gani (bomb/explosion/arrow/firespy),
        requesting it from the server exactly once (via _request_asset) if we
        don't have it cached yet. Returns None until it arrives."""
        gani = self.gani_parser.parse(name)
        if gani is None:
            self._request_asset(name + '.gani')
        return gani

    def _get_effect_sprite(self, filename: str):
        """Look up a cached static effect image (e.g. bomb.gif/arrow.gif),
        requesting it from the server exactly once if missing."""
        sprite = self.sprite_mgr.load_sheet(filename)
        if sprite is None:
            self._request_asset(filename)
        return sprite

    def _render_effect_gani_frame(self, gani, screen_x: float, screen_y: float,
                                   direction: int, elapsed: float):
        """Draw one frame of an object-effect gani, picked by elapsed time
        (loops/clamps exactly like AnimationState.update, see gani.py's
        Gani.get_frame) without needing a persistent per-instance
        AnimationState - bombs/explosions/arrows already track their own
        elapsed time in the caller's dict.

        Centered on (screen_x, screen_y): unlike players/NPCs (top-left, see
        CLAUDE.md), these effect coordinates are drop/impact POINTS - the
        primitives they replace were drawn centered there too (circles/
        triangles at that exact point), so a plain TILE_SIZE offset keeps the
        same placement."""
        anim = AnimationState(self.gani_parser)
        anim.gani = gani
        anim.direction = direction
        anim.frame = int(max(0.0, elapsed) / AnimationState.FRAME_DURATION)
        ox = screen_x - TILE_SIZE / 2
        oy = screen_y - TILE_SIZE / 2
        self._render_animated_entity(ox, oy, anim, {})

    def _render_effect_sprite_image(self, sprite: pygame.Surface, screen_x: float,
                                     screen_y: float, direction: Optional[int] = None):
        """Blit a static (non-gani) effect sprite centered on (screen_x,
        screen_y), rotated to face `direction` if given. The base image is
        assumed to face up (direction 0), matching the 0=up/1=left/2=down/
        3=right convention used everywhere else in this module."""
        img = sprite
        if direction is not None:
            angle = {0: 0, 1: 90, 2: 180, 3: -90}.get(direction, 0)
            if angle:
                img = pygame.transform.rotate(sprite, angle)
        w, h = img.get_size()
        self.screen.blit(img, (screen_x - w / 2, screen_y - h / 2))

    def _render_damage_numbers(self):
        """Render floating damage numbers."""
        current_time = time.time()


        # Update and render each damage number
        active_numbers = []
        for dmg in self.damage_numbers:
            elapsed = current_time - dmg['time']
            if elapsed < dmg['duration']:
                # Calculate position (float up over time)
                float_offset = elapsed * 30  # Float up 30 pixels per second
                alpha = int(255 * (1.0 - elapsed / dmg['duration']))

                # Convert world position to screen position
                screen_x, screen_y = self.camera.world_to_screen(dmg['x'], dmg['y'])
                screen_y -= float_offset

                # Render damage text
                damage_text = str(int(dmg['damage'] * 2))  # Display as half-hearts
                text_surf = self.font.render(damage_text, True, (255, 50, 50))
                text_surf.set_alpha(alpha)

                # Shadow
                shadow_surf = self.font.render(damage_text, True, (0, 0, 0))
                shadow_surf.set_alpha(alpha)

                self.screen.blit(shadow_surf, (screen_x + 1, screen_y + 1))
                self.screen.blit(text_surf, (screen_x, screen_y))

                active_numbers.append(dmg)

        self.damage_numbers = active_numbers
    def _render_bomb_ticking(self, screen_x: float, screen_y: float, elapsed: float):
        """Draw a still-ticking bomb: bomb.gif (or the standard bomb gani) if
        the asset has arrived, else the original flashing-circle primitive."""
        sprite = self._get_effect_sprite('bomb.gif')
        if sprite is not None:
            self._render_effect_sprite_image(sprite, screen_x, screen_y)
            # Fuse spark on top - a static image has no animated fuse of its own.
            pygame.draw.circle(self.screen, (255, 200, 50),
                               (int(screen_x + 4), int(screen_y - 8)), 3)
            return
        gani = self._get_effect_gani('bomb')
        if gani is not None:
            self._render_effect_gani_frame(gani, screen_x, screen_y, 2, elapsed)
            return
        # Fallback primitive (unchanged look).
        pygame.draw.circle(self.screen, (50, 50, 50), (int(screen_x), int(screen_y)), 8)
        pygame.draw.circle(self.screen, (30, 30, 30), (int(screen_x), int(screen_y)), 6)
        pygame.draw.circle(self.screen, (255, 200, 50),
                           (int(screen_x + 4), int(screen_y - 8)), 3)

    def _render_explosion_burst(self, screen_x: float, screen_y: float, elapsed: float,
                                 radius: int, alpha: int):
        """Draw an explosion: the classic explosion gani if it's been
        downloaded, else the original concentric-circle primitive sized to
        `radius`/`alpha`."""
        gani = self._get_effect_gani('explosion')
        if gani is not None:
            self._render_effect_gani_frame(gani, screen_x, screen_y, 2, elapsed)
            return
        if radius <= 0 or alpha <= 0:
            return
        explosion_surf = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        pygame.draw.circle(explosion_surf, (255, 150, 50, alpha), (radius, radius), radius)
        pygame.draw.circle(explosion_surf, (255, 100, 0, alpha), (radius, radius), int(radius * 0.7))
        pygame.draw.circle(explosion_surf, (255, 200, 100, alpha), (radius, radius), int(radius * 0.4))
        self.screen.blit(explosion_surf, (screen_x - radius, screen_y - radius))

    def _render_bombs(self):
        """Render active bombs and explosions."""
        current_time = time.time()


        active_bombs = []
        for bomb in self.active_bombs:
            elapsed = current_time - bomb['time']

            # Convert world position to screen position
            screen_x, screen_y = self.camera.world_to_screen(bomb['x'], bomb['y'])

            if not bomb['exploded'] and elapsed < self.bomb_fuse_time:
                # Bomb is still counting down - render bomb sprite
                # Flash faster as fuse runs out
                flash_rate = 5 + (elapsed / self.bomb_fuse_time) * 10
                if int(elapsed * flash_rate) % 2 == 0:
                    self._render_bomb_ticking(screen_x, screen_y, elapsed)
                active_bombs.append(bomb)

            elif elapsed < self.bomb_fuse_time + self.explosion_duration:
                # Explosion phase
                if not bomb['exploded']:
                    bomb['exploded'] = True
                    # Play explosion sound
                    self.sound_mgr.play("explode.wav")

                explosion_elapsed = elapsed - self.bomb_fuse_time
                explosion_progress = explosion_elapsed / self.explosion_duration

                # Expanding explosion radius
                radius = int(16 + bomb['power'] * 16 * explosion_progress)
                alpha = int(255 * (1.0 - explosion_progress))

                self._render_explosion_burst(screen_x, screen_y, explosion_elapsed, radius, alpha)
                active_bombs.append(bomb)
            # else: bomb finished, don't add to active list

        self.active_bombs = active_bombs
    # Fallback triangle colors, keyed by the projectile's 'gani' name -
    # 'arrow' (the default, matching the classic brown arrow it replaces)
    # and 'firespy' (a distinct fire-orange, so a fireball doesn't look like
    # a wooden arrow when the asset hasn't downloaded).
    _PROJECTILE_FALLBACK_COLORS = {
        'firespy': ((255, 120, 30), (200, 70, 10)),
    }
    _DEFAULT_PROJECTILE_COLORS = ((139, 69, 19), (80, 40, 10))  # brown arrow

    def _render_projectile_marker(self, kind: str, screen_x: float, screen_y: float,
                                   direction: int, elapsed: float):
        """Draw one projectile (arrow or firespy fireball): the named static
        sprite (e.g. arrow.gif) if downloaded, else its gani, else a
        directional triangle primitive."""
        sprite = self._get_effect_sprite(f'{kind}.gif')
        if sprite is not None:
            self._render_effect_sprite_image(sprite, screen_x, screen_y, direction)
            return
        gani = self._get_effect_gani(kind)
        if gani is not None:
            self._render_effect_gani_frame(gani, screen_x, screen_y, direction, elapsed)
            return
        if direction == 0:  # up
            points = [(screen_x, screen_y - 8), (screen_x - 3, screen_y + 4), (screen_x + 3, screen_y + 4)]
        elif direction == 1:  # left
            points = [(screen_x - 8, screen_y), (screen_x + 4, screen_y - 3), (screen_x + 4, screen_y + 3)]
        elif direction == 2:  # down
            points = [(screen_x, screen_y + 8), (screen_x - 3, screen_y - 4), (screen_x + 3, screen_y - 4)]
        else:  # right
            points = [(screen_x + 8, screen_y), (screen_x - 4, screen_y - 3), (screen_x - 4, screen_y + 3)]
        fill, outline = self._PROJECTILE_FALLBACK_COLORS.get(kind, self._DEFAULT_PROJECTILE_COLORS)
        pygame.draw.polygon(self.screen, fill, points)
        pygame.draw.polygon(self.screen, outline, points, 1)

    def _update_and_render_projectiles(self, dt: float):
        """Update and render active projectiles."""
        current_time = time.time()


        active_projectiles = []
        for proj in self.active_projectiles:
            # Update position
            proj['x'] += proj['dx'] * dt
            proj['y'] += proj['dy'] * dt

            # Check if projectile exceeded max distance
            dist_x = proj['x'] - proj['start_x']
            dist_y = proj['y'] - proj['start_y']
            distance = (dist_x ** 2 + dist_y ** 2) ** 0.5

            if distance < proj['max_distance']:
                # Convert world position to screen position
                screen_x, screen_y = self.camera.world_to_screen(proj['x'], proj['y'])

                self._render_projectile_marker(
                    proj.get('gani', 'arrow'), screen_x, screen_y, proj['direction'],
                    current_time - proj.get('time', current_time))

                active_projectiles.append(proj)

        self.active_projectiles = active_projectiles

    # Debris tints for thrown-object breaks: (bright, dark) per liftable type.
    BREAK_COLORS = {
        'bush': ((60, 145, 60), (28, 96, 28)),
        'pot':  ((198, 150, 104), (140, 96, 60)),
        'rock': ((150, 150, 150), (96, 96, 96)),
    }

    def _update_and_render_thrown(self, dt: float):
        """Fly thrown liftables (bush/pot/rock) along their arc and break them
        on landing or on the first blocking tile. The 2x2 tile graphic is drawn
        lifted by its arc height, so the throw actually reads as a throw."""
        survivors = []
        for obj in self.thrown_objects:
            step = obj['speed'] * dt
            obj['x'] += obj['dx'] * step
            obj['y'] += obj['dy'] * step
            obj['dist'] += step
            frac = min(1.0, obj['dist'] / obj['range'])
            obj['z'] = obj['z0'] * (1.0 - frac * frac)  # eases to the ground

            # Break when the leading edge of the 2x2 meets a wall, or at the
            # end of the arc.
            lead_x = obj['x'] + 1.0 + obj['dx']
            lead_y = obj['y'] + 1.0 + obj['dy']
            off_level = (not self.client.in_gmap_segment and
                         not (0 <= lead_x < 64 and 0 <= lead_y < 64))
            if obj['dist'] >= obj['range'] or off_level or \
                    self._is_tile_blocking(self._get_tile_at(lead_x, lead_y)):
                self._spawn_break_effect(obj)
                continue

            sx, sy = self.camera.world_to_screen(obj['x'], obj['y'] - obj['z'])
            for i, (dx, dy) in enumerate([(0, 0), (1, 0), (0, 1), (1, 1)]):
                tile_surf = self.tileset_mgr.get_tile_or_color(obj['tiles'][i])
                self.screen.blit(tile_surf, (sx + dx * TILE_SIZE, sy + dy * TILE_SIZE))
            survivors.append(obj)
        self.thrown_objects = survivors
        # Piggy-back the other-players'-throw arc and pushaway-knockback decay
        # on this method since it already runs every frame with dt (see
        # game/render.py's render loop, which calls this by name - it isn't
        # touched by this change).
        self._update_and_render_other_thrown(dt)
        self._apply_pushaway(dt)

    def _update_and_render_other_thrown(self, dt: float):
        """Fly OTHER players' thrown objects (PLO_THROWCARRIED - see
        game/setup.py's on_throwcarried) along the same arc as our own thrown
        objects above, but drawn as a generic colored 2x2 block rather than
        real level tiles: parse_throwcarried's payload is just the owner's
        player id (see packets.py) - the protocol never says what was thrown,
        so there's no tile graphic to look up for it."""
        survivors = []
        for obj in self.other_thrown_objects:
            step = obj['speed'] * dt
            obj['x'] += obj['dx'] * step
            obj['y'] += obj['dy'] * step
            obj['dist'] += step
            frac = min(1.0, obj['dist'] / obj['range'])
            obj['z'] = obj['z0'] * (1.0 - frac * frac)  # eases to the ground

            lead_x = obj['x'] + 1.0 + obj['dx']
            lead_y = obj['y'] + 1.0 + obj['dy']
            off_level = (not self.client.in_gmap_segment and
                         not (0 <= lead_x < 64 and 0 <= lead_y < 64))
            if obj['dist'] >= obj['range'] or off_level or \
                    self._is_tile_blocking(self._get_tile_at(lead_x, lead_y)):
                self.break_effects.append({
                    'x': obj['x'] + 1.0, 'y': obj['y'] + 1.0,
                    'time': time.time(), 'colors': obj['colors'],
                })
                self.sound_mgr.play("crush.wav")
                continue

            sx, sy = self.camera.world_to_screen(obj['x'], obj['y'] - obj['z'])
            bright, dark = obj['colors']
            for i, (dx, dy) in enumerate([(0, 0), (1, 0), (0, 1), (1, 1)]):
                chunk = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
                chunk.fill((*(bright if i % 2 == 0 else dark), 255))
                self.screen.blit(chunk, (sx + dx * TILE_SIZE, sy + dy * TILE_SIZE))
            survivors.append(obj)
        self.other_thrown_objects = survivors

    PUSHAWAY_DECAY = 6.0  # velocity damping per second; settles in well under a second

    def _apply_pushaway(self, dt: float):
        """PLO_PUSHAWAY knockback impulse (see game/setup.py's on_pushaway and
        packets.parse_push_away). Applied as a modest, quickly-decaying
        velocity nudge to the local player's authoritative position (picked
        up next frame by render.py's _update_visual_position chase, so it
        reads as a short shove rather than a teleport) - kept conservative
        since the GCHAR encoding is a single-source assumption (GServer-v2's
        doc comment) with no live sender in this workspace to verify against."""
        vx, vy = self._pushaway_velocity
        if vx == 0.0 and vy == 0.0:
            return
        # client.x/y are read-only properties mirroring client.player.x/y (see
        # client.py's Convenience Properties) - the player object is what
        # actually needs to move.
        self.client.player.x += vx * dt
        self.client.player.y += vy * dt
        decay = max(0.0, 1.0 - self.PUSHAWAY_DECAY * dt)
        vx *= decay
        vy *= decay
        if abs(vx) < 0.05 and abs(vy) < 0.05:
            vx = vy = 0.0
        self._pushaway_velocity = (vx, vy)

    def _spawn_hit_break_effect(self, x: float, y: float):
        """PLO_HITOBJECTS (see game/setup.py's on_hit_objects): spawn a short
        break/spark burst at the hit point when a player's sword/weapon connects
        with a bush/pot/etc. Reuses the same break_effects visual pipeline as
        _spawn_break_effect below (that one takes a thrown-object dict with a
        2x2 top-left `x`/`y` needing a +1.0 recentre and a `type` key for
        color; here x/y are already the exact hit point and there's no object
        type in the packet, so this appends directly with a neutral color)."""
        self.break_effects.append({
            'x': x, 'y': y,
            'time': time.time(),
            'colors': self.BREAK_COLORS['bush'],
        })
        self.sound_mgr.play("crush.wav")

    def _spawn_break_effect(self, obj):
        """Queue a debris burst where a thrown object broke."""
        self.break_effects.append({
            'x': obj['x'] + 1.0,   # ground center of the 2x2
            'y': obj['y'] + 1.0,
            'time': time.time(),
            'colors': self.BREAK_COLORS.get(obj.get('type'), self.BREAK_COLORS['bush']),
        })
        self.sound_mgr.play("crush.wav")

    BREAK_DURATION = 0.45

    def _render_break_effects(self):
        """Draw active debris bursts: 8 chunks scattering outward and fading."""
        now = time.time()
        active = []
        for eff in self.break_effects:
            t = (now - eff['time']) / self.BREAK_DURATION
            if t >= 1.0:
                continue
            cx, cy = self.camera.world_to_screen(eff['x'], eff['y'])
            bright, dark = eff['colors']
            alpha = int(255 * (1.0 - t))
            spread = (0.3 + 1.2 * t) * TILE_SIZE
            size = max(2, int(6 * (1.0 - t)))
            for i in range(8):
                ang = i * math.pi / 4.0
                # Debris flies out and settles down slightly, like falling bits.
                px = cx + math.cos(ang) * spread
                py = cy + math.sin(ang) * spread * 0.7 + (t * t) * 10
                chunk = pygame.Surface((size, size), pygame.SRCALPHA)
                chunk.fill((*(bright if i % 2 == 0 else dark), alpha))
                self.screen.blit(chunk, (px - size / 2, py - size / 2))
            active.append(eff)
        self.break_effects = active
    def _render_server_bombs(self):
        """Render bombs placed by OTHER players (client.bombs, from PLO_BOMBADD).

        The server never echoes PLI_BOMBADD back to the placer (see
        PlayerClientPackets.cpp msgPLI_BOMBADD - sendPacketToOneLevelPart
        excludes m_id), so this dict only ever holds other players' bombs; the
        placer's own bomb keeps rendering via the existing local
        active_bombs/_render_bombs path. No dedup between the two is needed.

        Since parse_bomb_add's dict has no wall-clock 'time' field, first-seen
        time is tracked locally per (x, y) key to drive the same fuse-flash /
        explosion look as the local bomb visual.
        """
        now = time.time()
        bombs = self.client.bombs
        seen = self._server_bomb_seen
        for key, bomb in bombs.items():
            first_seen = seen.get(key)
            if first_seen is None:
                first_seen = seen[key] = now
            fuse_total = max(0.05, bomb.get('timer_ms', 3050) / 1000.0)
            elapsed = now - first_seen
            x, y = bomb.get('x', 0.0), bomb.get('y', 0.0)
            screen_x, screen_y = self.camera.world_to_screen(x, y)
            if not self._entity_on_screen(screen_x, screen_y, margin=64):
                continue
            if elapsed < fuse_total:
                flash_rate = 5 + (elapsed / fuse_total) * 10
                if int(elapsed * flash_rate) % 2 == 0:
                    self._render_bomb_ticking(screen_x, screen_y, elapsed)
            else:
                # Timer elapsed but the server hasn't sent PLO_BOMBDEL yet (the
                # owner detonates it locally and relays the removal) - keep a
                # faint burst going rather than snapping back to a solid bomb.
                progress = min(1.0, (elapsed - fuse_total) / self.explosion_duration)
                radius = int(16 + bomb.get('power', 1) * 16 * progress)
                alpha = int(255 * (1.0 - progress))
                if radius > 0 and alpha > 0:
                    surf = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
                    pygame.draw.circle(surf, (255, 150, 50, alpha), (radius, radius), radius)
                    self.screen.blit(surf, (screen_x - radius, screen_y - radius))

        # Drop tracking for bombs the server has removed (PLO_BOMBDEL already
        # popped them out of client.bombs).
        for key in list(seen):
            if key not in bombs:
                del seen[key]

    def _render_server_bomb_explosions(self):
        """Render the brief flash queued by on_bomb_del (see game/setup.py)."""
        duration = 0.4
        now = time.time()
        active = []
        for exp in self.active_bomb_explosions:
            elapsed = now - exp['time']
            if elapsed < duration:
                screen_x, screen_y = self.camera.world_to_screen(exp['x'], exp['y'])
                progress = elapsed / duration
                radius = int(24 * (0.5 + progress * 0.5))
                alpha = int(255 * (1.0 - progress))
                surf = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
                pygame.draw.circle(surf, (255, 150, 50, alpha), (radius, radius), radius)
                pygame.draw.circle(surf, (255, 220, 120, alpha), (radius, radius), max(1, int(radius * 0.5)))
                self.screen.blit(surf, (screen_x - radius, screen_y - radius))
                active.append(exp)
        self.active_bomb_explosions = active

    _ARROW_DIRECTION_VECTOR = {0: (0, -1), 1: (-1, 0), 2: (0, 1), 3: (1, 0)}

    def _render_server_arrows(self):
        """Render arrows fired by OTHER players (client.arrows, PLO_ARROWADD).

        The protocol has no arrow-removal packet (see client.py comment on
        self.arrows), so life is simulated client-side: each entry gets a
        '_recv_time' stamped into the dict on first sight (safe - these are
        plain data dicts, not shared with the protocol layer) and is flown
        along its direction at a fixed speed for a short lifetime, matching
        the look of the local arrow projectile path in _use_weapon."""
        now = time.time()
        speed = 8.0       # tiles/sec, matches the local bow-shot visual
        lifetime = 1.25    # seconds (~10 tiles at speed 8)
        for arrow in self.client.arrows:
            recv_time = arrow.get('_recv_time')
            if recv_time is None:
                recv_time = arrow['_recv_time'] = now
            elapsed = now - recv_time
            if elapsed > lifetime:
                continue
            direction = arrow.get('direction', 2)
            dvx, dvy = self._ARROW_DIRECTION_VECTOR.get(direction, (0, 1))
            x = arrow.get('x', 0.0) + dvx * speed * elapsed
            y = arrow.get('y', 0.0) + dvy * speed * elapsed
            screen_x, screen_y = self.camera.world_to_screen(x, y)
            if not self._entity_on_screen(screen_x, screen_y, margin=32):
                continue
            self._render_projectile_marker('arrow', screen_x, screen_y, direction, elapsed)

    def _render_screen_tint(self):
        """Draw ambient and script-driven fullscreen tints under the HUD.

        Overlay surfaces are cached by size and tint so steady colors do not
        allocate or refill a full-screen surface every frame."""
        size = self.screen.get_size()
        if not hasattr(self, '_day_night_enabled'):
            self._day_night_enabled = Prefs.load().day_night
        server_time = getattr(self.client, 'server_time', 0)
        if self._day_night_enabled and server_time:
            minute_of_day = ((server_time * 5) // 60) % 1440
            ambient = day_night_tint(minute_of_day)
            if ambient and ambient[3] > 0:
                color = tuple(round(channel / 4) * 4 for channel in ambient)
                cache_key = (size, color)
                if cache_key != getattr(self, '_day_night_overlay_key', None):
                    self._day_night_overlay_key = cache_key
                    overlay = getattr(self, '_day_night_overlay_surface', None)
                    if overlay is None or overlay.get_size() != size:
                        overlay = self._day_night_overlay_surface = pygame.Surface(
                            size, pygame.SRCALPHA)
                    overlay.fill(color)
                self.screen.blit(self._day_night_overlay_surface, (0, 0))

        tint = self.screen_tint
        if not tint:
            return
        a = min(255, tint.get('a', 0))
        if a <= 0:
            return
        color = (tint.get('r', 0), tint.get('g', 0), tint.get('b', 0), a)
        cache_key = (size, color)
        if cache_key != getattr(self, '_tint_overlay_key', None):
            self._tint_overlay_key = cache_key
            overlay = getattr(self, '_tint_overlay_surface', None)
            if overlay is None or overlay.get_size() != size:
                overlay = self._tint_overlay_surface = pygame.Surface(size, pygame.SRCALPHA)
            overlay.fill(color)
        self.screen.blit(self._tint_overlay_surface, (0, 0))

    def _render_server_explosions(self):
        """Render explosions received from server (PLO_EXPLOSION packets)."""
        current_time = time.time()
        explosion_duration = 0.5  # seconds


        # Clean up expired explosions and render active ones
        active = []
        for exp in self.client.active_explosions:
            elapsed = current_time - exp['time']
            if elapsed < explosion_duration:
                # Calculate screen position
                screen_x, screen_y = self.camera.world_to_screen(exp['x'], exp['y'])

                # Expanding explosion based on radius
                progress = elapsed / explosion_duration
                base_radius = exp.get('radius', 2) * TILE_SIZE
                radius = int(base_radius * (0.5 + progress * 0.5))
                alpha = int(255 * (1.0 - progress))

                self._render_explosion_burst(screen_x, screen_y, elapsed, radius, alpha)

                active.append(exp)

        self.client.active_explosions = active
