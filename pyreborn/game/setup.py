"""SetupMixin — Asset paths, client callbacks, GS1 callbacks, NPC script bootstrap.

Split from pygame_game.py; methods operate on the GameClient instance."""

import time

from pathlib import Path
from typing import List, Optional

from .. import asset_paths
from .callbacks import wire_client_callbacks, wire_gs1_callbacks
from .callbacks.client_callbacks import SAMPLE_EXTS, append_start_message
from .constants import PACKAGE_DIR, CHAT_HISTORY_CAP




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
        wire_client_callbacks(self)
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
        wire_gs1_callbacks(self)

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
