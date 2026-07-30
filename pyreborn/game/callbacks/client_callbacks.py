"""Wire client chat, entity, item, board, file, weapon, and combat callbacks."""

import time

from ...asset_paths import normalize_asset_name
from ..constants import CHAT_HISTORY_CAP

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
        game._append_chat(f"[{player_id}] {message}")

    def on_pm(from_id, message):
        # Show received private messages in the chat log, named by sender.
        name = game._player_label(from_id)
        game._append_chat(f"[PM {name}] {message}")

    def _roster_name(info):
        return info.get('nickname') or info.get('account') or "?"

    def on_add_player(pid, info):
        # The server dumps the whole roster on login; only announce joins
        # that arrive after that settles (roster_ready_time, set in run()).
        if time.time() >= game.roster_ready_time:
            game._append_chat(f"-> {_roster_name(info)} entered")

    def on_del_player(pid, info):
        game._append_chat(f"<- {_roster_name(info)} left")

    def on_hurt(attacker_id, damage, damage_type, source_x, source_y):
        now = time.monotonic()
        # Spawn floating damage number at player position
        game.damage_numbers.append({
            'x': game.visual_x,
            'y': game.visual_y - 16,
            'damage': damage,
            'time': time.time(),
            'duration': 1.0,
        })
        # Trigger hurt flash
        game.combat_presentation.hurt(
            now, dead=game.client.player.hearts <= 0)

        # Check for death (hearts already reduced by client.respond_to_hurt)
        if game.client.player.hearts <= 0:
            # Play death sound
            game.sound_mgr.play("dead.wav")
            # Set death animation
            game.player_anim.set_animation("dead", game.client.player.direction)
        else:
            game.sound_mgr.play("hurt.wav")

    def on_item(x, y, item_type, removed):
        pass

    def on_explosion(x, y, radius, power):
        game._start_camera_shake(x, y)

    def on_minimap(data: bytes):
        """Handle minimap data from server."""
        game.minimap_data = data
        game._build_minimap_surface()

    def on_ghost_mode(enabled: bool):
        """Handle ghost mode toggle."""
        game.ghost_mode = enabled

    # Tier 3b: PLO_SERVERTEXT - a text answer from the server (e.g. a
    # gr.getstring()/gettext() reply) - surface it in the chat log like an
    # incoming message so it isn't silently dropped.
    def on_server_text(text: str):
        if text:
            game._append_chat(f"[server] {text}")
        # This assignment replaces the hook ClientGS2.attach() installed
        # (attach runs before _setup_callbacks), so forward the engine
        # event explicitly: onReceiveText drives the Login serverlist
        # chat weapon.
        gs2 = getattr(game, 'gs2', None)
        if gs2 is not None:
            gs2.handle_server_text(text)

    def on_start_message(text: str):
        """Put up to five non-empty initial-message lines in chat."""
        game.chat_seq += append_start_message(game.chat_messages, text)

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
            game.chat_seq += append_start_message(
                game.chat_messages, "\n".join(lines))

    def on_file(filename: str, data: bytes):
        """Cache a downloaded asset. Images go to the sprite cache, ganis to
        the gani parser's cache, one-shot samples to the sound cache; a
        music file we were waiting on starts playing once it arrives."""
        filename = normalize_asset_name(filename)
        ext = filename.rsplit('.', 1)[-1]
        if ext in ('png', 'gif', 'bmp', 'mng'):
            game.sprite_mgr.load_bytes(filename, data)
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
                pass
            else:
                # Request the sheets this gani names NOW. Discovering them
                # from the frame blit fallback instead costs one server
                # round trip per frame/direction: measured on a live
                # server, 43 files took 5.12s that way (~119ms each) on a
                # link that batches at 264 KB/s.
                try:
                    game._prefetch_gani_assets(gani)
                except Exception:
                    pass
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
                    pass
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

    # A weapon arrived (gr.addweapon, e.g. -arenaSYS/-arenaGUI on arena
    # entry): load it into the GS1 engine and fire its playerenters so it
    # activates immediately, like a real client adding a weapon.
    def on_weapon_add(name, weapon):
        script = weapon.get('script', '')
        if script and getattr(game, 'gs1', None) is not None:
            is_new = game.gs1.load_weapon(name, script)
            try:
                if is_new:
                    game.gs1.trigger_event('created', name=f'weapon_{name}')
                game.gs1.trigger_event('playerenters', name=f'weapon_{name}')
            except Exception:
                pass

    def on_bomb_add(info):
        game._add_remote_bomb(info)

    def on_bomb_del(x, y):
        game._detonate_bomb_at(x, y)

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

    # PLO_HITOBJECTS - a player's sword/weapon connected with a bush/pot/
    # etc; spawn the same break/spark burst a thrown object landing uses
    # (see render_effects._spawn_hit_break_effect).
    def on_hit_objects(x, y, power, player_id):
        game._spawn_hit_break_effect(x, y)
        game._spawn_leaf_particles(x, y)

    # PLO_THROWCARRIED - another player threw whatever they were
    # carrying. The packet only names the owner (see
    # packets.parse_throwcarried), so look up their last known
    # position/direction and launch a generic thrown-arc from there (see
    # render_effects._update_and_render_other_thrown / on init below).
    def on_throwcarried(owner_id):
        owner = game.client.players.get(owner_id)
        if not owner:
            return
        direction = owner.get('direction', 2) or 2
        ddx, ddy = game._facing_delta(direction)
        x, y = owner.get('x', 0.0), owner.get('y', 0.0)
        z0 = 2.75
        game.other_thrown_objects.append({
            'x': x, 'y': y + 1.0,
            'z': z0, 'z0': z0,
            'dx': ddx, 'dy': ddy,
            'speed': 20.0, 'dist': 0.0, 'range': 16.0,
            'colors': game.BREAK_COLORS['bush'],
        })

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
            'time': time.time(), 'direction': direction, 'gani': 'firespy',
            'max_distance': max(1.0, float(info.get('length', 1) or 1)),
            'start_x': x, 'start_y': y,
        })

    # PLO_PUSHAWAY (packet 38) - a knockback impulse. Queued here and
    # applied/decayed per-frame in render_effects._apply_pushaway (see its
    # docstring for the conservative-decode note).
    def on_pushaway(dx, dy):
        vx, vy = game._pushaway_velocity
        game._pushaway_velocity = (vx + dx, vy + dy)

    def on_say2(text):
        game._show_dialogue(text, classic_font=True)

    game.client.on_chat = on_chat
    game.client.on_say2 = on_say2
    game.client.on_pm = on_pm
    game.client.on_add_player = on_add_player
    game.client.on_del_player = on_del_player
    game.client.on_hurt = on_hurt
    game.client.on_item = on_item
    game.client.on_explosion = on_explosion
    game.client.on_minimap = on_minimap
    game.client.on_ghost_mode = on_ghost_mode
    if hasattr(game.client, 'on_bomb_del'):
        game.client.on_bomb_del = on_bomb_del
    if hasattr(game.client, 'on_bomb_add'):
        game.client.on_bomb_add = on_bomb_add
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
