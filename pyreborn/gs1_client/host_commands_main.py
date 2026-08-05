from __future__ import annotations

import logging
import math

from reborn_protocol.coords import world_to_local
from reborn_protocol.gs1.values import to_num, to_str

from ..sprites import REBORN_PALETTE
from .objects import _BADDY_DEFAULT_IMAGE, _BADDY_DEFAULT_POWER, _baddy_type_from_name, _color_name, _current_baddies, _item_ids, _push_dir
from .registry import _FALL_THROUGH, _GS1_MAIN_COMMANDS, _gs1_command



logger = logging.getLogger(__name__)


class MainCommandsMixin:
    # -- _GS1_MAIN_COMMANDS -------------------------------------------------

    @_gs1_command(_GS1_MAIN_COMMANDS, "destroy")
    def _cmd_destroy_weapon(self, name, args, ctx, imgs):
        # A weapon's destroy removes the weapon client-side like the real
        # client: drop its layers AND its program + registry entry, so a later
        # level's playerenters can't resurrect it (_load_weapon_scripts
        # re-loads every client.weapons entry on each level change — the
        # arena weapon's join-curtain branch otherwise re-fired in every
        # non-lobby level, e.g. the spar pit, painting a stuck black
        # seteffect + "Joining..." caption). The bomber re-grants weapons via
        # `triggeraction gr.addweapon,...` whenever a level wants them back
        # (lobby NPC 59, arena NPC 160), which re-streams the script fresh.
        # The currently-running event keeps executing (references are held);
        # only future loads/events stop.
        rt = self.rt
        if imgs is None:
            return _FALL_THROUGH
        imgs.clear()
        key = getattr(ctx, "_prog_key", None)
        if key is not None and str(key).startswith("weapon_"):
            rt._progs.pop(key, None)
            rt.scripts.pop(key, None)
            rt._weapon_timeouts.pop(key, None)
            rt._weapon_imgs.pop(key, None)
            wname = str(key)[len("weapon_"):]
            try:
                if rt.client is not None:
                    # delete_weapon drops the local registry entry AND
                    # tells the server (PLI_NPCWEAPONDEL) — otherwise the
                    # account keeps the weapon and re-streams it at next
                    # login, re-firing this whole lifecycle.
                    rt.client.delete_weapon(wname)
            except Exception:
                pass

    @_gs1_command(_GS1_MAIN_COMMANDS, "setimgpart")
    def _cmd_setimgpart(self, name, args, ctx, imgs):
        # setimgpart name,x,y,w,h — show only a sub-rect of the sheet. Without
        # the rect the renderer blits the entire sheet (e.g. all of pics1.png).
        npc = ctx.this_obj
        if not (isinstance(npc, dict) and len(args) >= 5):
            return _FALL_THROUGH
        npc["image"] = to_str(args[0])
        npc["imagepart"] = (int(to_num(args[1])), int(to_num(args[2])),
                            int(to_num(args[3])), int(to_num(args[4])))

    @_gs1_command(_GS1_MAIN_COMMANDS, "setimg", "setgif")
    def _cmd_setimg(self, name, args, ctx, imgs):
        # set the whole image; clear any prior sub-rect
        npc = ctx.this_obj
        if not (isinstance(npc, dict) and args):
            return _FALL_THROUGH
        npc["image"] = to_str(args[0])
        npc.pop("imagepart", None)

    @_gs1_command(_GS1_MAIN_COMMANDS, "message", "say")
    def _cmd_say(self, name, args, ctx, imgs):
        rt, npc = self.rt, ctx.this_obj
        if name == "say" and args:
            # `say index` displays LEVEL SIGN <index>'s text in the sign
            # dialogue, exactly like reading that sign (the lexer types the
            # arg as an expression - _tables.py 'say': 'E' - vs `message`'s
            # string). We used to alias it to `message` and paint the raw
            # index as a chat bubble. Out-of-range index shows nothing.
            sign_text = rt.sign_text_by_index(args[0])
            if sign_text is not None:
                if rt.on_say2:
                    rt.on_say2(sign_text)
                return
            if isinstance(args[0], (int, float)):
                return      # numeric but no such sign: nothing to show
            # non-numeric `say` (sloppy scripts): keep the bubble fallback
        text = to_str(args[0]) if args else ""
        if isinstance(npc, dict):
            npc["message"] = text
        if rt.on_say:
            rt.on_say(getattr(ctx, "_npc_id", 0), text)

    @_gs1_command(_GS1_MAIN_COMMANDS, "say2")
    def _cmd_say2(self, name, args, ctx, imgs):
        text = to_str(args[0]) if args else ""
        if self.rt.on_say2:
            self.rt.on_say2(text)

    @_gs1_command(_GS1_MAIN_COMMANDS, "putnpc")
    def _cmd_putnpc(self, name, args, ctx, imgs):
        # putnpc image,scriptfile,x,y - a WIRE command on the classic
        # client: the server creates the NPC from its own copy of
        # `scriptfile` and streams it back to the whole level (see
        # Client.send_putnpc / build_putnpc). No local spawn: the server
        # echo is the NPC, which is why GTA's furniture scripts guard with
        # `if (testnpc(x,y)<0) putnpc ...` - on re-entry the NPCs are
        # already there and the guard holds them back.
        rt = self.rt
        if len(args) < 4 or rt.client is None:
            return _FALL_THROUGH
        try:
            rt.client.send_putnpc(to_str(args[0]), to_str(args[1]),
                                  to_num(args[2]), to_num(args[3]))
        except Exception:
            pass

    @_gs1_command(_GS1_MAIN_COMMANDS, "putcomp", "putnewcomp")
    def _cmd_putcomp(self, name, args, ctx, imgs):
        # putcomp baddyname,x,y / putnewcomp baddyname,x,y,image,power -
        # "compus" are the classic computer-controlled baddies. Both send
        # PLI_BADDYADD; the baddy comes back via the server's level-wide
        # PLO_BADDYPROPS broadcast (Client.send_baddy_add). putcomp uses the
        # per-type default power/image tables; putnewcomp overrides both.
        # Power is half-hearts end to end: the defaults table, the script
        # arg and the wire byte share the unit (server clamps at 12).
        rt = self.rt
        if len(args) < 3 or rt.client is None:
            return _FALL_THROUGH
        btype = _baddy_type_from_name(args[0])
        x, y = to_num(args[1]), to_num(args[2])
        if name == "putnewcomp" and len(args) >= 5:
            image = to_str(args[3])
            power = int(to_num(args[4]))
        else:
            image = _BADDY_DEFAULT_IMAGE[btype]
            power = _BADDY_DEFAULT_POWER[btype]
        try:
            rt.client.send_baddy_add(x, y, btype, power, image)
        except Exception:
            pass

    @_gs1_command(_GS1_MAIN_COMMANDS, "removecompus")
    def _cmd_removecompus(self, name, args, ctx, imgs):
        rt = self.rt
        if rt.client is None:
            return _FALL_THROUGH
        try:
            rt.client.kill_all_baddies()
        except Exception:
            pass

    # -- scripted combat family (hurt/hit*/bombs/explosions/items) ----------

    def _hurt_local_player(self, halfhearts, from_x=None, from_y=None):
        """Apply floor(halfhearts) half-hearts to the LOCAL player, clamped to
        [0, max_hearts]. GS1Commands.cpp fn_hurt floors the argument. GTA also
        HEALS through this path (`hurt -3` fountains, `hitplayer 0,-2,...`),
        so negatives raise hearts up to the cap. Damage goes through
        client.respond_to_hurt -- the exact path a wire PLO_HURTPLAYER takes
        (hearts + hurt gani + CURPOWER props report) -- and then the on_hurt
        callback so the shell's flash/sound/death presentation fires. A heal
        sends a bare CURPOWER update (client.send_hearts)."""
        cl = self.rt.client
        player = self._player
        if cl is None or player is None:
            return
        hh = math.floor(to_num(halfhearts))
        old = float(getattr(player, "hearts", 0) or 0)
        maxh = float(getattr(player, "max_hearts", 3) or 3)
        new = min(maxh, max(0.0, old - hh / 2.0))
        if hh >= 0:
            try:
                cl.respond_to_hurt(old - new)
            except Exception:
                pass
            player.hearts = new
            cb = getattr(cl, "on_hurt", None)
            if cb:
                try:
                    cb(0, old - new, 0, from_x or 0, from_y or 0)
                except Exception:
                    pass
        else:
            player.hearts = new
            try:
                cl.send_hearts()
            except Exception:
                pass

    @_gs1_command(_GS1_MAIN_COMMANDS, "hurt")
    def _cmd_hurt(self, name, args, ctx, imgs):
        # hurt halfhearts -- hurts the CURRENT player (scripting-gs1-
        # commands.md "hurt"; fn_hurt GS1Commands.cpp:1423-1442 floors the
        # arg and routes it to hitPlayer with the player's own stand point
        # as the source, i.e. no knockback direction).
        if not args:
            return _FALL_THROUGH
        self._hurt_local_player(to_num(args[0]))

    @_gs1_command(_GS1_MAIN_COMMANDS, "hitplayer")
    def _cmd_hitplayer(self, name, args, ctx, imgs):
        # hitplayer index,halfhearts,fromx,fromy -- players[index], where
        # players[0] is the LOCAL player (host._player_list order, the
        # classic client's own convention: FourPlay's hitplayer applies the
        # local branch directly, TInitStatics.cpp:3447-3464, computing the
        # push from (fromx,fromy) to the stand point). A remote player is
        # relayed as PLI_HURTPLAYER (msgPLI_HURTPLAYER forwards it to the
        # victim only), same as a sword hit.
        rt = self.rt
        if len(args) < 2 or rt.client is None:
            return _FALL_THROUGH
        idx = int(to_num(args[0]))
        hh = to_num(args[1])
        fx = to_num(args[2]) if len(args) > 2 else None
        fy = to_num(args[3]) if len(args) > 3 else None
        if idx == 0:
            self._hurt_local_player(hh, fx, fy)
            return
        others = list(getattr(rt.client, "players", {}) or {})
        if not 1 <= idx <= len(others):
            return
        pid = others[idx - 1]
        target = rt.client.players.get(pid) or {}
        dx, dy = _push_dir(target.get("x", 0), target.get("y", 0), fx, fy)
        try:
            rt.client.attack_player(
                pid, damage=max(0.0, math.floor(hh) / 2.0),
                knockback_x=int(dx * 2), knockback_y=int(dy * 2))
        except Exception:
            pass

    @_gs1_command(_GS1_MAIN_COMMANDS, "hitcompu")
    def _cmd_hitcompu(self, name, args, ctx, imgs):
        # hitcompu index,halfhearts,fromx,fromy -- compus[index] (the baddy
        # array; scripting-gs1-commands.md). Same resolution as a sword hit
        # on a baddy: the level leader applies damage + broadcasts the
        # result, anyone else sends PLI_BADDYHURT for the leader to resolve
        # (client._leader_apply_baddy_damage docstring has the full relay
        # story).
        rt = self.rt
        if len(args) < 2 or rt.client is None:
            return _FALL_THROUGH
        ids = self._baddy_ids()
        idx = int(to_num(args[0]))
        if not 0 <= idx < len(ids):
            return
        bid = ids[idx]
        hh = max(0, math.floor(to_num(args[1])))
        baddy = _current_baddies(rt.client).get(bid) or {}
        dx, dy = _push_dir(baddy.get("x", 0), baddy.get("y", 0),
                           to_num(args[2]) if len(args) > 2 else None,
                           to_num(args[3]) if len(args) > 3 else None)
        try:
            if rt.client.is_leader:
                rt.client._leader_apply_baddy_damage(bid, hh)
            else:
                rt.client.hurt_baddy(bid, damage=hh / 2.0,
                                     hurt_dx=dx, hurt_dy=dy)
        except Exception:
            pass

    @_gs1_command(_GS1_MAIN_COMMANDS, "hitnpc")
    def _cmd_hitnpc(self, name, args, ctx, imgs):
        # hitnpc index,halfhearts,fromx,fromy -- npcs[index]: decrement its
        # power, put a character NPC in the hurt gani, fire washit --
        # fn_hitnpc (GS1Commands.cpp:1327-1368) does exactly these three.
        rt = self.rt
        if len(args) < 2 or rt.client is None:
            return _FALL_THROUGH
        ids = self._npc_ids()
        idx = int(to_num(args[0]))
        if not 0 <= idx < len(ids):
            return
        npc = rt.client.npcs.get(ids[idx])
        if not isinstance(npc, dict):
            return
        hh = math.floor(to_num(args[1]))
        npc["power"] = max(0.0, to_num(npc.get("power", 0)) - hh)
        if npc.get("gani"):
            # only character NPCs animate a hurt (fn_hitnpc's isCharacter()
            # gate); scripts normally setcharani themselves right after.
            npc["gani"] = "hurt"
        rt.trigger_npc_event(ids[idx], "washit")

    @_gs1_command(_GS1_MAIN_COMMANDS, "putbomb")
    def _cmd_putbomb(self, name, args, ctx, imgs):
        # putbomb power,x,y -- a scripted level bomb (power 1 normal /
        # 2 superbomb / 3 joltbomb, scripting-gs1-commands.md). Local spawn
        # via on_putbomb (the shell's active_bombs registry, classic 3s
        # fuse -- msgPLI_BOMBADD's own comment pins the 3s total) + wire
        # PLI_BOMBADD so the rest of the level sees it; consume_ammo=False
        # because a script bomb never spends the player's bag. On water the
        # reference spawns a splash instead of a bomb but still informs the
        # server (TServerLevel::putBomb asm: isOnWater -> putLeaps type 5).
        rt = self.rt
        if len(args) < 3:
            return _FALL_THROUGH
        power = max(0, min(3, int(to_num(args[0]))))
        x, y = to_num(args[1]), to_num(args[2])
        if rt.client is not None:
            try:
                rt.client.put_bomb(x, y, power, consume_ammo=False)
            except Exception:
                pass
        if rt.is_water_at((x + 1) % 64, (y + 1) % 64):
            if rt.on_putleaps:
                rt.on_putleaps(5, x, y)
            return
        if rt.on_putbomb:
            rt.on_putbomb(power, x, y, 3.0)

    @_gs1_command(_GS1_MAIN_COMMANDS, "explodebomb", "removebomb")
    def _cmd_removebomb(self, name, args, ctx, imgs):
        # explodebomb index / removebomb index -- bombs[index]. Both take
        # the bomb off the level and tell the server (PLI_BOMBDEL;
        # msgPLI_BOMBDEL relays and removes it); explodebomb bursts it now
        # (the reference routes it into the same explodeBomb the fuse uses,
        # TInitStatics.cpp:3322-3334), removebomb is the silent pickup.
        rt = self.rt
        if not args:
            return _FALL_THROUGH
        bombs = self._bomb_list()
        idx = int(to_num(args[0]))
        if not 0 <= idx < len(bombs):
            return
        bomb = bombs[idx]
        bx, by = to_num(bomb.get("x", 0)), to_num(bomb.get("y", 0))
        if rt.client is not None:
            try:
                rt.client.remove_bomb(*world_to_local(bx, by))
            except Exception:
                pass
            # keep the wire-echo registry consistent for headless callers
            reg = getattr(rt.client, "bombs", None)
            if isinstance(reg, dict):
                level = getattr(rt.client, "_current_level_name", "")
                reg.get(level, {}).pop((bx, by), None)
        if rt.on_removebomb:
            rt.on_removebomb(bomb, name == "explodebomb")

    @_gs1_command(_GS1_MAIN_COMMANDS, "putexplosion", "putexplosion2")
    def _cmd_putexplosion(self, name, args, ctx, imgs):
        # putexplosion radius,x,y (power 1) / putexplosion2
        # power,radius,x,y (scripting-gs1-commands.md; pygserver's
        # gs1/commands/combat.py _explode splits the args the same way).
        rt = self.rt
        if name == "putexplosion2":
            if len(args) < 4:
                return _FALL_THROUGH
            power, radius = int(to_num(args[0])), int(to_num(args[1]))
            x, y = to_num(args[2]), to_num(args[3])
        else:
            if len(args) < 3:
                return _FALL_THROUGH
            power, radius = 1, int(to_num(args[0]))
            x, y = to_num(args[1]), to_num(args[2])
        self._spawn_explosion(power, radius, x, y)

    def _spawn_explosion(self, power, radius, x, y):
        """Client-authoritative scripted explosion: draw it, damage the LOCAL
        player if covered, fire washit on covered NPCs, and send
        PLI_EXPLOSION (the server relays PLO_EXPLOSION to everyone else, who
        each run this same resolution for their own player). The hitbox is a
        BOX with an INCLUSIVE boundary and the damage is `power` hearts =
        power*2 half-hearts -- pinned by pygserver's tests/test_gs1_audience
        (audience.GS1_EXPLOSION_PLAYERS) and _explode's apply_damage call."""
        rt, cl = self.rt, self.rt.client
        if cl is not None:
            try:
                cl.send_explosion(radius, x, y, power)
            except Exception:
                pass
            explos = getattr(cl, "active_explosions", None)
            if explos is not None:
                import time as _t
                explos.append({"x": x, "y": y, "radius": radius,
                               "power": power, "time": _t.time()})
            px = getattr(cl, "x", None)
            py = getattr(cl, "y", None)
            if (px is not None and py is not None
                    and abs(float(px) - x) <= radius
                    and abs(float(py) - y) <= radius):
                self._hurt_local_player(power * 2, x, y)
            for npc_id, npc in list(getattr(cl, "npcs", {}).items()):
                if not isinstance(npc, dict):
                    continue
                if npc.get("visible", True) is False or npc.get("dontblock"):
                    continue
                if (abs(to_num(npc.get("x", 0)) - x) <= radius
                        and abs(to_num(npc.get("y", 0)) - y) <= radius):
                    rt.trigger_npc_event(npc_id, "washit")
        if rt.on_putexplosion:
            rt.on_putexplosion(power, radius, x, y)

    @_gs1_command(_GS1_MAIN_COMMANDS, "removeexplo")
    def _cmd_removeexplo(self, name, args, ctx, imgs):
        # removeexplo index -- drop explos[index]. Purely local: there is no
        # PLI op for explosion removal (constants.py has none); each client
        # culls its own effect list, like the reference's per-client explo
        # array.
        rt = self.rt
        if not args or rt.client is None:
            return _FALL_THROUGH
        explos = getattr(rt.client, "active_explosions", None)
        idx = int(to_num(args[0]))
        if explos is not None and 0 <= idx < len(explos):
            explos.pop(idx)

    @_gs1_command(_GS1_MAIN_COMMANDS, "lay", "lay2")
    def _cmd_lay(self, name, args, ctx, imgs):
        # lay itemname (at the NPC's feet) / lay2 itemname,x,y
        # (scripting-gs1-commands.md; the parser hands itemname through as
        # its literal string). The item lands in the current level's
        # client.items bucket -- the same registry PLO_ITEMADD fills -- so
        # equal local positions in adjacent gmap boards remain independent and
        # rendering/pickup treat it exactly
        # like a server drop -- and PLI_ITEMADD tells the server, which
        # relays it level-wide (msgPLI_ITEMADD).
        rt = self.rt
        if not args or rt.client is None:
            return _FALL_THROUGH
        item = to_str(args[0]).strip().lower()
        item_id = _item_ids().get(item)
        if item_id is None:
            try:
                item_id = int(float(item))
            except (TypeError, ValueError):
                return
        if name == "lay2":
            if len(args) < 3:
                return _FALL_THROUGH
            x, y = to_num(args[1]), to_num(args[2])
        else:
            npc = ctx.this_obj if isinstance(ctx.this_obj, dict) else None
            if npc is not None:
                x, y = to_num(npc.get("x", 0)), to_num(npc.get("y", 0))
            else:
                x = float(getattr(rt.client, "x", 0))
                y = float(getattr(rt.client, "y", 0))
        items = getattr(rt.client, "items", None)
        if items is not None:
            from ..packets import LEVEL_ITEM_NAMES
            level_name = getattr(rt.client, "_current_level_name", "") or ""
            items.setdefault(level_name, {})[(x, y)] = LEVEL_ITEM_NAMES.get(
                item_id, f"item{item_id}")
        try:
            rt.client.send_item_add(x, y, item_id)
        except Exception:
            pass

    @_gs1_command(_GS1_MAIN_COMMANDS, "putleaps")
    def _cmd_putleaps(self, name, args, ctx, imgs):
        # putleaps type,x,y - purely client-local debris burst. The
        # reference handler (scriptfun_gsfunctionsclient_putleaps,
        # Preagonal/FourPlay/quattroplay/src/TInitStatics.cpp:3579-3597)
        # rejects type >= 6 and calls TServerLevel::putLeaps, which spawns
        # the sprite animation and plays water.wav (type 5) or crush.wav
        # positionally (TServerLevel.cpp:2850-2866). Frames/sprites live in
        # game/render_effects.py; this just forwards to the renderer.
        rt = self.rt
        if len(args) < 3:
            return _FALL_THROUGH
        leap_type = int(to_num(args[0]))
        if not (0 <= leap_type <= 5):
            return
        if rt.on_putleaps:
            rt.on_putleaps(leap_type, to_num(args[1]), to_num(args[2]))

    @_gs1_command(_GS1_MAIN_COMMANDS, "attachplayertoobj")
    def _cmd_attachplayertoobj(self, name, args, ctx, imgs):
        # attachplayertoobj objecttype,id - slave the local player to an
        # NPC. The reference only accepts objecttype 0 (NPC) and looks the
        # id up in the universe NPC list (scriptfun_gsfunctionsclient_
        # attachplayertoobj, TInitStatics.cpp:3185-3205). While attached,
        # NPC movement propagates to the player with the attach-time offset
        # preserved, and the player's own position writes stay relative to
        # the NPC (TServerPlayer::attachToNPC / setlocalx,
        # TServerPlayer.cpp:530-581, 1491-1521) - our per-frame delta model
        # in process_timeouts is equivalent. Re-attaching to the same NPC is
        # a no-op, like the reference's `npc != attachedTo` check.
        rt = self.rt
        if len(args) < 2 or rt.client is None:
            return _FALL_THROUGH
        if int(to_num(args[0])) != 0:
            return
        npc_id = int(to_num(args[1]))
        npcs = getattr(rt.client, "npcs", {})
        if npc_id not in npcs:
            return
        att = rt._player_attach
        if att is not None and att.get("npc_id") == npc_id:
            return
        npc = npcs[npc_id]
        rt._player_attach = {
            "npc_id": npc_id,
            "last_x": to_num(npc.get("x", 0)),
            "last_y": to_num(npc.get("y", 0)),
        }

    @_gs1_command(_GS1_MAIN_COMMANDS, "detachplayer")
    def _cmd_detachplayer(self, name, args, ctx, imgs):
        # scriptfun_gsfunctionsclient_detachplayer (TInitStatics.cpp:
        # 3207-3211) -> TServerPlayer::detach.
        self.rt._player_attach = None

    @_gs1_command(_GS1_MAIN_COMMANDS, "play", "play2", "playlooped", "setmusic")
    def _cmd_play(self, name, args, ctx, imgs):
        if not (args and self.rt.on_play):
            return _FALL_THROUGH
        self.rt.on_play(to_str(args[0]))

    @_gs1_command(_GS1_MAIN_COMMANDS, "stopmusic", "stopmidi", "stopsong")
    def _cmd_stopmusic(self, name, args, ctx, imgs):
        if not self.rt.on_stopmusic:
            return _FALL_THROUGH
        self.rt.on_stopmusic()

    @_gs1_command(_GS1_MAIN_COMMANDS, "showimg", "showimg2")
    def _cmd_showimg_callback(self, name, args, ctx, imgs):
        # no layer store (see _layer_store): hand the draw to the embedder
        if not (self.rt.on_showimg and len(args) >= 4):
            return _FALL_THROUGH
        self.rt.on_showimg(int(to_num(args[0])), to_str(args[1]),
                           to_num(args[2]), to_num(args[3]))

    @_gs1_command(_GS1_MAIN_COMMANDS, "hideimg")
    def _cmd_hideimg_callback(self, name, args, ctx, imgs):
        if not (self.rt.on_hideimg and args):
            return _FALL_THROUGH
        self.rt.on_hideimg(int(to_num(args[0])))

    @_gs1_command(_GS1_MAIN_COMMANDS, "callnpc")
    def _cmd_callnpc(self, name, args, ctx, imgs):
        # callnpc <npcs[] index>,<event>[,<param>...] — run another level NPC's
        # handler for `event`. The lexer types the command 'ES' (_tables.py),
        # so everything after the index arrives as ONE string: the event name
        # then its params, which bind to #p(0).. exactly like a projectile's
        # (classic Bomber room0.nw: the arcade cabinets are activated with
        # `callnpc this.n,BOUT`, the room controller refreshes furniture NPCs
        # with the 3-arg `callnpc this.n,timeout,2`).
        if len(args) < 2:
            return _FALL_THROUGH
        ids = self._npc_ids()
        i = int(to_num(args[0]))
        if not 0 <= i < len(ids):
            return
        parts = to_str(args[1]).split(",")
        event = parts[0].strip()
        if not event:
            return
        self.rt.call_npc(ids[i], event, parts[1:])

    @_gs1_command(_GS1_MAIN_COMMANDS, "callweapon")
    def _cmd_callweapon(self, name, args, ctx, imgs):
        # callweapon <weaponscount index>,<event>[,<param>...] — run a handler
        # in one of the player's WEAPON scripts; clientside only, and the
        # params bind to #p(n) (scripting-gs1-commands.md:153-168). The lexer
        # types the command 'ESS' (reborn_protocol/gs1/_tables.py:16), so the
        # event name and the whole param list arrive as two separate strings:
        # classic Bomber's tailor NPC issues `callweapon this.i,TailorSystem,
        # true,#v(x+1.5),#v(y-2.5)` -> ['3.0', 'TailorSystem', 'true,18,9.5'].
        # The index is into the same weapon ordering `weaponscount` and #w(i)
        # use (_gb_weaponscount / weapon_message_code), which is how the
        # calling script found it.
        if len(args) < 2:
            return _FALL_THROUGH
        weapons = list(getattr(self.rt.client, "weapons", {}) or {})
        i = int(to_num(args[0]))
        if not 0 <= i < len(weapons):
            return
        event = to_str(args[1]).strip()
        if not event:
            return
        params = to_str(args[2]).split(",") if len(args) > 2 else []
        self.rt.call_weapon(weapons[i], event, params)

    @_gs1_command(_GS1_MAIN_COMMANDS, "setplayerprop")
    def _cmd_setplayerprop(self, name, args, ctx, imgs):
        if not (self.rt.on_setplayerprop and len(args) >= 2):
            return _FALL_THROUGH
        self.rt.on_setplayerprop(to_str(args[0]), to_str(args[1]))

    # FP's client appearance commands are thin wrappers over the local
    # player's prop slots: sethead -> setHead (TInitStatics.cpp:3711-3715),
    # setsword/setshield set the image and DISCARD the power arg (:3766-3770
    # / :3749-3753 — the int32_t parameter is unnamed and unused), and the
    # set*color family is setcolor(slot, color) with skin 0 / coat 1 /
    # sleeve 2 / shoe 3 / belt 4 (:3757 / :3635 / :3759 / :3755 / :3633).
    _APPEARANCE_CODES = {
        "sethead": "#3", "setsword": "#1", "setshield": "#2",
        "setskincolor": "#C0", "setcoatcolor": "#C1",
        "setsleevecolor": "#C2", "setshoecolor": "#C3", "setbeltcolor": "#C4",
    }

    @_gs1_command(_GS1_MAIN_COMMANDS, *sorted(_APPEARANCE_CODES))
    def _cmd_player_appearance(self, name, args, ctx, imgs):
        # Route through the same shell callback the setplayerprop command
        # uses (game/setup.py on_setplayerprop): #3 sends the head, #1/#2
        # set the sword/shield image slots, #Cn writes Player.colors. FP's
        # setcolor writes the colour STRING into the colors array; our
        # slots hold palette INDICES, so names normalize via _color_name
        # (accepts either form) and unknown colours are dropped.
        if not (self.rt.on_setplayerprop and args):
            return _FALL_THROUGH
        code = self._APPEARANCE_CODES[name]
        value = to_str(args[0])
        if code.startswith("#C"):
            pal = _color_name(value)
            if not pal:
                return
            value = str(REBORN_PALETTE.index(pal))
        self.rt.on_setplayerprop(code, value)

    @_gs1_command(_GS1_MAIN_COMMANDS, "setplayerdir")
    def _cmd_setplayerdir(self, name, args, ctx, imgs):
        # setplayerdir up|left|down|right|n — turn the LOCAL player
        # (scriptfun_gsfunctionsclient_setplayerdir, TInitStatics.cpp:
        # 3723-3747): the four cardinal names map to 0..3; anything else
        # parses as a number, negatives wrap via 4 - (-n & 3), and the
        # result masks with & 3 (so setplayerdir -1 faces right).
        player = getattr(self.rt.client, "player", None)
        if player is None or not args:
            return _FALL_THROUGH
        text = to_str(args[0]).strip().lower()
        direction = {"up": 0, "left": 1, "down": 2, "right": 3}.get(text)
        if direction is None:
            direction = int(to_num(text))
            if direction < 0:
                direction = 4 - (-direction & 3)
            direction &= 3
        player.direction = direction

    @_gs1_command(_GS1_MAIN_COMMANDS, "setmap")
    def _cmd_setmap(self, name, args, ctx, imgs):
        if not (self.rt.on_setmap and args):
            return _FALL_THROUGH
        self.rt.on_setmap(to_str(args[0]), "", 0, 0)

    @_gs1_command(_GS1_MAIN_COMMANDS, "triggeraction")
    def _cmd_triggeraction(self, name, args, ctx, imgs):
        # The action is everything after x,y joined with commas, e.g.
        # `triggeraction 0,0,gr.addweapon,-arenaSYS,-arenaGUI` -> the server
        # action "gr.addweapon,-arenaSYS,-arenaGUI". Dropping the tail would
        # break gr.addweapon (the arena gameplay weapons never get added).
        if not (self.rt.on_triggeraction and len(args) >= 3):
            return _FALL_THROUGH
        action = ",".join(to_str(a) for a in args[2:])
        self.rt.on_triggeraction(to_num(args[0]), to_num(args[1]), action,
                                 getattr(ctx, "_npc_id", 0))

    @_gs1_command(_GS1_MAIN_COMMANDS, "setshootparams")
    def _cmd_setshootparams(self, name, args, ctx, imgs):
        # setshootparams <name>,<p0>,<p1>,... — params the next `shoot` carries.
        # Bomber's room system uses this as a player-to-player message bus.
        self.rt._shoot_params = [to_str(a) for a in args]

    @_gs1_command(_GS1_MAIN_COMMANDS, "shoot", "shootarrow", "shootball",
                  "shootfireball")
    def _cmd_shoot(self, name, args, ctx, imgs):
        rt = self.rt
        if rt.on_shoot:
            # Pass the gani (penultimate-ish arg) and the queued shoot params.
            rt.on_shoot(name, [to_str(a) for a in args], list(rt._shoot_params))
        rt._shoot_params = []

    @_gs1_command(_GS1_MAIN_COMMANDS, "setshape2")
    def _cmd_setshape2(self, name, args, ctx, imgs):
        # Collision shape: record geometry keyed by NPC so the touch handler
        # reads it from here instead of regex-parsing the script. Both forms
        # store (width, height, per-tile flags) — 22 == solid/touchable.
        if len(args) < 3:
            return _FALL_THROUGH
        npc_id = getattr(ctx, "_npc_id", 0)
        w, h = int(to_num(args[0])), int(to_num(args[1]))
        flags = ([int(to_num(f)) for f in args[2]]
                 if isinstance(args[2], (list, tuple)) else [])
        self.rt.shapes[npc_id] = (w, h, flags)
        self.rt._update_shape_blocks(npc_id, ctx.this_obj, w, h, flags)

    @_gs1_command(_GS1_MAIN_COMMANDS, "setshape")
    def _cmd_setshape(self, name, args, ctx, imgs):
        # setshape type,width,height — type 1 is a fully-solid box.
        # width/height are in PIXELS (16 per tile, upstream setShape):
        # the Bomber-v6 lobby signs' setshape(1,32,32) is a 2x2-TILE box.
        # Treating pixels as tiles gave each sign a 32x32-tile block that
        # blanketed the whole level in shape blocks — every onwall2()
        # probe hit one, so the GS2 movement script saw walls everywhere
        # and the player couldn't move at all.
        if len(args) < 3:
            return _FALL_THROUGH
        npc_id = getattr(ctx, "_npc_id", 0)
        stype = int(to_num(args[0]))
        w = max(1, (int(to_num(args[1])) + 15) // 16)
        h = max(1, (int(to_num(args[2])) + 15) // 16)
        flags = [22] * (w * h) if stype == 1 else []
        self.rt.shapes[npc_id] = (w, h, flags)
        self.rt._update_shape_blocks(npc_id, ctx.this_obj, w, h, flags)
