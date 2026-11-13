"""InputMixin — Keyboard/mouse event handling and held-key movement.

Split from pygame_game.py; methods operate on the GameClient instance."""

from typing import Dict, List, Optional, Tuple

import pygame
from reborn_protocol import PLPROP, PLSTATUS
from pygame.locals import (
    QUIT, KEYDOWN,
    K_ESCAPE, K_RETURN, K_n,
    K_UP, K_DOWN, K_BACKSPACE,
)

from ..hiding import HIDDEN_SPEED, is_hidden
from . import keymap
from .keymap import held, pressed_now
from .overlays import Overlay, build_overlays, find as find_overlay
from .constants import (
    MOVE_STEP, pygame_key_to_vk, SHIELD_SPEED_MULTIPLIER,
    DEAD_STATUS_DELAY, REVIVAL_INPUT_DELAY,
)
from .clocked import ClockedMixin
from ..clock import sim_passed


class InputMixin(ClockedMixin):
    """Mixin providing the above methods for GameClient."""

    # A pending PLO_SERVERWARP offer awaiting the player's answer (see
    # offer_server_warp). Class-level default so a GameClient built without
    # going through __init__ paths still reads None.
    server_warp_prompt = None

    # -- short HUD notice --------------------------------------------------
    #: (text, monotonic expiry) of the one-line notice at the top of the
    #: screen, or None. Class-level default for the same reason as the prompt.
    hud_notice = None
    HUD_NOTICE_SECONDS = 6.0

    def show_hud_notice(self, text: str) -> None:
        self.hud_notice = (str(text), self.clock.frame_now() + self.HUD_NOTICE_SECONDS)

    # -- PLO_SERVERWARP consent ------------------------------------------
    #: The word the player types, then Enter, to follow a server's request.
    #: The prompt has its own input field that starts empty, and its keys are
    #: ignored for SERVER_WARP_ARM_SECONDS after it opens, so neither a held
    #: key nor a chat line being finished ("yes" + Enter) can confirm it.
    SERVER_WARP_CONFIRM_WORD = "warp"
    SERVER_WARP_ARM_SECONDS = 1.5
    SERVER_WARP_INPUT_MAX = 16

    def offer_server_warp(self, info) -> bool:
        """Ask the player whether to follow a server's move-to-another-server
        request. The target is chosen by the game server, so it is never
        followed without an explicit confirm: a hostile server could
        otherwise collect the account name and password this client logs in
        with. Unusable targets are dropped without a prompt, and while one
        prompt is open further offers are ignored so the answer cannot be
        swapped underneath the player. After a decline, or once the
        per-session offer cap is used up, no prompt opens (see
        ActionsMixin.server_warp_allowed). Opening the prompt closes chat
        input and discards queued key events, so text the player was typing
        elsewhere never lands in the prompt's field. Returns True when a
        prompt is now open."""
        from ..packet_codec.gameplay import validate_server_warp_target
        target = validate_server_warp_target(info)
        if target is None or self.server_warp_prompt is not None:
            return False
        if not self.client.note_server_warp_offer():
            self.client.note_server_warp_blocked(target['name'])
            return False
        host = target['host'].lower()
        target['in_list'] = any(
            str(getattr(entry, 'ip', '')).lower() == host
            and getattr(entry, 'port', None) == target['port']
            for entry in getattr(self, 'servers', ()))
        target['opened_at'] = self.clock.frame_now()
        target['typed'] = ''    # the prompt's own input field, starts empty
        self.server_warp_prompt = target
        self._ensure_settings_ui()
        self._close_overlays("player_list", "server_list", "pm", "chat",
                             "settings")
        pygame.event.clear((KEYDOWN, pygame.KEYUP, pygame.TEXTINPUT))
        return True

    def _decline_server_warp(self):
        self.server_warp_prompt = None
        self.client.note_server_warp_declined()

    def _handle_server_warp_key(self, event):
        # Default is No. Esc / N decline at once; Enter follows the request
        # only when the prompt is armed and its field holds the confirm word
        # exactly -- any other Enter declines (and starts the decline
        # cooldown). Other keys type into the prompt's own field.
        prompt = self.server_warp_prompt
        if event.key in (K_n, K_ESCAPE):
            self._decline_server_warp()
            return
        word = self.SERVER_WARP_CONFIRM_WORD
        armed = (self.clock.frame_now() - prompt['opened_at']
                 >= self.SERVER_WARP_ARM_SECONDS)
        if event.key == K_RETURN:
            if armed and prompt['typed'] == word:
                from ..listserver import ServerEntry
                target, self.server_warp_prompt = prompt, None
                self.switch_server = ServerEntry(
                    name=target['name'], type_prefix='', language='',
                    description='', url='', version='', player_count=0,
                    ip=target['host'], port=target['port'])
                # A script moved us: the next server keeps the frame tick.
                self.switch_frame_tick = self.clock.frame_tick_ms
                self.running = False
            else:
                self._decline_server_warp()
            return
        if not armed:
            return
        if event.key == K_BACKSPACE:
            prompt['typed'] = prompt['typed'][:-1]
            return
        char = getattr(event, 'unicode', '') or ''
        if (len(char) == 1 and char.isprintable()
                and len(prompt['typed']) < self.SERVER_WARP_INPUT_MAX):
            prompt['typed'] += char.lower()

    def _update_death_state(self, current_time):
        player = self.client.player
        if player.hearts > 0:
            self._death_started = None
            if getattr(player, 'status', 0) & PLSTATUS.DEAD:
                player.status &= ~PLSTATUS.DEAD
                self.client.send_appearance_prop(PLPROP.STATUS, player.status)
            return
        if getattr(self, '_death_started', None) is None:
            self._death_started = current_time
            if player.is_carrying():
                self._throw_object()
            # An authoritative HP=0 may arrive without PLO_HURTPLAYER.
            if getattr(self, 'current_anim_name', None) != 'dead':
                self.player_anim.set_animation('dead', player.direction)
                self.current_anim_name = 'dead'
                self.sound_mgr.play('dead.wav')
        # 28 ticks (TPlayer.cpp:2706).
        if (sim_passed(current_time, self._death_started, DEAD_STATUS_DELAY)
                and not player.status & PLSTATUS.DEAD):
            player.status |= PLSTATUS.DEAD
            self.client.send_appearance_prop(PLPROP.STATUS, player.status)

    def _revive_on_input(self, current_time, keys):
        self._update_death_state(current_time)
        player = self.client.player
        if player.hearts > 0:
            return False
        if not sim_passed(current_time, self._death_started, REVIVAL_INPUT_DELAY):
            return False   # 30 ticks (TPlayer.cpp:7319)
        # FourPlay TPlayer.cpp:2164
        if not held(keys, *keymap.REVIVE_ACTIONS):
            return False
        player.status &= ~PLSTATUS.DEAD
        # TPlayer.cpp:5581: predict the server's alignment-based restart HP.
        player.hearts = (3.0 if player.ap <= 19 else min(player.max_hearts, 5.0)
                         if player.ap <= 39 else player.max_hearts)
        self.client.send_appearance_prop(PLPROP.STATUS, player.status)
        self.client.send_appearance_prop(PLPROP.CURPOWER, int(player.hearts * 2))
        self._death_started = None
        self.player_anim.set_animation("idle", player.direction)
        self.current_anim_name = "idle"
        return True

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

    def _ensure_dev_ui(self):
        """Create the F12 dev playground panel (script editing + console).

        Like the RC panel, building it opens no connection: the NC login
        happens on the first F12 press.
        """
        dev = getattr(self, 'dev_ui', None)
        if dev is None:
            from .dev_ui import DevOverlay
            dev = self.dev_ui = DevOverlay(self)
        return dev

    def _ensure_editor(self):
        """Create the F11 level editor and its palette/overlay.

        Lazy like the other overlays, and inert until edit mode is toggled on:
        constructing it opens no connection and draws nothing.
        """
        editor = getattr(self, 'level_editor', None)
        if editor is None:
            from .editor import EditorOverlay, LevelEditor, TilePalette
            editor = self.level_editor = LevelEditor(self)
            self.tile_palette = TilePalette(self)
            self.editor_overlay = EditorOverlay(self, editor)
        return editor

    def _ensure_rc_ui(self):
        """Create the F10 RC tools overlay.

        Constructed lazily like the settings overlay, and cheap: it does NOT
        open the RC connection. That only happens on the first F10 press, so
        players without RC rights never make a second login.
        """
        rc = getattr(self, 'rc_ui', None)
        if rc is None:
            from .rc_ui import RCOverlay
            rc = self.rc_ui = RCOverlay(self)
        return rc

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

    # -- the overlay stack (game/overlays.py) -------------------------------
    @property
    def overlays(self) -> List[Overlay]:
        """Every overlay, topmost first: input priority order, the reverse
        of draw order. Built on first use; the entries read the UIs' state
        at call time, so lazily created UIs need no re-registration."""
        stack = self.__dict__.get('_overlay_stack')
        if stack is None:
            stack = self.__dict__['_overlay_stack'] = build_overlays(self)
        return stack

    def overlay(self, name: str) -> Optional[Overlay]:
        return find_overlay(self.overlays, name)

    def _close_overlays(self, *names: str) -> None:
        """Close the named overlays (an F-key closing the panels it replaces,
        the server-warp prompt clearing the screen)."""
        for overlay in self.overlays:
            if overlay.name in names:
                overlay.close()

    def _overlays_capture_keys(self) -> bool:
        """True while any overlay keeps held keys from driving gameplay."""
        return any(overlay.captures_keys for overlay in self.overlays)

    def _gs2_gui_captures_keys(self) -> bool:
        """True while a GS2 GUI text edit holds keyboard focus — held-key
        gameplay movement must not run alongside typing into a dialog."""
        return self.overlay("gs2_gui").captures_keys

    def _admin_overlay_captures_keys(self) -> bool:
        """True while the F10 RC panel or the F12 dev playground is open.

        Those two are modal in `_handle_events`, but movement does not run off
        events - `_handle_input` polls `key.get_pressed()` every frame. Without
        the gate the panel ate the KEYDOWN and the player still walked off
        under it, because the arrow keys that scroll a row are physically held
        down.

        F11 edit mode is deliberately NOT here: it is non-modal by design, so a
        builder walks around with the arrows while painting with the mouse.
        """
        return any(self.overlay(name).captures_keys
                   for name in ("rc_tools", "dev_tools"))

    def _route_to_overlays(self, event) -> bool:
        """Offer `event` to the overlays, topmost first; True = one consumed
        it (it never reaches gameplay)."""
        return any(overlay.handle_event(event) for overlay in self.overlays)

    # -- edges latched for the next tick ------------------------------------
    #
    # A key or click edge that reaches gameplay (no overlay consumed it and
    # none captures keys) is latched until the next simulation tick, so a tap
    # between two ticks still acts once. The latches remember the play state
    # they were made in (`_input_context`): a tick after a warp or a death
    # does not act on them, and an overlay opening or closing, or the window
    # losing focus, drops every latch.

    def _input_context(self):
        client = self.client
        return (getattr(client, 'plain_level_change_epoch', 0),
                client.player.hearts > 0)

    def _latch(self, key=None) -> None:
        """Latch a key edge (or, with no key, a left click) for the tick."""
        if self._overlays_capture_keys():
            return
        context = self._input_context()
        if getattr(self, '_latch_context', None) != context:
            self._drop_latched_input()
            self._latch_context = context
        if key is None:
            self._mouse_left_latched = True
        else:
            self.key_just_pressed[key] = True

    def _drop_latched_input(self) -> None:
        getattr(self, 'key_just_pressed', {}).clear()
        self._mouse_left_latched = False
        self._latch_context = None

    def _handle_events(self):
        """Handle pygame events."""
        # Make sure the lazily built overlays exist before the overlay
        # entries read their state (see _ensure_settings_ui).
        self._ensure_settings_ui()
        self._ensure_rc_ui()
        self._ensure_dev_ui()
        self._ensure_editor()

        # key_just_pressed is NOT cleared here: an edge stays latched until
        # the next simulation tick consumes it (`_end_input_tick`), so a key
        # pressed and released between two ticks still acts, exactly once.

        events = pygame.event.get()
        # Honour a close request up front: a handler raising mid-batch must
        # not drop a QUIT later in this already-drained batch.
        if any(e.type == QUIT for e in events):
            self.running = False

        captured = self._overlays_capture_keys()
        for event in events:
            self._handle_event(event)
            if self._overlays_capture_keys() != captured:
                # An overlay opened or closed: nothing typed around it acts.
                captured = not captured
                self._drop_latched_input()

    def _handle_event(self, event) -> None:
        """One pygame event: overlays first, then gameplay."""
        if event.type == QUIT:
            self.running = False

        elif event.type == pygame.WINDOWFOCUSLOST:
            self._drop_latched_input()

        elif (getattr(self.client, 'local_level_transition', '')
              or getattr(self, '_level_transition_input_frozen', False)):
            pass

        # The overlays, topmost first (game/overlays.py).
        elif self._route_to_overlays(event):
            pass

        elif event.type == KEYDOWN:
            if getattr(self.client, 'input_frozen', False):
                # Legacy lock: no packet sets it now (176/177 are server-mode
                # markers). A host that sets it ignores normal input until
                # reconnect. The overlays above stay usable so the local
                # player isn't completely locked out.
                pass
            else:
                self._latch(event.key)
                self._handle_key_press(event)
                # GS1 `keypressed` event (weapon scripts, e.g. the sword
                # emulation in npcserver.md). Only for gameplay input, same
                # as the overlay guard above — queued and fired from
                # _handle_input (after keys_dir is refreshed) so a script's
                # keydown() check sees the key that was just pressed.
                self._gs1_keypress_queue.append(
                    (event.key, event.unicode or ""))

        elif (event.type == pygame.MOUSEBUTTONDOWN
              and getattr(event, 'button', 0) == 1):
            # Latched like a key edge, for the next tick's mouse state.
            self._latch()

        elif event.type == pygame.VIDEORESIZE:
            # Resizable window: the viewport rescales the fixed virtual canvas.
            self.viewport.handle_resize(event.w, event.h)

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
                    self.local_chat_time = self.clock.sim_now()
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
        if event.key in keymap.keys_for("player_list", "back"):
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
        if event.key in keymap.keys_for("server_list", "back"):
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
            self.switch_frame_tick = None
            self.running = False
    def _handle_key_press(self, event):
        """Handle single key press events (the keymap's PRESS_ACTIONS)."""
        action = keymap.press_action(event.key)
        if action == "pause":
            from ..pausing import toggle_pause
            toggle_pause(self)
            return
        if action == "back":
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

        elif action == "chat":
            self.typing = True

        elif action == "inventory":
            # Toggle inventory
            self.inventory_ui.toggle()

        elif action == "zoom_reset":
            # Reset zoom to 1:1.
            self.camera.zoom = 1.0

        elif action == "debug":
            # Toggle the debug overlay (tile types, collision boxes, hover
            # readouts). It used to double as a tile-type EDITOR that wrote
            # per-install overrides; liftable objects come from the reference
            # pattern table now (pyreborn/liftobjects.py), so there is nothing
            # left to hand-tag.
            self.debug_mode = not self.debug_mode

        elif action == "unstick":
            # Emergency warp to (30, 30) on current level
            self.client.warp_to_level(self.client.current_level_name, 30, 30)
            self.visual_x = self.client.x
            self.visual_y = self.client.y
            print(f"Warped to (30, 30) on {self.client.current_level_name}")

        elif action == "player_list":
            # Toggle the player list (PM other players from it).
            self.show_player_list = not self.show_player_list
            self._close_overlays("server_list", "settings")
            self.player_list_sel = 0

        elif action == "server_list":
            # Toggle the server list (connect to a different server).
            self.show_server_list = not self.show_server_list
            self._close_overlays("player_list", "settings")
            self.server_list_sel = 0
            # The player is using the browser themselves: script-initiated
            # server warps may be offered again.
            self.client.reset_server_warp_limits()

        elif action == "settings":
            # Toggle the settings overlay (sound/music/day-night/minimap/zoom).
            self.settings_ui.toggle()
            self._close_overlays("player_list", "server_list")

        elif action == "rc_tools":
            # Toggle the RC tools overlay. The first press also opens the RC
            # connection, and the panel reports the outcome (connecting, no
            # RC access, or a live session) rather than the key going dead.
            self.rc_ui.toggle()
            self._close_overlays("settings", "player_list", "server_list")

        elif action == "level_editor":
            # Toggle level edit mode (paint tiles, place objects). Not modal:
            # the world stays live underneath and the player can still walk.
            self.level_editor.toggle()

        elif action == "dev_tools":
            # Toggle the dev playground (scripts + console). Opens the NC
            # connection on first use, same contract as F10 and RC.
            self.dev_ui.toggle()
            self._close_overlays("settings")

        elif action == "chat_scroll_back":
            # Scroll the chat log backward 5 messages at a time, up to the
            # stored history (CHAT_HISTORY_CAP) -- see hud.py's _draw_chat.
            if self.chat_messages:
                if self.chat_scroll == 0:
                    self._chat_scroll_baseline = self.chat_seq
                max_scroll = max(0, len(self.chat_messages) - 5)
                self.chat_scroll = min(max_scroll, self.chat_scroll + 5)

        elif action == "chat_scroll_forward":
            # Scroll forward; hitting the bottom resumes the live tail.
            self.chat_scroll = max(0, self.chat_scroll - 5)
            if self.chat_scroll == 0:
                self._chat_scroll_baseline = 0

        elif action == "help":
            # Toggle the controls/help overlay
            self.show_help = not self.show_help

        elif action == "map":
            self.big_map_visible = True

        elif action == "noclip":
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

    def _fire_gs1_keypress_queue(self):
        """Deliver queued GS1 `keypressed` events (see _handle_events)."""
        if not self._gs1_keypress_queue:
            return
        gs1 = getattr(self, 'gs1', None)
        queued, self._gs1_keypress_queue = self._gs1_keypress_queue, []
        if gs1 is not None:
            for pygame_key, ch in queued:
                vk = self._vk_cache.get(pygame_key)
                if vk is None:
                    vk = pygame_key_to_vk(pygame_key)
                    self._vk_cache[pygame_key] = vk
                gs1.fire_keypress(vk, ch)

    def _gs1_mouse_world(self):
        """The mouse cursor in world tile coords, for GS1's `mousex`/`mousey`
        (ClientGS1.mouse_world_source)."""
        return self.camera.screen_to_world(
            *self.viewport.window_to_virtual(*pygame.mouse.get_pos()))

    def _feed_gs1_input(self, keys):
        """Mirror pygame keyboard/mouse + screen size into the GS1 engine so
        weapon scripts (arenaSYS reads keydown()/playerx, arenaGUI reads the
        mouse + screen) can drive arena gameplay. The keydown indices are the
        keymap's gs1_index column (control-function table in
        scripting-gs1-functions.md; see game/keymap.py)."""
        gs1 = getattr(self, 'gs1', None)
        if gs1 is None:
            return
        gs1.screen_w = self.screen.get_width()
        gs1.screen_h = self.screen.get_height()
        # Virtual-canvas pixels, not raw window pixels: screen_w/h above are the
        # canvas, so a letterboxed viewport (native=False) would otherwise hand
        # scripts a cursor in a different frame from the screen size they scale
        # their menus by.
        gs1.mouse_x, gs1.mouse_y = self.viewport.window_to_virtual(
            *pygame.mouse.get_pos())
        # `mousex`/`mousey` are the same cursor in world TILE coords; hand the
        # engine a hook rather than values so it unprojects against the camera
        # as of the moment a script reads it (the camera is synced later in the
        # frame, game/render.py:274 _sync_camera).
        gs1.mouse_world_source = self._gs1_mouse_world
        gs1.mouse_left = (bool(pygame.mouse.get_pressed()[0])
                          or getattr(self, '_mouse_left_latched', False))
        gs1.keys_dir = keymap.gs1_keydown_indices(keys)
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

    def _tick_keys(self) -> "_TickKeys":
        """This tick's key state: what is held now, plus every key whose
        press was latched since the previous tick (released already or not)
        in the play state that still holds."""
        made = getattr(self, '_latch_context', None)
        if made is not None and made != self._input_context():
            self._drop_latched_input()
        return _TickKeys(pygame.key.get_pressed(),
                         getattr(self, 'key_just_pressed', {}))

    def _end_input_tick(self) -> None:
        """A tick consumed the latched edges: clear them."""
        self._drop_latched_input()

    def _handle_input(self, current_time: float):
        """One tick of held-key input: actions on latched edges, walking on
        held keys. Runs once per simulation tick, never per frame."""
        if getattr(self, '_ledge_jump', None) is not None:
            self.is_moving = False
            self._clear_gs1_input()
            return
        hurt = getattr(self.client.player, 'hurt', None)
        if hurt is not None and hurt.input_locked(current_time):
            self.is_moving = False
            self._clear_gs1_input()
            return
        if (getattr(self.client, 'input_frozen', False)
                or getattr(self.client, 'local_level_transition', '')
                or getattr(self, '_level_transition_input_frozen', False)
                or self._overlays_capture_keys()):
            self._clear_gs1_input()
            self._clear_push_hold()
            return

        # A GS1 `freezeplayer N` (e.g. talking to a lobby NPC) locks MOVEMENT
        # and actions until the timer expires — but scripts must still see the
        # keyboard: classic intro/cutscene NPCs (GTA's splashscreen menu does
        # `freezeplayer 99` then polls keydown(5) for "Press S to Select")
        # freeze the player precisely so the script can own the keys.
        keys = self._tick_keys()
        if not sim_passed(current_time, getattr(self, '_frozen_until', 0.0)):
            self.is_moving = False
            self._feed_gs1_input(keys)
            self._fire_gs1_keypress_queue()
            return

        # Revival consumes the first gameplay input after the death animation.
        if self._revive_on_input(current_time, keys):
            self._clear_gs1_input()
            return
        if self.client.player.hearts <= 0:
            self.is_moving = False
            self._clear_gs1_input()
            return

        self._feed_gs1_input(keys)
        if getattr(self.client.player, 'status', 0) & PLSTATUS.PAUSED:
            self.is_moving = False
            return
        self._auto_pickup_items()

        # Fire any GS1 `keypressed` events queued by _handle_events, now that
        # keys_dir above reflects the just-pressed key — so a script's
        # `keypressed && keydown(5)` (see npcserver.md's sword emulation)
        # actually sees it true on the same frame the event fires.
        self._fire_gs1_keypress_queue()

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
            if held(keys, "grab") and pressed_now(self.key_just_pressed, "grab") \
                    and sim_passed(current_time, self.last_action_time, self.action_delay):
                self._try_grab()
                self.last_action_time = current_time
            return

        # Check for combined key actions first. The S modifier
        # ("item_combo") is S alone; Space swings the sword but combines
        # with nothing.
        jp = self.key_just_pressed
        a_held = held(keys, "grab")
        s_held = held(keys, "item_combo")
        d_held = held(keys, "weapon")

        # Grab/pull is an A-held gesture only — anything else (cycling
        # weapons, swinging, shooting) drops it.
        if not a_held:
            self._clear_grab_state()

        # Mode 9 handles presses, never releases: TPlayer.cpp:2218-2253.
        # The decompile falls through to NONE even after cycling (:2251);
        # real-client play keeps selection up between S-held A taps.
        if getattr(self, '_giveaway_item', None) is not None:
            self.is_moving = False
            self._clear_push_hold()
            if pressed_now(jp, "grab"):
                if s_held:
                    self._giveaway_select()
                else:
                    self._giveaway_drop()
                    # A leaves mode 9 even when loseItem fails (:2232-2251).
                    self._giveaway_item = None
                    self.client.player.action_mode = 0
            elif pressed_now(jp, *keymap.MOVE_NAMES, "weapon", "sword"):
                self._giveaway_item = None
                self.client.player.action_mode = 0
            return

        # S + D = Cycle weapons (TPlayer.cpp:2297)
        if s_held and d_held and not a_held:
            self._clear_push_hold()
            if pressed_now(jp, "weapon", "item_combo"):
                if sim_passed(current_time, self.last_action_time, self.action_delay):
                    self._cycle_weapon()
                    self.last_action_time = current_time
            return

        # A press while S is held enters selection (TPlayer.cpp:2272-2281).
        if s_held and a_held:
            self._clear_push_hold()
            if pressed_now(jp, "grab"):
                self._giveaway_select()
                self.last_action_time = current_time
            return

        # Sword swing (S or Space, but not with A). Uses its own short cooldown
        # (not the shared 300ms action_delay) so the sword can be spam-swung —
        # each fresh press restarts the swing, classic style. While carrying,
        # S throws the object instead (you can't swing with a bush overhead).
        # Falls through to movement: the swing itself roots you (see below),
        # but holding S after the swing ends doesn't.
        if held(keys, "sword") and not a_held:
            if pressed_now(jp, "sword"):
                if self.client.player.is_carrying():
                    self._throw_object()
                elif sim_passed(current_time, self.last_sword_time, self.sword_delay):
                    self._swing_sword()
                    self.last_sword_time = current_time

        # Use weapon (D)
        elif d_held:
            self._clear_push_hold()
            # D while carrying hides/un-hides instead of firing a weapon
            # (TPlayer.cpp:2121), and never roots movement.
            if getattr(self.client.player, 'carried_object_type', ''):
                if pressed_now(jp, "weapon"):
                    self._hide_or_unhide()
            else:
                if pressed_now(jp, "weapon"):
                    if sim_passed(current_time, self.last_action_time, self.action_delay):
                        self._use_weapon()
                        self.last_action_time = current_time
                return

        # Get arrow key directions
        dx, dy = 0, 0
        if held(keys, "move_up"):
            dy = -1
        elif held(keys, "move_down"):
            dy = 1
        if held(keys, "move_left"):
            dx = -1
        elif held(keys, "move_right"):
            dx = 1

        # A + Arrow, with an established grab already facing a wall (see
        # _update_grab_pull_state) and the arrow OPPOSITE that facing: this
        # is "pull", not a fresh lift/pickup attempt in a new direction —
        # skip _try_pickup entirely so an active grab isn't reinterpreted as
        # "turn and lift/throw", and keep facing pinned on the grabbed wall.
        if a_held and self.push.grab is not None and self.push.grab_direction is not None \
                and (dx, dy) == self._facing_delta({0: 2, 1: 3, 2: 0, 3: 1}[self.push.grab_direction]):
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
            if self.push.grab is not None:
                self._clear_grab_state()
            fresh = pressed_now(jp, "grab", *keymap.MOVE_NAMES)
            if fresh and sim_passed(current_time, self.last_action_time, self.action_delay):
                self._try_pickup(dx, dy)
                self.last_action_time = current_time
            self._update_grab_pull_state(dx, dy)
            return

        # A alone = Grab/interact. The one-shot dispatch (lift/chest/sign/
        # door/pickup) only fires on a fresh press; the continuous hold-state
        # update runs every frame A is held so a plain wall shows "grab".
        if a_held and dx == 0 and dy == 0:
            if pressed_now(jp, "grab"):
                if sim_passed(current_time, self.last_action_time, self.action_delay):
                    self._try_grab()
                    self.last_action_time = current_time
            self._update_grab_pull_state(0, 0)
            return

        # Movement (arrow keys only, no A held)
        held_axes = [delta for name, delta in keymap.MOVE_ACTIONS
                     if held(keys, name)]
        if not a_held and held_axes:
            # A sword swing (or lift) roots you for its duration, classic
            # style. Once the gani finishes (setback -> idle) held arrows
            # resume walking.
            if (self.current_anim_name in ("sword", "spin", "lift")
                    or getattr(self.client.player, 'action_mode', 0) in (6, 13)):
                self.is_moving = False
                self._clear_push_hold()
                return
            # One tick of walking: walk_speed * TICK_SECONDS tiles (0.5 at
            # 10 tiles/s, TPlayer.cpp:807/7436), applied in MOVE_STEP-sized
            # collision steps; a remainder (shield x1.2) carries over. Per
            # tick, so a script-changed frame tick changes the walking speed
            # in real time, as in the reference.
            speed = self.walk_speed
            # FourPlay TPlayer.cpp:7447
            if is_hidden(self.client.player):
                speed = HIDDEN_SPEED
            elif not self.is_swimming and getattr(self.client.player, 'shield_power', 0) > 2:
                speed *= SHIELD_SPEED_MULTIPLIER
            self._move_accum += speed * self.clock.TICK_SECONDS
            steps = 0
            while self._move_accum >= MOVE_STEP and steps < 8:
                for ax, ay in held_axes:
                    self._move(ax, ay)
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


class _TickKeys:
    """A key-state sequence for one tick: `pressed[key]` is True when the key
    is held now or went down since the previous tick. Indexes like
    pygame.key.get_pressed() (keymap.held, _feed_gs1_input)."""

    __slots__ = ("_pressed", "_latched")

    def __init__(self, pressed, latched) -> None:
        self._pressed = pressed
        self._latched = latched

    def __getitem__(self, key):
        try:
            if self._pressed[key]:
                return True
        except (IndexError, KeyError, TypeError):
            pass
        return bool(self._latched.get(key, False))

    def __len__(self) -> int:
        return len(self._pressed)
