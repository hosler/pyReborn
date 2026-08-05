"""EffectsRenderMixin — damage numbers, bombs, projectiles, explosions.

Split from render.py; methods operate on the GameClient instance."""

import time
import math
import random
from typing import Callable, Optional, Tuple

import pygame

from reborn_protocol.coords import in_level_bounds

from ..gani import AnimationState
from ..liftobjects import BUSH_REPLACE, match_bush
from ..prefs import Prefs
from ..tiletypes import TileType
from .constants import TILE_SIZE
from .frame_context import FrameContext, FrameContextMixin


def _q_dim(v: int) -> int:
    """Quantize a scaled particle dimension for the surface-cache key
    (exact below 32 px, then <=1/16-relative steps): a continuously
    interpolating zoom/stretch modifier otherwise lands on a fresh (w, h)
    every frame, misses the cache each time and thrashes the 400-entry cap."""
    if v < 32:
        return v
    step = 1 << (v.bit_length() - 5)
    return v - (v % step)


def _pc255(v: float) -> int:
    """0..1 colour channel to a clamped 0..255 byte."""
    return max(0, min(255, int(v * 255)))


def day_night_tint(minute_of_day):
    """Return the ambient overlay tint for a minute in the daily cycle."""
    minute = minute_of_day % 1440
    # The duplicated midnight endpoints make this a simple linear curve while
    # retaining a distinct dusk, deep-night plateau, and pink-violet dawn.
    keyframes = (
        (0, (5, 5, 35, 155)),
        (240, (5, 5, 35, 155)),
        (300, (180, 80, 120, 65)),
        (330, (205, 105, 135, 42)),
        (420, (220, 140, 150, 0)),
        (1080, (255, 120, 55, 0)),
        (1170, (255, 120, 55, 38)),
        (1200, (235, 120, 45, 42)),
        (1320, (10, 10, 45, 110)),
        (1440, (5, 5, 35, 155)),
    )
    if 420 <= minute <= 1080:
        return None
    for (start_minute, start), (end_minute, end) in zip(keyframes, keyframes[1:]):
        if start_minute <= minute <= end_minute:
            progress = (minute - start_minute) / (end_minute - start_minute)
            tint = tuple(round(a + (b - a) * progress)
                         for a, b in zip(start, end))
            return tint if tint[3] else None
    return None


class EffectsRenderMixin(FrameContextMixin):
    """Mixin providing the above methods for GameClient."""

    def _render_world_object(self, frame: Optional[FrameContext],
                             world_y: float, draw: Callable[[], None],
                             height_tiles: float = 1.0) -> None:
        """Hand one layer-1 world object to the entity pass, to be drawn at its
        turn in the depth sort rather than on top of every character.

        What gets deferred is the DRAW CALL, not a captured image. Rendering
        each object into its own scratch surface would cost a full-screen
        allocation and a full-screen alpha scan per object per frame, and it
        would change the result for anything that blends against the scene
        under it. The closure already carries its own screen position.

        Idle callers still draw immediately, the same contract defer_light
        has. That is what keeps the standalone render harnesses working: they
        call these renderers with no entity pass to flush the queue."""
        frame = self._frame_context() if frame is None else frame
        if not frame.defer_world_draw(draw, world_y + height_tiles):
            draw()

    def _combat_surface(self, name, flags=pygame.SRCALPHA):
        """Return a screen-sized cached effect surface."""
        key = (name, self.screen.get_size())
        cache = getattr(self, '_combat_surface_cache', None)
        if cache is None:
            cache = self._combat_surface_cache = {}
        surf = cache.get(key)
        if surf is None:
            surf = cache[key] = pygame.Surface(self.screen.get_size(), flags)
        return surf

    def _render_combat_presentation(self):
        """Composite cached hurt/death effects after the HUD."""
        now = time.monotonic()
        state = self.combat_presentation
        warp = bool(getattr(self.client, '_local_level_transition', ''))
        state.sync(self.client.player.hearts <= 0, warp, now)

        hit_alpha = state.hit_flash_alpha(now)
        if hit_alpha:
            vignette = self._combat_surface('hurt-vignette')
            if not getattr(self, '_hurt_vignette_ready', False):
                vignette.fill((0, 0, 0, 0))
                w, h = vignette.get_size()
                edge = max(24, min(w, h) // 7)
                for i in range(edge):
                    alpha = round(90 * (1.0 - i / edge) ** 2)
                    pygame.draw.rect(vignette, (150, 0, 0, alpha),
                                     (i, i, w - i * 2, h - i * 2), 1)
                self._hurt_vignette_ready = True
            vignette.set_alpha(hit_alpha)
            self.screen.blit(vignette, (0, 0))

        if state.death_started is not None:
            # Keep an overlay-free completed frame for a respawn warp's
            # framebuffer hold. Reuse the surface instead of allocating.
            base = self._combat_surface('death-base', flags=0)
            base.blit(self.screen, (0, 0))
            self._death_base_frame = base
            fade = self._combat_surface('death-fade')
            fade.fill((24, 24, 28, state.death_fade_alpha(now)))
            self.screen.blit(fade, (0, 0))
            if state.show_death_overlay(now):
                self.hud.draw_death_overlay(self.screen)
        else:
            self._death_base_frame = None
            alpha = state.respawn_fade_alpha(now)
            if alpha:
                fade = self._combat_surface('respawn-fade')
                fade.fill((0, 0, 0, alpha))
                self.screen.blit(fade, (0, 0))

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
        else:
            prefetch = getattr(self, '_prefetch_gani_assets', None)
            if prefetch is not None:
                prefetch(gani)
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
        same placement. (The full -TILE_SIZE x offset bakes in the 8px that
        used to live in _render_animated_entity's canvas shift, preserving
        the tuned centring now that ganis anchor at the passed x.)"""
        anim = AnimationState(self.gani_parser)
        anim.gani = gani
        anim.direction = direction
        anim.frame = int(max(0.0, elapsed) / AnimationState.FRAME_DURATION)
        ox = screen_x - TILE_SIZE
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

    def _render_bombs(self, frame: Optional[FrameContext] = None):
        """Advance and render the unified local/remote bomb registry."""
        current_time = time.time()
        active_bombs = []
        for bomb in self.active_bombs:
            fuse_time = max(0.05, bomb.get('fuse_time', self.bomb_fuse_time))
            elapsed = current_time - bomb['time']

            # Convert world position to screen position
            screen_x, screen_y = self.camera.world_to_screen(bomb['x'], bomb['y'])

            if not bomb.get('exploded') and elapsed < fuse_time:
                # Bomb is still counting down - render bomb sprite
                # Flash faster as fuse runs out
                flash_rate = 5 + (elapsed / fuse_time) * 10
                if int(elapsed * flash_rate) % 2 == 0:
                    self._render_world_object(
                        frame, bomb['y'],
                        lambda screen_x=screen_x, screen_y=screen_y,
                        elapsed=elapsed: self._render_bomb_ticking(
                            screen_x, screen_y, elapsed))
                active_bombs.append(bomb)

            else:
                if not bomb.get('exploded'):
                    self._detonate_bomb(bomb, current_time)
                explosion_elapsed = current_time - bomb['explosion_time']
                if explosion_elapsed >= self.explosion_duration:
                    continue
                explosion_progress = explosion_elapsed / self.explosion_duration

                # Expanding explosion radius
                radius = int(16 + bomb['power'] * 16 * explosion_progress)
                alpha = int(255 * (1.0 - explosion_progress))

                self._render_world_object(
                    frame, bomb['y'],
                    lambda screen_x=screen_x, screen_y=screen_y,
                    explosion_elapsed=explosion_elapsed, radius=radius,
                    alpha=alpha: self._render_explosion_burst(
                        screen_x, screen_y, explosion_elapsed, radius, alpha))
                active_bombs.append(bomb)

        self.active_bombs = active_bombs

    def _add_remote_bomb(self, info: dict, now: Optional[float] = None):
        """Insert a wire bomb into the same registry used by local bombs."""
        now = time.time() if now is None else now
        x, y = info.get('x', 0.0), info.get('y', 0.0)
        for bomb in self.active_bombs:
            if (not bomb.get('exploded') and bomb.get('source') == 'remote'
                    and bomb['x'] == x and bomb['y'] == y):
                bomb.update(power=info.get('power', 1),
                            fuse_time=max(0.05, info.get('timer_ms', 3050) / 1000.0))
                return bomb
        bomb = {
            'x': x, 'y': y, 'time': now,
            'fuse_time': max(0.05, info.get('timer_ms', 3050) / 1000.0),
            'power': info.get('power', 1), 'exploded': False,
            'source': 'remote',
        }
        self.active_bombs.append(bomb)
        return bomb

    def _detonate_bomb_at(self, x: float, y: float, now: Optional[float] = None):
        """Honor a removal packet immediately, without starting a second burst."""
        now = time.time() if now is None else now
        matches = [b for b in self.active_bombs
                   if abs(b['x'] - x) < 0.01 and abs(b['y'] - y) < 0.01]
        if matches:
            bomb = next((b for b in matches if not b.get('exploded')), matches[0])
        else:
            bomb = {'x': x, 'y': y, 'time': now, 'fuse_time': 0.05,
                    'power': 1, 'exploded': False, 'source': 'remote'}
            self.active_bombs.append(bomb)
        self._detonate_bomb(bomb, now)
        return bomb

    def _detonate_bomb(self, bomb: dict, now: Optional[float] = None):
        if bomb.get('exploded'):
            return False
        now = time.time() if now is None else now
        bomb['exploded'] = True
        bomb['explosion_time'] = now
        self.sound_mgr.play("explode.wav")
        self._start_camera_shake(bomb['x'], bomb['y'])
        self._break_bushes_in_blast(bomb['x'], bomb['y'], bomb.get('power', 1))
        return True

    def _start_camera_shake(self, x: float, y: float,
                            now: Optional[float] = None) -> bool:
        """Start a short visual-only shake for a nearby explosion."""
        player = self.client.player
        if math.hypot(float(x) - player.x, float(y) - player.y) > 8.0:
            return False
        now = time.monotonic() if now is None else now
        started = getattr(self, '_camera_shake_started', None)
        if started is None or now - started >= 0.4:
            self._camera_shake_started = now
        return True

    def _clear_bush_tiles(self, ox: int, oy: int, index: int) -> None:
        """Replace a cut bush's 2x2 with its own stump tiles.

        `bushobjreplace` gives one stump per bush row (TInitStatics.cpp:1502),
        so this is not a blanket fill with the level's grass tile. Sent over
        the wire when the bush sits in the segment the player stands in, the
        way the reference cuts (TPlayer::slayBushes -> modifyBoard with its
        send flag set).
        """
        from reborn_protocol.coords import level_index, world_to_local

        replacement = BUSH_REPLACE[index]
        standing = self.client.get_current_level_from_position()
        for i, (dx, dy) in enumerate(((0, 0), (0, 1), (1, 0), (1, 1))):
            wx, wy = ox + dx, oy + dy
            level_name, tiles = self._level_tiles_at(wx, wy)
            if not level_name:
                continue
            lx, ly = world_to_local(wx, wy)
            if level_name == standing:
                self.client.modify_board(lx, ly, 1, 1, [replacement[i]])
            elif tiles:
                tiles[level_index(lx, ly)] = replacement[i]

    def _break_bushes_in_blast(self, x: float, y: float, power: int):
        """Remove vegetation objects whose tiles overlap the circular blast."""
        radius = 2.5 + power * 0.5
        # A bush is one of the reference client's `bushobj` 2x2 tile patterns
        # (pyreborn/liftobjects.py), not a tile type - matching on the whole
        # pattern is also what stops a lone bush-coloured tile from popping.
        matches = {}
        lo_x, hi_x = math.floor(x - radius), math.ceil(x + radius)
        lo_y, hi_y = math.floor(y - radius), math.ceil(y + radius)
        for ty in range(lo_y, hi_y + 1):
            for tx in range(lo_x, hi_x + 1):
                if math.hypot(tx + 0.5 - x, ty + 0.5 - y) > radius:
                    continue
                hit = match_bush(self._get_tile_at, tx, ty)
                if hit is not None:
                    index, ox, oy = hit
                    matches[(ox, oy)] = index
        origins = set(matches)
        for (ox, oy), index in matches.items():
            self._clear_bush_tiles(ox, oy, index)
            self._spawn_hit_break_effect(ox + 1.0, oy + 1.0)
            self._spawn_leaf_particles(ox + 1.0, oy + 1.0)
        if origins:
            self.world_surface = None
        return origins
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

    def _update_and_render_projectiles(self, dt: float,
                                       frame: Optional[FrameContext] = None):
        """Advance all arrows and stop them briefly at the first solid tile."""
        current_time = time.time()
        active_projectiles = []
        for proj in self.active_projectiles:
            if 'hit_time' in proj:
                if current_time - proj['hit_time'] < 0.12:
                    self._render_arrow_hit_spark(proj, current_time)
                    active_projectiles.append(proj)
                continue

            old_x, old_y = proj['x'], proj['y']
            proj['x'] += proj['dx'] * dt
            proj['y'] += proj['dy'] * dt
            travel = math.hypot(proj['x'] - old_x, proj['y'] - old_y)
            samples = max(1, math.ceil(travel * 4))
            hit = False
            for step in range(1, samples + 1):
                frac = step / samples
                sx = old_x + (proj['x'] - old_x) * frac
                sy = old_y + (proj['y'] - old_y) * frac
                if self._is_tile_blocking(self._get_tile_at(sx, sy)):
                    proj['x'], proj['y'] = sx, sy
                    proj['hit_time'] = current_time
                    hit = True
                    break
            if hit:
                self._render_arrow_hit_spark(proj, current_time)
                active_projectiles.append(proj)
                continue

            # Check if projectile exceeded max distance
            dist_x = proj['x'] - proj['start_x']
            dist_y = proj['y'] - proj['start_y']
            distance = (dist_x ** 2 + dist_y ** 2) ** 0.5

            if distance < proj['max_distance']:
                # Convert world position to screen position
                screen_x, screen_y = self.camera.world_to_screen(proj['x'], proj['y'])

                self._render_world_object(
                    frame, proj['y'],
                    lambda proj=proj, screen_x=screen_x, screen_y=screen_y,
                    current_time=current_time: self._render_projectile_marker(
                        proj.get('gani', 'arrow'), screen_x, screen_y,
                        proj['direction'],
                        current_time - proj.get('time', current_time)))

                active_projectiles.append(proj)

        self.active_projectiles = active_projectiles

    def _render_arrow_hit_spark(self, proj: dict, now: float):
        screen_x, screen_y = self.camera.world_to_screen(proj['x'], proj['y'])
        age = now - proj['hit_time']
        radius = max(1, int(5 * (1.0 - age / 0.12)))
        pygame.draw.circle(self.screen, (255, 220, 120),
                           (int(screen_x), int(screen_y)), radius, 1)

    def _add_remote_arrow(self, info: dict, now: Optional[float] = None):
        now = time.time() if now is None else now
        direction = info.get('direction', 2)
        vx, vy = self._ARROW_DIRECTION_VECTOR.get(direction, (0, 1))
        x, y = info.get('x', 0.0), info.get('y', 0.0)
        arrow = {
            'x': x, 'y': y, 'dx': vx * 8.0, 'dy': vy * 8.0,
            'time': now, 'direction': direction, 'gani': 'arrow',
            'max_distance': 10.0, 'start_x': x, 'start_y': y,
            'source': 'remote',
        }
        self.active_projectiles.append(arrow)
        return arrow

    # Debris tints for thrown-object breaks: (bright, dark) per liftable type.
    BREAK_COLORS = {
        'bush': ((60, 145, 60), (28, 96, 28)),
        'pot':  ((198, 150, 104), (140, 96, 60)),
        'vase': ((198, 150, 104), (140, 96, 60)),
        'rock': ((150, 150, 150), (96, 96, 96)),
        'sign': ((174, 132, 72), (103, 70, 36)),
    }

    def _update_and_render_thrown(self, dt: float,
                                  frame: Optional[FrameContext] = None):
        """Fly thrown liftables along their arc and break them
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
            pelted_npc = None
            for npc_id, npc in (getattr(self.client, 'npcs', {}) or {}).items():
                nx = float(npc.get('world_x', npc.get('x', 0)) or 0)
                ny = float(npc.get('world_y', npc.get('y', 0)) or 0)
                if (npc.get('visible', True) and
                        nx <= lead_x < nx + 2.0 and ny <= lead_y < ny + 2.0):
                    pelted_npc = (npc_id, npc)
                    break
            if step > 0 and pelted_npc is not None:
                npc_id, npc = pelted_npc
                kind = obj.get('type', '')
                npc['pelt_kind'] = {'pot': 'vase', 'rock': 'stone'}.get(kind, kind)
                gs1 = getattr(self, 'gs1', None)
                if gs1 is not None:
                    gs1.trigger_npc_event(npc_id, 'waspelt')
                gs2 = getattr(self, 'gs2', None)
                if gs2 is not None:
                    gs2.trigger_npc_event(npc_id, 'onWasPelt')
                self._spawn_break_effect(obj)
                continue
            off_level = (not self.client.in_gmap_segment and
                         not in_level_bounds(lead_x, lead_y))
            if obj['dist'] >= obj['range'] or off_level or \
                    self._is_tile_blocking(self._get_tile_at(lead_x, lead_y)):
                self._spawn_break_effect(obj)
                continue

            sx, sy = self.camera.world_to_screen(obj['x'], obj['y'] - obj['z'])

            def draw_thrown(obj=obj, sx=sx, sy=sy):
                for i, (dx, dy) in enumerate(
                        [(0, 0), (1, 0), (0, 1), (1, 1)]):
                    tile_surf = self.tileset_mgr.get_tile_or_color(
                        obj['tiles'][i])
                    self.screen.blit(
                        tile_surf,
                        (sx + dx * TILE_SIZE, sy + dy * TILE_SIZE))

            # The sprite rises, but its depth stays on the ground. Sorting by
            # the lifted bottom makes it jump behind characters near the arc.
            self._render_world_object(frame, obj['y'], draw_thrown,
                                      height_tiles=2.0)
            survivors.append(obj)
        self.thrown_objects = survivors
        # Piggy-back the other-players'-throw arc and pushaway-knockback decay
        # on this method since it already runs every frame with dt (see
        # game/render.py's render loop, which calls this by name - it isn't
        # touched by this change).
        self._update_and_render_other_thrown(dt, frame)
        self._apply_pushaway(dt)

    def _update_and_render_other_thrown(self, dt: float,
                                        frame: Optional[FrameContext] = None):
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
                         not in_level_bounds(lead_x, lead_y))
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

            def draw_other_thrown(obj=obj, sx=sx, sy=sy, bright=bright,
                                   dark=dark):
                for i, (dx, dy) in enumerate(
                        [(0, 0), (1, 0), (0, 1), (1, 1)]):
                    chunk = pygame.Surface(
                        (TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
                    chunk.fill((*(bright if i % 2 == 0 else dark), 255))
                    self.screen.blit(
                        chunk, (sx + dx * TILE_SIZE, sy + dy * TILE_SIZE))

            self._render_world_object(frame, obj['y'], draw_other_thrown,
                                      height_tiles=2.0)
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
    LEAF_DURATION = 0.6
    MAX_LEAF_PARTICLES = 64

    def _spawn_leaf_particles(self, x: float, y: float, now=None, count=None):
        """Add a small capped spray of procedural vegetation fragments."""
        now = time.time() if now is None else now
        count = random.randint(4, 6) if count is None else max(0, int(count))
        particles = getattr(self, 'leaf_particles', None)
        if particles is None:
            particles = self.leaf_particles = []
        room = max(0, self.MAX_LEAF_PARTICLES - len(particles))
        for _ in range(min(count, room)):
            angle = random.uniform(0.0, math.tau)
            speed = random.uniform(0.7, 1.7)
            particles.append({
                'x': x, 'y': y, 'time': now,
                'vx': math.cos(angle) * speed,
                'vy': math.sin(angle) * speed - random.uniform(0.2, 0.7),
                'shade': random.randrange(2),
                'phase': random.randrange(4),
            })
        return min(count, room)

    def _expire_leaf_particles(self, now=None):
        """Discard expired fragments and return the remaining registry."""
        now = time.time() if now is None else now
        self.leaf_particles[:] = [
            leaf for leaf in self.leaf_particles
            if now - leaf['time'] < self.LEAF_DURATION - 1e-9
        ]
        return self.leaf_particles

    # -- GS2 particle emitters (pyreborn/particles.py state model) ----------

    #: cached finished particle surfaces, keyed by everything that changes
    #: their pixels (quantized tint/alpha/rotation so the key space is small)
    _PARTICLE_CACHE_CAP = 400
    #: per-emitter draw cap; the SIM cap is particles.SIM_PARTICLE_CAP
    _PARTICLE_DRAW_CAP = 1000

    def _render_layer_emitter(self, rec: dict, emitter) -> None:
        """Draw a layer emitter's live particles, in the pass/stratum its
        owner record occupies (called per record from _render_npc_layers).
        Simulation is advanced by gs1.advance_layer_emitters, not here --
        this is a pure state consumer. World-band particle coords are tiles
        (drawn at y - z, TParticleEmitter::fastDraw quattroplay/src/
        TParticleEmitter.cpp:919), GUI-band coords are screen pixels;
        particle `mode` >= 2 is the additive blend family (drawMode
        premultiply, :956-961)."""
        particles = getattr(emitter, 'particles', None)
        if not particles:
            return
        from ..particles import ParticleEmitter
        if not isinstance(emitter, ParticleEmitter):
            return
        gui = self._layer_is_gui(rec)
        scale = 1.0 if gui else self.camera.scale
        owner = rec.get('_owner')
        if rec.get('attachtoowner') and isinstance(owner, dict):
            wx = float(owner.get('world_x', owner.get('x', 0.0)) or 0.0)
            wy = float(owner.get('world_y', owner.get('y', 0.0)) or 0.0)
            base = (wx, wy) if gui else self.camera.world_to_screen(wx, wy)
        else:
            base = self._layer_pos(rec)
        attach = emitter.get('attachposition') != 0.0
        rx = float(rec.get('x', 0.0) or 0.0)
        ry = float(rec.get('y', 0.0) or 0.0)
        rz = float(rec.get('z', 0.0) or 0.0)
        zoom_base = 1.0 if gui else self.camera.scale / float(TILE_SIZE)
        # firstinfront draws newest on top (default); painter's order
        ordered = (particles if emitter.get('firstinfront') != 0.0
                   else list(reversed(particles)))
        frame = self._frame_context()
        cache = getattr(self, '_particle_surf_cache', None)
        if cache is None:
            cache = self._particle_surf_cache = {}
        for p in ordered[:self._PARTICLE_DRAW_CAP]:
            image = p.image
            if not image:
                continue
            sheet = self.sprite_mgr.load_sheet(image)
            if sheet is None:
                self._request_asset(image)
                continue
            w = _q_dim(max(1, int(sheet.get_width()
                                  * zoom_base * p.zoom * p.stretchx)))
            h = _q_dim(max(1, int(sheet.get_height()
                                  * zoom_base * p.zoom * p.stretchy)))
            additive = p.mode >= 2
            rq = min(16, max(0, int(p.red * 16)))
            gq = min(16, max(0, int(p.green * 16)))
            bq = min(16, max(0, int(p.blue * 16)))
            aq = min(16, max(0, int(p.alpha * 16)))
            rot = int(math.degrees(p.rotation) / 15.0) * 15 if p.rotation else 0
            key = (image, w, h, rq, gq, bq, aq, additive, rot)
            surf = cache.get(key)
            if surf is None:
                surf = (sheet if (w, h) == sheet.get_size()
                        else pygame.transform.scale(sheet, (w, h)))
                r, g, b, a = rq / 16.0, gq / 16.0, bq / 16.0, aq / 16.0
                if additive:
                    # fold colour-alpha AND per-pixel alpha into RGB: BLEND_ADD
                    # ignores alpha (same trap as additive showimg layers)
                    if not surf.get_flags() & pygame.SRCALPHA:
                        surf = surf.convert_alpha()
                    surf = surf.premul_alpha()
                    surf.fill((_pc255(r * a), _pc255(g * a), _pc255(b * a),
                               255), special_flags=pygame.BLEND_RGB_MULT)
                elif (rq, gq, bq) != (16, 16, 16) or aq != 16:
                    surf = surf.copy()
                    if (rq, gq, bq) != (16, 16, 16):
                        surf.fill((_pc255(r), _pc255(g), _pc255(b), 255),
                                  special_flags=pygame.BLEND_RGB_MULT)
                    if aq != 16:
                        surf.set_alpha(_pc255(a))
                if rot:
                    surf = pygame.transform.rotate(surf, rot)
                if len(cache) > self._PARTICLE_CACHE_CAP:
                    cache.clear()
                cache[key] = surf
            px, py, pz = p.x, p.y, p.z
            if not attach:
                px -= rx
                py -= ry
                pz -= rz
            sx = base[0] + px * scale
            sy = base[1] + (py - pz) * scale
            if rot:
                sx -= (surf.get_width() - w) / 2.0
                sy -= (surf.get_height() - h) / 2.0
            if additive:
                if not frame.defer_light(surf, sx, sy):
                    self.screen.blit(surf, (int(sx), int(sy)),
                                     special_flags=pygame.BLEND_ADD)
            else:
                self.screen.blit(surf, (int(sx), int(sy)))

    def _render_leaf_particles(self):
        now = time.time()
        self._expire_leaf_particles(now)
        colors = ((72, 164, 62), (38, 112, 45))
        for leaf in self.leaf_particles:
            age = now - leaf['time']
            t = age / self.LEAF_DURATION
            wx = leaf['x'] + leaf['vx'] * age
            wy = leaf['y'] + leaf['vy'] * age + 1.8 * age * age
            px, py = self.camera.world_to_screen(wx, wy)
            size = 2 + ((int(t * 12) + leaf['phase']) & 1)
            color = (*colors[leaf['shade']], int(255 * (1.0 - t)))
            pygame.draw.rect(self.screen, color, (round(px), round(py), size, 2))

    # -- putleaps bursts ---------------------------------------------------
    #
    # GS1 `putleaps type,x,y` debris/splash bursts, the reference client's
    # exact frame data: TServerLeap.cpp's leapslen/leaps0..leaps5 tables
    # (Preagonal/FourPlay/quattroplay/src/TServerLeap.cpp:11-71), each packed
    # int decoded as (sprite index, dx, dy) with dx/dy signed eighth-tiles
    # (TServerLeap::draw applies offset * 0.125 tiles, :107-131). Sprites are
    # rects on the classic built-in sheet sprites.png (TPlayer::
    # drawSpriteAbsoluteOffset reads spritespos[], TPlayer.cpp:5315-5326;
    # rect table at TInitStatics.cpp:1045, defaults *spritesname =
    # "sprites.png" :4811). One frame advances per 0.05s engine tick;
    # spawn plays water.wav for type 5, else crush.wav
    # (TServerLevel::putLeaps, TServerLevel.cpp:2850-2866).
    LEAP_FRAME_TIME = 0.05
    MAX_LEAP_BURSTS = 64

    _LEAP_SPRITE_RECTS = {  # sprite index -> (x, y, w, h) on sprites.png
        24: (34, 8, 10, 8), 25: (44, 0, 16, 16), 26: (60, 0, 16, 16),
        96: (40, 82, 16, 16), 97: (24, 98, 16, 16), 98: (40, 98, 16, 16),
        99: (56, 82, 16, 14), 100: (72, 82, 16, 14), 101: (56, 96, 16, 14),
        102: (72, 96, 16, 14), 103: (104, 96, 16, 22),
        132: (12, 116, 12, 14), 133: (0, 130, 12, 14), 134: (12, 130, 12, 14),
        135: (0, 144, 16, 32), 326: (54, 114, 30, 30), 327: (90, 196, 16, 20),
    }

    _LEAP_FRAMES = (
        (  # type 0
            ((25, 0, 4), (25, 6, 0), (26, 6, 8), (26, 9, 17)),
            ((25, -2, 4), (25, 4, -4), (26, 8, 10), (26, 9, 19)),
            ((26, -4, 4), (25, 2, -8), (26, 10, 12), (26, 9, 21)),
            ((25, -5, 4), (25, 1, -10), (25, 9, 13), (25, 9, 22)),
            ((25, -6, 4), (25, 0, -12), (25, 10, 14), (25, 10, 23)),
            ((26, -7, 4), (25, -1, -14), (26, 10, 15), (26, 10, 24)),
            ((26, -8, 4), (25, -2, -16), (26, 10, 22), (26, 10, 25)),
        ),
        (  # type 1
            ((24, 0, 8), (24, 8, 0), (24, 12, 8)),
            ((24, -2, 8), (24, 8, -2), (24, 14, 8)),
            ((24, -4, 8), (24, 8, -4), (24, 16, 8)),
            ((24, -6, 8), (24, 8, -6), (24, 18, 8)),
        ),
        (  # type 2
            ((96, -1, 0), (96, 0, 9), (98, 9, -1), (98, 10, 8)),
            ((99, -3, -2), (99, -2, 11), (97, 11, -3), (97, 12, 10)),
            ((96, -5, -4), (96, -4, 13), (98, 13, -5), (98, 14, 12)),
            ((99, -7, -6), (99, -6, 15), (97, 15, -7), (97, 16, 14)),
        ),
        (  # type 3
            ((100, -1, 0), (100, 0, 9), (102, 9, -1), (102, 10, 8)),
            ((103, -3, -2), (103, -2, 11), (101, 11, -3), (101, 12, 10)),
            ((100, -5, -4), (100, -4, 13), (102, 13, -5), (102, 14, 12)),
            ((103, -7, -6), (103, -6, 15), (101, 15, -7), (101, 16, 14)),
        ),
        (  # type 4
            ((132, 0, 0), (133, 10, 0), (134, 0, 9), (135, 10, 9)),
            ((132, -4, -4), (133, 14, -4), (134, -4, 13), (135, 14, 13)),
            ((132, -8, -8), (133, 18, -8), (134, -8, 17), (135, 18, 17)),
            ((132, -12, -12), (133, 22, -12), (134, -12, 21), (135, 22, 21)),
        ),
        (  # type 5
            ((326, -6, 3), (327, 7, 3)),
            ((326, -8, 1), (327, 9, 1)),
            ((326, -9, -1), (327, 10, -1)),
            ((326, -10, -3), (327, 11, -3)),
            ((326, -13, -4), (327, 14, -4)),
            ((326, -15, -4), (327, 16, -4)),
            ((326, -17, -3), (327, 18, -3)),
            ((326, -19, -1), (327, 20, -1)),
        ),
    )

    def _spawn_leaps(self, leap_type: int, x: float, y: float, now=None):
        """GS1 `putleaps type,x,y` (wired from gs1.on_putleaps): queue the
        burst at level coords (x, y) and play its spawn sound."""
        if not 0 <= int(leap_type) <= 5:
            return
        now = time.time() if now is None else now
        bursts = getattr(self, 'leap_bursts', None)
        if bursts is None:
            bursts = self.leap_bursts = []
        if len(bursts) >= self.MAX_LEAP_BURSTS:
            return
        bursts.append({'type': int(leap_type), 'x': float(x), 'y': float(y),
                       'time': now})
        try:
            self._play_audio('water.wav' if int(leap_type) == 5 else 'crush.wav')
        except Exception:
            pass

    def _render_leaps(self):
        """Draw active putleaps bursts and expire finished ones."""
        bursts = getattr(self, 'leap_bursts', None)
        if not bursts:
            return
        now = time.time()
        sheet = self._get_effect_sprite('sprites.png')
        alive = []
        for burst in bursts:
            frames = self._LEAP_FRAMES[burst['type']]
            idx = int((now - burst['time']) / self.LEAP_FRAME_TIME)
            if idx >= len(frames):
                continue
            alive.append(burst)
            if sheet is None:
                continue        # keep animating; sheet may stream in mid-burst
            for sprite, dx, dy in frames[idx]:
                rect = self._LEAP_SPRITE_RECTS.get(sprite)
                if rect is None:
                    continue
                px, py = self.camera.world_to_screen(
                    burst['x'] + dx * 0.125, burst['y'] + dy * 0.125)
                self.screen.blit(sheet, (round(px), round(py)),
                                 area=pygame.Rect(rect))
        self.leap_bursts[:] = alive

    def _ripple_surface(self, radius: int):
        """Return a cached one-pixel ring for a ripple scale."""
        cache = getattr(self, '_ripple_surface_cache', None)
        if cache is None:
            cache = self._ripple_surface_cache = {}
        surface = cache.get(radius)
        if surface is None:
            side = radius * 2 + 2
            surface = pygame.Surface((side, side), pygame.SRCALPHA)
            pygame.draw.ellipse(surface, (175, 220, 225, 150),
                                (1, radius // 2, radius * 2, radius), 1)
            cache[radius] = surface
        return surface

    def _render_water_ripples(self):
        now = time.time()
        ripples = getattr(self, 'water_ripples', None)
        if ripples is None:
            ripples = self.water_ripples = []
        if self.is_swimming and now - getattr(self, '_last_ripple_time', 0.0) >= 0.5:
            feet_x, feet_y = self._player_feet()
            ripples.append({'x': feet_x, 'y': feet_y, 'time': now})
            self._last_ripple_time = now
        ripples[:] = [r for r in ripples if now - r['time'] < 0.5]
        for ripple in ripples:
            t = (now - ripple['time']) / 0.5
            radius = (5, 8, 11)[min(2, int(t * 3))]
            surface = self._ripple_surface(radius)
            surface.set_alpha(int(150 * (1.0 - t)))
            px, py = self.camera.world_to_screen(ripple['x'], ripple['y'])
            self.screen.blit(surface, (px - surface.get_width() / 2,
                                       py - surface.get_height() / 2))

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
    _ARROW_DIRECTION_VECTOR = {0: (0, -1), 1: (-1, 0), 2: (0, 1), 3: (1, 0)}

    def _render_server_arrows(self):
        """Render arrows fired by OTHER players (client.arrows, PLO_ARROWADD).

        The protocol has no arrow-removal packet (see client.py comment on
        self.arrows), so life is simulated client-side: each entry gets a
        '_recv_time' stamped into the dict on first sight (safe - these are
        plain data dicts, not shared with the protocol layer) and is flown
        along its direction at a fixed speed for a short lifetime, matching
        the look of the local arrow projectile path in _use_weapon."""
        return None

    def _render_screen_tint(self, frame: Optional[FrameContext] = None):
        """Draw ambient and script-driven fullscreen tints under the HUD.

        Overlay surfaces are cached by size and tint so steady colors do not
        allocate or refill a full-screen surface every frame."""
        frame = self._frame_context() if frame is None else frame
        size = self.screen.get_size()
        if not hasattr(self, '_day_night_enabled'):
            self._day_night_enabled = Prefs.load().day_night
        server_time = getattr(self.client, 'server_time', 0)
        if self._day_night_enabled and server_time:
            minute_of_day = ((server_time * 5) // 60) % 1440
            ambient = day_night_tint(minute_of_day)
            if ambient and ambient[3] > 0:
                # /4 quantization can round 255 up to 256 — clamp back into range.
                color = tuple(min(255, round(channel / 4) * 4) for channel in ambient)
                cache_key = (size, color)
                if cache_key != getattr(self, '_day_night_overlay_key', None):
                    self._day_night_overlay_key = cache_key
                    overlay = getattr(self, '_day_night_overlay_surface', None)
                    if overlay is None or overlay.get_size() != size:
                        overlay = self._day_night_overlay_surface = pygame.Surface(
                            size, pygame.SRCALPHA)
                    overlay.fill(color)
                self._blit_tint_overlay(self._day_night_overlay_surface, size,
                                        frame)

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
        self._blit_tint_overlay(self._tint_overlay_surface, size, frame)

    def _blit_tint_overlay(self, overlay: pygame.Surface, size: Tuple[int, int],
                           frame: Optional[FrameContext] = None):
        """Blit a cached darkness/tint overlay to the screen, first punching
        this frame's drawaslight NPC footprints out of it (FrameContext's
        light_sources, filled by render_entities.py's
        _render_light_sprite) so a light source genuinely
        brightens that spot instead of just glowing additively on top of
        otherwise-unchanged darkness.

        `overlay` is one of the size/color-keyed caches above and must stay
        clean for reuse next frame - the holes go into a separate per-frame
        scratch copy instead, so a light that moves (or a frame with no
        visible lights at all) never leaves a stale hole behind. Degrades to
        the old direct blit whenever there's nothing to punch (the common
        case: daytime, or a tinted scene with no light NPCs on screen)."""
        lights = (self._frame_context() if frame is None else frame).light_sources
        if not lights:
            self.screen.blit(overlay, (0, 0))
            return
        scratch = getattr(self, '_tint_hole_scratch', None)
        if scratch is None or scratch.get_size() != size:
            scratch = self._tint_hole_scratch = pygame.Surface(size, pygame.SRCALPHA)
        # An exact copy, not an alpha-composite: overlay's own per-pixel
        # alpha would otherwise get baked into scratch's RGB (premultiplied)
        # by a plain blit, applying it a second time when scratch is later
        # alpha-blitted onto the screen and washing the tint out far weaker
        # than the direct (no-lights) path above. Clear-then-saturating-add
        # is a straight byte copy regardless of alpha.
        scratch.fill((0, 0, 0, 0))
        scratch.blit(overlay, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)
        for eraser, lx, ly in lights:
            scratch.blit(eraser, (int(lx), int(ly)), special_flags=pygame.BLEND_RGBA_SUB)
        self.screen.blit(scratch, (0, 0))

    def _render_server_explosions(self,
                                  frame: Optional[FrameContext] = None):
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

                self._render_world_object(
                    frame, exp['y'],
                    lambda screen_x=screen_x, screen_y=screen_y,
                    elapsed=elapsed, radius=radius,
                    alpha=alpha: self._render_explosion_burst(
                        screen_x, screen_y, elapsed, radius, alpha))

                active.append(exp)

        self.client.active_explosions = active
