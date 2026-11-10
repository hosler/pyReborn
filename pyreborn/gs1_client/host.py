from __future__ import annotations

import logging
import re

from reborn_protocol.coords import local_to_world
from reborn_protocol.gs1.runtime import Host, UNSET
from reborn_protocol.gs1.values import to_num
from reborn_protocol.gs2 import GS2Object

from .objects import _GS1ObjectRef
from .registry import _FALL_THROUGH, _GS1_LAYER_COMMANDS, _GS1_MAIN_COMMANDS, _GS1_NPC_COMMANDS, _GS1_NPC_TAIL_COMMANDS, _GS1_PRE_COMMANDS, _report_gs1_error
from .host_builtins import BuiltinsMixin
from .host_commands_layer import LayerCommandsMixin
from .host_commands_main import MainCommandsMixin
from .host_commands_npc import NpcCommandsMixin
from .host_commands_pre import PreCommandsMixin
from .host_functions import FunctionsMixin



logger = logging.getLogger(__name__)



class GS1ClientHost(
    BuiltinsMixin, PreCommandsMixin, LayerCommandsMixin, NpcCommandsMixin,
    MainCommandsMixin, FunctionsMixin, Host,
):
    """The host connects GS1 to the live pyReborn client.

    The client contains the local player and the NPC dictionary. Visual, audio,
    and world commands fire the runtime's ``on_*`` callbacks. The pygame client
    then renders them. All other commands update the local NPC or player.
    """

    def __init__(self, runtime: "ClientGS1"):
        self.rt = runtime
        # Level-mates' players[] records, built once per script slice (see
        # begin_slice/end_slice). Packets only arrive between frames, so the
        # roster cannot change under a running slice; the local player is
        # rebuilt on every read because a script can write to it mid-slice.
        self._remote_records = None
        self._slice_depth = 0

    @property
    def _slice_active(self):
        return self._slice_depth > 0

    def begin_slice(self):
        """A script slice starts: remote players[] records may be cached.
        Slices nest (callnpc runs another script synchronously) and share
        one cache."""
        if self._slice_depth == 0:
            self._remote_records = None
        self._slice_depth += 1

    def end_slice(self):
        self._slice_depth = max(0, self._slice_depth - 1)
        if self._slice_depth == 0:
            self._remote_records = None

    @staticmethod
    def host_surface():
        """Return names accepted by the real shared GS1 lexer/host wiring."""
        from reborn_protocol.gs1 import COMMANDS, FUNCTIONS
        return frozenset(COMMANDS) | frozenset(FUNCTIONS)

    @property
    def _player(self):
        return getattr(self.rt.client, "player", None) if self.rt.client else None

    # players[i].<member> -> the record keys below (scripting-gs1-variables.md
    # "Players"). Aliases share one stored value.
    _PLAYER_MEMBER_ALIASES = {
        "nick": "nickname", "darts": "arrows", "gralats": "rupees",
        "hp": "hearts", "maxhp": "fullhearts",
    }

    _HEAD_SET = re.compile(r"head0*(\d+)\.(?:png|gif)")

    @classmethod
    def _head_set(cls, image):
        """players[].headset: the N of head<N>.png, else 0."""
        match = cls._HEAD_SET.fullmatch(str(image or "").lower())
        return float(match.group(1)) if match else 0.0

    def _local_player_record(self, cl, p, x, y):
        record = {
            "x": x, "y": y,
            "account": getattr(p, "account", ""),
            "nickname": getattr(p, "nickname", ""),
            "chat": getattr(p, "chat", ""),
        }
        if p is None:
            return record
        record.update({
            "id": float(getattr(p, "id", 0) or 0),
            "hearts": float(getattr(p, "hearts", 0) or 0),
            "fullhearts": float(getattr(p, "max_hearts", 0) or 0),
            "ap": float(getattr(p, "ap", 0) or 0),
            "mp": float(getattr(p, "mp", 0) or 0),
            "dir": float(int(getattr(p, "direction", 2) or 0) & 3),
            "rupees": float(getattr(p, "rupees", 0) or 0),
            "arrows": float(getattr(p, "arrows", 0) or 0),
            "bombs": float(getattr(p, "bombs", 0) or 0),
            "bombpower": float(getattr(p, "bomb_power", 0) or 0),
            "glovepower": float(getattr(p, "glove_power", 0) or 0),
            "swordpower": float(getattr(p, "sword_power", 0) or 0),
            "shieldpower": float(getattr(p, "shield_power", 0) or 0),
            "sprite": float(getattr(p, "sprite", 0) or 0),
            "headset": self._head_set(getattr(p, "head_image", "")),
            "carrysprite": float(getattr(p, "carry_sprite", -1)),
            "kills": float(getattr(p, "kills", 0) or 0),
            "deaths": float(getattr(p, "deaths", 0) or 0),
            "rating": float(getattr(p, "rating", 0) or 0),
            "ratingd": float(getattr(p, "rating_deviation", 0) or 0),
            "attachid": float(getattr(p, "attached_npc_id", 0) or 0),
            "attachtype": float(getattr(p, "attached_npc_type", 0) or 0),
            "z": float(getattr(p, "z", 0) or 0),
        })
        return record

    @classmethod
    def _remote_player_record(cls, op, x, y):
        """A level-mate's record from what PLO_OTHERPLPROPS carries. Members
        the wire never sends for other players (hearts, rupees, bombs, ...)
        read 0, like an unset property."""
        def num(key, default=0):
            try:
                return float(op.get(key, default) or 0)
            except (TypeError, ValueError):
                return 0.0
        direction = op.get("direction", op.get("dir", 2))
        return {
            "x": x, "y": y,
            "account": op.get("account", ""),
            "nickname": op.get("nickname", op.get("nick", "")),
            "chat": op.get("chat", ""),
            "id": num("id"),
            "hearts": num("hearts"), "fullhearts": num("max_hearts"),
            "ap": num("ap"), "mp": num("mp"),
            "dir": float(int(direction or 0) & 3),
            "rupees": num("rupees"), "arrows": num("arrows"),
            "bombs": num("bombs"), "bombpower": num("bomb_power"),
            "glovepower": num("glove_power"),
            "swordpower": num("sword_power"),
            "shieldpower": num("shield_power"),
            "sprite": num("sprite"),
            "headset": cls._head_set(op.get("head_image", "")),
            "carrysprite": num("carry_sprite", -1),
            "kills": num("kills"), "deaths": num("deaths"),
            "rating": num("rating"), "ratingd": num("rating_deviation"),
            "attachid": num("attach_npc"),
            "z": num("z"),
        }

    def _player_list(self):
        """Return all players that the client knows.

        Index 0 is the local player. The other players follow it. NPC scripts
        use this list for proximity checks and the room-join state machine.
        Examples are players[i].x, #a(i), and playerscount. Each record holds
        the members scripting-gs1-variables.md lists for `players[]` (x, y,
        id, hearts, fullhearts, ap, mp, dir, rupees, arrows, bombs,
        glovepower, swordpower, shieldpower, ...; aliases in
        _PLAYER_MEMBER_ALIASES). The positions are world coordinates on a gmap.
        """
        cl = self.rt.client
        if cl is None:
            return []
        p = getattr(cl, "player", None)
        out = [self._local_player_record(
            cl, p, float(getattr(cl, "x", 0)), float(getattr(cl, "y", 0)))]
        remotes = self._remote_records if self._slice_active else None
        if remotes is None:
            remotes = self._build_remote_records(cl)
            if self._slice_active:
                self._remote_records = remotes
        out.extend(remotes)
        return out

    def _build_remote_records(self, cl):
        # World frame, like playerx/playery in host_builtins.py::_pb_position.
        # Reference: GServer-v2/server/include/object/Character.h:getTilePosition (map*64 + local).
        segments = {name: cell for cell, name in (getattr(cl, "gmap_grid", {}) or {}).items()}
        current_segment = segments.get(getattr(cl, "_current_level_name", ""), (0, 0))
        out = []
        for pid, op in getattr(cl, "players", {}).items():
            if isinstance(op, dict):
                x, y = local_to_world(float(op.get("x", 0) or 0),
                                      float(op.get("y", 0) or 0),
                                      *segments.get(op.get("level"), current_segment))
                if getattr(cl, "is_gmap", False):
                    if op.get("world_x") is not None:
                        x = float(op["world_x"])
                    if op.get("world_y") is not None:
                        y = float(op["world_y"])
                record = self._remote_player_record(op, x, y)
                if not record["id"]:
                    record["id"] = float(pid)
                out.append(record)
        return out

    # -- era with-scope host-object members --------------------------------
    @staticmethod
    def _with_member_get(obj, name, indices):
        """Resolve a member path against a with-scoped host object.

        The member path can contain dots. Return UNSET if an object does not
        claim a path part. The function consumes indices in path order.
        `particles[0].lifetime` arrives as name "particles.lifetime" and indices
        [0]. The function uses the same flattening for `npcs[i].save[j]`.
        """
        if isinstance(obj, _GS1ObjectRef):
            return obj.get(name)
        cur = obj
        idx = list(indices or [])
        for part in name.split("."):
            if not isinstance(cur, GS2Object):
                return UNSET
            cur = cur.get(part)
            if cur is None:
                return UNSET
            while idx and isinstance(cur, list):
                i = int(to_num(idx.pop(0)))
                if not 0 <= i < len(cur):
                    return UNSET
                cur = cur[i]
        return cur

    @classmethod
    def _with_member_set(cls, obj, name, value, indices) -> bool:
        if isinstance(obj, _GS1ObjectRef):
            return obj.set(name, value)
        parts = name.split(".")
        if len(parts) > 1:
            parent = cls._with_member_get(obj, ".".join(parts[:-1]), indices)
            if not isinstance(parent, GS2Object):
                return False
            parent.set(parts[-1], value)
            return True
        # single name: a with-scope write lands on the with target (vivifying
        # an unclaimed member, same as the reference's innermost-with rule)
        obj.set(parts[0], value)
        return True

    # -- built-in attribute access ----------------------------------------
    # -- commands ----------------------------------------------------------
    def call_command(self, name, args, ctx) -> None:
        try:
            self._dispatch(name, args, ctx)
        except Exception as e:
            _report_gs1_error(f"command {name}", e)

    @staticmethod
    def _imgs(npc):
        """Get or create the NPC's showimg layer table (index -> record)."""
        d = npc.get("imgs")
        if d is None:
            d = npc["imgs"] = {}
        return d

    def _layer_store(self, ctx):
        """The showimg/showani layer table for the running script: an NPC keeps
        it on its dict. A weapon (no NPC obj, e.g. ArenaGUI's bombs/vases/
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
        different behavior. Anything no stage claims is silently ignored
        (client visuals we do not render).
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
