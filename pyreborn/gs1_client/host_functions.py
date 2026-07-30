from __future__ import annotations

import logging
import math

from reborn_protocol.gs1.runtime import NAMESPACES, UNSET
from reborn_protocol.gs1.values import to_num, to_str

from .objects import _GS1ObjectRef, _color_code_slot, _color_name, _is_color_code, _pcode
from .registry import _CHARPROP_NPC, _CHARPROP_PLAYER, _ONWALL2_EDGE_TOL



logger = logging.getLogger(__name__)


class FunctionsMixin:
    # -- functions / message codes ----------------------------------------
    def call_function(self, name, args, ctx):
        # Predicate functions return real bools (upstream returns bool
        # GameValues); floats would read false in conditions — see the
        # truthiness note in get_builtin.
        #
        # era with-scope method surface first: a bare `addlocalmodifier(...)`
        # inside `with (emitter) {...}` is a method call on the with target
        # (same innermost-with rule as the member bridge in get_builtin).
        hook = getattr(getattr(ctx, "this_obj", None), "gs1_method", None)
        if hook is not None:
            res = hook(name.lower(), args)
            if res is not NotImplemented:
                return res
        lowered = name.lower()
        if lowered in ("getplayer", "findplayer"):
            return self._object_ref(args, "player")
        if lowered in ("getnpc", "findnpc"):
            return self._object_ref(args, "npc")
        if name == "findimg" and ctx is not None:
            # era new-GS1 particle scripts reach the layer/emitter objects
            # this way (`with (findimg(200)) { with (emitter) {...} }`,
            # eradev2 particle_smoke.txt:14). Shared resolver with the GS2
            # host so both engines see ONE record and ONE emitter.
            table = self._layer_store(ctx)
            if table is None:
                return UNSET
            from ..gs2_client import layer_image_get
            owner = getattr(ctx, "this_obj", None)
            owner = owner if isinstance(owner, dict) else None
            return layer_image_get(
                table, int(to_num(args[0])) if args else 0, owner)
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
        if name in ("imgwidth", "imgheight", "getimgwidth", "getimgheight"):
            filename = to_str(args[0]).strip('"') if args else ""
            size = None
            if filename and self.rt.image_size_source is not None:
                try:
                    size = self.rt.image_size_source(filename)
                except Exception:
                    size = None
            if not size:
                return 0.0
            return float(size[0] if name in ("imgwidth", "getimgwidth")
                         else size[1])
        if name in ("textheight", "gettextheight"):
            zoom = to_num(args[0]) if args else 1.0
            return 16.0 * (zoom if zoom > 0 else 1.0)
        if name == "degtorad":
            return (to_num(args[0]) if args else 0.0) * math.pi / 180.0
        if name == "makevar":
            dynamic = to_str(args[0]).strip('"') if args else ""
            namespace, dot, key = dynamic.partition(".")
            scope = NAMESPACES.get(namespace) if dot else None
            if scope is None:
                key = dynamic
            value = ctx.vars.get(scope, key)
            return 0.0 if value is UNSET else value
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
        if name in ("testcompu", "testbomb", "testexplo"):
            return self._test_projectile_at(name, args)
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

    def _object_ref(self, args, kind):
        wanted = to_str(args[0]).strip('"').lower() if args else ""
        if not wanted:
            return 0.0
        if kind == "player":
            candidates = []
            if self._player is not None:
                candidates.append((self._player, True))
            candidates.extend(
                (player, False) for player in
                (getattr(self.rt.client, "players", {}) or {}).values()
                if isinstance(player, dict)
            )
            for player, writable in candidates:
                values = (
                    player.get("account", player.get("account_name", ""))
                    if isinstance(player, dict)
                    else getattr(player, "account_name",
                                 getattr(player, "account", "")),
                    player.get("nickname", "") if isinstance(player, dict)
                    else getattr(player, "nickname", ""),
                    player.get("id", "") if isinstance(player, dict)
                    else getattr(player, "id", ""),
                )
                if any(to_str(value).lower() == wanted for value in values):
                    return _GS1ObjectRef(
                        "player", player, writable=writable,
                        label=to_str(values[0]) or wanted)
            return 0.0
        client = self.rt.client
        for npc_id, npc in (getattr(client, "npcs", {}) or {}).items():
            if not isinstance(npc, dict):
                continue
            values = (npc.get("name", ""), npc.get("nickname", ""),
                      npc.get("id", npc_id), npc_id)
            if any(to_str(value).lower() == wanted for value in values):
                return _GS1ObjectRef("npc", npc)
        return 0.0

    def _test_projectile_at(self, name, args):
        if len(args) < 2:
            return -1.0
        x, y = to_num(args[0]), to_num(args[1])
        if name == "testcompu":
            objects = [
                (item_id, item) for item_id, item in
                (getattr(self.rt.client, "baddies", {}) or {}).items()
            ]
        elif name == "testbomb":
            objects = list(enumerate(self._bomb_list()))
        else:
            objects = list(enumerate(self._explo_list()))
        for item_id, item in objects:
            if (abs(to_num(item.get("x", 0)) - x) <= 1.0
                    and abs(to_num(item.get("y", 0)) - y) <= 1.0):
                return float(item_id)
        return -1.0

    @staticmethod
    def _char_rect(x, y):
        """The feet-centred 2x2-tile collision square, in pixels."""
        return to_num(x) * 16 + 8, to_num(y) * 16 + 16, 32, 32

    def _npc_rect(self, npc_id, npc):
        """An NPC's collision rect in pixels for _test_at: its setshape/
        setshape2 box if it set one, else the character square, else — for a
        VISIBLE image NPC — its image footprint, the same geometry that
        blocks and touches (npc_image_rect). A plain image NPC used to have
        no rect at all here, which broke the classic putnpc guard idiom
        live: GTA furnishes interiors with `if (testnpc(x,y)<0) putnpc ...`
        (the guard is the ONLY thing stopping every visit from stacking
        another copy onto the server), and with testnpc blind to the
        already-present furniture our client re-spawned the whole pub each
        entry (live-observed: adventurerpub.nw 34 -> 66 NPCs in two
        visits). The reference hit test that touch and walls share bails on
        invisible NPCs before any geometry (TServerNPC::isOnNPC — see
        npc_handler.update_npcs), hence the visibility gate on this path.

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
        if npc.get("visible", True) is False:
            return None
        rect = self.rt.npc_image_rect(npc)
        if rect is not None:
            rx, ry, rw, rh = rect
            return rx * 16, ry * 16, rw * 16, rh * 16
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

