"""Client-side GS2 bytecode execution for pyReborn.

Runs GS2 scripts (weapons/NPCs/classes/ganis) received as compiled bytecode
(PLO_NPCWEAPONSCRIPT / PLO_NPCBYTECODE / PLO_LOADSCRIPT / PLO_GANISCRIPT)
with the shared VM from ``reborn_protocol.gs2``.

Builtins route through the SAME client host surface the GS1 engine uses
(GS1ClientHost in gs1_client.py): showimg/changeimg*/showtext layers land in
the same layer store the pygame renderer draws, say/play/triggeraction fire
the same ``on_*`` callbacks, and player props read/write the same Player
handle. GS2-only surfaces with no GS1 equivalent (GUI controls etc.) are
log-stubbed once per name and show up in GS2VM.coverage_report()'s
builtins_missing.

Wiring mirrors ClientGS1: the embedding app creates ``ClientGS2(client, gs1)``
and calls ``attach()``; inbound bytecode then loads automatically via
client.on_gs2_bytecode, inbound PLO_TRIGGERACTION fires onAction<name>
handlers (client.gs2_host), and the game loop pumps process_timeouts(dt).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from reborn_protocol.gs1.runtime import UNSET
from reborn_protocol.gs2 import (
    GS2VM, GS2Host, GS2Object, NOT_HANDLED, to_bool, to_num, to_str,
)
from .gs1_client import PLAYER_ATTR

logger = logging.getLogger(__name__)

# Limits for untrusted script writes to each server-scoped cache directory.
SAVE_LINES_MAX_LINES = 4096
SAVE_LINES_MAX_CHARS_PER_LINE = 4096
SAVE_LINES_CACHE_MAX_BYTES = 5 * 1024 * 1024

# Floor for settimer()/this.timeout. The v6 reference (C# client) has NO
# 0.05s script-timer clamp — that tradition is the legacy GS1 path
# (OpenGraal.Common ScriptObj.cs:100, `timeout -= 0.05` per tick). Its GS2
# path fires onTimeout two racing ways, neither floored at 0.05:
#   * GS2Engine 1.8.3 Script.cs SetTimer(): a ThreadPool sleeper at
#     `Thread.Sleep(value * 1500)` (1.5x the requested delay, ~ms floor);
#   * GameEngine.cs:755 polls due timers every fixed-timestep Update
#     (TargetElapsedTime = 1/120 s — GameEngine.cs:85/171).
# So a self-rearming setTimer(0.01) loop ticks at roughly the frame rate
# (~60-120 Hz) — that cadence is what sizes the bomber lobby's CadavreTest
# cog spin (0.03 rad/tick) AND -Test_Movement's walk (0.3 tiles/tick). The
# old 0.05 floor here ran both at 1/3 speed. Floor at the reference's
# 120 Hz update tick; effective cadence stays bounded by how often the game
# loop pumps process_timeouts. A fixed-step accumulator catches up at 120 Hz
# when a rendered frame spans multiple update quanta.
TIMER_RESOLUTION = 1.0 / 120.0
TIMER_BACKLOG_CAP = 0.25
PENDING_EVENT_CAP = 16

# GS2 GUI-controls layer (showgui/GuiControl -- see gs2_gui.py's module
# docstring for how `new GuiButtonCtrl(...) { onAction = function(){...}; }`
# actually compiles). Lives under game/ (pygame-only, unlike the rest of this
# module) so headless callers -- e.g. game_tester's GameBot, which imports
# ClientGS2 with no pygame installed -- still work; GUI construction/builtins
# just no-op when it's unavailable.
try:
    from .game.gs2_gui import GS2GuiManager, GuiPopUpEditCtrl
except Exception:  # pragma: no cover - pygame not installed (headless use)
    GS2GuiManager = None
    GuiPopUpEditCtrl = None

#: GS1 command names (from the shared lexer table) -- any GS2 builtin call
#: with a matching name is routed to GS1ClientHost.call_command so both
#: engines drive identical client behavior.
try:
    from reborn_protocol.gs1 import COMMANDS as _GS1_COMMANDS
except ImportError:  # pragma: no cover
    _GS1_COMMANDS = frozenset()
_GS1_COMMANDS = frozenset(_GS1_COMMANDS) | {
    "play", "play2", "playlooped", "setmusic", "stopmidi", "stopsong",
}

#: GS1 function names answered by GS1ClientHost.call_function
_GS1_FUNCTIONS = frozenset({"onwall", "onwall2", "keydown", "keydown2", "hasweapon"})

#: player.<member> -> pyReborn Player attribute (reuses the GS1 table, which
#: is keyed "player<name>"; GS2 accesses the same fields as object members)
_PLAYER_MEMBER_ATTR = {k[len("player"):]: v for k, v in PLAYER_ATTR.items()}
_PLAYER_MEMBER_ATTR.update({
    "nick": "nickname",
    "ani": "gani",
    # v6 HUD scripts read these members directly (the bomber's scripted HUD
    # draws counters from player.mp/ap/darts and player.swordimg); none has
    # a GS1 "player<name>" builtin, so the derived map missed them and every
    # read came back 0/"" (MP/AP meters empty, dart count zero, no sword
    # icon). "darts" is the classic name for arrows on the wire.
    "mp": "mp", "magicpoints": "mp", "ap": "ap", "darts": "arrows",
    "swordimg": "sword_image", "shieldimg": "shield_image",
    "headimg": "head_image", "bodyimg": "body_image",
})


def _csv_flatten(args) -> List[str]:
    """Trigger params as wire CSV fields: a GS2 {array} argument contributes
    one field per element (the client flattens arrays into the action string)."""
    out: List[str] = []
    for a in args:
        if isinstance(a, (list, tuple)):
            out.extend(to_str(x) for x in a)
        else:
            out.append(to_str(a))
    return out


def _image_size(data: bytes):
    """(width, height) from a GIF/PNG/JPEG/BMP header, or None."""
    if len(data) < 26:
        return None
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return (int.from_bytes(data[6:8], "little"),
                int.from_bytes(data[8:10], "little"))
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return (int.from_bytes(data[16:20], "big"),
                int.from_bytes(data[20:24], "big"))
    if data[:2] == b"BM":
        return (int.from_bytes(data[18:22], "little", signed=True),
                abs(int.from_bytes(data[22:26], "little", signed=True)))
    if data[:2] == b"\xff\xd8":  # JPEG: scan for a SOF marker
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                return (int.from_bytes(data[i + 7:i + 9], "big"),
                        int.from_bytes(data[i + 5:i + 7], "big"))
            seg_len = int.from_bytes(data[i + 2:i + 4], "big")
            i += 2 + seg_len
    return None


class _EngineObject(GS2Object):
    """Stand-in for the v6 C# client's engine-object surface (the Unity-side
    API v6 scripts poke at: ``GameObject::Find``, ``object::findanyobjectbytype``,
    ``WorldsF``, ...).

    Member READS auto-vivify a nested stand-in, so chained accesses like
    ``GameObject::Find("Logger").transform.GetChild(0).gameObject.SetActive(true)``
    (v6 -System_Preloader init) stay on the object-exists path all the way down
    instead of collapsing to LValue(None, ...) at the first missing member.
    Member WRITES (``cam.orthographic = true`` in v6 -System onCreated) just
    land in the member dict. Both are exactly what the calling scripts expect
    from a live engine object, and every observed call site discards or
    re-reads only what it wrote."""

    def get(self, key: str) -> Any:
        k = key.lower()
        obj = self._members.get(k)
        if obj is None and k not in self._members:
            obj = self._members[k] = _EngineObject(
                name=f"{self.name}.{k}" if self.name else k)
        return obj


def _engine_object(rt2: "ClientGS2", key: str) -> _EngineObject:
    """Session-persistent stand-in registry: repeated Find()/findanyobjectbytype
    calls for the same name/type must return the SAME object so member writes
    persist across scripts (the -System camera setup relies on identity)."""
    objs = getattr(rt2, "_engine_objects", None)
    if objs is None:
        objs = rt2._engine_objects = {}
    obj = objs.get(key)
    if obj is None:
        obj = objs[key] = _EngineObject(name=key)
    return obj


class _FlagScopeObject(GS2Object):
    """GS2 view of a GS1 flag scope: `server.x` / `serverr.x` / `client.x` /
    `clientr.x` member reads and writes bridge to the shared GS1 scopes (see
    gs1_client._ServerFlagScope/_PlayerFlagScope), so GS2 and GS1 scripts --
    and the real wire flags behind them -- see one store.

    Wire names: "serverr."/"clientr." names are stored UNstripped in the
    server scope ("server." alone is stripped by its recv), so the serverr
    view prefixes its keys. serverr is the read-only replica -- writes stay
    local (dict.__setitem__) instead of echoing PLI_FLAGSET back.
    """

    __slots__ = ("_scope", "_prefix", "_local_writes")

    def __init__(self, name: str, scope: dict, prefix: str = "",
                 local_writes: bool = False):
        super().__init__(name=name)
        self._scope = scope
        self._prefix = prefix
        self._local_writes = local_writes

    def _key(self, key: str) -> str:
        return self._prefix + key if self._prefix else key

    def get(self, key: str) -> Any:
        k = self._key(key)
        if k in self._scope:
            return self._scope[k]
        return self._scope.get(k.lower(), "")

    def set(self, key: str, value: Any) -> None:
        if self._local_writes:
            dict.__setitem__(self._scope, self._key(key), value)
        else:
            self._scope[self._key(key)] = value

    def has(self, key: str) -> bool:
        # Report ACTUAL membership. Direct `server.x` access reads an unset
        # flag as "" via get() (member-access never consults has()), but the
        # with-scope variable lookup (vm.py _lookup) DOES gate on has() --
        # returning True unconditionally there would silently redirect every
        # bare local inside `with(server){...}` to a networked flag.
        k = self._key(key)
        return k in self._scope or k.lower() in self._scope


class _PlayerObject(GS2Object):
    """`player.` bridged onto the live pyReborn client/player."""

    __slots__ = ("_rt2",)

    def __init__(self, rt2: "ClientGS2"):
        super().__init__(name="player")
        self._rt2 = rt2

    def _player(self):
        cl = self._rt2.client
        return getattr(cl, "player", None) if cl else None

    def get(self, key: str) -> Any:
        key = key.lower()
        cl = self._rt2.client
        # WORLD-frame tile position (local + segment*64 on a gmap), matching
        # GServer-v2's scriptParameters "x"/"y" binding (Character::
        # getTilePosition = mapX*64 + local, shared by GS1's playerx/playery
        # and GS2's player.x/player.y - GS1Variables.cpp builds "player"+name
        # straight off the same scriptParameters map).
        # client.x/y (self.player.x/y) are already stored world-frame in
        # pyReborn (see client.py's gmap warp/spawn code), so no folding here.
        if key == "x":
            return float(getattr(cl, "x", 0)) if cl else 0.0
        if key == "y":
            return float(getattr(cl, "y", 0)) if cl else 0.0
        p = self._player()
        if p is not None:
            if key in _PLAYER_MEMBER_ATTR:
                v = getattr(p, _PLAYER_MEMBER_ATTR[key], 0)
                return v if isinstance(v, str) else to_num(v)
            if key == "chat":
                return to_str(getattr(p, "chat", ""))
            if key == "level":
                # `player.level == "x.nw"` drives level-scoped weapon logic
                # (Bomber v6 -arenaSYS clears its "Joining..." seteffect
                # curtain + destroy()s itself only on its bomblobby branch).
                # PLAYER_ATTR has no level entry, so this fell through to
                # empty member storage: the arena branch then ran in EVERY
                # level - permanently re-arming the black curtain after
                # leaving the arena and firing bogus `setlevel2,,,`
                # serverside triggers (answered by PLO_WARPFAILED '').
                # Scripts stringify it immediately, so return the name.
                lvl = getattr(p, "level", "") or ""
                if not lvl and cl is not None:
                    lvl = getattr(cl, "_current_level_name", "") or ""
                return to_str(lvl)
            if key == "weapon":
                # The player's currently selected weapon as an object
                # (scripted HUDs read player.weapon.image for the D-slot
                # icon). Selection follows the inventory UI, defaulting to
                # the first granted weapon.
                weapons = getattr(cl, "weapons", {}) or {}
                game = getattr(self._rt2, "game_shell", None)
                sel = getattr(getattr(game, "inventory_ui", None),
                              "selected_weapon_idx", 0) or 0
                names = list(weapons)
                obj = GS2Object(name="weapon")
                if names:
                    wname = names[sel] if 0 <= sel < len(names) else names[0]
                    rec = weapons.get(wname)
                    obj.set("name", to_str(wname))
                    obj.set("image", to_str(rec.get("image", ""))
                            if isinstance(rec, dict) else "")
                return obj
        return super().get(key)

    def set(self, key: str, value: Any) -> None:
        key = key.lower()
        p = self._player()
        if key in ("x", "y") and p is not None:
            # p.x/p.y (== client.x/y) are already world-frame - see get()'s
            # comment - so the assigned value is written straight through,
            # no re-folding against the current segment's grid origin.
            setattr(p, key, to_num(value))
            return
        if key == "chat" and self._rt2.gs1 is not None:
            # same path GS1's setplayerprop #c takes (chat bubble + server sync)
            self._rt2._gs1_command("setplayerprop", ["#c", to_str(value)], None)
            return
        if p is not None and key in _PLAYER_MEMBER_ATTR:
            # dir/sprite land in renderer + wire paths that index/int these;
            # GS2 numbers are floats (player.dir = 3.0 broke direction
            # lookups) so coerce here, at the bridge.
            if key == "dir":
                value = int(to_num(value)) % 4
            elif key == "sprite":
                value = int(to_num(value))
            setattr(p, _PLAYER_MEMBER_ATTR[key], value)
            return
        super().set(key, value)


class _ThisObject(GS2Object):
    """A script's `this.`: plain member storage plus the `timeout` hook
    (assigning this.timeout = N schedules onTimeout, like GS1's timeout=N)."""

    __slots__ = ("_rt2", "_vm_key")

    def __init__(self, rt2: "ClientGS2", vm_key: tuple, name: str = "this"):
        super().__init__(name=name)
        self._rt2 = rt2
        self._vm_key = vm_key

    def set(self, key: str, value: Any) -> None:
        if key.lower() == "timeout":
            # same floor as the settimer() builtin (see TIMER_RESOLUTION)
            # so this.timeout = 0.01 loops tick at frame rate too
            v = to_num(value)
            if 0.0 < v < TIMER_RESOLUTION:
                v = TIMER_RESOLUTION
            self._rt2._timeouts[self._vm_key] = max(0.0, v)
            return
        super().set(key, value)

    def get(self, key: str) -> Any:
        if key.lower() == "timeout":
            return self._rt2._timeouts.get(self._vm_key, 0.0)
        v = super().get(key)
        if v is None:
            # `this.<name>` where <name> is a same-script function, not a
            # stored member -- the shape `onAction = function(){...};` and
            # plain `x = function(){...}; x();` lambdas both compile to
            # this.<generated-function-name> (ExpressionFnObject; see
            # game/gs2_gui.py's module docstring point 2). GS2VM.has_function/
            # .call already recurse into joined classes, so this also
            # resolves a handler defined inside a joined class's own script.
            kind, key_ = self._vm_key
            vm = self._rt2.vms.get(kind, {}).get(key_)
            if vm is not None and vm.has_function(key):
                fname = key.lower()
                return lambda *args: vm.call(fname, *args)
        return v


#: GS2 NPC-script attribute name -> client npc-dict key. Same store the GS1
#: host writes (gs1_client.py NPC_ATTR/_CHARPROP_NPC) and render_entities.py
#: reads. v6 bytecode addresses these as BARE names (`y = 12.5;`,
#: `headimg = "...";`, `showimg(300, img, x, y)`) — the compiler scopes NPC
#: props implicitly, so the VM's this-object must claim them (has() below)
#: for both _lookup and _assign_name to bridge here instead of the shared
#: globals dict (which cross-contaminated every NPC in a level).
_NPC_THIS_ATTR = {
    "x": "x", "y": "y", "dir": "direction", "image": "image",
    "ani": "gani", "nick": "nickname", "chat": "message",
    "message": "message", "glovepower": "glove_power",
    "headimg": "head_image", "bodyimg": "body_image",
    "shieldimg": "shield_image", "swordimg": "sword_image",
    "horseimg": "horse_image",
}


class _NpcColorsObject(GS2Object):
    """`colors[i]` / `color[i]` in an NPC script: indexed reads/writes bridge
    to the npc dict's color0..color4 slots (what _render_npc's character
    compositor reads). The VM's OP_ARRAY_ASSIGN/OP_ARRAY_INDEX call
    set/get with the stringified index when the target is a GS2Object."""

    __slots__ = ("_owner",)

    def __init__(self, owner: "_NpcThisObject"):
        super().__init__(name="npc.colors")
        self._owner = owner

    @staticmethod
    def _slot(key: str) -> Optional[str]:
        try:
            i = int(to_num(key))
        except (TypeError, ValueError):
            return None
        return f"color{i}" if 0 <= i <= 4 else None

    def get(self, key: str) -> Any:
        npc, slot = self._owner._npc(), self._slot(key)
        if npc is not None and slot:
            return npc.get(slot, "")
        return super().get(key)

    def set(self, key: str, value: Any) -> None:
        npc, slot = self._owner._npc(), self._slot(key)
        if npc is not None and slot:
            npc[slot] = to_str(value)
            return
        super().set(key, value)

    def has(self, key: str) -> bool:
        return self._slot(key) is not None or super().has(key)


class _NpcThisObject(_ThisObject):
    """An NPC script's `this`: NPC display/position attributes bridge to the
    live client npc dict (lazily resolved — bytecode can arrive before the
    NPC's props stream), everything else is plain member storage like
    _ThisObject. Bare names route here too via _lookup/_assign_name because
    has() claims the attribute names."""

    __slots__ = ("_colors",)

    def __init__(self, rt2: "ClientGS2", vm_key: tuple, name: str = "this"):
        super().__init__(rt2, vm_key, name=name)
        self._colors = None

    def _npc(self) -> Optional[dict]:
        cl = self._rt2.client
        if cl is None:
            return None
        npcs = getattr(cl, "npcs", {})
        key = self._vm_key[1]
        npc = npcs.get(key)
        if npc is None and isinstance(key, str):
            try:
                npc = npcs.get(int(key))
            except (TypeError, ValueError):
                npc = None
        return npc if isinstance(npc, dict) else None

    def has(self, key: str) -> bool:
        k = key.lower()
        if k in _NPC_THIS_ATTR or k in ("colors", "color"):
            return True
        return super().has(key)

    def get(self, key: str) -> Any:
        k = key.lower()
        if k in ("colors", "color"):
            if self._colors is None:
                self._colors = _NpcColorsObject(self)
            return self._colors
        attr = _NPC_THIS_ATTR.get(k)
        if attr is not None:
            npc = self._npc()
            if npc is not None and attr in npc:
                v = npc.get(attr)
                return v if isinstance(v, str) else to_num(v)
        return super().get(key)

    def set(self, key: str, value: Any) -> None:
        k = key.lower()
        if k in ("colors", "color") and isinstance(value, (list, tuple)):
            npc = self._npc()
            if npc is not None:
                for i, v in enumerate(value[:5]):
                    npc[f"color{i}"] = to_str(v)
                return
        attr = _NPC_THIS_ATTR.get(k)
        if attr is not None:
            npc = self._npc()
            if npc is not None:
                if attr in ("x", "y"):
                    # Keep the renderer's preferred world_x/world_y in step
                    # (client.py stamps them on every PLO_NPCPROPS, world ==
                    # local + segment offset), and snap the visual position —
                    # a script placement is not movement to lerp across.
                    new = to_num(value)
                    wkey = "world_" + attr
                    if wkey in npc and npc.get(wkey) is not None:
                        old = to_num(npc.get(attr, 0) or 0)
                        npc[wkey] = to_num(npc.get(wkey, 0) or 0) + (new - old)
                    npc[attr] = new
                    mark = getattr(self._rt2.client, "_mark_npc_pos_snap", None)
                    if mark is not None:
                        mark(npc)
                else:
                    npc[attr] = value if isinstance(value, str) else to_num(value)
                return
        super().set(key, value)


class _LayerImage(GS2Object):
    """findimg(index) result: a LIVE view onto a showimg/showtext layer
    record in the GS1 layer store (the same dict the renderer draws).

    Property writes go straight through to the record — the reference
    client's findimg returns the engine's own image object, so scripts
    animate layers by assigning `findimg(i).rotation`, update captions via
    `.text`, toggle `.visible`, move layers with `.x/.y`, etc. A detached
    copy (the previous implementation) silently dropped all of those.

    `rotation` and `visible` are stored on the record for the renderer;
    `layer` maps to the classic vis band (changeimgvis)."""

    __slots__ = ("_rec",)

    _NUM_KEYS = frozenset(("x", "y", "zoom", "rotation", "mode"))
    _STR_KEYS = frozenset(("image", "font", "style"))

    def __init__(self, index: int, rec: dict):
        super().__init__(name=f"image:{index}")
        self._rec = rec

    def get(self, key: str) -> Any:
        k = key.lower()
        if k == "visible":
            return 1.0 if self._rec.get("visible", True) else 0.0
        if k == "layer":
            return float(self._rec.get("vis", 4))
        v = self._rec.get(k)
        return super().get(k) if v is None else v

    def set(self, key: str, value: Any) -> None:
        k = key.lower()
        if k == "visible":
            self._rec["visible"] = to_bool(value)
        elif k == "layer":
            self._rec["vis"] = int(to_num(value))
            self._rec["vis_set"] = True
        elif k in self._NUM_KEYS:
            self._rec[k] = to_num(value)
        elif k in self._STR_KEYS:
            self._rec[k] = to_str(value)
        elif k == "text":
            self._rec["text"] = to_str(value)
            self._rec["text_is"] = True
        elif k == "textshadow":
            self._rec["textshadow"] = to_bool(value)
        else:
            # unknown property: keep it on the record so a renderer that
            # learns the key later just works (and reads round-trip)
            self._rec[k] = value


class GS2ClientHost(GS2Host):
    """VM host: GS2-specific builtins first, then the GS1 client host
    surface, then log-stub."""

    def __init__(self, rt2: "ClientGS2"):
        self.rt2 = rt2

    # Calls deliberately accepted without effects. Each entry documents why
    # emulating it would be less correct than exposing an explicit inert stub.
    stubbed = frozenset({
        "hit",            # no packet-legitimate player/NPC hit action exists
        "modifyclientr",  # client record writes need an unsupported prop codec
    })

    @staticmethod
    def host_surface():
        """Return builtins handled directly or delegated to the real GS1 host."""
        import ast
        import inspect
        import textwrap

        tree = ast.parse(textwrap.dedent(inspect.getsource(
            GS2ClientHost.call_builtin)))
        names = set(_GS1_COMMANDS) | set(_GS1_FUNCTIONS)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            if not isinstance(node.left, ast.Name) or node.left.id != "name":
                continue
            for comparator in node.comparators:
                values = (comparator.elts
                          if isinstance(comparator, (ast.Tuple, ast.List, ast.Set))
                          else [comparator])
                names.update(value.value for value in values
                             if isinstance(value, ast.Constant)
                             and isinstance(value.value, str))
        return frozenset(names) | GS2ClientHost.stubbed

    # -- infrastructure ----------------------------------------------------

    def get_globals(self) -> Dict[str, Any]:
        return self.rt2.globals_store

    def get_object(self, name: str) -> Optional[GS2Object]:
        name = name.lower()
        if name in ("player", "playero"):
            return self.rt2.player_object
        if name == "level":
            return self.rt2.level_object
        if name in ("server", "serverr", "client", "clientr"):
            return self.rt2.flag_scope_object(name)
        if name == "worldsf":
            # v6 C# client world handle: scripts call WorldsF.setFrameTick(ms)
            # (v6 preloader init + npc 10371). Method calls on an object the
            # host can't resolve never reach call_builtin (the VM only
            # consults the host when obj is not None), so hand back a
            # persistent engine-object stand-in.
            return _engine_object(self.rt2, "worldsf")
        if name in ("screenwidth", "screenheight"):
            # Bare screen-size reads: -arenaSYS centers its "Joining..."
            # showtext at (screenwidth/2, screenheight/2), the preloader's
            # DrawBar anchors likewise. The VM resolves unknown bare names
            # through host.get_object, which returned None here -> the
            # values read as 0 and every GS2 screen-anchored layer landed
            # at (0,0) (a 'c'-centered caption then hangs off the top-left
            # corner with only its tail on screen). Same source the GS1
            # host's screenwidth/screenheight builtins use; get_object may
            # return a plain value - the VM pushes whatever comes back
            # (vm.py _lookup / _op_conv_to_object).
            gs1 = self.rt2.gs1
            attr = "screen_w" if name == "screenwidth" else "screen_h"
            return float(getattr(gs1, attr, 0) or 0)
        if name == "isleader":
            gs1 = self.rt2.gs1
            if gs1 is None:
                return False
            return gs1._host.get_builtin(
                "isleader", [], self.rt2._gs1_ctx(None))
        if name == "allstats":
            # Sum of every showstats bit (GServer-v2 docs, "showstats"):
            # 1 ASD + 2 icons + 4 gralats + 8 bombs + 16 arrows + 32 hearts
            # + 64 AP + 128 MP + 256 minimap + 512 inventory + 1024 players.
            # The v6 bomber's HUD weapon computes `showstats(allstats - 1 -
            # 2 - ... - 128)` to swap the client's default HUD for its own
            # scripted one; unresolved this read 0 and the mask went
            # negative.
            return 2047.0
        if name in ("timevar", "timevar2"):
            # bare-name clock reads (v6 -Test_Movement stamps player.notpush
            # = timevar2 for its push-mode timing); same source the GS1
            # engine's builtin uses so both engines share one clock.
            gs1 = self.rt2.gs1
            if gs1 is None:
                return 0.0
            return gs1._host.get_builtin(name, [], self.rt2._gs1_ctx(None))
        # a named weapon's script object (findweapon-style access)
        vm = self.rt2.vms["weapon"].get(name)
        if vm is not None:
            return vm.this
        return None

    def create_object(self, classname: str, arg: Any) -> GS2Object:
        # host.create_object() is already the VM's constructor hook for
        # every `new` (see _op_new_object in reborn_protocol/gs2/vm.py) --
        # no vm.py change was needed to wire this up. Any Gui*Ctrl classname
        # builds a real control (tracked by GS2GuiManager); everything else
        # keeps the prior behavior (an empty, untracked GS2Object).
        if self.rt2.gui is not None and classname.lower().startswith("gui"):
            return self.rt2.gui.create_control(classname, arg)
        return GS2Object(name=classname)

    def sleep(self, vm: GS2VM, seconds: float) -> None:
        # The VM can't suspend, so sleep() blocks — but it pumps the client's
        # packet loop while waiting, which is what sleeping scripts are
        # almost always waiting FOR (preloader download loops poll a file
        # between sleep(0.05) calls; without the pump the file never arrives
        # and the loop spins to the instruction budget). Scripts sleep in
        # small slices, so each call blocks the frame only briefly; capped at
        # 1s as a backstop against a script freezing the app.
        rt2 = self.rt2
        secs = min(max(to_num(seconds), 0.0), 1.0)
        if secs <= 0:
            return
        client = rt2.client
        if client is None or not getattr(client, "connected", False) or rt2._sleeping:
            # No client to pump (disconnected), or we're already inside
            # another script's sleep() pumping update() further up the
            # stack: recursing into update() here would re-enter packet
            # handling, but plain time.sleep() carries no such risk, so wait
            # out the FULL duration (in bounded slices, never one big block)
            # instead of truncating it to 50ms.
            end = time.time() + secs
            while time.time() < end:
                time.sleep(min(0.05, end - time.time()))
            return
        if getattr(client, "_in_update", False):
            # Inside client._handle_packet itself (an onAction handler fired
            # from PLO_TRIGGERACTION): blocking here for the full duration
            # would stall the socket read loop, and pumping update() would
            # re-enter packet handling. The VM has no suspension, so the
            # instructions right after this sleep() run immediately either
            # way -- defer the unpaid remainder onto this VM's next sleep()
            # call (chained short in-packet sleeps then catch back up to
            # real elapsed time) rather than silently dropping it.
            owed = min(getattr(vm, "_gs2_sleep_debt", 0.0) + secs, 1.0)
            wait = min(owed, 0.05)
            time.sleep(wait)
            vm._gs2_sleep_debt = owed - wait
            return
        rt2._sleeping = True
        try:
            end = time.time() + secs
            while time.time() < end and getattr(client, "connected", False):
                client.update(timeout=0.02)
        finally:
            rt2._sleeping = False

    # -- builtins ------------------------------------------------------------

    def call_builtin(self, vm: GS2VM, name: str, args: List[Any],
                     obj: Optional[GS2Object] = None) -> Any:
        rt2 = self.rt2

        if obj is not None:
            if name == "sort" and isinstance(obj, list):
                obj.sort(key=lambda value: (to_str(value).casefold(), to_num(value)))
                return obj
            if name == "savelines" and isinstance(obj, list):
                if args:
                    rt2.save_lines(to_str(args[0]), obj)
                return 0.0
            if name in self.stubbed:
                return 0.0
            if isinstance(obj, _EngineObject):
                # v6 C# client engine-object methods. Observed call sites
                # (v6 -System/-System_Preloader/npc 10371 disasm):
                #  * WorldsF.setFrameTick(ms): frame pacing hint, result
                #    discarded (OP_INDEX_DEC) -> inert.
                #  * Find("Logger").transform.GetChild(0).gameObject
                #      .SetActive(true): whole-chain result discarded; only
                #    non-null traversal matters. GetChild returns a stable
                #    auto-vivified child; SetActive records the flag.
                if name == "getchild":
                    return obj.get(f"child{int(to_num(args[0])) if args else 0}")
                if name == "setactive":
                    obj.set("active", 1.0 if not args or to_num(args[0]) else 0.0)
                    return 0.0
                # Any other engine-object method is part of the same C#-client
                # surface we don't emulate: inert, result never consumed.
                return 0.0
            if rt2.gui is not None:
                ctrl = rt2.gui._resolve(obj)
                if name in ("addcontainer", "addguicontainer"):
                    rt2.gui.add_to(obj, args[0] if args else None)
                    return 0.0
                if name == "getchild":
                    return rt2.gui.get_child(obj, args[0] if args else 0)
                if name == "setactive":
                    if ctrl is not None:
                        ctrl.visible = bool(to_num(args[0])) if args else True
                    return 0.0
                if name == "hidecontrols":
                    rt2.gui.hide_children(obj)
                    return 0.0
                if name == "makefirstresponder":
                    rt2.gui.focus(obj if not args or bool(to_num(args[0])) else None)
                    return 0.0
                if name == "trigger":
                    if ctrl is not None:
                        return 1.0 if ctrl.fire_action(*args) else 0.0
                    return 0.0
                if name == "animatecontrol":
                    # Immediate final-state application: deterministic headless
                    # fallback until the renderer gains a frame tween scheduler.
                    if ctrl is not None:
                        for key, value in zip(("x", "y", "width", "height"), args[-4:]):
                            ctrl.set(key, value)
                    return 0.0
            if name == "join":
                # this.join("classname") — same semantics as the global form
                # (the class merges into the calling script's VM).
                if args:
                    rt2.join_class(vm, to_str(args[0]))
                return 0.0
            if name == "destroy" and rt2.gui is not None:
                # ctrl.destroy() -- the object-method form (see the bare
                # destroy(ctrl) global form below for the other one).
                rt2.gui.destroy(obj)
                return 0.0
            if GuiPopUpEditCtrl is not None and isinstance(obj, GuiPopUpEditCtrl):
                if name in ("addrow", "add") and len(args) >= 2:
                    return obj.add_row(args[0], args[1])
                if name == "clear":
                    if rt2.gui is not None and rt2.gui._open_popup is obj:
                        rt2.gui._close_popup()
                    return obj.clear_rows()
                if name in ("getselectedrow", "getselected"):
                    return obj.get_selected_row()
                if name in ("getrowtext", "gettextbyid") and args:
                    return obj.get_row_text(args[0])
            # other object methods with no member function bound: no GS1
            # equivalent
            return NOT_HANDLED

        # GS2 GUI-controls builtins (showgui/GuiControl -- see gs2_gui.py's
        # module docstring). addcontrol()'s single argument is always "the
        # object this new-statement just constructed" (never a parent) --
        # GS2GuiManager infers nesting from create/addcontrol call order.
        if name == "addcontrol":
            if rt2.gui is not None:
                rt2.gui.addcontrol(args[0] if args else None)
            return 0.0

        if name in ("addcontainer", "addguicontainer"):
            if rt2.gui is not None and len(args) >= 2:
                rt2.gui.add_to(args[0], args[1])
            return 0.0

        if name in self.stubbed:
            return 0.0

        if name in ("screenx", "screeny"):
            game = getattr(rt2, "game_shell", None)
            camera = getattr(game, "camera", None)
            value = to_num(args[0]) if args else 0.0
            x = value if name == "screenx" else 0.0
            y = value if name == "screeny" else 0.0
            if len(args) > 1:
                x, y = to_num(args[0]), to_num(args[1])
            if camera is None:
                return value
            point = camera.world_to_screen(x, y)
            return float(point[0 if name == "screenx" else 1])

        if name in ("getmapx", "getmapy"):
            player = getattr(rt2.client, "player", None)
            pos = getattr(player, "x" if name == "getmapx" else "y", 0.0)
            return float(int(to_num(pos) // 64))

        if name == "getmusicfilename":
            game = getattr(rt2, "game_shell", None)
            manager = getattr(game, "sound_mgr", None)
            return to_str(getattr(manager, "_current_music", "") or "")

        if name == "getnearestplayers":
            player = getattr(rt2.client, "player", None)
            x = to_num(args[0]) if args else to_num(getattr(player, "x", 0))
            y = to_num(args[1]) if len(args) > 1 else to_num(getattr(player, "y", 0))
            return rt2.nearest_players(x, y)

        if name == "findimg":
            return rt2.find_image(vm, int(to_num(args[0]))) if args else 0.0

        if name == "enabledefaultcamera":
            game = getattr(rt2, "game_shell", None)
            if game is not None:
                game._camera_enabled = True
            return 0.0

        if name == "setzoom":
            game = getattr(rt2, "game_shell", None)
            if game is not None and args and getattr(game, "camera", None) is not None:
                game.camera.zoom = to_num(args[0])
            return 0.0

        if name in ("sendtext", "requesttext"):
            if rt2.client is not None and args:
                rt2.client.send_server_text(name == "requesttext", "\n".join(to_str(a) for a in args))
            return 0.0

        if name == "showgui":
            if rt2.gui is not None and args:
                rt2.gui.show(args[0])
            return 0.0

        if name == "hidegui":
            if rt2.gui is not None and args:
                rt2.gui.hide(args[0])
            return 0.0

        if name == "destroy":
            if rt2.gui is not None and args:
                rt2.gui.destroy(args[0])
            return 0.0

        if name == "settimer":
            # Floor at the reference client's 120Hz update tick, NOT the
            # legacy 0.05s: see TIMER_RESOLUTION. A prior wave clamped this
            # to 0.05 assuming -Test_Movement's setTimer(0.01) loop was
            # meant to tick at 20Hz (0.3 tiles/tick = the classic 6 tiles/s
            # walk) — but GS2Engine 1.8.3 (the exact package the C# client
            # pins) has no such floor, so per-frame ticking IS the reference
            # behavior, for movement speed included.
            v = to_num(args[0]) if args else 0.0
            if 0.0 < v < TIMER_RESOLUTION:
                v = TIMER_RESOLUTION
            rt2._timeouts[rt2._timeout_key(vm)] = max(0.0, v)
            return 0.0

        if name == "join":
            if args:
                rt2.join_class(vm, to_str(args[0]))
            return 0.0

        if name == "echo":
            text = to_str(args[0]) if args else ""
            rt2.echo_log.append(text)
            if len(rt2.echo_log) > 1000:      # scripts can echo in loops
                del rt2.echo_log[:-500]
            logger.info("GS2 echo: %s", text)
            return 0.0

        if name == "triggeraction":
            # triggeraction(x, y, action, params...) -> PLI_TRIGGERACTION
            if rt2.client is not None and len(args) >= 3:
                action = ",".join(_csv_flatten(args[2:]))
                rt2.client.triggeraction(action, x=to_num(args[0]), y=to_num(args[1]))
            return 0.0

        if name == "triggerserver":
            # triggerserver("gui"/"npc", target, params...): the first arg
            # picks the serverside target class and is NOT sent verbatim.
            # Wire format (GServer-v2 TriggerCommandHandlers.cpp):
            #   triggeraction 0,0,serverside,<weaponname>,<params...>
            #   triggeraction 0,0,servernpc,<npcname>,<params...>
            if rt2.client is not None and len(args) >= 2:
                prefix = ("servernpc" if to_str(args[0]).lower() == "npc"
                          else "serverside")
                action = ",".join([prefix] + _csv_flatten(args[1:]))
                rt2.client.triggeraction(action, x=0.0, y=0.0)
            return 0.0

        if name == "isobject":
            return 1.0 if (args and self.get_object(to_str(args[0])) is not None) else 0.0

        if name == "findweapon":
            wvm = rt2.vms["weapon"].get(to_str(args[0]).lower()) if args else None
            return wvm.this if wvm is not None else 0.0

        if name in ("setani", "setcharani"):
            # setcharani from an NPC script sets the NPC'S OWN animation —
            # piano/sign/furniture NPCs become visible exactly this way
            # (bomber v6 lobby: setcharani("sen_piano"), ("itsasign2")).
            # Route it through the GS1 host, which writes npc['gani'] for the
            # renderer; extra args are gani PARAM tokens, kept comma-joined
            # (render_entities._split_npc_gani splits them back off).
            # setani (v6 player builtin) and weapon-script setcharani keep
            # driving the local player below.
            if name == "setcharani" and vm is not None and rt2.gs1 is not None:
                kind, _key = rt2._timeout_key(vm)
                if kind == "npc":
                    joined = ",".join(to_str(a) for a in args).rstrip(",")
                    if joined:
                        rt2._gs1_command("setcharani", [joined], vm)
                    return 0.0
            # player animation (weapon scripts drive the local player)
            if rt2.client is not None and args:
                ani = to_str(args[0])
                try:
                    rt2.client.set_animation(ani)
                except Exception:
                    pass
                # Script-driven movement mode (disabledefmovement): the
                # renderer draws the local player from game.player_anim /
                # current_anim_name, which only the built-in input path
                # updates -- mirror the script's setani there or the player
                # slides around in the idle gani.
                game = getattr(rt2, "game_shell", None)
                if (game is not None and rt2.gs1 is not None
                        and not rt2.gs1.default_movement):
                    base = ani.split(",")[0].strip()
                    try:
                        game.player_anim.set_animation(
                            base,
                            int(to_num(getattr(rt2.client.player,
                                               "direction", 0))))
                        game.current_anim_name = base
                    except Exception:
                        pass
            return 0.0

        if name == "timevar2":
            return time.time()

        if name in ("getimgwidth", "getimgheight"):
            # Answered from the downloaded file's header; preloader-style
            # scripts poll this in a wait loop until the download lands, so
            # a miss also (re-)requests the file.
            fname = to_str(args[0]) if args else ""
            dims = rt2.image_size(fname) if fname else None
            if dims is None:
                return 0.0
            return float(dims[0] if name == "getimgwidth" else dims[1])

        if name == "tiletype":
            if rt2.client is not None and len(args) >= 2:
                from .tiletypes import get_tile_type
                x, y = int(to_num(args[0])), int(to_num(args[1]))
                tiles = getattr(rt2.client, "tiles", None)
                if tiles and 0 <= x < 64 and 0 <= y < 64:
                    return float(get_tile_type(tiles[y * 64 + x]))
            return 0.0

        # -- v6 C# client platform builtins ---------------------------------
        # Call-site evidence is the v6 bytecode disasms (job a34dbef5 tmp/):
        # -System, -System_Preloader, -Zoom, -warn, npc 10371.

        if name == "strequals":
            # npc 10371 onPlayerEnters:
            #   if (strequals("blank", player.ani)) setani("eye_bomber_idle0")
            # Result feeds OP_CONV_TO_FLOAT + OP_IF, so it must be 1/0.
            # Case-insensitive, matching the engine's string == convention
            # (VariableCollection lowercases; GS1 string compare ignores case).
            a = to_str(args[0]) if args else ""
            b = to_str(args[1]) if len(args) > 1 else ""
            return 1.0 if a.lower() == b.lower() else 0.0

        if name == "gettextwidth":
            # gettextwidth(zoom, font, styles, text) -> width in client px.
            # -warn uses it to centre eye_bomber_notice.png:
            #   wi = int((gettextwidth(.5,"Verdana","bc",msg) + 7) / 8);
            #   showimg(310, ..., screenwidth/2 - wi*4 - 20, 28)
            # so a good approximation only affects centring, never control
            # flow. Mirror the showtext render metric (render_entities.py
            # _render_showtext_rec: 16 px per zoom unit, same font cache).
            zoom = to_num(args[0]) if args else 1.0
            fontname = to_str(args[1]) if len(args) > 1 else ""
            style = to_str(args[2]) if len(args) > 2 else ""
            text = to_str(args[3]) if len(args) > 3 else ""
            size = max(8, int(16 * (zoom or 1.0)))
            game = getattr(rt2, "game_shell", None)
            if game is not None and hasattr(game, "_showtext_font"):
                try:
                    font = game._showtext_font(fontname or "Arial", size,
                                               "b" in style)
                    return float(font.size(text)[0])
                except Exception:
                    pass
            # headless fallback: mean glyph advance ~0.55em
            return float(len(text)) * size * 0.55

        if name == "getscalefactor":
            # -Zoom onCreated: this.maxscale = getScaleFactor() + 1, and the
            # desktop default for client.mobile_smoothzoom_* -> 1 on PC
            # (maxscale 2 matches -System's own scalefactor = 2).
            return 1.0

        if name == "getdevicemodel":
            # -Zoom uses it only as a client-flag name suffix
            # (client.mobile_smoothzoom_<model>): any stable, benign
            # desktop-ish token works.
            return "PC"

        if name in ("gameobject::find", "object::findanyobjectbytype"):
            # -System: cam = object::findanyobjectbytype(type::camera); then
            # cam.orthographic = true; cam.orthographicsize = 120; -- needs a
            # writable object with stable identity. -System_Preloader:
            # GameObject::Find("Logger") heads a discarded chain -- needs
            # non-null traversal. Never polled in a retry loop.
            key = to_str(args[0]) if args else ""
            return _engine_object(rt2, f"{name}:{key}".lower())

        if name == "quattro::transformextensions::getcomponents":
            # -System: cams = ...getcomponents(Type::Camera) -- assigned and
            # never read again; return a one-element list for shape-safety.
            key = to_str(args[0]) if args else ""
            return [_engine_object(rt2, f"component:{key}".lower())]

        if (name in ("setframetick", "adventure_setframetick",
                     "switchopengldevicescale", "setretinadisplaynoantialias")
                or name.startswith("quattro::debugtools::")):
            # Frame pacing / GL-scale / retina / exception-report toggles for
            # the C# client's renderer. Every observed call discards the
            # result (OP_INDEX_DEC at each site in -System, -System_Preloader,
            # -Zoom, npc 10371) -- inert by design.
            return 0.0

        # GS1 function surface (returns a value)
        if name in _GS1_FUNCTIONS and rt2.gs1 is not None:
            ctx = rt2._gs1_ctx(vm)
            res = rt2.gs1._host.call_function(name, args, ctx)
            if res is not UNSET:
                return res

        # GS1 command surface (side effects; returns 0)
        if name in _GS1_COMMANDS and rt2.gs1 is not None:
            rt2._gs1_command(name, args, vm)
            return 0.0

        return NOT_HANDLED


class ClientGS2:
    """Runs GS2 bytecode client-side. Mirrors ClientGS1's surface: load_*,
    trigger_event, process_timeouts, attach()."""

    def __init__(self, client=None, gs1=None):
        self.client = client
        self.gs1 = gs1                     # ClientGS1 runtime (shared host surface)
        self.host = GS2ClientHost(self)
        # kind -> {key(lowered str or npc id): GS2VM}
        self.vms: Dict[str, Dict[Any, GS2VM]] = {
            "weapon": {}, "npc": {}, "class": {}, "gani": {},
        }
        self.globals_store: Dict[str, Any] = {}
        self.player_object = _PlayerObject(self)
        self.level_object = GS2Object(name="level")
        self._flag_scopes: Dict[str, GS2Object] = {}
        # onPlayerEnters bookkeeping: which VMs got it for the current level
        self._entered_level: Optional[str] = None
        self._entered_vms: set = set()
        # GUI-controls tree (showgui/GuiControl); None when pygame isn't
        # installed (headless callers, e.g. game_tester's GameBot).
        self.gui = GS2GuiManager(rt2=self) if GS2GuiManager is not None else None
        self.game_shell = None
        self.echo_log: List[str] = []
        self._timeouts: Dict[tuple, float] = {}   # (kind, key) -> seconds left
        self._pending_joins: Dict[str, List[GS2VM]] = {}
        self._prev_bytecode_cb = None
        # Bytecode that arrived inside the client's packet loop, waiting to
        # be loaded/run from the game loop (see _on_bytecode).
        self._pending_bytecode: List[tuple] = []
        self._sleeping = False                    # a script sleep() is pumping update()
        self._coros: List[dict] = []
        self._active_coro_keys: set = set()
        self._pending_events: Dict[tuple, List[tuple]] = {}
        self._timer_accumulator = 0.0
        # script-driven movement wire sync (see _sync_script_position)
        self._pos_sync_last: Optional[tuple] = None
        self._pos_sync_next: float = 0.0

    def save_lines(self, filename: str, lines: list) -> bool:
        """Persist script lines beneath a server-scoped client cache directory."""
        from .prefs import config_dir
        import hashlib
        server = to_str(getattr(self.client, "server_name", "") or
                        getattr(self.client, "host", "") or "default")
        scope = hashlib.sha256(server.encode("utf-8")).hexdigest()[:16]
        leaf = Path(filename.replace("\\", "/")).name
        if not leaf or leaf in (".", "..") or "\x00" in leaf:
            return False
        if len(lines) > SAVE_LINES_MAX_LINES:
            return False
        text_lines = [to_str(line) for line in lines]
        if any(len(line) > SAVE_LINES_MAX_CHARS_PER_LINE for line in text_lines):
            return False
        payload = "\n".join(text_lines)
        payload_bytes = len(payload.encode("utf-8"))
        cache_dir = config_dir() / "client-cache" / scope
        target = cache_dir / leaf
        try:
            current_size = sum(
                path.stat().st_size for path in cache_dir.rglob("*") if path.is_file()
            ) if cache_dir.exists() else 0
            old_size = target.stat().st_size if target.is_file() else 0
            if current_size - old_size + payload_bytes > SAVE_LINES_CACHE_MAX_BYTES:
                return False
            cache_dir.mkdir(parents=True, exist_ok=True)
            target.write_text(payload, encoding="utf-8")
        except (OSError, ValueError):
            return False
        return True

    def nearest_players(self, x: float, y: float) -> list:
        """Return live other-player objects ordered by distance from (x, y)."""
        client = self.client
        if client is None:
            return []
        found = []
        for player_id, player in getattr(client, "players", {}).items():
            dx, dy = to_num(getattr(player, "x", 0)) - x, to_num(getattr(player, "y", 0)) - y
            distance = (dx * dx + dy * dy) ** 0.5
            item = GS2Object(name=f"player:{player_id}")
            for key, value in (("id", player_id), ("account", getattr(player, "account", "")),
                               ("nick", getattr(player, "nickname", "")), ("x", getattr(player, "x", 0)),
                               ("y", getattr(player, "y", 0)), ("distance", distance)):
                item.set(key, value)
            found.append((distance, item))
        return [item for _, item in sorted(found, key=lambda pair: pair[0])]

    def find_image(self, vm, index: int):
        """findimg(index) -> a LIVE view of the layer record (see
        _LayerImage). The prior detached-copy object silently dropped every
        `findimg(i).rotation += ...` / `.text = ...` write (the v6 bomber's
        CadavreTest cogs and debug readouts animate exclusively this way)."""
        if self.gs1 is None:
            return 0.0
        table = self.gs1._host._layer_store(self._gs1_ctx(vm))
        record = table.get(index) if table is not None else None
        if record is None:
            return 0.0
        obj = record.get("_findimg")
        # identity check: showtext REPLACES the rec dict for an index, so a
        # cached wrapper can point at a dead dict
        if not isinstance(obj, _LayerImage) or obj._rec is not record:
            obj = record["_findimg"] = _LayerImage(index, record)
        return obj

    # -- wiring --------------------------------------------------------------

    def attach(self):
        """Hook into the client: bytecode arrivals load into VMs, and inbound
        PLO_TRIGGERACTION fires onAction<name> handlers."""
        if self.client is None:
            return self
        self.client.gs2_host = self
        self._prev_bytecode_cb = self.client.on_gs2_bytecode
        self.client.on_gs2_bytecode = self._on_bytecode
        return self

    def _on_bytecode(self, kind: str, key, blob: bytes):
        if self._prev_bytecode_cb is not None:
            try:
                self._prev_bytecode_cb(kind, key, blob)
            except Exception:
                pass
        # This callback fires from inside client._handle_packet. Running the
        # script here (run_toplevel/onCreated) would execute VM code — which
        # may sleep() and pump update() — from inside the packet loop. Defer
        # to process_timeouts, which the game loop drives every frame.
        self._pending_bytecode.append((kind, key, blob))
        self.pump_pending()

    # -- loading -------------------------------------------------------------

    def load_bytecode(self, kind: str, key, blob: bytes) -> Optional[GS2VM]:
        """Parse a bytecode blob into a VM, register it, resolve pending
        class joins, and fire onCreated for weapons/NPCs. Returns the VM, or
        None if the blob does not parse (logged, never raises)."""
        norm_key = key.lower() if isinstance(key, str) else key
        try:
            vm = GS2VM(blob, name=f"{kind}:{key}", host=self.host)
        except Exception as e:  # GS2ContainerError/GS2DecodeError/anything
            logger.warning("GS2 %s %r: bytecode did not parse: %s", kind, key, e)
            return None

        vm_key = (kind, norm_key)
        # keep this. state across a re-send of the same script (same rule
        # ClientGS1.load_weapon follows)
        old = self.vms[kind].get(norm_key)
        if old is not None:
            self._cancel_vm_coroutines(old)
            vm.this = old.this
            vm.thiso = old.this
        else:
            # NPC scripts get the npc-dict-bridging this (bare x/y/nick/
            # headimg/... reads and writes reach the renderer's NPC store).
            this_cls = _NpcThisObject if kind == "npc" else _ThisObject
            vm.this = this_cls(self, vm_key, name=f"{kind}:{key}")
            vm.thiso = vm.this
        self.vms[kind][norm_key] = vm
        vm._gs2_kind, vm._gs2_key = vm_key
        vm._gs2_owner = vm_key

        if kind == "class":
            waiting = self._pending_joins.pop(norm_key, [])
            for joiner in waiting:
                self._attach_class(joiner, norm_key, vm)

        if kind in ("weapon", "npc"):
            # Toplevel runs on every (re)load, not just the first: idiomatic
            # scripts put join("class") calls in toplevel, and skipping it on
            # a re-send (e.g. a hot-reloaded/admin-edited weapon) left the
            # new VM's class attachments permanently empty -- rejoining here
            # rebuilds them via the same join_class() path the fresh-load
            # case uses. this. state already carries over via vm.this above,
            # so a re-send is a continuation of the same object, not a new
            # one: onCreated (constructor semantics, like GS1's load_weapon
            # never re-firing an equivalent hook) only fires the first time.
            vm.run_toplevel()
            if old is None and vm.has_function("onCreated"):
                self._run(vm, "onCreated")
        return vm

    # -- class joins ---------------------------------------------------------

    def join_class(self, vm: GS2VM, classname: str) -> bool:
        """join("classname"): merge the class's functions into the joining
        VM. If the class bytecode isn't here yet, request it (PLI_UPDATECLASS)
        and finish the join when it arrives."""
        cname = classname.lower()
        # already joined?
        for j in vm.joined:
            if getattr(j, "_gs2_key", None) == cname:
                return True

        cvm = self.vms["class"].get(cname)
        if cvm is None:
            blob = None
            if self.client is not None:
                blob = self.client.gs2_bytecode.get("class", {}).get(classname) or \
                       self.client.gs2_bytecode.get("class", {}).get(cname)
            if blob:
                cvm = self.load_bytecode("class", cname, blob)
        if cvm is not None:
            self._attach_class(vm, cname, cvm)
            return True

        # not available: request and remember
        self._pending_joins.setdefault(cname, []).append(vm)
        if self.client is not None:
            try:
                self.client.request_class_bytecode(classname)
            except Exception:
                pass
        return False

    def _attach_class(self, joiner: GS2VM, cname: str, class_vm: GS2VM):
        """Instantiate the class against the joiner: a fresh VM over the
        class bytecode sharing the joiner's this-object, so class methods
        read/write the same state."""
        inst = GS2VM(class_vm.container, name=f"class:{cname}", host=self.host)
        inst.this = joiner.this
        inst.thiso = joiner.thiso
        # ("class", cname) is kept for join-detection (join_class's "already
        # joined?" scan) and _gs1_ctx -- but a settimer() call executing on
        # this instance must resolve back to the joiner's own identity (see
        # _timeout_key), not the shared class name, since every joiner of
        # `cname` gets its own `inst` here.
        inst._gs2_kind = "class"
        inst._gs2_key = cname
        inst._gs2_owner = self._timeout_key(joiner)
        joiner.joined.append(inst)

    def _timeout_key(self, vm: GS2VM) -> tuple:
        """The (kind, key) identity a VM's settimer()/onTimeout state files
        under. A joined-class instance resolves to its joiner's own key
        (multiple joiners share one class's bytecode but never its timeout
        slot); a top-level weapon/npc/gani VM resolves to its own key."""
        return getattr(vm, "_gs2_owner",
                       (getattr(vm, "_gs2_kind", "weapon"),
                        getattr(vm, "_gs2_key", vm.name)))

    # -- events --------------------------------------------------------------

    def _run(self, vm: GS2VM, event: str, *args) -> None:
        key = self._timeout_key(vm)
        if key in self._active_coro_keys:
            pending = self._pending_events.setdefault(key, [])
            if len(pending) >= PENDING_EVENT_CAP:
                dropped = pending.pop(0)
                logger.debug("GS2 %s pending-event queue full; dropped %s",
                             vm.name, dropped[0])
            pending.append((event, args))
            return
        gen = vm.iter_call(event, *args)
        self._drive(gen, vm, key, event)

    def _event_finished(self, key: tuple) -> None:
        self._active_coro_keys.discard(key)
        pending = self._pending_events.get(key)
        if not pending:
            self._pending_events.pop(key, None)
            return
        event, args = pending.pop(0)
        if not pending:
            self._pending_events.pop(key, None)
        kind, vm_key = key
        vm = self.vms.get(kind, {}).get(vm_key)
        if vm is not None and vm.has_function(event):
            self._run(vm, event, *args)

    def _cancel_vm_coroutines(self, vm: GS2VM) -> None:
        key = self._timeout_key(vm)
        self._coros = [c for c in self._coros if c["key"] != key]
        self._active_coro_keys.discard(key)
        self._pending_events.pop(key, None)

    def _drive(self, gen, vm: GS2VM, key: tuple, event: str) -> None:
        try:
            delay = next(gen)
        except StopIteration:
            self._event_finished(key)
            return
        except Exception as e:
            self._event_finished(key)
            logger.warning("GS2 %s.%s aborted: %s", vm.name, event, e)
            return
        self._active_coro_keys.add(key)
        self._coros.append({"gen": gen, "vm": vm, "key": key,
                            "event": event, "remaining": float(delay)})

    def process_coroutines(self, dt: float) -> None:
        """Resume scripts whose cooperative sleep has elapsed."""
        if not self._coros:
            return
        still = []
        finished = []
        for coro in self._coros:
            coro["remaining"] -= dt
            if coro["remaining"] > 0:
                still.append(coro)
                continue
            try:
                coro["remaining"] = float(next(coro["gen"]))
                still.append(coro)
            except StopIteration:
                finished.append(coro["key"])
            except Exception as e:
                finished.append(coro["key"])
                logger.warning("GS2 %s.%s aborted: %s",
                               coro["vm"].name, coro["event"], e)
        self._coros = still
        for key in finished:
            self._event_finished(key)

    def trigger_event(self, event: str, *args) -> int:
        """Fire an event on every weapon/NPC VM that defines it. Returns the
        number of VMs that handled it."""
        n = 0
        for kind in ("weapon", "npc"):
            for vm in list(self.vms[kind].values()):
                if vm.has_function(event):
                    self._run(vm, event, *args)
                    n += 1
        return n

    def trigger_weapon_event(self, weapon: str, event: str, *args) -> bool:
        vm = self.vms["weapon"].get(weapon.lower())
        if vm is not None and vm.has_function(event):
            self._run(vm, event, *args)
            return True
        return False

    def trigger_weapon_fired(self, weapon: str) -> bool:
        """The player used this weapon (D key): onWeaponFired, falling back
        to the legacy onFired name."""
        for ev in ("onWeaponFired", "onFired"):
            if self.trigger_weapon_event(weapon, ev):
                return True
        return False

    def trigger_npc_event(self, npc_id, event: str, *args) -> bool:
        """Fire an event on one NPC's VM (touch/hit routing from the game
        layer). NPC VM keys keep the id type they arrived with, so try both
        int and str forms."""
        vms = self.vms["npc"]
        vm = vms.get(npc_id)
        if vm is None:
            vm = vms.get(str(npc_id))
        if vm is None:
            try:
                vm = vms.get(int(npc_id))
            except (TypeError, ValueError):
                pass
        if vm is not None and vm.has_function(event):
            self._run(vm, event, *args)
            return True
        return False

    def npc_has_event(self, npc_id, event: str) -> bool:
        """True if this NPC's VM defines the event (used by the touch
        handler's gate)."""
        vms = self.vms["npc"]
        vm = vms.get(npc_id) or vms.get(str(npc_id))
        if vm is None:
            try:
                vm = vms.get(int(npc_id))
            except (TypeError, ValueError):
                pass
        return vm is not None and vm.has_function(event)

    def flag_scope_object(self, name: str) -> GS2Object:
        """The GS2 view of a shared GS1 flag scope ('server'/'serverr'/
        'client'/'clientr'), created lazily and cached."""
        obj = self._flag_scopes.get(name)
        if obj is None:
            shared = self.gs1._shared if self.gs1 is not None else {}
            if name in ("client", "clientr"):
                scope = shared.setdefault("client", {})
                obj = _FlagScopeObject(name, scope,
                                       local_writes=(name == "clientr"))
            else:
                scope = shared.setdefault("server", {})
                prefix = "serverr." if name == "serverr" else ""
                obj = _FlagScopeObject(name, scope, prefix=prefix,
                                       local_writes=(name == "serverr"))
            self._flag_scopes[name] = obj
        return obj

    def handle_triggeraction(self, action_csv: str):
        """Inbound PLO_TRIGGERACTION: fire onAction<name>(params...) --
        the GS2 counterpart of the GS1 `action<name>` routing in client.py."""
        if not action_csv:
            return
        parts = action_csv.split(",")
        name = parts[0].strip()
        if name.lower() == "clientside" and len(parts) >= 2:
            # Server-pushed weapon trigger (triggerclient on the serverside):
            # "clientside,<weaponname>,<params...>" fires onActionClientSide
            # on the NAMED weapon only, params[] = the remaining args.
            self.trigger_weapon_event(parts[1], "onActionClientSide",
                                      *parts[2:])
            return
        if name:
            self.trigger_event("onAction" + name, *parts[1:])

    def image_size(self, fname: str):
        """(w, h) of an image the client has (downloaded or on disk), or
        None. A miss requests the download once so a polling script's next
        check can succeed."""
        client = self.client
        if client is None:
            return None
        data = client.get_file(fname)
        if data is None:
            if (fname not in client._pending_files
                    and fname not in client._failed_files):
                try:
                    client.request_file(fname)
                except Exception:
                    pass
            return None
        return _image_size(data)

    def pump_pending(self):
        """Load (and run toplevel/onCreated of) bytecode queued by
        _on_bytecode — a no-op while the client's packet loop is running."""
        if self.client is not None and getattr(self.client, "_in_update", False):
            return
        while self._pending_bytecode:
            kind, key, blob = self._pending_bytecode.pop(0)
            self.load_bytecode(kind, key, blob)

    def forget_npc(self, npc_id):
        """Drop all VM state for a despawned NPC (PLO_NPCDEL), mirroring
        ClientGS1.forget_npc. Without this the NPC's VM lingers in self.vms
        (so a reused npc-id inherits its this-state and skips onCreated),
        its pending settimer keeps firing onTimeout against a vanished NPC,
        and any parked coroutine keeps running."""
        for key in (npc_id, str(npc_id)):
            vm = self.vms["npc"].pop(key, None)
            if vm is None:
                continue
            self._entered_vms.discard(id(vm))
            tkey = ("npc", key)
            self._timeouts.pop(tkey, None)
            self._cancel_vm_coroutines(vm)

    def pump_level_events(self):
        """Fire onPlayerEnters once per VM per level visit: weapons always,
        NPC VMs once their NPC is present in the player's current level.
        Called every frame (from process_timeouts), so late-streaming
        bytecode gets its entry event when it arrives -- the classic-bomber
        lesson: on slow servers most NPCs stream in AFTER level entry and
        would otherwise never run their setup (setshape2 collision shapes,
        showimg layers, setTimer arming)."""
        client = self.client
        if client is None:
            return
        level = getattr(client, "_current_level_name", "") or ""
        if not level:
            return
        if level != self._entered_level:
            changed_level = self._entered_level is not None
            self._entered_level = level
            self._entered_vms = set()
            if changed_level:
                npc_keys = {c["key"] for c in self._coros
                            if c["key"][0] == "npc"}
                self._coros = [c for c in self._coros
                               if c["key"][0] != "npc"]
                self._active_coro_keys.difference_update(npc_keys)
                for key in npc_keys:
                    self._pending_events.pop(key, None)
        npcs = getattr(client, "npcs", {})
        for kind in ("weapon", "npc"):
            for key, vm in list(self.vms[kind].items()):
                if id(vm) in self._entered_vms:
                    continue
                if kind == "npc":
                    npc = npcs.get(key)
                    if npc is None and isinstance(key, str):
                        try:
                            npc = npcs.get(int(key))
                        except ValueError:
                            npc = None
                    if not isinstance(npc, dict):
                        continue          # not streamed as a level NPC (yet)
                    npc_level = npc.get("_level") or npc.get("level")
                    if npc_level and npc_level != level:
                        continue          # belongs to another level
                self._entered_vms.add(id(vm))
                if vm.has_function("onPlayerEnters"):
                    self._run(vm, "onPlayerEnters")

    def process_timeouts(self, dt: float):
        """Count down each VM's pending timeout and fire onTimeout when it
        elapses (handlers typically re-arm via settimer/this.timeout).

        vm_key here is always a top-level weapon/npc/gani VM's own key --
        never ("class", cname) -- because settimer()/this.timeout both file
        under the *joiner's* identity (see _timeout_key), so this always
        resolves to the actual joiner instance, not the shared class
        definition. onTimeout may still be defined on a joined class; call()
        finds it there via has_function()'s joined-VM fallback."""
        self.pump_pending()
        self.pump_level_events()
        for kind in ("weapon", "npc"):
            for vm in list(self.vms[kind].values()):
                if vm.has_function("onUpdate"):
                    self._run(vm, "onUpdate")
        self._timer_accumulator = min(
            self._timer_accumulator + max(0.0, dt), TIMER_BACKLOG_CAP)
        steps = int(self._timer_accumulator / TIMER_RESOLUTION)
        self._timer_accumulator -= steps * TIMER_RESOLUTION
        for _ in range(steps):
            self._process_timeout_step(TIMER_RESOLUTION)
        self._sync_script_position()

    def _process_timeout_step(self, dt: float):
        """Advance script timers by one fixed update quantum."""
        for vm_key in list(self._timeouts):
            t = self._timeouts[vm_key] - dt
            if t > 0:
                self._timeouts[vm_key] = t
                continue
            del self._timeouts[vm_key]      # handler may re-arm
            kind, key = vm_key
            vm = self.vms.get(kind, {}).get(key)
            if vm is None:
                continue
            # Don't fire the timer of an NPC that has moved to another level
            # (ghost effects from a stale settimer). A truly despawned NPC's
            # VM is already gone via forget_npc (PLO_NPCDEL); an NPC not
            # tracked in client.npcs at all is left alone (weapons and
            # test/headless VMs have no NPC record and must still tick).
            if kind == "npc" and self._npc_in_other_level(key):
                continue
            if vm.has_function("onTimeout"):
                self._run(vm, "onTimeout")

    def _sync_script_position(self):
        """While a script drives movement (disabledefmovement), its player.x/
        player.y/player.dir writes only touch local state -- nothing walks
        the built-in Client.move() path that puts movement on the wire, so
        other players saw us frozen at the spawn point. Broadcast position/
        direction changes ourselves, at most every 0.05s (one script tick)."""
        client, gs1 = self.client, self.gs1
        if (client is None or gs1 is None or gs1.default_movement
                or not getattr(client, "connected", False)):
            return
        p = getattr(client, "player", None)
        if p is None:
            return
        snap = (round(float(getattr(p, "x", 0.0)), 3),
                round(float(getattr(p, "y", 0.0)), 3),
                int(to_num(getattr(p, "direction", 0))))
        if snap == self._pos_sync_last:
            return
        now = time.time()
        if now < self._pos_sync_next:
            return
        self._pos_sync_next = now + 0.05
        self._pos_sync_last = snap
        try:
            client.send_position()
        except Exception:
            pass

    def _npc_in_other_level(self, key) -> bool:
        """True only if this NPC is present in client.npcs AND tagged to a
        level other than the player's current one."""
        client = self.client
        if client is None:
            return False
        npcs = getattr(client, "npcs", {})
        npc = npcs.get(key)
        if npc is None and isinstance(key, str):
            try:
                npc = npcs.get(int(key))
            except ValueError:
                npc = None
        if not isinstance(npc, dict):
            return False
        level = getattr(client, "_current_level_name", "") or ""
        npc_level = npc.get("_level") or npc.get("level")
        return bool(npc_level and level and npc_level != level)

    # -- GS1 host plumbing -----------------------------------------------------

    def _gs1_ctx(self, vm: Optional[GS2VM]):
        """A minimal ctx shim for GS1ClientHost (it only reads a handful of
        attributes). Weapon VMs get a per-script prog-key so their showimg
        layers land in the shared _weapon_imgs store the renderer draws.

        Joined-class instances resolve to their JOINER's identity (same rule
        as _timeout_key): class code running for an NPC must act on that
        NPC's dict (setcharani/showimg/setshape from a join()ed class), not
        as an anonymous shared "class" weapon."""
        vm_key = None
        if vm is not None:
            vm_key = getattr(vm, "_gs2_owner", None)
        kind, key = vm_key if vm_key else ("weapon", "?")
        npc = None
        if kind == "npc" and self.client is not None:
            npc = getattr(self.client, "npcs", {}).get(key)
        return SimpleNamespace(
            this_obj=npc,
            _npc_id=key if kind == "npc" else -1,
            _is_weapon=(kind != "npc"),
            _prog_key=f"gs2_{kind}_{key}",
            tokenize_tokens=[],
        )

    def _gs1_command(self, name: str, args: List[Any], vm: Optional[GS2VM]):
        if self.gs1 is None:
            return
        self.gs1._host.call_command(name, list(args), self._gs1_ctx(vm))
