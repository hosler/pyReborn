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
    K_ESCAPE, K_RETURN, K_q, K_a, K_s, K_d, K_SPACE, K_m, K_h, K_n,
    K_UP, K_DOWN, K_LEFT, K_RIGHT, K_BACKSPACE,
    K_F1, K_F2, K_F7, K_F8, K_1, K_2, K_3, K_4, K_5, K_6, K_7
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

                # Modal overlays consume input while open, in priority order:
                # composing a PM > player list > server list > chat > gameplay.
                if self.pm_target_id is not None:
                    self._handle_pm_input(event)
                elif self.show_player_list:
                    self._handle_player_list_key(event)
                elif self.show_server_list:
                    self._handle_server_list_key(event)
                elif self.typing:
                    self._handle_chat_input(event)
                else:
                    self._handle_key_press(event)

            elif event.type == pygame.VIDEORESIZE:
                # Resizable window: the viewport rescales the fixed virtual canvas.
                self.viewport.handle_resize(event.w, event.h)

            elif event.type == MOUSEBUTTONDOWN and self.debug_mode:
                self._handle_tile_click(event)

            elif event.type == pygame.MOUSEWHEEL and not self.debug_mode:
                # Zoom the world layer; the camera clamps to its min/max.
                self.camera.zoom_by(1.1 ** event.y)
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

    # -- F7 player list + private messaging -------------------------------
    def _other_players(self) -> List[Tuple[int, str]]:
        """Sorted [(player_id, label)] for the F7 list. Prefer the server-wide
        roster (PLO_ADDPLAYER); fall back to in-level players if the server
        doesn't send one. Excludes ourselves (matched by account)."""
        roster = self.client.player_list or self.client.players
        me = (getattr(self.client.player, 'account', '') or '').lower()
        out = []
        for pid, p in roster.items():
            if me and (p.get('account') or '').lower() == me:
                continue
            out.append((pid, self._player_label(pid)))
        out.sort(key=lambda t: t[1].lower())
        return out

    def _player_label(self, pid: int) -> str:
        p = self.client.player_list.get(pid) or self.client.players.get(pid, {})
        return str(p.get('nickname') or p.get('account') or f"player {pid}")

    def _handle_player_list_key(self, event):
        if event.key in (K_F7, K_ESCAPE):
            self.show_player_list = False
            return
        players = self._other_players()
        if event.key == K_UP:
            self.player_list_sel = max(0, self.player_list_sel - 1)
        elif event.key == K_DOWN:
            self.player_list_sel = min(max(0, len(players) - 1),
                                       self.player_list_sel + 1)
        elif event.key == K_RETURN and players:
            sel = min(self.player_list_sel, len(players) - 1)
            self.pm_target_id = players[sel][0]   # -> opens the PM input
            self.pm_input = ""

    def _handle_pm_input(self, event):
        if event.key == K_RETURN:
            msg = self.pm_input.strip()
            if msg:
                self.client.send_pm(self.pm_target_id, msg)
                name = self._player_label(self.pm_target_id)
                self.chat_messages.append(f"[PM to {name}] {msg}")
                if len(self.chat_messages) > 10:
                    self.chat_messages.pop(0)
            self.pm_target_id = None
            self.pm_input = ""
        elif event.key == K_ESCAPE:
            self.pm_target_id = None
            self.pm_input = ""
        elif event.key == K_BACKSPACE:
            self.pm_input = self.pm_input[:-1]
        elif event.unicode and len(self.pm_input) < 100:
            self.pm_input += event.unicode

    # -- F8 server list ---------------------------------------------------
    def _handle_server_list_key(self, event):
        if event.key in (K_F8, K_ESCAPE):
            self.show_server_list = False
            return
        if not self.servers:
            return
        if event.key == K_UP:
            self.server_list_sel = max(0, self.server_list_sel - 1)
        elif event.key == K_DOWN:
            self.server_list_sel = min(len(self.servers) - 1,
                                       self.server_list_sel + 1)
        elif event.key == K_RETURN:
            # Picked a server: stash it and end the loop; run() returns it and
            # the launcher reconnects.
            self.switch_server = self.servers[self.server_list_sel]
            self.running = False
    def _handle_key_press(self, event):
        """Handle single key press events."""
        if event.key == K_ESCAPE:
            self.running = False

        elif event.key == K_RETURN:
            self.typing = True

        elif event.key == K_q:
            # Toggle inventory
            self.inventory_ui.toggle()

        elif event.key == pygame.K_0:
            # Reset zoom to 1:1.
            self.camera.zoom = 1.0

        elif event.key == K_F1:
            # Toggle debug/tile editing mode
            self.debug_mode = not self.debug_mode
            if self.debug_mode:
                # The tile editor picks by screen pixel, so it needs 1:1.
                self.camera.zoom = 1.0
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

        elif event.key == K_F7:
            # Toggle the player list (PM other players from it).
            self.show_player_list = not self.show_player_list
            self.show_server_list = False
            self.player_list_sel = 0

        elif event.key == K_F8:
            # Toggle the server list (connect to a different server).
            self.show_server_list = not self.show_server_list
            self.show_player_list = False
            self.server_list_sel = 0

        elif event.key == K_h:
            # Toggle the controls/help overlay
            self.show_help = not self.show_help

        elif event.key == K_m:
            # Toggle minimap visibility
            self.minimap_visible = not self.minimap_visible

        elif event.key == K_n:
            # Toggle noclip — walk through walls to escape a bad server spawn.
            self.noclip = not self.noclip
            print(f"Noclip {'ON' if self.noclip else 'OFF'}")
    def _handle_input(self, current_time: float):
        """Handle held key input."""
        if (self.typing or self.inventory_ui.visible or self.show_player_list
                or self.show_server_list or self.pm_target_id is not None):
            return

        # A GS1 `freezeplayer N` (e.g. talking to a lobby NPC) locks input until
        # the timer expires.
        if current_time < getattr(self, '_frozen_until', 0.0):
            self.is_moving = False
            return

        # Dead players can't move or act until the server respawns them (it
        # restores hearts after a short delay); the death gani plays meanwhile.
        if self.client.player.hearts <= 0:
            self.is_moving = False
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
            # Stand up if sitting and trying to move — but only on a FRESH
            # direction press. Otherwise the held key that sat you down on a
            # chair would immediately pop you back out of it next frame.
            if self.client.player.is_sitting:
                arrow_just = any(self.key_just_pressed.get(k, False)
                                 for k in (K_UP, K_DOWN, K_LEFT, K_RIGHT))
                if not arrow_just:
                    self.is_moving = False
                    return
                self.client.player.stand_up()
                self.player_anim.set_animation("idle", self.client.player.direction, force=True)
                self.current_anim_name = "idle"
                self.client.set_animation("idle")
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
            # Sitting is handled on the walk-into path (pressing toward a chair),
            # so there's nothing to settle here on stop — just go idle. (Settling
            # on stop would re-seat the player every time they tapped to stand.)
            self.is_moving = False
            self._move_accum = 0.0
