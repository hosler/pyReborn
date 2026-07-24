"""Client-side GS1 execution for pyReborn.

In real Reborn, GS1 NPC scripts run on the CLIENT (the server ships the script).
This module runs them with the shared, faithful interpreter from
``reborn_protocol.gs1`` (the same engine pygserver uses server-side), via a
client Host that maps built-in variables to the local player / NPC and turns
visual commands (showimg, play, say, ...) into callbacks the pygame client
renders.

``ClientGS1`` is a drop-in replacement for the old regex ``GS1Interpreter``:
same ``scripts`` dict, ``load_script`` / ``trigger_event`` methods, and
``on_*`` callback attributes.
"""
from __future__ import annotations

import logging
import os
import sys
import traceback

from reborn_protocol.gs1.runtime import Host, UNSET, VarStore, Context
from reborn_protocol.gs1.interp import Interpreter
from reborn_protocol.gs1.parser import parse
from reborn_protocol.gs1.values import to_num, to_str
from .tiletypes import is_blocking, is_water

logger = logging.getLogger(__name__)

# Surface GS1 script errors (they're otherwise swallowed) so problems are
# visible. Deduped so a per-frame failure doesn't spam. Set GS1_DEBUG=1 for a
# full traceback on each unique error.
_GS1_ERR_SEEN: set = set()
_GS1_DEBUG = os.environ.get("GS1_DEBUG")


def _report_gs1_error(where: str, exc: Exception):
    sig = (where, type(exc).__name__, str(exc)[:160])
    if sig in _GS1_ERR_SEEN:
        return
    _GS1_ERR_SEEN.add(sig)
    print(f"[GS1] {where}: {type(exc).__name__}: {exc}", file=sys.stderr)
    if _GS1_DEBUG:
        traceback.print_exc()

# player-prefixed builtin -> attribute on the pyReborn Player
PLAYER_ATTR = {
    "playerdir": "direction", "playersprite": "sprite",
    "playerrupees": "rupees", "playergralats": "rupees",
    "playerhearts": "hearts", "playerfullhearts": "max_hearts",
    "playerarrows": "arrows", "playerbombs": "bombs",
    "playerswordpower": "sword_power", "playershieldpower": "shield_power",
    "playernick": "nickname",
    "playeraccount": "account", "playerhead": "head_image",
    "playerbody": "body_image", "playersword": "sword_image",
    "playershield": "shield_image",
}
# unprefixed builtin -> key on the client NPC dict (the NPC running the script)
NPC_ATTR = {
    "x": "x", "y": "y", "dir": "direction", "image": "image", "ani": "gani",
    "nick": "nickname", "message": "message", "glovepower": "glove_power",
}
# command -> NPC dict key it writes (so the renderer reflects the change).
# Image commands are handled explicitly in _dispatch (they also manage the
# imagepart sub-rect), so they're not listed here.
_NPC_WRITE = {
    "setani": "gani", "setcharani": "gani", "setnick": "nickname",
}

# setcharprop / setplayerprop message-code target -> NPC dict key. These mirror
# a Reborn player's appearance slots (#2 shield, #3 head, #8 body, colours, ...).
# A character NPC (showcharacter) is then composited like a player.
_CHARPROP_NPC = {
    "#1": "sword_image", "#2": "shield_image", "#3": "head_image",
    "#5": "horse_image", "#7": "gani", "#8": "body_image",
    "#m": "gani", "#n": "nickname", "#c": "message",
    "#C0": "color0", "#C1": "color1", "#C2": "color2",
    "#C3": "color3", "#C4": "color4", "#C5": "color5",
    "#C6": "color6", "#C7": "color7",
}

# Commands that just toggle/ignore for client rendering (input/feature state we
# don't model, or world side-effects irrelevant to drawing the lobby). Swallowed
# silently so a script full of them still runs its visible commands.
_NOOP = frozenset({
    "timereverywhere", "enablefeatures",
    "noplayerkilling",
    "setcursor", "sleep", "callweapon", "callnpc",
    "serverwarp",
    "deletestring", "insertstring", "replacestring",
})


class GS1ClientHost(Host):
    """Host bridging GS1 to the live pyReborn client (local player + NPC dict).

    Visual / audio / world commands fire the runtime's ``on_*`` callbacks so the
    pygame client renders them; everything else updates the local NPC/player.
    """

    def __init__(self, runtime: "ClientGS1"):
        self.rt = runtime

    @staticmethod
    def host_surface():
        """Return names accepted by the real shared GS1 lexer/host wiring."""
        from reborn_protocol.gs1 import COMMANDS, FUNCTIONS
        return frozenset(COMMANDS) | frozenset(FUNCTIONS)

    @property
    def _player(self):
        return getattr(self.rt.client, "player", None) if self.rt.client else None

    def _player_list(self):
        """All players the client knows: index 0 is us, then everyone else. Used
        by NPC scripts (players[i].x, #a(i), playerscount) for proximity checks
        and the room-join state machine."""
        cl = self.rt.client
        if cl is None:
            return []
        p = getattr(cl, "player", None)
        out = [{"x": float(getattr(cl, "x", 0)), "y": float(getattr(cl, "y", 0)),
                "account": getattr(p, "account", ""),
                "nickname": getattr(p, "nickname", ""),
                "chat": getattr(p, "chat", "")}]
        for op in getattr(cl, "players", {}).values():
            if isinstance(op, dict):
                out.append({"x": float(op.get("x", 0) or 0),
                            "y": float(op.get("y", 0) or 0),
                            "account": op.get("account", ""),
                            "nickname": op.get("nickname", ""),
                            "chat": op.get("chat", "")})
        return out

    # -- built-in attribute access ----------------------------------------
    def get_builtin(self, name, indices, ctx):
        player = self._player
        npc = ctx.this_obj
        if player is not None:
            # World-frame like upstream: Character.h getTilePosition() binds
            # mapX*64 + local into playerx/playery (same source GS2's player.x
            # uses). On non-gmap levels world == local, so classic servers
            # (e.g. Bomber Arena) are unaffected.
            if name == "playerx":
                return float(getattr(self.rt.client, "x", 0))
            if name == "playery":
                return float(getattr(self.rt.client, "y", 0))
            if name in PLAYER_ATTR:
                return _num_or_str(getattr(player, PLAYER_ATTR[name], 0))
            if name == "playerglovepower":
                # Player script values use 1/2/3 (none/glove1/glove2), while
                # NPC glovepower and the wire-backed Player field use 0/1/2.
                return float(getattr(player, "glove_power", 0) + 1)
            # Boolean-natured builtins must return real Python bools: under the
            # oracle-verified truthiness model (gs1_truthy, values.py) numbers
            # are NEVER truthy in conditions, so a 1.0 here would make
            # `if (isweapon)` etc. silently false. Upstream models these as
            # bool flags/GameValues, not doubles.
            if name == "playeronline":
                return True
            # playerswimming: no dedicated swim-state on the core Client (that
            # lives on GameClient, which this host can't see) — approximate it
            # with the same tile-water check onwater()/is_wall() already use.
            if name == "playerswimming":
                px = float(getattr(self.rt.client, "x", 0)) % 64
                py = float(getattr(self.rt.client, "y", 0)) % 64
                return bool(self.rt.is_water_at(px, py))
            # playeronhorse: PLPROP_HORSEGIF (21) is only non-empty while
            # mounted (mount_horse/dismount are player-props round trips).
            if name == "playeronhorse":
                return bool(getattr(player, "horse_image", ""))
            # playerfreezetime: seconds left on the last `freezeplayer` call
            # (rt._freeze_until is armed in _dispatch, same duration the input
            # layer locks movement for).
            if name == "playerfreezetime":
                import time as _t
                remaining = self.rt._freeze_until - _t.monotonic()
                return remaining if remaining > 0 else -1.0
            # carry* flags: pyReborn only models bush/rock/pot lift objects
            # (game/collision.py _get_liftable_name); "rock"/"pot" are the
            # same objects Reborn's docs call "stone"/"vase". The remaining
            # carry flags are defined for script compatibility, but nothing in
            # this client can currently lift those object types.
            if name == "carrying":
                return bool(player.is_carrying())
            if name == "carriesbush":
                return player.carried_object_type == "bush"
            if name == "carriesstone":
                return player.carried_object_type == "rock"
            if name == "carriesvase":
                return player.carried_object_type == "pot"
            if name in ("carriessign", "carriesblackstone", "carriesnpc"):
                return False
        if isinstance(npc, dict) and name in NPC_ATTR:
            return _num_or_str(npc.get(NPC_ATTR[name], 0))
        # visible: True unless `hide`/`destroy` cleared it (npc dict has no
        # key until then, so a never-hidden NPC must default true).
        if isinstance(npc, dict) and name == "visible":
            return bool(npc.get("visible", True))
        if name == "isweapon":
            return bool(getattr(ctx, "_is_weapon", False))
        if name == "weaponscount":
            return float(len(getattr(self.rt.client, "weapons", {}) or {}))
        if name == "weaponsenabled":
            return bool(self.rt.weapons_enabled)
        if name == "playerscount":
            return float(len(self._player_list()))
        if name == "tokenscount":   # number of tokens from the last `tokenize`
            return float(len(getattr(ctx, "tokenize_tokens", []) or []))
        if name == "timevar":
            # Reborn server clock (GServer-v2 Server::calculateNWTime): integer
            # ticks of 5 seconds since 2001-02-01 17:33:34 UTC. The bomber room
            # timers (server.bombrm_NN) are in this scale; raw unix seconds were
            # out of scale + decimal, which broke the room-timer comparisons.
            import time as _t
            return float(int((_t.time() - 981048814) / 5))
        if name == "timevar2":
            import time as _t
            return float(_t.monotonic() * 1000.0)
        # arena GUI/screen + game-role builtins (read-only)
        if name == "allstats":
            # sum of every showstats bit (see the showstats handler in
            # _dispatch): 1+2+4+...+1024
            return 2047.0
        if name == "screenwidth":
            return float(self.rt.screen_w)
        if name == "screenheight":
            return float(self.rt.screen_h)
        if name == "mousescreenx":
            return float(self.rt.mouse_x)
        if name == "mousescreeny":
            return float(self.rt.mouse_y)
        if name == "leftmousebutton":
            return bool(self.rt.mouse_left)
        if name == "isleader":
            # Standard Reborn: true on the first/authority player in the level.
            # Forced override wins (tests); otherwise we're leader iff no other
            # player shares our level.
            if self.rt.is_leader is not None:
                return bool(self.rt.is_leader)
            cl = self.rt.client
            lvl = to_str(getattr(cl, "level", "")) if cl else ""
            for op in (getattr(cl, "players", {}) or {}).values():
                if isinstance(op, dict) and to_str(op.get("level", lvl)) == lvl:
                    return False
            return True
        # tiles[x,y] — the level board tile id at (x,y); read-only. The room
        # editor reads this for wall detection (tiles[x,y] in {0x278,0x939}).
        if name == "tiles":
            tiles = getattr(self.rt.client, "tiles", None) if self.rt.client else None
            if tiles and len(indices) >= 2:
                x, y = int(indices[0]), int(indices[1])
                if 0 <= x < 64 and 0 <= y < 64 and y * 64 + x < len(tiles):
                    return float(tiles[y * 64 + x])
            return 0.0
        # players[i].x / players[i].y / players[i].account -> the i-th player.
        if name.startswith("players."):
            attr = name.split(".", 1)[1]
            pl = self._player_list()
            i = int(indices[0]) if indices else 0
            return _num_or_str(pl[i].get(attr, 0)) if 0 <= i < len(pl) else 0.0
        return UNSET

    def set_builtin(self, name, value, indices, ctx) -> bool:
        npc = ctx.this_obj
        # `timeout = N` schedules the NPC's `timeout` event N seconds out. Most
        # bomber NPCs drive their logic this way (proximity checks, the room-join
        # processing, animations); the game loop fires it via process_timeouts.
        if name == "timeout":
            if isinstance(npc, dict):
                npc["_timeout"] = max(0.0, to_num(value))
                return True
            # weapon context (no NPC): re-arm the weapon's timeout event so its
            # per-frame gameplay loop keeps running (arenaGUI/arenaSYS do this).
            key = getattr(ctx, "_prog_key", None)
            if key is not None:
                self.rt._weapon_timeouts[key] = max(0.0, to_num(value))
                return True
            return False
        # playerx/playery: the arena weapons drive movement by assigning these.
        # client.x/y are read-only and resolve to player.x/y, so write the player
        # handle. World-frame both ways (matches the getter and upstream), so a
        # read-modify-write round trip stays consistent on gmap segments.
        if name in ("playerx", "playery"):
            p = self._player
            if p is not None:
                setattr(p, name[-1], to_num(value))
                return True
            return False
        if isinstance(npc, dict) and name in NPC_ATTR:
            npc[NPC_ATTR[name]] = value
            return True
        player = self._player
        if player is not None and name in PLAYER_ATTR:
            setattr(player, PLAYER_ATTR[name], value)
            return True
        if player is not None and name == "playerglovepower":
            setattr(player, "glove_power", max(0, int(to_num(value)) - 1))
            return True
        return False

    # -- commands ----------------------------------------------------------
    def call_command(self, name, args, ctx) -> None:
        try:
            self._dispatch(name, args, ctx)
        except Exception as e:
            _report_gs1_error(f"command {name}", e)

    @staticmethod
    def _imgs(npc):
        """The NPC's showimg layer table (index -> record), created on demand."""
        d = npc.get("imgs")
        if d is None:
            d = npc["imgs"] = {}
        return d

    def _layer_store(self, ctx):
        """The showimg/showani layer table for the running script: an NPC keeps
        it on its dict; a weapon (no NPC obj, e.g. arenaGUI's bombs/vases/
        explosions) keeps it in _weapon_imgs keyed by prog-key. The renderer
        draws both. Returns None if there's nowhere to store (no NPC, no key)."""
        npc = ctx.this_obj
        if isinstance(npc, dict):
            return self._imgs(npc)
        key = getattr(ctx, "_prog_key", None)
        if key is not None and getattr(ctx, "_is_weapon", False):
            return self.rt._weapon_imgs.setdefault(key, {})
        # An NPC script with no NPC dict (despawned, or still loaded from the
        # PREVIOUS level while a warp is settling) must not draw: routing it
        # into the weapon table gave the old level's showimgs an unowned,
        # never-culled store — the bomber lobby's subtract smoke kept painting
        # the spar pit black after taking the stairs down.
        return None

    def _dispatch(self, name, args, ctx):
        rt, npc = self.rt, ctx.this_obj
        npc_id = getattr(ctx, "_npc_id", 0)

        if name in _NOOP:
            return
        # showstats bitflag — select which default-HUD elements the client
        # draws (1 ASD, 2 icons, 4 gralats, 8 bombs, 16 arrows, 32 hearts,
        # 64 AP, 128 MP, 256 minimap, 512 inventory, 1024 players; allstats
        # = 2047). Scripted HUDs call showstats(allstats - <bits>) to hide
        # the built-in HUD before drawing their own. game/hud.py reads
        # rt.stats_mask each frame; None = never called = show everything.
        # State persists across level changes like the real client (levels
        # that care re-issue it on playerenters).
        if name == "showstats":
            rt.stats_mask = int(to_num(args[0])) if args else None
            return
        # disable/enable the engine's built-in WASD/arrow movement. The arena
        # weapons (arenaSYS) disable it and move the player themselves via
        # keydown()+playerx; the input layer checks rt.default_movement.
        if name == "disabledefmovement":
            rt.default_movement = False
            return
        if name == "enabledefmovement":
            rt.default_movement = True
            return
        # enableweapons/disableweapons: real client-side state (backs the
        # `weaponsenabled` flag), not just a swallowed no-op.
        if name == "enableweapons":
            rt.weapons_enabled = True
            return
        if name == "disableweapons":
            rt.weapons_enabled = False
            return
        # addtiledef2 <image>, <level>, <xoffset>, <yoffset> — remap a tile-block
        # to a custom tileset image (Bomber Arena's chocolate tiles). The block
        # is xoffset/256 (8 images x 256px build the level's 2048px tileset).
        # removetiledefs reverts to the default tileset.
        if name == "addtiledef2":
            if len(args) >= 3 and rt.on_tiledef:
                image = to_str(args[0])
                levelstart = to_str(args[1]) if len(args) >= 2 else ""
                block = int(to_num(args[2])) // 256
                rt.on_tiledef(block, image, levelstart)
            return
        # addtiledef <image>[, <levelstart>[, <type>]] — replace the WHOLE
        # tileset (the image is a full 2048x512 sheet; Bomber v6's
        # bmb_pics1.png). block -1 marks it for the callback.
        if name == "addtiledef":
            if args and rt.on_tiledef:
                image = to_str(args[0])
                levelstart = to_str(args[1]) if len(args) >= 2 else ""
                rt.on_tiledef(-1, image, levelstart)
            return
        if name == "removetiledefs":
            if rt.on_tiledef:
                rt.on_tiledef(None, None)   # None block = clear all
            return
        # seteffect r,g,b,a — fullscreen colour tint (Tier 3d). 0..1 floats.
        if name == "seteffect" and rt.on_seteffect and len(args) >= 4:
            rt.on_seteffect(to_num(args[0]), to_num(args[1]),
                            to_num(args[2]), to_num(args[3]))
            return
        # #P1..#P30 player gattribs (room slot lists). setcharprop/setplayerprop
        # on a #P code targets the PLAYER, not the NPC — store it so the script
        # can read it back via #P1(-1) etc.
        if name in ("setcharprop", "setplayerprop") and len(args) >= 2:
            pk = _pcode(to_str(args[0]))
            if pk is not None:
                val = to_str(args[1])
                rt._player_props[pk] = val
                # sync our gattrib to the server so other players see it (the
                # bomber room queue shares slot lists this way)
                try:
                    if rt.client is not None:
                        rt.client.set_gattrib(int(pk[1:]), val)
                except Exception:
                    pass
                return
        # replaceani orig,new — swap a default player ani for a level-supplied
        # one (visuals via the game client's resolver AND #m, which scripts
        # test — e.g. the bomber stairs NPC's walk check). One arg restores
        # the default.
        if name == "replaceani" and args:
            orig = to_str(args[0])
            if len(args) >= 2 and to_str(args[1]):
                new = to_str(args[1])
                rt.ani_replacements[orig] = new
                # The replacement gani only reaches the parser cache via a
                # server download (setup.py on_file) — fetch it once, or the
                # player's anim silently keeps the old gani.
                if new not in rt._requested_anis:
                    rt._requested_anis.add(new)
                    try:
                        rt.client.request_file(new + ".gani")
                    except Exception:
                        pass
            else:
                rt.ani_replacements.pop(orig, None)
            return
        if name in _NPC_WRITE and args:
            if isinstance(npc, dict):
                npc[_NPC_WRITE[name]] = to_str(args[0])
            return

        # -- player / game commands (work for weapon scripts too, where there
        # is no NPC object) -------------------------------------------------
        if name in ("setlevel2", "setlevel") and rt.on_warp and args:
            x = to_num(args[1]) if len(args) > 1 else None
            y = to_num(args[2]) if len(args) > 2 else None
            rt.on_warp(to_str(args[0]), x, y)
            return
        if name == "freezeplayer":
            secs = to_num(args[0]) if args else 0.5
            if rt.on_freezeplayer:
                rt.on_freezeplayer(secs)
            import time as _t
            rt._freeze_until = _t.monotonic() + max(0.0, secs)
            return
        # hitobjects power,x,y — client-side sword-hit emulation (see
        # npcserver.md "Emulating sword hits"): fire `washit` on NPCs and hurt
        # baddies at that (level-local) point, same effects as a real sword
        # swing (client.py _sword_hit_npcs/_sword_hit_baddies).
        if name == "hitobjects" and len(args) >= 3:
            rt.hit_objects_at(to_num(args[1]), to_num(args[2]), to_num(args[0]))
            return
        if name == "setminimap" and rt.on_setminimap:
            rt.on_setminimap([to_str(a) for a in args])
            return
        if name == "toweapons" and rt.on_toweapons and args:
            rt.on_toweapons(to_str(args[0]))
            return

        # -- showimg / changeimg* layer system -----------------------------
        # NPCs paint floating images (lights, signs, furniture) addressed by a
        # numeric index; changeimg* then mutate that record. The renderer reads
        # npc['imgs'] each frame. Coords are level tiles (showimg) for index < ...
        # showimg/showani/changeimg*/showtext/showpoly/hideimg layer system. NPCs store
        # layers on npc['imgs']; weapons (no NPC obj — e.g. arenaGUI's bombs,
        # vases and explosions) store them in _weapon_imgs. The renderer draws
        # both. _layer_store resolves to the right table for the running script.
        imgs = self._layer_store(ctx)
        if imgs is not None:
            if name in ("showimg", "showimg2") and len(args) >= 2:
                idx = int(to_num(args[0]))
                rec = imgs.setdefault(idx, {})
                rec["image"] = to_str(args[1])
                if len(args) >= 4:
                    rec["x"], rec["y"] = to_num(args[2]), to_num(args[3])
                rec["screen"] = (name == "showimg2")
                rec.setdefault("vis", 4)
                return
            if name in ("showani", "showani2") and len(args) >= 3:
                # showani index,x,y,dir,gani,param1,... / showani2
                # index,x,y,z,dir,gani,param1,... (reference lexer: EEEDS vs
                # EEEEDS — showani2 only ADDS a z coordinate; BOTH are
                # level-tile draws, unlike showimg2/showtext2 which are the
                # screen-space variants. Bomber's PetSys pet and the emotes
                # bubble are showani2-at-player-coords: flagging them
                # screen-space painted them at pixel (playerx,playery), i.e.
                # the screen's top-left corner, instead of on the player).
                # Record gani + position so the renderer can animate
                # furniture/effects. Pull the first string arg after the
                # coords as the gani name (best-effort), then keep everything
                # after it as params: the classic GANI "PARAMn" frame-token
                # substitution (Bomber Arena's DrawBomb() picks the bomb's
                # body/decal sprite and decal image this way, see
                # _render_animated_entity).
                idx = int(to_num(args[0]))
                rec = imgs.setdefault(idx, {})
                rec["x"], rec["y"] = to_num(args[1]), to_num(args[2])
                if name == "showani2" and len(args) >= 4:
                    rec["z"] = to_num(args[3])
                name_idx = next((i for i in range(3, len(args))
                                  if isinstance(args[i], str) and args[i]), None)
                if name_idx is not None:
                    # The lexer delivers the trailing S arg as ONE comma-joined
                    # string ("eye_bomber_expl,2,7"): the first token is the
                    # gani, the rest are its PARAMn values. Keeping only the
                    # name and dropping the tail left params empty — and the
                    # scripted-gani explosion fallback keys on params[0], so
                    # explosions drew nothing.
                    _parts = [p.strip() for p in to_str(args[name_idx]).split(",")]
                    gani = _parts[0]
                    # Classic `ani[frame]` notation: the bracket picks a frame
                    # of that gani, it is NOT part of the filename. PetSys
                    # hand-animates the squirrel/kitty walk this way
                    # (pet-eye-squirrelwalk1[0..1] each 0.05s tick); keeping
                    # the bracket in the name made the file unresolvable, so
                    # the pet only drew via its plain idle ani — i.e. it was
                    # invisible while following and "teleported" on stop.
                    # Strip to the base name (the renderer then simply PLAYS
                    # the gani, which cycles the same frames) and record the
                    # requested frame for renderers that want exactness.
                    if gani.endswith("]") and "[" in gani:
                        base, _, fidx = gani[:-1].partition("[")
                        gani = base
                        try:
                            rec["gani_frame"] = int(float(fidx))
                        except (TypeError, ValueError):
                            rec.pop("gani_frame", None)
                    else:
                        rec.pop("gani_frame", None)
                    if gani != rec.get("gani"):
                        rec["gani"] = gani
                        rec.pop("_anim", None)   # gani changed -> rebuild animation
                    rec["params"] = _parts[1:] + list(args[name_idx + 1:])
                    rec.pop("_fx_t", None)   # a re-shown effect restarts its burst clock
                    # The arg just before the gani name is the direction
                    # (present in both forms once enough args are given).
                    if name_idx >= 4:
                        try:
                            rec["dir"] = int(to_num(args[name_idx - 1])) & 3
                        except (TypeError, ValueError):
                            pass
                rec["screen"] = False
                rec.setdefault("vis", 4)
                return
            if name == "changeimgpart" and len(args) >= 5:
                rec = imgs.get(int(to_num(args[0])))
                if rec is not None:
                    rec["part"] = (int(to_num(args[1])), int(to_num(args[2])),
                                   int(to_num(args[3])), int(to_num(args[4])))
                return
            if name == "changeimgcolors" and len(args) >= 5:
                rec = imgs.get(int(to_num(args[0])))
                if rec is not None:
                    rec["colors"] = tuple(to_num(a) for a in args[1:5])
                return
            if name == "changeimgzoom" and len(args) >= 2:
                rec = imgs.get(int(to_num(args[0])))
                if rec is not None:
                    rec["zoom"] = to_num(args[1])
                return
            if name == "changeimgvis" and len(args) >= 2:
                rec = imgs.get(int(to_num(args[0])))
                if rec is not None:
                    rec["vis"] = int(to_num(args[1]))
                    # An EXPLICIT vis matters to the renderer: scripts that set
                    # vis>=4 opt the layer into the GUI band (screen-pixel
                    # coords, drawn above the seteffect tint — the classic
                    # layer table: 0 under players, 1 with players, 2-3 over
                    # players, 4+ GUI). Layers that never call changeimgvis
                    # keep the default band AND world-tile coords.
                    rec["vis_set"] = True
                return
            if name == "changeimgmode" and len(args) >= 2:
                rec = imgs.get(int(to_num(args[0])))
                if rec is not None:
                    rec["mode"] = int(to_num(args[1]))
                return
            if name == "showtext" and len(args) >= 6:
                idx = int(to_num(args[0]))
                imgs[idx] = {
                    "x": to_num(args[1]), "y": to_num(args[2]),
                    "font": to_str(args[3]), "style": to_str(args[4]),
                    "text": to_str(args[5]), "text_is": True, "vis": 4,
                    "screen": False,
                }
                return
            if name == "showtext2" and len(args) >= 7:
                # showtext2 index,x,y,zoom,font,style,text (lexer 'EEEESSS' —
                # one more arg than showtext's 'EEESSS', an extra leading
                # zoom float before font/style/text).
                idx = int(to_num(args[0]))
                imgs[idx] = {
                    "x": to_num(args[1]), "y": to_num(args[2]),
                    "zoom": to_num(args[3]),
                    "font": to_str(args[4]), "style": to_str(args[5]),
                    "text": to_str(args[6]), "text_is": True, "vis": 4,
                    "screen": True,
                }
                return
            if name == "changeimgcolors":  # too few args: ignore
                return
            if name in ("hideimg", "hidetext") and args:
                imgs.pop(int(to_num(args[0])), None)
                return
            if name == "hideimgs":
                # hideimgs start,end — clear layers in [start, end] (the bomber
                # uses this form, e.g. `hideimgs 300,304`). hideimgs start — from
                # start onward. hideimgs — all.
                start = int(to_num(args[0])) if args else None
                end = int(to_num(args[1])) if len(args) >= 2 else None
                for k in [k for k in imgs
                          if (start is None or k >= start)
                          and (end is None or k <= end)]:
                    imgs.pop(k, None)
                return
            if name in ("showpoly", "showpoly2") and len(args) >= 2:
                # showpoly index,{x1,y1,x2,y2,...} (2D) / showpoly2
                # index,{x1,y1,z1,x2,y2,z2,...} (3D — a height/z per vertex,
                # e.g. eye_furniture_*.gani's pupil poly). The second arg is a
                # GS1 array literal, which the interpreter already evaluates to
                # a flat Python list — a prior version stored `args[1:]` (the
                # *tuple of remaining args*, i.e. a 1-element list wrapping
                # that list) which silently failed to render since it isn't a
                # flat number list. Stored as a regular layer record (like
                # showimg/showani/showtext) so changeimgvis/changeimgcolors and
                # the vis>=2 over-player ordering apply to it the same way.
                idx = int(to_num(args[0]))
                rec = imgs.setdefault(idx, {})
                rec["poly"] = [float(to_num(v)) for v in args[1]]
                rec["poly_dim"] = 3 if name == "showpoly2" else 2
                rec.setdefault("vis", 4)
                return
        if isinstance(npc, dict):
            if name == "setzoomeffect" and args:
                npc["zoom_effect"] = to_num(args[0])
                return
            if name == "seteffectmode" and args:
                npc["effect_mode"] = int(to_num(args[0]))
                return
            if name == "setcoloreffect" and len(args) >= 4:
                npc["coloreffect"] = tuple(to_num(v) for v in args[:4])
                return
            if name == "showcharacter":
                npc["is_character"] = True
                return
            if name == "setcharprop" and len(args) >= 2:
                code = to_str(args[0])
                key = _CHARPROP_NPC.get(code)
                if key is not None:
                    npc[key] = to_str(args[1])
                return
            if name in ("drawoverplayer", "drawunderplayer"):
                npc["draw_layer"] = "over" if name == "drawoverplayer" else "under"
                return
            if name == "dontblock":
                npc["dontblock"] = True
                rt.shapes.pop(npc_id, None)
                rt._update_shape_blocks(npc_id, npc, 0, 0, [])
                return
            if name == "destroy":
                npc["visible"] = False
                npc.pop("imgs", None)
                return
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
        if name == "destroy" and imgs is not None:
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
            return
        # setimgpart name,x,y,w,h — show only a sub-rect of the sheet. Without
        # the rect the renderer blits the entire sheet (e.g. all of pics1.png).
        if name == "setimgpart" and isinstance(npc, dict) and len(args) >= 5:
            npc["image"] = to_str(args[0])
            npc["imagepart"] = (int(to_num(args[1])), int(to_num(args[2])),
                                int(to_num(args[3])), int(to_num(args[4])))
            return
        # setimg/setgif set the whole image; clear any prior sub-rect.
        if name in ("setimg", "setgif") and isinstance(npc, dict) and args:
            npc["image"] = to_str(args[0])
            npc.pop("imagepart", None)
            return
        if name in ("message", "say2", "say"):
            text = to_str(args[0]) if args else ""
            if isinstance(npc, dict):
                npc["message"] = text
            if rt.on_say:
                rt.on_say(npc_id, text)
            return
        if name in ("play", "play2", "playlooped", "setmusic") and args and rt.on_play:
            rt.on_play(to_str(args[0]))
            return
        if name in ("stopmidi", "stopsong") and rt.on_stopmusic:
            rt.on_stopmusic()
            return
        if name in ("showimg", "showimg2") and rt.on_showimg and len(args) >= 4:
            rt.on_showimg(int(to_num(args[0])), to_str(args[1]),
                          to_num(args[2]), to_num(args[3]))
            return
        if name == "hideimg" and rt.on_hideimg and args:
            rt.on_hideimg(int(to_num(args[0])))
            return
        if name == "setplayerprop" and rt.on_setplayerprop and len(args) >= 2:
            rt.on_setplayerprop(to_str(args[0]), to_str(args[1]))
            return
        if name == "setmap" and rt.on_setmap and args:
            rt.on_setmap(to_str(args[0]), "", 0, 0)
            return
        if name == "triggeraction" and rt.on_triggeraction and len(args) >= 3:
            # The action is everything after x,y joined with commas, e.g.
            # `triggeraction 0,0,gr.addweapon,-arenaSYS,-arenaGUI` -> the server
            # action "gr.addweapon,-arenaSYS,-arenaGUI". Dropping the tail would
            # break gr.addweapon (the arena gameplay weapons never get added).
            action = ",".join(to_str(a) for a in args[2:])
            rt.on_triggeraction(to_num(args[0]), to_num(args[1]), action, npc_id)
            return
        # setshootparams <name>,<p0>,<p1>,... — params the next `shoot` carries.
        # Bomber's room system uses this as a player-to-player message bus.
        if name == "setshootparams":
            rt._shoot_params = [to_str(a) for a in args]
            return
        if name in ("shoot", "shootarrow", "shootball", "shootfireball"):
            if rt.on_shoot:
                # Pass the gani (penultimate-ish arg) and the queued shoot params.
                rt.on_shoot(name, [to_str(a) for a in args], list(rt._shoot_params))
            rt._shoot_params = []
            return
        # Collision shape: record geometry keyed by NPC so the touch handler
        # reads it from here instead of regex-parsing the script. Both forms
        # store (width, height, per-tile flags) — 22 == solid/touchable.
        if name == "setshape2" and len(args) >= 3:
            w, h = int(to_num(args[0])), int(to_num(args[1]))
            flags = ([int(to_num(f)) for f in args[2]]
                     if isinstance(args[2], (list, tuple)) else [])
            rt.shapes[npc_id] = (w, h, flags)
            rt._update_shape_blocks(npc_id, npc, w, h, flags)
            return
        if name == "setshape" and len(args) >= 3:
            # setshape type,width,height — type 1 is a fully-solid box.
            # width/height are in PIXELS (16 per tile, upstream setShape):
            # the Bomber-v6 lobby signs' setshape(1,32,32) is a 2x2-TILE box.
            # Treating pixels as tiles gave each sign a 32x32-tile block that
            # blanketed the whole level in shape blocks — every onwall2()
            # probe hit one, so the GS2 movement script saw walls everywhere
            # and the player couldn't move at all.
            stype = int(to_num(args[0]))
            w = max(1, (int(to_num(args[1])) + 15) // 16)
            h = max(1, (int(to_num(args[2])) + 15) // 16)
            flags = [22] * (w * h) if stype == 1 else []
            rt.shapes[npc_id] = (w, h, flags)
            rt._update_shape_blocks(npc_id, npc, w, h, flags)
            return

        if name == "hide" and isinstance(npc, dict):
            npc["visible"] = False
        elif name == "show" and isinstance(npc, dict):
            npc["visible"] = True
        elif name == "move" and isinstance(npc, dict) and len(args) >= 2:
            npc["x"] = to_num(npc.get("x", 0)) + to_num(args[0])
            npc["y"] = to_num(npc.get("y", 0)) + to_num(args[1])
        # other commands (client visuals not yet rendered) are ignored

    # -- functions / message codes ----------------------------------------
    def call_function(self, name, args, ctx):
        # Predicate functions return real bools (upstream returns bool
        # GameValues); floats would read false in conditions — see the
        # truthiness note in get_builtin.
        if name == "onwall":
            x = int(to_num(args[0])) if args else 0
            y = int(to_num(args[1])) if len(args) > 1 else 0
            return bool(self.rt.is_wall(x, y))
        if name == "onwall2":
            # onwall2(x, y[, width, height]) — the GS2/v6 4-arg rect form
            # (used by -Test_Movement's CheckWall probes) tests every tile
            # the [x,x+w) x [y,y+h) rect covers. The 2/3-arg legacy form
            # keeps the single-tile check (3rd arg = layer, unmodelled).
            # w/h clamp: >=0 (scripts pass slightly-negative degenerate
            # widths, which the rect walk must treat as "just this tile"),
            # <=8 so a bogus huge rect can't stall the frame.
            xf = to_num(args[0]) if args else 0.0
            yf = to_num(args[1]) if len(args) > 1 else 0.0
            if len(args) >= 4:
                import math as _m
                w = min(max(to_num(args[2]), 0.0), 8.0)
                h = min(max(to_num(args[3]), 0.0), 8.0)
                x0, y0 = int(_m.floor(xf)), int(_m.floor(yf))
                x1 = max(x0, int(_m.ceil(xf + w)) - 1)
                y1 = max(y0, int(_m.ceil(yf + h)) - 1)
                for ty in range(y0, y1 + 1):
                    for tx in range(x0, x1 + 1):
                        if self.rt.is_wall(tx, ty):
                            return True
                return False
            return bool(self.rt.is_wall(int(xf), int(yf)))
        if name in ("onwater", "onwater2"):
            x = int(to_num(args[0])) if args else 0
            y = int(to_num(args[1])) if len(args) > 1 else 0
            return bool(self.rt.is_water_at(x, y))
        if name == "textwidth":
            # textwidth(zoom, font, style, text) — approximate: Reborn text is
            # ~8px/char at zoom 1 (scripts do int((textwidth(...)+7)/8) to get
            # 8px cells), and we have no font metrics in the headless host.
            zoom = to_num(args[0]) if args else 1.0
            text = to_str(args[3]) if len(args) > 3 else ""
            return float(len(text)) * 8.0 * (zoom if zoom > 0 else 1.0)
        if name == "keydown":
            i = int(to_num(args[0])) if args else -1
            return i in self.rt.keys_dir
        if name == "keydown2":
            # keydown2(keycode[, edge]) — edge true = just-pressed this frame
            code = int(to_num(args[0])) if args else -1
            edge = len(args) > 1 and to_num(args[1]) != 0
            if edge:
                held = code in self.rt.keys_raw and code not in self.rt._keys_raw_prev
            else:
                held = code in self.rt.keys_raw
            return bool(held)
        if name == "hasweapon":
            # case-insensitive exact match (Account::hasWeapon uses
            # string::equalsi, Account.h:118) — match server semantics.
            wname = to_str(args[0]).lower() if args else ""
            weapons = getattr(self.rt.client, "weapons", {}) or {}
            return any(str(w).lower() == wname for w in weapons)
        if name == "playersays":
            return self._playersays(args, contains=False)
        if name == "playersays2":
            return self._playersays(args, contains=True)
        return UNSET

    def _playersays(self, args, contains):
        # playersays(text) / playersays(index,text) — GS1Functions.cpp:963/995.
        # playersays: case-insensitive EXACT match; playersays2: case-
        # insensitive CONTAINS. An optional leading index selects a player
        # from _player_list() (index 0 = us) instead of the local player.
        if not args:
            return False
        if len(args) >= 2:
            idx = int(to_num(args[0]))
            text = to_str(args[1])
            pl = self._player_list()
            chat = to_str(pl[idx].get("chat", "")) if 0 <= idx < len(pl) else None
        else:
            text = to_str(args[0])
            player = self._player
            chat = to_str(getattr(player, "chat", "")) if player is not None else None
        if chat is None:
            return False
        chat, text = chat.lower(), text.lower()
        return text in chat if contains else chat == text

    def message_code(self, code, args, ctx) -> str:
        player = self._player
        npc = ctx.this_obj
        if player is not None:
            if code == "#a":
                # #a(i) -> the i-th player's account; bare #a -> ours.
                if args:
                    pl = self._player_list()
                    i = int(to_num(args[0]))
                    return to_str(pl[i].get("account", "")) if 0 <= i < len(pl) else ""
                return to_str(getattr(player, "account", ""))
            if code == "#n":
                return to_str(getattr(player, "nickname", ""))
            if code == "#c":
                return to_str(getattr(player, "chat", ""))
        pk = _pcode(code)            # #P1..#P30 player gattrib (room slot list)
        if pk is not None:
            ai = int(pk[1:])
            idx = int(to_num(args[0])) if args else -1
            if idx <= -1:
                # merged list across all players (self + everyone else), DEDUPED
                # by account — this is what HostTemp tokenizes to see who's
                # queued. Each player's gattrib holds a copy of the list (the
                # script appends the merge back), so dedup is essential.
                seen, out = set(), []
                vals = [self.rt._player_props.get(pk, "")]
                for op in (getattr(self.rt.client, "players", {}) or {}).values():
                    if isinstance(op, dict):
                        vals.append(op.get(f"gattrib{ai}", ""))
                for v in vals:
                    for tok in str(v).replace(",", " ").split():
                        if tok and tok not in seen:
                            seen.add(tok)
                            out.append(tok)
                return ",".join(out)
            if idx == 0:
                return to_str(self.rt._player_props.get(pk, ""))
            others = list((getattr(self.rt.client, "players", {}) or {}).values())
            if 0 <= idx - 1 < len(others) and isinstance(others[idx - 1], dict):
                return to_str(others[idx - 1].get(f"gattrib{ai}", ""))
            return ""
        if code == "#L":
            # The SOURCE NPC's level, not the player's — an NPC's script (e.g.
            # a control-NPC or one on a different gmap segment) should report
            # where IT lives. npc['_level'] is set from PLO_NPCPROPS; fall back
            # to the player's level when the NPC has none (weapon scripts).
            if isinstance(npc, dict) and npc.get("_level"):
                return to_str(npc["_level"])
            # Weapon scripts (no NPC): the player's CURRENT level. Prefer
            # _current_level_name — it is what the script-reload machinery
            # keys on, so a post-warp playerenters is guaranteed to see the
            # level it is being (re)run for. client.level (= player.level)
            # lags until the server's PLO_PLAYERWARP lands, and that stale
            # window made the Bomber arena weapon re-run its "Joining..."
            # join-curtain branch while already standing in the lobby.
            if self.rt.client is None:
                return ""
            return to_str(getattr(self.rt.client, "_current_level_name", "")
                          or getattr(self.rt.client, "level", ""))
        if code == "#p":  # projectile param n during actionprojectile2
            idx = int(to_num(args[0])) if args else 0
            pp = self.rt._proj_params
            return to_str(pp[idx]) if 0 <= idx < len(pp) else ""
        if code == "#m":
            # Player's current ani — what every bomber NPC keys on
            # (strequals(#m,blank), #e(11,4,#m)=="walk" on the stairs...).
            # #m(-1) is the source NPC's own ani, same indexed-source
            # convention as #Cn(-1) (npc21 uses it for its grab check).
            if args and int(to_num(args[0])) == -1 and isinstance(npc, dict):
                return to_str(npc.get("gani", ""))
            return to_str(self.rt.current_player_ani())
        if isinstance(npc, dict):
            if code == "#f":
                return to_str(npc.get("image", ""))
            # character-appearance codes read back what setcharprop stored
            key = _CHARPROP_NPC.get(code)
            if key is not None:
                return to_str(npc.get(key, ""))
        return ""

    def weapon_message_code(self, code, index, ctx) -> str:
        client = self.rt.client
        if client is None:
            return ""
        weapons = list((getattr(client, "weapons", {}) or {}).items())
        if index is None:
            index = self.rt.selected_weapon_index()
        if index < 0 or index >= len(weapons):
            return ""
        name, data = weapons[index]
        if code == "#w":
            return to_str(name)
        return to_str(data.get("image", "")) if isinstance(data, dict) else ""


class _ServerFlagScope(dict):
    """The GS1 `server.` scope backed by real server flags. Writing a flag
    (setstring server.X) sends PLI_FLAGSET so other players see it; received
    PLO_FLAGSET values are merged via recv(). Bomber's room roster lives here
    (server.bombrm_NN) — the member reads it to find the host's room."""

    def __init__(self, rt):
        super().__init__()
        self._rt = rt
        self._sent = {}

    def __setitem__(self, k, v):
        super().__setitem__(k, v)
        cl = self._rt.client
        if cl is None:
            return
        sv = v if isinstance(v, str) else to_str(v)
        if self._sent.get(k) == sv:        # dedup: don't resend unchanged flags
            return
        # Untrusted server bytecode drives these writes; a `for(...)server.x=i`
        # loop would flood the wire with PLI_FLAGSET. Rate-limit outbound
        # sends (local value still updates so scripts read back what they set).
        if not self._rt._flag_send_allowed():
            return
        # On the wire global flags are named with the "server." prefix
        # (server.bombrm_NN); the GS1 scope keys them without it.
        try:
            cl.set_flag("server." + str(k), sv)
            self._sent[k] = sv
        except Exception:
            pass

    def recv(self, k, v):
        """Set a flag value received from the server (don't echo it back). The
        wire name carries a "server." prefix; strip it to the scope key."""
        k = k[7:] if str(k).startswith("server.") else k
        super().__setitem__(k, v)
        self._sent[k] = v

    def recv_del(self, k):
        """Drop a flag the server deleted (PLO_FLAGDEL), same key transform
        as recv(), no echo. Bomber's queue roster empties this way — the
        server unsets serverr.lobbyN when its last member leaves, so a stale
        local value here reads as a ghost queue entry."""
        k = k[7:] if str(k).startswith("server.") else k
        super().pop(k, None)
        self._sent.pop(k, None)


class _PlayerFlagScope(dict):
    """The GS1 `client.` scope backed by the player's PERSISTED account flags.
    The server streams them at login as PLO_FLAGSET packets named with a
    "client."/"clientr." wire prefix (GServer PlayerClient.cpp sendLogin:
    account.variables); scripts write them with `setstring client.X,...`,
    which the classic client echoes back as PLI_FLAGSET so the selection
    sticks on the account. Bomber's PetSys keys the pet sprite off
    #s(client.pet) — before this scope existed those login flags were dumped
    into the SERVER scope, so every pet rendered as the default squirrel."""

    def __init__(self, rt):
        super().__init__()
        self._rt = rt
        self._sent = {}

    def __setitem__(self, k, v):
        super().__setitem__(k, v)
        cl = self._rt.client
        if cl is None:
            return
        sv = v if isinstance(v, str) else to_str(v)
        if self._sent.get(k) == sv:        # dedup: don't resend unchanged flags
            return
        if not self._rt._flag_send_allowed():
            return
        try:
            cl.set_flag("client." + str(k), sv)
            self._sent[k] = sv
        except Exception:
            pass

    def recv(self, k, v):
        """Merge a player flag received from the server (no echo). Both
        "client." and "clientr." wire prefixes land in this scope — GS1's
        NAMESPACES maps clientr to the client scope (clientr is just the
        server-writable-only variant of the same namespace)."""
        k = str(k)
        for pfx in ("clientr.", "client."):
            if k.startswith(pfx):
                k = k[len(pfx):]
                break
        super().__setitem__(k, v)
        self._sent[k] = v

    def recv_del(self, k):
        """Drop a player flag the server deleted (PLO_FLAGDEL), no echo."""
        k = str(k)
        for pfx in ("clientr.", "client."):
            if k.startswith(pfx):
                k = k[len(pfx):]
                break
        super().pop(k, None)
        self._sent.pop(k, None)


def _pcode(code):
    """#P1..#P30 player-gattrib code -> store key 'P1'..; else None."""
    if code and code.startswith("#P") and code[2:].isdigit():
        return code[1:]
    return None


def _num_or_str(v):
    if isinstance(v, str):
        return v
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


class ClientGS1:
    """Runs GS1 NPC scripts client-side. Drop-in for the old GS1Interpreter."""

    # Outbound flag rate limit: refill tokens/sec, burst cap. Legit scripts
    # write a handful of flags per action (bomber room state); this only bites
    # a runaway setstring loop.
    _FLAG_SEND_RATE = 60.0
    _FLAG_SEND_BURST = 120.0

    def _flag_send_allowed(self) -> bool:
        """Token-bucket gate for outbound PLI_FLAGSET (see _flag_tokens)."""
        import time as _t
        now = _t.time()
        if self._flag_last_refill:
            self._flag_tokens = min(
                self._FLAG_SEND_BURST,
                self._flag_tokens + (now - self._flag_last_refill) * self._FLAG_SEND_RATE)
        self._flag_last_refill = now
        if self._flag_tokens < 1.0:
            return False
        self._flag_tokens -= 1.0
        return True

    def __init__(self, client=None):
        self.client = client
        self.scripts: dict = {}        # name -> raw code (back-compat)
        self._progs: dict = {}         # name -> entry dict
        self._parse_cache: dict = {}   # source text -> parsed Program (or None)
        self._PARSE_CACHE_MAX = 512
        # npc_id -> (width, height, flags) recorded when setshape/setshape2 runs.
        # The NPC touch handler reads collision geometry from here.
        self.shapes: dict = {}
        # shared non-NPC scopes + client-player GS1 flags
        self._shared = {"client": _PlayerFlagScope(self),
                        "server": _ServerFlagScope(self),
                        "level": {}, "global": {}}
        self._flags: dict = {}
        # Outbound-flag rate limiter (token bucket): bounds PLI_FLAGSET
        # packets so untrusted server bytecode can't flood the wire with a
        # setstring loop. Shared by the server + client flag scopes.
        self._flag_tokens = float(self._FLAG_SEND_BURST)
        self._flag_last_refill = 0.0
        self._proj_params: list = []   # #p(n) during actionprojectile2/keypressed
        self._shoot_params: list = []  # set by setshootparams, sent by shoot
        # Input / screen / game-role state the arena weapons read via builtins.
        # The pygame input layer populates these each frame; headless tests set
        # them directly. keys_dir holds held control-function indices (see the
        # keydown() table in scripting-gs1-functions.md: 0=up 1=left 2=down
        # 3=right 4=weapon/D 5=sword/S 6=grab/A 7=map/M 8=chat/Tab 9=inventory/Q);
        # keys_raw holds raw keycodes for keydown2.
        self.screen_w = 800
        self.screen_h = 600
        self.mouse_x = 0.0
        self.mouse_y = 0.0
        self.mouse_left = False
        # Leader = the first player in the level (NPC-authority client); a
        # standard Reborn builtin, not bomber-specific. None = auto-detect (we're
        # leader iff alone in the level); set True/False to force (tests).
        self.is_leader = None
        self.default_movement = True   # disabledefmovement: arena weapons drive movement
        self.weapons_enabled = True    # enableweapons/disableweapons -> `weaponsenabled`
        # showstats bitmask (None = never called = draw the full default
        # HUD). Written by the showstats command (GS1 and GS2 scripts share
        # that dispatch path), read by game/hud.py. Persists across level
        # changes like the real client.
        self.stats_mask = None
        # `replaceani orig,new` — client-session map of default player ani
        # names to level-supplied ones (Bomber's NPC 43: walk->eye_bomber_walk0
        # etc.). Read by resolve_ani(); #m reports the RESOLVED name, which is
        # what NPC scripts key on (the stairs NPC checks #e(11,4,#m)=="walk").
        # Persists across level changes like the real client; levels re-apply
        # it on playerenters anyway.
        self.ani_replacements: dict = {}
        self._requested_anis: set = set()   # replacement ganis fetched once
        # optional callable returning the local player's current logical ani
        # name ("walk"/"idle"/...); the pygame client wires this to its
        # animation state, headless tests can leave it unset.
        self.player_ani_source = None
        self._freeze_until = 0.0       # monotonic deadline used by `playerfreezetime`
        self.selected_weapon_index = lambda: 0
        self.keys_dir: set = set()
        self.keys_raw: set = set()
        self._keys_raw_prev: set = set()  # previous frame, for keydown2 edge
        self._shape_blocks: set = set()   # (tx,ty) cells blocked via setshape2
        self._shape_block_owners: dict = {}  # npc_id -> set of (tx,ty) it contributed
        self._weapon_timeouts: dict = {}  # prog-key -> seconds until timeout event
        self._weapon_imgs: dict = {}      # prog-key -> showimg/showani layer table
        self._coros: list = []            # suspended script coroutines (sleep)
        self._active_coro_keys: set = set()  # prog-keys with a live coroutine
        # Player gattrib props #P1..#P30 (the bomber room slot lists live here).
        # Stored locally so the local player sees them; full multiplayer sync
        # (PLI/PLO player props) is a later step.
        self._player_props: dict = {}
        self._host = GS1ClientHost(self)
        # callbacks (same surface the pygame client wires up)
        self.on_showimg = None
        self.on_hideimg = None
        self.on_play = None
        self.on_stopmusic = None
        self.on_say = None
        self.on_message = None
        self.on_setmap = None
        self.on_movement_changed = None
        self.on_triggeraction = None
        self.on_setplayerprop = None
        self.on_shoot = None
        self.on_freezeplayer = None
        self.on_warp = None
        self.on_setminimap = None
        self.on_toweapons = None
        self.on_tiledef = None
        self.on_seteffect = None

    def _parse_cached(self, name, code):
        """Parse `code`, memoized on the source text. A level re-entry reloads
        every NPC/weapon script from scratch (clear() drops the progs), and
        re-parsing the bomber lobby's 67 NPCs + weapons measured ~300ms of an
        ~800ms single-frame re-entry stall. Programs are immutable once built
        (the interpreter never mutates AST nodes; entries already reuse one
        prog across runs), so sharing them by source is safe. Parse failures
        are cached as None too, so a broken script isn't re-parsed each visit."""
        cache = self._parse_cache
        if code in cache:
            return cache[code]
        try:
            prog = parse(code)
        except Exception:
            logger.debug("failed to parse client GS1 script %s", name, exc_info=True)
            prog = None
        if len(cache) >= self._PARSE_CACHE_MAX:
            cache.clear()               # simple bound; re-parses warm it again
        cache[code] = prog
        return prog

    def load_script(self, name, code, npc_id=0, x=0, y=0):
        self.scripts[name] = code
        prog = self._parse_cached(name, code)
        # npc_bound: the NPC dict existed when the script was loaded (the
        # game always loads from client.npcs). If it later vanishes (despawn,
        # or a warp cleared client.npcs before the engine reload), _run skips
        # the script — see the guard there. Headless harnesses that load
        # scripts for ids with no NPC dict stay runnable (npc_bound False).
        self._progs[name] = {
            "prog": prog, "npc_id": npc_id, "_key": name,
            "npc_bound": bool(self.client is not None and npc_id
                              and npc_id in getattr(self.client, "npcs", {})),
            "scopes": {"this": {}, "thiso": {}, "local": {}},
        }

    def recv_flag(self, name, value):
        """Route a PLO_FLAGSET wire flag into the right GS1 scope: player
        account flags ("client."/"clientr." prefix, streamed at login and
        whenever the server sets one) go to the client scope; everything else
        (the "server."-prefixed globals) to the server scope. Callers
        (game/setup.py's on_flag + its engine-init backfill) used to shove
        everything into the server scope, which left #s(client.pet) empty."""
        n = str(name)
        if n.startswith("client.") or n.startswith("clientr."):
            self._shared["client"].recv(n, value)
        else:
            self._shared["server"].recv(n, value)

    def recv_flag_del(self, name):
        """Route a PLO_FLAGDEL wire deletion into the same scope recv_flag
        would have used, so scripts stop seeing the stale value."""
        n = str(name)
        if n.startswith("client.") or n.startswith("clientr."):
            self._shared["client"].recv_del(n)
        else:
            self._shared["server"].recv_del(n)

    def load_weapon(self, name, code):
        """Load a player weapon script (e.g. -validation, -arenaSYS). Weapons
        run client-side like NPCs but have no NPC object; `isweapon` reads true
        and they're keyed off any NPC-touch path (npc_id -1)."""
        key = f"weapon_{name}"
        self.scripts[key] = code
        prog = self._parse_cached(key, code)
        # Preserve a weapon's persistent this./local. scope across re-loads so a
        # re-sent weapon doesn't lose its state mid-game.
        old = self._progs.get(key)
        scopes = old["scopes"] if old else {"this": {}, "thiso": {}, "local": {}}
        self._progs[key] = {
            "prog": prog, "npc_id": -1, "is_weapon": True, "_key": key,
            "weapon_name": name, "scopes": scopes,
        }

    def clear(self):
        # Keep weapon progs across a level change (they belong to the player, not
        # the level); only drop NPC scripts + per-NPC shapes.
        weapons = {k: v for k, v in self._progs.items() if v.get("is_weapon")}
        wscripts = {k: v for k, v in self.scripts.items() if k.startswith("weapon_")}
        self.scripts.clear()
        self.scripts.update(wscripts)
        self._progs.clear()
        self._progs.update(weapons)
        self.shapes.clear()
        self._shape_blocks.clear()
        self._shape_block_owners.clear()
        self.drop_level_weapon_layers()  # GS1 weapon layers are re-drawn per level
        self._coros.clear()             # abandon suspended scripts from old level
        self._active_coro_keys.clear()
        # Normal movement is the per-level default; the arena weapon disables it
        # again on its playerenters. Prevents getting stuck if we leave the arena
        # without the weapon's enabledefmovement running.
        self.default_movement = True

    def drop_level_weapon_layers(self):
        """Clear weapon showimg layer stores on a level change — EXCEPT the
        GS2 weapon/class stores ("gs2_*" prog-keys). Real-client parity:
        weapon layers persist across warps and scripts hide their own; the
        per-level clear is a workaround for OUR GS1 reload model (GS1
        weapon playerenters re-runs and redraws, and stale world-band bombs
        must not survive a warp). GS2 weapon VMs are NOT reloaded per level
        and idiomatic v6 HUD scripts (the bomber's) only repaint layers
        whose backing state changed — clearing their stores erased the
        scripted HUD at the first warp and it never came back."""
        for key in [k for k in self._weapon_imgs
                    if not str(k).startswith("gs2_")]:
            self._weapon_imgs.pop(key, None)

    def forget_npc(self, npc_id):
        """Drop a despawned NPC's prog, shape, blocked cells and any suspended
        coroutine (PLO_NPCDEL). Weapons (npc_id -1) are never touched. Without
        this the NPC's script stays loaded and keeps running from its old tile."""
        if npc_id < 0:
            return
        dead_keys = {k for k, e in self._progs.items()
                     if e.get("npc_id") == npc_id and not e.get("is_weapon")}
        for k in dead_keys:
            self._progs.pop(k, None)
            self.scripts.pop(k, None)
            self._active_coro_keys.discard(k)
            self._weapon_timeouts.pop(k, None)
        if dead_keys:
            self._coros = [c for c in self._coros if c.get("key") not in dead_keys]
        self.shapes.pop(npc_id, None)
        cells = self._shape_block_owners.pop(npc_id, None)
        if cells:
            self._shape_blocks -= cells

    def trigger_event(self, event, name=None):
        names = [name] if name is not None else list(self._progs)
        for n in names:
            entry = self._progs.get(n)
            if entry and entry["prog"] is not None:
                self._run(entry, event)

    def trigger_npc_event(self, npc_id, event):
        for entry in self._progs.values():
            if entry["npc_id"] == npc_id and entry["prog"] is not None:
                self._run(entry, event)

    def _update_shape_blocks(self, npc_id, npc, w, h, flags):
        """Translate an NPC's setshape/setshape2 geometry into world-tile
        blocking cells for onwall()/onwall2(), anchored at the NPC's current
        (x, y) — same convention npc_handler.NPCHandler uses for touch shapes.
        Re-derives this NPC's contribution to `_shape_blocks` from scratch each
        call so re-running setshape2 (e.g. NPC 161's per-frame falling choc
        blocks during the arena's sudden-death `hurryup`) keeps it in sync,
        without disturbing other NPCs' contributions."""
        old = self._shape_block_owners.pop(npc_id, None)
        if old:
            self._shape_blocks -= old
        if not flags or w <= 0 or h <= 0:
            return
        ax = int(to_num(npc.get('x', 0))) if isinstance(npc, dict) else 0
        ay = int(to_num(npc.get('y', 0))) if isinstance(npc, dict) else 0
        mine = set()
        for i, flag in enumerate(flags):
            if int(to_num(flag)) == 22:
                col, row = i % w, i // w
                mine.add((ax + col, ay + row))
        if mine:
            self._shape_blocks |= mine
            self._shape_block_owners[npc_id] = mine

    def is_wall(self, x, y):
        """Collision test at world tile (x, y) for onwall(). Checks the current
        level board (a blocking tile id), plus any dynamic collision rects set
        via setshape2 (the arena's falling sudden-death choc blocks)."""
        ix, iy = int(x), int(y)
        if 0 <= ix < 64 and 0 <= iy < 64:
            tiles = getattr(self.client, "tiles", None) if self.client else None
            if tiles and len(tiles) >= 64 * 64:
                try:
                    if is_blocking(tiles[iy * 64 + ix]):
                        return True
                except (IndexError, TypeError):
                    pass
        # dynamic shapes (setshape2) recorded as world-tile blocking cells
        return (ix, iy) in self._shape_blocks

    def is_water_at(self, x, y):
        """Water test at world tile (x, y) for onwater() — deep or shallow."""
        ix, iy = int(x), int(y)
        if 0 <= ix < 64 and 0 <= iy < 64:
            tiles = getattr(self.client, "tiles", None) if self.client else None
            if tiles and len(tiles) >= 64 * 64:
                try:
                    return is_water(tiles[iy * 64 + ix])
                except (IndexError, TypeError):
                    pass
        return False

    def resolve_ani(self, name):
        """Apply any `replaceani` mapping to a logical player ani name."""
        return self.ani_replacements.get(name, name)

    def current_player_ani(self):
        """The local player's current ani name as `#m` should report it:
        the logical name from the game client (or the wire prop as fallback),
        passed through the replaceani map — a real client substitutes the
        replacement ani wholesale, so scripts see the replaced name."""
        name = ""
        if self.player_ani_source is not None:
            try:
                name = self.player_ani_source() or ""
            except Exception:
                name = ""
        if not name and self.client is not None:
            name = getattr(getattr(self.client, "player", None),
                           "animation", "") or ""
        return self.resolve_ani(name)

    def advance_input_frame(self):
        """Snapshot raw keys so keydown2(code, edge=true) reports just-pressed.
        Call once per game-loop iteration after handling input."""
        self._keys_raw_prev = set(self.keys_raw)

    def process_timeouts(self, dt):
        """Count down each NPC's pending `timeout` and fire its `timeout` event
        when it elapses (the event handler typically re-arms it). This is what
        drives proximity checks, the room-join state machine, etc."""
        if self.client is None:
            return
        for npc_id, npc in list(getattr(self.client, "npcs", {}).items()):
            t = npc.get("_timeout")
            if t is None:
                continue
            t -= dt
            if t <= 0:
                npc["_timeout"] = None      # event handler may re-arm it
                self.trigger_npc_event(npc_id, "timeout")
            else:
                npc["_timeout"] = t
        # weapons drive their per-frame gameplay loop the same way (arenaGUI /
        # arenaSYS re-arm `timeout = 0.05` each frame); they have no NPC dict so
        # their countdown lives in _weapon_timeouts keyed by prog-key.
        for key in list(self._weapon_timeouts):
            entry = self._progs.get(key)
            if entry is None or entry["prog"] is None:
                self._weapon_timeouts.pop(key, None)
                continue
            t = self._weapon_timeouts[key] - dt
            if t <= 0:
                del self._weapon_timeouts[key]   # event handler may re-arm it
                self._run(entry, "timeout")
            else:
                self._weapon_timeouts[key] = t

    def fire_projectile(self, params):
        """A projectile arrived: fire `actionprojectile2` across all scripts with
        `#p(n)` bound to params[n] (params[0] = the shoot's name/first param)."""
        self._proj_params = list(params)
        try:
            self.trigger_event("actionprojectile2")
        finally:
            self._proj_params = []

    def fire_keypress(self, keycode, char=""):
        """A key was pressed: fire `keypressed` (npcserver-gs1.md) across all
        scripts, with `#p(0)`/`#p(1)` bound to the keycode/character. Shares
        _proj_params with actionprojectile2 — the two never fire concurrently."""
        self._proj_params = [float(keycode), char]
        try:
            self.trigger_event("keypressed")
        finally:
            self._proj_params = []

    def hit_objects_at(self, x, y, power=1.0):
        """`hitobjects power,x,y` (also used to emulate a sword hit, see
        npcserver.md "Emulating sword hits"): fire `washit` on visible,
        blocking NPCs at (x, y) and PLI_BADDYHURT on baddies there.
        Coordinates are level-local (0-63), matching npc/baddy x,y and
        playerx/playery. `power` is hearts of damage (GS1Commands.cpp doubles
        it to half-hearts only for the network PLO_HITOBJECTS relay; our
        hurt_baddy() already takes hearts)."""
        cl = self.client
        if cl is None:
            return
        for npc_id, npc in list(getattr(cl, "npcs", {}).items()):
            if not isinstance(npc, dict):
                continue
            if npc.get("visible", True) is False or npc.get("dontblock"):
                continue
            nx, ny = to_num(npc.get("x", 0)), to_num(npc.get("y", 0))
            if abs(nx - x) <= 1.0 and abs(ny - y) <= 1.0:
                self.trigger_npc_event(npc_id, "washit")
        for baddy_id, baddy in list(getattr(cl, "baddies", {}).items()):
            if not isinstance(baddy, dict):
                continue
            bx, by = to_num(baddy.get("x", 0)), to_num(baddy.get("y", 0))
            if abs(bx - x) <= 1.0 and abs(by - y) <= 1.0:
                try:
                    cl.hurt_baddy(baddy_id, damage=power)
                except Exception:
                    pass

    def _run(self, entry, event):
        key = entry.get("_key")
        # Serialize per script: GS1 runs a script's events one at a time. If a
        # previous event is still suspended on a `sleep`, don't start another
        # (the suspended one re-arms `timeout` when it finishes). This is what
        # lets NPC 162 sit in `while(playerscount<2){sleep}` without the
        # per-frame timeout firing a second copy.
        if key is not None and key in self._active_coro_keys:
            return
        sc = entry["scopes"]
        scopes = {
            "this": sc["this"], "thiso": sc["thiso"], "local": sc["local"],
            "temp": {},
            "client": self._shared["client"], "server": self._shared["server"],
            "level": self._shared["level"], "global": self._shared["global"],
        }
        is_weapon = entry.get("is_weapon", False)
        npc = None
        if not is_weapon and self.client is not None:
            npc = getattr(self.client, "npcs", {}).get(entry["npc_id"])
            # The NPC existed at load time but is gone now: it despawned, or
            # we left its level mid-transition (warp cleared client.npcs
            # before the engine reload) — its script must not run: with
            # this_obj=None its timeout re-arms into _weapon_timeouts and its
            # draws have no owner, which is how the old level's scripts kept
            # running forever after a door-link warp. Harness scripts loaded
            # without an NPC dict (npc_bound False) keep running as before.
            if npc is None and entry.get("npc_bound"):
                return
        vs = VarStore(scopes=scopes, player_flags=self._flags)
        player = getattr(self.client, "player", None) if self.client else None
        ctx = Context(self._host, vs, this_obj=npc, player=player)
        ctx._npc_id = entry["npc_id"]
        ctx._is_weapon = is_weapon
        ctx._prog_key = key
        interp = Interpreter(ctx)
        interp._coro = True                # `sleep` suspends; we pump it below
        gen = interp.iter_event(entry["prog"], event)
        self._drive(gen, ctx, key, entry, event)

    def _drive(self, gen, ctx, key, entry, event):
        """Pump a script generator until it suspends on a `sleep` or finishes.
        A suspended generator is parked in _coros and resumed by
        process_coroutines once its sleep elapses."""
        ctx.steps = 0          # fresh step budget per slice; sleeps don't count
        try:
            delay = next(gen)
        except StopIteration:
            if key is not None:
                self._active_coro_keys.discard(key)
            return
        except Exception as e:
            if key is not None:
                self._active_coro_keys.discard(key)
            who = entry.get("weapon_name") or f"npc_{entry['npc_id']}"
            _report_gs1_error(f"event {event} on {who}", e)
            return
        if key is not None:
            self._active_coro_keys.add(key)
        self._coros.append({"gen": gen, "ctx": ctx, "key": key,
                            "entry": entry, "event": event,
                            "remaining": float(delay)})

    def process_coroutines(self, dt):
        """Resume suspended scripts whose `sleep` has elapsed. Driven once per
        frame by the game loop (alongside process_timeouts)."""
        if not self._coros:
            return
        still = []
        for c in self._coros:
            c["remaining"] -= dt
            if c["remaining"] > 0:
                still.append(c)
                continue
            c["ctx"].steps = 0
            try:
                c["remaining"] = float(next(c["gen"]))
                still.append(c)
            except StopIteration:
                if c["key"] is not None:
                    self._active_coro_keys.discard(c["key"])
            except Exception as e:
                if c["key"] is not None:
                    self._active_coro_keys.discard(c["key"])
                ent = c["entry"]
                who = ent.get("weapon_name") or f"npc_{ent['npc_id']}"
                _report_gs1_error(f"event {c['event']} on {who}", e)
        self._coros = still
