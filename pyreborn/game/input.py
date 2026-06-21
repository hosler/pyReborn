"""InputMixin — Keyboard/mouse event handling and held-key movement.

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
from ..gs1_interpreter import GS1Interpreter
from ..player import Player
from ..tiletypes import TileType, get_tile_type
from .constants import (
    TILE_CORRECTIONS_FILE, TILE_SIZE, SCREEN_WIDTH, SCREEN_HEIGHT,
    TILESET_COLS, TILESET_ROWS, MOVE_STEP, parse_npc_visual_effects,
)


class InputMixin:
    """Mixin providing the above methods for GameClient."""

    def _handle_events(self):
        """Handle pygame events."""
        # Reset just-pressed flags
        self.key_just_pressed.clear()

        for event in pygame.event.get():
            if event.type == QUIT:
                self.running = False

            elif event.type == KEYDOWN:
                self.key_just_pressed[event.key] = True

                if self.typing:
                    self._handle_chat_input(event)
                else:
                    self._handle_key_press(event)

            elif event.type == MOUSEBUTTONDOWN and self.debug_mode:
                self._handle_tile_click(event)
    def _handle_chat_input(self, event):
        """Handle chat input mode."""
        if event.key == K_RETURN:
            if self.chat_input:
                self.client.say(self.chat_input)
                # Set local player's chat bubble
                self.local_chat_text = self.chat_input
                self.local_chat_time = time.time()
                # Also add to chat log
                self.chat_messages.append(f"[You] {self.chat_input}")
                if len(self.chat_messages) > 10:
                    self.chat_messages.pop(0)
            self.chat_input = ""
            self.typing = False
        elif event.key == K_ESCAPE:
            self.chat_input = ""
            self.typing = False
        elif event.key == pygame.K_BACKSPACE:
            self.chat_input = self.chat_input[:-1]
        elif event.unicode and len(self.chat_input) < 100:
            self.chat_input += event.unicode
    def _handle_key_press(self, event):
        """Handle single key press events."""
        if event.key == K_ESCAPE:
            self.running = False

        elif event.key == K_RETURN:
            self.typing = True

        elif event.key == K_q:
            # Toggle inventory
            self.inventory_ui.toggle()

        elif event.key == K_F1:
            # Toggle debug/tile editing mode
            self.debug_mode = not self.debug_mode
            if self.debug_mode:
                print("Debug mode ON - Use 1-7 to select type, click to apply:")
                print("  1=Walkable, 2=Blocking, 3=Water, 4=Chair, 5=Bush, 6=Pot, 7=Rock")
            else:
                self._save_tile_corrections()
                print("Debug mode OFF - Corrections saved")

        elif self.debug_mode and event.key in (K_1, K_2, K_3, K_4, K_5, K_6, K_7):
            # Number keys select tile type in debug mode
            type_map = {
                K_1: (TileType.NONBLOCK, "Walkable"),
                K_2: (TileType.BLOCKING, "Blocking"),
                K_3: (TileType.WATER, "Water"),
                K_4: (TileType.CHAIR, "Chair"),
                K_5: (TileType.BUSH, "Bush"),
                K_6: (TileType.POT, "Pot"),
                K_7: (TileType.ROCK, "Rock"),
            }
            self.debug_selected_type, type_name = type_map[event.key]
            print(f"Selected type: {type_name}")

        elif event.key == K_F2:
            # Emergency warp to (30, 30) on current level
            self.client.warp_to_level(self.client._current_level_name, 30, 30)
            self.visual_x = self.client.x
            self.visual_y = self.client.y
            print(f"Warped to (30, 30) on {self.client._current_level_name}")

        elif event.key == K_h:
            # Toggle the controls/help overlay
            self.show_help = not self.show_help

        elif event.key == K_m:
            # Toggle minimap visibility
            self.minimap_visible = not self.minimap_visible
    def _handle_input(self, current_time: float):
        """Handle held key input."""
        if self.typing or self.inventory_ui.visible:
            return

        keys = pygame.key.get_pressed()

        # Check for combined key actions first
        a_held = keys[K_a]
        s_held = keys[K_s]

        # S + A = Cycle weapons
        if s_held and a_held:
            if self.key_just_pressed.get(K_a, False) or self.key_just_pressed.get(K_s, False):
                if current_time - self.last_action_time > self.action_delay:
                    self._cycle_weapon()
                    self.last_action_time = current_time
            return

        # Sword swing (S or Space, but not with A)
        if (s_held or keys[K_SPACE]) and not a_held:
            if self.key_just_pressed.get(K_s, False) or self.key_just_pressed.get(K_SPACE, False):
                if current_time - self.last_action_time > self.action_delay:
                    self._swing_sword()
                    self.last_action_time = current_time
            return

        # Use weapon (D)
        if keys[K_d]:
            if self.key_just_pressed.get(K_d, False):
                if current_time - self.last_action_time > self.action_delay:
                    self._use_weapon()
                    self.last_action_time = current_time
            return

        # Get arrow key directions
        dx, dy = 0, 0
        if keys[K_UP]:
            dy = -1
        elif keys[K_DOWN]:
            dy = 1
        if keys[K_LEFT]:
            dx = -1
        elif keys[K_RIGHT]:
            dx = 1

        # A + Arrow = Pickup
        if a_held and (dx != 0 or dy != 0):
            if current_time - self.last_action_time > self.action_delay:
                self._try_pickup(dx, dy)
                self.last_action_time = current_time
            return

        # A alone = Grab/interact
        if a_held and dx == 0 and dy == 0:
            if self.key_just_pressed.get(K_a, False):
                if current_time - self.last_action_time > self.action_delay:
                    self._try_grab()
                    self.last_action_time = current_time
            return

        # Movement (arrow keys only, no A held)
        if not a_held and (dx != 0 or dy != 0):
            # Stand up automatically if sitting and trying to move
            if self.client.player.is_sitting:
                self.client.player.stand_up()
                self.player_anim.set_animation("idle", self.client.player.direction, force=True)
                self.current_anim_name = "idle"
            # Frame-rate independent movement: accumulate distance at walk_speed
            # and apply it in MOVE_STEP-sized steps so speed is identical
            # regardless of frame rate.
            self._move_accum += self.walk_speed * self._frame_dt
            steps = 0
            while self._move_accum >= MOVE_STEP and steps < 8:
                self._move(dx, dy)
                self._move_accum -= MOVE_STEP
                steps += 1
            self.is_moving = True
        else:
            self.is_moving = False
            self._move_accum = 0.0
            # Settle into the chair if we've come to rest on one.
            player = self.client.player
            if not player.is_sitting and not player.is_carrying():
                fx, fy = self._player_feet()
                if self._is_tile_chair(self._get_tile_at(fx, fy)):
                    if player.sit_down(player.direction):
                        self.player_anim.set_animation("sit", player.direction, force=True)
                        self.current_anim_name = "sit"
