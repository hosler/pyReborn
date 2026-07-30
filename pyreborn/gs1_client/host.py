from __future__ import annotations

import logging

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

    # -- era with-scope host-object members --------------------------------
    @staticmethod
    def _with_member_get(obj, name, indices):
        """Resolve a (possibly dotted) member path against a with-scoped host
        object; UNSET when any hop is unclaimed. Indices are consumed in path
        order (`particles[0].lifetime` arrives as name "particles.lifetime",
        indices [0] -- same flattening as `npcs[i].save[j]`)."""
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

