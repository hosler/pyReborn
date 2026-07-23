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
    PLAYER_STAND_X, PLAYER_STAND_Y,
)


class RenderMixin:
    """Frame orchestration, camera sync, the main _render loop, and debug overlays.

    Entity/world/effects/level-object drawing live in the render_* sibling mixins."""

    def _update_animations(self, dt: float):
        """Update all animation states."""
        # Walk-on sitting: derive seated state from the tile under the feet.
        self._update_sitting_state()

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
                self.client.set_animation(setback)
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

        # If sitting and not already in sit animation. Don't stomp a one-shot
        # action gani (sword swing while seated) — its setback returns here.
        if self.client.player.is_sitting:
            if self.current_anim_name not in ("sit", "sword", "lift"):
                self.player_anim.set_animation("sit", self.client.player.direction)
                self.current_anim_name = "sit"

        # Push/grab/pull hold state (game/actions.py's _update_push_hold /
        # _update_grab_pull_state, driven every frame from game/input.py's
        # held-key handling). Those already keep current_anim_name in sync
        # while the state is active; this is the release path — A/the
        # movement key let go (or carrying/sitting took over) clears the
        # state but doesn't itself touch the gani, so fall back to idle here
        # instead of leaving "push"/"grab"/"pull" stuck on screen.
        if self.grab_state and self.current_anim_name != self.grab_state:
            self.player_anim.set_animation(self.grab_state, self._grab_direction, force=True)
            self.current_anim_name = self.grab_state
        elif not self.grab_state and self.current_anim_name in ("grab", "pull"):
            self.player_anim.set_animation("idle", self.client.player.direction)
            self.current_anim_name = "idle"

        if self.is_pushing and self.current_anim_name != "push":
            self.player_anim.set_animation("push", self.client.player.direction, force=True)
            self.current_anim_name = "push"
        elif not self.is_pushing and self.current_anim_name == "push":
            self.player_anim.set_animation("idle", self.client.player.direction)
            self.current_anim_name = "idle"

        # If not moving, switch to appropriate idle animation. Skip while a
        # weapon script drives movement (disabledefmovement): is_moving is
        # only set by the built-in input path, so this stomped the script's
        # setani("walk") back to idle every frame — the script sets idle
        # itself when the keys are released (ReturnIdle).
        if (getattr(getattr(self, "gs1", None), "default_movement", True)
                and not self.is_moving
                and self.current_anim_name in ("walk", "swim")):
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
        # audible life beyond the local player — the C# client attenuates these by
        # distance from the listener; we add a stereo pan on top.
        for pid, anim in list(self.other_player_anims.items()):
            if pid not in self.client.players:
                del self.other_player_anims[pid]
                self.other_player_visual.pop(pid, None)  # else this leaks per
                continue                                 # player id for the session
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

        # Same bug class as baddies above: horse_anims entries (keyed by the
        # horse's (x, y), like client.horses) were created on first draw but
        # never advanced, so mounts sat frozen on frame 0.
        for hkey, anim in list(self.horse_anims.items()):
            if hkey not in self.client.horses:
                del self.horse_anims[hkey]
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
        on the player (the C# client snaps its camera to the player every frame) and
        only a large correction eases in.
        """
        # A discrete local level warp changes authoritative x/y before its
        # board arrives.  Keep the last stable view until that board is active.
        if getattr(self.client, '_local_level_transition', ''):
            return

        transition_epoch = getattr(
            self.client, '_local_level_transition_epoch', 0)
        seen_epoch = getattr(self, '_seen_level_transition_epoch',
                             transition_epoch)
        if transition_epoch != seen_epoch:
            self.visual_x = self.client.x
            self.visual_y = self.client.y
            self._seen_level_transition_epoch = transition_epoch
            return

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
    # it. The sprite is honestly 3 tiles wide, top-left anchored (see
    # render_entities.py's _render_player) — true horizontal centre is
    # x+1.5 tiles, matching the classic-engine spec collision box's own
    # horizontal centre (collision.py's PLAYER_FEET_DX). DX was previously
    # 1.0, half a tile left of this box's true centre — the same
    # mis-centering bug this pass fixes elsewhere; left uncorrected here the
    # player would render visibly off-centre in the viewport once the
    # sprite's own anchor became honest. DY (torso height, not the box's
    # feet-centre) is a separate framing choice, left as-is.
    CAMERA_BODY_DX = PLAYER_STAND_X
    CAMERA_BODY_DY = PLAYER_STAND_Y

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
        # set_bounds() re-clamps the center on top of the clamp set_center() below
        # already redoes every frame, so only call it again when one of its
        # inputs (level/GMAP switch, zoom, or a window resize) actually changed.
        bounds_key = (self.client.in_gmap_segment, self.client.gmap_width,
                     self.client.gmap_height, self.client._current_level_name,
                     self.camera.zoom, self.screen_w, self.screen_h)
        if bounds_key != self._camera_bounds_key:
            self._camera_bounds_key = bounds_key
            if self.client.in_gmap_segment:
                self.camera.set_bounds(0, 0, self.client.gmap_width * 64,
                                       self.client.gmap_height * 64)
            else:
                self.camera.set_bounds(0, 0, 64, 64)

        self.camera.set_center(gmap_visual_x + self.CAMERA_BODY_DX,
                               gmap_visual_y + self.CAMERA_BODY_DY)
        self.camera.set_render_offset()
        started = getattr(self, '_camera_shake_started', None)
        if started is not None and not getattr(self.client, '_local_level_transition', ''):
            age = time.monotonic() - started
            if age < 0.4:
                strength = 3.0 * (1.0 - age / 0.4)
                self.camera.set_render_offset(
                    math.sin(age * 91.0) * strength,
                    math.cos(age * 73.0) * strength)
            else:
                self._camera_shake_started = None

    # How long a held transition may freeze the frame before failing open
    # (confirmation lost / server hiccup). Normal confirms land within a
    # couple of frames even over a slow link.
    TRANSITION_HOLD_MAX_S = 1.0
    TRANSITION_SLIDE_S = 0.45

    def _draw_transition_slide(self, now: float) -> bool:
        """Present static source/destination scenes while a slide is active."""
        slide = getattr(self, '_level_transition_slide', None)
        if slide is None:
            return False
        age = now - slide['started']
        if age < 0 or age > self.TRANSITION_HOLD_MAX_S:
            self._level_transition_slide = None
            self._level_transition_input_frozen = False
            return False
        progress = min(1.0, age / self.TRANSITION_SLIDE_S)
        # Smoothstep keeps both endpoints still and avoids a mechanical pan.
        progress = progress * progress * (3.0 - 2.0 * progress)
        width, height = self.screen.get_size()
        dx, dy = ((0, height), (width, 0), (0, -height), (-width, 0))[
            slide['direction']]
        old_x, old_y = round(dx * progress), round(dy * progress)
        new_x = old_x - dx
        new_y = old_y - dy
        self.screen.fill((0, 0, 0))
        self.screen.blit(slide['source'], (old_x, old_y))
        self.screen.blit(slide['destination'], (new_x, new_y))
        self._check_and_render_signs()
        self._render_ui()
        self._render_combat_presentation()
        self.viewport.present()
        if age >= self.TRANSITION_SLIDE_S:
            self._level_transition_slide = None
            self._level_transition_input_frozen = False
        return True

    def _capture_transition_destination(self, source, direction: int,
                                        now: float) -> bool:
        """Render one destination scene without exposing camera recomputation."""
        try:
            destination = self.screen.copy()
            canvas = self.screen
            self.screen = destination
            try:
                self._sync_camera()
                zoom = self.camera.zoom
                if zoom == 1.0:
                    destination.fill((0, 0, 0))
                    self._render_scene()
                else:
                    self._render_scene_zoomed(zoom)
                self._render_gui_band()
            finally:
                self.screen = canvas
            self._level_transition_slide = {
                'source': source, 'destination': destination,
                'direction': direction, 'started': now,
            }
            self._level_transition_input_frozen = True
            return True
        except Exception:
            self._level_transition_slide = None
            self._level_transition_input_frozen = False
            return False

    def _render(self):
        """Render the game."""
        now = time.monotonic()
        if self._draw_transition_slide(now):
            return
        # A held local level transition keeps the LAST COMPLETED frame on
        # screen verbatim until the destination is presentable. Freezing the
        # framebuffer - not just visual_x/y - is what actually keeps the view
        # still: every other camera input (bounds, gmap-vs-standalone frame,
        # the active board, clamping) flips mid-transition, so recomputing
        # any of them moves the camera even with the visual position frozen
        # (live-traced: world->local bounds clamp jumped the camera to the
        # 64x64 corner while the hold was engaged, and a cached destination
        # board replaced the world content instantly under the held camera).
        if getattr(self.client, '_local_level_transition', ''):
            presentation = getattr(self, 'combat_presentation', None)
            if presentation is not None:
                presentation.sync(
                    self.client.player.hearts <= 0, True, time.monotonic())
            started = getattr(
                self.client, '_local_level_transition_started', 0.0)
            if time.monotonic() - started <= self.TRANSITION_HOLD_MAX_S:
                frozen = getattr(self, '_transition_frame', None)
                if frozen is None:
                    # First held frame: self.screen still holds the last
                    # completed pre-warp frame. Snapshot it.
                    base = getattr(self, '_death_base_frame', None)
                    self._transition_frame = (base.copy() if base is not None
                                              else self.screen.copy())
                else:
                    self.screen.blit(frozen, (0, 0))
                self.viewport.present()
                return
            self.client._release_local_transition()

        frozen = getattr(self, '_transition_frame', None)
        direction = getattr(
            self.client, '_local_level_transition_direction', None)
        if frozen is not None and direction in range(4):
            source = getattr(self, '_transition_scene_frame', frozen).copy()
            self.client._local_level_transition_direction = None
            self._transition_frame = None
            if self._capture_transition_destination(source, direction, now):
                self._draw_transition_slide(now)
                return
        self.client._local_level_transition_direction = None
        self._transition_frame = None

        # Position the camera before any world-space drawing.
        self._sync_camera()

        # World + entities, optionally through a zoom layer (see _render_scene).
        zoom = self.camera.zoom
        if zoom == 1.0:
            self.screen.fill((0, 0, 0))
            self._render_scene()
        else:
            self._render_scene_zoomed(zoom)
        # Screen-space scripted GUI band, after any zoom scale (see
        # _render_gui_band).
        self._render_gui_band()

        # Preserve the world-only portion of the last completed frame. The
        # ordinary hold still freezes the full framebuffer verbatim; this copy
        # is used only if that hold later becomes a slide, keeping the HUD fixed.
        self._transition_scene_frame = self.screen.copy()

        # Screen-space overlays (never zoomed): sign popups, then the HUD.
        self._check_and_render_signs()
        self._render_ui()
        self._render_combat_presentation()

        # Scale the virtual canvas onto the (resizable) window and flip.
        self.viewport.present()

    def _render_scene(self):
        """Draw all world-space layers to self.screen via self.camera."""
        self._render_world()
        self._render_animated_tiles()                # Tier 4a: water/lava shimmer
        if self.debug_mode:
            self._render_debug_overlay()
        self._render_chests()                       # ground, behind entities
        self._render_items()                         # ground items, behind entities
        self._render_entities()                     # depth-sorted by Y (incl. horses)
        self._render_damage_numbers()
        self._render_bombs()
        self._update_and_render_projectiles(getattr(self, '_last_dt', 0.016))
        self._update_and_render_thrown(getattr(self, '_last_dt', 0.016))
        self._render_break_effects()
        self._render_leaf_particles()
        self._render_water_ripples()
        self._render_chest_reveals()
        self._render_server_explosions()
        self._render_screen_tint()                   # seteffect overlay, under HUD
        self._render_deferred_lights()               # additive glows, above tint

    def _render_gui_band(self):
        """Draw the vis>=4 GUI band (scripted HUDs, captions) in TRUE screen
        pixels, above the tint. This must run on the real canvas AFTER the
        zoom scale — when it lived at the end of _render_scene, a script's
        setZoom(2) rendered it into the 1:1 zoom scratch surface and the
        upscale doubled every GUI layer's position/size (the v6 bomber's
        scripted HUD landed half off-screen). While zoomed, also neutralize
        the camera factor render_entities.py's showimg renderer applies
        (camera.scale/TILE_SIZE — a world-space term) with a plain unit
        camera; GUI layers never use world_to_screen, so only that factor
        (and world-band text sizing, which this pass never draws) sees it."""
        gui_layers = getattr(self, '_render_gui_layers', None)
        if gui_layers is None:
            # partial hosts (unit-test harnesses) mix in RenderMixin without
            # EntityRenderMixin, which owns the actual layer walk
            return
        cam = self.camera
        if getattr(cam, 'zoom', 1.0) == 1.0:
            gui_layers()
            return
        key = (self.screen_w, self.screen_h, cam.tile_size)
        if key != getattr(self, '_gui_cam_key', None):
            self._gui_cam_key = key
            self._gui_cam = Camera2D(self.screen_w, self.screen_h, cam.tile_size)
        self.camera = self._gui_cam
        try:
            gui_layers()
        finally:
            self.camera = cam

    def _render_scene_zoomed(self, zoom: float):
        """Render the world layer at 1:1 into a smaller offscreen surface, then
        scale it onto the canvas. One scale here zooms every world-space draw
        uniformly, so the per-sprite blits don't each need a zoom factor.

        The scratch surface + scene camera are cached and only reallocated
        when their size actually changes (zoom level or window resize) -
        otherwise this ran a fresh Surface allocation + transform.scale
        every single frame while zoomed."""
        sw = math.ceil(self.screen_w / zoom)
        sh = math.ceil(self.screen_h / zoom)
        cache_key = (sw, sh, self.camera.tile_size)
        if cache_key != getattr(self, '_zoom_scene_key', None):
            self._zoom_scene_key = cache_key
            self._zoom_scene_surface = pygame.Surface((sw, sh))
            self._zoom_scene_cam = Camera2D(sw, sh, self.camera.tile_size)
        scene = self._zoom_scene_surface
        scene.fill((0, 0, 0))

        # Swap in the cached 1:1 camera, re-centered where the real one is.
        # Debug rendering must use this path too: segment surfaces are baked at
        # one pixel footprint per base tile and cannot be positioned directly
        # with a zoomed camera without opening gaps between adjacent segments.
        canvas, real_cam = self.screen, self.camera
        scene_cam = self._zoom_scene_cam
        scene_cam.set_center(*real_cam.center)
        ox, oy = real_cam.render_offset
        scene_cam.set_render_offset(ox / zoom, oy / zoom)
        self.screen, self.camera = scene, scene_cam
        try:
            self._render_scene()
        finally:
            self.screen, self.camera = canvas, real_cam

        # Nearest-neighbour scale directly into self.screen (same size as
        # (self.screen_w, self.screen_h) by construction) - skips allocating
        # a fresh scaled Surface every frame just to blit-and-discard it.
        pygame.transform.scale(scene, (self.screen_w, self.screen_h), self.screen)
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
        self.inventory_ui.render(self.client.player, self.client.weapons)

        # GS2 GUI controls (showgui/GuiControl) draw last: topmost of all.
        if getattr(self.gs2, "gui", None) is not None:
            self.gs2.gui.render(self.screen, self.fonts, self.sprite_mgr)

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
        # Anchor to the live window width, not the SCREEN_WIDTH constant -
        # this drew centred/right-aligned for a 640px window regardless of the
        # window's real (WM-imposed) size, so on anything wider the text sat
        # off to the left instead of centred/right-anchored.
        self._draw_text_with_bg(debug_text, self.screen_w // 2 - 150, 30, (255, 255, 0))

        if not self.typing and not self.inventory_ui.visible:
            help_text = "1-7: Type | Click: Apply | RClick: Reset | F1: Exit"
            text = self.font_small.render(help_text, True, (255, 255, 0))
            self.screen.blit(text, (self.screen_w - text.get_width() - 10, 10))

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
