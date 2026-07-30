"""Wire GS1 audio, speech, dialogue, animation, warp, and trigger callbacks."""

import os
import time

from ...sprites import strip_tiledef_image

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
            game.npc_chat_texts[npc_id] = (message, time.time())
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
            pass
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
            pass

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
        game._frozen_until = time.time() + max(0.0, float(seconds or 0))

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
            if script and getattr(game, 'gs1', None) is not None:
                is_new = game.gs1.load_weapon(name, script)
                try:
                    if is_new:
                        game.gs1.trigger_event('created', name=f'weapon_{name}')
                    game.gs1.trigger_event('playerenters', name=f'weapon_{name}')
                except Exception:
                    pass
        elif current is None:
            game.client.weapons[name] = {'name': name, 'image': '', 'script': ''}
        if npc_id is not None:
            try:
                game.client.send_weapon_add(npc_id)
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
        now = time.time()
        sent = game._triggeraction_sent
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
            game.client.triggeraction(action, x, y, npc_id)
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
        me = str(getattr(game.client.player, 'id', '') or
                 getattr(game.client.player, 'account', ''))
        if not hasattr(game, '_pending_self_shoots'):
            game._pending_self_shoots = []
        game._pending_self_shoots.append([me, gani] + list(shoot_params))
        try:
            game.client.shoot(gani=gani, params=','.join(shoot_params))
        except Exception:
            pass

    game.gs1.on_play = on_play
    game.gs1.on_stopmusic = on_stopmusic
    # putleaps type,x,y -> debris burst (render_effects owns frames+sound)
    game.gs1.on_putleaps = (lambda leap_type, x, y:
                            game._spawn_leaps(leap_type, x, y))

    # -- scripted combat family (GS1 putbomb/explosions/setbackpal) ----
    # putbomb -> the same active_bombs registry local/remote bombs use
    # (render_effects.py runs the fuse, burst, sound and bush-break).
    def on_putbomb(power, x, y, fuse_s):
        game.active_bombs.append({
            'x': float(x), 'y': float(y), 'time': time.time(),
            'fuse_time': max(0.05, float(fuse_s)),
            'power': max(1, int(power)), 'exploded': False,
            'source': 'script',
        })

    # removebomb (silent pickup) / explodebomb (burst now)
    def on_removebomb(bomb, explode):
        if explode:
            game._detonate_bomb(bomb)
            return
        try:
            game.active_bombs.remove(bomb)
        except ValueError:
            pass

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
    game.gs1.bombs_source = lambda: game.active_bombs
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
            game.local_chat_time = time.time()
            game.client.player.chat = value
        elif code == '#3':
            game.client.send_head_image(value)
        elif code == '#8':
            game.client.send_body_image(value)
        elif code.startswith('#C') and code[2:].isdigit():
            index = int(code[2:])
            colors = list(game.client.player.colors)
            if 0 <= index < game.client._colors_len:
                colors.extend([0] * (game.client._colors_len - len(colors)))
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
                pass

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
