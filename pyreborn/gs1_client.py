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
import os
import sys
import traceback

from reborn_protocol.coords import level_index, segment_at, world_to_local
from reborn_protocol.gs1.runtime import Host, UNSET, VarStore, Context
from reborn_protocol.gs1.interp import Interpreter
from reborn_protocol.gs1.lexer import tokenize
from reborn_protocol.gs1.parser import Parser
from reborn_protocol.gs1.values import gs1_int, to_num, to_str
from reborn_protocol.gs1.host_shared import (
    A_CLASS_NPC_ATTR, A_CLASS_PLAYER_ATTR, host_value, tokens_count,
)
from .sprites import REBORN_PALETTE, REBORN_PALETTE_ALIASES
from .tiletypes import (
    TileType, get_tile_type, tilestype_for_level, type_is_blocking,
    register_tiledef, remove_tiledefs,
)

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


class GS1NoBoard(Exception):
    """`tiles[x,y]` was read while the current level's board is not in hand.

    There is no honest answer: GS1 has no "unknown tile" value, so any number
    we invent is indistinguishable from a real tile id. Answering 0.0 (the old
    behaviour) reads as "empty floor", and classic Bomber's room0.nw furniture
    catalog deletes every wall-mounted object whose tile is not the wall id
    0x278 -- writing the truncated object list straight back to `server.room<N>`
    (ResetObj/Delete, room0.nw:1006/1052). Aborting the script instead leaves
    the furniture alone; the event re-runs once the board has arrived.
    """


# ---------------------------------------------------------------------------
# Script-visible board access -- tiles[] reads/writes and updateboard -- shared
# by BOTH engines (GS1's `tiles[x,y]` builtin below, GS2's tiles_view in
# gs2_client.py). Coordinates are in the SCRIPT frame: world tiles while
# standing on a gmap segment (LTTP's -Player/Movement indexes 0..width*64),
# plain local 0..63 in a standalone level (houses, classic servers) -- the
# same frame split every other client-side probe (tiletype, onwall, playerx)
# already uses. Frame math comes from reborn_protocol.coords per house rules.
# ---------------------------------------------------------------------------

def _board_locate(client, x, y):
    """Resolve script-frame tile coords -> (level_name, lx, ly, grid).

    level_name is None when the coords land outside the world (or in a hole
    of the gmap grid); grid is the (gx, gy) segment on a gmap, None in a
    standalone level."""
    if client is None:
        return None, 0, 0, None
    tx, ty = int(math.floor(x)), int(math.floor(y))
    if getattr(client, "in_gmap_segment", False) and getattr(client, "gmap_grid", None):
        grid = segment_at(tx, ty)
        level = client.gmap_grid.get(grid)
        if not level:
            return None, tx, ty, grid
        lx, ly = world_to_local(tx, ty)
        return level, int(lx), int(ly), grid
    if 0 <= tx < 64 and 0 <= ty < 64:
        return getattr(client, "_current_level_name", "") or None, tx, ty, None
    return None, tx, ty, None


def _board_list(client, level_name):
    """The 4096-entry tile list backing `level_name`, or None. Same resolution
    order as the renderer's _segment_tiles (client.levels cache first, then
    the active client.tiles) -- Client._apply_board_modify patches both."""
    levels = getattr(client, "levels", None) or {}
    board = levels.get(level_name)
    if board is None and level_name == getattr(client, "_tiles_level_name", ""):
        board = getattr(client, "tiles", None)
    return board if board is not None and len(board) >= 4096 else None


def board_world_dims(client):
    """(width, height) of the script-frame board in tiles: the whole gmap
    while standing on a segment, one level otherwise."""
    if client is not None and getattr(client, "in_gmap_segment", False):
        w = int(getattr(client, "gmap_width", 0) or 0)
        h = int(getattr(client, "gmap_height", 0) or 0)
        if w > 0 and h > 0:
            return w * 64, h * 64
    return 64, 64


def board_tile_read(client, x, y):
    """tiles[x,y] read. None = unanswerable (outside the world, or that
    segment's board never streamed); callers pick their engine's miss value."""
    level, lx, ly, _grid = _board_locate(client, x, y)
    if level is None:
        return None
    board = _board_list(client, level)
    if board is None:
        return None
    return float(board[level_index(lx, ly)])


def board_tile_write(client, x, y, tile_id) -> bool:
    """tiles[x,y] = id. Routes through Client._apply_board_modify (the same
    path a PLO_BOARDMODIFY server delta takes), so the write hits the REAL
    board -- client.levels + active client.tiles, hence collision -- and then
    the on_board_modify callback, which the pygame client wires to the
    renderer's per-segment surface patcher. Off-world / board-less writes are
    dropped (matching a server delta for a level we don't have)."""
    level, lx, ly, grid = _board_locate(client, x, y)
    if level is None or _board_list(client, level) is None:
        return False
    info = {"layer": 0, "x": lx, "y": ly, "width": 1, "height": 1,
            "tiles": [max(0, int(to_num(tile_id))) & 0xFFF]}
    if grid is not None:
        info["map_x"], info["map_y"] = grid
    client._apply_board_modify(level, info)
    cb = getattr(client, "on_board_modify", None)
    if cb:
        cb(info)
    return True


def board_update_region(client, x, y, w, h) -> None:
    """`updateboard x,y,width,height` -- re-blit the rect from current board
    data. Oracle: GServer-v2 GS1Commands.cpp:3560-3575 (fn_updateboard /
    fn_updateboard2): exactly this argument order, each value clamped at 0,
    the rect handed to Level::updateBoard for a region redraw; updateboard2
    additionally saves the level server-side, which has no client-side
    meaning, so both spellings redraw here. Scripts edit tiles[] first and
    then call this to publish the change (LTTP's CheckTiles bush slash);
    board_tile_write already patches the renderer per write, so this is the
    idempotent region form -- and the only path that repaints edits made
    behind the callback's back."""
    if client is None:
        return
    cb = getattr(client, "on_board_modify", None)
    if cb is None:
        return
    x0 = max(0, int(math.floor(x)))
    y0 = max(0, int(math.floor(y)))
    ww, wh = board_world_dims(client)
    x1 = min(x0 + max(0, int(math.floor(w))), ww)
    y1 = min(y0 + max(0, int(math.floor(h))), wh)
    if x1 <= x0 or y1 <= y0:
        return
    on_gmap = bool(getattr(client, "in_gmap_segment", False)
                   and getattr(client, "gmap_grid", None))
    targets = []
    if on_gmap:
        for gy in range(y0 // 64, (y1 - 1) // 64 + 1):
            for gx in range(x0 // 64, (x1 - 1) // 64 + 1):
                level = client.gmap_grid.get((gx, gy))
                if not level:
                    continue
                targets.append((level, (gx, gy),
                                max(x0, gx * 64) - gx * 64,
                                max(y0, gy * 64) - gy * 64,
                                min(x1, (gx + 1) * 64) - gx * 64,
                                min(y1, (gy + 1) * 64) - gy * 64))
    else:
        level = getattr(client, "_current_level_name", "") or None
        if level:
            targets.append((level, None, x0, y0, x1, y1))
    for level, grid, lx0, ly0, lx1, ly1 in targets:
        board = _board_list(client, level)
        if board is None:
            continue
        tiles = [board[level_index(tx, ty)]
                 for ty in range(ly0, ly1) for tx in range(lx0, lx1)]
        info = {"layer": 0, "x": lx0, "y": ly0,
                "width": lx1 - lx0, "height": ly1 - ly0, "tiles": tiles}
        if grid is not None:
            info["map_x"], info["map_y"] = grid
        cb(info)


# player-prefixed builtin -> attribute on the pyReborn Player
PLAYER_ATTR = {**A_CLASS_PLAYER_ATTR, "playeraccount": "account"}
# unprefixed builtin -> key on the client NPC dict (the NPC running the script)
NPC_ATTR = dict(A_CLASS_NPC_ATTR)
# command -> NPC dict key it writes (so the renderer reflects the change).
# Image commands are handled explicitly in _dispatch (they also manage the
# imagepart sub-rect), so they're not listed here. NB `setani` is NOT here:
# it always targets the LOCAL PLAYER, even from an NPC script (see
# _cmd_setani) — only `setcharani` is the NPC-targeting form.
_NPC_WRITE = {
    "setcharani": "gani", "setnick": "nickname",
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

# The same appearance codes read off the LOCAL PLAYER, for a script with no NPC
# source (a weapon). Colours are not here: they live in Player.colors as
# palette indices, keyed by the code's slot number (see _color_code_slot).
_CHARPROP_PLAYER = {
    "#1": "sword_image", "#2": "shield_image",
    "#3": "head_image", "#8": "body_image",
}

# Commands that just toggle/ignore for client rendering (input/feature state we
# don't model, or world side-effects irrelevant to drawing the lobby). Swallowed
# silently so a script full of them still runs its visible commands.
_NOOP = frozenset({
    "timereverywhere", "enablefeatures",
    "noplayerkilling",
    "setcursor", "sleep",
    "serverwarp",
    "deletestring", "insertstring", "replacestring",
})

# onwall2 rect probes: far-edge sliver overlaps up to this many tiles are NOT
# counted as hits (see the onwall2 comment in call_function for the full
# derivation from -Test/Movement's flush-wall sliding bug). Must exceed the
# worst resting wall penetration a check-then-move script can leave (one
# movement step, 0.3 tiles on Bomber v6) minus the 1/16 the scripts already
# shave off their probe extents: 0.3 - 1/16 = 0.2375.
_ONWALL2_EDGE_TOL = 0.25

# `timeout = v` with v at or below this cancels the pending timeout instead of
# arming it — TScriptSpace::setTimeout deactivates the timer for any value
# <= 0.0001 (Preagonal/FourPlay/quattroplay/src/TScriptSpace.cpp:121-129).
_TIMEOUT_CANCEL = 0.0001

# Default footprint for an image NPC whose texture size is unknown (image not
# loaded / headless host): 32x32 pixels = 2x2 tiles, the reference engine's
# fallback for an unsized texture (TParticleData::pixelsize,
# Preagonal/FourPlay/quattroplay/src/TParticleData.cpp:155-163).
_DEFAULT_IMAGE_PX = 32


# ---------------------------------------------------------------------------
# GS1 client-host dispatch registries.
#
# GS1ClientHost.get_builtin and ._dispatch consult these tables in a fixed
# stage order (documented on each method). They are EXPLICIT registries, not
# auto-discovery: every name a script can use appears literally in a
# @_gs1_builtin / @_gs1_command decorator, so grep finds its handler.
# ---------------------------------------------------------------------------

#: A handler returns this to mean "my guard did not hold, keep walking the
#: stages" -- the flat if/elif chain's fall-through, made explicit. Returning
#: None means handled.
_FALL_THROUGH = object()

#: get_builtin stages. Each has a gate; the two shared data tables
#: (PLAYER_ATTR / NPC_ATTR) are consulted right after their stage's handlers.
_GS1_PLAYER_BUILTINS: dict = {}     # gate: a local player exists
_GS1_NPC_BUILTINS: dict = {}        # gate: ctx.this_obj is an NPC dict
_GS1_BUILTINS: dict = {}            # no gate

#: _dispatch stages, in dispatch order.
_GS1_PRE_COMMANDS: dict = {}        # before the layer store is resolved
_GS1_LAYER_COMMANDS: dict = {}      # gate: a layer store exists
_GS1_NPC_COMMANDS: dict = {}        # gate: ctx.this_obj is an NPC dict
_GS1_MAIN_COMMANDS: dict = {}       # no gate
_GS1_NPC_TAIL_COMMANDS: dict = {}   # gate: NPC dict; last stage


def _gs1_builtin(table, *names):
    """Register a get_builtin handler in `table` under each of `names`.
    Handlers take (self, name, indices, ctx) and may return UNSET.

    A name must not also be in the data table that shares the stage's gate
    (PLAYER_ATTR / NPC_ATTR), because those are read AFTER the handlers and the
    duplicate would be unreachable.
    """
    shadowed = {id(_GS1_PLAYER_BUILTINS): PLAYER_ATTR,
                id(_GS1_NPC_BUILTINS): NPC_ATTR}.get(id(table), ())

    def register(fn):
        for entry in names:
            if entry in table or entry in shadowed:
                raise AssertionError(f"duplicate GS1 builtin {entry!r}")
            table[entry] = fn
        return fn
    return register


def _gs1_command(table, *names):
    """Register a _dispatch handler in `table` under each of `names`.
    Handlers take (self, name, args, ctx, imgs) and return None (handled) or
    _FALL_THROUGH."""
    def register(fn):
        for entry in names:
            if entry in table:
                raise AssertionError(f"duplicate GS1 command {entry!r}")
            table[entry] = fn
        return fn
    return register
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
        """Read a GS1 built-in variable. Registry-driven: three stages, each a
        @_gs1_builtin table plus the data table that shares its gate.

        Returning UNSET means "not a built-in here" and sends the interpreter
        on to the ordinary flag/var lookup -- `statsoff` uses that
        deliberately, so a handler may return it too.
        """
        player = self._player
        npc = ctx.this_obj
        if player is not None:
            handler = _GS1_PLAYER_BUILTINS.get(name)
            if handler is not None:
                return handler(self, name, indices, ctx)
            # ...and the plain attribute table (disjoint from the handlers
            # above; _GS1_BUILTIN_TABLES asserts it).
            if name in PLAYER_ATTR:
                return _num_or_str(getattr(player, PLAYER_ATTR[name], 0))
        if isinstance(npc, dict):
            handler = _GS1_NPC_BUILTINS.get(name)
            if handler is not None:
                return handler(self, name, indices, ctx)
            if name in NPC_ATTR:
                return _num_or_str(npc.get(NPC_ATTR[name], 0))
        handler = _GS1_BUILTINS.get(name)
        if handler is not None:
            return handler(self, name, indices, ctx)
        # players[i].x / players[i].y / players[i].account -> the i-th player.
        if name.startswith("players."):
            attr = name.split(".", 1)[1]
            pl = self._player_list()
            i = int(indices[0]) if indices else 0
            return _num_or_str(pl[i].get(attr, 0)) if 0 <= i < len(pl) else 0.0
        # npcs[i].x / npcs[i].save[j] / ... -> the i-th NPC in the level.
        if name.startswith("npcs."):
            return self._npc_array_attr(name.split(".", 1)[1], indices)
        return UNSET

    def _npc_ids(self):
        """Level NPC ids in `npcs[]` index order.

        GS1's npcs[] is a level-order array; client.npcs is keyed by the
        server's NPC id. The server allocates those ids in level order, so
        sorting them reproduces the array's ordering."""
        cl = self.rt.client
        if cl is None:
            return []
        return sorted(getattr(cl, "npcs", {}) or {})

    def _npc_array_attr(self, attr, indices):
        """npcs[i].<attr>. `indices` is [i] plus, for `save`, the slot index:
        the interpreter forwards every index across the whole reference, so
        `npcs[3].save[1]` arrives as [3, 1]."""
        ids = self._npc_ids()
        i = int(indices[0]) if indices else 0
        if not 0 <= i < len(ids):
            return 0.0
        if attr == "save":
            slots = self.rt.npc_save_slots(ids[i]) or []
            j = int(indices[1]) if len(indices) > 1 else 0
            return float(slots[j]) if 0 <= j < len(slots) else 0.0
        npc = self.rt.client.npcs.get(ids[i])
        if isinstance(npc, dict) and attr in NPC_ATTR:
            return _num_or_str(npc.get(NPC_ATTR[attr], 0))
        return 0.0

    # -- _GS1_PLAYER_BUILTINS (gate: the client has a local player) ---------
    #
    # Boolean-natured builtins must return real Python bools: under the
    # oracle-verified truthiness model (gs1_truthy, values.py) numbers are
    # NEVER truthy in conditions, so a 1.0 would make `if (isweapon)` etc.
    # silently false. Upstream models these as bool flags/GameValues, not
    # doubles. The same rule applies to the predicate handlers further down.

    @_gs1_builtin(_GS1_PLAYER_BUILTINS, "playerx", "playery")
    def _pb_position(self, name, indices, ctx):
        # World-frame like upstream: Character.h getTilePosition() binds
        # mapX*64 + local into playerx/playery (same source GS2's player.x
        # uses). On non-gmap levels world == local, so classic servers
        # (e.g. Bomber Arena) are unaffected.
        return float(getattr(self.rt.client, "x" if name == "playerx" else "y", 0))

    @_gs1_builtin(_GS1_PLAYER_BUILTINS, "playerglovepower")
    def _pb_glovepower(self, name, indices, ctx):
        # Player script values use 1/2/3 (none/glove1/glove2), while
        # NPC glovepower and the wire-backed Player field use 0/1/2.
        return float(getattr(self._player, "glove_power", 0) + 1)

    @_gs1_builtin(_GS1_PLAYER_BUILTINS, "playeronline")
    def _pb_online(self, name, indices, ctx):
        return True

    @_gs1_builtin(_GS1_PLAYER_BUILTINS, "playerswimming")
    def _pb_swimming(self, name, indices, ctx):
        # no dedicated swim-state on the core Client (that lives on
        # GameClient, which this host can't see) -- approximate it with the
        # same tile-water check onwater()/is_wall() already use.
        px = float(getattr(self.rt.client, "x", 0)) % 64
        py = float(getattr(self.rt.client, "y", 0)) % 64
        return bool(self.rt.is_water_at(px, py))

    @_gs1_builtin(_GS1_PLAYER_BUILTINS, "playeronhorse")
    def _pb_onhorse(self, name, indices, ctx):
        # PLPROP_HORSEGIF (21) is only non-empty while mounted
        # (mount_horse/dismount are player-props round trips).
        return bool(getattr(self._player, "horse_image", ""))

    @_gs1_builtin(_GS1_PLAYER_BUILTINS, "playerfreezetime")
    def _pb_freezetime(self, name, indices, ctx):
        # seconds left on the last `freezeplayer` call (rt._freeze_until is
        # armed in _dispatch, same duration the input layer locks movement for)
        import time as _t
        remaining = self.rt._freeze_until - _t.monotonic()
        return remaining if remaining > 0 else -1.0

    @_gs1_builtin(_GS1_PLAYER_BUILTINS, "carrying", "carriesbush",
                  "carriesstone", "carriesvase", "carriessign",
                  "carriesblackstone", "carriesnpc")
    def _pb_carrying(self, name, indices, ctx):
        # pyReborn only models bush/rock/pot lift objects
        # (game/collision.py _get_liftable_name); "rock"/"pot" are the
        # same objects Reborn's docs call "stone"/"vase". The remaining
        # carry flags are defined for script compatibility, but nothing in
        # this client can currently lift those object types.
        player = self._player
        if name == "carrying":
            return bool(player.is_carrying())
        wanted = {"carriesbush": "bush", "carriesstone": "rock",
                  "carriesvase": "pot"}.get(name)
        if wanted is None:
            return False
        return player.carried_object_type == wanted

    # -- _GS1_NPC_BUILTINS (gate: the script has an NPC dict) ---------------

    @_gs1_builtin(_GS1_NPC_BUILTINS, "visible")
    def _nb_visible(self, name, indices, ctx):
        # True unless `hide`/`destroy` cleared it (npc dict has no key until
        # then, so a never-hidden NPC must default true).
        return bool(ctx.this_obj.get("visible", True))

    # -- _GS1_BUILTINS (no gate) -------------------------------------------

    @_gs1_builtin(_GS1_BUILTINS, "isweapon")
    def _gb_isweapon(self, name, indices, ctx):
        return bool(getattr(ctx, "_is_weapon", False))

    @_gs1_builtin(_GS1_BUILTINS, "statsoff")
    def _gb_statsoff(self, name, indices, ctx):
        # `showstats 0` hides the whole stats bar; the classic client then
        # reports statsoff true, and HUD scripts skip drawing (GTA's
        # splashscreen relies on this to keep the clock/counter overlays
        # off the loading screen). Scripts can also set/unset the flag
        # themselves, so only claim the name while the mask says hidden —
        # otherwise fall through to the plain flag lookup.
        if self.rt.stats_mask == 0:
            return True
        return UNSET

    @_gs1_builtin(_GS1_BUILTINS, "weaponscount")
    def _gb_weaponscount(self, name, indices, ctx):
        return float(len(getattr(self.rt.client, "weapons", {}) or {}))

    @_gs1_builtin(_GS1_BUILTINS, "selectedweapon")
    def _gb_selectedweapon(self, name, indices, ctx):
        # Index of the equipped weapon in the same full-array ordering
        # weaponscount/#w(i)/callweapon use; -1 when none (matches the v6
        # object of the same name, TInitStatics.cpp getters — GS1 scripts use
        # it too: GTA's -System3 does `callweapon selectedweapon,wweaponfired`
        # while swimming; as a plain unset flag it resolved to 0 = whatever
        # weapon was first in the array).
        return float(self.rt.selected_weapon_index())

    @_gs1_builtin(_GS1_BUILTINS, "weaponsenabled")
    def _gb_weaponsenabled(self, name, indices, ctx):
        return bool(self.rt.weapons_enabled)

    @_gs1_builtin(_GS1_BUILTINS, "playerscount")
    def _gb_playerscount(self, name, indices, ctx):
        return float(len(self._player_list()))

    @_gs1_builtin(_GS1_BUILTINS, "npcscount")
    def _gb_npcscount(self, name, indices, ctx):
        return float(len(self._npc_ids()))

    @_gs1_builtin(_GS1_BUILTINS, "save")
    def _gb_save(self, name, indices, ctx):
        # Bare save[i]: the RUNNING NPC's persistent slots, the same storage
        # `this.save[i]` uses (the interpreter special-cases that spelling into
        # a 10-slot list on the this-scope, interp.py:832). Weapons have no
        # NPC and therefore no save[] -- fall through to the plain var lookup.
        slots = self.rt.npc_save_slots(getattr(ctx, "_npc_id", None))
        if slots is None:
            return UNSET
        i = int(indices[0]) if indices else 0
        return float(slots[i]) if 0 <= i < len(slots) else 0.0

    @_gs1_builtin(_GS1_BUILTINS, "tokenscount")
    def _gb_tokenscount(self, name, indices, ctx):
        # number of tokens from the last `tokenize`
        return tokens_count(ctx)

    @_gs1_builtin(_GS1_BUILTINS, "timevar")
    def _gb_timevar(self, name, indices, ctx):
        # Reborn server clock (GServer-v2 Server::calculateNWTime): integer
        # ticks of 5 seconds since 2001-02-01 17:33:34 UTC. The bomber room
        # timers (server.bombrm_NN) are in this scale; raw unix seconds were
        # out of scale + decimal, which broke the room-timer comparisons.
        import time as _t
        return float(int((_t.time() - 981048814) / 5))

    @_gs1_builtin(_GS1_BUILTINS, "timevar2")
    def _gb_timevar2(self, name, indices, ctx):
        import time as _t
        return float(_t.monotonic() * 1000.0)

    # arena GUI/screen + game-role builtins (read-only)

    @_gs1_builtin(_GS1_BUILTINS, "allstats")
    def _gb_allstats(self, name, indices, ctx):
        # sum of every showstats bit (see the showstats handler in
        # _dispatch): 1+2+4+...+1024
        return 2047.0

    @_gs1_builtin(_GS1_BUILTINS, "screenwidth", "screenheight")
    def _gb_screensize(self, name, indices, ctx):
        return float(self.rt.screen_w if name == "screenwidth"
                     else self.rt.screen_h)

    @_gs1_builtin(_GS1_BUILTINS, "graalversion")
    def _gb_client_version(self, name, indices, ctx):
        # "The current version of the game client" as a NUMBER
        # (scripting-gs1-variables.md:56) — the version we negotiated at
        # login, so a script's version gate picks the layout a real client of
        # that version would get. Classic Bomber's tailor branches on
        # `(graalversion < 2.211)` and drew its whole GUI in the pre-2.211
        # layout (shifted -31x/+64y, character preview skipped) while the name
        # was unimplemented and read 0.
        return _version_number(getattr(self.rt.client, "version", None))

    @_gs1_builtin(_GS1_BUILTINS, "mousescreenx", "mousescreeny")
    def _gb_mousepos(self, name, indices, ctx):
        return float(self.rt.mouse_x if name == "mousescreenx"
                     else self.rt.mouse_y)

    @_gs1_builtin(_GS1_BUILTINS, "mousex", "mousey")
    def _gb_mouseworld(self, name, indices, ctx):
        # The SAME cursor as mousescreenx/y, in level/world TILE units:
        # `mousex` is getMouseLevelX() (Preagonal/FourPlay/quattroplay/src/
        # TInitStatics.cpp:2505), i.e. screenToWorldX(cursor.x - the level
        # view's offset) (TPlayer.cpp:1465), against mousescreenx's raw cursor
        # pixel (TInitStatics.cpp:2570). Scripts use the pair to convert
        # between the two frames: the bomber shop anchors its panel on the
        # PLAYER'S SCREEN PIXEL with `mousescreenx - (mousex - playerx) * 16`
        # (Preagonal/graal-bomber-gs1/world/bomblobby.nw:584) — with an
        # unimplemented mousex==0 that degenerates to cursor + playerx*16,
        # which threw the whole shop panel off the canvas.
        x, y = self.rt.mouse_world()
        return float(x if name == "mousex" else y)

    @_gs1_builtin(_GS1_BUILTINS, "leftmousebutton")
    def _gb_leftmousebutton(self, name, indices, ctx):
        return bool(self.rt.mouse_left)

    @_gs1_builtin(_GS1_BUILTINS, "isleader")
    def _gb_isleader(self, name, indices, ctx):
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

    @_gs1_builtin(_GS1_BUILTINS, "tiles")
    def _gb_tiles(self, name, indices, ctx):
        # tiles[x,y] — the board tile id at (x,y), gmap-aware: world coords
        # on a gmap segment, local 0..63 in a standalone level (see
        # _board_locate). The room editor reads this for wall detection
        # (tiles[x,y] in {0x278,0x939}); writes route through set_builtin
        # below. Off-board indices answer 0 (a real "nothing there"); a
        # MISSING or stale board refuses to answer at all — see GS1NoBoard.
        if not self.rt.board_ready():
            raise GS1NoBoard("tiles[] read before the level board arrived")
        if len(indices) >= 2:
            v = board_tile_read(self.rt.client,
                                to_num(indices[0]), to_num(indices[1]))
            if v is not None:
                return v
        return 0.0

    def set_builtin(self, name, value, indices, ctx) -> bool:
        npc = ctx.this_obj
        # Bare `save[i] = n` — the running NPC's persistent slots. Without this
        # the write reached VarStore.set(None, "save", ...), which drops an
        # indexed write into a non-existent array (runtime.py:199-201), so
        # every classic Bomber room NPC advertised save[1]=0 and the room
        # controller's `npcs[n].save[1]==13` scan found nobody to refresh.
        # Same clamp the interpreter applies to `this.save[i]` (interp.py:836).
        if name == "save" and indices:
            slots = self.rt.npc_save_slots(getattr(ctx, "_npc_id", None),
                                           create=True)
            if slots is None:
                return False
            i = int(indices[0])
            if 0 <= i < len(slots):
                slots[i] = float(min(220, max(0, int(to_num(value)))))
            return True
        # `tiles[x,y] = id` — script board edit, same gmap-aware frame as the
        # _gb_tiles read above (LTTP's CheckTiles rewrites a slashed bush this
        # way, then calls updateboard). Handled even when the write lands
        # off-board/off-world, so a stray write doesn't fall through and
        # create a plain variable named "tiles".
        if name == "tiles" and len(indices) >= 2:
            board_tile_write(self.rt.client, to_num(indices[0]),
                             to_num(indices[1]), value)
            return True
        # `timeout = N` schedules the NPC's `timeout` event N seconds out. Most
        # bomber NPCs drive their logic this way (proximity checks, the room-join
        # processing, animations); the game loop fires it via process_timeouts.
        # `timeout = 0` CANCELS the pending event: TScriptSpace::setTimeout
        # (Preagonal/FourPlay/quattroplay/src/TScriptSpace.cpp:121-129) zeroes
        # and deactivates the timer for any value <= 0.0001. Re-arming at 0
        # instead turned the classic disable idiom `timeout = 0;` into a
        # permanent per-frame loop (GTA npc313's trunk-shrink timeout ran
        # forever, walking its imagepart width negative).
        if name == "timeout":
            t = to_num(value)
            if isinstance(npc, dict):
                npc["_timeout"] = None if t <= _TIMEOUT_CANCEL else t
                return True
            # weapon context (no NPC): re-arm the weapon's timeout event so its
            # per-frame gameplay loop keeps running (arenaGUI/arenaSYS do this).
            key = getattr(ctx, "_prog_key", None)
            if key is not None:
                if t <= _TIMEOUT_CANCEL:
                    self.rt._weapon_timeouts.pop(key, None)
                else:
                    self.rt._weapon_timeouts[key] = t
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
        """Run one GS1 command.

        Registry-driven, in the stage order the flat if/elif chain used: the
        first stage whose gate holds and whose handler does not return
        _FALL_THROUGH wins. Order matters -- `destroy`, `showimg`, `hideimg`,
        `setcharprop` and `setplayerprop` each appear in TWO stages with
        different behaviour. Anything no stage claims is silently ignored
        (client visuals we don't render).
        """
        handler = _GS1_PRE_COMMANDS.get(name)
        # `imgs` is deliberately still unresolved here: _layer_store() CREATES
        # the layer table as a side effect, and the pre-layer commands must not
        # cause that.
        if handler is not None and handler(self, name, args, ctx, None) is not _FALL_THROUGH:
            return
        # showimg/showani/changeimg*/showtext/showpoly/hideimg layer system.
        # NPCs paint floating images (lights, signs, furniture) addressed by a
        # numeric index and store them on npc['imgs']; weapons (no NPC obj --
        # e.g. arenaGUI's bombs, vases and explosions) store them in
        # _weapon_imgs. The renderer draws both. _layer_store resolves to the
        # right table for the running script, or None when there is nowhere to
        # store.
        imgs = self._layer_store(ctx)
        if imgs is not None:
            handler = _GS1_LAYER_COMMANDS.get(name)
            if handler is not None and handler(self, name, args, ctx, imgs) is not _FALL_THROUGH:
                return
        if isinstance(ctx.this_obj, dict):
            handler = _GS1_NPC_COMMANDS.get(name)
            if handler is not None and handler(self, name, args, ctx, imgs) is not _FALL_THROUGH:
                return
        handler = _GS1_MAIN_COMMANDS.get(name)
        if handler is not None and handler(self, name, args, ctx, imgs) is not _FALL_THROUGH:
            return
        if isinstance(ctx.this_obj, dict):
            handler = _GS1_NPC_TAIL_COMMANDS.get(name)
            if handler is not None:
                handler(self, name, args, ctx, imgs)

    # -- _GS1_PRE_COMMANDS: before the layer store is resolved --------------

    @_gs1_command(_GS1_PRE_COMMANDS, *_NOOP)
    def _cmd_noop(self, name, args, ctx, imgs):
        # Commands that just toggle/ignore for client rendering (input/feature
        # state we don't model, or world side-effects irrelevant to drawing the
        # lobby). Swallowed silently so a script full of them still runs its
        # visible commands. Membership is the _NOOP set, which other modules
        # read.
        return None

    @_gs1_command(_GS1_PRE_COMMANDS, "showstats")
    def _cmd_showstats(self, name, args, ctx, imgs):
        # showstats bitflag — select which default-HUD elements the client
        # draws (1 ASD, 2 icons, 4 gralats, 8 bombs, 16 arrows, 32 hearts,
        # 64 AP, 128 MP, 256 minimap, 512 inventory, 1024 players; allstats
        # = 2047). Scripted HUDs call showstats(allstats - <bits>) to hide
        # the built-in HUD before drawing their own. game/hud.py reads
        # rt.stats_mask each frame; None = never called = show everything.
        # State persists across level changes like the real client (levels
        # that care re-issue it on playerenters).
        self.rt.stats_mask = int(to_num(args[0])) if args else None

    @_gs1_command(_GS1_PRE_COMMANDS, "disabledefmovement", "enabledefmovement")
    def _cmd_defmovement(self, name, args, ctx, imgs):
        # disable/enable the engine's built-in WASD/arrow movement. The arena
        # weapons (arenaSYS) disable it and move the player themselves via
        # keydown()+playerx; the input layer checks rt.default_movement.
        self.rt.default_movement = name == "enabledefmovement"

    @_gs1_command(_GS1_PRE_COMMANDS, "enableweapons", "disableweapons")
    def _cmd_weapons_enabled(self, name, args, ctx, imgs):
        # real client-side state (backs the `weaponsenabled` flag), not just a
        # swallowed no-op
        self.rt.weapons_enabled = name == "enableweapons"

    @_gs1_command(_GS1_PRE_COMMANDS, "updateboard", "updateboard2")
    def _cmd_updateboard(self, name, args, ctx, imgs):
        # updateboard x,y,width,height — region redraw from board data (see
        # board_update_region for the oracle citation). GS2 scripts reach
        # this through the shared GS1-command surface (gs2_client routes any
        # reborn_protocol.gs1 COMMANDS name here), which is how LTTP's
        # -Player/Movement publishes its CheckTiles bush edits.
        if len(args) >= 4:
            board_update_region(self.rt.client,
                                to_num(args[0]), to_num(args[1]),
                                to_num(args[2]), to_num(args[3]))

    @_gs1_command(_GS1_PRE_COMMANDS, "addtiledef2")
    def _cmd_addtiledef2(self, name, args, ctx, imgs):
        # addtiledef2 <image>, <level>, <xoffset>, <yoffset> — paste an image
        # onto the active tileset sheet at the given pixel offset.
        rt = self.rt
        if len(args) >= 3 and rt.on_tiledef:
            image = to_str(args[0])
            levelstart = to_str(args[1]) if len(args) >= 2 else ""
            x = int(to_num(args[2]))
            y = int(to_num(args[3])) if len(args) >= 4 else 0
            rt.on_tiledef("paste", image, levelstart, x, y)

    @_gs1_command(_GS1_PRE_COMMANDS, "addtiledef")
    def _cmd_addtiledef(self, name, args, ctx, imgs):
        # addtiledef <image>[, <levelstart>[, <type>]] — replace the WHOLE
        # tileset (the image is a full 2048x512 sheet; Bomber v6's
        # bmb_pics1.png). The type selects the tile-TYPE table for matching
        # levels (0 classic, 1/2 new-world, 5 none — tiletypes.py); it is
        # registered even headless, where on_tiledef is unwired but script
        # probes (onwall/onwater/tiletype) still read the tables.
        rt = self.rt
        if not args:
            return
        image = to_str(args[0])
        levelstart = to_str(args[1]) if len(args) >= 2 else ""
        try:
            tile_type = int(to_num(args[2])) if len(args) >= 3 else 0
        except (TypeError, ValueError):
            tile_type = 0
        register_tiledef(levelstart, tile_type)
        if rt.on_tiledef:
            rt.on_tiledef("full", image, levelstart, tile_type)

    @_gs1_command(_GS1_PRE_COMMANDS, "removetiledefs")
    def _cmd_removetiledefs(self, name, args, ctx, imgs):
        # revert to the default tileset
        prefix = to_str(args[0]).lower() if args else ""
        remove_tiledefs(prefix)
        if self.rt.on_tiledef:
            self.rt.on_tiledef(None, prefix)

    @_gs1_command(_GS1_PRE_COMMANDS, "seteffect")
    def _cmd_seteffect(self, name, args, ctx, imgs):
        # seteffect r,g,b,a — fullscreen colour tint (Tier 3d). 0..1 floats.
        rt = self.rt
        if not (rt.on_seteffect and len(args) >= 4):
            return _FALL_THROUGH
        rt.on_seteffect(to_num(args[0]), to_num(args[1]),
                        to_num(args[2]), to_num(args[3]))

    @_gs1_command(_GS1_PRE_COMMANDS, "setcharprop", "setplayerprop")
    def _cmd_player_gattrib(self, name, args, ctx, imgs):
        # #P1..#P30 player gattribs (room slot lists). setcharprop/setplayerprop
        # on a #P code targets the PLAYER, not the NPC — store it so the script
        # can read it back via #P1(-1) etc. Any other code falls through to the
        # NPC-dict setcharprop / the on_setplayerprop callback below.
        rt = self.rt
        if len(args) < 2:
            return _FALL_THROUGH
        pk = _pcode(to_str(args[0]))
        if pk is None:
            return _FALL_THROUGH
        val = to_str(args[1])
        rt._player_props[pk] = val
        # sync our gattrib to the server so other players see it (the
        # bomber room queue shares slot lists this way)
        try:
            if rt.client is not None:
                rt.client.set_gattrib(int(pk[1:]), val)
        except Exception:
            pass

    @_gs1_command(_GS1_PRE_COMMANDS, "replaceani")
    def _cmd_replaceani(self, name, args, ctx, imgs):
        # replaceani orig,new — swap a default player ani for a level-supplied
        # one (visuals via the game client's resolver AND #m, which scripts
        # test — e.g. the bomber stairs NPC's walk check). One arg restores
        # the default.
        rt = self.rt
        if not args:
            return _FALL_THROUGH
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

    @_gs1_command(_GS1_PRE_COMMANDS, *_NPC_WRITE)
    def _cmd_npc_write(self, name, args, ctx, imgs):
        # command -> NPC dict key it writes, so the renderer reflects the
        # change (the _NPC_WRITE table).
        if not args:
            return _FALL_THROUGH
        npc = ctx.this_obj
        if isinstance(npc, dict):
            npc[_NPC_WRITE[name]] = to_str(args[0])

    # -- player / game commands (work for weapon scripts too, where there
    # is no NPC object) -----------------------------------------------------

    @_gs1_command(_GS1_PRE_COMMANDS, "setani")
    def _cmd_setani(self, name, args, ctx, imgs):
        # setani ALWAYS drives the LOCAL PLAYER's gani, even from an NPC
        # script — setcharani is the NPC-targeting form (GServer-v2
        # GS1Commands.cpp resolves setani to the player, setcharani to the
        # npc; the GS2 host's _bi_setani splits the same way). Aliasing both
        # onto the NPC made bomber-classic's piano vanish on seating: doPlay's
        # `setani sen_piano_idle,;` replaced the piano NPC's own gani, and
        # the seated player never showed the playing pose.
        rt = self.rt
        if not args:
            return _FALL_THROUGH
        joined = ",".join(to_str(a) for a in args).rstrip(",")
        base = joined.split(",")[0].strip()
        if not base:
            return None
        # Wire prop (other clients + #m); set_animation applies replaceani.
        send = getattr(rt.client, "set_animation", None)
        if send is not None:
            try:
                send(base)
            except Exception:
                pass
        # Local mirror: the renderer draws the local player from
        # player_anim/current_anim_name, which only the built-in input path
        # updates — the pygame shell wires on_setani (game/setup.py) to
        # reflect the scripted gani (params ride along: a gani's PLAYSOUND
        # is routinely a PARAMn token).
        if rt.on_setani:
            rt.on_setani(joined)
        return None

    @_gs1_command(_GS1_PRE_COMMANDS, "setlevel2", "setlevel")
    def _cmd_setlevel(self, name, args, ctx, imgs):
        rt = self.rt
        if not (rt.on_warp and args):
            return _FALL_THROUGH
        x = to_num(args[1]) if len(args) > 1 else None
        y = to_num(args[2]) if len(args) > 2 else None
        rt.on_warp(to_str(args[0]), x, y)

    @_gs1_command(_GS1_PRE_COMMANDS, "freezeplayer", "unfreezeplayer")
    def _cmd_freezeplayer(self, name, args, ctx, imgs):
        rt = self.rt
        # unfreezeplayer cancels a running freeze early (GTA's magic system
        # pairs `freezeplayer <cast time>` with it); freezeplayer 0 through
        # the same path clears both the rt deadline and the game shell's.
        secs = 0.0 if name == "unfreezeplayer" else (
            to_num(args[0]) if args else 0.5)
        if rt.on_freezeplayer:
            rt.on_freezeplayer(secs)
        import time as _t
        rt._freeze_until = _t.monotonic() + max(0.0, secs)

    @_gs1_command(_GS1_PRE_COMMANDS, "hitobjects")
    def _cmd_hitobjects(self, name, args, ctx, imgs):
        # hitobjects power,x,y — client-side sword-hit emulation (see
        # npcserver.md "Emulating sword hits"): fire `washit` on NPCs and hurt
        # baddies at that (level-local) point, same effects as a real sword
        # swing (client.py _sword_hit_npcs/_sword_hit_baddies).
        if len(args) < 3:
            return _FALL_THROUGH
        self.rt.hit_objects_at(to_num(args[1]), to_num(args[2]), to_num(args[0]))

    @_gs1_command(_GS1_PRE_COMMANDS, "setminimap")
    def _cmd_setminimap(self, name, args, ctx, imgs):
        if not self.rt.on_setminimap:
            return _FALL_THROUGH
        self.rt.on_setminimap([to_str(a) for a in args])

    @_gs1_command(_GS1_PRE_COMMANDS, "setfocus")
    def _cmd_setfocus(self, name, args, ctx, imgs):
        # setfocus x,y — camera looks at a level position instead of the
        # player (GTA's splashscreen/cutscenes); resetfocus returns it.
        if not (self.rt.on_setfocus and len(args) >= 2):
            return _FALL_THROUGH
        self.rt.on_setfocus(to_num(args[0]), to_num(args[1]))

    @_gs1_command(_GS1_PRE_COMMANDS, "resetfocus")
    def _cmd_resetfocus(self, name, args, ctx, imgs):
        if self.rt.on_setfocus:
            self.rt.on_setfocus(None, None)

    @_gs1_command(_GS1_PRE_COMMANDS, "toweapons")
    def _cmd_toweapons(self, name, args, ctx, imgs):
        rt, npc = self.rt, ctx.this_obj
        if not (rt.on_toweapons and args):
            return _FALL_THROUGH
        weapon_name = to_str(args[0])
        if getattr(ctx, "_is_weapon", False):
            rt.on_toweapons(weapon_name)
            return
        script = npc.get("script", "") if isinstance(npc, dict) else ""
        image = npc.get("image", "") if isinstance(npc, dict) else ""
        if isinstance(script, bytes):
            script = script.decode("latin-1")
        try:
            rt.on_toweapons(weapon_name, getattr(ctx, "_npc_id", 0), script, image)
        except TypeError:
            # Some headless integrations still expose the original callback.
            rt.on_toweapons(weapon_name)

    # -- _GS1_LAYER_COMMANDS (gate: the script has a layer store) -----------

    @_gs1_command(_GS1_LAYER_COMMANDS, "showimg", "showimg2")
    def _cmd_showimg_layer(self, name, args, ctx, imgs):
        if len(args) < 2:
            return _FALL_THROUGH
        idx = int(to_num(args[0]))
        rec = imgs.setdefault(idx, {})
        src = to_str(args[1])
        if src.startswith("@"):
            # Classic text form: showimg idx,@font@text,x,y (font may
            # be empty). GTA's splashscreen menu is drawn entirely
            # this way (@b@Start / @Wingdings@è); treating it as an
            # image filename rendered nothing.
            parts = src.split("@", 2)
            rec.pop("image", None)
            rec["font"] = parts[1] if len(parts) > 1 else ""
            rec["style"] = ""
            rec["text"] = parts[2] if len(parts) > 2 else ""
            rec["text_is"] = True
        else:
            rec["image"] = src
            rec.pop("text", None)
            rec.pop("text_is", None)
        if len(args) >= 4:
            rec["x"], rec["y"] = to_num(args[2]), to_num(args[3])
        rec["screen"] = (name == "showimg2")
        rec.setdefault("vis", 4)

    @_gs1_command(_GS1_LAYER_COMMANDS, "showani", "showani2")
    def _cmd_showani(self, name, args, ctx, imgs):
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
        if len(args) < 3:
            return _FALL_THROUGH
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

    @_gs1_command(_GS1_LAYER_COMMANDS, "changeimgpart")
    def _cmd_changeimgpart(self, name, args, ctx, imgs):
        if len(args) < 5:
            return _FALL_THROUGH
        rec = imgs.get(int(to_num(args[0])))
        if rec is not None:
            rec["part"] = (int(to_num(args[1])), int(to_num(args[2])),
                           int(to_num(args[3])), int(to_num(args[4])))

    @_gs1_command(_GS1_LAYER_COMMANDS, "changeimgcolors")
    def _cmd_changeimgcolors(self, name, args, ctx, imgs):
        # too few args: ignore (do NOT fall through -- the flat chain had a
        # second, bodyless `changeimgcolors` arm for exactly this)
        if len(args) >= 5:
            rec = imgs.get(int(to_num(args[0])))
            if rec is not None:
                rec["colors"] = tuple(to_num(a) for a in args[1:5])

    @_gs1_command(_GS1_LAYER_COMMANDS, "changeimgzoom")
    def _cmd_changeimgzoom(self, name, args, ctx, imgs):
        if len(args) < 2:
            return _FALL_THROUGH
        rec = imgs.get(int(to_num(args[0])))
        if rec is not None:
            rec["zoom"] = to_num(args[1])

    @_gs1_command(_GS1_LAYER_COMMANDS, "changeimgvis")
    def _cmd_changeimgvis(self, name, args, ctx, imgs):
        if len(args) < 2:
            return _FALL_THROUGH
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

    @_gs1_command(_GS1_LAYER_COMMANDS, "changeimgmode")
    def _cmd_changeimgmode(self, name, args, ctx, imgs):
        if len(args) < 2:
            return _FALL_THROUGH
        rec = imgs.get(int(to_num(args[0])))
        if rec is not None:
            rec["mode"] = int(to_num(args[1]))

    @_gs1_command(_GS1_LAYER_COMMANDS, "showtext")
    def _cmd_showtext(self, name, args, ctx, imgs):
        if len(args) < 6:
            return _FALL_THROUGH
        imgs[int(to_num(args[0]))] = {
            "x": to_num(args[1]), "y": to_num(args[2]),
            "font": to_str(args[3]), "style": to_str(args[4]),
            "text": to_str(args[5]), "text_is": True, "vis": 4,
            "screen": False,
        }

    @_gs1_command(_GS1_LAYER_COMMANDS, "showtext2")
    def _cmd_showtext2(self, name, args, ctx, imgs):
        # showtext2 index,x,y,zoom,font,style,text (lexer 'EEEESSS' —
        # one more arg than showtext's 'EEESSS', an extra leading
        # zoom float before font/style/text).
        if len(args) < 7:
            return _FALL_THROUGH
        imgs[int(to_num(args[0]))] = {
            "x": to_num(args[1]), "y": to_num(args[2]),
            "zoom": to_num(args[3]),
            "font": to_str(args[4]), "style": to_str(args[5]),
            "text": to_str(args[6]), "text_is": True, "vis": 4,
            "screen": True,
        }

    @_gs1_command(_GS1_LAYER_COMMANDS, "hideimg", "hidetext")
    def _cmd_hideimg_layer(self, name, args, ctx, imgs):
        if not args:
            return _FALL_THROUGH
        imgs.pop(int(to_num(args[0])), None)

    @_gs1_command(_GS1_LAYER_COMMANDS, "hideimgs")
    def _cmd_hideimgs(self, name, args, ctx, imgs):
        # hideimgs start,end — clear layers in [start, end] (the bomber
        # uses this form, e.g. `hideimgs 300,304`). hideimgs start — from
        # start onward. hideimgs — all.
        start = int(to_num(args[0])) if args else None
        end = int(to_num(args[1])) if len(args) >= 2 else None
        for k in [k for k in imgs
                  if (start is None or k >= start)
                  and (end is None or k <= end)]:
            imgs.pop(k, None)

    @_gs1_command(_GS1_LAYER_COMMANDS, "showpoly", "showpoly2")
    def _cmd_showpoly(self, name, args, ctx, imgs):
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
        if len(args) < 2:
            return _FALL_THROUGH
        rec = imgs.setdefault(int(to_num(args[0])), {})
        rec["poly"] = [float(to_num(v)) for v in args[1]]
        rec["poly_dim"] = 3 if name == "showpoly2" else 2
        rec.setdefault("vis", 4)

    # -- _GS1_NPC_COMMANDS (gate: the script has an NPC dict) ---------------

    @_gs1_command(_GS1_NPC_COMMANDS, "setzoomeffect")
    def _cmd_setzoomeffect(self, name, args, ctx, imgs):
        if not args:
            return _FALL_THROUGH
        ctx.this_obj["zoom_effect"] = to_num(args[0])

    @_gs1_command(_GS1_NPC_COMMANDS, "seteffectmode")
    def _cmd_seteffectmode(self, name, args, ctx, imgs):
        if not args:
            return _FALL_THROUGH
        ctx.this_obj["effect_mode"] = int(to_num(args[0]))

    @_gs1_command(_GS1_NPC_COMMANDS, "setcoloreffect")
    def _cmd_setcoloreffect(self, name, args, ctx, imgs):
        if len(args) < 4:
            return _FALL_THROUGH
        ctx.this_obj["coloreffect"] = tuple(to_num(v) for v in args[:4])

    @_gs1_command(_GS1_NPC_COMMANDS, "showcharacter")
    def _cmd_showcharacter(self, name, args, ctx, imgs):
        ctx.this_obj["is_character"] = True

    @_gs1_command(_GS1_NPC_COMMANDS, "setcharprop")
    def _cmd_setcharprop_npc(self, name, args, ctx, imgs):
        # a non-#P code: mirror a Reborn player's appearance slots
        # (_CHARPROP_NPC) onto the NPC so showcharacter composites it
        if len(args) < 2:
            return _FALL_THROUGH
        key = _CHARPROP_NPC.get(to_str(args[0]))
        if key is not None:
            ctx.this_obj[key] = to_str(args[1])

    @_gs1_command(_GS1_NPC_COMMANDS, "drawoverplayer", "drawunderplayer")
    def _cmd_draw_layer(self, name, args, ctx, imgs):
        ctx.this_obj["draw_layer"] = ("over" if name == "drawoverplayer"
                                      else "under")

    @_gs1_command(_GS1_NPC_COMMANDS, "dontblock", "dontblocklocal")
    def _cmd_dontblock(self, name, args, ctx, imgs):
        # dontblocklocal differs only in wire sync (scriptfun_servernpc_
        # dontblocklocal, TServerNPCProperties.cpp:443 — same blocking field
        # as dontblock :436); identical client-side.
        #
        # Sets ONLY the not-blocking flag. The reference command writes one
        # boolean (TServerNPCProperties.cpp:436-446) and leaves the shape
        # geometry alone, so `blockagain` restores blocking with the shape
        # intact, and the shape stays available to TOUCH tests (which ignore
        # the blocking flag — see npc_blocks_at's rule derivation). The old
        # code here popped rt.shapes and the published cells, which made
        # blockagain a no-op and killed touch on any dontblock'ed NPC.
        ctx.this_obj["dontblock"] = True

    @_gs1_command(_GS1_NPC_COMMANDS, "blockagain", "blockagainlocal")
    def _cmd_blockagain(self, name, args, ctx, imgs):
        # inverse of dontblock: clears the same flag
        # (scriptfun_servernpc_blockagain/blockagainlocal,
        # TServerNPCProperties.cpp:358-371). Blocking queries read the flag
        # live, so the NPC's footprint (shape cells or image rect) resumes
        # blocking immediately — GTA's doors re-arm this way on timeout.
        ctx.this_obj["dontblock"] = False

    @_gs1_command(_GS1_NPC_COMMANDS, "destroy")
    def _cmd_destroy_npc(self, name, args, ctx, imgs):
        ctx.this_obj["visible"] = False
        ctx.this_obj.pop("imgs", None)
        entry = self.rt._progs.get(getattr(ctx, "_prog_key", None))
        if entry is not None:
            entry["inactive"] = True
        npc_id = getattr(ctx, "_npc_id", 0)
        if npc_id > 0 and self.rt.client is not None:
            self.rt.client.delete_npc(npc_id)

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

    @_gs1_command(_GS1_MAIN_COMMANDS, "play", "play2", "playlooped", "setmusic")
    def _cmd_play(self, name, args, ctx, imgs):
        if not (args and self.rt.on_play):
            return _FALL_THROUGH
        self.rt.on_play(to_str(args[0]))

    @_gs1_command(_GS1_MAIN_COMMANDS, "stopmidi", "stopsong")
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

    # -- _GS1_NPC_TAIL_COMMANDS (gate: an NPC dict; last stage) -------------

    @_gs1_command(_GS1_NPC_TAIL_COMMANDS, "hide", "show",
                  "hidelocal", "showlocal")
    def _cmd_visible(self, name, args, ctx, imgs):
        # The *local forms only differ on the wire (visibility change not
        # synced to other players — scriptfun_servernpc_hidelocal/showlocal,
        # TServerNPCProperties.cpp:460/:778 vs hide/show :453/:757); for a
        # client-side renderer they are the same toggle. Live GTA uses
        # hidelocal 67 times across its weapon scripts.
        ctx.this_obj["visible"] = name in ("show", "showlocal")

    @_gs1_command(_GS1_NPC_TAIL_COMMANDS, "move")
    def _cmd_move(self, name, args, ctx, imgs):
        npc = ctx.this_obj
        if len(args) >= 2:
            npc["x"] = to_num(npc.get("x", 0)) + to_num(args[0])
            npc["y"] = to_num(npc.get("y", 0)) + to_num(args[1])

    # -- functions / message codes ----------------------------------------
    def call_function(self, name, args, ctx):
        # Predicate functions return real bools (upstream returns bool
        # GameValues); floats would read false in conditions — see the
        # truthiness note in get_builtin.
        if name == "onwall":
            x = int(to_num(args[0])) if args else 0
            y = int(to_num(args[1])) if len(args) > 1 else 0
            return bool(self.rt.is_wall(
                x, y, exclude_npc=getattr(ctx, "_npc_id", None)))
        if name == "onwall2":
            # onwall2(x, y[, width, height]) — the GS2/v6 4-arg rect form
            # (used by -Test_Movement's CheckWall probes) tests every tile
            # the [x,x+w) x [y,y+h) rect covers. The 2/3-arg legacy form
            # keeps the single-tile check (3rd arg = layer, unmodelled).
            # w/h clamp: >=0 (scripts pass slightly-negative degenerate
            # widths, which the rect walk must treat as "just this tile"),
            # <=8 so a bogus huge rect can't stall the frame.
            #
            # Far edges are EXCLUSIVE minus a quarter-tile forgiveness
            # (_ONWALL2_EDGE_TOL). Why: the reference client (FourPlay
            # TServerLevel::isRectOnWall) rejects w<=0 or h<=0 outright, so
            # movement scripts whose probe extents come out degenerate
            # (-Test/Movement passes speed/16 - 1/16 = -0.04375 with
            # player.speed = 0.3 tiles) check NOTHING on a real client. Our
            # origin-cell fallback is what makes them block at all — but it
            # only trips after the check-then-move loop has stepped the
            # leading edge INTO the wall row, so the player rests penetrated
            # by up to one step (0.3). The perpendicular slide probes
            # (extent 15/16) then graze that wall row/column by
            # (penetration - 1/16) <= 0.2375, and an exact coverage walk
            # counted the grazed cell: pressed flush against a bottom wall
            # you couldn't move left/right, against a right wall not
            # up/down. Forgiving far-edge slivers <= 0.25 restores sliding
            # (and gives classic corner-assist feel); integer-aligned rects
            # and any overlap beyond a quarter tile behave exactly as
            # before.
            xf = to_num(args[0]) if args else 0.0
            yf = to_num(args[1]) if len(args) > 1 else 0.0
            _self_id = getattr(ctx, "_npc_id", None)
            if len(args) >= 4:
                import math as _m
                w = min(max(to_num(args[2]), 0.0), 8.0)
                h = min(max(to_num(args[3]), 0.0), 8.0)
                x0, y0 = int(_m.floor(xf)), int(_m.floor(yf))
                x1 = max(x0, int(_m.ceil(xf + w - _ONWALL2_EDGE_TOL)) - 1)
                y1 = max(y0, int(_m.ceil(yf + h - _ONWALL2_EDGE_TOL)) - 1)
                for ty in range(y0, y1 + 1):
                    for tx in range(x0, x1 + 1):
                        if self.rt.is_wall(tx, ty, exclude_npc=_self_id):
                            return True
                return False
            return bool(self.rt.is_wall(int(xf), int(yf),
                                        exclude_npc=_self_id))
        if name in ("onwater", "onwater2"):
            x = int(to_num(args[0])) if args else 0
            y = int(to_num(args[1])) if len(args) > 1 else 0
            return bool(self.rt.is_water_at(x, y))
        if name == "tiletype":
            # tiletype(x, y) — bare, or as `level.tiletype(...)` (the member
            # form arrives here too; the level object has no such member so
            # the VM falls through to the host). Zelda's -Player/Movement
            # gates sitting (3), sleeping (4/5) and ledge-jumps (21) on it.
            return self.rt.tile_type_at(to_num(args[0]) if args else 0.0,
                                        to_num(args[1]) if len(args) > 1 else 0.0)
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
        if name == "testnpc":
            return self._test_at(args, players=False)
        if name == "testplayer":
            return self._test_at(args, players=True)
        if name == "playersays":
            return self._playersays(args, contains=False)
        if name == "playersays2":
            return self._playersays(args, contains=True)
        return UNSET

    def _test_at(self, args, players):
        """testnpc(x, y) / testplayer(x, y) — the npcs[] / players[] INDEX of
        the object whose collision rect covers the TILE coordinate (x, y),
        or -1 / -2 on a miss.

        The index is the whole point: classic Bomber's shop counter reaches
        its item catalogue with `callnpc testnpc(56,26),GrabItemList,...`
        (Preagonal/graal-bomber-gs1/world/bomblobby.nw:792), so this must
        agree with _cmd_callnpc's ordering — both walk _npc_ids(). Falling
        through to UNSET (0.0) sent every such call to npcs[0] instead, which
        is why the shop's clientr.Shop_* lists stayed empty.

        Hit-test semantics mirror the server host (pygserver gs1_host.py:515
        _test_at, :542 _collision_rect) so the two engines answer the same
        question — see _npc_rect. Units: the probe arrives in TILES and the
        comparison runs in PIXELS, both rect edges inclusive.

        Miss values are the server host's. The reference client's own
        testplayer answers -1 for both cases
        (Preagonal/FourPlay/quattroplay/src/TInitStatics.cpp:3880), but real
        content only ever tests `< 0` (`if(testnpc(19,17.5)<0) putnpc ...`),
        so agreeing with the server host costs nothing.
        """
        miss = -2.0 if players else -1.0
        if len(args) < 2:
            return miss
        px = math.floor(to_num(args[0]) * 16)
        py = math.floor(to_num(args[1]) * 16)
        if players:
            rects = [self._char_rect(p.get("x", 0), p.get("y", 0))
                     for p in self._player_list()]
        else:
            npcs = getattr(self.rt.client, "npcs", {}) or {}
            rects = [self._npc_rect(npc_id, npcs.get(npc_id))
                     for npc_id in self._npc_ids()]
        for index, rect in enumerate(rects):
            if rect is None:
                continue
            x, y, width, height = rect
            if x <= px <= x + width and y <= py <= y + height:
                return float(index)
        return miss

    @staticmethod
    def _char_rect(x, y):
        """The feet-centred 2x2-tile collision square, in pixels."""
        return to_num(x) * 16 + 8, to_num(y) * 16 + 16, 32, 32

    def _npc_rect(self, npc_id, npc):
        """An NPC's collision rect in pixels for _test_at: its setshape/
        setshape2 box if it set one, else the character square, else None —
        a plain image NPC that never called setshape cannot be hit at all.

        rt.shapes holds the box in TILES (_cmd_setshape divides the command's
        PIXEL width/height by 16), so a `setshape 1,96,16` counter is 6x1
        tiles and scales back to 96x16 px here."""
        if not isinstance(npc, dict):
            return None
        x, y = to_num(npc.get("x", 0)) * 16, to_num(npc.get("y", 0)) * 16
        shape = self.rt.shapes.get(npc_id)
        if shape and len(shape) >= 2:
            return x, y, to_num(shape[0]) * 16, to_num(shape[1]) * 16
        if npc.get("gani") or npc.get("body_image") or npc.get("head_image"):
            return self._char_rect(npc.get("x", 0), npc.get("y", 0))
        return None

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
                value = npc.get(key, "")
                return (_color_name(value) if _is_color_code(code)
                        else to_str(value))
        elif player is not None:
            # No NPC source, i.e. a WEAPON script: the appearance codes
            # resolve against the PLAYER. "No index means we try to get the
            # character from the current source, biasing to the initiator"
            # (GS1MessageCodes.cpp:281-287) — for a weapon the initiator is
            # its owner. Answering "" here is what made classic Bomber's
            # tailor snapshot blanks in grab_Old(), so its Cancel() reset the
            # player's head, body and all five colours to white.
            index = int(to_num(args[0])) if args else 0
            if index < 0:
                return ""      # -1 asks for the source NPC; a weapon has none
            key = _CHARPROP_PLAYER.get(code)
            if key is not None:
                return to_str(getattr(player, key, "") or "")
            slot = _color_code_slot(code)
            if slot is not None:
                colors = list(getattr(player, "colors", None) or [])
                return _color_name(colors[slot]) if slot < len(colors) else ""
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
    into the SERVER scope, so every pet rendered as the default squirrel.

    Only `client.` writes go on the wire. `clientr.` shares this storage (GS1's
    NAMESPACES folds the two spellings together) but is a plain local variable
    upstream: the reference client binds `client` to a self-sending
    TGraalClientVar and `clientr` to an ordinary TGraalVar
    (Preagonal/FourPlay/quattroplay/src/TPlayer.cpp:642,649), and
    TClient::sendFlag drops any name that does not start with "client."
    (TClient.cpp:895). set_local() is that non-sending write; the spelling the
    script used reaches it via _ClientScopeVarStore. Before this, opening
    classic Bomber's shop pushed its three `clientr.Shop_*` scratch strings
    onto the live account."""

    def __init__(self, rt):
        super().__init__()
        self._rt = rt
        self._sent = {}

    def set_local(self, k, v):
        """Store without transmitting — the `clientr.` write path. Mirrors GS2's
        read-only flag views (gs2_client.py _FlagScopeObject local_writes)."""
        dict.__setitem__(self, k, v)

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


class _ClientScopeVarStore(VarStore):
    """VarStore that keeps `client.` and `clientr.` writes apart.

    The shared runtime folds both spellings into the one "client" scope
    (NAMESPACES, reborn_protocol/gs1/runtime.py:25) and _PlayerFlagScope holds
    the merged storage, which is right for reads — but only `client.` writes
    are transmitted (see _PlayerFlagScope). `_ref_namespace` is the spelling of
    the reference currently being resolved, published by
    _RefNamespaceInterpreter; it is trustworthy here because every scoped write
    is `_resolve(ref)` immediately followed by this `set()`, with nothing
    resolvable in between (interp.py:832-842 set_ref, :863-865 _store_set).
    """

    #: spelling of the reference being written; "client" unless a
    #: `clientr.`-spelled reference was the last thing resolved.
    _ref_namespace = "client"

    def set(self, scope, key, value, index=None):
        if scope == "client" and index is None and self._ref_namespace != "client":
            table = self.scopes.get("client")
            if isinstance(table, _PlayerFlagScope):
                table.set_local(key, value)
                return
        super().set(scope, key, value, index)


class _RefNamespaceInterpreter(Interpreter):
    """Interpreter that tells the VarStore which spelling a player-flag
    reference used, since _resolve is the last place it still exists.

    Tagging AFTER super()._resolve() matters: a nested reference (a `clientr.`
    read in the write's value or index expression) is resolved first, so the
    outer reference — resolved last, right before the store — is the spelling
    that decides.
    """

    def _resolve(self, ref):
        resolved = super()._resolve(ref)
        scope, _key, _indices, names = resolved
        if scope == "client":
            store = self.ctx.vars
            if isinstance(store, _ClientScopeVarStore):
                store._ref_namespace = names[0] if names else "client"
        return resolved


def _pcode(code):
    """#P1..#P30 player-gattrib code -> store key 'P1'..; else None."""
    if code and code.startswith("#P") and code[2:].isdigit():
        return code[1:]
    return None


def _num_or_str(v):
    return host_value(v)


def _version_number(version) -> float:
    """A negotiated client-version string as the number the client-version
    builtin reports (see _gb_client_version).

    Takes the leading numeric run, so the build-suffixed spellings in
    protocol.VERSIONS ("6.037_linux") answer the same as their base version.
    Anything with no leading number answers 0.0.
    """
    text = str(version or "").strip()
    end = 0
    while end < len(text) and (text[end].isdigit() or text[end] == "."):
        end += 1
    try:
        return float(text[:end])
    except ValueError:
        return 0.0


def _color_code_slot(code):
    """`#C0`..`#C7` -> its COLORS slot number; anything else -> None."""
    if code and code.startswith("#C") and code[2:].isdigit():
        return int(code[2:])
    return None


def _is_color_code(code) -> bool:
    return _color_code_slot(code) is not None


def _color_name(value) -> str:
    """A COLORS slot as the palette NAME a `#Cn` read reports.

    Slots reach us as palette INDICES (PLPROP_COLORS, Player.colors) but
    scripts also write names (`setcharprop #C0,orange`), so accept either and
    always answer the name — see the `#Cn` handling in message_code for why
    that direction is the one the content needs. An unset/out-of-range slot is
    "" (no answer), not a colour: white is a real value a script may act on.
    """
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        text = value.strip().lower()
        text = REBORN_PALETTE_ALIASES.get(text, text)
        if text in REBORN_PALETTE:
            return text
        try:
            value = float(text)
        except ValueError:
            return ""      # neither a palette name nor an index: no answer
    try:
        index = int(to_num(value))
    except (TypeError, ValueError):
        return ""
    if 0 <= index < len(REBORN_PALETTE):
        return REBORN_PALETTE[index]
    return ""


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
        self.on_movement_changed = None
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
        if not image:
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
