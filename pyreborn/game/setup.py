"""SetupMixin — Asset paths, client callbacks, GS1 callbacks, NPC script bootstrap.

Split from pygame_game.py; methods operate on the GameClient instance."""

import os
import time
from pathlib import Path
from typing import List, Optional

from .. import asset_paths
from ..asset_paths import normalize_asset_name
from ..sprites import strip_tiledef_image
from .constants import PACKAGE_DIR, CHAT_HISTORY_CAP


# Downloaded audio handled as one-shot samples (mixer.Sound). The streaming
# side of the split is SoundManager.MUSIC_EXTS; .ogg deliberately appears only
# there, so a downloaded track keeps going to mixer.music.
SAMPLE_EXTS = ('wav', 'aiff', 'aif', 'flac')


def append_start_message(chat_messages: list, text: str) -> int:
    """Append at most five non-empty initial-message lines to chat.

    Returns the number of lines appended so the caller can advance
    chat_seq (the monotonic append counter the scroll indicator uses).
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    added = [f"[server] {line}" for line in lines[:5]]
    chat_messages.extend(added)
    if len(chat_messages) > CHAT_HISTORY_CAP:
        del chat_messages[:-CHAT_HISTORY_CAP]
    return len(added)


class SetupMixin:
    """Mixin providing the above methods for GameClient."""

    def _invalidate_tile_derived_caches(self) -> None:
        """Clear every render cache whose pixels come from the tileset."""
        clear_tiles = getattr(self.tileset_mgr, "clear_cache", None)
        if clear_tiles is not None:
            clear_tiles()
        else:
            tile_cache = getattr(self.tileset_mgr, "tile_cache", None)
            if tile_cache is not None:
                tile_cache.clear()
        self.world_surface = None
        for name in ("_shimmer_cache", "_chest_sprite_cache"):
            cache = getattr(self, name, None)
            if cache is not None:
                cache.clear()

    def _append_chat(self, message: str) -> None:
        """Append one chat-log line, trim to the cap, and advance chat_seq.

        chat_seq is a monotonic count of appends: unlike len(chat_messages),
        it keeps growing once the log is at CHAT_HISTORY_CAP (where every
        append pops a line), so the scroll indicator's "N new" math works.
        """
        self.chat_messages.append(message)
        if len(self.chat_messages) > CHAT_HISTORY_CAP:
            self.chat_messages.pop(0)
        self.chat_seq += 1

    def _update_low_hearts_warning(self, now: Optional[float] = None) -> bool:
        """Play the low-health reminder at most once per second."""
        now = time.monotonic() if now is None else now
        player = self.client.player
        active = (getattr(self, '_low_hearts_warning_enabled', True)
                  and self.client.connected and 0 < player.hearts <= 1.0
                  and player.max_hearts > 1)
        if not active:
            self._low_hearts_next_beep = 0.0
            return False
        if now < getattr(self, '_low_hearts_next_beep', 0.0):
            return False
        self._low_hearts_next_beep = now + 1.0
        self.sound_mgr.play("beep.wav", volume=0.35)
        return True

    def _setup_asset_paths(self) -> List[Path]:
        """Setup asset search paths."""
        # Server art wins over the user's stock copy of the same filename;
        # bundled defaults are the last resort.
        return [
            asset_paths.server_cache_dir(self.client.host, self.client.port),
            *asset_paths.content_dirs(),
            PACKAGE_DIR / "assets",
        ]
    def _setup_callbacks(self):
        """Setup client callbacks."""
        # State for the newer render_effects visuals below - initialized here
        # (this runs once, at the end of GameClient.__init__) rather than in
        # pygame_game.py, which owns the rest of the render-state init.
        self.other_thrown_objects = []   # PLO_THROWCARRIED arcs (other players)
        self._pushaway_velocity = (0.0, 0.0)   # PLO_PUSHAWAY knockback, tiles/sec

        # Let the sound manager fetch sounds it doesn't have, through the same
        # one-shot request path images/ganis use (render_entities.py:1077).
        # Wired here rather than beside the manager's construction because
        # _request_asset needs _requested_assets, built later in __init__; the
        # names preload_common_sounds() wrote off before now are re-requested
        # on their next miss (sounds.py:127-132).
        self.sound_mgr.file_requester = self._request_asset

        send_level_chat = self.client.send_level_chat
        def send_level_chat_with_events(message):
            sent = send_level_chat(message)
            if sent:
                if getattr(self, 'gs1', None) is not None:
                    self.gs1.trigger_event('playerchats')
                if getattr(self, 'gs2', None) is not None:
                    self.gs2.trigger_event("onPlayerChats")
            return sent
        self.client.send_level_chat = send_level_chat_with_events

        def on_chat(player_id, message):
            self._append_chat(f"[{player_id}] {message}")

        def on_pm(from_id, message):
            # Show received private messages in the chat log, named by sender.
            name = self._player_label(from_id)
            self._append_chat(f"[PM {name}] {message}")

        def _roster_name(info):
            return info.get('nickname') or info.get('account') or "?"

        def on_add_player(pid, info):
            # The server dumps the whole roster on login; only announce joins
            # that arrive after that settles (roster_ready_time, set in run()).
            if time.time() >= self.roster_ready_time:
                self._append_chat(f"-> {_roster_name(info)} entered")

        def on_del_player(pid, info):
            self._append_chat(f"<- {_roster_name(info)} left")

        def on_hurt(attacker_id, damage, damage_type, source_x, source_y):
            now = time.monotonic()
            # Spawn floating damage number at player position
            self.damage_numbers.append({
                'x': self.visual_x,
                'y': self.visual_y - 16,
                'damage': damage,
                'time': time.time(),
                'duration': 1.0,
            })
            # Trigger hurt flash
            self.combat_presentation.hurt(
                now, dead=self.client.player.hearts <= 0)

            # Check for death (hearts already reduced by client.respond_to_hurt)
            if self.client.player.hearts <= 0:
                # Play death sound
                self.sound_mgr.play("dead.wav")
                # Set death animation
                self.player_anim.set_animation("dead", self.client.player.direction)
            else:
                self.sound_mgr.play("hurt.wav")

        def on_item(x, y, item_type, removed):
            pass

        def on_explosion(x, y, radius, power):
            self._start_camera_shake(x, y)

        def on_minimap(data: bytes):
            """Handle minimap data from server."""
            self.minimap_data = data
            self._build_minimap_surface()

        def on_ghost_mode(enabled: bool):
            """Handle ghost mode toggle."""
            self.ghost_mode = enabled

        # Tier 3b: PLO_SERVERTEXT - a text answer from the server (e.g. a
        # gr.getstring()/gettext() reply) - surface it in the chat log like an
        # incoming message so it isn't silently dropped.
        def on_server_text(text: str):
            if text:
                self._append_chat(f"[server] {text}")
            # This assignment replaces the hook ClientGS2.attach() installed
            # (attach runs before _setup_callbacks), so forward the engine
            # event explicitly: onReceiveText drives the Login serverlist
            # chat weapon.
            gs2 = getattr(self, 'gs2', None)
            if gs2 is not None:
                gs2.handle_server_text(text)

        def on_start_message(text: str):
            """Put up to five non-empty initial-message lines in chat."""
            self.chat_seq += append_start_message(self.chat_messages, text)

        # PLO_RPGWINDOW (179) is the server's login greeting in practice
        # (GServer-v2 PlayerClient.cpp sends "Welcome to <name>." + credits
        # right before PLO_STARTMESSAGE). The real classic client shows it
        # non-modally; routing it into our modal sign dialog gated all input
        # at login (input.py's dialogue_text check) until the player noticed
        # and dismissed it. Put it in the chat log like the startmessage.
        # Real sign dialogs (level signs, PLO_SAY2) stay modal — see
        # actions.py / on_say2.
        def on_rpg_window(lines):
            if lines:
                self.chat_seq += append_start_message(
                    self.chat_messages, "\n".join(lines))

        def on_file(filename: str, data: bytes):
            """Cache a downloaded asset. Images go to the sprite cache, ganis to
            the gani parser's cache, one-shot samples to the sound cache; a
            music file we were waiting on starts playing once it arrives."""
            filename = normalize_asset_name(filename)
            ext = filename.rsplit('.', 1)[-1]
            if ext in ('png', 'gif', 'bmp', 'mng'):
                self.sprite_mgr.load_bytes(filename, data)
                # A custom tileset image (addtiledef/addtiledef2) just
                # arrived — drop the tile cache so blocks re-render with it
                # instead of the default.
                tm = self.tileset_mgr
                if (any(img == filename for img, _, _, _ in tm.tiledefs)
                        or any(img == filename
                               for img, _, _ in tm.full_tiledefs)
                        # the setbackpal palette file just arrived: recompose
                        # so the swap actually shows (set_backpal ran before
                        # the download finished)
                        or filename == normalize_asset_name(tm.backpal)
                        # the BASE sheet just arrived. Classic (2.x) sessions
                        # switch default_tileset to pics1.png and request it
                        # from the server when there is no local copy
                        # (pygame_game.py); without this the download lands in
                        # the sprite cache but every tile keeps rendering from
                        # the stale surface, so the whole world stays wrong.
                        or filename == normalize_asset_name(
                            tm.default_tileset
                        )):
                    self._invalidate_tile_derived_caches()
            elif ext == 'gani':
                # The server streams gani scripts on demand; cache the parsed
                # animation so NPCs/players using it stop falling back to the
                # missing-asset placeholder. Keyed by the bare name (no .gani).
                name = filename[:-5] if filename.lower().endswith('.gani') else filename
                gani = None
                try:
                    gani = self.gani_parser.parse_content(
                        data.decode('latin-1'), name)
                    self.gani_parser.put_cache(name, gani)
                except Exception:
                    pass
                else:
                    # Request the sheets this gani names NOW. Discovering them
                    # from the frame blit fallback instead costs one server
                    # round trip per frame/direction: measured on a live
                    # server, 43 files took 5.12s that way (~119ms each) on a
                    # link that batches at 264 KB/s.
                    try:
                        self._prefetch_gani_assets(gani)
                    except Exception:
                        pass
                # A scripted player gani (GS1 setani -> on_setani below) may
                # have been asked for before it was downloaded; the anim
                # state remembers the ask in requested_name — re-assert it so
                # the pose pops in on arrival (NPCs get this for free from
                # the per-frame render re-assert; the player path is
                # transition-driven).
                anim = getattr(self, 'player_anim', None)
                if (anim is not None and anim.requested_name == name
                        and (anim.gani is None or anim.gani.name != name)):
                    try:
                        anim.set_animation(name)
                        self.current_anim_name = name
                    except Exception:
                        pass
            elif self.sound_mgr.is_music(filename):
                if filename == getattr(self, '_pending_music', None):
                    self._pending_music = None
                    self.sound_mgr.play_music(filename, data=data)
            elif ext in SAMPLE_EXTS:
                # A server's custom sounds exist nowhere on disk until asked
                # for (`file sounds/*.wav` in foldersconfig), so these bytes
                # are the only copy we will ever get; without this branch they
                # were discarded and the sound stayed silent for the session.
                # Ordered AFTER the is_music test on purpose: mixer.Sound can
                # decode an .ogg too, but a streaming format belongs to
                # mixer.music (sounds.py:285).
                self.sound_mgr.load_bytes(filename, data)

        # A weapon arrived (gr.addweapon, e.g. -arenaSYS/-arenaGUI on arena
        # entry): load it into the GS1 engine and fire its playerenters so it
        # activates immediately, like a real client adding a weapon.
        def on_weapon_add(name, weapon):
            script = weapon.get('script', '')
            if script and getattr(self, 'gs1', None) is not None:
                is_new = self.gs1.load_weapon(name, script)
                try:
                    if is_new:
                        self.gs1.trigger_event('created', name=f'weapon_{name}')
                    self.gs1.trigger_event('playerenters', name=f'weapon_{name}')
                except Exception:
                    pass

        def on_bomb_add(info):
            self._add_remote_bomb(info)

        def on_bomb_del(x, y):
            self._detonate_bomb_at(x, y)

        def on_arrow_add(info):
            self._add_remote_arrow(info)

        # Tier 1b: a board tile delta arrived - patch just the affected rect
        # into the cached world_surface instead of a full rebuild.
        def on_board_modify(info):
            self._patch_world_surface_for_modify(info)

        # Tier 1d: an extra board layer streamed in/changed - layers are only
        # sent a handful of times per level (not every frame), so a full
        # world_surface rebuild is cheap and simplest here.
        def on_board_layer(layer, x, y, tiles):
            self.world_surface = None

        # PLO_HITOBJECTS - a player's sword/weapon connected with a bush/pot/
        # etc; spawn the same break/spark burst a thrown object landing uses
        # (see render_effects._spawn_hit_break_effect).
        def on_hit_objects(x, y, power, player_id):
            self._spawn_hit_break_effect(x, y)
            self._spawn_leaf_particles(x, y)

        # PLO_THROWCARRIED - another player threw whatever they were
        # carrying. The packet only names the owner (see
        # packets.parse_throwcarried), so look up their last known
        # position/direction and launch a generic thrown-arc from there (see
        # render_effects._update_and_render_other_thrown / on init below).
        def on_throwcarried(owner_id):
            owner = self.client.players.get(owner_id)
            if not owner:
                return
            direction = owner.get('direction', 2) or 2
            ddx, ddy = self._facing_delta(direction)
            x, y = owner.get('x', 0.0), owner.get('y', 0.0)
            z0 = 2.75
            self.other_thrown_objects.append({
                'x': x, 'y': y + 1.0,
                'z': z0, 'z0': z0,
                'dx': ddx, 'dy': ddy,
                'speed': 20.0, 'dist': 0.0, 'range': 16.0,
                'colors': self.BREAK_COLORS['bush'],
            })

        # PLO_FIRESPY - a GS1 firespy/fireball effect from another player's
        # weapon script. Like PLO_THROWCARRIED, the payload is just the owner
        # + power/length (see packets.parse_firespy); feed it into the same
        # active_projectiles pipeline as a local bow shot, tagged 'firespy' so
        # render_effects picks the fireball gani/fallback color instead of
        # the arrow's.
        def on_firespy(info):
            owner = self.client.players.get(info.get('owner_id'))
            if not owner:
                return
            direction = owner.get('direction', 2) or 2
            speed = 10.0
            dx_map = {0: 0, 1: -speed, 2: 0, 3: speed}
            dy_map = {0: -speed, 1: 0, 2: speed, 3: 0}
            x, y = owner.get('x', 0.0), owner.get('y', 0.0)
            self.active_projectiles.append({
                'x': x, 'y': y,
                'dx': dx_map.get(direction, 0), 'dy': dy_map.get(direction, 0),
                'time': time.time(), 'direction': direction, 'gani': 'firespy',
                'max_distance': max(1.0, float(info.get('length', 1) or 1)),
                'start_x': x, 'start_y': y,
            })

        # PLO_PUSHAWAY (packet 38) - a knockback impulse. Queued here and
        # applied/decayed per-frame in render_effects._apply_pushaway (see its
        # docstring for the conservative-decode note).
        def on_pushaway(dx, dy):
            vx, vy = self._pushaway_velocity
            self._pushaway_velocity = (vx + dx, vy + dy)

        def on_say2(text):
            self._show_dialogue(text, classic_font=True)

        self.client.on_chat = on_chat
        self.client.on_say2 = on_say2
        self.client.on_pm = on_pm
        self.client.on_add_player = on_add_player
        self.client.on_del_player = on_del_player
        self.client.on_hurt = on_hurt
        self.client.on_item = on_item
        self.client.on_explosion = on_explosion
        self.client.on_minimap = on_minimap
        self.client.on_ghost_mode = on_ghost_mode
        if hasattr(self.client, 'on_bomb_del'):
            self.client.on_bomb_del = on_bomb_del
        if hasattr(self.client, 'on_bomb_add'):
            self.client.on_bomb_add = on_bomb_add
        if hasattr(self.client, 'on_arrow_add'):
            self.client.on_arrow_add = on_arrow_add
        if hasattr(self.client, 'on_board_modify'):
            self.client.on_board_modify = on_board_modify
        if hasattr(self.client, 'on_board_layer'):
            self.client.on_board_layer = on_board_layer
        if hasattr(self.client, 'on_server_text'):
            self.client.on_server_text = on_server_text
        if hasattr(self.client, 'on_start_message'):
            self.client.on_start_message = on_start_message
        if hasattr(self.client, 'on_rpg_window'):
            self.client.on_rpg_window = on_rpg_window
        if hasattr(self.client, 'on_hit_objects'):
            self.client.on_hit_objects = on_hit_objects
        if hasattr(self.client, 'on_throwcarried'):
            self.client.on_throwcarried = on_throwcarried
        if hasattr(self.client, 'on_firespy'):
            self.client.on_firespy = on_firespy
        if hasattr(self.client, 'on_pushaway'):
            self.client.on_pushaway = on_pushaway
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
            args = [shooter, gani] + params
            self.gs1.fire_projectile(args)
            # GS2 weapons take the same event; params[i] == GS1's #p(i)
            # (verified against Bomber v6's -validation: params[2] is the
            # Bomb.Queue tag, params[3] the room+account).
            gs2 = getattr(self, 'gs2', None)
            if gs2 is not None:
                gs2.trigger_event("onActionProjectile2", *args)

        # A server flag arrived (PLO_FLAGSET) — route it into the right GS1
        # scope: "client."/"clientr." are the player's persisted account flags
        # (PetSys's client.pet chocobo/squirrel selection), the rest are
        # globals (bomber's room roster server.bombrm_NN).
        def on_flag(name, value):
            gs1 = getattr(self, 'gs1', None)
            if gs1 is not None:
                gs1.recv_flag(name, value)

        # PLO_FLAGDEL: the server unsets flags too (bomber empties its queue
        # roster this way) — without this, scripts keep reading stale values.
        def on_flag_del(name):
            gs1 = getattr(self, 'gs1', None)
            if gs1 is not None:
                gs1.recv_flag_del(name)

        self.client.on_file = on_file
        self.client.on_weapon_add = on_weapon_add
        self.client.on_projectile = on_projectile
        self.client.on_flag = on_flag
        self.client.on_flag_del = on_flag_del
        # flags received before the GS1 engine existed
        if getattr(self, 'gs1', None) is not None:
            for _fn, _fv in (self.client.global_flags or {}).items():
                self.gs1.recv_flag(_fn, _fv)
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

        # stopmidi/stopsong — stop streaming music and clear the dedup name so a
        # later play (even of the same track) starts fresh.
        def on_stopmusic():
            self.sound_mgr.stop_music()
            self._current_music_name = None
            self._pending_music = None

        # Say/chat callback - sets NPC speech bubble. Fed by the GS1
        # say/message command AND by a GS2 NPC's `this.chat = ...` write
        # (gs2_client._NpcThisObject.set). Empty text clears the bubble
        # immediately (setting chat to "" is how scripts stop speaking)
        # rather than letting the stale bubble ride out its timeout.
        def on_say(npc_id, message):
            if message:
                self.npc_chat_texts[npc_id] = (message, time.time())
            else:
                self.npc_chat_texts.pop(npc_id, None)

        def on_say2(text):
            self._show_dialogue(text, classic_font=True)

        # Show message callback (dialogue box)
        def on_message(text):
            self._show_dialogue(text)

        # setani from ANY GS1 script targets the LOCAL PLAYER (setcharani is
        # the NPC form — gs1_client._cmd_setani). Mirror the scripted gani
        # into the state the renderer draws (player_anim/current_anim_name),
        # which only the built-in input path otherwise updates. `joined` is
        # the raw comma-joined `ani,param1,...` form; set_animation splits
        # the params off itself so PARAMn sound/sprite tokens resolve.
        def on_setani(joined):
            base = joined.split(',')[0].strip()
            if not base:
                return
            # Marks the ani as script-owned: render.py's finished-animation
            # chain holds a setback-less scripted gani on its final frame
            # instead of auto-idling (disarmed as soon as any other writer
            # changes current_anim_name away from this name).
            self._scripted_player_ani = base
            try:
                direction = int(self.client.player.direction) & 3
            except (TypeError, ValueError):
                direction = 2
            try:
                self.player_anim.set_animation(base, direction,
                                               params=joined.split(',')[1:])
                self.current_anim_name = base
            except Exception:
                pass
            # The scripted gani may not be downloaded yet (bomber's
            # sen_piano_idle) — fetch it through the once-only asset path;
            # the on_file gani branch above re-asserts it when it lands.
            try:
                gani = self.gani_parser.parse(base)
                if gani is None:
                    self._request_asset(base + '.gani')
                else:
                    self._prefetch_gani_assets(gani)
            except Exception:
                pass

        # Set effect callback (Tier 3d) - fullscreen tint drawn under the HUD,
        # over the world (see game/render_effects.py _render_screen_tint,
        # called from the main render loop). r,g,b,a are 0..1 GS1 multipliers,
        # same convention as changeimgcolors/setcoloreffect elsewhere.
        def on_seteffect(r, g, b, a):
            def c255(v):
                return max(0, min(255, int(float(v) * 255)))
            if a and c255(a) > 0:
                self.screen_tint = {'r': c255(r), 'g': c255(g), 'b': c255(b), 'a': c255(a)}
            else:
                self.screen_tint = None

        # freezeplayer N — lock local input for N seconds (NPC dialogue, etc).
        def on_freezeplayer(seconds):
            self._frozen_until = time.time() + max(0.0, float(seconds or 0))

        # toweapons <name> converts a level NPC into a local weapon and asks the
        # server to persist the grant. Weapon callers retain name-only behavior.
        def on_toweapons(name, npc_id=None, script=None, image=None):
            if not name:
                return
            current = self.client.weapons.get(name)
            if npc_id is not None and (current is None or not current.get('script')):
                script = script or ''
                self.client.weapons[name] = {
                    'name': name, 'image': image or '', 'script': script,
                }
                if script and getattr(self, 'gs1', None) is not None:
                    is_new = self.gs1.load_weapon(name, script)
                    try:
                        if is_new:
                            self.gs1.trigger_event('created', name=f'weapon_{name}')
                        self.gs1.trigger_event('playerenters', name=f'weapon_{name}')
                    except Exception:
                        pass
            elif current is None:
                self.client.weapons[name] = {'name': name, 'image': '', 'script': ''}
            if npc_id is not None:
                try:
                    self.client.send_weapon_add(npc_id)
                except Exception:
                    pass

        # setminimap img,txt,... — remember the minimap source + fetch the file.
        # Via _request_asset (not raw request_file) so it's requested once per
        # session: setminimap re-runs on every level (re-)entry playerenters,
        # and re-requested the same files (no-shield.png/bombarena_map.txt on
        # bomber) on each re-entry.
        def on_setminimap(args):
            for a in args:
                if isinstance(a, str) and '.' in a:
                    self._request_asset(a)

        # setlevel2 / serverwarp — authoritative in Reborn. Record it; the game
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
                # PYREBORN_DEBUG breadcrumb (same idiom as npc_handler's
                # [touch] line): a suppressed re-send within the 5s window is
                # invisible otherwise. GS1-path repeats are deliberately
                # dropped here for five seconds; GS2 triggeraction calls use
                # their direct host path and do not pass through this throttle.
                if os.environ.get("PYREBORN_DEBUG"):
                    import sys
                    print(f"[trigger] throttled (<5s repeat): {action!r}",
                          file=sys.stderr)
                return
            sent[action] = now
            if os.environ.get("PYREBORN_DEBUG"):
                import sys
                print(f"[trigger] -> server: {action!r}", file=sys.stderr)
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
        self.gs1.on_stopmusic = on_stopmusic
        # putleaps type,x,y -> debris burst (render_effects owns frames+sound)
        self.gs1.on_putleaps = (lambda leap_type, x, y:
                                self._spawn_leaps(leap_type, x, y))

        # -- scripted combat family (GS1 putbomb/explosions/setbackpal) ----
        # putbomb -> the same active_bombs registry local/remote bombs use
        # (render_effects.py runs the fuse, burst, sound and bush-break).
        def on_putbomb(power, x, y, fuse_s):
            self.active_bombs.append({
                'x': float(x), 'y': float(y), 'time': time.time(),
                'fuse_time': max(0.05, float(fuse_s)),
                'power': max(1, int(power)), 'exploded': False,
                'source': 'script',
            })

        # removebomb (silent pickup) / explodebomb (burst now)
        def on_removebomb(bomb, explode):
            if explode:
                self._detonate_bomb(bomb)
                return
            try:
                self.active_bombs.remove(bomb)
            except ValueError:
                pass

        # putexplosion's presentation half (the damage/washit/wire half is
        # client-level, gs1_client._spawn_explosion): boom + shake + bushes.
        def on_putexplosion(power, radius, x, y):
            self.sound_mgr.play("explode.wav")
            self._start_camera_shake(x, y)
            self._break_bushes_in_blast(x, y, max(1, int(power)))

        def on_setbackpal(image):
            image = (image or "").strip()
            if not image:
                return
            changed = self.tileset_mgr.set_backpal(image)
            # pal files are server assets (GTA's underwaterpal.png & co);
            # _request_asset dedupes the fetch across the per-level re-issues.
            if not self.sprite_mgr.has_sheet(image):
                self._request_asset(image)
            if changed:
                self._invalidate_tile_derived_caches()

        self.gs1.on_putbomb = on_putbomb
        self.gs1.on_removebomb = on_removebomb
        self.gs1.on_putexplosion = on_putexplosion
        self.gs1.on_setbackpal = on_setbackpal
        # bombs[] index order = the shell's placement-ordered registry
        self.gs1.bombs_source = lambda: self.active_bombs
        self.gs1.on_say = on_say
        self.gs1.on_say2 = on_say2
        self.gs1.on_setani = on_setani
        self.gs1.on_message = on_message
        self.gs1.on_freezeplayer = on_freezeplayer
        self.gs1.on_toweapons = on_toweapons
        self.gs1.on_setminimap = on_setminimap

        # setfocus/resetfocus — scripted camera target (splash/cutscenes).
        # Consumed by render.py's per-frame centering; cleared on level
        # reload (scripts re-issue it on playerenters if they still want it).
        def on_setfocus(x, y):
            self._camera_focus = None if x is None else (float(x), float(y))
        self.gs1.on_setfocus = on_setfocus
        self.gs1.on_seteffect = on_seteffect
        # setplayerprop #code,value — NPCs talk to you and change your look this
        # way (e.g. NPC 64 sets #c,:Added: when you join a room). #c shows as a
        # speech bubble over you; appearance codes update the local player.
        _PLAYER_PROP = {
            '#1': 'sword_image', '#2': 'shield_image', '#3': 'head_image',
            '#8': 'body_image', '#n': 'nickname',
        }
        def on_setplayerprop(code, value):
            if code == '#c':
                if os.environ.get("PYREBORN_DEBUG"):
                    import sys
                    print(f"[chat] {value!r}", file=sys.stderr)
                self.local_chat_text = value
                self.local_chat_time = time.time()
                self.client.player.chat = value
            elif code == '#3':
                self.client.send_head_image(value)
            elif code == '#8':
                self.client.send_body_image(value)
            elif code.startswith('#C') and code[2:].isdigit():
                index = int(code[2:])
                colors = list(self.client.player.colors)
                if 0 <= index < self.client._colors_len:
                    colors.extend([0] * (self.client._colors_len - len(colors)))
                    colors[index] = int(float(value))
                    self.client.send_colors(colors)
            elif code in _PLAYER_PROP:
                setattr(self.client.player, _PLAYER_PROP[code], value)
            # other codes (#P1-#P30 gattribs, ...) not modelled yet — ignore

        # Point the tileset manager at custom sheets, downloading them if
        # needed, so the board renders with the active definitions.
        def on_tiledef(kind, image, levelstart="", x=0, y=0):
            if kind is None:
                if self.tileset_mgr.clear_tiledefs(image or ""):
                    self._invalidate_tile_derived_caches()
                return
            image = strip_tiledef_image(image)
            if kind == "full":
                # addtiledef: whole-tileset replacement sheet. For "full"
                # the x slot carries the def's tile TYPE (0 classic,
                # 1/2 new-world, 5 none), which also picks the type table.
                self.tileset_mgr.set_full_tiledef(image, levelstart, x)
            else:
                self.tileset_mgr.set_tiledef(image, levelstart, x, y)
            # tileset_mgr's tile_cache is cleared above, but the baked
            # per-segment surfaces in render_world.py's _segments() cache
            # are keyed off tiles_id/layers_snapshot only - a tiledef swap
            # doesn't touch either, so they'd keep returning stale bakes
            # from the old tileset. Force a full rebuild.
            self._invalidate_tile_derived_caches()
            if not self.sprite_mgr.has_sheet(image):
                try:
                    self.client.request_file(image)
                except Exception:
                    pass

        self.gs1.on_warp = on_warp
        self.gs1.on_triggeraction = on_triggeraction
        self.gs1.on_shoot = on_shoot
        self.gs1.on_setplayerprop = on_setplayerprop
        self.gs1.on_tiledef = on_tiledef

        # #m / replaceani wiring: scripts read the player's CURRENT ani via #m
        # (Bomber's stairs NPC gates its slowdown on it), so the engine needs
        # our live logical anim name; and our anim state + outgoing gani prop
        # substitute any `replaceani` mapping (walk -> eye_bomber_walk0 etc.)
        # like the real client does.
        self.gs1.player_ani_source = lambda: getattr(self, "current_anim_name", "")
        self.player_anim.name_resolver = self.gs1.resolve_ani
        self.client.ani_resolver = self.gs1.resolve_ani

        # Script tile probes (onwall/onwater/tiletype) must read the same
        # board our own collision does. CollisionMixin._get_tile_at resolves
        # a WORLD coordinate through the gmap grid to the owning segment;
        # (guarded: unit harnesses mix SetupMixin in without CollisionMixin,
        # and the GS1 host's own single-level fallback is right for them.)
        self.gs1.tile_source = getattr(self, "_get_tile_at", None)

        # Image-NPC footprints (blocking + touch) size themselves off the
        # actual art and are refined by per-pixel transparency where it is
        # loaded — see gs1_client.ClientGS1.npc_blocks_at for the
        # oracle-derived rule. Without the opaque probe a mostly-transparent
        # decoration (glows, lamp halos) would wall off its whole rect.
        sprite_mgr = getattr(self, "sprite_mgr", None)
        if sprite_mgr is not None:
            def _npc_image_size(name, _sm=sprite_mgr):
                sheet = _sm.load_sheet(name)
                return sheet.get_size() if sheet is not None else None

            def _npc_image_opaque(name, px, py, _sm=sprite_mgr):
                sheet = _sm.load_sheet(name)
                if sheet is None:
                    return None            # unknown art: caller treats opaque
                w, h = sheet.get_size()
                if not (0 <= px < w and 0 <= py < h):
                    return False           # off the art: transparent
                c = sheet.get_at((int(px), int(py)))
                if c.a == 0:
                    return False
                ck = sheet.get_colorkey()  # gif palette transparency
                if ck is not None and (c.r, c.g, c.b) == tuple(ck[:3]):
                    return False
                return True

            self.gs1.image_size_source = _npc_image_size
            self.gs1.image_opaque_source = _npc_image_opaque

        # A sword swing connected with a level NPC (client.py _sword_hit_npcs):
        # fire `washit` on it, same as the real client (scripting-gs1-events.md).
        self.client.on_sword_hit_npc = (
            lambda npc_id: self.gs1.trigger_npc_event(npc_id, "washit"))

        # Route NPC touch events through the shared GS1 engine, which runs the
        # script (including its `play`/`triggeraction`/etc. side effects via the
        # gs1.on_* callbacks above). The handler only does collision detection.
        if getattr(self, "npc_handler", None) is not None:
            def _route_touch(npc_id, npc_data):
                self.gs1.trigger_npc_event(npc_id, "playertouchsme")
                # GS2 NPCs (v6 servers stream bytecode) take the same touch.
                # gs2 is created after this callback is wired (GameClient
                # __init__ order), hence the getattr.
                gs2 = getattr(self, "gs2", None)
                if gs2 is not None:
                    gs2.trigger_npc_event(npc_id, "onPlayerTouchsMe")
            self.npc_handler.on_playertouchsme = _route_touch
            # The handler reads collision shapes the engine records on setshape.
            self.npc_handler.gs1 = self.gs1
            # Drop a despawned NPC's shape/script so its ghost can't keep
            # firing playertouchsme from the old tile, and clear its render
            # caches.
            self.client.on_npc_del = self._on_npc_del

    def _on_npc_del(self, npc_id: int):
        if getattr(self, "npc_handler", None) is not None:
            self.npc_handler.forget_npc(npc_id)
        for attr in ('npc_anims', 'npc_effects', 'npc_chat_texts', 'npc_visual'):
            cache = getattr(self, attr, None)
            if isinstance(cache, dict):
                cache.pop(npc_id, None)

    def _load_npc_scripts(self):
        """Load NPC scripts into the GS1 interpreter and fire each one's
        `created` event — the real client runs onCreated when a level NPC
        spawns (each level visit). GTA's system NPCs rely on it: their
        `if (created) hide;` is what keeps the weapon-icon NPCs (*Clock and
        friends, placed mid-level on splashscreen.nw) invisible."""
        for npc_id, npc in self.client.npcs.items():
            script = npc.get('script', '')
            if script:
                x, y = npc.get('x', 0), npc.get('y', 0)
                self.gs1.load_script(f"npc_{npc_id}", script, npc_id=npc_id, x=x, y=y)
                try:
                    self.gs1.trigger_event('created', name=f"npc_{npc_id}")
                except Exception:
                    pass
        self._load_weapon_scripts()

    def _load_weapon_scripts(self):
        """Load the player's weapon scripts (-validation, -arenaSYS, ...) into the
        GS1 engine. They run client-side like NPCs and drive Bomber Arena's whole
        room/game flow (actionprojectile2, setlevel2, ...)."""
        for name, weapon in self.client.weapons.items():
            script = weapon.get('script', '')
            if script:
                if self.gs1.load_weapon(name, script):
                    try:
                        self.gs1.trigger_event('created', name=f'weapon_{name}')
                    except Exception:
                        pass
    def _trigger_playerenters(self):
        """Fire `playerenters` once across all loaded NPC scripts (trigger_event
        with no name already runs every program; calling it per-script would run
        the whole set N times and re-send each triggeraction/shoot).

        Held off entirely until the level's board has arrived: a level's entry
        scripts read `tiles[x,y]` to decide what the room contains, and classic
        Bomber's room0.nw DELETES catalog entries (writing the result back to
        `server.room<N>`) for wall furniture whose tile isn't the wall id — so
        running it against a board that is missing or still the previous
        level's destroys the player's room. The retry lives in
        _check_level_change."""
        if not self.gs1.board_ready():
            self._gs1_playerenters_pending = True
            return
        self._gs1_playerenters_pending = False
        try:
            self.gs1.trigger_event('playerenters')
        except Exception:
            pass  # Silently ignore errors during event execution

    def _load_new_npcs(self):
        """NPCs stream in over several seconds on a slow server; the startup
        _trigger_playerenters only ran the ones present then. Load + fire
        playerenters on any NPC that arrived since, so it actually runs.

        Held off during a level transition (engine not yet reloaded for the
        new level): _reload_level_scripts fires playerenters weapons-first,
        matching real-client event order. Pre-firing a streamed NPC here let
        the arena's control NPC run before the player's -validation weapon
        had set #P2, so it read the room as empty and kicked the host
        (":No Players:") before the match could form."""
        if self.client._current_level_name != getattr(self, '_gs1_level', None):
            return
        if not self.gs1.board_ready():
            return  # same boardless-playerenters rule as _trigger_playerenters
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
                self.gs1.trigger_npc_event(npc_id, 'created')
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
            gs2 = getattr(self, 'gs2', None)
            if gs2 is not None:
                try:
                    gs2.trigger_event("onActionProjectile2", *params)
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
            # Recompute swimming immediately for the new level/position -
            # don't rely solely on the next frame's blanket run() update
            # (see _use_door_link for the same reasoning on link warps).
            self._update_swimming_state()
        except Exception:
            pass

    def _check_level_change(self):
        """Reload the GS1 engine when the player lands in a new level (script
        warp, door, or server-initiated), once that level's NPCs have streamed
        in. warp_to_level clears NPCs, so reloading too early would run nothing."""
        lvl = self.client._current_level_name
        epoch = self.client._plain_level_change_epoch
        if epoch != getattr(self, '_gs1_visual_level_epoch', epoch):
            # NOT a blanket clear: GS2 weapon HUD stores persist across
            # levels (real-client parity — see ClientGS1.drop_level_weapon_
            # layers; the v6 bomber's scripted HUD only repaints on state
            # deltas, so a clear here blanked it forever after the
            # preloader->lobby warp).
            self.gs1.drop_level_weapon_layers()
            # A scripted seteffect curtain is owned by whatever script drew
            # it, and a level change abandons that script (its coroutine dies
            # in gs1.clear()); an uncleared tint would stick forever — e.g.
            # leaving the arena mid-join with the black fade curtain up. The
            # new level's scripts re-apply their own seteffect on
            # playerenters right after the reload.
            self.screen_tint = None
            # A confirmed plain level change ALWAYS needs the full engine
            # reload below. actions.py's _use_door_link pre-stamps _gs1_level
            # after its own (partial) load — it never calls gs1.clear(), so
            # trusting that stamp left the OLD level's NPC scripts loaded and
            # running with their NPC dicts gone (this_obj=None): their
            # showimgs landed in the orphan _weapon_imgs store and kept
            # rendering — the bomber lobby's player-centered subtract smoke
            # followed you down the stairs and blacked out the spar pit.
            # Clearing the stamp forces _reload_level_scripts (idempotent;
            # weapon/NPC playerenters are re-runnable by design).
            self._gs1_level = None
        self._gs1_visual_level_epoch = epoch
        # A reload that had to skip `playerenters` because the board hadn't
        # arrived yet (see _trigger_playerenters) owes the level one: replay
        # the whole reload — it's idempotent by design — now that it has.
        if getattr(self, '_gs1_playerenters_pending', False) and self.gs1.board_ready():
            self._gs1_level = None
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

    def _snapshot_gs2_npc_shapes(self):
        """Collision shapes owned by CURRENT-level GS2 NPCs, taken before
        gs1.clear() wipes the shared shape store.

        GS2 NPCs (v6 bytecode) run setshape/setshape2 exactly once per level
        visit, in onPlayerEnters via ClientGS2.pump_level_events — which the
        frame loop pumps BEFORE _check_level_change triggers this reload (the
        reload additionally waits up to 0.6s for NPCs to stream). gs1.clear()
        then destroyed those shapes + onwall2 blocking cells, and GS2 never
        re-records: its per-level entry event is already consumed, and a
        still-sleeping onPlayerEnters coroutine (the Bomber queue counter
        sleeps 1s right after its setshape2) blocks any replay via the
        active-coroutine guard. Net effect live: no NPC touch, and scripted
        movement walked straight through the counter."""
        gs2 = getattr(self, 'gs2', None)
        keep = {}
        if gs2 is None:
            return keep
        npc_vms = gs2.vms.get('npc', {})
        for nid, geom in self.gs1.shapes.items():
            if nid in npc_vms or str(nid) in npc_vms:
                if isinstance(self._gs2_shape_npc(nid), dict):
                    keep[nid] = geom
        return keep

    def _gs2_shape_npc(self, nid):
        """client.npcs lookup tolerant of a str-keyed VM id (bytecode keys
        keep the id type they arrived with; npc dicts are int-keyed)."""
        npc = self.client.npcs.get(nid)
        if npc is None and isinstance(nid, str):
            try:
                npc = self.client.npcs.get(int(nid))
            except ValueError:
                npc = None
        return npc

    def _restore_gs2_npc_shapes(self, keep):
        """Re-apply a _snapshot_gs2_npc_shapes() snapshot after gs1.clear():
        both the touch-shape store and the derived onwall2 blocking cells."""
        for nid, geom in keep.items():
            npc = self._gs2_shape_npc(nid)
            if not isinstance(npc, dict):
                continue  # despawned between snapshot and restore
            self.gs1.shapes[nid] = geom
            w, h, flags = geom
            self.gs1._update_shape_blocks(nid, npc, w, h, flags)

    def _reload_level_scripts(self, lvl: str):
        """Swap the GS1 engine + per-NPC render state over to the current level."""
        gs2_shapes = self._snapshot_gs2_npc_shapes()
        self.gs1.clear()
        self._restore_gs2_npc_shapes(gs2_shapes)
        # Stale scripted screen tint dies with the old level's scripts (see
        # the epoch-clear in _check_level_change; this also covers reloads
        # that don't come through a plain-level epoch bump).
        self.screen_tint = None
        # Tileset remaps (addtiledef/addtiledef2) PERSIST across level
        # changes (real-client semantics: Bomber v6 sets them once in its
        # preloader); only a script's removetiledefs drops them. What changes
        # per level is which defs APPLY -- each def carries a levelstart
        # prefix the manager re-evaluates here. Levels that want different
        # tiles re-run removetiledefs + addtiledef2 themselves (classic
        # bomber's arena NPC 162 does).
        self.tileset_mgr.set_current_level(self.client._current_level_name)
        self._invalidate_tile_derived_caches()
        self._camera_focus = None   # scripted setfocus dies with its level
        self._load_npc_scripts()
        self._trigger_playerenters()
        self.npc_handler.update_npcs()
        for attr in ('npc_anims', 'npc_effects', 'npc_chat_texts', 'npc_visual',
                     'other_player_visual'):
            cache = getattr(self, attr, None)
            if isinstance(cache, dict):
                cache.clear()
        # Combat effects are level-local (bomb/arrow/thrown-object flight,
        # break bursts) — carrying them across a warp let a bomb armed in the
        # old level keep ticking (and eventually exploding) on top of the
        # new one.
        for attr in ('active_projectiles', 'thrown_objects', 'active_bombs',
                     'break_effects',
                     'leaf_particles', 'water_ripples'):
            effects = getattr(self, attr, None)
            if isinstance(effects, list):
                effects.clear()
        self.visual_x, self.visual_y = self.client.x, self.client.y
        self.world_surface = None
        self._gs1_level = lvl
        self._level_change_pending = None
