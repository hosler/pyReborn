from __future__ import annotations

import logging
import math

from reborn_protocol.gs1.runtime import UNSET, VarStore
from reborn_protocol.gs1.interp import Interpreter
from reborn_protocol.gs1.values import to_num, to_str
from reborn_protocol.gs1.host_shared import host_value

from ..sprites import REBORN_PALETTE, REBORN_PALETTE_ALIASES
from .registry import NPC_ATTR, PLAYER_ATTR



logger = logging.getLogger(__name__)


class _GS1ObjectRef:
    """Live player/NPC handle used as a GS1 with-target."""

    gs1_with_members = True

    _remote_write_logs: set = set()
    _PLAYER_MEMBERS = {
        **{k.removeprefix("player"): v for k, v in PLAYER_ATTR.items()},
        **PLAYER_ATTR,
        "x": "x", "y": "y", "dir": "direction", "id": "id",
        "account": "account", "nickname": "nickname", "chat": "chat",
    }

    def __init__(self, kind, target, *, writable=True, label=""):
        self.kind = kind
        self.target = target
        self.writable = writable
        self.label = label

    def get(self, name):
        table = NPC_ATTR if self.kind == "npc" else self._PLAYER_MEMBERS
        if name not in table:
            return UNSET
        attr = table[name]
        if isinstance(self.target, dict):
            return _num_or_str(self.target.get(attr, 0))
        return _num_or_str(getattr(self.target, attr, 0))

    def set(self, name, value):
        table = NPC_ATTR if self.kind == "npc" else self._PLAYER_MEMBERS
        if name not in table:
            return False
        if not self.writable:
            log_key = self.label.lower()
            if log_key not in self._remote_write_logs:
                self._remote_write_logs.add(log_key)
                logger.debug("ignored GS1 write to remote player %s", self.label)
            return True
        attr = table[name]
        if isinstance(self.target, dict):
            self.target[attr] = value
        else:
            setattr(self.target, attr, value)
        return True

# Classic baddy ("compus") tables for putcomp/putnewcomp, from GServer-v2:
# names + spider->octopus alias, LevelBaddy.h:26-47 (BaddyType/BaddyNames);
# per-type default image and power (half-hearts), LevelBaddy.cpp:29-40
# (baddyImages/baddyPower). GTA's corpus maps the same names to the same art
# (`putnewcomp graysoldier,x,y,skeleton_baddy.png,...`).
_BADDY_TYPES = {
    "graysoldier": 0, "bluesoldier": 1, "redsoldier": 2, "shootingsoldier": 3,
    "swampsoldier": 4, "frog": 5, "octopus": 6, "goldenwarrior": 7,
    "lizardon": 8, "dragon": 9, "spider": 6,
}
_BADDY_DEFAULT_IMAGE = (
    "baddygray.png", "baddyblue.png", "baddyred.png", "baddyblue.png",
    "baddygray.png", "baddyhare.png", "baddyoctopus.png", "baddygold.png",
    "baddylizardon.png", "baddydragon.png",
)
_BADDY_DEFAULT_POWER = (2, 3, 4, 3, 2, 1, 1, 6, 12, 8)


def _push_dir(target_x, target_y, from_x, from_y):
    """Normalized knockback direction for the hit family: target position
    minus the hit's (fromx, fromy), unit length (GS1Commands.cpp fn_hitnpc/
    fn_hitcompu compute exactly this). (0, 0) when no source was given or the
    hit is dead-centre."""
    if from_x is None or from_y is None:
        return 0.0, 0.0
    dx = float(target_x) - float(from_x)
    dy = float(target_y) - float(from_y)
    length = math.hypot(dx, dy)
    if not length:
        return 0.0, 0.0
    return dx / length, dy / length


# item NAME -> LevelItemType id for lay/lay2 (the parser hands the name
# through as a SpecialLit ITEM string). Same table the wire/renderer use
# (packets.LEVEL_ITEM_NAMES); imported lazily and memoized because packets
# pulls in the whole codec package.
_ITEM_ID_CACHE: dict = {}


def _item_ids() -> dict:
    if not _ITEM_ID_CACHE:
        from ..packets import LEVEL_ITEM_NAMES
        _ITEM_ID_CACHE.update(
            {iname: iid for iid, iname in LEVEL_ITEM_NAMES.items()})
    return _ITEM_ID_CACHE


def _baddy_type_from_name(value) -> int:
    """Baddy name/id -> BaddyType id, the reference resolution order
    (LevelBaddy::getBaddyTypeFromString, LevelBaddy.cpp:44-66): name
    case-insensitively (spider aliased to octopus), then numeric id, else
    graysoldier."""
    name = to_str(value).strip().lower()
    if name in _BADDY_TYPES:
        return _BADDY_TYPES[name]
    try:
        as_id = int(float(name))
    except (TypeError, ValueError):
        return 0
    return as_id if 0 <= as_id <= 9 else 0


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

