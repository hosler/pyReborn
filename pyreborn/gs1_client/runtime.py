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
import math

from reborn_protocol.gs1.runtime import Context
from reborn_protocol.gs1 import ast
from reborn_protocol.gs1.interp import PREEMPTED
from reborn_protocol.gs1.lexer import tokenize
from reborn_protocol.gs1.parser import Parser
from reborn_protocol.gs1.values import to_num, to_str

from ..particles import ParticleEmitter
from ..tiletypes import TileType, get_tile_type, tilestype_for_level, type_is_blocking
from .host import GS1ClientHost
from .objects import _ClientScopeVarStore, _PlayerFlagScope, _RefNamespaceInterpreter, _ServerFlagScope
from .registry import _DEFAULT_IMAGE_PX, _GS1_PREEMPT_BOARD_WAIT_FRAMES, _GS1_STATEMENTS_PER_SLICE, _report_gs1_error



logger = logging.getLogger(__name__)


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
        self._gs1_classes: dict = {}
        self._pending_class_joins: dict = {}
        self._requested_classes: set = set()
        self._rejected_class_payloads: set = set()
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
        self._callnpc_depth = 0        # nesting guard, see _CALLNPC_MAX_DEPTH
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
        # optional (x, y) -> tile id for WORLD coords, wired to the pygame
        # client's gmap-aware CollisionMixin._get_tile_at. The fallback below
        # only knows one 64x64 level, so inside a gmap every probe lands
        # outside 0..63 and answers "not a wall".
        self.tile_source = None
        # optional (image_name) -> (w_px, h_px) or None, wired to the pygame
        # sprite manager. Sizes an image NPC's default blocking/touch
        # footprint; an unset hook or unknown image falls back to
        # _DEFAULT_IMAGE_PX square (the engine's unsized-texture default).
        self.image_size_source = None
        # optional (image_name, px, py) -> bool/None: is that image pixel
        # opaque (None = unknown, treated opaque)? The reference footprint is
        # per-pixel — a wall/touch probe inside the image rect resolves to
        # !isPixelTransparent (TServerNPC::isOnNPC, Preagonal/FourPlay/
        # quattroplay/src/TServerNPC.cpp:2158-2196) — so a mostly-transparent
        # decoration only blocks where its art actually is.
        self.image_opaque_source = None
        # optional () -> (x, y) giving the mouse cursor in WORLD TILE coords,
        # wired to the pygame client's camera (game/input.py). Unset (headless
        # harnesses) answers the player's own position, which makes
        # `mousescreenx - (mousex - playerx) * 16` collapse to the cursor
        # pixel rather than to garbage — see mouse_world().
        self.mouse_world_source = None
        self._freeze_until = 0.0       # monotonic deadline used by `playerfreezetime`
        self.selected_weapon_index = lambda: 0
        self.keys_dir: set = set()
        self.keys_raw: set = set()
        self._keys_raw_prev: set = set()  # previous frame, for keydown2 edge
        self._shape_blocks: set = set()   # (tx,ty) cells blocked via setshape2
        self._shape_block_owners: dict = {}  # npc_id -> set of (tx,ty) it contributed
        # (tx,ty) -> tile TYPE published by a setshape2 array (see
        # _update_shape_blocks / npc_tile_type).
        self._shape_types: dict = {}
        self._shape_type_owners: dict = {}   # npc_id -> {(tx,ty): type}
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
        self.on_say2 = None
        self.on_setani = None
        self.on_message = None
        self.on_setmap = None
        self.on_triggeraction = None
        self.on_setplayerprop = None
        self.on_shoot = None
        self.on_freezeplayer = None
        self.on_warp = None
        self.on_setminimap = None
        self.on_setfocus = None
        self.on_toweapons = None
        self.on_tiledef = None
        self.on_seteffect = None
        self.on_putleaps = None
        # scripted-combat family (putbomb/putexplosion/setbackpal wave):
        # on_putbomb(power, x, y, fuse_s)   -- spawn a level bomb visual
        # on_removebomb(bomb, explode)      -- drop bombs[i]; explode=True is
        #                                      explodebomb (burst now)
        # on_putexplosion(power, radius, x, y) -- burst visual/sound/bushes
        # on_setbackpal(filename)           -- tileset palette swap
        self.on_putbomb = None
        self.on_removebomb = None
        self.on_putexplosion = None
        self.on_setbackpal = None
        # () -> ordered list of live bomb dicts ({'x','y','power','time',
        # 'fuse_time'}). The pygame shell wires this to its active_bombs
        # registry (game/render_effects.py), which holds BOTH local and wire
        # bombs in placement order -- that order is the script-visible
        # bombs[] index. Headless fallback: the wire-echo dict client.bombs.
        self.bombs_source = None
        # attachplayertoobj state: {'npc_id', 'last_x', 'last_y'} or None.
        # last_* is the NPC's position when we last propagated its movement
        # to the player (see the delta step in process_timeouts).
        self._player_attach = None

    def board_ready(self) -> bool:
        """Is the CURRENT level's board in hand?

        `client.tiles` is the active render/collision board and lags the
        optimistic `_current_level_name` flip a warp performs — on a
        first-visit level it still holds the PREVIOUS level's tiles until
        PLO_BOARDPACKET lands (handlers/level.py:238-240 re-points both
        together). Scripts must not run against either state: a missing board
        and another room's board are equally wrong answers, and classic
        Bomber's room0.nw deletes furniture on the strength of them (see
        GS1NoBoard). Gates `tiles[x,y]` and the playerenters fire in
        game/setup.py.
        """
        cl = self.client
        if cl is None:
            return False
        lvl = getattr(cl, "_current_level_name", "")
        tiles = getattr(cl, "tiles", None)
        if not lvl or not tiles or len(tiles) < 64 * 64:
            return False
        return getattr(cl, "_tiles_level_name", "") == lvl

    def _parse_cached(self, name, code):
        """Parse `code`, memoized on the source text. A level re-entry reloads
        every NPC/weapon script from scratch (clear() drops the progs), and
        re-parsing the bomber lobby's 67 NPCs + weapons measured ~300ms of an
        ~800ms single-frame re-entry stall. Programs are immutable once built
        (the interpreter never mutates AST nodes; entries already reuse one
        prog across runs), so sharing them by source is safe. Parse failures
        are cached as None too, so a broken script isn't re-parsed each visit.

        Both failure modes are reported at WARNING, because both used to be
        invisible: a LexError killed an NPC outright behind a debug-level log,
        and the parser's panic-mode recovery dropped statements with no signal
        at all — which is how a lookahead bug silently truncated classic
        Bomber's furniture catalog to its first entry for as long as we had
        the level."""
        cache = self._parse_cache
        if code in cache:
            return cache[code]
        try:
            parser = Parser(tokenize(code))
            prog = parser.parse_program()
            if parser.errors:
                logger.warning(
                    "client GS1 script %s: %d statement(s) dropped by parse "
                    "recovery; first: %s", name, len(parser.errors),
                    parser.errors[0])
        except Exception as exc:
            logger.warning("failed to parse client GS1 script %s: %s", name, exc,
                           exc_info=logger.isEnabledFor(logging.DEBUG))
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

    def join_class(self, ctx, class_name):
        """Merge a fetched GS1 class into the program that issued ``join``."""
        cname = class_name.strip().lower()
        key = getattr(ctx, "_prog_key", None)
        entry = self._progs.get(key)
        if not cname or entry is None:
            return False
        joined = entry.setdefault("joined_classes", set())
        if cname in joined:
            return True
        class_prog = self._gs1_classes.get(cname)
        if class_prog is not None:
            entry["prog"] = ast.Program(
                list(entry["prog"].body) + list(class_prog.body))
            joined.add(cname)
            return True
        waiters = self._pending_class_joins.setdefault(cname, set())
        waiters.add(key)
        if cname not in self._requested_classes and self.client is not None:
            self._requested_classes.add(cname)
            try:
                self.client.request_class_bytecode(class_name)
            except Exception:
                pass
        return False

    def receive_class_source(self, class_name, source):
        """Supply a class response and complete every pending GS1 join."""
        cname = to_str(class_name).strip().lower()
        if not cname:
            return False
        if isinstance(source, bytes):
            if b"\x00" in source:
                if cname not in self._rejected_class_payloads:
                    self._rejected_class_payloads.add(cname)
                    logger.warning(
                        "ignored non-source GS1 class payload for %s", cname)
                self._requested_classes.discard(cname)
                return False
            try:
                source = source.decode("latin-1")
            except Exception:
                self._requested_classes.discard(cname)
                return False
        prog = self._parse_cached("class_" + cname, to_str(source))
        if prog is None:
            self._requested_classes.discard(cname)
            return False
        self._gs1_classes[cname] = prog
        completed = []
        for key in self._pending_class_joins.pop(cname, set()):
            entry = self._progs.get(key)
            if entry is None or cname in entry.setdefault("joined_classes", set()):
                continue
            entry["prog"] = ast.Program(
                list(entry["prog"].body) + list(prog.body))
            entry["joined_classes"].add(cname)
            completed.append(entry)
        for entry in completed:
            self._run(entry, "created")
        return True

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
        and they're keyed off any NPC-touch path (npc_id -1).

        Returns True when this registers a NEW weapon (or replaces its script)
        — the caller should then fire its `created` event, like a real client
        compiling a freshly added weapon. GTA's system weapons set their
        install-handshake flags (gotsys2/gotclock) in `created`; without it the
        -System weapon bounces the player back to splashscreen.nw forever."""
        key = f"weapon_{name}"
        is_new = self.scripts.get(key) != code
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
        return is_new

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
        self._shape_types.clear()
        self._shape_type_owners.clear()
        self.drop_level_weapon_layers()  # GS1 weapon layers are re-drawn per level
        self._coros.clear()             # abandon suspended scripts from old level
        self._active_coro_keys.clear()
        # attachplayertoobj does not survive the level: the ride NPC lives in
        # the level we just left (process_attachment would self-detach when
        # client.npcs turns over anyway; this just makes it deterministic).
        self._player_attach = None
        # default_movement is deliberately NOT reset here: dis/enabledefmovement
        # is PLAYER-scoped state, not level-scoped. In the reference client the
        # only setDefaultMovement(true) resets are session boundaries — leaving
        # the server (TPlayer::resetAttributes, FourPlay quattroplay
        # src/TPlayer.cpp:1549, called from TServerList.cpp:265), entering/
        # restarting one (TPlayer::loadStartLevel, src/TPlayer.cpp:5573) and
        # server-side player init (TServerPlayer.cpp:239) — never a level
        # change. A per-level reset here silently re-enabled native movement on
        # LTTP, whose GS2 -Player/Movement calls disabledefmovement ONCE in
        # onCreated: the first level announce turned the flag back on, gating
        # off the whole scripted-movement probe chain (seam announces, link
        # warps) and double-driving movement. Our session boundary is a fresh
        # ClientGS1 (one per GameClient per server connection).

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
        self._forget_shape_types(npc_id)

    def trigger_event(self, event, name=None):
        names = [name] if name is not None else list(self._progs)
        for n in names:
            entry = self._progs.get(n)
            if entry and entry["prog"] is not None:
                self._run(entry, event)

    def trigger_npc_event(self, npc_id, event):
        # An NPC event may run `toweapons`, which adds a weapon program.
        for entry in list(self._progs.values()):
            if entry["npc_id"] == npc_id and entry["prog"] is not None:
                self._run(entry, event)

    #: callnpc/callweapon nesting cap, one shared counter (an NPC and a weapon
    #: that call each other cycle just as happily as two NPCs). Two scripts
    #: calling each other would otherwise recurse until Python's own stack
    #: limit, since each hop builds a fresh Context with a fresh step budget.
    #: Server scripts are untrusted (same reasoning as the outbound-flag token
    #: bucket above); nothing legitimate chains this deep -- Bomber's room
    #: controller is one hop, and so is its tailor NPC -> -tailor weapon.
    _CALLNPC_MAX_DEPTH = 8

    def call_npc(self, npc_id, event, params=()):
        """`callnpc`: run another NPC's `event` with `params` bound to #p(n).

        Shares _proj_params with actionprojectile2/keypressed, but unlike
        those this fires from INSIDE a running script, so the previous
        binding is restored rather than cleared — a keypressed handler that
        calls an NPC must still see its own #p() afterwards."""
        if self._callnpc_depth >= self._CALLNPC_MAX_DEPTH:
            logger.warning("callnpc nesting limit reached at npc %s/%s",
                           npc_id, event)
            return
        prev = self._proj_params
        self._proj_params = list(params)
        self._callnpc_depth += 1
        try:
            self.trigger_npc_event(npc_id, event)
        finally:
            self._callnpc_depth -= 1
            self._proj_params = prev

    def call_weapon(self, weapon_name, event, params=()):
        """`callweapon`: run a weapon script's `event` with `params` bound to
        #p(n). Same #p() save/restore and the same nesting guard as call_npc:
        this also fires from INSIDE a running script, and a weapon that calls
        back into the NPC that called it is a cycle nothing else bounds."""
        if self._callnpc_depth >= self._CALLNPC_MAX_DEPTH:
            logger.warning("callweapon nesting limit reached at %s/%s",
                           weapon_name, event)
            return
        prev = self._proj_params
        self._proj_params = list(params)
        self._callnpc_depth += 1
        try:
            self.trigger_event(event, name=f"weapon_{weapon_name}")
        finally:
            self._callnpc_depth -= 1
            self._proj_params = prev

    def npc_save_slots(self, npc_id, create=False):
        """The `save[0..9]` slots of the NPC with `npc_id`: a list (empty until
        it first writes one, unless `create`), or None when no such NPC script
        is loaded — "this NPC has written no slots" and "there is no such NPC"
        are different answers and callers act on the difference.

        GS1 keeps save[] on the NPC itself; our engine keeps it in that NPC's
        script scope, because that is where the interpreter's `this.save[i]`
        special case (interp.py:832) puts it — the two spellings are the same
        storage, and `npcs[i].save[j]` has to read it from outside."""
        for entry in self._progs.values():
            if entry.get("npc_id") == npc_id and not entry.get("is_weapon"):
                this = entry["scopes"]["this"]
                if create:
                    return this.setdefault("save", [0.0] * 10)
                return this.get("save") or []
        return None

    def _update_shape_blocks(self, npc_id, npc, w, h, flags):
        """Translate an NPC's setshape/setshape2 geometry into world-tile state,
        anchored at the NPC's current (x, y) — same convention
        npc_handler.NPCHandler uses for touch shapes.

        A setshape2 array is a per-cell TILE TYPE table, not a blocking mask:
        `TServerNPC::getTileType` (Preagonal/FourPlay/quattroplay/src/
        TServerNPC.cpp:2016-2040) indexes the array by the offset from the
        NPC's origin and returns the cell verbatim, and
        `TServerLevel::getTileType` (TServerLevel.cpp:688-708) lets any NPC
        answer above 1 OVERRIDE the board's own type. Recording only the
        blocking value 22 (the arena's falling choc blocks, the only one we
        had a use for) silently discarded every other type: classic Bomber's
        room controller publishes 32 cells of type 3 (CHAIR) over the whole
        64x64 room via `setshape2 64,64,obj`, and dropping them is why the
        furniture chairs never seated anyone. `npc_tile_type` is the reader.

        Re-derives this NPC's contribution from scratch each call so re-running
        setshape2 (e.g. NPC 161's per-frame falling choc blocks during the
        arena's sudden-death `hurryup`) keeps it in sync, without disturbing
        other NPCs' contributions."""
        old = self._shape_block_owners.pop(npc_id, None)
        if old:
            self._shape_blocks -= old
        self._forget_shape_types(npc_id)
        if not flags or w <= 0 or h <= 0:
            return
        ax = int(to_num(npc.get('x', 0))) if isinstance(npc, dict) else 0
        ay = int(to_num(npc.get('y', 0))) if isinstance(npc, dict) else 0
        mine = set()
        types = {}
        for i, flag in enumerate(flags):
            ttype = int(to_num(flag))
            # Only >1 overrides the board (TServerLevel.cpp:694-696). Below
            # that the array is saying "nothing here", and the room controller
            # also parks its own private markers (-1..-9) in the same cells.
            if ttype <= 1:
                continue
            col, row = i % w, i // w
            cell = (ax + col, ay + row)
            types[cell] = ttype
            # A shape cell WALLS at type >= 20, not just 22: the reference
            # wall test on a shape-2 NPC is getTileType(x, y) >= 20
            # (TServerNPC::isOnNPC, Preagonal/FourPlay/quattroplay/src/
            # TServerNPC.cpp:2199-2213; board walltile uses the same > 0x13
            # threshold, TServerLevel.cpp:742).
            if ttype >= 20:
                mine.add(cell)
        if mine:
            self._shape_blocks |= mine
            self._shape_block_owners[npc_id] = mine
        if types:
            self._shape_types.update(types)
            self._shape_type_owners[npc_id] = types

    def _forget_shape_types(self, npc_id):
        """Drop one NPC's tile-type cells, restoring any cell another NPC also
        publishes (two shape NPCs blanket the same 64x64 room in Bomber, so
        cells genuinely overlap)."""
        mine = self._shape_type_owners.pop(npc_id, None)
        if not mine:
            return
        for cell in mine:
            self._shape_types.pop(cell, None)
        for other in self._shape_type_owners.values():
            for cell, ttype in other.items():
                if cell in mine:
                    self._shape_types[cell] = ttype

    def npc_tile_type(self, x, y) -> int:
        """Tile TYPE an NPC's setshape2 array publishes at world tile (x, y),
        or 0 when no NPC covers it.

        The client-side half of `TServerLevel::getNPCTileType`
        (Preagonal/FourPlay/quattroplay/src/TServerLevel.cpp:536-561): the
        level's NPCs are asked before the board, and the first non-zero answer
        wins. Callers apply the board fallback for anything <= 1."""
        return self._shape_types.get((int(math.floor(x)), int(math.floor(y))), 0)

    # -- NPC blocking footprints (image NPCs, characters, shape cells) ------
    #
    # Rule derived from the reference client (Preagonal/FourPlay/quattroplay/
    # src): the level wall test asks its NPCs before the board
    # (TServerLevel::isOnWall, TServerLevel.cpp:2642-2654 — NPCs, bombs,
    # chests, players, then the board tile; it is a plain OR, so order does
    # not change the answer), and the player's own movement collision runs
    # through exactly that test (TPlayer::movementAction, TPlayer.cpp:
    # 7515-7519). Per NPC (TServerNPC::isOnNPC, TServerNPC.cpp:2093-2226):
    #
    # - an INVISIBLE NPC (hide/hidelocal/destroy) never blocks and never
    #   touches (:2095), nor does one zoomed to 0 (:2099).
    # - the not-blocking flag (dontblock/dontblocklocal set it, blockagain
    #   clears it — TServerNPCProperties.cpp:358-371, 436-446) exempts the
    #   NPC from WALL tests only; touch tests ignore the flag. The flag's
    #   polarity is pinned by TServerNPC::isOnWall marking ITSELF
    #   not-blocking around its own level wall probe so a script's onwall()
    #   can't collide with its own NPC (TServerNPC.cpp:2288-2313) — which
    #   only works if wall tests skip flagged NPCs. (The decompile's
    #   `!ignoreBlocking` at :2097 renders that store dead, i.e. the
    #   negation is a decompiler artifact.)
    # - a CHARACTER NPC's box is 2x2 tiles at +(0.5, 1.0) (TServerNPC.cpp:
    #   2106-2112; GServer-v2 NPC.h:544-551 agrees: translate(8,16),
    #   {32,32}).
    # - a setshape type-1 NPC blocks its w x h pixel box; a setshape2 array
    #   cell blocks at type >= 20 (both handled by the shape-cell path).
    # - anything else visible blocks its IMAGE footprint: the setimgpart
    #   rect if set, else the image's full size — UNCAPPED (TServerNPC::
    #   pixelsize, TServerNPC.cpp:1993-2014: shape > imgpart > texture
    #   size) — refined per-pixel by image transparency (:2158-2196) via
    #   the image_opaque_source hook where the art is loaded. No image at
    #   all -> no footprint (:2130-2132).
    #
    # Local script constructs never block: weapon showimg layers and
    # effects are not NPCs (they live in _weapon_imgs / npc['imgs'], not
    # client.npcs), and this walk only sees server NPCs.

    @staticmethod
    def _npc_solid(npc) -> bool:
        """The gate isOnNPC applies before any geometry on a WALL test:
        visible, blocking flag intact, not zoomed away."""
        if npc.get("visible", True) is False or npc.get("dontblock"):
            return False
        z = npc.get("zoom_effect")
        if z is not None and to_num(z) == 0.0:
            return False
        return True

    def _shape_cell_blocks(self, x, y, exclude_npc=None) -> bool:
        """Does a setshape/setshape2 blocking cell cover (x, y), owned by an
        NPC that is currently solid? The flat _shape_blocks set answers the
        cheap membership test; the owner walk applies the per-NPC
        visible/dontblock gate (the flag no longer edits the cell sets, so
        blockagain can restore them — see _cmd_dontblock)."""
        cell = (int(math.floor(x)), int(math.floor(y)))
        if cell not in self._shape_blocks:
            return False
        npcs = getattr(self.client, "npcs", {}) if self.client else {}
        for nid, cells in self._shape_block_owners.items():
            if nid == exclude_npc:
                continue
            if cell in cells:
                npc = npcs.get(nid)
                if not isinstance(npc, dict) or self._npc_solid(npc):
                    return True
        return False

    def npc_image_rect(self, npc):
        """World-tile footprint rect (x, y, w, h) of a shapeless NPC, or None.

        Character NPCs get the implicit 2x2 box on their feet; an image NPC
        covers its setimgpart rect if set, else its image's full size
        (image_size_source; unknown -> the 2x2 engine default). Tiles are
        pixels / 16. Visibility/blocking gates are the CALLER's business —
        touch uses this same rect without them."""
        if not isinstance(npc, dict):
            return None
        if npc.get("is_character") or npc.get("image") == "#c#":
            nx, ny = to_num(npc.get("x", 0)), to_num(npc.get("y", 0))
            return (nx + 0.5, ny + 1.0, 2.0, 2.0)
        image = npc.get("image") or ""
        if not image or image == "-":
            # "-" is the classic no-image placeholder (script-only NPCs in
            # .nw files): no art, no footprint.
            return None
        part = npc.get("imagepart")
        if part:
            w_px, h_px = part[2], part[3]
        else:
            size = None
            if self.image_size_source is not None:
                try:
                    size = self.image_size_source(image)
                except Exception:
                    size = None
            w_px, h_px = size if size else (_DEFAULT_IMAGE_PX,
                                            _DEFAULT_IMAGE_PX)
        if w_px <= 0 or h_px <= 0:
            return None
        nx, ny = to_num(npc.get("x", 0)), to_num(npc.get("y", 0))
        return (nx, ny, w_px / 16.0, h_px / 16.0)

    def npc_footprint_hit(self, npc, x, y) -> bool:
        """Is world point (x, y) inside `npc`'s footprint (rect, refined by
        image transparency where the art is loaded)? No solidity gating —
        shared by wall tests (which add _npc_solid) and touch (which only
        requires visibility)."""
        rect = self.npc_image_rect(npc)
        if rect is None:
            return False
        rx, ry, rw, rh = rect
        if not (rx <= x < rx + rw and ry <= y < ry + rh):
            return False
        if (self.image_opaque_source is None or npc.get("is_character")
                or npc.get("image") == "#c#"):
            return True
        part = npc.get("imagepart")
        px = int((x - rx) * 16) + (int(part[0]) if part else 0)
        py = int((y - ry) * 16) + (int(part[1]) if part else 0)
        try:
            opaque = self.image_opaque_source(npc.get("image"), px, py)
        except Exception:
            opaque = None
        return opaque is not False

    def npc_blocks_at(self, x, y, exclude_npc=None) -> bool:
        """Does any NPC WALL the world point (x, y)? (See the rule derivation
        above.) Consulted by is_wall (script onwall/onwall2 probes and
        scripted movement) and by the pygame client's movement collision
        (game/collision.py _is_blocked_at). `exclude_npc` — see is_wall."""
        if self._shape_cell_blocks(x, y, exclude_npc=exclude_npc):
            return True
        cl = self.client
        if cl is None:
            return False
        for npc_id, npc in getattr(cl, "npcs", {}).items():
            if npc_id == exclude_npc or not isinstance(npc, dict):
                continue
            geom = self.shapes.get(npc_id)
            if geom and geom[0] > 0 and geom[1] > 0:
                continue    # shape overrides the image footprint (pixelsize)
            if not self._npc_solid(npc):
                continue
            if self.npc_footprint_hit(npc, x, y):
                return True
        return False

    def tile_at(self, x, y):
        """Tile id under world coordinate (x, y), or None when no board
        resolves there.

        Prefers the host's `tile_source` (the pygame client's gmap-aware
        segment lookup); falls back to the current level's own 64x64 board so
        headless callers with no game shell keep working."""
        if self.tile_source is not None:
            try:
                tile = self.tile_source(x, y)
            except Exception:
                tile = None
            if tile is not None:
                return None if tile < 0 else tile
            return None
        ix, iy = int(x), int(y)
        if 0 <= ix < 64 and 0 <= iy < 64:
            tiles = getattr(self.client, "tiles", None) if self.client else None
            if tiles and len(tiles) >= 64 * 64:
                try:
                    return tiles[iy * 64 + ix]
                except (IndexError, TypeError):
                    pass
        return None

    def _tilestype(self):
        """The tilestype in force for the client's CURRENT level, so script
        probes read the same type table (classic vs new-world) the level's
        tiledefs select — see tiletypes.select_tilestype."""
        name = ""
        if self.client is not None:
            name = getattr(self.client, "_current_level_name", "") or ""
        return tilestype_for_level(name)

    def is_wall(self, x, y, exclude_npc=None):
        """Collision test at world tile (x, y) for onwall(). Checks the level
        board under (x, y) (a blocking tile id), plus NPC footprints — shape
        cells (setshape/setshape2, e.g. the arena's falling sudden-death choc
        blocks) and visible blocking image/character NPCs, matching
        TServerLevel::isOnWall's NPC leg (see npc_blocks_at).

        `exclude_npc`: the CALLING NPC's id, so a script's own onwall()
        probe never collides with its own footprint — the reference marks
        the probing NPC not-blocking for the duration (TServerNPC::isOnWall,
        Preagonal/FourPlay/quattroplay/src/TServerNPC.cpp:2288-2313)."""
        tile = self.tile_at(x, y)
        if tile is not None:
            try:
                if type_is_blocking(get_tile_type(tile, self._tilestype())):
                    return True
            except TypeError:
                pass
        elif self.tile_source is not None:
            # tile_source resolved nothing: off the world (its own -1 case).
            return True
        return self.npc_blocks_at(x, y, exclude_npc=exclude_npc)

    def is_water_at(self, x, y):
        """Water test at world tile (x, y) for onwater() — deep or shallow."""
        tile = self.tile_at(x, y)
        if tile is None:
            return False
        try:
            return get_tile_type(tile, self._tilestype()) in (
                TileType.WATER, TileType.NEAR_WATER)
        except TypeError:
            return False

    def tile_type_at(self, x, y):
        """`tiletype(x, y)`: the tile's TYPE code (tiletypes.py, table chosen
        by the level's tilestype), not its tile id. Zelda's movement engine
        reads it for chairs (3), beds (4/5) and jumpable ledges (21)."""
        tile = self.tile_at(x, y)
        if tile is None:
            return 0.0
        try:
            return float(int(get_tile_type(tile, self._tilestype())))
        except (TypeError, ValueError):
            return 0.0

    def mouse_world(self):
        """`mousex`/`mousey`: the mouse cursor in WORLD TILE coords.

        Prefers `mouse_world_source` (the pygame client's camera-aware
        unproject). With no hook, answer the player's own position — the same
        world frame `playerx`/`playery` report — so a script converting
        between the screen and world frames (bomber's shop panel anchor,
        bomblobby.nw:584) gets the cursor pixel back instead of an offset
        computed against a bogus 0."""
        if self.mouse_world_source is not None:
            try:
                x, y = self.mouse_world_source()
                return float(x), float(y)
            except Exception:
                logger.debug("mouse_world_source failed", exc_info=True)
        cl = self.client
        if cl is None:
            return 0.0, 0.0
        return float(getattr(cl, "x", 0.0)), float(getattr(cl, "y", 0.0))

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

    def process_attachment(self):
        """Propagate an attached-to NPC's movement to the local player
        (attachplayertoobj). The reference slaves the player to the NPC by
        propagating every NPC position write to its attached children with
        the child's offset preserved, while the player's OWN writes just
        re-derive the offset (TServerPlayer::setlocalx/setlocaly,
        Preagonal/FourPlay/quattroplay/src/TServerPlayer.cpp:1491-1552).
        Applying the NPC's per-frame movement DELTA to the player is the same
        math: script movement of the player between frames implicitly updates
        the offset. Detaches itself when the NPC disappears (level change
        clears client.npcs; the reference equally can't stay attached to a
        despawned NPC)."""
        att = self._player_attach
        cl = self.client
        if att is None or cl is None:
            return
        npc = getattr(cl, "npcs", {}).get(att["npc_id"])
        if not isinstance(npc, dict):
            self._player_attach = None
            return
        nx, ny = to_num(npc.get("x", 0)), to_num(npc.get("y", 0))
        dx, dy = nx - att["last_x"], ny - att["last_y"]
        if dx or dy:
            att["last_x"], att["last_y"] = nx, ny
            try:
                cl.player.x += dx
                cl.player.y += dy
                cl.send_position()
            except Exception:
                pass

    def sign_text_by_index(self, index) -> "str | None":
        """Text of the CURRENT level's sign `index` (0-based, in the order the
        signs arrived - PLO_LEVELSIGN is sent in level-file order, kept as an
        ordered list in client.sign_lists). The (x, y)-keyed client.signs
        dict is only a fallback for harnesses that never populated the list;
        it CANNOT be authoritative because say-only signs are conventionally
        stacked at 0,0 and collapse to one dict key (live GTA abermose7.nw:
        five signs, one dict entry). None for a non-numeric index or one out
        of range. Used by `say <n>`."""
        cl = self.client
        if cl is None:
            return None
        if isinstance(index, bool):
            return None
        if isinstance(index, (int, float)):
            idx = int(index)
        else:
            # a stringly number still counts; anything else is not an index
            # (to_num would silently read it as 0 = sign zero)
            try:
                idx = int(float(to_str(index).strip()))
            except (TypeError, ValueError):
                return None
        lvl = getattr(cl, "_current_level_name", "")
        ordered = getattr(cl, "sign_lists", {}).get(lvl)
        if ordered:
            if 0 <= idx < len(ordered):
                return ordered[idx][2]
            return None
        signs = getattr(cl, "signs", {}).get(lvl)
        if not signs or not 0 <= idx < len(signs):
            return None
        return list(signs.values())[idx]

    def process_timeouts(self, dt):
        """Count down each NPC's pending `timeout` and fire its `timeout` event
        when it elapses (the event handler typically re-arms it). This is what
        drives proximity checks, the room-join state machine, etc. Also steps
        the attachplayertoobj slave link - it must track scripted NPC movement
        every frame, and this is the engine's per-frame hook."""
        if self.client is None:
            return
        self.process_attachment()
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
        self.advance_layer_emitters(dt)

    def advance_layer_emitters(self, dt):
        """Step every layer record's particle emitter (pyreborn/particles.py)
        -- this per-frame hook is the client's stand-in for the reference's
        per-draw TParticleEmitter::process, and running it here (not in the
        renderer) keeps the state model advancing for headless embedders.
        Emitters live only on layer records, so the NPC img stores plus
        _weapon_imgs cover them all; GS2-created emitters share these same
        records."""
        stores = list(self._weapon_imgs.values())
        for npc in (getattr(self.client, "npcs", {}) or {}).values():
            if isinstance(npc, dict):
                imgs = npc.get("imgs")
                if imgs:
                    stores.append(imgs)
        for store in stores:
            for rec in list(store.values()):
                emitter = rec.get("emitter") if isinstance(rec, dict) else None
                if isinstance(emitter, ParticleEmitter):
                    try:
                        emitter.advance(dt)
                    except Exception as e:
                        _report_gs1_error("particle emitter", e)

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
        if entry.get("inactive"):
            return
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
        vs = _ClientScopeVarStore(scopes=scopes, player_flags=self._flags)
        player = getattr(self.client, "player", None) if self.client else None
        ctx = Context(self._host, vs, this_obj=npc, player=player)
        ctx._npc_id = entry["npc_id"]
        ctx._is_weapon = is_weapon
        ctx._prog_key = key
        interp = _RefNamespaceInterpreter(ctx)
        interp._coro = True                # `sleep` suspends; we pump it below
        interp.statement_budget = _GS1_STATEMENTS_PER_SLICE
        gen = interp.iter_event(entry["prog"], event)
        self._drive(gen, ctx, key, entry, event)

    def _drive(self, gen, ctx, key, entry, event):
        """Pump one script slice, parking sleep and preemption continuations.

        A preempted generator gets remaining=0 but is not pumped again here:
        process_coroutines sees it on the next frame, preserving the frame
        boundary that removes the measured 430-ms playerenters stall."""
        ctx.steps = 0
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
                            "remaining": (0.0 if delay is PREEMPTED
                                          else float(delay)),
                            "preempted": delay is PREEMPTED,
                            "board_wait_frames": 0})

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
            # Sleep already crossed level changes before slicing existed, so
            # only the synthetic preemption park inherits playerenters'
            # board-ready window.  Holding the record also holds its active
            # key, preventing a duplicate event while the continuation waits.
            if c["preempted"] and not self.board_ready():
                c["board_wait_frames"] += 1
                if c["board_wait_frames"] <= _GS1_PREEMPT_BOARD_WAIT_FRAMES:
                    still.append(c)
                    continue
            # A numeric sleep starts a fresh statement slice.  A preemption
            # stopped immediately before its next statement and already reset
            # the shared ctx.steps counter; resetting again would fail to count
            # that pending statement when the generator continues below.
            if not c["preempted"]:
                c["ctx"].steps = 0
            try:
                delay = next(c["gen"])
                c["remaining"] = (0.0 if delay is PREEMPTED
                                  else float(delay))
                c["preempted"] = delay is PREEMPTED
                c["board_wait_frames"] = 0
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
