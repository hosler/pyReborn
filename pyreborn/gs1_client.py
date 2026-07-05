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
    "playerglovepower": "glove_power", "playernick": "nickname",
    "playeraccount": "account", "playerhead": "head_image",
    "playerbody": "body_image", "playersword": "sword_image",
    "playershield": "shield_image",
}
# unprefixed builtin -> key on the client NPC dict (the NPC running the script)
NPC_ATTR = {
    "x": "x", "y": "y", "dir": "direction", "image": "image", "ani": "gani",
    "nick": "nickname", "message": "message",
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
    "enableweapons", "disableweapons", "noplayerkilling",
    "showstats", "setcursor", "sleep", "replaceani", "seteffectmode",
    "setcoloreffect", "setzoomeffect", "callweapon", "callnpc",
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
            if name == "playerx":
                return float(getattr(self.rt.client, "x", 0)) % 64
            if name == "playery":
                return float(getattr(self.rt.client, "y", 0)) % 64
            if name in PLAYER_ATTR:
                return _num_or_str(getattr(player, PLAYER_ATTR[name], 0))
            if name == "playeronline":
                return 1.0
        if isinstance(npc, dict) and name in NPC_ATTR:
            return _num_or_str(npc.get(NPC_ATTR[name], 0))
        if name == "isweapon":
            return 1.0 if getattr(ctx, "_is_weapon", False) else 0.0
        if name == "weaponscount":
            return float(len(getattr(self.rt.client, "weapons", {}) or {}))
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
        # arena GUI/screen + game-role builtins (read-only)
        if name == "screenwidth":
            return float(self.rt.screen_w)
        if name == "screenheight":
            return float(self.rt.screen_h)
        if name == "mousescreenx":
            return float(self.rt.mouse_x)
        if name == "mousescreeny":
            return float(self.rt.mouse_y)
        if name == "leftmousebutton":
            return 1.0 if self.rt.mouse_left else 0.0
        if name == "isleader":
            # Standard Reborn: true on the first/authority player in the level.
            # Forced override wins (tests); otherwise we're leader iff no other
            # player shares our level.
            if self.rt.is_leader is not None:
                return 1.0 if self.rt.is_leader else 0.0
            cl = self.rt.client
            lvl = to_str(getattr(cl, "level", "")) if cl else ""
            for op in (getattr(cl, "players", {}) or {}).values():
                if isinstance(op, dict) and to_str(op.get("level", lvl)) == lvl:
                    return 0.0
            return 1.0
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
        # handle. Preserve the GMAP segment (the value is the local 0-63 part).
        if name in ("playerx", "playery"):
            p = self._player
            if p is not None:
                axis = name[-1]                      # 'x' or 'y'
                cur = float(getattr(p, axis, 0))
                setattr(p, axis, (int(cur) // 64) * 64 + to_num(value))
                return True
            return False
        if isinstance(npc, dict) and name in NPC_ATTR:
            npc[NPC_ATTR[name]] = value
            return True
        player = self._player
        if player is not None and name in PLAYER_ATTR:
            setattr(player, PLAYER_ATTR[name], value)
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
        if key is not None:
            return self.rt._weapon_imgs.setdefault(key, {})
        return None

    def _dispatch(self, name, args, ctx):
        rt, npc = self.rt, ctx.this_obj
        npc_id = getattr(ctx, "_npc_id", 0)

        if name in _NOOP:
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
        # addtiledef2 <image>, <level>, <xoffset>, <yoffset> — remap a tile-block
        # to a custom tileset image (Bomber Arena's chocolate tiles). The block
        # is xoffset/256 (8 images x 256px build the level's 2048px tileset).
        # removetiledefs reverts to the default tileset.
        if name == "addtiledef2":
            if len(args) >= 3 and rt.on_tiledef:
                image = to_str(args[0])
                block = int(to_num(args[2])) // 256
                rt.on_tiledef(block, image)
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
            if rt.on_freezeplayer:
                rt.on_freezeplayer(to_num(args[0]) if args else 0.5)
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
                # showani index,x,y,dir,gani,param1,param2,... — record gani +
                # position so the renderer can animate furniture/effects. Pull
                # the first string arg after the coords as the gani name
                # (best-effort), then keep everything after it as params: the
                # classic GANI "PARAMn" frame-token substitution (Bomber
                # Arena's DrawBomb() picks the bomb's body/decal sprite and
                # decal image this way, see _render_animated_entity).
                idx = int(to_num(args[0]))
                rec = imgs.setdefault(idx, {})
                rec["x"], rec["y"] = to_num(args[1]), to_num(args[2])
                name_idx = next((i for i in range(3, len(args))
                                  if isinstance(args[i], str) and args[i]), None)
                if name_idx is not None:
                    gani = to_str(args[name_idx])
                    if gani != rec.get("gani"):
                        rec["gani"] = gani
                        rec.pop("_anim", None)   # gani changed -> rebuild animation
                    rec["params"] = list(args[name_idx + 1:])
                rec["screen"] = (name == "showani2")
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
        # a weapon's destroy (e.g. arenaGUI in the lobby) drops its layers
        if name == "destroy" and imgs is not None:
            imgs.clear()
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
        if name in ("play", "play2", "playlooped") and args and rt.on_play:
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
            stype = int(to_num(args[0]))
            w, h = int(to_num(args[1])), int(to_num(args[2]))
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
        if name == "onwall":
            x = int(to_num(args[0])) if args else 0
            y = int(to_num(args[1])) if len(args) > 1 else 0
            return 1.0 if self.rt.is_wall(x, y) else 0.0
        if name == "onwall2":
            # onwall2(x,y,layer) — we only model the base board layer
            x = int(to_num(args[0])) if args else 0
            y = int(to_num(args[1])) if len(args) > 1 else 0
            return 1.0 if self.rt.is_wall(x, y) else 0.0
        if name in ("onwater", "onwater2"):
            x = int(to_num(args[0])) if args else 0
            y = int(to_num(args[1])) if len(args) > 1 else 0
            return 1.0 if self.rt.is_water_at(x, y) else 0.0
        if name == "textwidth":
            # textwidth(zoom, font, style, text) — approximate: Reborn text is
            # ~8px/char at zoom 1 (scripts do int((textwidth(...)+7)/8) to get
            # 8px cells), and we have no font metrics in the headless host.
            zoom = to_num(args[0]) if args else 1.0
            text = to_str(args[3]) if len(args) > 3 else ""
            return float(len(text)) * 8.0 * (zoom if zoom > 0 else 1.0)
        if name == "keydown":
            i = int(to_num(args[0])) if args else -1
            return 1.0 if i in self.rt.keys_dir else 0.0
        if name == "keydown2":
            # keydown2(keycode[, edge]) — edge true = just-pressed this frame
            code = int(to_num(args[0])) if args else -1
            edge = len(args) > 1 and to_num(args[1]) != 0
            if edge:
                held = code in self.rt.keys_raw and code not in self.rt._keys_raw_prev
            else:
                held = code in self.rt.keys_raw
            return 1.0 if held else 0.0
        if name == "hasweapon":
            # case-insensitive exact match (Account::hasWeapon uses
            # string::equalsi, Account.h:118) — match server semantics.
            wname = to_str(args[0]).lower() if args else ""
            weapons = getattr(self.rt.client, "weapons", {}) or {}
            return 1.0 if any(str(w).lower() == wname for w in weapons) else 0.0
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
            return 0.0
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
            return 0.0
        chat, text = chat.lower(), text.lower()
        return 1.0 if (text in chat if contains else chat == text) else 0.0

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
            return to_str(getattr(self.rt.client, "level", "")) if self.rt.client else ""
        if code == "#p":  # projectile param n during actionprojectile2
            idx = int(to_num(args[0])) if args else 0
            pp = self.rt._proj_params
            return to_str(pp[idx]) if 0 <= idx < len(pp) else ""
        if isinstance(npc, dict):
            if code == "#m":
                return to_str(npc.get("gani", ""))
            if code == "#f":
                return to_str(npc.get("image", ""))
            # character-appearance codes read back what setcharprop stored
            key = _CHARPROP_NPC.get(code)
            if key is not None:
                return to_str(npc.get(key, ""))
        if code == "#w" and args and self.rt.client is not None:
            names = list(getattr(self.rt.client, "weapons", {}) or {})
            try:
                return names[int(float(args[0]))]
            except (ValueError, IndexError, TypeError):
                return ""
        return ""


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
        self._sent[k] = sv
        # On the wire global flags are named with the "server." prefix
        # (server.bombrm_NN); the GS1 scope keys them without it.
        try:
            cl.set_flag("server." + str(k), sv)
        except Exception:
            pass

    def recv(self, k, v):
        """Set a flag value received from the server (don't echo it back). The
        wire name carries a "server." prefix; strip it to the scope key."""
        k = k[7:] if str(k).startswith("server.") else k
        super().__setitem__(k, v)
        self._sent[k] = v


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

    def __init__(self, client=None):
        self.client = client
        self.scripts: dict = {}        # name -> raw code (back-compat)
        self._progs: dict = {}         # name -> entry dict
        # npc_id -> (width, height, flags) recorded when setshape/setshape2 runs.
        # The NPC touch handler reads collision geometry from here.
        self.shapes: dict = {}
        # shared non-NPC scopes + client-player GS1 flags
        self._shared = {"client": {}, "server": _ServerFlagScope(self),
                        "level": {}, "global": {}}
        self._flags: dict = {}
        self._proj_params: list = []   # #p(n) during an actionprojectile2 event
        self._shoot_params: list = []  # set by setshootparams, sent by shoot
        # Input / screen / game-role state the arena weapons read via builtins.
        # The pygame input layer populates these each frame; headless tests set
        # them directly. keys_dir holds held arrow/action indices (0=up 1=left
        # 2=down 3=right 4=action/D); keys_raw holds raw keycodes for keydown2.
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

    def load_script(self, name, code, npc_id=0, x=0, y=0):
        self.scripts[name] = code
        try:
            prog = parse(code)
        except Exception:
            logger.debug("failed to parse client GS1 script %s", name, exc_info=True)
            prog = None
        self._progs[name] = {
            "prog": prog, "npc_id": npc_id, "_key": name,
            "scopes": {"this": {}, "thiso": {}, "local": {}},
        }

    def load_weapon(self, name, code):
        """Load a player weapon script (e.g. -validation, -arenaSYS). Weapons
        run client-side like NPCs but have no NPC object; `isweapon` reads true
        and they're keyed off any NPC-touch path (npc_id -1)."""
        key = f"weapon_{name}"
        self.scripts[key] = code
        try:
            prog = parse(code)
        except Exception:
            logger.debug("failed to parse weapon GS1 script %s", name, exc_info=True)
            prog = None
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
        self._weapon_imgs.clear()       # weapon layers are per-level (bombs, HUD)
        self._coros.clear()             # abandon suspended scripts from old level
        self._active_coro_keys.clear()
        # Normal movement is the per-level default; the arena weapon disables it
        # again on its playerenters. Prevents getting stuck if we leave the arena
        # without the weapon's enabledefmovement running.
        self.default_movement = True

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
