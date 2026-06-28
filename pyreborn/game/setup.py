"""SetupMixin — Asset paths, client callbacks, GS1 callbacks, NPC script bootstrap.

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
    PACKAGE_DIR, TILE_CORRECTIONS_FILE, TILE_SIZE, SCREEN_WIDTH, SCREEN_HEIGHT,
    TILESET_COLS, TILESET_ROWS, MOVE_STEP, parse_npc_visual_effects,
)


class SetupMixin:
    """Mixin providing the above methods for GameClient."""

    def _setup_asset_paths(self) -> List[Path]:
        """Setup asset search paths."""
        base_path = PACKAGE_DIR  # pyreborn/ — independent of this module's location
        paths = [
            base_path / "assets",
            base_path.parent / "cache",
            base_path.parent / "cache" / "levels" / f"{self.client.host}_{self.client.port}",
            base_path.parent / "examples" / "games" / "reborn_modern" / "assets" / "levels",
            base_path.parent / "examples" / "games" / "reborn_modern" / "assets",
        ]
        # Add subdirectories for ganis and sounds
        extra_paths = []
        for p in paths:
            extra_paths.append(p / "ganis")
            extra_paths.append(p / "sounds")
            extra_paths.append(p / "bodies")
            extra_paths.append(p / "heads")
            extra_paths.append(p / "swords")
            extra_paths.append(p / "shields")
        return paths + extra_paths
    def _setup_callbacks(self):
        """Setup client callbacks."""
        def on_chat(player_id, message):
            self.chat_messages.append(f"[{player_id}] {message}")
            if len(self.chat_messages) > 10:
                self.chat_messages.pop(0)

        def on_pm(from_id, message):
            # Show received private messages in the chat log, named by sender.
            name = self._player_label(from_id)
            self.chat_messages.append(f"[PM {name}] {message}")
            if len(self.chat_messages) > 10:
                self.chat_messages.pop(0)

        def _roster_name(info):
            return info.get('nickname') or info.get('account') or "?"

        def on_add_player(pid, info):
            # The server dumps the whole roster on login; only announce joins
            # that arrive after that settles (roster_ready_time, set in run()).
            if time.time() >= self.roster_ready_time:
                self.chat_messages.append(f"-> {_roster_name(info)} entered")
                if len(self.chat_messages) > 10:
                    self.chat_messages.pop(0)

        def on_del_player(pid, info):
            self.chat_messages.append(f"<- {_roster_name(info)} left")
            if len(self.chat_messages) > 10:
                self.chat_messages.pop(0)

        def on_hurt(attacker_id, damage, damage_type, source_x, source_y):
            # Spawn floating damage number at player position
            self.damage_numbers.append({
                'x': self.visual_x,
                'y': self.visual_y - 16,
                'damage': damage,
                'time': time.time(),
                'duration': 1.0,
            })
            # Trigger hurt flash
            self.hurt_flash_time = time.time()

            # Check for death (hearts already reduced by client.respond_to_hurt)
            if self.client.player.hearts <= 0:
                # Play death sound
                self.sound_mgr.play("dead.wav")
                # Set death animation
                self.player_anim.set_animation("dead", self.client.player.direction)

        def on_minimap(data: bytes):
            """Handle minimap data from server."""
            self.minimap_data = data
            self._build_minimap_surface()

        def on_ghost_mode(enabled: bool):
            """Handle ghost mode toggle."""
            self.ghost_mode = enabled

        def on_file(filename: str, data: bytes):
            """Cache a downloaded asset. Images go to the sprite cache, ganis to
            the gani parser's cache; a music file we were waiting on starts
            playing once it arrives."""
            ext = filename.lower().rsplit('.', 1)[-1]
            if ext in ('png', 'gif', 'bmp', 'mng'):
                self.sprite_mgr.load_bytes(filename, data)
            elif ext == 'gani':
                # The server streams gani scripts on demand; cache the parsed
                # animation so NPCs/players using it stop falling back to the
                # missing-asset placeholder. Keyed by the bare name (no .gani).
                name = filename[:-5] if filename.lower().endswith('.gani') else filename
                try:
                    self.gani_parser.cache[name] = self.gani_parser.parse_content(
                        data.decode('latin-1'), name)
                except Exception:
                    pass
            elif self.sound_mgr.is_music(filename):
                if filename == getattr(self, '_pending_music', None):
                    self._pending_music = None
                    self.sound_mgr.play_music(filename, data=data)

        # A weapon arrived (gr.addweapon, e.g. -arenaSYS/-arenaGUI on arena
        # entry): load it into the GS1 engine and fire its playerenters so it
        # activates immediately, like a real client adding a weapon.
        def on_weapon_add(name, weapon):
            script = weapon.get('script', '')
            if script and getattr(self, 'gs1', None) is not None:
                self.gs1.load_weapon(name, script)
                try:
                    self.gs1.trigger_event('playerenters', name=f'weapon_{name}')
                except Exception:
                    pass

        self.client.on_chat = on_chat
        self.client.on_pm = on_pm
        self.client.on_add_player = on_add_player
        self.client.on_del_player = on_del_player
        self.client.on_hurt = on_hurt
        self.client.on_minimap = on_minimap
        self.client.on_ghost_mode = on_ghost_mode
        # A relayed projectile (another player's shoot) — fire actionprojectile2
        # so weapons react (Bomber Arena's room system is built on this). #p(n)
        # maps to event args: per GServer-v2 mc_p, #p(0) is the first param after
        # the event name. The arena room-join reads the Bomb.Queue tag at #p(2)
        # and the room+account at #p(3), so the two leading slots are the shooter
        # and gani. NOTE: this prefix is inferred, not yet confirmed against a
        # real 2-player relayed packet — tune once one is captured.
        def on_projectile(info):
            if getattr(self, 'gs1', None) is None:
                return
            csv = info.get('params', '') or ''
            params = csv.split(',') if csv else []
            shooter = str(info.get('shooter', ''))
            gani = info.get('gani', '') or ''
            self.gs1.fire_projectile([shooter, gani] + params)

        self.client.on_file = on_file
        self.client.on_weapon_add = on_weapon_add
        self.client.on_projectile = on_projectile
    def _play_audio(self, name: str):
        """Play a `play <file>` from an NPC script: stream MIDI/OGG music via
        mixer.music, or fire a one-shot sample. Music is downloaded from the
        server if we don't have it yet, then started in on_file."""
        if not name:
            return
        if self.sound_mgr.is_music(name):
            if name == getattr(self, '_current_music_name', None):
                return  # already playing/queued this track
            self._current_music_name = name
            if self.sound_mgr.play_music(name):       # on disk already
                return
            # Not local — ask the server for it; on_file plays it on arrival.
            self._pending_music = name
            try:
                self.client.request_file(name)
            except Exception:
                pass
        else:
            self.sound_mgr.play(name)

    def _setup_gs1_callbacks(self):
        """Setup GS1 interpreter callbacks for visual/audio feedback."""
        # action string -> last-sent time, to throttle repeated triggeractions.
        self._triggeraction_sent = {}
        # Play sound/music callback (routes MIDI to streaming music).
        def on_play(sound_name):
            self._play_audio(sound_name)

        # Say/chat callback - sets NPC speech bubble
        def on_say(npc_id, message):
            self.npc_chat_texts[npc_id] = (message, time.time())

        # Show message callback (dialogue box)
        def on_message(text):
            self._show_dialogue(text)

        # Set effect callback
        def on_seteffect(r, g, b, a):
            # Could apply screen tint effect here
            pass

        # freezeplayer N — lock local input for N seconds (NPC dialogue, etc).
        def on_freezeplayer(seconds):
            self._frozen_until = time.time() + max(0.0, float(seconds or 0))

        # toweapons <name> — script wants this weapon present locally; make sure
        # it's registered so #w()/weapon logic see it (server also streams it).
        def on_toweapons(name):
            if name and name not in self.client.weapons:
                self.client.weapons[name] = {'name': name, 'image': '', 'script': ''}

        # setminimap img,txt,... — remember the minimap source + fetch the file.
        def on_setminimap(args):
            self._gs1_minimap = args
            for a in args:
                if isinstance(a, str) and '.' in a:
                    try:
                        self.client.request_file(a)
                    except Exception:
                        pass

        # setlevel2 / serverwarp — authoritative in Graal. Record it; the game
        # loop performs the warp between events (see _process_pending_warp).
        def on_warp(level, x, y):
            self._pending_gs1_warp = (level, x, y)

        # triggeraction x,y,action,... — forward to the server. This is how an
        # arena adds its gameplay weapons (gr.addweapon,-arenaSYS,-arenaGUI).
        # THROTTLE duplicates: scripts like the arena's NPC 162 do
        # `while(!hasweapon(X)) triggeraction gr.addweapon,X` — if the server
        # never pushes X, that loop fires the same action endlessly and floods
        # the server. Send a given action at most once per 5s.
        def on_triggeraction(x, y, action, npc_id):
            now = time.time()
            sent = self._triggeraction_sent
            if now - sent.get(action, 0.0) < 5.0:
                return
            sent[action] = now
            try:
                self.client.triggeraction(action, x, y, npc_id)
            except Exception:
                pass

        # shoot — Bomber's room system uses projectiles as a message bus
        # (setshootparams Bomb.Queue,... ; shoot ...,blank). Send it to the
        # server, which relays it to players in the level as a projectile.
        def on_shoot(kind, args, shoot_params):
            gani = next((a for a in args if a and a != 'blank'), 'blank')
            # The shooter also processes its OWN projectile client-side (the
            # server relay only reaches other players); queue our own
            # actionprojectile2 so e.g. the host of a Bomber room — who shot the
            # Bomb.Queue — reacts to it and warps in. Queued first (before the
            # network send, which may throw) and deferred so we don't re-enter
            # the GS1 engine mid-shoot.
            me = str(getattr(self.client.player, 'id', '') or
                     getattr(self.client.player, 'account', ''))
            if not hasattr(self, '_pending_self_shoots'):
                self._pending_self_shoots = []
            self._pending_self_shoots.append([me, gani] + list(shoot_params))
            try:
                self.client.shoot(gani=gani, params=','.join(shoot_params))
            except Exception:
                pass

        self.gs1.on_play = on_play
        self.gs1.on_say = on_say
        self.gs1.on_message = on_message
        self.gs1.on_freezeplayer = on_freezeplayer
        self.gs1.on_toweapons = on_toweapons
        self.gs1.on_setminimap = on_setminimap
        # setplayerprop #code,value — NPCs talk to you and change your look this
        # way (e.g. NPC 64 sets #c,:Added: when you join a room). #c shows as a
        # speech bubble over you; appearance codes update the local player.
        _PLAYER_PROP = {
            '#1': 'sword_image', '#2': 'shield_image', '#3': 'head_image',
            '#8': 'body_image', '#n': 'nickname',
        }
        def on_setplayerprop(code, value):
            if code == '#c':
                self.local_chat_text = value
                self.local_chat_time = time.time()
                self.client.player.chat = value
            elif code in _PLAYER_PROP:
                setattr(self.client.player, _PLAYER_PROP[code], value)
            # other codes (#P1-#P30 gattribs, ...) not modelled yet — ignore

        self.gs1.on_warp = on_warp
        self.gs1.on_triggeraction = on_triggeraction
        self.gs1.on_shoot = on_shoot
        self.gs1.on_setplayerprop = on_setplayerprop

        # Route NPC touch events through the shared GS1 engine, which runs the
        # script (including its `play`/`triggeraction`/etc. side effects via the
        # gs1.on_* callbacks above). The handler only does collision detection.
        if getattr(self, "npc_handler", None) is not None:
            self.npc_handler.on_playertouchsme = (
                lambda npc_id, npc_data: self.gs1.trigger_npc_event(
                    npc_id, "playertouchsme"))
            # The handler reads collision shapes the engine records on setshape.
            self.npc_handler.gs1 = self.gs1
    def _load_npc_scripts(self):
        """Load NPC scripts into the GS1 interpreter."""
        for npc_id, npc in self.client.npcs.items():
            script = npc.get('script', '')
            if script:
                x, y = npc.get('x', 0), npc.get('y', 0)
                self.gs1.load_script(f"npc_{npc_id}", script, npc_id=npc_id, x=x, y=y)
        self._load_weapon_scripts()

    def _load_weapon_scripts(self):
        """Load the player's weapon scripts (-validation, -arenaSYS, ...) into the
        GS1 engine. They run client-side like NPCs and drive Bomber Arena's whole
        room/game flow (actionprojectile2, setlevel2, ...)."""
        for name, weapon in self.client.weapons.items():
            script = weapon.get('script', '')
            if script:
                self.gs1.load_weapon(name, script)
    def _trigger_playerenters(self):
        """Fire `playerenters` once across all loaded NPC scripts (trigger_event
        with no name already runs every program; calling it per-script would run
        the whole set N times and re-send each triggeraction/shoot)."""
        try:
            self.gs1.trigger_event('playerenters')
        except Exception:
            pass  # Silently ignore errors during event execution

    def _load_new_npcs(self):
        """NPCs stream in over several seconds on a slow server; the startup
        _trigger_playerenters only ran the ones present then. Load + fire
        playerenters on any NPC that arrived since, so it actually runs."""
        new = []
        for npc_id, npc in list(self.client.npcs.items()):
            key = "npc_%s" % npc_id
            script = npc.get('script', '')
            if script and key not in self.gs1.scripts:
                self.gs1.load_script(key, script, npc_id=npc_id,
                                     x=npc.get('x', 0), y=npc.get('y', 0))
                new.append(npc_id)
        for npc_id in new:
            try:
                self.gs1.trigger_npc_event(npc_id, 'playerenters')
            except Exception:
                pass
        if new:
            self.npc_handler.update_npcs()     # pick up their collision shapes

    def _process_self_shoots(self):
        """Fire actionprojectile2 for projectiles WE shot (the shooter handles
        its own projectile; the server relay only reaches other players). Done
        between events so we never re-enter the GS1 engine mid-shoot."""
        pending = getattr(self, '_pending_self_shoots', None)
        if not pending:
            return
        self._pending_self_shoots = []
        for params in pending:
            try:
                self.gs1.fire_projectile(params)
            except Exception:
                pass

    def _process_pending_warp(self):
        """Perform a GS1-requested warp (setlevel2/serverwarp) recorded by the
        on_warp callback. Done here, between events, so we never mutate level
        state in the middle of the script that asked for the warp."""
        warp = getattr(self, '_pending_gs1_warp', None)
        if not warp:
            return
        self._pending_gs1_warp = None
        level, x, y = warp
        if not level:
            return
        try:
            self.client.warp_to_level(level, 30.0 if x is None else x,
                                      30.0 if y is None else y)
        except Exception:
            pass

    def _check_level_change(self):
        """Reload the GS1 engine when the player lands in a new level (script
        warp, door, or server-initiated), once that level's NPCs have streamed
        in. warp_to_level clears NPCs, so reloading too early would run nothing."""
        lvl = self.client._current_level_name
        if not lvl or lvl == getattr(self, '_gs1_level', None):
            return
        now = time.time()
        if getattr(self, '_level_change_pending', None) != lvl:
            self._level_change_pending = lvl
            self._level_change_at = now
        # Give NPCs a beat to arrive, but don't hang on a genuinely empty level.
        if not self.client.npcs and now - self._level_change_at < 0.6:
            return
        self._reload_level_scripts(lvl)

    def _reload_level_scripts(self, lvl: str):
        """Swap the GS1 engine + per-NPC render state over to the current level."""
        self.gs1.clear()
        self._load_npc_scripts()
        self._trigger_playerenters()
        self.npc_handler.update_npcs()
        for attr in ('npc_anims', 'npc_effects', 'npc_chat_texts', 'npc_visual'):
            cache = getattr(self, attr, None)
            if isinstance(cache, dict):
                cache.clear()
        self.visual_x, self.visual_y = self.client.x, self.client.y
        self.world_surface = None
        self._gs1_level = lvl
        self._level_change_pending = None
