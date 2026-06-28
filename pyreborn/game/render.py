"""RenderMixin — All rendering plus per-frame visual/animation updates.

Split from pygame_game.py; methods operate on the GameClient instance."""

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
from .camera import Camera2D
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
    """Frame orchestration, camera sync, the main _render loop, and debug overlays.

    Entity/world/effects/level-object drawing live in the render_* sibling mixins."""

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

        # Update other players / NPCs / baddies. Their gani sounds (sword
        # swings, NPC effects, ...) are played positionally so the world has
        # audible life beyond the local player — Preagonal attenuates these by
        # distance from the listener; we add a stereo pan on top.
        for pid, anim in list(self.other_player_anims.items()):
            if pid not in self.client.players:
                del self.other_player_anims[pid]
                continue
            self._play_entity_sounds(anim.update(dt), self.other_player_visual.get(pid))

        for npc_id, anim in list(self.npc_anims.items()):
            if npc_id not in self.client.npcs:
                del self.npc_anims[npc_id]
                continue
            self._play_entity_sounds(anim.update(dt), self.npc_visual.get(npc_id))

        # Baddy anims were created on first draw but never advanced, leaving
        # them frozen on frame 0. Advance them here too. (Baddies aren't tracked
        # in a visual dict, so their sounds aren't positioned — they sit in the
        # local player's segment anyway.)
        for bid, anim in list(self.baddy_anims.items()):
            if bid not in self.client.baddies:
                del self.baddy_anims[bid]
                continue
            anim.update(dt)

    def _play_entity_sounds(self, sounds, world_pos):
        """Play an entity's gani sounds attenuated/panned by its distance from
        the local player. world_pos is the entity's (x, y) in world tiles, or
        None if its on-screen position isn't known yet (skip — sound on the
        very first frame an entity appears is imperceptible)."""
        if not sounds or world_pos is None:
            return
        dx = world_pos[0] - self.visual_x
        dy = world_pos[1] - self.visual_y
        for sound in sounds:
            self.sound_mgr.play_positional(sound, dx, dy)
    def _update_visual_position(self, dt: float):
        """Track the authoritative position tightly.

        The old exponential lerp left a constant steady-state gap of
        walk_speed/lerp_speed (~0.4 tiles) between where the player actually was
        and where they were drawn, which reads as floaty/laggy. Instead, chase
        the target at follow_speed (well above walk_speed) and lock on once
        within a frame's reach, so during normal movement the camera sits exactly
        on the player (Preagonal snaps its camera to the player every frame) and
        only a large correction eases in.
        """
        target_x = self.client.x
        target_y = self.client.y
        dx = target_x - self.visual_x
        dy = target_y - self.visual_y
        dist = math.hypot(dx, dy)

        # Warp/teleport: snap so we don't slide across the level.
        if dist > 2.0:
            self.visual_x = target_x
            self.visual_y = target_y
            return

        step = self.follow_speed * dt
        if step >= dist:                 # within reach this frame: lock on
            self.visual_x = target_x
            self.visual_y = target_y
        else:
            self.visual_x += dx / dist * step
            self.visual_y += dy / dist * step
    # The camera aims at the player's body centre, not the sprite's top-left,
    # so the character sits at screen centre instead of reading low-and-right of
    # it. Mirrors Preagonal centring on PixelX+24,PixelY+32. The sprite bounding
    # box is 2 tiles wide with feet at (+1, +3) tiles, so the torso is ~1 tile
    # right and ~1.5 tiles down from the top-left.
    CAMERA_BODY_DX = 1.0
    CAMERA_BODY_DY = 1.5

    def _sync_camera(self):
        """Point the camera at the player's GMAP-relative visual position.

        Every render method used to recompute this offset inline; now it's set
        once per frame and all world->screen mapping goes through self.camera.
        """
        gmap_visual_x = self.visual_x - self.client._gmap_offset_x * 64
        gmap_visual_y = self.visual_y - self.client._gmap_offset_y * 64
        # Remember the sprite's top-left (render frame) so _render_entities can
        # draw the local player through the camera like every other entity,
        # rather than pinning it to the camera centre (which is now the body).
        self._player_render_pos = (gmap_visual_x, gmap_visual_y)

        # Bound the camera to the world extent. With the window now larger than a
        # single 64x64 level, this CENTRES that level (Camera2D centres any world
        # smaller than the viewport) with black around it; a GMAP larger than the
        # window scroll-clamps to its perimeter instead of revealing the void.
        if self.client.in_gmap_segment:
            self.camera.set_bounds(0, 0, self.client.gmap_width * 64,
                                   self.client.gmap_height * 64)
        else:
            self.camera.set_bounds(0, 0, 64, 64)

        self.camera.set_center(gmap_visual_x + self.CAMERA_BODY_DX,
                               gmap_visual_y + self.CAMERA_BODY_DY)

    def _render(self):
        """Render the game."""
        # Position the camera before any world-space drawing.
        self._sync_camera()

        # World + entities, optionally through a zoom layer (see _render_scene).
        zoom = self.camera.zoom
        if zoom == 1.0 or self.debug_mode:
            self.screen.fill((0, 0, 0))
            self._render_scene()
        else:
            self._render_scene_zoomed(zoom)

        # Screen-space overlays (never zoomed): sign popups, then the HUD.
        self._check_and_render_signs()
        self._render_ui()

        # Scale the virtual canvas onto the (resizable) window and flip.
        self.viewport.present()

    def _render_scene(self):
        """Draw all world-space layers to self.screen via self.camera."""
        self._render_world()
        if self.debug_mode:
            self._render_debug_overlay()
        self._render_chests()                       # ground, behind entities
        self._render_entities()                     # depth-sorted by Y
        self._render_damage_numbers()
        self._render_bombs()
        self._update_and_render_projectiles(getattr(self, '_last_dt', 0.016))
        self._render_server_explosions()

    def _render_scene_zoomed(self, zoom: float):
        """Render the world layer at 1:1 into a smaller offscreen surface, then
        scale it onto the canvas. One scale here zooms every world-space draw
        uniformly, so the per-sprite blits don't each need a zoom factor."""
        sw = math.ceil(self.screen_w / zoom)
        sh = math.ceil(self.screen_h / zoom)
        scene = pygame.Surface((sw, sh))
        scene.fill((0, 0, 0))

        # Swap in a 1:1 camera centered where the real one is, sized to the scene.
        canvas, real_cam = self.screen, self.camera
        scene_cam = Camera2D(sw, sh, self.camera.tile_size)
        scene_cam.set_center(*real_cam.center)
        self.screen, self.camera = scene, scene_cam
        try:
            self._render_scene()
        finally:
            self.screen, self.camera = canvas, real_cam

        # Nearest-neighbour scale keeps the pixel art crisp.
        self.screen.blit(pygame.transform.scale(scene, (self.screen_w, self.screen_h)),
                         (0, 0))
    def _world_to_screen(self, world_x: float, world_y: float) -> Tuple[float, float]:
        """Convert world (render-frame) tile coordinates to screen pixels.

        Thin wrapper over the camera; kept for the call sites that already use
        this name. The camera is centered once per frame by _sync_camera().
        """
        return self.camera.world_to_screen(world_x, world_y)

    # Chest sprite as a 2x2 tile block into the tileset (dustynewpics1.png),
    # picked from the real chest art (tools/chest_picker.py). Closed = lid down;
    # open = lid back with the gems showing.
    CHEST_TILES_CLOSED = ((1784, 1785),
                          (1800, 1801))
    CHEST_TILES_OPEN = ((829, 830),
                        (845, 846))
    def _render_debug_overlay(self):
        """Render colored overlay showing tile types."""
        # Only iterate tiles actually touching the viewport.
        start_tile_x, start_tile_y, end_tile_x, end_tile_y = \
            self.camera.visible_tile_range()
        start_tile_x -= 1
        start_tile_y -= 1
        end_tile_x += 2
        end_tile_y += 2

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
                screen_x, screen_y = self.camera.world_to_screen(tx, ty)

                # Skip if off screen
                if screen_x < -TILE_SIZE or screen_x > self.screen_w:
                    continue
                if screen_y < -TILE_SIZE or screen_y > self.screen_h:
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
    def _render_ui(self):
        """Render the play HUD, then the tile-editor overlay when active."""
        self.hud.update()
        self.hud.draw()

        if self.debug_mode:
            self._render_debug_hud()

        # Inventory overlay (drawn on top of everything)
        self.inventory_ui.render(self.client.player, self.weapons)

    def _render_debug_hud(self):
        """Tile-editor readouts and hover info, shown only in debug mode."""
        player = self.client.player

        # Left-column readouts
        ui_y = 64
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

        type_names = {
            TileType.NONBLOCK: "Walkable",
            TileType.BLOCKING: "Blocking",
            TileType.WATER: "Water",
            TileType.NEAR_WATER: "Shallow",
            TileType.CHAIR: "Chair",
            TileType.BUSH: "Bush",
            TileType.POT: "Pot",
            TileType.ROCK: "Rock",
        }
        selected_name = type_names.get(self.debug_selected_type, "?")
        debug_text = (f"TILE EDIT - Selected: {selected_name} - "
                      f"Corrections: {len(self.tile_corrections)}")
        self._draw_text_with_bg(debug_text, SCREEN_WIDTH // 2 - 150, 30, (255, 255, 0))

        if not self.typing and not self.inventory_ui.visible:
            help_text = "1-7: Type | Click: Apply | RClick: Reset | F1: Exit"
            text = self.font_small.render(help_text, True, (255, 255, 0))
            self.screen.blit(text, (SCREEN_WIDTH - text.get_width() - 10, 10))

        # Tile info under the cursor (mapped to virtual-canvas space)
        mouse_x, mouse_y = self.viewport.mouse_pos()
        tile_info = self._get_tile_info_at_screen_pos(mouse_x, mouse_y)
        if tile_info:
            tile_id, tile_type, tx, ty = tile_info
            type_name = type_names.get(tile_type, f"Type {tile_type}")
            info_text = f"Tile {tile_id} ({tx},{ty}): {type_name}"
            self._draw_text_with_bg(info_text, mouse_x + 15, mouse_y + 15,
                                    (255, 255, 255))
    def _draw_text_with_bg(self, text: str, x: int, y: int,
                            color: Tuple[int, int, int], alpha: int = 180):
        """Draw text with a semi-transparent background."""
        text_surf = self.font.render(text, True, color)
        bg = pygame.Surface((text_surf.get_width() + 10, text_surf.get_height() + 4))
        bg.fill((0, 0, 0))
        bg.set_alpha(alpha)
        self.screen.blit(bg, (x - 5, y - 2))
        self.screen.blit(text_surf, (x, y))
