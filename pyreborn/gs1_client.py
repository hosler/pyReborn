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

from reborn_protocol.gs1.runtime import Host, UNSET, VarStore, Context
from reborn_protocol.gs1.interp import Interpreter
from reborn_protocol.gs1.parser import parse
from reborn_protocol.gs1.values import to_num, to_str

logger = logging.getLogger(__name__)

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
        return UNSET

    def set_builtin(self, name, value, indices, ctx) -> bool:
        npc = ctx.this_obj
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
        except Exception:
            logger.debug("gs1 client command %s failed", name, exc_info=True)

    def _dispatch(self, name, args, ctx):
        rt, npc = self.rt, ctx.this_obj
        npc_id = getattr(ctx, "_npc_id", 0)

        if name in _NPC_WRITE and args:
            if isinstance(npc, dict):
                npc[_NPC_WRITE[name]] = to_str(args[0])
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
            rt.on_triggeraction(to_num(args[0]), to_num(args[1]),
                                to_str(args[2]), npc_id)
            return
        if name in ("shoot", "shootarrow", "shootball", "shootfireball") and rt.on_shoot:
            rt.on_shoot(name, [to_str(a) for a in args])
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
        if player is not None:
            if code == "#a":
                return to_str(getattr(player, "account", ""))
            if code == "#n":
                return to_str(getattr(player, "nickname", ""))
            if code == "#c":
                return to_str(getattr(player, "chat", ""))
        return ""


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
        self._shared = {"client": {}, "server": {}, "level": {}, "global": {}}
        self._flags: dict = {}
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

    def clear(self):
        self.scripts.clear()
        self._progs.clear()
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

    def _run(self, entry, event):
        sc = entry["scopes"]
        scopes = {
            "this": sc["this"], "thiso": sc["thiso"], "local": sc["local"],
            "temp": {},
            "client": self._shared["client"], "server": self._shared["server"],
            "level": self._shared["level"], "global": self._shared["global"],
        }
        npc = None
        if self.client is not None:
            npc = getattr(self.client, "npcs", {}).get(entry["npc_id"])
        vs = VarStore(scopes=scopes, player_flags=self._flags)
        player = getattr(self.client, "player", None) if self.client else None
        ctx = Context(self._host, vs, this_obj=npc, player=player)
        ctx._npc_id = entry["npc_id"]
        try:
            Interpreter(ctx).run_event(entry["prog"], event)
        except Exception:
            logger.debug("client GS1 event %s failed", event, exc_info=True)
