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
    K_UP, K_DOWN, K_LEFT, K_RIGHT, K_BACKSPACE, K_TAB,
    K_F1, K_F2, K_F7, K_F8, K_F9, K_PAGEUP, K_PAGEDOWN,
    K_1, K_2, K_3, K_4, K_5, K_6, K_7
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
    TILESET_COLS, TILESET_ROWS, MOVE_STEP, CHAT_HISTORY_CAP,
    parse_npc_visual_effects, pygame_key_to_vk,
)


class InputMixin:
    """Mixin providing the above methods for GameClient."""

    # pygame_key_to_vk rebuilds a small dict internally on every call; caching
    # its result per pygame keycode avoids redoing that ~512 times a frame in
    # _feed_gs1_input (once per held key, but the whole key range is scanned
    # every frame to find them).
    _vk_cache: Dict[int, int] = {}

    # Chat scrollback (PageUp/PageDown -- see _handle_key_press/_draw_chat).
    # Class-level defaults so `self.chat_scroll` is safe to read before the
    # first keypress, same trick as _vk_cache above. `chat_scroll` counts
    # messages back from the live tail (0 = at bottom); `_chat_scroll_baseline`
    # is the history length when scrolling started, so hud.py can show "N new"
    # while scrolled without needing its own per-frame bookkeeping.
    chat_scroll: int = 0
    _chat_scroll_baseline: int = 0
    # Monotonic count of chat-log appends (advanced by _append_chat): unlike
    # len(chat_messages) it keeps growing at the history cap, so the scroll
    # indicator's "N new" stays honest once the log is full.
    chat_seq: int = 0

    def _ensure_settings_ui(self):
        """Create the F9 settings overlay and apply its saved live settings.

        GameClient calls this during construction; the guard also keeps the
        helper safe for lightweight harnesses and older call sites.
        """
        su = getattr(self, 'settings_ui', None)
        if su is None:
            from .settings_ui import SettingsOverlay
            su = self.settings_ui = SettingsOverlay(self)
            su.apply_saved_prefs()
        return su

    def _gs2_gui_event(self, event) -> bool:
        """Offer an event to the GS2 GUI layer (topmost overlay). True =
        consumed. Mouse positions are remapped to virtual-canvas coordinates
        first, per gs2_gui.handle_event's contract."""
        gs2 = getattr(self, 'gs2', None)
        mgr = getattr(gs2, 'gui', None) if gs2 is not None else None
        if mgr is None:
            return False
        # Chat/PM composition keeps the keyboard: an incidentally-open GS2
        # window must not swallow Esc (or any key) out from under it.
        if event.type == KEYDOWN and (self.typing
                                      or self.pm_target_id is not None):
            return False
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP,
                          pygame.MOUSEMOTION):
            vpos = self.viewport.window_to_virtual(*event.pos)
            event = pygame.event.Event(event.type, {**event.dict, 'pos': vpos})
        return mgr.handle_event(event)

    def _gs2_gui_captures_keys(self) -> bool:
        """True while a GS2 GUI text edit holds keyboard focus — held-key
        gameplay movement must not run alongside typing into a dialog."""
        gs2 = getattr(self, 'gs2', None)
        mgr = getattr(gs2, 'gui', None) if gs2 is not None else None
        return bool(mgr is not None and mgr.keyboard_captured)

    def _handle_events(self):
        """Handle pygame events."""
        # Make sure the settings overlay exists before the dispatch chain
        # below checks its .visible flag (see _ensure_settings_ui).
        self._ensure_settings_ui()

        # Reset just-pressed flags
        self.key_just_pressed.clear()

        for event in pygame.event.get():
            if event.type == QUIT:
                self.running = False

            elif (getattr(self.client, '_local_level_transition', '')
                  or getattr(self, '_level_transition_input_frozen', False)):
                pass

            # GS2 GUI controls are topmost: a consumed event (click inside a
            # control, keystroke into a focused text edit, Esc on a window)
            # never reaches the overlays or gameplay below.
            elif self._gs2_gui_event(event):
                pass

            elif event.type == KEYDOWN:
                self.key_just_pressed[event.key] = True

                # Modal overlays consume input while open, in priority order:
                # composing a PM > player list > server list > settings > map
                # > chat > dialogue > inventory > gameplay.
                if self.pm_target_id is not None:
                    self._handle_pm_input(event)
                elif self.show_player_list:
                    self._handle_player_list_key(event)
                elif self.show_server_list:
                    self._handle_server_list_key(event)
                elif self.settings_ui.visible:
                    self.settings_ui.handle_key(event)
                elif getattr(self, 'big_map_visible', False):
                    if event.key in (K_m, K_ESCAPE):
                        self.big_map_visible = False
                elif self.typing:
                    self._handle_chat_input(event)
                elif self.dialogue_text is not None:
                    if event.key in (K_a, K_s, K_SPACE):
                        self._advance_dialogue()
                        # This keystroke belongs to the dialog. If it just
                        # DISMISSED it (last page), dialogue_text is now
                        # None and _handle_input runs this same frame — a
                        # leftover just-pressed A would re-fire _try_grab
                        # and instantly re-open the sign under the player
                        # (live on bomber v6: the dialog wrapped to page 0
                        # forever instead of closing).
                        self.key_just_pressed.pop(event.key, None)
                    elif event.key in (K_UP, K_DOWN, K_PAGEUP, K_PAGEDOWN):
                        amount = {
                            K_UP: -1, K_DOWN: 1,
                            K_PAGEUP: -self.dialogue_pager.page_size,
                            K_PAGEDOWN: self.dialogue_pager.page_size,
                        }[event.key]
                        self.dialogue_pager.scroll(amount)
                    elif event.key in (K_F1, K_F2, K_F7, K_F8, K_F9):
                        self._handle_key_press(event)
                elif self.inventory_ui.visible:
                    # The inventory owns its opener while visible, plus grid
                    # navigation/equip keys. Nothing reaches gameplay/GS1.
                    self.inventory_ui.handle_key(event.key, self.client.weapons)
                elif getattr(self.client, 'input_frozen', False):
                    # PLO_FULLSTOP/FULLSTOP2: client ignores normal input until
                    # reconnect (no resume packet exists). Modal overlays above
                    # stay usable so the local player isn't completely locked out.
                    pass
                else:
                    self._handle_key_press(event)
                    # GS1 `keypressed` event (weapon scripts, e.g. the sword
                    # emulation in npcserver.md). Only for gameplay input, same
                    # as the overlay guard above — queued and fired from
                    # _handle_input (after keys_dir is refreshed) so a script's
                    # keydown() check sees the key that was just pressed.
                    self._gs1_keypress_queue.append(
                        (event.key, event.unicode or ""))

            elif event.type == pygame.VIDEORESIZE:
                # Resizable window: the viewport rescales the fixed virtual canvas.
                self.viewport.handle_resize(event.w, event.h)

            elif getattr(self, 'big_map_visible', False):
                # The large map is modal; mouse actions must not reach the
                # inventory, editor, camera zoom, or world underneath it.
                pass

            elif event.type == pygame.MOUSEMOTION and self.inventory_ui.visible:
                self.inventory_ui.handle_mouse_motion(event.pos)

            elif event.type == MOUSEBUTTONDOWN and self.inventory_ui.visible:
                if event.button == 1:
                    self.inventory_ui.handle_click(event.pos, self.client.weapons)

            elif event.type == MOUSEBUTTONDOWN and self.debug_mode:
                self._handle_tile_click(event)

            elif event.type == pygame.MOUSEWHEEL and not self.debug_mode:
                # Zoom the world layer; the camera clamps to its min/max.
                self.camera.zoom_by(1.1 ** event.y)
    def _handle_chat_input(self, event):
        """Handle chat input mode."""
        if event.key == K_RETURN:
            if self.chat_input:
                message = self.chat_input
                if message.startswith("toall "):
                    # Classic explicit server-wide chat; keep Client.say() as
                    # the PLI_TOALL library API used by bots and other callers.
                    message = message[len("toall "):]
                    if message:
                        self.client.say(message)
                        self._append_chat(f"[You] {message}")
                else:
                    # Normal typed chat is CURCHAT: it appears over the player
                    # and is the path that level NPC playerchats handlers see.
                    self.client.send_level_chat(message)
                    self.local_chat_text = message
                    self.local_chat_time = time.time()
                    self._append_chat(f"[You] {message}")
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
        label = str(p.get('nickname') or p.get('account') or f"player {pid}")
        # Tier 3c: append the selectable status label (PLO_STATUSLIST), if any.
        status = self._status_label(p.get('status'))
        return f"{label} [{status}]" if status else label

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
                self._append_chat(f"[PM to {name}] {msg}")
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
            # Consistent with the other modal overlays (PM/player-list/server
            # -list/chat all close on Escape instead of quitting): resume the
            # live chat tail first if scrolled back, then close the
            # inventory, then fall through to quit the app.
            if self.chat_scroll > 0:
                self.chat_scroll = 0
                self._chat_scroll_baseline = 0
            elif self.inventory_ui.visible:
                self.inventory_ui.toggle()
            else:
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
            self.settings_ui.close()
            self.player_list_sel = 0

        elif event.key == K_F8:
            # Toggle the server list (connect to a different server).
            self.show_server_list = not self.show_server_list
            self.show_player_list = False
            self.settings_ui.close()
            self.server_list_sel = 0

        elif event.key == K_F9:
            # Toggle the settings overlay (sound/music/day-night/minimap/zoom).
            self.settings_ui.toggle()
            self.show_player_list = False
            self.show_server_list = False

        elif event.key == K_PAGEUP:
            # Scroll the chat log backward 5 messages at a time, up to the
            # stored history (CHAT_HISTORY_CAP) -- see hud.py's _draw_chat.
            if self.chat_messages:
                if self.chat_scroll == 0:
                    self._chat_scroll_baseline = self.chat_seq
                max_scroll = max(0, len(self.chat_messages) - 5)
                self.chat_scroll = min(max_scroll, self.chat_scroll + 5)

        elif event.key == K_PAGEDOWN:
            # Scroll forward; hitting the bottom resumes the live tail.
            self.chat_scroll = max(0, self.chat_scroll - 5)
            if self.chat_scroll == 0:
                self._chat_scroll_baseline = 0

        elif event.key == K_h:
            # Toggle the controls/help overlay
            self.show_help = not self.show_help

        elif event.key == K_m:
            self.big_map_visible = True

        elif event.key == K_n:
            # Toggle noclip — walk through walls to escape a bad server spawn.
            self.noclip = not self.noclip
            print(f"Noclip {'ON' if self.noclip else 'OFF'}")
    def _clear_gs1_input(self):
        """Drop all held keys from the GS1 engine (input is blocked this frame).
        Also drops any queued `keypressed` fires — a key pressed while an
        overlay/chat box consumed it, or while frozen/dead, shouldn't reach
        weapon scripts (matches keys_dir being cleared the same frames)."""
        gs1 = getattr(self, 'gs1', None)
        if gs1 is not None:
            gs1.keys_dir = set()
            gs1.keys_raw = set()
        self._gs1_keypress_queue.clear()

    def _feed_gs1_input(self, keys):
        """Mirror pygame keyboard/mouse + screen size into the GS1 engine so
        weapon scripts (arenaSYS reads keydown()/playerx, arenaGUI reads the
        mouse + screen) can drive arena gameplay. keydown indices follow the
        control-function table in scripting-gs1-functions.md: 0=up 1=left
        2=down 3=right 4=weapon(D) 5=sword(S/Space) 6=grab(A) 7=map(M)
        8=chat(Tab) 9=inventory(Q). Index 10 (pause/P) has no bound key here."""
        gs1 = getattr(self, 'gs1', None)
        if gs1 is None:
            return
        gs1.screen_w = self.screen.get_width()
        gs1.screen_h = self.screen.get_height()
        mx, my = pygame.mouse.get_pos()
        gs1.mouse_x, gs1.mouse_y = float(mx), float(my)
        gs1.mouse_left = bool(pygame.mouse.get_pressed()[0])
        d = set()
        if keys[K_UP]:
            d.add(0)
        if keys[K_LEFT]:
            d.add(1)
        if keys[K_DOWN]:
            d.add(2)
        if keys[K_RIGHT]:
            d.add(3)
        if keys[K_d]:
            d.add(4)
        if keys[K_s] or keys[K_SPACE]:
            d.add(5)
        if keys[K_a]:
            d.add(6)
        if keys[K_m]:
            d.add(7)
        if keys[K_TAB]:
            d.add(8)
        if keys[K_q]:
            d.add(9)
        gs1.keys_dir = d
        # Translate to VK-style codes (see pygame_key_to_vk) so scripts'
        # keydown2(<Reborn VK code>) calls actually match held keys. Cache the
        # per-key result instead of calling pygame_key_to_vk (which rebuilds a
        # dict internally) for every held key, every frame.
        cache = self._vk_cache
        raw = set()
        for i in range(len(keys)):
            if not keys[i]:
                continue
            vk = cache.get(i)
            if vk is None:
                vk = pygame_key_to_vk(i)
                cache[i] = vk
            raw.add(vk)
        gs1.keys_raw = raw

    def _handle_input(self, current_time: float):
        """Handle held key input."""
        if (self.typing or self.dialogue_text is not None
                or self.inventory_ui.visible or self.show_player_list
                or self.show_server_list or self.pm_target_id is not None
                or getattr(self, 'big_map_visible', False)
                or self._ensure_settings_ui().visible
                or getattr(self.client, 'input_frozen', False)
                or getattr(self.client, '_local_level_transition', '')
                or getattr(self, '_level_transition_input_frozen', False)
                or self._gs2_gui_captures_keys()):
            self._clear_gs1_input()
            return

        # A GS1 `freezeplayer N` (e.g. talking to a lobby NPC) locks input until
        # the timer expires.
        if current_time < getattr(self, '_frozen_until', 0.0):
            self.is_moving = False
            self._clear_gs1_input()
            return

        # Dead players can't move or act until the server respawns them (it
        # restores hearts after a short delay); the death gani plays meanwhile.
        if self.client.player.hearts <= 0:
            self.is_moving = False
            self._clear_gs1_input()
            return

        keys = pygame.key.get_pressed()
        self._feed_gs1_input(keys)

        # Fire any GS1 `keypressed` events queued by _handle_events, now that
        # keys_dir above reflects the just-pressed key — so a script's
        # `keypressed && keydown(5)` (see npcserver.md's sword emulation)
        # actually sees it true on the same frame the event fires.
        if self._gs1_keypress_queue:
            gs1 = getattr(self, 'gs1', None)
            queued, self._gs1_keypress_queue = self._gs1_keypress_queue, []
            if gs1 is not None:
                for pygame_key, ch in queued:
                    vk = self._vk_cache.get(pygame_key)
                    if vk is None:
                        vk = pygame_key_to_vk(pygame_key)
                        self._vk_cache[pygame_key] = vk
                    gs1.fire_keypress(vk, ch)

        # Arena mode: a weapon called disabledefmovement and drives movement +
        # bomb placement itself by reading keydown()/playerx. Don't run the
        # built-in WASD movement or D-weapon handling — just feed it the keys.
        if not self.gs1.default_movement:
            # NPC touch is still client-detected: _move() never runs here, so
            # probe pushing-into-an-NPC-shape off the held direction keys
            # (Bomber v6 queue counter — see _scripted_movement_touch).
            self._scripted_movement_touch(keys)
            # A = grab/interact stays a BUILT-IN under scripted movement:
            # disabledefmovement only disables the default arrow-key
            # movement, not the grab action — returning before the A
            # dispatch made sign reading (walk into a level sign + press A,
            # Bomber v6 bomblobby's 3 PLO_LEVELSIGN signs) silently dead in
            # any disabledefmovement level. One-shot on a fresh press only,
            # arrows held or not (walk-into-and-press is the classic sign
            # gesture), same action_delay cooldown as the default path.
            if keys[K_a] and self.key_just_pressed.get(K_a, False) \
                    and current_time - self.last_action_time > self.action_delay:
                self._try_grab()
                self.last_action_time = current_time
            return

        # Check for combined key actions first
        a_held = keys[K_a]
        s_held = keys[K_s]

        # Grab/pull is an A-held gesture only — anything else (cycling
        # weapons, swinging, shooting) drops it.
        if not a_held:
            self._clear_grab_state()

        # S + A = Cycle weapons
        if s_held and a_held:
            self._clear_push_hold()
            if self.key_just_pressed.get(K_a, False) or self.key_just_pressed.get(K_s, False):
                if current_time - self.last_action_time > self.action_delay:
                    self._cycle_weapon()
                    self.last_action_time = current_time
            return

        # Sword swing (S or Space, but not with A). Uses its own short cooldown
        # (not the shared 300ms action_delay) so the sword can be spam-swung —
        # each fresh press restarts the swing, classic style. While carrying,
        # S throws the object instead (you can't swing with a bush overhead).
        # Falls through to movement: the swing itself roots you (see below),
        # but holding S after the swing ends doesn't.
        if (s_held or keys[K_SPACE]) and not a_held:
            if self.key_just_pressed.get(K_s, False) or self.key_just_pressed.get(K_SPACE, False):
                if self.client.player.is_carrying():
                    self._throw_object()
                elif current_time - self.last_sword_time > self.sword_delay:
                    self._swing_sword()
                    self.last_sword_time = current_time

        # Use weapon (D)
        elif keys[K_d]:
            self._clear_push_hold()
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

        # A + Arrow, with an established grab already facing a wall (see
        # _update_grab_pull_state) and the arrow OPPOSITE that facing: this
        # is "pull", not a fresh lift/pickup attempt in a new direction —
        # skip _try_pickup entirely so an active grab isn't reinterpreted as
        # "turn and lift/throw", and keep facing pinned on the grabbed wall.
        if a_held and self.grab_state is not None and self._grab_direction is not None \
                and (dx, dy) == self._facing_delta({0: 2, 1: 3, 2: 0, 3: 1}[self._grab_direction]):
            self._update_grab_pull_state(dx, dy)
            return

        # A + Arrow = Pickup/throw — only on a fresh press of A or the arrow.
        # The old held-repeat re-fired this every 300ms, so lifting a bush and
        # keeping the keys held threw it right back out of your hands.
        if a_held and (dx != 0 or dy != 0):
            # Re-aiming away from an established grab (not the opposite
            # direction, handled above as "pull") is a fresh aim-and-lift
            # attempt in a new direction, not a continuation of the old
            # grab — drop the stale pinned facing before _try_pickup turns
            # to face this arrow.
            if self.grab_state is not None:
                self._clear_grab_state()
            fresh = any(self.key_just_pressed.get(k, False)
                        for k in (K_a, K_UP, K_DOWN, K_LEFT, K_RIGHT))
            if fresh and current_time - self.last_action_time > self.action_delay:
                self._try_pickup(dx, dy)
                self.last_action_time = current_time
            self._update_grab_pull_state(dx, dy)
            return

        # A alone = Grab/interact. The one-shot dispatch (lift/chest/sign/
        # door/pickup) only fires on a fresh press; the continuous hold-state
        # update runs every frame A is held so a plain wall shows "grab".
        if a_held and dx == 0 and dy == 0:
            if self.key_just_pressed.get(K_a, False):
                if current_time - self.last_action_time > self.action_delay:
                    self._try_grab()
                    self.last_action_time = current_time
            self._update_grab_pull_state(0, 0)
            return

        # Movement (arrow keys only, no A held)
        if not a_held and (dx != 0 or dy != 0):
            # A sword swing (or lift) roots you for its duration, classic
            # style. Once the gani finishes (setback -> idle) held arrows
            # resume walking.
            if self.current_anim_name in ("sword", "lift"):
                self.is_moving = False
                self._clear_push_hold()
                return
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
            self._clear_push_hold()
