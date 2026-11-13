"""Wire GS1 audio, speech, dialogue, animation, warp, and trigger callbacks."""

import os

from ...colors_width import colors_len_in_force
from ...flyingobjects import NOT_BOUNCING
from ...sprites import strip_tiledef_image
from .client_callbacks import route_gs2_source
import logging
from ...logutil import log_swallowed
logger = logging.getLogger(__name__)

# A script loop can spawn thrown objects, bombs and flying objects faster
# than they expire (`timeout = 0.05` re-arming throwcarry), so each live list
# refuses new entries at this size instead of growing without bound.
MAX_SCRIPT_OBJECTS = 256


def wire_gs1_callbacks(game):
    # action string -> last-sent time, to throttle repeated triggeractions.
    game._triggeraction_sent = {}
    # Play sound/music callback (routes MIDI to streaming music).
    def on_play(sound_name):
        game._play_audio(sound_name)

    # stopmidi/stopsong — stop streaming music and clear the dedup name so a
    # later play (even of the same track) starts fresh.
    def on_stopmusic():
        game.sound_mgr.stop_music()
        game._current_music_name = None
        game._pending_music = None

    # Say/chat callback - sets NPC speech bubble. Fed by the GS1
    # say/message command AND by a GS2 NPC's `this.chat = ...` write
    # (gs2_client._NpcThisObject.set). Empty text clears the bubble
    # immediately (setting chat to "" is how scripts stop speaking)
    # rather than letting the stale bubble ride out its timeout.
    def on_say(npc_id, message):
        if message:
            game.npc_chat_texts[npc_id] = (message, game.clock.sim_now())
        else:
            game.npc_chat_texts.pop(npc_id, None)

    def on_say2(text):
        game._show_dialogue(text, classic_font=True)

    # Show message callback (dialogue box)
    def on_message(text):
        game._show_dialogue(text)

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
        game._scripted_player_ani = base
        try:
            direction = int(game.client.player.direction) & 3
        except (TypeError, ValueError):
            direction = 2
        try:
            game.player_anim.set_animation(base, direction,
                                           params=joined.split(',')[1:])
            game.current_anim_name = base
        except Exception:
            log_swallowed(logger)
        # The scripted gani may not be downloaded yet (bomber's
        # sen_piano_idle) — fetch it through the once-only asset path;
        # the on_file gani branch above re-asserts it when it lands.
        try:
            gani = game.gani_parser.parse(base)
            if gani is None:
                game._request_asset(base + '.gani')
            else:
                game._prefetch_gani_assets(gani)
        except Exception:
            log_swallowed(logger)

    # Set effect callback (Tier 3d) - fullscreen tint drawn under the HUD,
    # over the world (see game/render_effects.py _render_screen_tint,
    # called from the main render loop). r,g,b,a are 0..1 GS1 multipliers,
    # same convention as changeimgcolors/setcoloreffect elsewhere.
    def on_seteffect(r, g, b, a):
        def c255(v):
            return max(0, min(255, int(float(v) * 255)))
        if a and c255(a) > 0:
            game.screen_tint = {'r': c255(r), 'g': c255(g), 'b': c255(b), 'a': c255(a)}
        else:
            game.screen_tint = None

    # freezeplayer N — lock local input for N seconds (NPC dialogue, etc).
    def on_freezeplayer(seconds):
        game._frozen_until = game.clock.sim_now() + max(0.0, float(seconds or 0))

    # toweapons <name> converts a level NPC into a local weapon and asks the
    # server to persist the grant. Weapon callers retain name-only behavior.
    def on_toweapons(name, npc_id=None, script=None, image=None):
        if not name:
            return
        current = game.client.weapons.get(name)
        if npc_id is not None and (current is None or not current.get('script')):
            script = script or ''
            game.client.weapons[name] = {
                'name': name, 'image': image or '', 'script': script,
            }
            if (script and not route_gs2_source(game, 'weapon', name, script)
                    and getattr(game, 'gs1', None) is not None):
                is_new = game.gs1.load_weapon(name, script)
                try:
                    if is_new:
                        game.gs1.trigger_event('created', name=f'weapon_{name}')
                    game.gs1.trigger_event('playerenters', name=f'weapon_{name}')
                except Exception:
                    log_swallowed(logger)
        elif current is None:
            game.client.weapons[name] = {'name': name, 'image': '', 'script': ''}
        if npc_id is not None:
            try:
                game.client.send_weapon_add(npc_id)
            except Exception:
                log_swallowed(logger)

    # setminimap img,txt,... — remember the minimap source + fetch the file.
    # Via _request_asset (not raw request_file) so it's requested once per
    # session: setminimap re-runs on every level (re-)entry playerenters,
    # and re-requested the same files (no-shield.png/bombarena_map.txt on
    # bomber) on each re-entry.
    def on_setminimap(args):
        for a in args:
            if isinstance(a, str) and '.' in a:
                game._request_asset(a)

    # setlevel2 / serverwarp — authoritative in Reborn. Record it; the game
    # loop performs the warp between events (see _process_pending_warp).
    def on_warp(level, x, y):
        game._pending_gs1_warp = (level, x, y)

    # triggeraction x,y,action,... — forward to the server. This is how an
    # arena adds its gameplay weapons (gr.addweapon,-arenaSYS,-arenaGUI).
    # THROTTLE duplicates: scripts like the arena's NPC 162 do
    # `while(!hasweapon(X)) triggeraction gr.addweapon,X` — if the server
    # never pushes X, that loop fires the same action endlessly and floods
    # the server. Send a given action at most once per 5s.
    def on_triggeraction(x, y, action, npc_id):
        sent = game._triggeraction_sent
        if action in sent and not game.clock.passed(sent[action], 5.0):
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
        sent[action] = game.clock.sim_now()
        if os.environ.get("PYREBORN_DEBUG"):
            import sys
            print(f"[trigger] -> server: {action!r}", file=sys.stderr)
        try:
            game.client.triggeraction(action, x, y, npc_id)
        except Exception:
            log_swallowed(logger)

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
        me = str(getattr(game.client.player, 'id', '') or
                 getattr(game.client.player, 'account', ''))
        if not hasattr(game, '_pending_self_shoots'):
            game._pending_self_shoots = []
        game._pending_self_shoots.append([me, gani] + list(shoot_params))
        try:
            game.client.shoot(gani=gani, params=','.join(shoot_params))
        except Exception:
            log_swallowed(logger)

    game.gs1.on_play = on_play
    game.gs1.on_stopmusic = on_stopmusic
    # putleaps type,x,y -> debris burst (render_effects owns frames+sound)
    game.gs1.on_putleaps = (lambda leap_type, x, y:
                            game._spawn_leaps(leap_type, x, y))

    # throwcarry on a character NPC (gs1_client._cmd_throwcarry): launch what it
    # carried one tile ahead of itself with the player's throw arc, one tick
    # short (TServerPlayer::throwObject(1), TServerPlayer.cpp:1054-1092:
    # start offset flyd[dir] * 1, range 9 - 1 ticks).
    def on_throwcarry(npc, code):
        from ...carrying import BOMB_CODES
        from ...throwing import carry_code, carry_object, make_throw, THROW_TICKS
        if code in BOMB_CODES:
            carried = ('bomb', ())
        else:
            carried = carry_object(code)
        if carried is None:
            return
        x = float(npc.get('world_x', npc.get('x', 0)) or 0)
        y = float(npc.get('world_y', npc.get('y', 0)) or 0)
        try:
            direction = int(npc.get('direction', 2)) & 3
        except (TypeError, ValueError):
            direction = 2
        # TInitStatics.cpp flyd: (x, sprite y, ground y) per facing
        flyd = ((0.0, -0.8, -1.0), (-1.0, 0.2, 0.0),
                (0.0, 1.2, 1.0), (1.0, 0.2, 0.0))[direction]
        kind, tiles = carried
        if kind == 'bomb':
            # a thrown bomb keeps ticking and lands as a level bomb (a script
            # `putbomb`-style bomb: the NPC's bag is not the player's)
            # TServerNPCProperties.cpp:985-1017: sprites 0x41/0x42 give power 1,
            # 0x141 (superbomb) 2, 0x15b/0x15c (jolt bombs) 3. `code` is the
            # DECODED carry value, so the sprite ids go through carry_code too.
            power = {carry_code(0x141): 2, carry_code(0x15b): 3,
                     carry_code(0x15c): 3}.get(code, 1)
            if len(game.active_bombs) >= MAX_SCRIPT_OBJECTS:
                return
            bomb = {'x': x, 'y': y, 'time': game.clock.sim_now(), 'fuse_time': 3.0,
                    'fuse_remaining': 3.0, 'power': power, 'exploded': False,
                    'source': 'script', 'in_flight': True}
            obj = make_throw(x, y, direction, 'bomb', ())
            obj['bomb'] = bomb
            target = game.thrown_objects
        else:
            obj = make_throw(x, y, direction, kind, tiles, owner_id=0)
            target = game.other_thrown_objects
        if len(target) >= MAX_SCRIPT_OBJECTS:
            return
        obj['x'] += flyd[0]
        obj['y'] += flyd[2]
        obj['landing_tick'] = THROW_TICKS - 1
        if kind == 'bomb':
            game.active_bombs.append(obj['bomb'])
        target.append(obj)

    game.gs1.on_throwcarry = on_throwcarry

    # shootfireblast / shootnuke: a flying object that travels one tile per
    # 20 Hz tick, like an arrow (putFlyingObject speed 1.0,
    # TServerNPCProperties.cpp:112-150). game/flying.py applies the official
    # hit rules each tick: the local player (level NPCs' shots only), the NPC
    # under it (`wasshot`), and walls plus an explosion for power > 1.
    # 'from_player' is the reference's from == 1, a weapon script's shot that
    # never hurts its own player (TServerNPCProperties.cpp:155-163,
    # TServerFlying.cpp:127). The GS1 engine runs `shootfireblast` only for a
    # script that has an NPC dict, so every queued shot is a level NPC's.
    def on_flying(x, y, direction, power):
        if len(game.active_projectiles) >= MAX_SCRIPT_OBJECTS:
            return
        step = game.client.ARROW_SPEED
        dx, dy = ((0, -step), (-step, 0), (0, step), (step, 0))[direction]
        game.active_projectiles.append({
            'x': x, 'y': y, 'dx': dx, 'dy': dy, 'time': game.clock.sim_now(),
            'direction': direction, 'gani': {2: 'fireblast', 3: 'nukeshot'}[power],
            'max_distance': game.client.ARROW_MAX_DISTANCE,
            'start_x': x, 'start_y': y, 'source': 'script',
            'flying': True, 'power': power, 'from_player': False,
            'lx': x, 'ly': y, 'tick_acc': 0.0, 'bounce': NOT_BOUNCING,
        })

    game.gs1.on_flying = on_flying

    # -- scripted combat family (GS1 putbomb/explosions/setbackpal) ----
    # putbomb -> the same active_bombs registry local/remote bombs use
    # (render_effects.py runs the fuse, burst, sound and bush-break).
    def on_putbomb(power, x, y, fuse_s):
        game.active_bombs.append({
            'x': float(x), 'y': float(y), 'time': game.clock.sim_now(),
            'fuse_time': max(0.05, float(fuse_s)),
            'power': max(1, int(power)), 'exploded': False,
            'source': 'script',
        })
        game._client_bomb_record(game.active_bombs[-1])

    # removebomb (silent pickup) / explodebomb (burst now)
    def on_removebomb(bomb, explode):
        if explode:
            game._detonate_bomb(bomb)
            return
        position = game.client.bomb_half_tile(bomb['x'], bomb['y'])
        game.active_bombs[:] = [b for b in game.active_bombs
                                if b.get('exploded')
                                or game.client.bomb_half_tile(b['x'], b['y']) != position]

    # putexplosion's presentation half (the damage/washit/wire half is
    # client-level, gs1_client._spawn_explosion): boom + shake + bushes.
    def on_putexplosion(power, radius, x, y):
        game.sound_mgr.play("explode.wav")
        game._start_camera_shake(x, y)
        game._break_bushes_in_blast(x, y, max(1, int(power)))

    def on_setbackpal(image):
        image = (image or "").strip()
        if not image:
            return
        changed = game.tileset_mgr.set_backpal(image)
        # pal files are server assets (GTA's underwaterpal.png & co);
        # _request_asset dedupes the fetch across the per-level re-issues.
        if not game.sprite_mgr.has_sheet(image):
            game._request_asset(image)
        if changed:
            game._invalidate_tile_derived_caches()

    game.gs1.on_putbomb = on_putbomb
    game.gs1.on_removebomb = on_removebomb
    game.gs1.on_putexplosion = on_putexplosion
    game.gs1.on_setbackpal = on_setbackpal
    # bombs[] index order = the shell's placement-ordered registry
    def bombs_source():
        for bomb in game.active_bombs:
            if not bomb.get('exploded') and not bomb.get('discarded'):
                game._client_bomb_record(bomb)
        return game.active_bombs
    game.gs1.bombs_source = bombs_source
    game.gs1.on_say = on_say
    game.gs1.on_say2 = on_say2
    game.gs1.on_setani = on_setani
    game.gs1.on_message = on_message
    game.gs1.on_freezeplayer = on_freezeplayer
    game.gs1.on_toweapons = on_toweapons
    game.gs1.on_setminimap = on_setminimap

    # setfocus/resetfocus — scripted camera target (splash/cutscenes).
    # Consumed by render.py's per-frame centering; cleared on level
    # reload (scripts re-issue it on playerenters if they still want it).
    def on_setfocus(x, y):
        game._camera_focus = None if x is None else (float(x), float(y))
    game.gs1.on_setfocus = on_setfocus
    game.gs1.on_seteffect = on_seteffect
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
            game.local_chat_text = value
            game.local_chat_time = game.clock.sim_now()
            game.client.player.chat = value
        elif code == '#3':
            game.client.send_head_image(value)
        elif code == '#8':
            game.client.send_body_image(value)
        elif code.startswith('#C') and code[2:].isdigit():
            index = int(code[2:])
            colors = list(game.client.player.colors)
            width = colors_len_in_force(game.client)
            if 0 <= index < width:
                colors.extend([0] * (width - len(colors)))
                colors[index] = int(float(value))
                game.client.send_colors(colors)
        elif code in _PLAYER_PROP:
            setattr(game.client.player, _PLAYER_PROP[code], value)
        # other codes (#P1-#P30 gattribs, ...) not modelled yet — ignore

    # Point the tileset manager at custom sheets, downloading them if
    # needed, so the board renders with the active definitions.
    def on_tiledef(kind, image, levelstart="", x=0, y=0):
        if kind is None:
            if game.tileset_mgr.clear_tiledefs(image or ""):
                game._invalidate_tile_derived_caches()
            return
        image = strip_tiledef_image(image)
        if kind == "full":
            # addtiledef: whole-tileset replacement sheet. For "full"
            # the x slot carries the def's tile TYPE (0 classic,
            # 1/2 new-world, 5 none), which also picks the type table.
            game.tileset_mgr.set_full_tiledef(image, levelstart, x)
        else:
            game.tileset_mgr.set_tiledef(image, levelstart, x, y)
        # tileset_mgr's tile_cache is cleared above, but the baked
        # per-segment surfaces in render_world.py's _segments() cache
        # are keyed off tiles_id/layers_snapshot only - a tiledef swap
        # doesn't touch either, so they'd keep returning stale bakes
        # from the old tileset. Force a full rebuild.
        game._invalidate_tile_derived_caches()
        if not game.sprite_mgr.has_sheet(image):
            try:
                game.client.request_file(image)
            except Exception:
                log_swallowed(logger)

    game.gs1.on_warp = on_warp
    game.gs1.on_triggeraction = on_triggeraction
    game.gs1.on_shoot = on_shoot
    game.gs1.on_setplayerprop = on_setplayerprop
    game.gs1.on_tiledef = on_tiledef

    # #m / replaceani wiring: scripts read the player's CURRENT ani via #m
    # (Bomber's stairs NPC gates its slowdown on it), so the engine needs
    # our live logical anim name; and our anim state + outgoing gani prop
    # substitute any `replaceani` mapping (walk -> eye_bomber_walk0 etc.)
    # like the real client does.
    game.gs1.player_ani_source = lambda: getattr(game, "current_anim_name", "")
    game.player_anim.name_resolver = game.gs1.resolve_ani
    game.client.ani_resolver = game.gs1.resolve_ani

    # Script tile probes (onwall/onwater/tiletype) must read the same
    # board our own collision does. CollisionMixin._get_tile_at resolves
    # a WORLD coordinate through the gmap grid to the owning segment;
    # (guarded: unit harnesses mix SetupMixin in without CollisionMixin,
    # and the GS1 host's own single-level fallback is right for them.)
    game.gs1.tile_source = getattr(game, "_get_tile_at", None)

    # Image-NPC footprints (blocking + touch) size themselves off the
    # actual art and are refined by per-pixel transparency where it is
    # loaded — see gs1_client.ClientGS1.npc_blocks_at for the
    # oracle-derived rule. Without the opaque probe a mostly-transparent
    # decoration (glows, lamp halos) would wall off its whole rect.
    sprite_mgr = getattr(game, "sprite_mgr", None)
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

        game.gs1.image_size_source = _npc_image_size
        game.gs1.image_opaque_source = _npc_image_opaque

    # A sword swing connected with a level NPC (client.py _sword_hit_npcs):
    # fire `washit` on it, same as the real client (scripting-gs1-events.md).
    game.client.on_sword_hit_npc = (
        lambda npc_id: game.gs1.trigger_npc_event(npc_id, "washit"))

    # Route NPC touch events through the shared GS1 engine, which runs the
    # script (including its `play`/`triggeraction`/etc. side effects via the
    # gs1.on_* callbacks above). The handler only does collision detection.
    if getattr(game, "npc_handler", None) is not None:
        def _route_touch(npc_id, npc_data):
            game.gs1.trigger_npc_event(npc_id, "playertouchsme")
            # GS2 NPCs (v6 servers stream bytecode) take the same touch.
            # gs2 is created after this callback is wired (GameClient
            # __init__ order), hence the getattr.
            gs2 = getattr(game, "gs2", None)
            if gs2 is not None:
                gs2.trigger_npc_event(npc_id, "onPlayerTouchsMe")
        game.npc_handler.on_playertouchsme = _route_touch
        # The handler reads collision shapes the engine records on setshape.
        game.npc_handler.gs1 = game.gs1
        # Drop a despawned NPC's shape/script so its ghost can't keep
        # firing playertouchsme from the old tile, and clear its render
        # caches.
        game.client.on_npc_del = game._on_npc_del
