"""Client-side GS1 execution for pyReborn.

In real Graal, GS1 NPC scripts run on the CLIENT (the server ships the script).
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
# a Graal player's appearance slots (#2 shield, #3 head, #8 body, colours, ...).
# A character NPC (showcharacter) is then composited like a player.
_CHARPROP_NPC = {
    "#1": "sword_image", "#2": "shield_image", "#3": "head_image",
    "#8": "body_image", "#n": "nickname", "#c": "message",
    "#C0": "color0", "#C1": "color1", "#C2": "color2",
    "#C3": "color3", "#C4": "color4",
}

# Commands that just toggle/ignore for client rendering (input/feature state we
# don't model, or world side-effects irrelevant to drawing the lobby). Swallowed
# silently so a script full of them still runs its visible commands.
_NOOP = frozenset({
    "timereverywhere", "enablefeatures", "enabledefmovement",
    "disabledefmovement", "enableweapons", "disableweapons", "noplayerkilling",
    "showstats", "setcursor", "sleep", "stopmidi", "replaceani", "seteffectmode",
    "setcoloreffect", "setzoomeffect", "seteffect", "callweapon", "callnpc",
    "removetiledefs", "addtiledef2", "serverwarp",
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
                "nickname": getattr(p, "nickname", "")}]
        for op in getattr(cl, "players", {}).values():
            if isinstance(op, dict):
                out.append({"x": float(op.get("x", 0) or 0),
                            "y": float(op.get("y", 0) or 0),
                            "account": op.get("account", ""),
                            "nickname": op.get("nickname", "")})
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
        if name == "timevar":       # server clock (bomber compares room flag times to this)
            import time as _t
            return _t.time()
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

    def _dispatch(self, name, args, ctx):
        rt, npc = self.rt, ctx.this_obj
        npc_id = getattr(ctx, "_npc_id", 0)

        if name in _NOOP:
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
        if isinstance(npc, dict):
            if name in ("showimg", "showimg2") and len(args) >= 2:
                idx = int(to_num(args[0]))
                rec = self._imgs(npc).setdefault(idx, {})
                rec["image"] = to_str(args[1])
                if len(args) >= 4:
                    rec["x"], rec["y"] = to_num(args[2]), to_num(args[3])
                rec["screen"] = (name == "showimg2")
                rec.setdefault("vis", 4)
                return
            if name in ("showani", "showani2") and len(args) >= 3:
                # showani index,x,y,...,gani,... — record gani + position so the
                # renderer can animate furniture/effects. Pull the first string
                # arg after the coords as the gani name (best-effort).
                idx = int(to_num(args[0]))
                rec = self._imgs(npc).setdefault(idx, {})
                rec["x"], rec["y"] = to_num(args[1]), to_num(args[2])
                gani = next((to_str(a) for a in args[3:] if isinstance(a, str) and a), "")
                if gani:
                    rec["gani"] = gani
                rec["screen"] = (name == "showani2")
                rec.setdefault("vis", 4)
                return
            if name == "changeimgpart" and len(args) >= 5:
                rec = self._imgs(npc).get(int(to_num(args[0])))
                if rec is not None:
                    rec["part"] = (int(to_num(args[1])), int(to_num(args[2])),
                                   int(to_num(args[3])), int(to_num(args[4])))
                return
            if name == "changeimgcolors" and len(args) >= 5:
                rec = self._imgs(npc).get(int(to_num(args[0])))
                if rec is not None:
                    rec["colors"] = tuple(to_num(a) for a in args[1:5])
                return
            if name == "changeimgzoom" and len(args) >= 2:
                rec = self._imgs(npc).get(int(to_num(args[0])))
                if rec is not None:
                    rec["zoom"] = to_num(args[1])
                return
            if name == "changeimgvis" and len(args) >= 2:
                rec = self._imgs(npc).get(int(to_num(args[0])))
                if rec is not None:
                    rec["vis"] = int(to_num(args[1]))
                return
            if name == "changeimgmode" and len(args) >= 2:
                rec = self._imgs(npc).get(int(to_num(args[0])))
                if rec is not None:
                    rec["mode"] = int(to_num(args[1]))
                return
            if name == "showtext" and len(args) >= 6:
                idx = int(to_num(args[0]))
                self._imgs(npc)[idx] = {
                    "x": to_num(args[1]), "y": to_num(args[2]),
                    "font": to_str(args[3]), "style": to_str(args[4]),
                    "text": to_str(args[5]), "text_is": True, "vis": 4,
                    "screen": False,
                }
                return
            if name == "showtext2" and len(args) >= 6:
                idx = int(to_num(args[0]))
                self._imgs(npc)[idx] = {
                    "x": to_num(args[1]), "y": to_num(args[2]),
                    "font": to_str(args[3]), "style": to_str(args[4]),
                    "text": to_str(args[5]), "text_is": True, "vis": 4,
                    "screen": True,
                }
                return
            if name == "changeimgcolors":  # too few args: ignore
                return
            if name in ("hideimg", "hidetext") and args:
                self._imgs(npc).pop(int(to_num(args[0])), None)
                return
            if name == "hideimgs":
                # hideimgs [start] — clear all layers at/after start (or all).
                start = int(to_num(args[0])) if args else None
                imgs = self._imgs(npc)
                for k in [k for k in imgs if start is None or k >= start]:
                    imgs.pop(k, None)
                return
            if name == "showpoly":  # polygons not drawn yet; store raw
                if args:
                    npc.setdefault("polys", {})[int(to_num(args[0]))] = args[1:]
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
                return
            if name == "destroy":
                npc["visible"] = False
                npc.pop("imgs", None)
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
            return
        if name == "setshape" and len(args) >= 3:
            # setshape type,width,height — type 1 is a fully-solid box.
            stype = int(to_num(args[0]))
            w, h = int(to_num(args[1])), int(to_num(args[2]))
            flags = [22] * (w * h) if stype == 1 else []
            rt.shapes[npc_id] = (w, h, flags)
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
        return UNSET

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
        # Player gattrib props #P1..#P30 (the bomber room slot lists live here).
        # Stored locally so the local player sees them; full multiplayer sync
        # (PLI/PLO player props) is a later step.
        self._player_props: dict = {}
        self._host = GS1ClientHost(self)
        # callbacks (same surface the pygame client wires up)
        self.on_showimg = None
        self.on_hideimg = None
        self.on_play = None
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

    def load_script(self, name, code, npc_id=0, x=0, y=0):
        self.scripts[name] = code
        try:
            prog = parse(code)
        except Exception:
            logger.debug("failed to parse client GS1 script %s", name, exc_info=True)
            prog = None
        self._progs[name] = {
            "prog": prog, "npc_id": npc_id,
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
            "prog": prog, "npc_id": -1, "is_weapon": True,
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

    def fire_projectile(self, params):
        """A projectile arrived: fire `actionprojectile2` across all scripts with
        `#p(n)` bound to params[n] (params[0] = the shoot's name/first param)."""
        self._proj_params = list(params)
        try:
            self.trigger_event("actionprojectile2")
        finally:
            self._proj_params = []

    def _run(self, entry, event):
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
        try:
            Interpreter(ctx).run_event(entry["prog"], event)
        except Exception as e:
            who = entry.get("weapon_name") or f"npc_{entry['npc_id']}"
            _report_gs1_error(f"event {event} on {who}", e)
