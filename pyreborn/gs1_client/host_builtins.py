from __future__ import annotations

import logging

from reborn_protocol.gs1.runtime import UNSET
from reborn_protocol.gs1.values import to_num, to_str
from reborn_protocol.gs1.host_shared import tokens_count

from .board import GS1NoBoard, board_tile_read, board_tile_write
from .objects import _num_or_str, _version_number
from .registry import NPC_ATTR, PLAYER_ATTR, _GS1_BUILTINS, _GS1_NPC_BUILTINS, _GS1_PLAYER_BUILTINS, _TIMEOUT_CANCEL, _gs1_builtin



logger = logging.getLogger(__name__)


class BuiltinsMixin:
    def get_builtin(self, name, indices, ctx):
        """Read a GS1 built-in variable. Registry-driven: three stages, each a
        @_gs1_builtin table plus the data table that shares its gate.

        Returning UNSET means "not a built-in here" and sends the interpreter
        on to the ordinary flag/var lookup -- `statsoff` uses that
        deliberately, so a handler may return it too.
        """
        # era new-GS1 with-scope: `with (findimg(200)) { with (emitter)
        # {...} }` sets this_obj to a HOST OBJECT (_LayerImage / particle
        # objects, flagged gs1_with_members); its claimed members shadow
        # everything, like the innermost with-target does in the reference.
        # Unclaimed names fall through to the normal stages.
        this_obj = getattr(ctx, "this_obj", None)
        if getattr(this_obj, "gs1_with_members", False):
            v = self._with_member_get(this_obj, name, indices)
            if v is not UNSET:
                return v
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
        # bombs[i].x/y/power/time and explos[i].x/y/power/radius -- the level
        # projectile arrays (scripting-gs1-variables.md "Bombs"; GTA reads
        # both: ffort1.nw's conveyor re-lays `bombs[this.i].power` and
        # uwwatershrine.nw branches on `explos[this.i].power`).
        if name.startswith("bombs."):
            return self._bomb_array_attr(name.split(".", 1)[1], indices)
        if name.startswith("explos."):
            return self._explo_array_attr(name.split(".", 1)[1], indices)
        # compus[i].x/y/power/mode/dir/type -- the classic baddies array
        # (scripting-gs1-variables.md "Baddies"); GTA's hitcompu callers
        # branch on `compus[this.i].y`/`.mode` before striking.
        if name.startswith("compus."):
            return self._compu_array_attr(name.split(".", 1)[1], indices)
        return UNSET

    def _npc_ids(self):
        """Return level NPC IDs in `npcs[]` index order.

        GS1 uses level order for the npcs[] array. Client.npcs uses the server's
        NPC ID as its key. The server allocates these IDs in level order. Thus,
        sorting the IDs reproduces the array order.
        """
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

    def _bomb_list(self):
        """Live bombs in bombs[] index order (see rt.bombs_source)."""
        src = self.rt.bombs_source
        if src is not None:
            try:
                return [b for b in (src() or []) if not b.get("exploded")]
            except Exception:
                return []
        cl = self.rt.client
        return list(getattr(cl, "bombs", {}).values()) if cl else []

    def _explo_list(self):
        """Active explosions in explos[] index order (client-level registry,
        shared with the PLO_EXPLOSION handler and the renderer)."""
        cl = self.rt.client
        return list(getattr(cl, "active_explosions", []) or []) if cl else []

    def _baddy_ids(self):
        """Baddy ids in compus[] index order: like npcs[], the server allocates
        them in level order, so the sorted ids reproduce the array."""
        cl = self.rt.client
        if cl is None:
            return []
        return sorted(getattr(cl, "baddies", {}) or {})

    def _bomb_array_attr(self, attr, indices):
        bombs = self._bomb_list()
        i = int(indices[0]) if indices else 0
        if not 0 <= i < len(bombs):
            return 0.0
        b = bombs[i]
        if attr == "time":
            # seconds until it explodes. Shell bombs carry a placement stamp
            # + fuse; a wire-echo dict only has the total timer.
            import time as _t
            if "fuse_time" in b:
                return max(0.0, float(b.get("time", 0))
                           + float(b.get("fuse_time", 0)) - _t.time())
            return float(b.get("timer_ms", 0)) / 1000.0
        if attr in ("x", "y", "power"):
            return to_num(b.get(attr, 0))
        return 0.0

    def _explo_array_attr(self, attr, indices):
        explos = self._explo_list()
        i = int(indices[0]) if indices else 0
        if not 0 <= i < len(explos):
            return 0.0
        if attr in ("x", "y", "power", "radius"):
            return to_num(explos[i].get(attr, 0))
        return 0.0

    def _compu_array_attr(self, attr, indices):
        ids = self._baddy_ids()
        i = int(indices[0]) if indices else 0
        if not 0 <= i < len(ids):
            return 0.0
        baddy = self.rt.client.baddies.get(ids[i])
        if not isinstance(baddy, dict):
            return 0.0
        key = {"dir": "direction", "headdir": "direction"}.get(attr, attr)
        if key in ("x", "y", "power", "mode", "type", "direction"):
            return to_num(baddy.get(key, 0))
        if key == "image":
            return to_str(baddy.get("image", ""))
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

    @_gs1_builtin(_GS1_BUILTINS, "bombscount")
    def _gb_bombscount(self, name, indices, ctx):
        return float(len(self._bomb_list()))

    @_gs1_builtin(_GS1_BUILTINS, "exploscount")
    def _gb_exploscount(self, name, indices, ctx):
        return float(len(self._explo_list()))

    @_gs1_builtin(_GS1_BUILTINS, "compuscount")
    def _gb_compuscount(self, name, indices, ctx):
        return float(len(self._baddy_ids()))

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
        # era with-scope writes on a host object -- see get_builtin
        this_obj = getattr(ctx, "this_obj", None)
        if getattr(this_obj, "gs1_with_members", False):
            if self._with_member_set(this_obj, name, value, indices):
                return True
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
