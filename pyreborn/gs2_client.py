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
from reborn_protocol.gs2 import GS2VM, GS2Host, GS2Object, NOT_HANDLED, to_num, to_str
from .gs1_client import PLAYER_ATTR

logger = logging.getLogger(__name__)

# Limits for untrusted script writes to each server-scoped cache directory.
SAVE_LINES_MAX_LINES = 4096
SAVE_LINES_MAX_CHARS_PER_LINE = 4096
SAVE_LINES_CACHE_MAX_BYTES = 5 * 1024 * 1024

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
})


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
            self._rt2._timeouts[self._vm_key] = max(0.0, to_num(value))
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
            owed = min(rt2._sleep_debt.get(id(vm), 0.0) + secs, 1.0)
            wait = min(owed, 0.05)
            time.sleep(wait)
            rt2._sleep_debt[id(vm)] = owed - wait
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
            rt2._timeouts[rt2._timeout_key(vm)] = (
                max(0.0, to_num(args[0])) if args else 0.0)
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
                action = ",".join(to_str(a) for a in args[2:])
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
                action = ",".join([prefix] + [to_str(a) for a in args[1:]])
                rt2.client.triggeraction(action, x=0.0, y=0.0)
            return 0.0

        if name == "isobject":
            return 1.0 if (args and self.get_object(to_str(args[0])) is not None) else 0.0

        if name == "findweapon":
            wvm = rt2.vms["weapon"].get(to_str(args[0]).lower()) if args else None
            return wvm.this if wvm is not None else 0.0

        if name in ("setani", "setcharani"):
            # player animation (weapon scripts drive the local player)
            if rt2.client is not None and args:
                try:
                    rt2.client.set_animation(to_str(args[0]))
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
        # GUI-controls tree (showgui/GuiControl); None when pygame isn't
        # installed (headless callers, e.g. game_tester's GameBot).
        self.gui = GS2GuiManager(rt2=self) if GS2GuiManager is not None else None
        self.game_shell = None
        self.echo_log: List[str] = []
        self._timeouts: Dict[tuple, float] = {}   # (kind, key) -> seconds left
        self._vm_keys: Dict[int, tuple] = {}      # id(vm) -> (kind, key)
        # id(joined-class instance) -> the joiner's own (kind, key). Multiple
        # weapon/npc VMs can join the same class, each getting its own
        # instantiated GS2VM over the shared class bytecode (_attach_class);
        # those instances all carry _vm_keys[id(inst)] == ("class", cname)
        # for join-detection purposes, but settimer()/timeout resolution
        # must use the *joiner's* identity or two joiners of one class
        # clobber each other's single ("class", cname) timeout slot. See
        # _timeout_key().
        self._vm_owners: Dict[int, tuple] = {}
        self._pending_joins: Dict[str, List[GS2VM]] = {}
        self._prev_bytecode_cb = None
        # Bytecode that arrived inside the client's packet loop, waiting to
        # be loaded/run from the game loop (see _on_bytecode).
        self._pending_bytecode: List[tuple] = []
        self._sleeping = False                    # a script sleep() is pumping update()
        self._sleep_debt: Dict[int, float] = {}   # id(vm) -> unpaid in-packet sleep() time

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
        if self.gs1 is None:
            return 0.0
        table = self.gs1._host._layer_store(self._gs1_ctx(vm))
        record = table.get(index)
        if record is None:
            return 0.0
        obj = GS2Object(name=f"image:{index}")
        for key, value in record.items():
            obj.set(key, value)
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
            vm.this = old.this
            vm.thiso = old.this
        else:
            vm.this = _ThisObject(self, vm_key, name=f"{kind}:{key}")
            vm.thiso = vm.this
        self.vms[kind][norm_key] = vm
        self._vm_keys[id(vm)] = vm_key

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
                vm.call("onCreated")
        return vm

    # -- class joins ---------------------------------------------------------

    def join_class(self, vm: GS2VM, classname: str) -> bool:
        """join("classname"): merge the class's functions into the joining
        VM. If the class bytecode isn't here yet, request it (PLI_UPDATECLASS)
        and finish the join when it arrives."""
        cname = classname.lower()
        # already joined?
        for j in vm.joined:
            if self._vm_keys.get(id(j), ("", ""))[1] == cname:
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
        self._vm_keys[id(inst)] = ("class", cname)
        self._vm_owners[id(inst)] = self._vm_keys.get(id(joiner), ("weapon", joiner.name))
        joiner.joined.append(inst)

    def _timeout_key(self, vm: GS2VM) -> tuple:
        """The (kind, key) identity a VM's settimer()/onTimeout state files
        under. A joined-class instance resolves to its joiner's own key
        (multiple joiners share one class's bytecode but never its timeout
        slot); a top-level weapon/npc/gani VM resolves to its own key."""
        owner = self._vm_owners.get(id(vm))
        if owner is not None:
            return owner
        return self._vm_keys.get(id(vm), ("weapon", vm.name))

    # -- events --------------------------------------------------------------

    def trigger_event(self, event: str, *args) -> int:
        """Fire an event on every weapon/NPC VM that defines it. Returns the
        number of VMs that handled it."""
        n = 0
        for kind in ("weapon", "npc"):
            for vm in list(self.vms[kind].values()):
                if vm.has_function(event):
                    vm.call(event, *args)
                    n += 1
        return n

    def trigger_weapon_event(self, weapon: str, event: str, *args) -> bool:
        vm = self.vms["weapon"].get(weapon.lower())
        if vm is not None and vm.has_function(event):
            vm.call(event, *args)
            return True
        return False

    def trigger_weapon_fired(self, weapon: str) -> bool:
        """The player used this weapon (D key): onWeaponFired, falling back
        to the legacy onFired name."""
        for ev in ("onWeaponFired", "onFired"):
            if self.trigger_weapon_event(weapon, ev):
                return True
        return False

    def handle_triggeraction(self, action_csv: str):
        """Inbound PLO_TRIGGERACTION: fire onAction<name>(params...) --
        the GS2 counterpart of the GS1 `action<name>` routing in client.py."""
        if not action_csv:
            return
        parts = action_csv.split(",")
        name = parts[0].strip()
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
        for vm_key in list(self._timeouts):
            t = self._timeouts[vm_key] - dt
            if t > 0:
                self._timeouts[vm_key] = t
                continue
            del self._timeouts[vm_key]      # handler may re-arm
            kind, key = vm_key
            vm = self.vms.get(kind, {}).get(key)
            if vm is not None and vm.has_function("onTimeout"):
                vm.call("onTimeout")

    # -- GS1 host plumbing -----------------------------------------------------

    def _gs1_ctx(self, vm: Optional[GS2VM]):
        """A minimal ctx shim for GS1ClientHost (it only reads a handful of
        attributes). Weapon VMs get a per-script prog-key so their showimg
        layers land in the shared _weapon_imgs store the renderer draws."""
        vm_key = self._vm_keys.get(id(vm)) if vm is not None else None
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
