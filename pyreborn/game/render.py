"""RenderMixin — All rendering plus per-frame visual/animation updates.

Split from pygame_game.py; methods operate on the GameClient instance."""

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


class RenderMixin:
    """Mixin providing the above methods for GameClient."""

    def _update_animations(self, dt: float):
        """Update all animation states."""
        # Update local player animation
        sounds = self.player_anim.update(dt)
        for sound in sounds:
            self.sound_mgr.play_from_gani(sound)

        # Check if animation finished and needs setback
        if self.player_anim.is_finished():
            setback = self.player_anim.get_setback()
            if setback:
                self.player_anim.set_animation(setback, self.client.player.direction)
                self.current_anim_name = setback
            elif self.client.player.is_carrying():
                # Switch to carry animation after lift finishes
                self.player_anim.set_animation("carry", self.client.player.direction)
                self.current_anim_name = "carry"
            elif self.client.player.is_sitting:
                # Stay in sit animation
                self.player_anim.set_animation("sit", self.client.player.direction)
                self.current_anim_name = "sit"
            elif self.current_anim_name != "idle":
                self.player_anim.set_animation("idle", self.client.player.direction)
                self.current_anim_name = "idle"

        # If carrying and not in a transition animation, use carry
        if self.client.player.is_carrying():
            if self.current_anim_name not in ("lift", "throw", "carry"):
                self.player_anim.set_animation("carry", self.client.player.direction)
                self.current_anim_name = "carry"

        # If sitting and not already in sit animation
        if self.client.player.is_sitting:
            if self.current_anim_name != "sit":
                self.player_anim.set_animation("sit", self.client.player.direction)
                self.current_anim_name = "sit"

        # If not moving, switch to appropriate idle animation
        if not self.is_moving and self.current_anim_name in ("walk", "swim"):
            if self.is_swimming:
                # Use swim idle animation (or swim if no swim_idle exists)
                self.player_anim.set_animation("swim", self.client.player.direction)
                self.current_anim_name = "swim"
            elif self.client.player.is_carrying():
                self.player_anim.set_animation("carry", self.client.player.direction)
                self.current_anim_name = "carry"
            else:
                self.player_anim.set_animation("idle", self.client.player.direction)
                self.current_anim_name = "idle"

        # Update other player animations
        for pid, anim in list(self.other_player_anims.items()):
            if pid not in self.client.players:
                del self.other_player_anims[pid]
                continue
            anim.update(dt)

        # Update NPC animations
        for npc_id, anim in list(self.npc_anims.items()):
            if npc_id not in self.client.npcs:
                del self.npc_anims[npc_id]
                continue
            anim.update(dt)
    def _update_visual_position(self, dt: float):
        """Smoothly interpolate visual position toward actual position."""
        target_x = self.client.x
        target_y = self.client.y

        # Calculate distance to target
        dx = target_x - self.visual_x
        dy = target_y - self.visual_y

        # Large gap = a warp/teleport, not walking: snap immediately so we don't
        # slide across the whole level.
        if abs(dx) > 2.0 or abs(dy) > 2.0:
            self.visual_x = target_x
            self.visual_y = target_y
            return

        # Very close: snap to kill sub-pixel jitter.
        if abs(dx) < 0.02 and abs(dy) < 0.02:
            self.visual_x = target_x
            self.visual_y = target_y
            return

        # Otherwise always lerp toward the target (exponential smoothing). This
        # keeps the character gliding smoothly to a stop on key release instead
        # of snapping forward.
        lerp_factor = min(1.0, self.lerp_speed * dt)
        self.visual_x += dx * lerp_factor
        self.visual_y += dy * lerp_factor
    def _render(self):
        """Render the game."""
        # Clear screen
        self.screen.fill((34, 139, 34))

        # Render world
        self._render_world()

        # Render debug overlay if enabled
        if self.debug_mode:
            self._render_debug_overlay()

        # Render level chests (on the ground, behind entities)
        self._render_chests()

        # Render entities (sorted by Y for depth)
        self._render_entities()

        # Render combat effects (damage numbers, bombs, projectiles, explosions)
        self._render_damage_numbers()
        self._render_bombs()
        self._update_and_render_projectiles(getattr(self, '_last_dt', 0.016))
        self._render_server_explosions()

        # Render sign popups
        self._check_and_render_signs()

        # Render UI
        self._render_ui()

        # Flip display
        pygame.display.flip()
    def _world_to_screen(self, world_x: float, world_y: float) -> Tuple[float, float]:
        """Convert world tile coordinates to screen pixel coordinates.

        Uses the same GMAP-relative camera offset as entity rendering so
        overlays line up with players, NPCs and tiles.
        """
        gmap_visual_x = self.visual_x - self.client._gmap_offset_x * 64
        gmap_visual_y = self.visual_y - self.client._gmap_offset_y * 64
        cam_offset_x = SCREEN_WIDTH // 2 - gmap_visual_x * TILE_SIZE
        cam_offset_y = SCREEN_HEIGHT // 2 - gmap_visual_y * TILE_SIZE
        return (world_x * TILE_SIZE + cam_offset_x,
                world_y * TILE_SIZE + cam_offset_y)

    # Chest sprite as a tile layout into the tileset (dustynewpics1.png).
    # The chest art is a 3-wide x 2-tall block centered on the chest footprint.
    CHEST_TILES_CLOSED = ((3312, 3313, 3314),
                          (3328, 3329, 3330))
    def _get_chest_sprite(self, opened: bool) -> Optional[pygame.Surface]:
        """Build (and cache) the chest sprite from tileset tiles.

        Chests are a client-side overlay (not baked into the level board), so we
        composite the chest graphic from the tileset here. Opened chests reuse
        the same tiles dimmed, until distinct open-chest tiles are wired in.
        """
        cache = getattr(self, "_chest_sprite_cache", None)
        if cache is None:
            cache = {}
            self._chest_sprite_cache = cache
        if opened in cache:
            return cache[opened]

        layout = self.CHEST_TILES_CLOSED
        rows = len(layout)
        cols = len(layout[0])
        surf = pygame.Surface((cols * TILE_SIZE, rows * TILE_SIZE), pygame.SRCALPHA)

        drew_any = False
        for ry, row in enumerate(layout):
            for cx, tile_id in enumerate(row):
                tile = self.tileset_mgr.get_tile(tile_id)
                if tile:
                    surf.blit(tile, (cx * TILE_SIZE, ry * TILE_SIZE))
                    drew_any = True

        if not drew_any:
            cache[opened] = None
            return None

        if opened:
            # Dim looted chests so open/closed reads at a glance.
            surf.fill((110, 110, 110, 255), special_flags=pygame.BLEND_RGBA_MULT)

        cache[opened] = surf
        return surf
    def _render_chests(self):
        """Draw level chests from client state, reflecting open/closed."""
        chests = getattr(self.client, "chests", None)
        if not chests:
            return

        for (cx, cy), opened in chests.items():
            sprite = self._get_chest_sprite(bool(opened))
            if sprite is None:
                continue
            # Chest tile (cx, cy) is the top-left of its 2x2 footprint. The
            # sprite is 3 tiles wide, so shift left half a tile to center it
            # over the 2-wide footprint.
            sprite_tiles_w = sprite.get_width() / TILE_SIZE
            origin_x = cx - (sprite_tiles_w - 2) / 2.0
            sx, sy = self._world_to_screen(origin_x, cy)
            # Cull if fully off-screen
            if sx < -sprite.get_width() or sx > SCREEN_WIDTH or \
               sy < -sprite.get_height() or sy > SCREEN_HEIGHT:
                continue
            self.screen.blit(sprite, (int(sx), int(sy)))
    def _render_debug_overlay(self):
        """Render colored overlay showing tile types."""
        # Get camera offset using GMAP-relative visual position
        gmap_visual_x = self.visual_x - self.client._gmap_offset_x * 64
        gmap_visual_y = self.visual_y - self.client._gmap_offset_y * 64

        world_px = gmap_visual_x * TILE_SIZE
        world_py = gmap_visual_y * TILE_SIZE

        cam_offset_x = SCREEN_WIDTH // 2 - world_px
        cam_offset_y = SCREEN_HEIGHT // 2 - world_py

        # Calculate visible tile range
        start_tile_x = int(-cam_offset_x / TILE_SIZE) - 1
        start_tile_y = int(-cam_offset_y / TILE_SIZE) - 1
        end_tile_x = start_tile_x + (SCREEN_WIDTH // TILE_SIZE) + 3
        end_tile_y = start_tile_y + (SCREEN_HEIGHT // TILE_SIZE) + 3

        # Create semi-transparent surfaces for each tile type
        blocking_color = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
        blocking_color.fill((255, 0, 0, 100))  # Red for blocking

        water_color = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
        water_color.fill((0, 100, 255, 100))  # Blue for water

        walkable_color = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
        walkable_color.fill((0, 255, 0, 50))  # Green for walkable (subtle)

        chair_color = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
        chair_color.fill((255, 200, 0, 120))  # Yellow/orange for chairs

        bush_color = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
        bush_color.fill((0, 180, 0, 120))  # Dark green for bushes

        pot_color = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
        pot_color.fill((180, 100, 50, 120))  # Brown for pots

        rock_color = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
        rock_color.fill((128, 128, 128, 120))  # Gray for rocks

        # Draw overlay for each visible tile
        for ty in range(start_tile_y, end_tile_y):
            for tx in range(start_tile_x, end_tile_x):
                # Get tile at this world position
                tile_id = self._get_tile_at(tx, ty)
                if tile_id == 0:
                    continue

                tile_type = self._get_corrected_tile_type(tile_id)

                # Calculate screen position
                screen_x = tx * TILE_SIZE + cam_offset_x
                screen_y = ty * TILE_SIZE + cam_offset_y

                # Skip if off screen
                if screen_x < -TILE_SIZE or screen_x > SCREEN_WIDTH:
                    continue
                if screen_y < -TILE_SIZE or screen_y > SCREEN_HEIGHT:
                    continue

                # Draw overlay based on tile type
                if tile_type == TileType.BLOCKING:
                    self.screen.blit(blocking_color, (screen_x, screen_y))
                elif tile_type in (TileType.WATER, TileType.NEAR_WATER):
                    self.screen.blit(water_color, (screen_x, screen_y))
                elif tile_type == TileType.CHAIR:
                    self.screen.blit(chair_color, (screen_x, screen_y))
                elif tile_type == TileType.BUSH:
                    self.screen.blit(bush_color, (screen_x, screen_y))
                elif tile_type == TileType.POT:
                    self.screen.blit(pot_color, (screen_x, screen_y))
                elif tile_type == TileType.ROCK:
                    self.screen.blit(rock_color, (screen_x, screen_y))
                else:
                    self.screen.blit(walkable_color, (screen_x, screen_y))
    def _render_world(self):
        """Render the tile world."""
        world_surf = self._get_world_surface()
        if not world_surf:
            return

        # Calculate camera offset using visual position in GMAP coordinate space
        # Convert world coords to GMAP-relative coords by subtracting offset
        gmap_visual_x = self.visual_x - self.client._gmap_offset_x * 64
        gmap_visual_y = self.visual_y - self.client._gmap_offset_y * 64

        # World pixel position (using GMAP-relative visual position)
        world_px = gmap_visual_x * TILE_SIZE
        world_py = gmap_visual_y * TILE_SIZE

        offset_x = SCREEN_WIDTH // 2 - world_px
        offset_y = SCREEN_HEIGHT // 2 - world_py

        self.screen.blit(world_surf, (offset_x, offset_y))
    def _get_world_surface(self) -> Optional[pygame.Surface]:
        """Get or create the world surface."""
        if not self.client.levels and not self.client.tiles:
            return None

        # Check if we need to invalidate cache
        current_count = len(self.client.levels) + (1 if self.client.tiles else 0)
        current_level = self.client._current_level_name
        current_level_keys = set(self.client.levels.keys())

        # Invalidate if: count changed, level changed, or new levels appeared
        needs_redraw = (
            current_count != self.last_level_count or
            current_level != self.last_level_name or
            not current_level_keys.issubset(self.known_levels)
        )

        if not needs_redraw and self.world_surface:
            return self.world_surface

        # Update tracking
        self.last_level_count = current_count
        self.last_level_name = current_level
        self.known_levels.update(current_level_keys)

        # Check if current level is in GMAP
        in_gmap = self.client._current_level_name in self.client.gmap_grid.values()

        if in_gmap and self.client.gmap_grid:
            world_w = max(1, self.client.gmap_width) * 64 * TILE_SIZE
            world_h = max(1, self.client.gmap_height) * 64 * TILE_SIZE
        else:
            world_w = 64 * TILE_SIZE
            world_h = 64 * TILE_SIZE

        self.world_surface = pygame.Surface((world_w, world_h))
        self.world_surface.fill((34, 139, 34))

        # Render tiles
        if not in_gmap or not self.client.gmap_grid:
            self._render_single_level(self.world_surface, self.client.tiles, 0, 0)
        else:
            for (gx, gy), level_name in self.client.gmap_grid.items():
                if level_name in self.client.levels:
                    level_tiles = self.client.levels[level_name]
                    offset_x = gx * 64 * TILE_SIZE
                    offset_y = gy * 64 * TILE_SIZE
                    self._render_single_level(self.world_surface, level_tiles, offset_x, offset_y)

        return self.world_surface
    def _render_single_level(self, surface: pygame.Surface, tiles: List[int],
                              offset_x: int, offset_y: int):
        """Render a single level's tiles."""
        if not tiles:
            return

        for ty in range(64):
            for tx in range(64):
                tile_id = tiles[ty * 64 + tx]
                dest_x = offset_x + tx * TILE_SIZE
                dest_y = offset_y + ty * TILE_SIZE

                tile = self.tileset_mgr.get_tile_or_color(tile_id)
                surface.blit(tile, (dest_x, dest_y))
    def _render_entities(self):
        """Render all entities (players, NPCs) sorted by Y position."""
        entities = []

        # Calculate camera offset using GMAP-relative visual position
        # This avoids jumps when _current_level_name changes during interpolation
        gmap_visual_x = self.visual_x - self.client._gmap_offset_x * 64
        gmap_visual_y = self.visual_y - self.client._gmap_offset_y * 64

        world_px = gmap_visual_x * TILE_SIZE
        world_py = gmap_visual_y * TILE_SIZE
        cam_offset_x = SCREEN_WIDTH // 2 - world_px
        cam_offset_y = SCREEN_HEIGHT // 2 - world_py

        # Add local player - screen center (camera follows player)
        player = self.client.player
        local_y = self.visual_y % 64
        px = SCREEN_WIDTH // 2
        py = SCREEN_HEIGHT // 2
        entities.append(('player', local_y, px, py, player))

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

                opx = vx * TILE_SIZE + cam_offset_x
                opy = vy * TILE_SIZE + cam_offset_y
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

                npx = vx * TILE_SIZE + cam_offset_x
                npy = vy * TILE_SIZE + cam_offset_y
                entities.append(('npc', vy, npx, npy, npc, npc_id))

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
    def _render_damage_numbers(self):
        """Render floating damage numbers."""
        current_time = time.time()

        # Get camera offset
        gmap_visual_x = self.visual_x - self.client._gmap_offset_x * 64
        gmap_visual_y = self.visual_y - self.client._gmap_offset_y * 64
        world_px = gmap_visual_x * TILE_SIZE
        world_py = gmap_visual_y * TILE_SIZE
        cam_offset_x = SCREEN_WIDTH // 2 - world_px
        cam_offset_y = SCREEN_HEIGHT // 2 - world_py

        # Update and render each damage number
        active_numbers = []
        for dmg in self.damage_numbers:
            elapsed = current_time - dmg['time']
            if elapsed < dmg['duration']:
                # Calculate position (float up over time)
                float_offset = elapsed * 30  # Float up 30 pixels per second
                alpha = int(255 * (1.0 - elapsed / dmg['duration']))

                # Convert world position to screen position
                screen_x = dmg['x'] * TILE_SIZE + cam_offset_x
                screen_y = (dmg['y'] * TILE_SIZE + cam_offset_y) - float_offset

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
    def _render_bombs(self):
        """Render active bombs and explosions."""
        current_time = time.time()

        # Get camera offset
        gmap_visual_x = self.visual_x - self.client._gmap_offset_x * 64
        gmap_visual_y = self.visual_y - self.client._gmap_offset_y * 64
        world_px = gmap_visual_x * TILE_SIZE
        world_py = gmap_visual_y * TILE_SIZE
        cam_offset_x = SCREEN_WIDTH // 2 - world_px
        cam_offset_y = SCREEN_HEIGHT // 2 - world_py

        active_bombs = []
        for bomb in self.active_bombs:
            elapsed = current_time - bomb['time']

            # Convert world position to screen position
            screen_x = bomb['x'] * TILE_SIZE + cam_offset_x
            screen_y = bomb['y'] * TILE_SIZE + cam_offset_y

            if not bomb['exploded'] and elapsed < self.bomb_fuse_time:
                # Bomb is still counting down - render bomb sprite
                # Flash faster as fuse runs out
                flash_rate = 5 + (elapsed / self.bomb_fuse_time) * 10
                if int(elapsed * flash_rate) % 2 == 0:
                    # Draw bomb (simple circle for now)
                    pygame.draw.circle(self.screen, (50, 50, 50), (int(screen_x), int(screen_y)), 8)
                    pygame.draw.circle(self.screen, (30, 30, 30), (int(screen_x), int(screen_y)), 6)
                    # Fuse spark
                    fuse_x = screen_x + 4
                    fuse_y = screen_y - 8
                    pygame.draw.circle(self.screen, (255, 200, 50), (int(fuse_x), int(fuse_y)), 3)
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

                # Draw explosion circles
                explosion_surf = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
                pygame.draw.circle(explosion_surf, (255, 150, 50, alpha), (radius, radius), radius)
                pygame.draw.circle(explosion_surf, (255, 100, 0, alpha), (radius, radius), int(radius * 0.7))
                pygame.draw.circle(explosion_surf, (255, 200, 100, alpha), (radius, radius), int(radius * 0.4))

                self.screen.blit(explosion_surf, (screen_x - radius, screen_y - radius))
                active_bombs.append(bomb)
            # else: bomb finished, don't add to active list

        self.active_bombs = active_bombs
    def _update_and_render_projectiles(self, dt: float):
        """Update and render active projectiles."""
        current_time = time.time()

        # Get camera offset
        gmap_visual_x = self.visual_x - self.client._gmap_offset_x * 64
        gmap_visual_y = self.visual_y - self.client._gmap_offset_y * 64
        world_px = gmap_visual_x * TILE_SIZE
        world_py = gmap_visual_y * TILE_SIZE
        cam_offset_x = SCREEN_WIDTH // 2 - world_px
        cam_offset_y = SCREEN_HEIGHT // 2 - world_py

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
                screen_x = proj['x'] * TILE_SIZE + cam_offset_x
                screen_y = proj['y'] * TILE_SIZE + cam_offset_y

                # Draw arrow based on direction
                direction = proj['direction']
                if direction == 0:  # up
                    points = [(screen_x, screen_y - 8), (screen_x - 3, screen_y + 4), (screen_x + 3, screen_y + 4)]
                elif direction == 1:  # left
                    points = [(screen_x - 8, screen_y), (screen_x + 4, screen_y - 3), (screen_x + 4, screen_y + 3)]
                elif direction == 2:  # down
                    points = [(screen_x, screen_y + 8), (screen_x - 3, screen_y - 4), (screen_x + 3, screen_y - 4)]
                else:  # right
                    points = [(screen_x + 8, screen_y), (screen_x - 4, screen_y - 3), (screen_x - 4, screen_y + 3)]

                pygame.draw.polygon(self.screen, (139, 69, 19), points)  # Brown arrow
                pygame.draw.polygon(self.screen, (80, 40, 10), points, 1)  # Outline

                active_projectiles.append(proj)

        self.active_projectiles = active_projectiles
    def _render_server_explosions(self):
        """Render explosions received from server (PLO_EXPLOSION packets)."""
        current_time = time.time()
        explosion_duration = 0.5  # seconds

        # Get camera offset
        gmap_visual_x = self.visual_x - self.client._gmap_offset_x * 64
        gmap_visual_y = self.visual_y - self.client._gmap_offset_y * 64
        world_px = gmap_visual_x * TILE_SIZE
        world_py = gmap_visual_y * TILE_SIZE
        cam_offset_x = SCREEN_WIDTH // 2 - world_px
        cam_offset_y = SCREEN_HEIGHT // 2 - world_py

        # Clean up expired explosions and render active ones
        active = []
        for exp in self.client.active_explosions:
            elapsed = current_time - exp['time']
            if elapsed < explosion_duration:
                # Calculate screen position
                screen_x = exp['x'] * TILE_SIZE + cam_offset_x
                screen_y = exp['y'] * TILE_SIZE + cam_offset_y

                # Expanding explosion based on radius
                progress = elapsed / explosion_duration
                base_radius = exp.get('radius', 2) * TILE_SIZE
                radius = int(base_radius * (0.5 + progress * 0.5))
                alpha = int(255 * (1.0 - progress))

                # Draw explosion circles
                if radius > 0:
                    explosion_surf = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
                    pygame.draw.circle(explosion_surf, (255, 150, 50, alpha), (radius, radius), radius)
                    pygame.draw.circle(explosion_surf, (255, 100, 0, alpha), (radius, radius), int(radius * 0.7))
                    pygame.draw.circle(explosion_surf, (255, 200, 100, alpha), (radius, radius), int(radius * 0.4))
                    self.screen.blit(explosion_surf, (screen_x - radius, screen_y - radius))

                active.append(exp)

        self.client.active_explosions = active
    def _check_and_render_signs(self):
        """Check if player is near a sign and show popup."""
        if not self.client.signs:
            return

        px = self.client.player.x
        py = self.client.player.y

        # Check each sign
        for (sx, sy), text in self.client.signs.items():
            # Check if player is within 2 tiles of sign
            if abs(px - sx) < 2 and abs(py - sy) < 2:
                self._render_sign_popup(text)
                break  # Only show one sign at a time
    def _render_sign_popup(self, text: str):
        """Render sign text as popup overlay."""
        if not text:
            return

        # Render sign text in a box at bottom of screen
        font = getattr(self, '_sign_font', None)
        if font is None:
            try:
                self._sign_font = pygame.font.Font(None, 24)
            except:
                self._sign_font = pygame.font.SysFont('monospace', 20)
            font = self._sign_font

        # Split text into lines
        lines = text.split('\n')
        line_height = font.get_linesize()
        max_width = 0
        rendered_lines = []

        for line in lines:
            rendered = font.render(line, True, (0, 0, 0))
            rendered_lines.append(rendered)
            max_width = max(max_width, rendered.get_width())

        # Create background box
        box_width = max_width + 20
        box_height = len(rendered_lines) * line_height + 20
        box_x = (SCREEN_WIDTH - box_width) // 2
        box_y = SCREEN_HEIGHT - box_height - 60  # Above the UI bar

        # Draw box with border
        pygame.draw.rect(self.screen, (240, 230, 200), (box_x, box_y, box_width, box_height))
        pygame.draw.rect(self.screen, (100, 80, 50), (box_x, box_y, box_width, box_height), 2)

        # Draw text
        y = box_y + 10
        for rendered in rendered_lines:
            x = box_x + (box_width - rendered.get_width()) // 2
            self.screen.blit(rendered, (x, y))
            y += line_height
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
    def _render_npc(self, x: float, y: float, npc: dict, npc_id: int):
        """Render an NPC."""
        gani_name = npc.get('gani', npc.get('animation'))
        image_name = npc.get('image')

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
            self._render_animated_entity(x, y, anim, {})

        elif image_name:
            # Static sprite - position at top-left of NPC coords (no offset)
            sprite = self.sprite_mgr.load_sheet(image_name)
            if sprite:
                # Apply visual effects for light NPCs
                if is_light or coloreffect:
                    self._render_light_sprite(sprite, x, y, is_light, coloreffect)
                else:
                    self.screen.blit(sprite, (x, y))
            else:
                self.screen.blit(self.npc_placeholder, (x, y))
        else:
            # Placeholder
            self.screen.blit(self.npc_placeholder, (x, y))

        # Render NPC chat bubble if active (and not timed out)
        if npc_id in self.npc_chat_texts:
            text, chat_time = self.npc_chat_texts[npc_id]
            if time.time() - chat_time < self.chat_bubble_duration:
                self._render_speech_bubble(x, y, text)
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
    def _draw_stat_icon(self, x: int, y: int, kind: str, count: int) -> int:
        """Draw a small consumable icon + count. Returns the x after the text."""
        s = self.screen
        cy = y + 8
        if kind == 'rupee':
            # Green diamond
            pygame.draw.polygon(s, (60, 220, 90),
                                [(x + 6, y), (x + 12, cy), (x + 6, y + 16), (x, cy)])
            pygame.draw.polygon(s, (20, 110, 40),
                                [(x + 6, y), (x + 12, cy), (x + 6, y + 16), (x, cy)], 1)
        elif kind == 'bomb':
            # Dark sphere with a fuse
            pygame.draw.circle(s, (40, 40, 50), (x + 6, cy + 1), 6)
            pygame.draw.circle(s, (90, 90, 105), (x + 4, cy - 1), 2)
            pygame.draw.line(s, (200, 150, 60), (x + 9, y + 2), (x + 11, y - 2), 2)
        elif kind == 'arrow':
            # Simple arrow pointing up-right
            pygame.draw.line(s, (210, 200, 180), (x, y + 14), (x + 12, y + 2), 2)
            pygame.draw.polygon(s, (210, 200, 180),
                                [(x + 12, y + 2), (x + 7, y + 3), (x + 11, y + 7)])
        txt = self.font_small.render(str(count), True, (245, 245, 245))
        s.blit(txt, (x + 16, y + 1))
        return x + 16 + txt.get_width()
    def _render_help_overlay(self):
        """Centered controls panel, toggled with H."""
        lines = [
            ("Arrow Keys", "Move"),
            ("A", "Grab / Pick up / Throw"),
            ("S or Space", "Swing sword"),
            ("D", "Use weapon"),
            ("Q", "Inventory"),
            ("M", "Toggle minimap"),
            ("Enter", "Chat"),
            ("F1", "Debug / tile editor"),
            ("H", "Close this help"),
        ]
        pad = 14
        line_h = 22
        w = 320
        h = pad * 2 + 28 + line_h * len(lines)
        x = (SCREEN_WIDTH - w) // 2
        y = (SCREEN_HEIGHT - h) // 2

        panel = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(panel, (0, 0, 0, 200), (0, 0, w, h), border_radius=8)
        pygame.draw.rect(panel, (120, 120, 160, 255), (0, 0, w, h), width=2, border_radius=8)
        self.screen.blit(panel, (x, y))

        title = self.font.render("Controls", True, (255, 255, 255))
        self.screen.blit(title, (x + pad, y + pad))

        ty = y + pad + 30
        for key, desc in lines:
            ks = self.font_small.render(key, True, (255, 220, 120))
            ds = self.font_small.render(desc, True, (225, 225, 225))
            self.screen.blit(ks, (x + pad, ty))
            self.screen.blit(ds, (x + pad + 110, ty))
            ty += line_h
    def _render_ui(self):
        """Render UI elements."""
        player = self.client.player

        # --- Core HUD (always visible): hearts + consumables in one panel ---
        hearts_w = int(player.max_hearts) * (self.heart_display.HEART_SIZE +
                                             self.heart_display.HEART_SPACING)
        panel_w = max(168, hearts_w + 16)
        panel = pygame.Surface((panel_w, 52), pygame.SRCALPHA)
        pygame.draw.rect(panel, (0, 0, 0, 130), (0, 0, panel_w, 52), border_radius=6)
        self.screen.blit(panel, (6, 6))

        # Hearts row
        self.heart_display.render(self.screen, player.hearts, player.max_hearts)

        # Consumables row: icon + count
        icon_y = 32
        x = self._draw_stat_icon(12, icon_y, 'rupee', player.rupees)
        x = self._draw_stat_icon(x + 12, icon_y, 'bomb', player.bombs)
        self._draw_stat_icon(x + 12, icon_y, 'arrow', player.arrows)

        ui_y = 64

        # --- Debug readouts (toggle with F1) ---
        if self.debug_mode:
            local_x = self.client.x % 64
            local_y = self.client.y % 64
            link_count = sum(len(l) for l in self.client.links.values())
            for line in (
                f"{self.client._current_level_name}  ({local_x:.1f}, {local_y:.1f})",
                f"Sword {player.sword_power}  Shield {player.shield_power}  Glove {player.glove_power}",
                f"NPCs {len(self.client.npcs)}  Links {link_count}",
            ):
                self._draw_text_with_bg(line, 10, ui_y, (140, 220, 140))
                ui_y += 20

        # Swimming status
        if self.is_swimming:
            self._draw_text_with_bg("SWIMMING", 10, ui_y, (100, 200, 255))
            ui_y += 20

        # Door prompt
        door = self._get_non_edge_door()
        if door:
            door_text = f"Door -> {door.get('dest_level', '?')} (press A)"
            self._draw_text_with_bg(door_text, 10, ui_y, (255, 255, 100))
            ui_y += 20

        # Carrying status
        player = self.client.player
        if player.is_carrying():
            carry_text = f"Carrying: {player.carried_object_type.title()} (A to throw)"
            self._draw_text_with_bg(carry_text, 10, ui_y, (100, 255, 100))
            ui_y += 20

        # Sitting status
        if player.is_sitting:
            sit_text = "Sitting (press A to stand)"
            self._draw_text_with_bg(sit_text, 10, ui_y, (255, 200, 100))
            ui_y += 20

        # Dialogue box
        if self.dialogue_text:
            elapsed = time.time() - self.dialogue_time
            if elapsed < self.dialogue_duration:
                # Fade out in last 0.5 seconds
                alpha = 255 if elapsed < self.dialogue_duration - 0.5 else int(255 * (self.dialogue_duration - elapsed) / 0.5)

                # Draw dialogue box
                box_width = min(SCREEN_WIDTH - 40, 400)
                box_height = 60
                box_x = (SCREEN_WIDTH - box_width) // 2
                box_y = SCREEN_HEIGHT - 150

                # Background
                box_surf = pygame.Surface((box_width, box_height), pygame.SRCALPHA)
                pygame.draw.rect(box_surf, (0, 0, 50, min(200, alpha)), (0, 0, box_width, box_height))
                pygame.draw.rect(box_surf, (100, 100, 200, min(255, alpha)), (0, 0, box_width, box_height), 2)
                self.screen.blit(box_surf, (box_x, box_y))

                # Text (word wrap)
                words = self.dialogue_text.split()
                lines = []
                current_line = ""
                for word in words:
                    test_line = current_line + (" " if current_line else "") + word
                    if self.font_small.size(test_line)[0] < box_width - 20:
                        current_line = test_line
                    else:
                        if current_line:
                            lines.append(current_line)
                        current_line = word
                if current_line:
                    lines.append(current_line)

                text_y = box_y + 10
                for line in lines[:3]:  # Max 3 lines
                    text_surf = self.font_small.render(line, True, (255, 255, 255))
                    text_surf.set_alpha(alpha)
                    self.screen.blit(text_surf, (box_x + 10, text_y))
                    text_y += 18
            else:
                self.dialogue_text = None

        # Chat messages
        y = SCREEN_HEIGHT - 60
        for msg in reversed(self.chat_messages[-5:]):
            self._draw_text_with_bg(msg[:60], 10, y, (255, 255, 255), alpha=150)
            y -= 20

        # Chat input
        if self.typing:
            input_text = f"> {self.chat_input}_"
            pygame.draw.rect(self.screen, (0, 0, 0), (5, SCREEN_HEIGHT - 30, SCREEN_WIDTH - 10, 25))
            text = self.font.render(input_text, True, (255, 255, 0))
            self.screen.blit(text, (10, SCREEN_HEIGHT - 25))

        # Help text
        if not self.typing and not self.inventory_ui.visible:
            if self.debug_mode:
                help_text = "1-7: Type | Click: Apply | RClick: Reset | F1: Exit"
                text = self.font_small.render(help_text, True, (255, 255, 0))
                self.screen.blit(text, (SCREEN_WIDTH - text.get_width() - 10, 10))
            elif self.show_help:
                self._render_help_overlay()
            else:
                # Small unobtrusive hint; full controls behind H
                hint = self.font_small.render("H: Help", True, (210, 210, 210))
                hint.set_alpha(170)
                self.screen.blit(hint, (SCREEN_WIDTH - hint.get_width() - 10, 10))

        # Debug mode indicator and hover info
        if self.debug_mode:
            # Get selected type name
            selected_type_names = {
                TileType.NONBLOCK: "Walkable",
                TileType.BLOCKING: "Blocking",
                TileType.WATER: "Water",
                TileType.CHAIR: "Chair",
                TileType.BUSH: "Bush",
                TileType.POT: "Pot",
                TileType.ROCK: "Rock",
            }
            selected_name = selected_type_names.get(self.debug_selected_type, "?")
            debug_text = f"TILE EDIT - Selected: {selected_name} - Corrections: {len(self.tile_corrections)}"
            self._draw_text_with_bg(debug_text, SCREEN_WIDTH // 2 - 150, 30, (255, 255, 0))

            # Show tile info under mouse cursor
            mouse_x, mouse_y = pygame.mouse.get_pos()
            tile_info = self._get_tile_info_at_screen_pos(mouse_x, mouse_y)
            if tile_info:
                tile_id, tile_type, tx, ty = tile_info
                type_names = {
                    TileType.NONBLOCK: "Walkable",
                    TileType.BLOCKING: "BLOCKING",
                    TileType.WATER: "Water",
                    TileType.NEAR_WATER: "Shallow",
                    TileType.CHAIR: "Chair",
                    TileType.BUSH: "Bush",
                    TileType.POT: "Pot",
                    TileType.ROCK: "Rock",
                }
                type_name = type_names.get(tile_type, f"Type {tile_type}")
                info_text = f"Tile {tile_id} ({tx},{ty}): {type_name}"
                self._draw_text_with_bg(info_text, mouse_x + 15, mouse_y + 15, (255, 255, 255))

        # Minimap (top-right corner)
        if self.minimap_visible and self.minimap_surface:
            minimap_x = SCREEN_WIDTH - self.minimap_size[0] - 10
            minimap_y = 10

            # Draw border
            border_rect = pygame.Rect(
                minimap_x - 2, minimap_y - 2,
                self.minimap_size[0] + 4, self.minimap_size[1] + 4
            )
            pygame.draw.rect(self.screen, (100, 100, 100), border_rect)
            pygame.draw.rect(self.screen, (50, 50, 50), border_rect, 2)

            # Draw minimap
            self.screen.blit(self.minimap_surface, (minimap_x, minimap_y))

            # Draw player position indicator
            if self.client._current_level_name:
                # Calculate player dot position relative to minimap
                grid_size = 64  # Assume 64x64 minimap
                local_x = self.client.x % 64
                local_y = self.client.y % 64
                dot_x = int(minimap_x + (local_x / 64) * self.minimap_size[0])
                dot_y = int(minimap_y + (local_y / 64) * self.minimap_size[1])
                pygame.draw.circle(self.screen, (255, 0, 0), (dot_x, dot_y), 3)
                pygame.draw.circle(self.screen, (255, 255, 255), (dot_x, dot_y), 3, 1)

        # Ghost mode indicator
        if self.ghost_mode:
            ghost_text = "GHOST MODE"
            ghost_surf = self.font.render(ghost_text, True, (200, 200, 255))
            self.screen.blit(ghost_surf, (SCREEN_WIDTH // 2 - ghost_surf.get_width() // 2, 50))

        # Inventory UI
        self.inventory_ui.render(self.client.player, self.weapons)
    def _draw_text_with_bg(self, text: str, x: int, y: int,
                            color: Tuple[int, int, int], alpha: int = 180):
        """Draw text with a semi-transparent background."""
        text_surf = self.font.render(text, True, color)
        bg = pygame.Surface((text_surf.get_width() + 10, text_surf.get_height() + 4))
        bg.fill((0, 0, 0))
        bg.set_alpha(alpha)
        self.screen.blit(bg, (x - 5, y - 2))
        self.screen.blit(text_surf, (x, y))
