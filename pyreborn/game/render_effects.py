"""EffectsRenderMixin — damage numbers, bombs, projectiles, explosions.

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


class EffectsRenderMixin:
    """Mixin providing the above methods for GameClient."""

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

                # Draw explosion circles
                if radius > 0:
                    explosion_surf = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
                    pygame.draw.circle(explosion_surf, (255, 150, 50, alpha), (radius, radius), radius)
                    pygame.draw.circle(explosion_surf, (255, 100, 0, alpha), (radius, radius), int(radius * 0.7))
                    pygame.draw.circle(explosion_surf, (255, 200, 100, alpha), (radius, radius), int(radius * 0.4))
                    self.screen.blit(explosion_surf, (screen_x - radius, screen_y - radius))

                active.append(exp)

        self.client.active_explosions = active
