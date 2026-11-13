"""Wire client chat, entity, item, board, file, weapon, and combat callbacks."""

import logging
import os
import re

from reborn_protocol.gs2.compiler import Gs2Compiler
from reborn_protocol.gs2.detect import looks_like_gs2

from ...asset_paths import normalize_asset_name
from ...client_callbacks import emit
from ...gmap_coords import level_origin, world_from_local
from ...packets import PacketID, parse_npcweapondel
from ..constants import CHAT_HISTORY_CAP
from ...logutil import log_swallowed

# Downloaded audio handled as one-shot samples (mixer.Sound). The streaming
# side of the split is SoundManager.MUSIC_EXTS; .ogg deliberately appears only
# there, so a downloaded track keeps going to mixer.music.
SAMPLE_EXTS = ('wav', 'aiff', 'aif', 'flac')

logger = logging.getLogger(__name__)


class Gs2SourceRouter:
    """Per-game record of GS2 source compile attempts and their warnings."""

    def __init__(self):
        self.attempts = {}
        self.warned = set()
        self.compiler = None

    def route(self, game, kind, key, script):
        """Consume GS2 text through the existing bytecode arrival callback.

        True means bytecode is available, so GS1 must skip this source. Failed
        attempts retain their False result so repeated scans still fall back.
        NPC identity permits reloading on respawn.
        """
        identity = (kind, key)
        owner = game.client.npcs.get(key) if kind == 'npc' else None
        previous = self.attempts.get(identity)
        if previous is not None and previous[0] == script and previous[1] is owner:
            return previous[2]
        if not looks_like_gs2(script):
            return False
        source = re.split(r'(?m)^\s*//#CLIENTSIDE[^\n]*(?:\n|$)',
                          script.replace('\xa7', '\n'), maxsplit=1)[-1]
        self.attempts[identity] = (script, owner, False)
        if os.environ.get('PYREBORN_GS2_SOURCE') == '0':
            error = 'source compilation disabled by PYREBORN_GS2_SOURCE=0'
        else:
            compiler = self.compiler
            if compiler is None:
                compiler = self.compiler = Gs2Compiler()
            blob = compiler.compile(source, str(key))
            if blob is not None:
                self.attempts[identity] = (script, owner, True)
                # Match handlers/scripts.py: retain the blob for runtime startup
                # replay, then let ClientGS2._on_bytecode queue it for load_bytecode.
                game.client.gs2_bytecode[kind][key] = blob
                emit(game.client, 'on_gs2_bytecode', kind, key, blob)
                return True
            error = getattr(compiler, 'last_error', '') or 'compilation failed'
        if identity not in self.warned:
            self.warned.add(identity)
            logger.warning('GS2-looking %s %s: %s; running it in the GS1 engine', kind, key,
                           error.splitlines()[0])
        return False


def route_gs2_source(game, kind, key, script):
    return game.gs2_sources.route(game, kind, key, script)


def append_start_message(messages: list, text: str) -> int:
    """Append at most five non-empty initial-message lines to chat.

    Returns the number of lines appended so the caller can advance
    chat.seq (the monotonic append counter the scroll indicator uses).
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    added = [f"[server] {line}" for line in lines[:5]]
    messages.extend(added)
    if len(messages) > CHAT_HISTORY_CAP:
        del messages[:-CHAT_HISTORY_CAP]
    return len(added)


def wire_client_callbacks(game):
    # State for the newer render_effects visuals below - initialized here
    # (this runs once, at the end of GameClient.__init__) rather than in
    # pygame_game.py, which owns the rest of the render-state init.
    game.other_thrown_objects = []   # PLO_THROWCARRIED arcs (other players)
    game._pushaway_velocity = (0.0, 0.0)   # PLO_PUSHAWAY knockback, tiles/sec

    # Let the sound manager fetch sounds it doesn't have, through the same
    # one-shot request path images/ganis use (render_entities.py:1077).
    # Wired here rather than beside the manager's construction because
    # _request_asset needs _requested_assets, built later in __init__; the
    # names preload_common_sounds() wrote off before now are re-requested
    # on their next miss (sounds.py:127-132).
    game.sound_mgr.file_requester = game._request_asset

    send_level_chat = game.client.send_level_chat
    def send_level_chat_with_events(message):
        sent = send_level_chat(message)
        if sent:
            if getattr(game, 'gs1', None) is not None:
                game.gs1.trigger_event('playerchats')
            if getattr(game, 'gs2', None) is not None:
                game.gs2.trigger_event("onPlayerChats")
        return sent
    game.client.send_level_chat = send_level_chat_with_events

    def on_chat(player_id, message):
        game.chat.append(f"[{player_id}] {message}")

    def on_pm(from_id, message):
        # Show received private messages in the chat log, named by sender.
        name = game._player_label(from_id)
        game.chat.append(f"[PM {name}] {message}")

    def _roster_name(info):
        return info.get('nickname') or info.get('account') or "?"

    def on_add_player(pid, info):
        # The server dumps the whole roster on login; only announce joins
        # that arrive after that settles (roster_ready_time, set in run()).
        if game.clock.frame_now() >= game.roster_ready_time:
            game.chat.append(f"-> {_roster_name(info)} entered")

    def on_del_player(pid, info):
        game.chat.append(f"<- {_roster_name(info)} left")

    def on_hurt(attacker_id, damage, damage_type, source_x, source_y):
        was_dead = game.current_anim_name == 'dead'
        state = game.client.player.hurt
        stamp = (state.generation, game.clock.sim_now())
        advanced = state.generation > game.combat_presentation.presented_hurt_generation
        tracked = state.generation > 0 and game.client.auto_respond_hurt and damage > 0
        if (tracked and stamp == game.combat_presentation.presented_hurt_stamp
                and (game.client.player.hearts > 0 or game.current_anim_name == 'dead')):
            return
        game.combat_presentation.presented_hurt_stamp = stamp if advanced and tracked else None
        game.combat_presentation.presented_hurt_generation = state.generation
        # TPlayer.cpp:5771-5779,6574: hurt/death release through the normal throw path.
        if game.client.player.is_carrying():
            game._throw_object()
        if getattr(game.client.player, 'hurt_vector_pending', False):
            from ...hurt import hurt_vector
            if source_x or source_y:
                state.dx, state.dy = hurt_vector(
                    game.client.x - source_x, game.client.y - source_y)
            game.client.player.hurt_vector_pending = False
        now = game.clock.frame_now()
        # Spawn floating damage number at player position
        game.particles.damage_numbers.append({
            'x': game.visual_x,
            'y': game.visual_y - 16,
            'damage': damage,
            'time': game.clock.frame_now(),
            'duration': 1.0,
        })
        # Trigger hurt flash
        game.combat_presentation.hurt(
            now, dead=game.client.player.hearts <= 0)

        # Check for death (hearts already reduced by client.respond_to_hurt)
        if game.client.player.hearts <= 0:
            # TPlayer.cpp:5743-5744: death ends the current action and counter.
            game.client.player.action_mode = 0
            for clear in ('_clear_push_hold', '_clear_grab_state'):
                callback = getattr(game, clear, None)
                if callback is not None:
                    callback()
            if hasattr(game, '_ledge_jump'):
                game._ledge_jump = None
            # Play death sound
            game.sound_mgr.play("dead.wav")
            # Set death animation
            game.player_anim.set_animation("dead", game.client.player.direction)
            game.current_anim_name = "dead"
            # TPlayer.cpp:5753: playerdies runs on NPCs
            # (GServer-v2/bin/docs/scripting-gs1-events.md:196-204).
            gs1 = getattr(game, 'gs1', None)
            if not was_dead and gs1 is not None:
                for npc_id in list(game.client.npcs):
                    gs1.trigger_npc_event(npc_id, 'playerdies')
        else:
            game.sound_mgr.play("hurt.wav")
            game.player_anim.set_animation("hurt", game.client.player.direction, force=True)
            game.current_anim_name = "hurt"

    def on_item(x, y, item_type, removed):
        pass

    def on_explosion(x, y, radius, power):
        game._start_camera_shake(*_wire_to_world(x, y))

    def on_bush_cut(x, y, index):
        game._spawn_leaf_particles(x, y)
        game.world_surface = None

    def on_leaps(leap_type, x, y):
        # TServerLevel.cpp:2850-2867: shared debris and spawn sound.
        game._spawn_leaps(leap_type, x, y)
        game.world_surface = None

    def on_minimap(data: bytes):
        """Handle minimap data from server."""
        game.minimap_data = data
        game._build_minimap_surface()

    def on_ghost_mode(mode: int):
        """Preserve the server's spectator mode."""
        game.ghost_mode = mode

    # Tier 3b: PLO_SERVERTEXT - a text answer from the server (e.g. a
    # gr.getstring()/gettext() reply) - surface it in the chat log like an
    # incoming message so it isn't silently dropped.
    def on_server_text(text: str):
        # The engine's onReceiveText (Login serverlist chat weapon) is a
        # separate subscriber: ClientGS2.attach() listens on the same callback.
        if text:
            game.chat.append(f"[server] {text}")

    def on_start_message(text: str):
        """Put up to five non-empty initial-message lines in chat."""
        game.chat.seq += append_start_message(game.chat.messages, text)

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
            game.chat.seq += append_start_message(
                game.chat.messages, "\n".join(lines))

    def on_file(filename: str, data: bytes):
        """Cache a downloaded asset. Images go to the sprite cache, ganis to
        the gani parser's cache, one-shot samples to the sound cache; a
        music file we were waiting on starts playing once it arrives."""
        filename = normalize_asset_name(filename)
        ext = filename.rsplit('.', 1)[-1]
        if ext in ('png', 'gif', 'bmp', 'mng'):
            game.sprite_mgr.load_bytes(filename, data)
            rewrap = getattr(game, "_rewrap_sign_dialogue", None)
            if rewrap is not None:
                rewrap(filename)
            # A custom tileset image (addtiledef/addtiledef2) just
            # arrived — drop the tile cache so blocks re-render with it
            # instead of the default.
            tm = game.tileset_mgr
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
                game._invalidate_tile_derived_caches()
        elif ext == 'gani':
            # The server streams gani scripts on demand; cache the parsed
            # animation so NPCs/players using it stop falling back to the
            # missing-asset placeholder. Keyed by the bare name (no .gani).
            name = filename[:-5] if filename.lower().endswith('.gani') else filename
            gani = None
            try:
                gani = game.gani_parser.parse_content(
                    data.decode('latin-1'), name)
                game.gani_parser.put_cache(name, gani)
            except Exception:
                log_swallowed(logger)
            else:
                # Request the sheets this gani names NOW. Discovering them
                # from the frame blit fallback instead costs one server
                # round trip per frame/direction: measured on a live
                # server, 43 files took 5.12s that way (~119ms each) on a
                # link that batches at 264 KB/s.
                try:
                    game._prefetch_gani_assets(gani)
                except Exception:
                    log_swallowed(logger)
            # A scripted player gani (GS1 setani -> on_setani below) may
            # have been asked for before it was downloaded; the anim
            # state remembers the ask in requested_name — re-assert it so
            # the pose pops in on arrival (NPCs get this for free from
            # the per-frame render re-assert; the player path is
            # transition-driven).
            anim = getattr(game, 'player_anim', None)
            if (anim is not None and anim.requested_name == name
                    and (anim.gani is None or anim.gani.name != name)):
                try:
                    anim.set_animation(name)
                    game.current_anim_name = name
                except Exception:
                    log_swallowed(logger)
        elif game.sound_mgr.is_music(filename):
            if filename == getattr(game, '_pending_music', None):
                game._pending_music = None
                game.sound_mgr.play_music(filename, data=data)
        elif ext in SAMPLE_EXTS:
            # A server's custom sounds exist nowhere on disk until asked
            # for (`file sounds/*.wav` in foldersconfig), so these bytes
            # are the only copy we will ever get; without this branch they
            # were discarded and the sound stayed silent for the session.
            # Ordered AFTER the is_music test on purpose: mixer.Sound can
            # decode an .ogg too, but a streaming format belongs to
            # mixer.music (sounds.py:285).
            game.sound_mgr.load_bytes(filename, data)

    # Source weapons use the matching engine, including classic GS2 servers
    # that send text instead of a bytecode announcement.
    def on_weapon_add(name, weapon):
        script = weapon.get('script', '')
        if script and route_gs2_source(game, 'weapon', name, script):
            return
        if script and getattr(game, 'gs1', None) is not None:
            is_new = game.gs1.load_weapon(name, script)
            try:
                if is_new:
                    game.gs1.trigger_event('created', name=f'weapon_{name}')
                game.gs1.trigger_event('playerenters', name=f'weapon_{name}')
            except Exception:
                log_swallowed(logger)

    # Forget the old VM attempt when a weapon leaves inventory. A packet
    # listener runs after the inventory handler and before any embedding
    # on_packet hook, which keeps its own slot.
    def on_weapon_del(data):
        name = parse_npcweapondel(data)
        game.gs2_sources.attempts.pop(('weapon', name), None)

    game.client.add_packet_listener(PacketID.PLO_NPCWEAPONDEL, on_weapon_del)

    def _wire_to_world(x, y):
        # Bomb packets are level-local (PLO_BOMBADD/BOMBDEL/EXPLOSION carry
        # the sender's level coordinates); game.active_bombs holds WORLD
        # coordinates on a gmap, like local lays and the lift/throw code.
        if not game.client.in_gmap_segment:
            return x, y
        level = game.client.pending_level_name or game.client.current_level_name
        return world_from_local(game.client.gmap_grid, level, x, y)

    def on_bomb_add(info):
        wx, wy = _wire_to_world(info.get('x', 0.0), info.get('y', 0.0))
        game._add_remote_bomb(dict(info, x=wx, y=wy))

    def on_bomb_exploded(record, cells):
        game._on_client_bomb_exploded(record, cells)

    def on_bomb_del(x, y):
        from ...carrying import BOMB_CODES
        from ...throwing import remote_origin
        from ...liftobjects import LIFT_PROBE
        import math
        # GServer-v2 PlayerClientPackets.cpp:251: BOMBDEL only removes.
        level = game.client.pending_level_name or game.client.current_level_name
        origin_x, origin_y = level_origin(
            game.client.gmap_grid if game.client.in_gmap_segment else None, level)
        game.client.remove_bombs_at(level, x, y)
        position = game.client.bomb_half_tile(x + origin_x, y + origin_y)
        for pid, owner in game.client.players.items():
            if owner.get('carry_sprite', -1) not in BOMB_CODES or owner.get('_carried_bomb'):
                continue
            ox, oy = remote_origin(game.client, owner)
            px, py = owner.get('world_x'), owner.get('world_y')
            px = owner.get('x', 0) + ox if px is None else px
            py = owner.get('y', 0) + oy if py is None else py
            dx, dy = LIFT_PROBE[owner.get('direction', 2)]
            tx, ty = math.floor(px + dx + .0001), math.floor(py + dy + .0001)
            if not (x + origin_x <= tx < x + origin_x + 2 and y + origin_y <= ty < y + origin_y + 2):
                continue
            bomb = next((b for b in game.active_bombs
                         if game.client.bomb_half_tile(b['x'], b['y']) == position
                         and not b.get('exploded')), None)
            if bomb is not None:
                bomb['fuse_remaining'] = max(.05, bomb['time'] + bomb['fuse_time'] - game.clock.sim_now())
                bomb['carried_by'] = pid
                owner['_carried_bomb'] = bomb
                break
        game.active_bombs[:] = [bomb for bomb in game.active_bombs
                               if bomb.get('exploded') or bomb.get('carried_by') is not None
                               or game.client.bomb_half_tile(bomb['x'], bomb['y']) != position]

    def on_arrow_add(info):
        game._add_remote_arrow(info)

    # Tier 1b: a board tile delta arrived - patch just the affected rect
    # into the cached world_surface instead of a full rebuild.
    def on_board_modify(info):
        game._patch_world_surface_for_modify(info)

    # Tier 1d: an extra board layer streamed in/changed - layers are only
    # sent a handful of times per level (not every frame), so a full
    # world_surface rebuild is cheap and simplest here.
    def on_board_layer(layer, x, y, tiles):
        game.world_surface = None

    # PLO_HITOBJECTS keeps the weapon-hit sparks and leaves.
    def on_hit_objects(x, y, power, player_id):
        game._spawn_hit_break_effect(x, y)
        game._spawn_leaf_particles(x, y)

    def on_throwcarried(owner_id):
        from ...throwing import remote_throw
        obj = remote_throw(game.client, owner_id)
        if obj is not None:
            game.other_thrown_objects.append(obj)

    # PLO_FIRESPY - a GS1 firespy/fireball effect from another player's
    # weapon script. Like PLO_THROWCARRIED, the payload is just the owner
    # + power/length (see packets.parse_firespy); feed it into the same
    # active_projectiles pipeline as a local bow shot, tagged 'firespy' so
    # render_effects picks the fireball gani/fallback color instead of
    # the arrow's.
    def on_firespy(info):
        owner = game.client.players.get(info.get('owner_id'))
        if not owner:
            return
        direction = owner.get('direction', 2) or 2
        speed = 10.0
        dx_map = {0: 0, 1: -speed, 2: 0, 3: speed}
        dy_map = {0: -speed, 1: 0, 2: speed, 3: 0}
        x, y = owner.get('x', 0.0), owner.get('y', 0.0)
        game.active_projectiles.append({
            'x': x, 'y': y,
            'dx': dx_map.get(direction, 0), 'dy': dy_map.get(direction, 0),
            'time': game.clock.sim_now(), 'direction': direction, 'gani': 'firespy',
            'max_distance': max(1.0, float(info.get('length', 1) or 1)),
            'start_x': x, 'start_y': y,
        })

    # TClient.cpp:3168-3175: pushaway replaces hurtFly's vector without
    # starting another hurt action or changing HP/immunity.
    def on_pushaway(dx, dy):
        game.client.player.hurt.dx = dx
        game.client.player.hurt.dy = dy

    def on_say2(text):
        game._show_dialogue(text, classic_font=True)

    def on_server_warp(info):
        # FourPlay/quattroplay/src/TServerList.cpp:131-160: the reference
        # client only raises a script event and never connects by itself. The
        # target is named by the game server, so following it would hand this
        # session's account name and password to whatever host it says;
        # the player is asked first (GameClient.offer_server_warp).
        from ...packet_codec.gameplay import validate_server_warp_target
        target = validate_server_warp_target(info)
        if target is None:
            return
        gs2 = getattr(game, 'gs2', None)
        if gs2 is not None:
            gs2.trigger_weapon_event(
                'StartScript_Connector', 'onServerWarp',
                target['name'], target['host'], target['port'])
        game.offer_server_warp(info)

    def on_server_warp_blocked(destination):
        game.show_hud_notice(
            "A script's server move was blocked. F8 opens the server browser.")

    game.client.on_server_warp = on_server_warp
    game.client.on_server_warp_blocked = on_server_warp_blocked
    pending = getattr(game.client, 'server_warp_info', None)
    if isinstance(pending, dict):
        on_server_warp(pending)
    game.client.on_chat = on_chat
    game.client.on_say2 = on_say2
    game.client.on_pm = on_pm
    game.client.on_add_player = on_add_player
    game.client.on_del_player = on_del_player
    game.client.on_hurt = on_hurt
    game.client.on_item = on_item
    game.client.on_explosion = on_explosion
    game.client.on_bush_cut = on_bush_cut
    game.client.on_leaps = on_leaps
    game.client.on_minimap = on_minimap
    game.client.on_ghost_mode = on_ghost_mode
    if hasattr(game.client, 'on_bomb_del'):
        game.client.on_bomb_del = on_bomb_del
    if hasattr(game.client, 'on_bomb_add'):
        game.client.on_bomb_add = on_bomb_add
    game.client.on_bomb_exploded = on_bomb_exploded
    if hasattr(game.client, 'on_arrow_add'):
        game.client.on_arrow_add = on_arrow_add
    if hasattr(game.client, 'on_board_modify'):
        game.client.on_board_modify = on_board_modify
    if hasattr(game.client, 'on_board_layer'):
        game.client.on_board_layer = on_board_layer
    if hasattr(game.client, 'on_server_text'):
        game.client.on_server_text = on_server_text
    if hasattr(game.client, 'on_start_message'):
        game.client.on_start_message = on_start_message
    if hasattr(game.client, 'on_rpg_window'):
        game.client.on_rpg_window = on_rpg_window
    if hasattr(game.client, 'on_hit_objects'):
        game.client.on_hit_objects = on_hit_objects
    if hasattr(game.client, 'on_throwcarried'):
        game.client.on_throwcarried = on_throwcarried
    if hasattr(game.client, 'on_firespy'):
        game.client.on_firespy = on_firespy
    if hasattr(game.client, 'on_pushaway'):
        game.client.on_pushaway = on_pushaway
    # A relayed projectile (another player's shoot) — fire actionprojectile2
    # so weapons react (Bomber Arena's room system is built on this). #p(n)
    # maps to event args: per GServer-v2 mc_p, #p(0) is the first param after
    # the event name. The arena room-join reads the Bomb.Queue tag at #p(2)
    # and the room+account at #p(3), so the two leading slots are the shooter
    # and gani. NOTE: this prefix is inferred, not yet confirmed against a
    # real 2-player relayed packet — tune once one is captured.
    def on_projectile(info):
        if getattr(game, 'gs1', None) is None:
            return
        csv = info.get('params', '') or ''
        params = csv.split(',') if csv else []
        shooter = str(info.get('shooter', ''))
        gani = info.get('gani', '') or ''
        args = [shooter, gani] + params
        game.gs1.fire_projectile(args)
        # GS2 weapons take the same event; params[i] == GS1's #p(i)
        # (verified against Bomber v6's -validation: params[2] is the
        # Bomb.Queue tag, params[3] the room+account).
        gs2 = getattr(game, 'gs2', None)
        if gs2 is not None:
            gs2.trigger_event("onActionProjectile2", *args)

    # A server flag arrived (PLO_FLAGSET) — route it into the right GS1
    # scope: "client."/"clientr." are the player's persisted account flags
    # (PetSys's client.pet chocobo/squirrel selection), the rest are
    # globals (bomber's room roster server.bombrm_NN).
    def on_flag(name, value):
        gs1 = getattr(game, 'gs1', None)
        if gs1 is not None:
            gs1.recv_flag(name, value)

    # PLO_FLAGDEL: the server unsets flags too (bomber empties its queue
    # roster this way) — without this, scripts keep reading stale values.
    def on_flag_del(name):
        gs1 = getattr(game, 'gs1', None)
        if gs1 is not None:
            gs1.recv_flag_del(name)

    game.client.on_file = on_file
    game.client.on_weapon_add = on_weapon_add
    game.client.on_projectile = on_projectile
    game.client.on_flag = on_flag
    game.client.on_flag_del = on_flag_del
    # flags received before the GS1 engine existed
    if getattr(game, 'gs1', None) is not None:
        for _fn, _fv in (game.client.global_flags or {}).items():
            game.gs1.recv_flag(_fn, _fv)
