"""EffectsRenderMixin — damage numbers, bombs, projectiles, explosions.

Split from render.py; methods operate on the GameClient instance."""

import math
import random
from typing import Callable, Optional, Tuple

import pygame

from reborn_protocol.coords import in_level_bounds

from ..gani import AnimationState
from ..classic_sprites import draw_sprite, sprite_rect
from ..explosions import (
    EXPLOSION_TICKS, bomb_crosses, cross_cells, explosion_sound,
    explosion_sprite, order_point_y,
)
from ..prefs import Prefs
from ..throwing import LEAP_FRAMES, TICK, advance_throw, landing_type
from ..tiletypes import TileType
from .constants import TILE_SIZE, EXPLOSION_DURATION
from .flying import FlyingObjectsMixin
from .frame_context import FrameContext, FrameContextMixin
from .clocked import ClockedMixin
import logging
from ..logutil import log_swallowed
from ..lru import LruCache
logger = logging.getLogger(__name__)


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


class EffectsRenderMixin(ClockedMixin, FlyingObjectsMixin, FrameContextMixin):
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
        now = self.clock.frame_now()
        state = self.combat_presentation
        warp = bool(getattr(self.client, 'local_level_transition', ''))
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
        anim.frame = gani.frame_index_at(elapsed, direction)
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
        current_time = self.clock.frame_now()


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

    def _render_carried_bomb(self, x, y, bomb=None):
        sprite = self._get_effect_sprite((bomb or {}).get('image') or 'bomb.gif')
        if sprite is not None:
            self.screen.blit(sprite, (x, y))
        else:
            pygame.draw.circle(self.screen, (50, 50, 50),
                               (round(x + TILE_SIZE), round(y + TILE_SIZE)), TILE_SIZE)

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

    def _render_explosion_cell(self, frame, cell_x, cell_y, sprite_row,
                                elapsed, order_offset):
        # TServerLevel.cpp:1606-1607; TExplosion.cpp:24-46: fixed sprite,
        # top-left draw position, and the time-dependent order point.
        ticks_left = EXPLOSION_TICKS - int(elapsed / TICK + 1e-9)
        screen_x, screen_y = self.camera.world_to_screen(cell_x, cell_y)

        def draw():
            surf = draw_sprite(self.sprite_mgr, explosion_sprite(sprite_row))
            if surf is not None:
                self.screen.blit(surf, (screen_x, screen_y))
            else:
                alpha = int(255 * (1.0 - elapsed / EXPLOSION_DURATION))
                self._render_explosion_burst(screen_x, screen_y, elapsed, 16, alpha)

        self._render_world_object(
            frame, cell_y, draw,
            height_tiles=order_point_y(0.0, order_offset, ticks_left))

    @staticmethod
    def _bomb_explosion_cells(bomb):
        # TServerLevel.cpp:1710-1724: retain overlapping cells of all five crosses.
        return [cell for x, y, radius in bomb_crosses(
            bomb['x'], bomb['y'], bomb.get('power', 1))
                for cell in cross_cells(x, y, radius)]

    def _advance_bombs(self) -> None:
        """Simulation, once per tick: carried bombs follow their carrier, a
        lying bomb the Client does not simulate detonates on the legacy
        clock, and a finished burst leaves the registry after
        EXPLOSION_TICKS + 1 ticks (TServerLevel.cpp:1606, TExplosion.cpp:
        101-102: counter 11 down to 0, all twelve visible). Draws nothing."""
        current_time = self.clock.sim_now()
        tick = self.clock.tick
        active_bombs = []
        for bomb in self.active_bombs:
            if bomb.get('discarded'):
                continue
            carrier = bomb.get('carried_by')
            if carrier == self.client.player.id:
                bomb['x'], bomb['y'] = self.client.x + .5, self.client.y - 1.375
            elif carrier is not None:
                owner = self.client.players.get(carrier)
                if owner is not None:
                    from ..throwing import remote_origin
                    ox, oy = remote_origin(self.client, owner)
                    bx, by = owner.get('world_x'), owner.get('world_y')
                    bomb['x'] = (owner.get('x', 0) + ox if bx is None else bx) + .5
                    bomb['y'] = (owner.get('y', 0) + oy if by is None else by) - 1.375
            fuse_time = max(0.05, bomb.get('fuse_time', self.bomb_fuse_time))
            # A lying bomb the client simulates detonates when
            # Client._tick_bomb_sims fires (_on_client_bomb_exploded), not by
            # this clock (TServerLevel.cpp:1310-1337 lives in the Client).
            # Carried and in-flight bombs are not in that registry, and a
            # bomb the client does not know keeps the legacy clock.
            if not bomb.get('exploded') and (
                    carrier is not None or bomb.get('in_flight')
                    or not self.clock.passed(bomb['time'], fuse_time)
                    or self._client_bomb_record(bomb) is not None):
                active_bombs.append(bomb)
                continue
            if not bomb.get('exploded'):
                self._detonate_bomb(bomb, current_time)
            if tick - bomb.get('explosion_tick', tick) > EXPLOSION_TICKS:
                continue
            active_bombs.append(bomb)
        self.active_bombs = active_bombs

    def _render_bombs(self, frame: Optional[FrameContext] = None):
        """Draw the unified local/remote bomb registry (`_advance_bombs` runs
        it): lying bombs flash, exploded ones draw their burst cells."""
        current_time = self.clock.sim_now()
        tick = self.clock.tick
        for bomb in self.active_bombs:
            if bomb.get('discarded'):
                continue
            if bomb.get('carried_by') is not None or bomb.get('in_flight'):
                continue
            screen_x, screen_y = self.camera.world_to_screen(bomb['x'], bomb['y'])
            if not bomb.get('exploded'):
                fuse_time = max(0.05, bomb.get('fuse_time', self.bomb_fuse_time))
                elapsed = current_time - bomb['time']
                # Flash faster as fuse runs out
                flash_rate = 5 + min(1.0, elapsed / fuse_time) * 10
                if int(elapsed * flash_rate) % 2 == 0:
                    self._render_world_object(
                        frame, bomb['y'],
                        lambda screen_x=screen_x, screen_y=screen_y,
                        elapsed=elapsed: self._render_bomb_ticking(
                            screen_x, screen_y, elapsed))
                continue
            age = tick - bomb.get('explosion_tick', tick)
            if age > EXPLOSION_TICKS:
                continue
            if 'cells' not in bomb:
                bomb['cells'] = self._bomb_explosion_cells(bomb)
            for cell in bomb['cells']:
                self._render_explosion_cell(frame, cell.x, cell.y, cell.sprite_row,
                                            age * TICK, 0.0)

    def _add_remote_bomb(self, info: dict, now: Optional[float] = None):
        """Insert a wire bomb into the same registry used by local bombs."""
        now = self.clock.sim_now() if now is None else now
        x, y = info.get('x', 0.0), info.get('y', 0.0)
        bomb = {
            'x': x, 'y': y, 'time': info.get('placed_at', now),
            'fuse_time': max(0.05, info.get('timer_ms', 3050) / 1000.0),
            'power': info.get('power', 1), 'exploded': False,
            'source': 'remote',
        }
        if 'bomb_id' in info:
            bomb['bomb_id'] = info['bomb_id']
        self.active_bombs.append(bomb)
        return bomb

    def _detonate_bomb_at(self, x: float, y: float, now: Optional[float] = None):
        """Honor a removal packet immediately, without starting a second burst."""
        now = self.clock.sim_now() if now is None else now
        matches = []
        for bomb in self.active_bombs:
            tolerance = .51 if bomb.get('carried_by') is not None or bomb.get('in_flight') else .01
            if abs(bomb['x'] - x) < tolerance and abs(bomb['y'] - y) < tolerance:
                matches.append(bomb)
        if matches:
            bomb = next((b for b in matches if not b.get('exploded')), matches[0])
        else:
            bomb = {'x': x, 'y': y, 'time': now, 'fuse_time': 0.05,
                    'power': 1, 'exploded': False, 'source': 'remote'}
            self.active_bombs.append(bomb)
        self._detonate_bomb(bomb, now)
        return bomb

    def _client_bomb_record(self, bomb: dict):
        """The Client simulation's record for a lying registry bomb, if any."""
        records = getattr(self.client, 'bomb_records', None)
        if records is None:
            return None
        if 'bomb_id' in bomb:
            return next((r for r in records() if r['bomb_id'] == bomb['bomb_id']), None)
        assigned = {b['bomb_id'] for b in self.active_bombs if 'bomb_id' in b}
        for record in records():
            if (record['bomb_id'] not in assigned
                    and abs(record['wx'] - bomb['x']) < .01
                    and abs(record['wy'] - bomb['y']) < .01):
                bomb['bomb_id'] = record['bomb_id']
                return record
        return None

    def _on_client_bomb_exploded(self, record: dict, cells, now: Optional[float] = None):
        """Present a detonation the Client simulation already resolved (board
        blast, chain, damage): sound, shake and the cell animation."""
        now = self.clock.sim_now() if now is None else now
        bomb = next((b for b in self.active_bombs
                     if not b.get('exploded') and not b.get('discarded')
                     and b.get('carried_by') is None and not b.get('in_flight')
                     and ('bomb_id' not in b or b['bomb_id'] == record['bomb_id'])
                     and abs(record['wx'] - b['x']) < .01
                     and abs(record['wy'] - b['y']) < .01), None)
        if bomb is None:
            bomb = {'x': record['wx'], 'y': record['wy'], 'time': now,
                    'fuse_time': 0.05, 'power': record.get('power', 1),
                    'exploded': False, 'source': 'remote'}
            self.active_bombs.append(bomb)
        bomb['bomb_id'] = record['bomb_id']
        bomb['power'] = record.get('power', bomb.get('power', 1))
        return self._detonate_bomb(bomb, now, cells=cells)

    def _detonate_bomb(self, bomb: dict, now: Optional[float] = None, *,
                       cells=None):
        """Start a bomb's burst. `cells` marks a detonation the Client
        simulation already applied to the board, so it is not blasted again."""
        if bomb.get('exploded'):
            return False
        now = self.clock.sim_now() if now is None else now
        bomb['exploded'] = True
        bomb['explosion_time'] = now
        bomb['explosion_tick'] = self.clock.tick
        own_carry = (getattr(self.client.player, 'carried_bomb', None) is bomb
                     or any(obj.get('bomb') is bomb and not obj.get('remote')
                            for obj in getattr(self, 'thrown_objects', ())))
        if own_carry:
            # TClient.cpp:1386-1414: report the blast through PLI_EXPLOSION.
            self.client.send_explosion(2, bomb['x'], bomb['y'], bomb.get('power', 1))
        if getattr(self.client.player, 'carried_bomb', None) is bomb:
            from ..carrying import publish_carry
            self.client.player.throw_object()
            publish_carry(self.client, -1)
            if self.client.player.action_mode == 4:
                self.client.player.action_mode = 0
            self.player_anim.set_animation('idle', self.client.player.direction)
            self.current_anim_name = 'idle'
        for owner in getattr(self.client, 'players', {}).values():
            if owner.get('_carried_bomb') is bomb:
                owner.pop('_carried_bomb', None)
                owner['carry_sprite'] = -1
        # TServerLevel.cpp:1697: power is the bomb type, including joltbombs.
        self.sound_mgr.play(explosion_sound(bomb.get('power', 1)))
        self._start_camera_shake(bomb['x'], bomb['y'])
        if cells is not None:
            bomb['cells'] = list(cells)
            return True
        bomb['cells'] = self._bomb_explosion_cells(bomb)
        for cell in bomb['cells']:
            self.client.blast_board_at(cell.x, cell.y)
        return True

    def _start_camera_shake(self, x: float, y: float,
                            now: Optional[float] = None) -> bool:
        """Start a short visual-only shake for a nearby explosion."""
        player = self.client.player
        if math.hypot(float(x) - player.x, float(y) - player.y) > 8.0:
            return False
        now = self.clock.frame_now() if now is None else now
        started = getattr(self, '_camera_shake_started', None)
        if started is None or now - started >= 0.4:
            self._camera_shake_started = now
        return True

    def _break_bushes_in_blast(self, x: float, y: float, power: int):
        """Compatibility alias for one cell's board effects."""
        return self.client.blast_board_at(x, y)
    # Fallback triangle colors, keyed by the projectile's 'gani' name -
    # 'arrow' (the default, matching the classic brown arrow it replaces)
    # and 'firespy' (a distinct fire-orange, so a fireball doesn't look like
    # a wooden arrow when the asset hasn't downloaded).
    _PROJECTILE_FALLBACK_COLORS = {
        'firespy': ((255, 120, 30), (200, 70, 10)),
        'fireblast': ((255, 150, 40), (220, 60, 10)),
        'nukeshot': ((235, 235, 120), (255, 255, 255)),
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

    #: How long an arrow's impact spark lives after it stops at a wall.
    ARROW_HIT_SPARK_SECONDS = 0.12

    def _update_projectiles(self, dt: float) -> None:
        """Simulation: advance all arrows and flying objects by `dt`, stop an
        arrow at the first solid tile, and drop the ones that flew their
        maximum distance or whose impact spark is over. Draws nothing; see
        `_render_projectiles`."""
        current_time = self.clock.sim_now()
        active_projectiles = []
        for proj in self.active_projectiles:
            if 'hit_time' in proj:
                if not self.clock.passed(proj['hit_time'], self.ARROW_HIT_SPARK_SECONDS):
                    active_projectiles.append(proj)
                continue

            if proj.get('flying'):
                # Script-fired fireblast/nuke: 20 Hz hit rules (flying.py).
                if not self._advance_flying(proj, dt):
                    continue
                if self._projectile_in_range(proj):
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
            if hit or self._projectile_in_range(proj):
                active_projectiles.append(proj)

        self.active_projectiles = active_projectiles

    @staticmethod
    def _projectile_in_range(proj: dict) -> bool:
        """True while `proj` has not flown its maximum distance."""
        dist_x = proj['x'] - proj['start_x']
        dist_y = proj['y'] - proj['start_y']
        return (dist_x ** 2 + dist_y ** 2) ** 0.5 < proj['max_distance']

    def _interpolated_object(self, kind: str, obj: dict, x: float, y: float):
        """Draw position of a simulated object between the last two ticks
        (presentation only, game/interpolation.py)."""
        interpolator = getattr(self, 'interpolator', None)
        if interpolator is None:
            return x, y
        return interpolator.position((kind, id(obj)), (x, y), self.clock.tick,
                                     self.clock.alpha, owner=obj)

    def _render_projectiles(self, frame: Optional[FrameContext] = None) -> None:
        """Draw every live arrow, flying object and impact spark."""
        current_time = self.clock.sim_now()
        for proj in self.active_projectiles:
            if 'hit_time' in proj:
                self._render_arrow_hit_spark(proj, current_time)
                continue
            draw_x, draw_y = self._interpolated_object('proj', proj, proj['x'], proj['y'])
            screen_x, screen_y = self.camera.world_to_screen(draw_x, draw_y)
            self._render_world_object(
                frame, proj['y'],
                lambda proj=proj, screen_x=screen_x, screen_y=screen_y,
                current_time=current_time: self._render_projectile_marker(
                    proj.get('gani', 'arrow'), screen_x, screen_y,
                    proj['direction'],
                    current_time - proj.get('time', current_time)))

    def _update_and_render_projectiles(self, dt: float,
                                       frame: Optional[FrameContext] = None):
        """Update then draw, for a harness that renders outside `step()`."""
        self._update_projectiles(dt)
        self._render_projectiles(frame)

    def _render_arrow_hit_spark(self, proj: dict, now: float):
        screen_x, screen_y = self.camera.world_to_screen(proj['x'], proj['y'])
        age = now - proj['hit_time']
        radius = max(1, int(5 * (1.0 - age / 0.12)))
        pygame.draw.circle(self.screen, (255, 220, 120),
                           (int(screen_x), int(screen_y)), radius, 1)

    def _add_remote_arrow(self, info: dict, now: Optional[float] = None):
        now = self.clock.sim_now() if now is None else now
        direction = info.get('direction', 2)
        vx, vy = self._ARROW_DIRECTION_VECTOR.get(direction, (0, 1))
        x, y = info.get('x', 0.0), info.get('y', 0.0)
        # 1 tile per tick (TClient.cpp:3646), flying until a wall or the
        # server's 2-level cap, like our own arrows and the Client's
        # victim-side simulation (it used to fly 8 tiles/s for 10 tiles).
        speed = getattr(self.client, 'ARROW_SPEED', 20.0)
        arrow = {
            'x': x, 'y': y, 'dx': vx * speed, 'dy': vy * speed,
            'time': now, 'direction': direction, 'gani': 'arrow',
            'max_distance': getattr(self.client, 'ARROW_MAX_DISTANCE', 128.0),
            'start_x': x, 'start_y': y,
            'source': 'remote',
        }
        self.active_projectiles.append(arrow)
        return arrow

    # Fallback tints for weapon-hit bursts.
    BREAK_COLORS = {
        'bush': ((60, 145, 60), (28, 96, 28)),
        'pot':  ((198, 150, 104), (140, 96, 60)),
        'vase': ((198, 150, 104), (140, 96, 60)),
        'rock': ((150, 150, 150), (96, 96, 96)),
        'sign': ((174, 132, 72), (103, 70, 36)),
    }

    def _update_thrown(self, dt: float) -> None:
        """Simulation: advance our own and other players' thrown objects by
        `dt`, then the pushaway knockback. Draws nothing."""
        self.thrown_objects = self._advance_throws(self.thrown_objects, dt)
        self.other_thrown_objects = self._advance_throws(
            self.other_thrown_objects, dt, remote=True)
        self._apply_pushaway(dt)

    def _advance_throws(self, objects, dt, remote=False):
        survivors = []
        for obj in objects:
            bomb = obj.get('bomb')
            if bomb is not None and (bomb.get('exploded') or bomb.get('discarded')):
                continue
            if advance_throw(self, obj, dt, remote=remote):
                self._spawn_break_effect(obj)
                continue
            if bomb is not None:
                bomb['x'], bomb['y'] = obj['x'], obj['y'] - obj['z']
            survivors.append(obj)
        return survivors

    def _render_thrown(self, frame: Optional[FrameContext] = None) -> None:
        """Draw our own, then other players', thrown objects."""
        self._render_throws(self.thrown_objects, frame)
        self._render_throws(self.other_thrown_objects, frame)

    def _render_throws(self, objects, frame) -> None:
        for obj in objects:
            bomb = obj.get('bomb')
            if bomb is not None and (bomb.get('exploded') or bomb.get('discarded')):
                continue

            ox, oy = self._interpolated_object('thrown', obj, obj['x'], obj['y'])
            oz = self._interpolated_object('thrown_z', obj, obj['z'], 0.0)[0]

            def draw_thrown(obj=obj, ox=ox, oy=oy, oz=oz):
                # TServerCarry.cpp:86-97: shadow stays on the ground track.
                sx, sy = self.camera.world_to_screen(ox + .25, oy + 2.5)
                scale = getattr(self.camera, 'scale', TILE_SIZE)
                pygame.draw.ellipse(self.screen, (25, 25, 30),
                                    (sx, sy, max(1, 1.5 * scale), max(1, .4 * scale)))
                if obj.get('type') == 'bomb':
                    px, py = self.camera.world_to_screen(ox, oy - oz)
                    self._render_carried_bomb(px, py, obj.get('bomb'))
                    return
                for i, (dx, dy) in enumerate(((0, 0), (1, 0), (0, 1), (1, 1))):
                    px, py = self.camera.world_to_screen(
                        ox + dx, oy - oz + dy)
                    self.screen.blit(self.tileset_mgr.get_tile_or_color(obj['tiles'][i]),
                                     (px, py))

            self._render_world_object(frame, obj['y'], draw_thrown, height_tiles=2.0)

    def _update_and_render_thrown(self, dt: float,
                                  frame: Optional[FrameContext] = None):
        """Update then draw, for a harness that renders outside `step()`."""
        self._update_thrown(dt)
        self._render_thrown(frame)

    def _update_and_render_other_thrown(self, dt: float,
                                        frame: Optional[FrameContext] = None):
        self.other_thrown_objects = self._advance_throws(
            self.other_thrown_objects, dt, remote=True)
        self._render_throws(self.other_thrown_objects, frame)

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
        """Queue the existing weapon-hit spark burst at its reported point."""
        self.break_effects.append({
            'x': x, 'y': y,
            'time': self.clock.frame_now(),
            'colors': self.BREAK_COLORS['bush'],
        })
        self.sound_mgr.play("crush.wav")

    def _spawn_break_effect(self, obj):
        """Queue a table-driven burst at the object's ground landing point."""
        if obj.get('type') == 'bomb' and obj.get('remote'):
            bomb = obj.get('bomb')
            self.active_bombs[:] = [b for b in self.active_bombs if b is not bomb]
            return
        leap_type = landing_type(self, obj)
        if obj.get('type') == 'bomb' and obj.get('bomb') is not None:
            bomb = obj['bomb']
            if leap_type != 5:
                # TServerCarry.cpp:237-258: re-place the live bomb using sprite y.
                bomb['x'], bomb['y'] = obj['x'], obj['y'] - obj['z'] + 1.5
                bomb['in_flight'] = False
                remaining = max(50, round(bomb.get('fuse_remaining', bomb['fuse_time']) * 1000))
                bomb['time'], bomb['fuse_time'] = self.clock.sim_now(), remaining / 1000
                bomb.pop('fuse_remaining', None)
                bomb.pop('bomb_id', None)
                if not obj.get('remote'):
                    # TServerCarry.cpp:243-253: the carry's own player flag
                    # rides sendBomb, so the re-placed bomb stays ours.
                    self.client.put_bomb(bomb['x'], bomb['y'], bomb.get('power', 1),
                                         timer_ms=remaining, consume_ammo=False,
                                         from_player=True)
                    self._client_bomb_record(bomb)
                return
            self.active_bombs[:] = [b for b in self.active_bombs if b is not bomb]
        self.break_effects.append({
            'x': obj['x'], 'y': obj['y'], 'time': self.clock.frame_now(),
            'leap_type': leap_type, 'tiles': obj.get('tiles', ()),
        })
        # TServerLevel.cpp:2850-2866: only landing plays the object sound.
        self.sound_mgr.play('water.wav' if leap_type == 5 else 'crush.wav')

    BREAK_DURATION = 0.45
    LEAF_DURATION = 0.6
    MAX_LEAF_PARTICLES = 64

    def _spawn_leaf_particles(self, x: float, y: float, now=None, count=None):
        """Add a small capped spray of procedural vegetation fragments."""
        now = self.clock.frame_now() if now is None else now
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
        now = self.clock.frame_now() if now is None else now
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
            cache = self._particle_surf_cache = LruCache(self._PARTICLE_CACHE_CAP)
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
        now = self.clock.frame_now()
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

    # Scripted bursts and thrown-object landings share the leap frame data.
    LEAP_FRAME_TIME = TICK
    MAX_LEAP_BURSTS = 64

    _LEAP_SPRITE_RECTS = {
        sprite: sprite_rect(sprite)
        for frames in LEAP_FRAMES
        for frame in frames
        for sprite, _dx, _dy in frame
    }

    _LEAP_FRAMES = LEAP_FRAMES

    def _spawn_leaps(self, leap_type: int, x: float, y: float, now=None):
        """GS1 `putleaps type,x,y` (wired from gs1.on_putleaps): queue the
        burst at level coords (x, y) and play its spawn sound."""
        if not 0 <= int(leap_type) <= 5:
            return
        now = self.clock.frame_now() if now is None else now
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
            log_swallowed(logger)

    def _render_leaps(self):
        """Draw active putleaps bursts and expire finished ones."""
        bursts = getattr(self, 'leap_bursts', None)
        if not bursts:
            return
        now = self.clock.frame_now()
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
        now = self.clock.frame_now()
        ripples = getattr(self, 'water_ripples', None)
        if ripples is None:
            ripples = self.water_ripples = []
        if self.is_swimming and now - getattr(self, '_last_ripple_time', float('-inf')) >= 0.5:
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
        """Draw thrown-object leap frames and the existing weapon-hit sparks."""
        now = self.clock.frame_now()
        active = []
        for eff in self.break_effects:
            if 'leap_type' in eff:
                frames = LEAP_FRAMES[eff['leap_type']]
                frame = max(0, int((now - eff['time'] + 1e-9) / TICK))
                if frame >= len(frames):
                    continue
                for i, (_sprite, dx, dy) in enumerate(frames[frame]):
                    px, py = self.camera.world_to_screen(
                        eff['x'] + dx / 8, eff['y'] + dy / 8)
                    if eff['leap_type'] == 5:
                        scale = max(1, round(getattr(self.camera, 'scale', TILE_SIZE)))
                        pygame.draw.rect(self.screen, (150, 215, 255),
                                         (px, py, scale, scale))
                    elif i < len(eff['tiles']):
                        self.screen.blit(
                            self.tileset_mgr.get_tile_or_color(eff['tiles'][i]), (px, py))
                active.append(eff)
                continue
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
        """Draw the client's explosion cells (Client.make_explosion). The
        Client drops each after EXPLOSION_TICKS + 1 ticks
        (Client._expire_explosions); this only draws."""
        tick = self.clock.tick
        for exp in self.client.active_explosions:
            elapsed = (tick - exp.get('tick', tick)) * TICK
            if 'sprite_row' in exp:
                self._render_explosion_cell(
                    frame, exp['x'], exp['y'], exp['sprite_row'], elapsed,
                    exp.get('order_offset', 0.0))
            else:
                # Legacy script bursts store a whole cross in one entry.
                for cell in cross_cells(exp['x'], exp['y'], exp.get('radius', 2)):
                    self._render_explosion_cell(
                        frame, cell.x, cell.y, cell.sprite_row, elapsed,
                        exp.get('order_offset', 0.0))
