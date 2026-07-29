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
import math
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from reborn_protocol.gs1.runtime import UNSET
from reborn_protocol.gs2 import (
    GS2_NULL, GS2VM, GS2Host, GS2Object, NOT_HANDLED,
    casefold as gs2_casefold, to_bool, to_num, to_str,
)
from .gs1_client import (
    PLAYER_ATTR, board_tile_read, board_tile_write, board_world_dims,
)
from .particles import (
    EMITTER_METHOD_NAMES, MODIFIER_METHOD_NAMES, ParticleEmitter,
    ParticleModifier, emitter_for_record,
)

logger = logging.getLogger(__name__)

# Limits for untrusted script writes to each server-scoped cache directory.
SAVE_LINES_MAX_LINES = 4096
SAVE_LINES_MAX_CHARS_PER_LINE = 4096
SAVE_LINES_CACHE_MAX_BYTES = 5 * 1024 * 1024

# Floor for settimer()/this.timeout. The v6 reference has no 0.05s clamp (that
# is the legacy GS1 path, OpenReborn.Common ScriptObj.cs:100). Its GS2 timers
# fire off the fixed-timestep Update (GameEngine.cs:755, TargetElapsedTime =
# 1/120 s at :171), so a self-rearming setTimer(0.01) ticks at frame rate --
# which is what sizes CadavreTest's cog spin and -Test_Movement's walk.
TIMER_RESOLUTION = 1.0 / 120.0
# settimer(v)/this.timeout = v at or below this CANCELS the pending timer —
# the reference setTimeout deactivates for values <= 0.0001
# (TScriptSpace::setTimeout, Preagonal/FourPlay/quattroplay/src/
# TScriptSpace.cpp:121-129). Mirrors gs1_client._TIMEOUT_CANCEL.
_TIMER_CANCEL = 0.0001
TIMER_BACKLOG_CAP = 0.25
PENDING_EVENT_CAP = 16
# Ceiling on scheduleevent() arms in flight across every script (a runaway
# script must not be able to grow the queue without bound).
SCHEDULED_EVENT_CAP = 256

# GS2 GUI-controls layer (showgui/GuiControl -- see gs2_gui.py's module
# docstring for how `new GuiButtonCtrl(...) { onAction = function(){...}; }`
# actually compiles). Lives under game/ (pygame-only, unlike the rest of this
# module) so headless callers -- e.g. game_tester's GameBot, which imports
# ClientGS2 with no pygame installed -- still work; GUI construction/builtins
# just no-op when it's unavailable.
try:
    from .game.gs2_gui import GS2GuiManager, GuiControl, GuiPopUpEditCtrl
except Exception:  # pragma: no cover - pygame not installed (headless use)
    GS2GuiManager = None
    GuiControl = None
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

#: Level tile probes: v6 binds these itself (onwater/onwater2 at FourPlay
#: quattroplay/src/TInitStatics.cpp:4240-4241 -> TServerLevel::isOnWater), but
#: the GS1 host already answers them against the same tile store, so routing
#: them there keeps ONE answer per tile for both engines -- and that store is
#: gmap-aware, which a 0..63 board probe is not. Zelda spells tiletype both
#: ways: bare (weapon-Player_Movement.txt:451) and as a level member (:369),
#: so the obj-method block routes here too.
#:
#: testnpc/testplayer are the same deal one step out: they probe level
#: OBJECTS rather than tiles, GS1ClientHost._test_at has answered them since
#: the classic-Bomber shop fix, and v6 registers them as `level.testnpc`
#: (src/TServerLevelProperties.cpp:263) and the global `testplayer`
#: (src/TInitStatics.cpp:4278, body :3880-3900). They were simply missing
#: from this table, so every GS2 spelling read 0.0 -- i.e. "index 0", a hit
#: on the first NPC in the level, for a probe whose miss value is negative.
_GS1_LEVEL_PROBES = frozenset({
    "onwall", "onwall2", "onwater", "onwater2", "tiletype",
    "testnpc", "testplayer",
})

#: GS1 function names (value-returning) answered by GS1ClientHost.call_function.
_GS1_FUNCTIONS = _GS1_LEVEL_PROBES | frozenset({
    "keydown", "keydown2", "hasweapon",
})

#: The GS1 interpreter's PURE (host-independent) function table, so a name
#: both engines expose resolves to ONE implementation instead of a second
#: copy that can drift. Only explicitly listed names are routed to it.
try:
    from reborn_protocol.gs1.interp import _PURE as _GS1_PURE
except ImportError:  # pragma: no cover - older reborn-protocol
    _GS1_PURE = {}

#: TStringConstants::wordborder -- the character class contains() treats as a
#: word boundary (FourPlay quattroplay/src/TInitStatics.cpp:283, installed at
#: :5085). Verbatim, including the two latin-1 characters.
_WORD_BORDER = frozenset(" .,;:-_><|!\"§$%&/\\()=?`´{[]}+*~#''^")

#: GS1-command argument positions that become DISPLAY TEXT. A number a GS2
#: script passes there is stringified with GS2's rule before the GS1 host
#: sees it -- see ClientGS2._gs1_args.
_GS1_TEXT_ARGS = {
    "showtext": (5,), "showtext2": (6,),
    "say": (0,), "say2": (0,), "message": (0,),
}

#: player.<member> -> pyReborn Player attribute (reuses the GS1 table, which
#: is keyed "player<name>"; GS2 accesses the same fields as object members)
_PLAYER_MEMBER_ATTR = {k[len("player"):]: v for k, v in PLAYER_ATTR.items()}
_PLAYER_MEMBER_ATTR.update({
    "id": "id",
    "nick": "nickname",
    # Player stores the current gani in `animation`; "gani" is the key the
    # remote-player RECORDS use, not an attribute on Player. This entry is
    # reached on WRITES only (get() answers ani/gani as a handle above), and
    # pointing it at a non-existent attribute made `player.ani = "walk"` land
    # somewhere nothing reads.
    "ani": "animation",
    # v6 HUD scripts read these members directly; none has a GS1
    # "player<name>" builtin. "darts" is the classic name for arrows.
    "mp": "mp", "magicpoints": "mp", "ap": "ap", "darts": "arrows",
    "swordimg": "sword_image", "shieldimg": "shield_image",
    "headimg": "head_image", "bodyimg": "body_image",
    "horseimg": "horse_image",
    # `hp`/`maxhp` are the v6 spellings of hearts/fullhearts; maxhp reuses
    # fullhearts' getter outright (FourPlay quattroplay/src/
    # TServerPlayerProperties.cpp:585) and is READ-ONLY there.
    "hp": "hearts", "maxhp": "max_hearts",
    # The RAW 0/1/2 field, not GS1's playerglovepower (which reports 1/2/3 --
    # see gs1_client._pb_glovepower): the reference's getter hands back
    # getGlovePower() unbiased (TServerPlayerProperties.cpp:118).
    "glovepower": "glove_power",
})

#: player members READ-ONLY in the reference, i.e. registered with a nullptr
#: setter. `nick` is the interesting one: TPlayerProperties's own entry
#: (quattroplay/src/TPlayerProperties.cpp:252-258) has a nullptr setter and
#: REPLACES TServerPlayer's read/write entry (:609) when the child table is
#: compiled (src/TProperties.cpp:117-129), so writing player.nick on the LOCAL
#: player is a no-op. Remote players keep the writable slot, which is why this
#: gate lives here and not on the script_player_object entries.
_PLAYER_READONLY = frozenset({"nick", "maxhp", "levelname"})

#: Members the reference registers with returnType 's' that pyReborn has no
#: source for. They must answer a STRING anyway: a name that resolves to
#: nothing becomes Number 0.0 (quattroplay/src/TScriptStackEntry.cpp:228-229)
#: and a Number-vs-String compare runs strtofloat() over the string
#: (src/TScriptMachine.cpp:1463), which is 0.0 for any non-numeric literal --
#: so an unanswered name equals EVERY word a script compares it against.
#: "" goes through compareIgnoreCase instead and behaves.
_PLAYER_EMPTY_STRINGS = frozenset({
    # TGraalVar's own `name`, inherited by every object. TServerPlayer passes
    # a null name to the TGraalVar base (src/TServerPlayer.cpp:95), so "" is
    # the reference's answer here too, not a placeholder for one.
    "name",
    "language", "languagedomain",   # TServerPlayerProperties.cpp:555, :564
    "chatoffset",                   # :339
    "alliedguilds", "letters",      # TPlayerProperties.cpp:54, :234
    "aniparams", "rotationcenter",  # TGaniObjectProperties.cpp:55, :208
})

#: The same rule for OTHER players (findplayer / findnearestplayers entries,
#: whose chain is TServerPlayer -> TGaniObject -> TGraalVar). `platform` and
#: `communityname` are "" here rather than what _PlayerObject answers: we know
#: our own host OS, never a remote player's. `message` (the waiting-PM text,
#: fed by pm_received / cleared by GuiPMCtrl.showPM) and `messagebubble` are
#: seeded once and then owned by the PM machinery / scripts.
_REMOTE_PLAYER_EMPTY_STRINGS = frozenset(
    _PLAYER_EMPTY_STRINGS | {"platform", "communityname", "horseimg",
                             "message", "messagebubble"})

#: Script-WRITABLE roster members seeded 0.0 once and never clobbered by a
#: refresh: the -Playerlist weapon stamps buddy/ignore state and the local
#: status-icon choice straight onto player objects (`person.isbuddy = true`,
#: `player.playerlisticon = rowid`), which only works on persistent wrappers.
_REMOTE_PLAYER_STICKY_NUMBERS = ("isbuddy", "isignored", "playerlisticon")

#: Default staff-guild list (FourPlay quattroplay/src/TPlayerList.cpp:25),
#: overridable by the server via PLO_STAFFGUILDS (client.staff_guilds). The
#: match rule is isadminguild's: append ")" to the player's nick-derived
#: guild and prefix-match each entry (TPlayerList.cpp:6-18) -- so "Coder)"
#: matches exactly the guild "Coder" while a bare "RC" matches any guild
#: starting with RC.
_DEFAULT_STAFF_GUILDS = ("Coder)", "RC", "LAT)", "Admin)", "GP",
                         "Senior GP", "FAQ")


def _is_admin_guild(guild: str, staff_guilds) -> bool:
    if not guild:
        return False
    probe = (to_str(guild) + ")").lower()
    if staff_guilds is None:
        # PLO_STAFFGUILDS never arrived this session: the client-baked
        # defaults apply (the reference seeds them at startup,
        # initStaffGuildList).
        entries = _DEFAULT_STAFF_GUILDS
    else:
        # A server-SENT list is authoritative even when empty: the oracle
        # answers false for every guild then (TPlayerList.cpp:11-12) --
        # it never falls back to the defaults. Blank entries are dropped
        # rather than prefix-matching everything.
        entries = [e for e in staff_guilds if to_str(e)]
    # NB: the case-insensitive match is an unverified inference (TString::
    # starts' case behavior is not established from the decompile).
    return any(probe.startswith(to_str(entry).lower()) for entry in entries)

#: TGaniObject's per-object render transform (TGaniObjectProperties.cpp:199,
#: :217, :226, :235, :244, :253, :262, :271, :280, :289), registered on
#: players AND NPCs. Every getter there is a raw address, so the oracle backs
#: only the names, types and read/write flags -- the values below are the
#: identity transform our own showimg records already use, chosen so a script
#: that reads a slot it never wrote gets a no-op rather than a black,
#: zero-scaled object. Writes are remembered (the renderer does not consume
#: them yet; that lives outside this module).
_GANI_TRANSFORM_DEFAULTS = {
    "rotation": 0.0, "zoom": 1.0, "stretchx": 1.0, "stretchy": 1.0,
    "red": 1.0, "green": 1.0, "blue": 1.0, "alpha": 1.0,
    "mode": 0.0, "useowncenter": 0.0,
}

#: player.zoomfactor's clamp: value <= 16.0 ? max(value, 1.0) : 16.0
#: (quattroplay/src/TPlayerProperties.cpp:44-50, constants FLOAT_0040231c =
#: 16.0 and FLOAT_004022c0 = 1.0 at src/TInitStatics.cpp:1221,1226).
ZOOM_FACTOR_MIN = 1.0
ZOOM_FACTOR_MAX = 16.0

#: player.freezetime is carried as a tick counter decremented once per player
#: update; the property converts with 20 ticks per second and the setter caps
#: at 600 ticks == 30 s (quattroplay/src/TPlayerProperties.cpp:11-37, with
#: DOUBLE_004023f8 = 20.0 and DOUBLE_00402518 = 30.0 at
#: src/TInitStatics.cpp:1264,1254). Not frozen reads -1.0, not 0.
FREEZE_TICKS_PER_SECOND = 20.0
FREEZE_MAX_TICKS = 600


def _csv_flatten(args) -> List[str]:
    """Trigger params as wire CSV fields: a GS2 {array} argument contributes
    one field per element (the client flattens arrays into the action string)."""
    out: List[str] = []
    for a in args:
        if isinstance(a, (list, tuple)):
            values = (to_str(x) for x in a)
        else:
            values = (to_str(a),)
        for value in values:
            if any(char in value for char in '",\\'):
                value = '"' + ''.join(
                    char * 2 if char in '"\\' else char for char in value
                ) + '"'
            out.append(value)
    return out


def _csv_unflatten(value: str) -> List[str]:
    """Decode trigger CSV, falling back to the legacy raw split if malformed."""
    fields, field = [], []
    pos, quoted = 0, False
    try:
        while pos < len(value):
            char = value[pos]
            if not field and char == '"':
                quoted = True
                pos += 1
                continue
            if quoted:
                if char in '"\\':
                    if pos + 1 < len(value) and value[pos + 1] == char:
                        field.append(char)
                        pos += 2
                        continue
                    if char == '"' and (pos + 1 == len(value)
                                       or value[pos + 1] == ','):
                        quoted = False
                        pos += 1
                        continue
                    raise ValueError
                field.append(char)
            elif char == ',':
                fields.append(''.join(field))
                field = []
            elif char == '"':
                raise ValueError
            else:
                field.append(char)
            pos += 1
        if quoted:
            raise ValueError
        fields.append(''.join(field))
        return fields
    except ValueError:
        return value.split(",")


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


class _CanvasObject(_EngineObject):
    """GUIContainer / GraalControl(3D) stand-ins. Unlike the C#-client
    engine objects, an unknown METHOD on these must FALL THROUGH rather
    than answer inertly: whole construction runs execute inside
    `with (GUIContainer) {...}`, where every bare call resolves through
    the with-stack -- the inert catch-all was swallowing plain builtins
    (the F2 log window's tab labels called uppercase() there and got 0.0,
    rendering as "0ame")."""


def _engine_object(rt2: "ClientGS2", key: str,
                   cls: type = _EngineObject) -> _EngineObject:
    """Session-persistent stand-in registry: repeated Find()/findanyobjectbytype
    calls for the same name/type must return the SAME object so member writes
    persist across scripts (the -System camera setup relies on identity)."""
    objs = getattr(rt2, "_engine_objects", None)
    if objs is None:
        objs = rt2._engine_objects = {}
    obj = objs.get(key)
    if obj is None:
        obj = objs[key] = cls(name=key)
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

    `client`, `clientr` and `serverr` are ALSO the executing player:
    resolveObjectMember binds all three to `executingplayer` (FourPlay
    quattroplay/src/TScriptMachine.cpp:5123-5130), so `client.nick`,
    `clientr.x` and `serverr.account` are player-property reads, not flags.
    A `player` handed to __init__ answers those once the flag store has
    said it does not have the name. Only READS fall through: a write here
    stays a flag write, because these stores are the wire flag namespace
    and live content spells `clientr.x = ...` meaning a flag.
    """

    __slots__ = ("_scope", "_prefix", "_local_writes", "_player")

    def __init__(self, name: str, scope: dict, prefix: str = "",
                 local_writes: bool = False,
                 player: Optional[GS2Object] = None):
        super().__init__(name=name)
        self._scope = scope
        self._prefix = prefix
        self._local_writes = local_writes
        self._player = player

    def _key(self, key: str) -> str:
        return self._prefix + key if self._prefix else key

    def get(self, key: str) -> Any:
        k = self._key(key)
        if k in self._scope:
            return self._scope[k]
        lower = k.lower()
        if lower in self._scope:
            return self._scope[lower]
        if self._prefix:
            if key in self._scope:
                return self._scope[key]
            if key.lower() in self._scope:
                return self._scope[key.lower()]
        if self._player is not None:
            value = self._player.get(key)
            if value is not None:
                return value
        return ""

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
        # bare local inside `with(server){...}` to a networked flag. The
        # player fallback in get() is deliberately NOT reported here for the
        # same reason: `with(client){ x = 1; }` must not become a teleport.
        k = self._key(key)
        return (k in self._scope or k.lower() in self._scope
                or (bool(self._prefix)
                    and (key in self._scope or key.lower() in self._scope)))


class _NameObject(GS2Object):
    """A handle scripts read BOTH as a string and through `.name`.

    The engine hands back an object where a naive port hands back a string:
    Zelda's CheckHurt gates on `i.ani.name == "zlttp_sword"` while other
    content compares `player.ani` straight against a string. Both work here
    -- gs2_compare's object/string rule compares the object's .name, and
    to_str() falls through to __str__."""

    __slots__ = ("_text",)

    def __init__(self, text: str):
        super().__init__(name=text)
        self._text = text
        self.set("name", text)

    def __str__(self):
        return self._text


#: Number of gani attributes a player carries (#P1..#P30 on the wire).
PLAYER_ATTR_COUNT = 30

#: What `player.platform` / getplatform() report. The reference client bakes
#: one token per build (TIdentification::platformname); we report the real
#: host OS in the same vocabulary the corpus branches on -- and never a token
#: that would impersonate a client we are not.
_PLATFORM_NAMES = {"win32": "win", "cygwin": "win", "darwin": "mac"}
PLATFORM_NAME = _PLATFORM_NAMES.get(sys.platform, "linux")


def _guild_from_nick(nick: Any) -> str:
    """The guild tag inside a nickname, "" when there is none.

    Reference: TServerPlayer::setNick (FourPlay quattroplay/src/
    TServerPlayer.cpp:300-340) -- find the first '(', then the next ')'
    after it, and keep what is between them."""
    text = to_str(nick)
    open_at = text.find("(")
    if open_at < 0:
        return ""
    close_at = text.find(")", open_at + 1)
    return text[open_at + 1:close_at] if close_at >= 0 else ""


class _PlayerAttrObject(GS2Object):
    """`player.attr[i]` / `pl.attr[i]`: the gani-attribute slots.

    ONE-BASED, with a permanently empty cell 0. The reference builds the
    array that way explicitly -- FourPlay quattroplay/src/TGaniObject.cpp:
    332-344 adds a plain empty TGraalVar first and then TGaniParam(this, i)
    for i = 1..30 -- which is why Zelda's carry code writes
    `(pl.attr[0] != null ? pl.attr[0] : 0)`: attr[0] is ALWAYS null, attr[1]
    is gattrib 1. Slot i is the same value the GS1 engine reaches as #P<i>.

    A remote player's slots are a read-only view of that player's record
    (the wire props parse_other_player stored). The local player's slots
    read and write the shared GS1 store and sync to the server exactly the
    way GS1's `setplayerprop #P<i>` does -- the same single writer, so the
    two engines can't disagree about what we are carrying."""

    __slots__ = ("_rt2", "_player_id")

    def __init__(self, rt2: "ClientGS2", player_id=None):
        super().__init__(name="player.attr")
        self._rt2 = rt2
        #: None == the local player
        self._player_id = player_id

    @staticmethod
    def _slot(key: str) -> Optional[int]:
        try:
            i = int(to_num(key))
        except (TypeError, ValueError):
            return None
        return i if 1 <= i <= PLAYER_ATTR_COUNT else None

    def _record(self) -> Optional[dict]:
        client = self._rt2.client
        if client is None or self._player_id is None:
            return None
        record = (getattr(client, "players", {}) or {}).get(self._player_id)
        return record if isinstance(record, dict) else None

    def get(self, key: str) -> Any:
        index = self._slot(key)
        if index is None:
            return super().get(key)
        if self._player_id is not None:
            record = self._record()
            return to_str(record.get(f"gattrib{index}", "")) if record else ""
        gs1 = self._rt2.gs1
        if gs1 is not None:
            return to_str(gs1._player_props.get(f"P{index}", ""))
        player = getattr(self._rt2.client, "player", None)
        return to_str((getattr(player, "gattribs", None) or {}).get(index, ""))

    def set(self, key: str, value: Any) -> None:
        index = self._slot(key)
        if index is None:
            super().set(key, value)
            return
        text = to_str(value)
        if self._player_id is not None:
            # Another player's attributes are server-owned; keep the local
            # copy consistent for the rest of the frame, send nothing.
            record = self._record()
            if record is not None:
                record[f"gattrib{index}"] = text
            return
        gs1 = self._rt2.gs1
        if gs1 is not None:
            gs1._player_props[f"P{index}"] = text
        client = self._rt2.client
        if client is not None:
            try:
                client.set_gattrib(index, text)
            except Exception:
                pass

    def has(self, key: str) -> bool:
        return self._slot(key) is not None or super().has(key)


class _PlayerColorsObject(GS2Object):
    """`player.colors[i]` / `pl.colors[i]`: the five body-colour slots
    (FourPlay TGaniObject.cpp:2717 iterates color0..color4). Zelda's lift
    code packs a carried player's appearance as
    `pl.headimg @ ":" @ ... @ pl.colors[0] @ ... @ pl.colors[4]`, so these
    have to answer off a REMOTE player's record too."""

    __slots__ = ("_rt2", "_player_id")

    #: PLPROP_COLORS carries 8 entries on v6 clients but only the first five
    #: are the gani colour slots the script surface exposes.
    COLOR_COUNT = 5

    def __init__(self, rt2: "ClientGS2", player_id=None):
        super().__init__(name="player.colors")
        self._rt2 = rt2
        self._player_id = player_id

    @classmethod
    def _slot(cls, key: str) -> Optional[int]:
        try:
            i = int(to_num(key))
        except (TypeError, ValueError):
            return None
        return i if 0 <= i < cls.COLOR_COUNT else None

    def _colors(self) -> list:
        client = self._rt2.client
        if client is None:
            return []
        if self._player_id is None:
            return list(getattr(getattr(client, "player", None), "colors", []) or [])
        record = (getattr(client, "players", {}) or {}).get(self._player_id)
        if isinstance(record, dict):
            return list(record.get("colors", []) or [])
        return []

    def get(self, key: str) -> Any:
        index = self._slot(key)
        if index is None:
            return super().get(key)
        colors = self._colors()
        return float(colors[index]) if index < len(colors) else 0.0

    def has(self, key: str) -> bool:
        return self._slot(key) is not None or super().has(key)


class _PlayerObject(GS2Object):
    """`player.` bridged onto the live pyReborn client/player."""

    __slots__ = ("_rt2", "_attr", "_colors")

    def __init__(self, rt2: "ClientGS2"):
        super().__init__(name="player")
        self._rt2 = rt2
        self._attr = None
        self._colors = None

    def _player(self):
        cl = self._rt2.client
        return getattr(cl, "player", None) if cl else None

    def get(self, key: str) -> Any:
        key = key.lower()
        cl = self._rt2.client
        if key == "attr":
            if self._attr is None:
                self._attr = _PlayerAttrObject(self._rt2)
            return self._attr
        if key in ("colors", "color"):
            if self._colors is None:
                self._colors = _PlayerColorsObject(self._rt2)
            return self._colors
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
        # -- STRING-VALUED identity properties ---------------------------------
        # These must answer a STRING even with nothing to say: an unanswered member
        # reads None, and None == "<any non-numeric literal>" is TRUE (both coerce to
        # 0), so every content comparison fires. Live: 48 player.platform ==
        # "linuxstream" tests per 25s Login session hid controls at
        # weapon-Rescripted_Serverlist.txt:336/:2247 and took the mobile branch at
        # :441. Corpus-swept members: platform, account, chat, level, communityname,
        # guild, ani.
        if key == "platform":
            # The reference reports its BUILD's platform name
            # (TServerPlayerProperties.cpp:627 -> TPlayer::platform, set from
            # TIdentification::platformname, TPlayer.cpp:663). We report our
            # real host OS in the same vocabulary content uses -- and
            # deliberately never one of the tokens that would impersonate a
            # client we are not ("linuxstream" is the streamed Linux client,
            # "android"/"iphone"/"bada" the handsets).
            return PLATFORM_NAME
        if key == "communityname":
            # Read-only in the reference too
            # (TServerPlayerProperties.cpp:330, no writer). We hold no
            # platform community account, and "" is exactly what the
            # serverlist's profile pane tests for before offering its
            # "Choose one" link.
            return ""
        p = self._player()
        if key == "guild":
            # Derived from the nick, not carried separately: the reference's
            # TServerPlayer::setNick (TServerPlayer.cpp:300-340) takes the
            # text between the first '(' and the next ')' and stores it as
            # `guild` (empty when the nick has no parentheses).
            return _guild_from_nick(getattr(p, "nickname", "") if p else "")
        if p is not None:
            if key in ("ani", "gani"):
                # The animation is a HANDLE, not a string: Zelda's CheckHurt
                # reads `i.ani.name` off every player findnearestplayers()
                # hands it (weapon-Player_Movement.txt:734). _NameObject
                # keeps the plain-string comparisons working too.
                #
                # The LOCAL player keeps it in Player.animation; only the
                # remote-player RECORDS (packets.parse_other_player) use the
                # key "gani". Reading `p.gani` here therefore always found
                # nothing, so player.ani was permanently "" and every
                # `player.ani == "idle"` / "walk" / "sword" branch in content
                # was dead. Both spellings are accepted so a caller that does
                # stamp `gani` still wins.
                ani = getattr(p, "gani", None) or getattr(p, "animation", "")
                return _NameObject(to_str(ani or ""))
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
                return _NameObject(to_str(lvl))
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
            if key == "weapons":
                return self._rt2.weapon_list_objects()
            if key == "levelname":
                # The OFFICIAL spelling of the current level
                # (TServerPlayerProperties.cpp:573, getter :181). `level`
                # just above is our own extension -- no player class in the
                # reference registers it (the reference puts `level` on
                # TLevelObject, src/TLevelObjectProperties.cpp:6) -- but it
                # fixed a real bug and stays; content written against the
                # reference spells levelname and used to read 0.0.
                return to_str(self.get("level"))
            if key in ("hurt", "hurted"):
                # b RO (TPlayerProperties.cpp:144, :171; raw-address bodies).
                # Player.hurt_timeout is when the hurt animation ends, which
                # is the only "recently hit" state this client keeps.
                return 1.0 if to_num(getattr(p, "hurt_timeout", 0.0)) > \
                    time.time() else 0.0
            if key in ("hurtdx", "hurtdy", "hurtpower"):
                # d RO (:153, :162, :180). PLO_HURTPLAYER carries these but
                # nothing retains them past the handler, so 0.0 -- which is
                # what a numeric-typed unanswered name reads as anyway, so
                # this costs nothing and is listed only to be explicit.
                return 0.0
            if key in ("swimming", "onhorse", "online", "freezetime"):
                return self._gs1_player_builtin("player" + key)
        if key == "zoomfactor":
            game = getattr(self._rt2, "game_shell", None)
            camera = getattr(game, "camera", None)
            if camera is not None:
                return float(camera.zoom)
            stored = super().get(key)
            return ZOOM_FACTOR_MIN if stored is None else to_num(stored)
        if key in ("defaultwalkspeed", "diagonalwalkspeed"):
            # d RW (TPlayerProperties.cpp:81, :90), raw-address bodies -- the
            # reference's UNIT was not recovered, so a script's write is
            # remembered but deliberately not fed back into movement; the
            # read reports our own walk speed in tiles/second.
            stored = super().get(key)
            if stored is not None:
                return to_num(stored)
            game = getattr(self._rt2, "game_shell", None)
            return float(getattr(game, "walk_speed", 0.0) or 0.0)
        value = super().get(key)
        if value is None:
            if key in _PLAYER_EMPTY_STRINGS:
                return ""
            if key in _GANI_TRANSFORM_DEFAULTS:
                return _GANI_TRANSFORM_DEFAULTS[key]
        return value

    def _gs1_player_builtin(self, name: str) -> Any:
        """One of the state flags both engines expose, answered by the GS1
        host so the two never disagree (playerswimming / playeronhorse /
        playeronline / playerfreezetime)."""
        gs1 = self._rt2.gs1
        if gs1 is None:
            return 0.0
        value = gs1._host.get_builtin(name, [], self._rt2._gs1_ctx(None))
        return 0.0 if value is UNSET else value

    def _set_freezetime(self, seconds: float) -> None:
        """player.freezetime = N, with the reference's quantisation.

        propfun_player_freezetime_w (quattroplay/src/TPlayerProperties.cpp:
        18-37): a negative value freezes for 0 ticks, anything past 30 s
        saturates at the 600-tick ceiling, and everything else is
        `int(seconds * 20 + 1e-4)` ticks -- so 0.03 s rounds DOWN to nothing
        while 0.05 s is exactly one tick. It then clears the action mode; the
        input lock our freezeplayer handler installs (game/setup.py
        on_freezeplayer) is this client's equivalent, so routing through the
        GS1 command keeps one writer for both engines."""
        if seconds < 0.0:
            ticks = 0
        elif seconds <= FREEZE_MAX_TICKS / FREEZE_TICKS_PER_SECOND:
            ticks = int(seconds * FREEZE_TICKS_PER_SECOND + 0.0001)
        else:
            ticks = FREEZE_MAX_TICKS
        self._rt2._gs1_command("freezeplayer",
                               [ticks / FREEZE_TICKS_PER_SECOND], None)

    def set(self, key: str, value: Any) -> None:
        key = key.lower()
        p = self._player()
        if key in _PLAYER_READONLY:
            return
        if key == "freezetime":
            self._set_freezetime(to_num(value))
            return
        if key == "zoomfactor":
            zoom = to_num(value)
            zoom = ZOOM_FACTOR_MAX if zoom > ZOOM_FACTOR_MAX else max(
                zoom, ZOOM_FACTOR_MIN)
            game = getattr(self._rt2, "game_shell", None)
            camera = getattr(game, "camera", None)
            if camera is not None:
                camera.zoom = zoom
            super().set(key, zoom)
            return
        if key == "glovepower" and p is not None:
            # The reference's setter floors at 0 and nothing else
            # (TServerPlayerProperties.cpp:119-123).
            setattr(p, "glove_power", max(0, int(to_num(value))))
            return
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
            # so this.timeout = 0.01 loops tick at frame rate too.
            # `timeout = 0` (or anything <= 0.0001) CANCELS the pending
            # timer instead of arming an immediate fire — the reference
            # engine's setTimeout deactivates it (TScriptSpace::setTimeout,
            # Preagonal/FourPlay/quattroplay/src/TScriptSpace.cpp:121-129);
            # storing 0.0 here re-fired onTimeout next frame forever.
            v = to_num(value)
            if v <= _TIMER_CANCEL:
                self._rt2._timeouts.pop(self._vm_key, None)
                return
            self._rt2._timeouts[self._vm_key] = max(v, TIMER_RESOLUTION)
            return
        super().set(key, value)

    def get(self, key: str) -> Any:
        if key.lower() == "timeout":
            return self._rt2._timeouts.get(self._vm_key, 0.0)
        v = super().get(key)
        if v is None:
            # A script's `this` doubles as its PUBLIC INTERFACE: Login's
            # -ReShared does `Gs2Utils = this;` in onCreated, and every
            # other Login weapon then calls Gs2Utils.replaceAll(...) /
            # .destroyObject(...) across VM boundaries. Those reads land
            # here, on the foreign script's this-object, not on the reading
            # VM's own `this` (which the shared VM resolves itself), so the
            # public-function lookup has to happen here.
            # GS2VM.script_function recurses into joined classes, so a
            # class's public function resolves too.
            kind, key_ = self._vm_key
            vm = self._rt2.vms.get(kind, {}).get(key_)
            if vm is not None:
                fn = vm.script_function(key)
                if fn is not None:
                    return fn
            if key.lower() == "name":
                # TGraalVar's `name` (quattroplay/src/TGraalVarProperties.cpp:
                # 627) is on EVERY object and is string-typed, so leaving it
                # unanswered makes `this.name == "<anything>"` true -- see
                # _PLAYER_EMPTY_STRINGS for why. The reference passes no name
                # to the base for a script object, so "" is its answer too.
                return ""
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
    # Verified alias pairs: identical getter AND setter pointers in the same
    # table, so each is one slot under two names -- head/headimg
    # (quattroplay/src/TGaniObjectProperties.cpp:154 and :163), body/bodyimg
    # (:109, :118), shield/shieldimg and sword/swordimg
    # (src/TPlayerProperties.cpp:297/:306 and :333/:342). So `shield` on an
    # NPC is the shield IMAGE, never the shield power.
    "head": "head_image", "body": "body_image",
    "shield": "shield_image", "sword": "sword_image",
}

#: string-typed members an NPC `this` inherits from TServerPlayer that a
#: client-side NPC never has a value for. Answered as "" for the reason in
#: _PLAYER_EMPTY_STRINGS: unanswered would compare equal to every literal.
#: `account` src/TServerPlayerProperties.cpp:267, `communityname` :330,
#: `platform` :627.
_NPC_EMPTY_STRINGS = frozenset({"account", "communityname", "platform"})

#: the string-typed half of _NPC_THIS_ATTR (the rest -- x/y/dir/glovepower --
#: is numeric, where an unanswered read is already the right shape).
_NPC_STRING_ATTRS = frozenset({
    "image", "ani", "nick", "chat", "message", "headimg", "bodyimg",
    "shieldimg", "swordimg", "horseimg", "head", "body", "shield", "sword",
})


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

    def _npc_id(self):
        """The client.npcs key this VM's record lives under — the same id
        render_entities iterates with, so speech-bubble entries keyed on it
        actually reach this NPC's draw."""
        cl = self._rt2.client
        if cl is None:
            return None
        npcs = getattr(cl, "npcs", {})
        key = self._vm_key[1]
        if key in npcs:
            return key
        if isinstance(key, str):
            try:
                ikey = int(key)
            except (TypeError, ValueError):
                return None
            if ikey in npcs:
                return ikey
        return None

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
        if k == "guild":
            # RO, src/TServerPlayerProperties.cpp:384. Derived from the nick
            # exactly as TServerPlayer::setNick derives it -- see
            # _guild_from_nick.
            npc = self._npc()
            return _guild_from_nick((npc or {}).get("nickname", ""))
        if k in _NPC_EMPTY_STRINGS:
            return ""
        # Member storage still wins (bytecode can run before the NPC's props
        # stream, and set() parks writes there), so the string/transform
        # defaults only fill in a slot nobody has written.
        value = super().get(key)
        if value is None:
            if k in _NPC_STRING_ATTRS:
                return ""
            if k in _GANI_TRANSFORM_DEFAULTS:
                return _GANI_TRANSFORM_DEFAULTS[k]
        return value

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
                elif attr == "message":
                    # `this.chat = "Yes?"` is how a GS2 NPC speaks (bomber v6
                    # Isaac 10333, gani sen_grab). Storing it on the dict
                    # alone is silent — the renderer's bubble reads
                    # npc_chat_texts (render_entities._render_npc), fed for
                    # GS1 by the say/message command via rt.on_say (setup.py's
                    # on_say). Feed the same store from this write path.
                    # Numbers settle to text with GS2's rule (to_str), the
                    # same as any other GS2 value becoming display text.
                    text = value if isinstance(value, str) else to_str(value)
                    npc[attr] = text
                    say = getattr(self._rt2.gs1, "on_say", None)
                    npc_id = self._npc_id()
                    if say is not None and npc_id is not None:
                        say(npc_id, text)
                else:
                    npc[attr] = value if isinstance(value, str) else to_num(value)
                return
        super().set(key, value)


class _GaniThisObject(_ThisObject):
    """The hidden, per-wearer object used by a scripted animation."""

    __slots__ = ("_wearer_key",)

    def __init__(self, rt2: "ClientGS2", vm_key: tuple, wearer_key: tuple,
                 name: str = "this"):
        super().__init__(rt2, vm_key, name=name)
        self._wearer_key = wearer_key

    def mirror_wearer(self) -> None:
        wearer = self._rt2._gani_wearer_record(self._wearer_key)
        if wearer is None:
            return
        get = wearer.get if isinstance(wearer, dict) else (
            lambda key, default=None: getattr(wearer, key, default))
        x = get("world_x", None)
        y = get("world_y", None)
        super().set("x", get("x", 0.0) if x is None else x)
        super().set("y", get("y", 0.0) if y is None else y)
        super().set("dir", get("direction", get("dir", 0.0)))


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

    #: era new-GS1 with-scope member bridge (see gs1_client.get_builtin)
    gs1_with_members = True

    __slots__ = ("_rec",)

    _NUM_KEYS = frozenset(("x", "y", "zoom", "rotation", "mode"))
    _STR_KEYS = frozenset(("image", "font", "style"))

    #: every string-typed TShowImg property (src/TShowImgProperties.cpp:144,
    #: :171, :198, :207, :216, :225, :234, :270, :360, :387, :477, :531,
    #: :558). A layer property nobody has written must still read as a STRING
    #: -- see _PLAYER_EMPTY_STRINGS for what an unanswered one does.
    _SHOWIMG_STRINGS = frozenset((
        "ani", "image", "font", "shadowoffset", "shadowcolor", "style",
        "text", "code", "position", "rotationcenter", "attachoffset",
        "movementvector", "sound",
    ))

    #: names get() COMPUTES rather than reads out of the record/member dict.
    #: has() must claim the whole readable surface (these + the string/num
    #: property vocabulary + whatever the record holds) because the VM's
    #: with-stack resolution is has()-gated (vm._lookup/_assign_name):
    #: an unclaimed name inside `with (findimg(i)) { ... }` silently reads
    #: None and WRITES to VM globals -- `emitter` was invisible and the
    #: era corpus' `with (findimg(200)) { emitter... }` pattern configured
    #: nothing. Same idiom as the other host bridge objects (_NpcColorsObject
    #: etc.).
    _COMPUTED_KEYS = frozenset(("visible", "layer", "emitter", "textshadow"))

    def __init__(self, index: int, rec: dict):
        super().__init__(name=f"image:{index}")
        self._rec = rec

    def has(self, key: str) -> bool:
        k = key.lower()
        return (k in self._COMPUTED_KEYS or k in self._NUM_KEYS
                or k in self._SHOWIMG_STRINGS or k in self._rec
                or super().has(key))

    def get(self, key: str) -> Any:
        k = key.lower()
        if k == "visible":
            return 1.0 if self._rec.get("visible", True) else 0.0
        if k == "layer":
            return float(self._rec.get("vis", 4))
        if k == "emitter":
            # read-only object prop, lazy-created + identity-stable
            # (TShowImg::getParticleEmitter, quattroplay/src/TShowImg
            # .cpp:180-185)
            return emitter_for_record(self._rec)
        v = self._rec.get(k)
        if v is None:
            v = super().get(k)
        if v is None and k in self._SHOWIMG_STRINGS:
            return ""
        return v

    def set(self, key: str, value: Any) -> None:
        k = key.lower()
        if k == "emitter":
            # nullptr setter in the reference property table
            # (TShowImgProperties.cpp:495-498)
            return
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


def layer_image_get(table: dict, index: int, owner=None):
    """Shared findimg(index) resolver for BOTH engines: the identity-cached
    live _LayerImage over the layer record, CREATING an empty record on a
    miss.  The decompiled NPC binding answers null for an unknown index
    (TShowImgList::getByImgIndex), but live-server particle content
    configures emitters on virgin indices as a matter of course --
    era_partyhouse.nw:495 even does `hideimg(200); with (findimg(200))
    {...}` -- so on the shipping client the pattern must materialize a
    layer; an empty record draws nothing until a script gives it content.
    `owner` (the running NPC's dict, when there is one) is stashed for the
    renderer's attachtoowner anchoring."""
    record = table.get(index)
    if record is None:
        record = table[index] = {}
        if owner is not None:
            record["_owner"] = owner
    obj = record.get("_findimg")
    # identity check: showtext REPLACES the rec dict for an index, so a
    # cached wrapper can point at a dead dict
    if not isinstance(obj, _LayerImage) or obj._rec is not record:
        obj = record["_findimg"] = _LayerImage(index, record)
    return obj


class _LevelObject(GS2Object):
    """`level.` bridged onto the client's current level.

    Its chain is TServerLevel -> TGraalVar: six own properties
    (quattroplay/src/TServerLevelProperties.cpp:60-115) plus TGraalVar's
    eight (src/TGraalVarProperties.cpp:625-698). All fourteen used to read
    0.0, `name` included -- and `level.name == "somelevel.nw"` is a common
    script idiom, so it was true in EVERY level."""

    __slots__ = ("_rt2",)

    def __init__(self, rt2: "ClientGS2"):
        super().__init__(name="level")
        self._rt2 = rt2

    @property
    def name(self) -> str:
        # Shadows GS2Object's `name` slot on purpose: gs2_compare's
        # object-vs-string row reads the object's name field, so a bare
        # `level == "x.nw"` has to see the level filename rather than the
        # literal string "level".
        return self._name()

    @name.setter
    def name(self, value) -> None:
        # no-op for the same reason set("name") is -- see below
        pass

    def _name(self) -> str:
        # TServerLevel hands TFiles::lowerCaseFilename(levelName) to the
        # TGraalVar base (src/TServerLevel.cpp:352-354), so the script-visible
        # name is the LOWER-CASED level filename.
        client = self._rt2.client
        return to_str(getattr(client, "_current_level_name", "") or "").lower()

    def _span(self, segments_attr: str) -> float:
        # 64 for a plain level; on a gmap the MAP's segment count << 6
        # (propfun_serverlevel_width_r / _height_r,
        # src/TServerLevelProperties.cpp:43-53 and :6-16).
        client = self._rt2.client
        segments = int(getattr(client, segments_attr, 0) or 0) if client else 0
        return float(segments << 6) if segments > 0 else 64.0

    def get(self, key: str) -> Any:
        k = key.lower()
        if k == "name":
            return self._name()
        if k == "width":
            return self._span("gmap_width")
        if k == "height":
            return self._span("gmap_height")
        if k == "tilelayercount":
            # TServerLevel's m_tileLayers array size. PLO_BOARDLAYER ids are
            # sparse here, so report the highest occupied one; a level with
            # only the base board has exactly one layer.
            layers = getattr(self._rt2.client, "board_layers", None) or {}
            stored = super().get(k)
            if stored is not None:
                return to_num(stored)
            return float(max([0] + [int(i) for i in layers]) + 1)
        if k in ("joinedclasses", "scripterrors"):
            # TGraalVar object-typed lists (:654, :672). Nothing joins or
            # errors on the level object here; an empty array is what a
            # script iterating one expects.
            return []
        value = super().get(key)
        if value is None:
            # The remaining TGraalVar entries -- initialized (:636),
            # ispaused (:645), maxlooplimit (:663),
            # scriptlogmissingfunctions (:681), timeout (:690) -- and
            # TServerLevel's isnopkzone / nopkzone / issparringzone
            # (:71, :89, :80) are all numeric or boolean, where 0.0 is both
            # the right shape and the right value for a client-side level.
            return 0.0
        return value

    def set(self, key: str, value: Any) -> None:
        if key.lower() == "name":
            # propfun_graalvar_name_w (src/TGraalVarProperties.cpp:154-161)
            # assigns only while the object is still unnamed AND unlinked; a
            # live level is neither, so the write is a no-op there too.
            return
        super().set(key, value)


class _BoardTilesColumn(list):
    """One column of the live `tiles[]` view (see ClientGS2.tiles_view).

    A real list subclass so every VM op that gates on isinstance(list)
    (OP_ARRAY / OP_ARRAY_ASSIGN / OP_ARRAY_MULTIDIM*) accepts it, but the
    element storage is the CLIENT BOARD: reads and writes route through the
    gmap-aware helpers in gs1_client, so world coords hit the owning
    segment's board and a write patches the real board (collision) plus the
    renderer's cached segment surface -- not a detached snapshot. The base
    list stays empty; __len__ supplies the world height so the VM's bounds
    checks and its extend-on-grow path stay in-range without materializing
    placeholder rows."""

    __slots__ = ("_rt2", "_x", "_h")

    def __init__(self, rt2: "ClientGS2", x: int, height: int):
        super().__init__()
        self._rt2 = rt2
        self._x = x
        self._h = height

    def __len__(self) -> int:
        return self._h

    def __bool__(self) -> bool:
        return self._h > 0

    def __iter__(self):
        return (self[i] for i in range(self._h))

    def __getitem__(self, y):
        if isinstance(y, slice):
            return [self[i] for i in range(*y.indices(self._h))]
        v = board_tile_read(self._rt2.client, self._x, y)
        return 0.0 if v is None else v

    def __setitem__(self, y, value):
        if not isinstance(y, slice):
            board_tile_write(self._rt2.client, self._x, y, to_num(value))


# ---------------------------------------------------------------------------
# GS2 builtin dispatch registries.
#
# GS2ClientHost.call_builtin consults these tables in a fixed order (see
# call_builtin / _call_obj_method / _call_bare_builtin). They are EXPLICIT
# registries, not auto-discovery: every name a script can call appears
# literally in a @_gs2_builtin decorator, so grep finds its handler and
# host_surface() is just their key set.
# ---------------------------------------------------------------------------

#: A handler returns this to mean "my guard did not hold, keep walking the
#: stages" -- the flat if/elif chain's fall-through, made explicit. Distinct
#: from NOT_HANDLED, which is the FINAL answer "no host implementation, the VM
#: may handle it natively".
_FALL_THROUGH = object()

#: Answered for BOTH call forms, before the obj-method stages.
_GS2_ANY: Dict[str, Any] = {}
#: obj-method stages, in dispatch order. The gate is in the stage name.
_GS2_LIST_METHODS: Dict[str, Any] = {}      # obj is a plain Python list
_GS2_STR_METHODS: Dict[str, Any] = {}       # obj is a str
_GS2_ENGINE_METHODS: Dict[str, Any] = {}    # obj is an _EngineObject
_GS2_GUI_METHODS: Dict[str, Any] = {}       # a GS2GuiManager exists
_GS2_OBJ_METHODS: Dict[str, Any] = {}       # any obj, no type gate
_GS2_PARTICLE_METHODS: Dict[str, Any] = {}  # obj is a ParticleEmitter/Modifier
_GS2_POPUP_METHODS: Dict[str, Any] = {}     # obj is a GuiPopUpEditCtrl
_GS2_VARS_METHODS: Dict[str, Any] = {}      # obj is a GS2Object
#: bare-call stages: GUI construction is consulted BEFORE `stubbed`.
_GS2_BARE_GUI: Dict[str, Any] = {}
_GS2_BARE: Dict[str, Any] = {}

#: Named-object factories for get_object() -- bare-name reads (`player`,
#: `GUIContainer`, `screenwidth`, ...). Keyed by the LOWERCASED name, as
#: get_object() lowercases before looking up.
_GS2_OBJECTS: Dict[str, Any] = {}

#: every table above -- host_surface()'s source of truth.
_GS2_TABLES = (_GS2_ANY, _GS2_LIST_METHODS, _GS2_STR_METHODS,
               _GS2_ENGINE_METHODS, _GS2_GUI_METHODS, _GS2_OBJ_METHODS,
               _GS2_PARTICLE_METHODS, _GS2_POPUP_METHODS, _GS2_VARS_METHODS,
               _GS2_BARE_GUI, _GS2_BARE)


def _gs2_builtin(table, *names):
    """Register a call_builtin handler in `table` under each of `names`.
    Every handler takes (self, vm, name, args, obj)."""
    def register(fn):
        for entry in names:
            if entry in table:
                raise AssertionError(f"duplicate GS2 builtin {entry!r}")
            table[entry] = fn
        return fn
    return register


def _gs2_object(*names):
    """Register a get_object() factory under each of `names` (lowercase).
    Every factory takes (self, name)."""
    def register(fn):
        for entry in names:
            if entry in _GS2_OBJECTS:
                raise AssertionError(f"duplicate GS2 object {entry!r}")
            _GS2_OBJECTS[entry] = fn
        return fn
    return register


def _set_selected_weapon(rt2: "ClientGS2", key: str, value: Any) -> bool:
    """selectedweapon / selectedsword writes, bounds-checked exactly as
    propfun_gsfunctionsclient_selectedweapon_w does (quattroplay/src/
    TInitStatics.cpp:2662-2668, and :2645-2654 for the sword): a negative
    index, or one past the end of the weapon array, is IGNORED -- and setting
    either one adopts the other when that one is still unselected."""
    index = int(to_num(value))
    weapons = getattr(rt2.client, "weapons", {}) or {}
    if index < 0 or index >= len(weapons):
        return True
    if key == "selectedsword":
        rt2._selected_sword = index
    else:
        inventory = getattr(getattr(rt2, "game_shell", None),
                            "inventory_ui", None)
        if inventory is not None:
            inventory.selected_weapon_idx = index
            inventory.cursor_weapon_idx = index
        if rt2._selected_sword < 0:
            rt2._selected_sword = index
    return True


def _set_lighting_enabled(rt2: "ClientGS2", key: str, value: Any) -> bool:
    game = getattr(rt2, "game_shell", None)
    if game is not None:
        game._day_night_enabled = to_bool(value)
    return True


#: Bare GLOBAL names the reference registers with a real setter. vm.py's
#: _assign_name drops a bare-name write straight into the globals dict and
#: _lookup reads that dict before ever consulting host.get_object, so without
#: this hook the write would be swallowed by the dict: the engine would never
#: see it and every later read would answer the swallowed copy instead of live
#: state. A handler returning True means "consumed, store nothing".
_GS2_GLOBAL_SETTERS = {
    "selectedweapon": _set_selected_weapon,
    "selectedsword": _set_selected_weapon,
    "isgraalplugin": lambda rt2, key, value: True,
    "isgraal3d": lambda rt2, key, value: True,
    "lighteffectsenabled": _set_lighting_enabled,
}


class _GlobalsStore(dict):
    """The VM-shared global namespace, with engine-backed globals routed to
    the engine instead of shadowed -- see _GS2_GLOBAL_SETTERS."""

    __slots__ = ("_rt2",)

    def __init__(self, rt2: "ClientGS2"):
        super().__init__()
        self._rt2 = rt2

    def __setitem__(self, key: str, value: Any) -> None:
        handler = _GS2_GLOBAL_SETTERS.get(key)
        if handler is not None and handler(self._rt2, key, value):
            return
        super().__setitem__(key, value)

    def __contains__(self, key: object) -> bool:
        return key == "lighteffectsenabled" or super().__contains__(key)

    def __getitem__(self, key: str) -> Any:
        if key == "lighteffectsenabled":
            return self._rt2.host._obj_lighting_enabled(key)
        return super().__getitem__(key)

    def get(self, key: str, default=None) -> Any:
        if key == "lighteffectsenabled":
            return self[key]
        return super().get(key, default)


def _gs2_sort_key(value):
    """Key for sort()/sortAscending()/sortDescending(): GS2's ASCII-only case
    fold -- the same policy every case-insensitive compare in the machine uses
    (reborn_protocol.gs2.values.casefold) -- then the numeric value as the
    tie-break for a list of numbers."""
    return (gs2_casefold(to_str(value)), to_num(value))
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
        # Login/-LoginScreen credential + platform surface (live corpus).
        # Inert BY POLICY: this client must never store, derive, or transmit
        # credential material on a script's behalf (accounts come from
        # prefs.py). des_encrypt returning 0.0 means a script's "encrypted"
        # credential blob is a constant, never real data.
        "des_encrypt",
        "setaccountname",
        "setnickname",
        "setpassword",
        "savegraaloptions",     # native options store; nothing to write
        "reconnect",            # engine-driven reconnect; not script-safe here
        "adventure_getsystemid",  # native device identity; no stable analog
        # the live Login Mobile corpus calls the same surface through the
        # Adventure engine's prefixed bindings
        "adventure_setaccountname",
        "adventure_setnickname",
        "adventure_setpassword",
        "adventure_savegraaloptions",
        "adventure_reconnect",
        # native-canvas rebuild toggle the Login serverlist calls at init;
        # there is no native canvas here, so nothing to rebuild
        "adventure_setgraalcontrolrecreate",
        # -- 2026-07-24 Login corpus (weapon-LoginScreen / -Rescripted_IRC_*
        # / -Rescripted_Serverlist / ServerListScreen) ---------------------
        # credential surface -- inert BY POLICY, accounts come from prefs.py
        "setpasswordofaccount",
        "applypassword",
        "clearpassword",
        # -- 2026-07-26 mobile Login corpus (weapon-Mobile_Login /
        # weapon-LoginScreen) ----------------------------------------------
        # credential surface, same policy as des_encrypt above: the mobile
        # saveCredentials/getSavedPassword pair round-trips account+password
        # through des_encrypt/des_decrypt on a cache file. Decrypt must be
        # exactly as inert as encrypt -- a functional decrypt over an inert
        # encrypt would still hand scripts a constant, but implementing
        # either endpoint invites the other.
        "des_decrypt",
        # native display reconfiguration for the iphone build
        # (weapon-LoginScreen.txt:35, gated on getplatform() == "iphone",
        # which this client never reports); no display to reconfigure
        "initializeiphonedisplay",
        "adventure_geteditnickname",
        "adventure_geteditaccountnames",
        # external-app launch -- attack primitive, inert BY POLICY
        "opengraalurl",
        "gotowebpage",
        "adventure_openexternaloptions",
        "showupdatewindow",
        "startgraalstreaming",
        "showfriendinvitationwindow",
        "showgiftinvitationwindow",
        # native platform toggles, result always discarded
        "adventure_startofflinemode",
        "adventure_setallowedsocketsconnect",
        "adventure_setfullscreen",
        "adventure_setchat",
        "adventure_opendefaultviewer",
        "adventure_setallowrecordbyscript",
        "adventure_quit",
        "createsmartphoneui",
        "mouselock", "mouseunlock",
        # connect-through: we join servers from our own browser
        "connecttoselectedserver",
        "serverdirectconnect",
        "startscriptedrc",
        "initserverlist",
        "requestserverinfo",
        "selectservercategory",
        # platform account windows: no session
        "showshop",
        "showprofile",
        "showoptions",
        "openchat",
        "haspanel",
        # Server-side directory listing (`files.loadfolder("x/*.gani", 0)`).
        # The file protocol has no directory query, so there is nothing
        # truthful to return; the caller iterates the (empty) result.
        "loadfolder",
        # Native client patcher. Never real here (pyReborn downloads assets
        # through the ordinary file-request path, not update packages), but
        # the RETURN VALUES matter: IRC_Installer polls these in a progress
        # loop, so they must read as "nothing to download, already
        # complete" or the loop never terminates -- hence the value table
        # below rather than the blanket 0.0 the rest of this set gets.
        "gettotalupdatepackagesize",
        "getdownloadedupdatepackagesize",
        "getpackagesdownloaded",
        "isdownloadingfiles",
        "getpackagesdownloadcomplete",
        "getdownloadingpackage",
    })

    #: Terminating constants for the patcher queries listed in `stubbed`:
    #: zero bytes outstanding, download complete, nothing in flight.
    _PATCHER_STUB_VALUES = {
        "gettotalupdatepackagesize": 0.0,
        "getdownloadedupdatepackagesize": 0.0,
        "getpackagesdownloaded": 0.0,
        "isdownloadingfiles": 0.0,
        "getpackagesdownloadcomplete": 1.0,
        "getdownloadingpackage": "",
    }

    #: host_surface() cache -- computed once per process because the surface
    #: is static.
    _surface_cache: Optional[frozenset] = None

    @staticmethod
    def host_surface():
        """Return builtins handled directly or delegated to the real GS1 host.

        Just the dispatch registries' key set (plus the two delegated GS1
        tables and the stub set) -- the flat if/elif chain this replaced had to
        be recovered by parsing call_builtin's own AST.
        """
        if GS2ClientHost._surface_cache is not None:
            return GS2ClientHost._surface_cache
        names = set(_GS1_COMMANDS) | set(_GS1_FUNCTIONS)
        for table in _GS2_TABLES:
            names.update(table)
        # control METHODS answered by GuiControl.get() bound callables
        # (method-form and with-scope calls never reach call_builtin's
        # dispatch, but they ARE part of the live host surface). Every
        # control CLASS contributes: a tree view's addNodeByPath is no less
        # implemented than the base class's showTop.
        if GS2GuiManager is not None:
            from .game.gs2_gui import control_method_names
            names |= control_method_names()
        GS2ClientHost._surface_cache = frozenset(names) | GS2ClientHost.stubbed
        return GS2ClientHost._surface_cache

    # -- infrastructure ----------------------------------------------------

    def get_globals(self) -> Dict[str, Any]:
        return self.rt2.globals_store

    def get_object(self, name: str) -> Optional[GS2Object]:
        """Resolve a bare name to an object (or plain value -- the VM pushes
        whatever comes back; see vm.py _lookup / _op_conv_to_object).

        Named engine objects/globals come from the _GS2_OBJECTS registry; a
        name that is in no table falls through to the three dynamic sources
        below (loaded weapon scripts, GUI controls, the GS1 host's builtins).
        """
        name = name.lower()
        factory = _GS2_OBJECTS.get(name)
        if factory is not None:
            return factory(self, name)
        # a named weapon's script object (findweapon-style access)
        vm = self.rt2.vms["weapon"].get(name)
        if vm is not None:
            return vm.this
        # a named GUI control: `new GuiWindowCtrl(Serverlist_Panel)` binds the
        # ctor arg as a global name, and scripts then address the control as a
        # bare global -- the live Login server's -Rescripted/IRC/Login3 does
        # `GuiRC.visible = true; gr_LoginScreen.visible = false;` and gates on
        # `isObject("Serverlist_Panel")`. GS2GuiManager already keeps the
        # name->control registry; without this hop those bare references (and
        # isobject() on control names, which routes through get_object) never
        # resolved.
        if self.rt2.gui is not None:
            ctrl = self.rt2.gui._named.get(name)
            if ctrl is not None:
                return ctrl
            if name.endswith("profile"):
                # bare reference to an ENGINE-BUILTIN profile
                # (`profile = GuiBlueTransWindowProfile;`,
                # `with (GuiDefaultProfile) {...}`): never script-declared,
                # vivified from the builtin style table on first use
                prof = self.rt2.gui.profile_by_name(name)
                if prof is not None:
                    return prof
        gs1 = self.rt2.gs1
        if gs1 is not None:
            value = gs1._host.get_builtin(
                name, [], self.rt2._gs1_ctx(None))
            if value is not UNSET:
                return value
        return None

    @_gs2_object("player", "playero")
    def _obj_player(self, name):
        vm = self.rt2._executing_vm
        return getattr(vm, "_gs2_player", self.rt2.player_object)

    @_gs2_object("level")
    def _obj_level(self, name):
        return self.rt2.level_object

    @_gs2_object("server", "serverr", "client", "clientr")
    def _obj_flag_scope(self, name):
        return self.rt2.flag_scope_object(name)

    @_gs2_object("guicontainer")
    def _obj_guicontainer(self, name):
        # The engine's root GUI canvas. Scripts wrap whole construction
        # runs in `with (GUIContainer) { Win = new ("GuiWindowCtrl")
        # {...} }` (Login -Serverlist_Chat addChatWindowControls; readable
        # source: Preagonal/gbf/bytecode/login/_Serverlist_Chat.gs2bc.gs2).
        # A with-block requires an object target.
        # A persistent engine-object stand-in is sufficient: parenting
        # comes from the compiler's auto-emitted addcontrol calls, not
        # from the container. It must also answer canvas geometry reads.
        obj = _engine_object(self.rt2, "guicontainer", _CanvasObject)
        gs1 = self.rt2.gs1
        w = float(getattr(gs1, "screen_w", 800) or 800)
        h = float(getattr(gs1, "screen_h", 600) or 600)
        obj._members.update({
            "width": w, "height": h, "clientwidth": w, "clientheight": h,
            "extent": [w, h], "clientextent": [w, h],
        })
        return obj

    @_gs2_object("graalcontrol", "graalcontrol3d")
    def _obj_game_viewport(self, name):
        # The engine's game-viewport control. Login's
        # initGraalControlSize resizes it (height = parent.clientheight
        # - taskbar) and then anchors its ChatBar/toggle button off its
        # clientwidth/clientheight, so it must answer geometry reads;
        # the script's own `height` write (with-scope, existence-gated
        # -- hence the setdefault) takes precedence over the live
        # canvas height on later clientheight reads.
        obj = _engine_object(self.rt2, name, _CanvasObject)
        gs1 = self.rt2.gs1
        w = float(getattr(gs1, "screen_w", 800) or 800)
        h = float(getattr(gs1, "screen_h", 600) or 600)
        own_h = obj._members.get("height")
        eff_h = to_num(own_h) if own_h is not None else h
        obj._members.setdefault("height", eff_h)
        obj._members.setdefault("y", 0.0)
        obj._members["parent"] = self.get_object("guicontainer")
        obj._members.update({
            "width": w, "clientwidth": w, "clientheight": eff_h,
            "extent": [w, eff_h], "clientextent": [w, eff_h],
        })
        return obj

    @_gs2_object("servername")
    def _obj_servername(self, name):
        # Bare global: the CURRENT server's serverlist name ("Login").
        # The Login scripts gate their whole taskbar layout on it
        # (isLoginServer(): Serverlist_TaskButton_Server is visible in
        # the non-login case).
        return to_str(getattr(self.rt2.client, "server_name", "") or "")

    @_gs2_object("serverstartconnect", "serverstartparams", "serveraddr")
    def _obj_serverlist_globals(self, name):
        # The other three TServerList globals. They MUST answer as
        # STRINGS, not as "unresolved" -- the reference allocates all
        # four as TStrings up front (`TServerList::serverstartconnect =
        # new TString()`, FourPlay quattroplay/src/TInitStatics.cpp:
        # 4928-4937, alongside the servername = "Offline" above), so an
        # untouched one is the empty STRING and compares by strcasecmp.
        # Unanswered -> None -> lattice NUMBER 0.0, and 0.0 == strtofloat(s) is TRUE
        # for any non-numeric string (TScriptMachine.cpp:1463), which is how
        # initServerlist's serverstartconnect == "skills" test at
        # weapon-Rescripted_Serverlist.txt:85 fired and skipped
        # sendServerListRequest() at :121.
        #
        # `serverstartconnect` carries the server the client was launched
        # to auto-join (an auto-join URL / command line); pyReborn is always
        # launched at a server directly, so it is always empty here.
        return ""

    @_gs2_object("worldsf")
    def _obj_worldsf(self, name):
        # v6 C# client world handle: scripts call WorldsF.setFrameTick(ms)
        # (v6 preloader init + npc 10371). Method calls on an object the
        # host can't resolve never reach call_builtin (the VM only
        # consults the host when obj is not None), so hand back a
        # persistent engine-object stand-in.
        return _engine_object(self.rt2, "worldsf")

    @_gs2_object("screenwidth", "screenheight")
    def _obj_screensize(self, name):
        # Bare screen-size reads: -arenaSYS centers its "Joining..."
        # showtext at (screenwidth/2, screenheight/2), the preloader's
        # DrawBar anchors likewise. The VM resolves unknown bare names
        # through host.get_object, which returned None here -> the
        # Numeric unresolved-read rule: see the identity-property note.
        # Same source the GS1 host's screenwidth/screenheight builtins use.
        gs1 = self.rt2.gs1
        attr = "screen_w" if name == "screenwidth" else "screen_h"
        return float(getattr(gs1, attr, 0) or 0)

    @_gs2_object("isleader")
    def _obj_isleader(self, name):
        gs1 = self.rt2.gs1
        if gs1 is None:
            return False
        return gs1._host.get_builtin("isleader", [], self.rt2._gs1_ctx(None))

    @_gs2_object("allstats")
    def _obj_allstats(self, name):
        # Sum of every showstats bit (GServer-v2 docs, "showstats"):
        # 1 ASD + 2 icons + 4 gralats + 8 bombs + 16 arrows + 32 hearts
        # + 64 AP + 128 MP + 256 minimap + 512 inventory + 1024 players.
        # Numeric unresolved-read rule: see the identity-property note.
        return 2047.0

    @_gs2_object("timevar", "timevar2")
    def _obj_timevar(self, name):
        # bare-name clock reads (v6 -Test_Movement stamps player.notpush
        # = timevar2 for its push-mode timing); same source the GS1
        # engine's builtin uses so both engines share one clock.
        gs1 = self.rt2.gs1
        if gs1 is None:
            return 0.0
        return gs1._host.get_builtin(name, [], self.rt2._gs1_ctx(None))

    @_gs2_object("allfeatures", "allrenderobjecttypes")
    def _obj_all_bitmasks(self, name):
        # allstats' two neighbours in the same constant block
        # (quattroplay/src/TInitStatics.cpp:2336 and :2338): 0xffff and 0x3f.
        return 65535.0 if name == "allfeatures" else 63.0

    @_gs2_object("isgraalplugin", "isgraal3d")
    def _obj_legacy_modes(self, name):
        return 0.0

    @_gs2_object("lighteffectsenabled")
    def _obj_lighting_enabled(self, name):
        game = getattr(self.rt2, "game_shell", None)
        return 1.0 if getattr(game, "_day_night_enabled", False) else 0.0

    @_gs2_object("spritesimage", "statusimage")
    def _obj_sheet_names(self, name):
        # RW globals with NON-EMPTY reference defaults
        # (src/TInitStatics.cpp:2779/:2780, seeded at :4809-4813). A script
        # write lands in the VM globals dict, which _lookup consults before
        # ever reaching here, so the write shadows this default.
        return "sprites.png" if name == "spritesimage" else "state.png"

    @_gs2_object(
        # -- registered 's', no source here: they must answer the empty
        # STRING, never nothing. An unanswered name resolves to Number 0.0
        # (quattroplay/src/TScriptStackEntry.cpp:228-229) and a Number/String
        # compare strtofloat()s the string (src/TScriptMachine.cpp:1463), so
        # `<name> == "<any word>"` is TRUE. That is not hypothetical: it is
        # how serverstartconnect and player.platform each broke a live
        # session. "" compares through compareIgnoreCase and behaves.
        "emoticonchar",             # TInitStatics.cpp:2746 (TInput state)
        "downloadfile",             # TFileDownload.cpp:69
        "lastdownloadfile",         # :70
        "disabledsoundeffects",     # sound/TSounds.cpp:214
        "allowedimageanimations",   # TTexture.cpp:70
        "installedlanguages",       # TTranslations.cpp:39
        # The web-plugin session cookie, genuinely empty until a plugin host
        # sets one (TOptions.cpp:457, backing store seeded as a bare TString
        # at TInitStatics.cpp:4784-4786). A registry KEY a script types
        # verbatim, so it keeps the reference's pre-rebrand spelling for the
        # same reason gs1_client's `graalversion` builtin does.
        "graalplugincookie",
    )
    def _obj_empty_string_globals(self, name):
        # Deliberately "" rather than a guess: our file transport is a
        # request/response fetch with no single "current download", and we run
        # no translation catalogue -- so "" is the honest answer AND the safe
        # one. Contrast _obj_option_defaults below, where the reference does
        # seed a value and "" would be the wrong answer.
        return ""

    #: The desktop OPTION store. T4 says it is not implementable client-side,
    #: which is true of the persistence -- but the reference seeds every one
    #: of these at startup (`*_initStaticVars`), and content reads the seeds,
    #: so answering "" is as wrong as answering nothing. Values verified at
    #: quattroplay/src/TInitStatics.cpp:4777 (screenshotformat), :4789/:4790
    #: (the two GUI styles), :4841 (language), :4981/:4983/:4984 (font size,
    #: font name, unicode font). Same verbatim-key rule as graalplugincookie.
    #:
    #: `defaultfontsize` is the one this table exists for. It is NUMERIC, so
    #: the `== "literal"` hazard does not apply and the top-down sweep of
    #: string-typed names never listed it -- but Zelda does
    #: `zoom = $pref::graal::defaultfontsize/24;` (graal-lttp
    #: weapons/weapon-Player_Movement.txt:101) and then draws every player's
    #: nick at that zoom (:93). Unanswered it is 0, so the labels render at
    #: zoom 0; answered it is 24/24 == 1.
    _OPTION_DEFAULTS = {
        "$pref::video::defaultguistyle": "toon_small.wba",
        "$pref::video::externalguistyle": "toon_small.wba",
        "$pref::video::screenshotformat": "PNG",
        "$pref::graal::language": "English",
        "$pref::graal::defaultfontname": "Arial",
        "$pref::graal::utf8fontfile": "DroidSansFallback.ttf",
        "$pref::graal::defaultfontsize": 24.0,
        # b RW (TOptions.cpp:45-46), default false there. We answer TRUE: this
        # client never stores credentials on a script's behalf (see the
        # `stubbed` credential set), so "do not save passwords" is the state
        # the Login screen's checkbox should reflect.
        "$pref::graal::dontsavepasswords": 1.0,
    }

    @_gs2_object(*_OPTION_DEFAULTS)
    def _obj_option_defaults(self, name):
        return self._OPTION_DEFAULTS[name]

    @_gs2_object("iscarrying")
    def _obj_iscarrying(self, name):
        # b RO, TInitStatics.cpp:2754 (getter :2418-2421). Same answer the
        # GS1 `carrying` builtin gives, so one carry state serves both.
        gs1 = self.rt2.gs1
        if gs1 is None:
            return False
        return gs1._host.get_builtin("carrying", [], self.rt2._gs1_ctx(None))

    @_gs2_object("isonmap")
    def _obj_isonmap(self, name):
        # b RO, TInitStatics.cpp:2756 (getter :2428-2431: the acting player
        # has a map pointer).
        return bool(getattr(self.rt2.client, "gmap_width", 0))

    @_gs2_object("levelorgx", "levelorgy")
    def _obj_levelorg(self, name):
        # d RO, TInitStatics.cpp:2757/:2758. NOT a level origin: the getters
        # (:2445-2455, helper :2433-2443) return the LOCAL x/y of the object
        # the acting NPC is ATTACHED TO, and 0 when nothing is attached.
        # pyReborn models no attachment at all, so 0.0 is the reference's own
        # answer for our situation, not a placeholder for one.
        return 0.0

    @_gs2_object("selectedweapon", "selectedsword")
    def _obj_selected_weapon(self, name):
        # i RW, TInitStatics.cpp:2778/:2777 (getters :2657-2660, :2640-2643):
        # an index into the player's weapon array, -1 when nothing is
        # selected. Writes are bounds-checked -- see _GLOBAL_SETTERS.
        rt2 = self.rt2
        if name == "selectedsword":
            return float(rt2._selected_sword)
        weapons = getattr(rt2.client, "weapons", {}) or {}
        if not weapons:
            return -1.0
        game = getattr(rt2, "game_shell", None)
        # Full-array index (hidden "-" weapons included): the shell converts
        # the inventory's filtered index — see
        # pygame_game.selected_weapon_full_index.
        conv = getattr(game, "selected_weapon_full_index", None)
        if conv is not None:
            return float(conv())
        index = getattr(getattr(game, "inventory_ui", None),
                        "selected_weapon_idx", 0) or 0
        return float(index) if 0 <= index < len(weapons) else -1.0

    @_gs2_object("mousebuttons", "mousebuttonsglobal", "rightmousebutton",
                 "rightmousebuttonglobal", "middlemousebutton",
                 "middlemousebuttonglobal", "leftmousebuttonglobal",
                 "mousewheeldelta", "mousewheeldeltaglobal")
    def _obj_mouse_buttons(self, name):
        # TInitStatics.cpp:2759-2767. The mask is left=1, middle=2, right=4
        # (:2457-2469); mousebuttons is mousebuttonsglobal forced to 0 while
        # the game viewport lacks focus (:2471-2474), a distinction this
        # client has no separate state for -- the pygame window IS the
        # viewport -- so the two agree here. Only the left button is tracked
        # (game/input.py feeds gs1.mouse_left and nothing else), so the other
        # bits read 0; getattr keeps them correct the moment that changes.
        gs1 = self.rt2.gs1
        left = bool(getattr(gs1, "mouse_left", False))
        middle = bool(getattr(gs1, "mouse_middle", False))
        right = bool(getattr(gs1, "mouse_right", False))
        if name.startswith("mousewheeldelta"):
            return float(getattr(gs1, "mouse_wheel", 0) or 0)
        if name.startswith("rightmousebutton"):
            return right
        if name.startswith("middlemousebutton"):
            return middle
        if name == "leftmousebuttonglobal":
            return left
        return float(left) + 2.0 * middle + 4.0 * right

    @_gs2_object("players")
    def _obj_players(self, name):
        return self.rt2.player_list_objects()

    @_gs2_object("allplayers")
    def _obj_allplayers(self, name):
        # The engine's GLOBAL player list (TGameEnvironment::allplayers,
        # TInitStatics.cpp:5148), distinct from the in-level `players`.
        # -Playerlist's whole roster and -Serverlist_Chat's chatters pane
        # iterate it; unregistered it read Number 0.0 and both no-oped.
        return self.rt2.all_player_objects()

    @_gs2_object("scriptedplayerlist")
    def _obj_scriptedplayerlist(self, name):
        # Hardwired TRUE in the reference
        # (Q/src/TInitStatics.cpp:2638 propfun_gsfunctionsclient_
        # scriptedplayerlist_r, registered :2776): "this client wants the
        # scripted player list" -- the transition flag from the old
        # engine-drawn sidebar. -Playerlist.onCreated wraps EVERYTHING in
        # `if (scriptedplayerlist)`, so leaving it unregistered (0.0) was
        # the root cause of the dead player list.
        return 1.0

    @_gs2_object("weapons")
    def _obj_weapons(self, name):
        return self.rt2.weapon_list_objects()

    @_gs2_object("tiles")
    def _obj_tiles(self, name):
        return self.rt2.tiles_view()

    def create_object(self, classname: str, arg: Any) -> GS2Object:
        # host.create_object() is the VM's constructor hook for every `new`
        # (see _op_new_object in reborn_protocol/gs2/vm.py). Any Gui*Ctrl classname
        # builds a real control (tracked by GS2GuiManager); everything else
        # keeps the prior behavior (an empty, untracked GS2Object).
        # A classname ENDING in "profile" is a profile DERIVATION whose
        # classname names the PARENT profile -- Login's addProfiles derives
        # `new IRC_WindowProfile("IRC_WindowLeftProfile")` etc., which does
        # NOT start with "gui": the startswith gate alone dropped every such
        # derived profile to a plain GS2Object (unregistered, fields lost,
        # and its auto-emitted addcontrol warned "non-control value").
        cn = classname.lower()
        if self.rt2.gui is not None and (cn.startswith("gui")
                                         or cn.endswith("profile")):
            return self.rt2.gui.create_control(classname, arg)
        obj = GS2Object(name=classname)
        # `new <Class>("objname")` names the object through the TGraalVar
        # base, and TGraalVar's `name` is string-typed on EVERY object
        # (quattroplay/src/TGraalVarProperties.cpp:627) -- so leaving the
        # member unset made `obj.name == "<anything>"` true. "" when the
        # constructor was handed something that is not a name.
        obj.set("name", arg if isinstance(arg, str) else "")
        return obj

    def sleep(self, vm: GS2VM, seconds: float) -> None:
        # The VM can't suspend, so sleep() blocks -- but it pumps the packet loop,
        # which is what sleeping scripts wait FOR (preloader poll loops). Capped at
        # 1s so a script can't freeze the app.
        rt2 = self.rt2
        secs = min(max(to_num(seconds), 0.0), 1.0)
        if secs <= 0:
            return
        client = rt2.client
        if client is None or not getattr(client, "connected", False) or rt2._sleeping:
            # Disconnected, or already inside another sleep()'s update() pump: re-entering
            # update() would re-enter packet handling. Wait the FULL duration in slices
            # with plain time.sleep() instead.
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
    #
    # Dispatch is table-driven: `call_builtin` walks the stages below in the
    # order the flat if/elif chain it replaced used to, consulting one
    # @_gs2_builtin-registered table per stage. The stage ORDER is load-bearing
    # (see the individual comments); a name may appear in more than one table
    # with different behaviour, and the first stage whose gate matches and
    # whose handler does not return _FALL_THROUGH wins.

    def call_builtin(self, vm: GS2VM, name: str, args: List[Any],
                     obj: Optional[GS2Object] = None) -> Any:
        # Answered for BOTH forms (bare call and obj method): the object
        # method spelling is the only one the live corpus uses, but the
        # obj-method stages below end in NOT_HANDLED, so these must come first.
        handler = _GS2_ANY.get(name)
        if handler is not None:
            result = handler(self, vm, name, args, obj)
            if result is not _FALL_THROUGH:
                return result
        if obj is not None:
            return self._call_obj_method(vm, name, args, obj)
        return self._call_bare_builtin(vm, name, args)

    def _call_obj_method(self, vm: GS2VM, name: str, args: List[Any],
                         obj: Any) -> Any:
        rt2 = self.rt2
        if isinstance(obj, list):
            handler = _GS2_LIST_METHODS.get(name)
            if handler is not None:
                return handler(self, vm, name, args, obj)
        if isinstance(obj, str):
            handler = _GS2_STR_METHODS.get(name)
            if handler is not None:
                return handler(self, vm, name, args, obj)
            # ("-Serverlist_Options").showOptions() -- a method call on a
            # string that NAMES a weapon script dispatches to that weapon's
            # public function (the reference resolves the string literal
            # through the universe vars, where installed weapons live --
            # TScriptStackEntry::makeProperty's String case; Login's whole
            # start menu drives -Serverlist_Options, -Rescripted/-F2LogWindow,
            # -ShopGlobal and -ScriptedRC this way). A weapon that is not
            # loaded is fetched over the PLI_UPDATESCRIPT channel, this
            # client's stand-in for the client install (see fetch_weapon) --
            # safe to do from here because ONLY method calls reach this
            # branch: isobject()/bare-name reads never trigger a fetch, and
            # a name the server does not answer is negative-cached.
            wvm = rt2.vms["weapon"].get(obj.lower())
            if wvm is None:
                wvm = rt2.fetch_weapon(obj)
            if wvm is not None and wvm.has_function(name):
                return wvm.call(name, *args)
        # Other list methods (add/addarray/size/clear/index/sortbyvalue)
        # deliberately fall through as NOT_HANDLED: the shared VM implements
        # them natively and gives the host first refusal (obj= may be a plain
        # Python list here, not a GS2Object).
        if name in self.stubbed:
            # NOTE: the obj form is a flat 0.0, NOT the bare form's
            # _PATCHER_STUB_VALUES table.
            return 0.0
        if name == "addcontrol" and rt2.gui is not None:
            # Its own stage, ABOVE the engine-object catch-all: obj may be the
            # GUIContainer engine-object stand-in, whose addcontrol must
            # parent a control rather than answer inertly.
            return self._obj_addcontrol(vm, name, args, obj)
        if isinstance(obj, _EngineObject):
            # C# client engine-object classes: WorldsF, GameObject, and Object.
            # Observed call results are always discarded.
            handler = _GS2_ENGINE_METHODS.get(name)
            if handler is not None:
                return handler(self, vm, name, args, obj)
            # Any other engine-object method is part of the same C#-client
            # surface we don't emulate: inert, result never consumed. The
            # CANVAS stand-ins are the exception -- they sit on the
            # with-stack under whole construction runs, so an unknown name
            # must keep falling through to the outer scopes (see
            # _CanvasObject).
            if not isinstance(obj, _CanvasObject):
                return 0.0
        if isinstance(obj, (ParticleEmitter, ParticleModifier)):
            handler = _GS2_PARTICLE_METHODS.get(name)
            if handler is not None:
                result = handler(self, vm, name, args, obj)
                if result is not _FALL_THROUGH:
                    return result
        if rt2.gui is not None:
            handler = _GS2_GUI_METHODS.get(name)
            if handler is not None:
                result = handler(self, vm, name, args, obj)
                if result is not _FALL_THROUGH:
                    return result
        handler = _GS2_OBJ_METHODS.get(name)
        if handler is not None:
            result = handler(self, vm, name, args, obj)
            if result is not _FALL_THROUGH:
                return result
        if GuiPopUpEditCtrl is not None and isinstance(obj, GuiPopUpEditCtrl):
            handler = _GS2_POPUP_METHODS.get(name)
            if handler is not None:
                result = handler(self, vm, name, args, obj)
                if result is not _FALL_THROUGH:
                    return result
        if isinstance(obj, GS2Object):
            handler = _GS2_VARS_METHODS.get(name)
            if handler is not None:
                return handler(self, vm, name, args, obj)
        if name in _GS1_LEVEL_PROBES and rt2.gs1 is not None:
            res = rt2.gs1._host.call_function(name, args, rt2._gs1_ctx(vm))
            if res is not UNSET:
                return res
        # other object methods with no member function bound: no GS1
        # equivalent
        return NOT_HANDLED

    def _call_bare_builtin(self, vm: GS2VM, name: str,
                           args: List[Any]) -> Any:
        rt2 = self.rt2
        handler = _GS2_BARE_GUI.get(name)
        if handler is not None:
            return handler(self, vm, name, args, None)
        if name in self.stubbed:
            return self._PATCHER_STUB_VALUES.get(name, 0.0)
        handler = _GS2_BARE.get(name)
        if handler is not None:
            return handler(self, vm, name, args, None)
        if name.startswith("quattro::debugtools::"):
            # staff cheat-window toggles; same inert group as _bi_platform_inert
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

    # -- _GS2_ANY: answered for both the bare and the obj-method form --------

    @_gs2_builtin(_GS2_ANY, "catchevent")
    def _any_catchevent(self, vm, name, args, obj):
        # catchevent(target, eventname, handlername) -> the multi-catcher
        # registry (TScriptSpace::catchEvent, quattroplay/src/TScriptSpace.
        # cpp:1662-1764): distinct catcher scripts accumulate, re-registering
        # the same (catcher, event) replaces the handler name, and a name
        # that resolves to nothing registers PENDING and attaches when the
        # control is created. The named handler runs with the source object
        # prepended to the event's own args. Two model-specific fallbacks:
        # -Serverlist_Chat wires its smilie buttons from inside each
        # button's construction block via `thiso.catchevent(this.name,
        # "onAction", "onSmilieButton")`, where `this.name` reads back
        # empty (the VM's `this` is the weapon) -- an EMPTY name falls back
        # to the control currently being constructed; and a non-control
        # object target (requesturl's dead request object) takes a member
        # closure so the registration still lands somewhere real.
        rt2 = self.rt2
        if rt2.gui is None or len(args) < 3 or vm is None:
            return 0.0
        target = args[0]
        event = to_str(args[1]).lower()
        handler = to_str(args[2]).lower()
        if not event or not handler:
            return 0.0
        if isinstance(target, str) and not target \
                and rt2.gui._construction_stack:
            target = rt2.gui._construction_stack[-1]
        if GuiControl is not None and not isinstance(target, GuiControl) \
                and isinstance(target, GS2Object):
            target.set(event,
                       lambda *a, _o=target, _vm=vm, _h=handler:
                           _vm.call(_h, _o, *a))
            return 0.0
        rt2.gui.register_catchevent(target, event, vm, handler)
        return 0.0

    @_gs2_builtin(_GS2_ANY, "ignoreevent", "ignoreevents")
    def _any_ignoreevent(self, vm, name, args, obj):
        # ignoreevent(target, eventname): reverse a catchevent registration
        # (TScriptSpace.cpp:597-613).
        rt2 = self.rt2
        if rt2.gui is None or len(args) < 2 or vm is None:
            return 0.0
        rt2.gui.unregister_catchevent(args[0], to_str(args[1]).lower(), vm)
        return 0.0

    @_gs2_builtin(_GS2_ANY, "objecttype")
    def _any_objecttype(self, vm, name, args, obj):
        # obj.objecttype() -> the object's class name (TGraalVar method,
        # TGraalVarProperties.cpp:475-483 `{'s', ""}`). Login's
        # serverlist filters its taskbar with
        # `temp.button.objecttype() != "GuiButtonCtrl"`
        # (weapon-Rescripted_Serverlist.txt:351) and -Staff/GUIExplorer
        # labels every node with it. GuiControl subclasses carry the
        # authoritative spelling on CTRL_CLASS; everything the host
        # builds through create_object() is named after its `new`
        # classname.
        target = obj if obj is not None else getattr(vm, "this", None)
        return to_str(getattr(target, "CTRL_CLASS", None)
                      or getattr(target, "name", "") or "")

    @_gs2_builtin(_GS2_ANY, "testsign", "testitem", "testbomb", "testexplo")
    def _any_test_level_object(self, vm, name, args, obj):
        # level.testsign/testitem/testbomb/testexplo(x, y) -- the sibling
        # probes of level.testnpc, registered at
        # quattroplay/src/TServerLevelProperties.cpp:254, :245, :227 and
        # :236. Their bodies are raw addresses in the decompilation, so only
        # the signature and the -1 miss value are oracle-backed: the hit test
        # below is a TILE-CELL containment, matching the granularity the
        # protocol identifies each of these object kinds by. Answered for the
        # bare form too, since content reaches level objects both ways.
        if len(args) < 2:
            return -1.0
        tx, ty = math.floor(to_num(args[0])), math.floor(to_num(args[1]))
        found = self.rt2.level_object_positions(name)
        for index, (ox, oy) in enumerate(found):
            if math.floor(ox) == tx and math.floor(oy) == ty:
                return float(index)
        return -1.0

    # -- _GS2_LIST_METHODS: methods on a plain Python list -------------------

    @_gs2_builtin(_GS2_LIST_METHODS, "sort")
    def _list_sort(self, vm, name, args, obj):
        obj.sort(key=_gs2_sort_key)
        return obj

    # -- _GS2_STR_METHODS: string methods the compiler leaves as calls -------

    @_gs2_builtin(_GS2_STR_METHODS, "lower", "lowercase", "upper", "uppercase")
    def _str_case(self, vm, name, args, obj):
        # `.lower()`/`.upper()` are the two the live corpus uses (Login's
        # staff sprite-editor weapon keys its per-gani default map on
        # `this.gdefault.(@def.lower())`).
        return obj.lower() if name in ("lower", "lowercase") else obj.upper()

    # -- _GS2_ENGINE_METHODS: C# client engine-object stand-ins -------------

    @_gs2_builtin(_GS2_ENGINE_METHODS, "getchild")
    def _engine_getchild(self, vm, name, args, obj):
        # Find/GetChild/SetActive chains only require non-null traversal;
        # GetChild returns a stable child and SetActive records the flag.
        return obj.get(f"child{int(to_num(args[0])) if args else 0}")

    @_gs2_builtin(_GS2_ENGINE_METHODS, "setactive")
    def _engine_setactive(self, vm, name, args, obj):
        obj.set("active", 1.0 if not args or to_num(args[0]) else 0.0)
        return 0.0

    @_gs2_builtin(_GS2_ENGINE_METHODS, "makefirstresponder")
    def _engine_makefirstresponder(self, vm, name, args, obj):
        # GraalControl.makeFirstResponder(true): the canvas root takes the
        # keyboard back from whatever control held it (Login's hideChatBar,
        # weapon-Rescripted_Serverlist.txt:2698). Canvas-as-first-responder
        # IS this model's FR-None state, so clear the manager's slot (which
        # fires onLoseFirstResponder on the outgoing control) and the text
        # focus. Unanswered, this fell into the engine-object inert
        # catch-all and FR could never return to the canvas -- keystrokes
        # vanished into the invisible chat bar and keyboard_captured
        # blocked held-key movement for the rest of the session.
        rt2 = self.rt2
        if rt2.gui is not None and to_str(getattr(obj, "name", "")).lower() \
                in ("graalcontrol", "graalcontrol3d", "guicontainer"):
            rt2.gui.focus(None)
        return 0.0

    # -- _GS2_GUI_METHODS: control methods (gate: a GUI manager exists) -----

    def _obj_addcontrol(self, vm, name, args, obj):
        # Compiler-emitted `addcontrol(<child name>)` after each
        # nested new's WITHEND, resolved against the ENCLOSING
        # with-target (the VM routes with-scope bare calls here with
        # obj= that target; verified against the official
        # interpreter). Parent the named child under obj -- this is
        # what builds the real control hierarchy for the inline-new
        # compile shape (-Serverlist_Chat emits 13 of these). obj may
        # also be the GUIContainer engine-object stand-in (canvas
        # root): _resolve() returns None then and the child stays a
        # root, which IS the canvas.
        rt2 = self.rt2
        child = args[0] if args else None
        if isinstance(child, str):
            child = rt2.gui._named.get(child.lower(), child)
        rt2.gui.addcontrol(child, owner_vm=vm)
        rt2.gui.add_to(obj, child)
        return 0.0

    @_gs2_builtin(_GS2_GUI_METHODS, "addcontainer", "addguicontainer")
    def _gui_addcontainer(self, vm, name, args, obj):
        self.rt2.gui.add_to(obj, args[0] if args else None)
        return 0.0

    @_gs2_builtin(_GS2_GUI_METHODS, "getchild")
    def _gui_getchild(self, vm, name, args, obj):
        return self.rt2.gui.get_child(obj, args[0] if args else 0)

    @_gs2_builtin(_GS2_GUI_METHODS, "setactive")
    def _gui_setactive(self, vm, name, args, obj):
        ctrl = self.rt2.gui._resolve(obj)
        if ctrl is not None:
            ctrl.visible = bool(to_num(args[0])) if args else True
        return 0.0

    @_gs2_builtin(_GS2_GUI_METHODS, "hidecontrols")
    def _gui_hidecontrols(self, vm, name, args, obj):
        self.rt2.gui.hide_children(obj)
        return 0.0

    @_gs2_builtin(_GS2_GUI_METHODS, "makefirstresponder")
    def _gui_makefirstresponder(self, vm, name, args, obj):
        self.rt2.gui.focus(obj if not args or bool(to_num(args[0])) else None)
        return 0.0

    @_gs2_builtin(_GS2_GUI_METHODS, "showtop", "show")
    def _gui_showtop(self, vm, name, args, obj):
        # ctrl.showTop(): make visible and raise to the top of
        # the sibling z-order (Login's -Serverlist_Chat openChat
        # ends with GlobalChat_Window.showtop()). Same semantics
        # as the global showgui() form.
        ctrl = self.rt2.gui._resolve(obj)
        if ctrl is None:
            return _FALL_THROUGH
        self.rt2.gui.show(ctrl)
        return 0.0

    @_gs2_builtin(_GS2_GUI_METHODS, "hide")
    def _gui_hide(self, vm, name, args, obj):
        ctrl = self.rt2.gui._resolve(obj)
        if ctrl is None:
            return _FALL_THROUGH
        self.rt2.gui.hide(ctrl)
        return 0.0

    @_gs2_builtin(_GS2_GUI_METHODS, "gettextwidth")
    def _gui_gettextwidth(self, vm, name, args, obj):
        # profile.getTextWidth(text) -> px width of `text` in that
        # profile's font (-Playerlist sizes its status label with
        # `extent = {profile.getTextWidth(this.text), 23}`,
        # B/_Playerlist.gs2bc.gs2:478). Approximated off the profile's
        # fontsize with the same mean-glyph metric as the bare
        # gettextwidth's headless fallback.
        text = to_str(args[0]) if args else ""
        size = 14.0
        try:
            fields = obj._members if isinstance(obj, GS2Object) else {}
            size = to_num(fields.get("fontsize", 14.0) or 14.0)
        except Exception:
            pass
        return float(len(text)) * max(size, 8.0) * 0.55

    @_gs2_builtin(_GS2_GUI_METHODS, "trigger")
    def _gui_trigger(self, vm, name, args, obj):
        ctrl = self.rt2.gui._resolve(obj)
        if ctrl is not None:
            return 1.0 if ctrl.fire_action(*args) else 0.0
        return 0.0

    @_gs2_builtin(_GS2_GUI_METHODS, "animatecontrol")
    def _gui_animatecontrol(self, vm, name, args, obj):
        # Immediate final-state application: deterministic headless
        # fallback until the renderer gains a frame tween scheduler.
        ctrl = self.rt2.gui._resolve(obj)
        if ctrl is not None:
            for key, value in zip(("x", "y", "width", "height"), args[-4:]):
                ctrl.set(key, value)
        return 0.0

    # -- _GS2_OBJ_METHODS: object methods with no type gate -----------------
    #
    # The TGraalVar ROOT methods live here rather than in _GS2_LIST_METHODS.
    # The reference registers them on TGraalVar, i.e. on EVERY object
    # (quattroplay/src/TGraalVarProperties.cpp:494 savelines, :548 settimer,
    # :557 sortascending, :566 sortdescending), so `this.savelines("f.txt", 0)`
    # and `this.settimer(1)` are valid spellings. An `isinstance(obj, list)`
    # gate here is not just narrow, it is LOAD-BEARING in the wrong direction:
    # the host is consulted before the VM, so a gate that does not match
    # walks on to the later stages and ends at 0.0 -- which is what these did
    # even after the VM widened its own root surface.
    # `add`/`size`/`clear`/`index` deliberately stay array-only in the VM:
    # those mirror compiled opcodes, not registered names.

    @_gs2_builtin(_GS2_STR_METHODS, "hasfunction")
    @_gs2_builtin(_GS2_OBJ_METHODS, "hasfunction")
    def _obj_hasfunction(self, vm, name, args, obj):
        if not args:
            return 0.0
        wanted = to_str(args[0])
        if isinstance(obj, str):
            owner = self.rt2.vms["weapon"].get(obj.lower())
            return 1.0 if owner is not None and owner.has_function(wanted) else 0.0
        if isinstance(obj, GS2Object):
            if obj.has(wanted):
                return 1.0
            if any(owner.has_public_function(wanted)
                   for owner in obj.script_vms):
                return 1.0
        return 0.0

    @_gs2_builtin(_GS2_OBJ_METHODS, "sortascending", "sortdescending")
    def _obj_sort_directed(self, vm, name, args, obj):
        if not isinstance(obj, list):
            # An object with no array cells has nothing to sort -- the same
            # answer the VM's root surface gives for addarray/sortbyvalue.
            return 0.0
        obj.sort(key=_gs2_sort_key, reverse=name == "sortdescending")
        return obj

    @_gs2_builtin(_GS2_OBJ_METHODS, "savelines")
    def _obj_savelines(self, vm, name, args, obj):
        # savelines(filename, appendflag): the second argument is the append
        # flag ("si"), which this client's server-scoped cache does not model
        # -- it always rewrites. A non-array object has no lines to write.
        if args and isinstance(obj, list):
            self.rt2.save_lines(to_str(args[0]), obj)
        return 0.0

    @_gs2_builtin(_GS2_OBJ_METHODS, "loadvars")
    def _obj_loadvars(self, vm, name, args, obj):
        # obj.loadvars(filename): populate the OBJECT's members from
        # `name=value` lines out of this client's server-scoped cache --
        # the object-target spelling of the bare loadvars above.
        # -Playerlist's options live behind exactly this
        # (`this.options.loadvars("scriptfiles/playerlistoptions.txt")`,
        # B/_Playerlist.gs2bc.gs2:882); a missing file leaves the object
        # untouched, which is the fresh-client state.
        if not isinstance(obj, GS2Object) or not args:
            return 0.0
        for line in self.rt2.load_lines(to_str(args[0])):
            key, sep, value = to_str(line).partition("=")
            if sep and key.strip():
                obj.set(key.strip(), value)
        return 0.0

    @_gs2_builtin(_GS2_OBJ_METHODS, "loadlines")
    def _obj_loadlines(self, vm, name, args, obj):
        # obj.loadlines(filename): the reference turns the target VAR into
        # an array of the file's lines (TGraalVar loadlines). When the
        # script pre-assigned an array we can refill it in place; a
        # vivified plain object cannot be re-typed from the host, so it
        # stays empty -- indistinguishable from the missing-file case,
        # which is the true state until savelines has written the group
        # files this weapon reads back.
        if isinstance(obj, list) and args:
            obj[:] = self.rt2.load_lines(to_str(args[0]))
        return 0.0

    @_gs2_builtin(_GS2_OBJ_METHODS, "settimer")
    def _obj_settimer(self, vm, name, args, obj):
        # Same timer store the bare form arms, keyed on the CALLING script:
        # the reference's timer lives on the TGraalVar it was called on, and
        # every live call site is a script arming its own `this`.
        return self._bi_settimer(vm, name, args, None)

    @_gs2_builtin(_GS2_OBJ_METHODS, "join")
    def _obj_join(self, vm, name, args, obj):
        if args:
            self.rt2.join_class(vm, to_str(args[0]))
        return 0.0

    @_gs2_builtin(_GS2_OBJ_METHODS, "leave", "isinclass", "getcallstack")
    def _obj_class_ops(self, vm, name, args, obj):
        # The object-method spelling of the three bare forms. Every live
        # call site uses THIS one: Zelda's class:gui_builder built() ends
        # with `this.leave("gui_builder"); echo(... this.isinclass(
        # "gui_builder"))`, and g2k1's weaponParticleEditor dumps
        # `this.getCallStack()`.
        if vm is None:
            return _FALL_THROUGH
        rt2 = self.rt2
        if name == "getcallstack":
            return rt2.call_stack(vm)
        if name == "isinclass":
            return 1.0 if (args and rt2.is_in_class(vm, to_str(args[0]))) else 0.0
        if args:
            rt2.leave_class(vm, to_str(args[0]))
        return 0.0

    @_gs2_builtin(_GS2_OBJ_METHODS, "destroy")
    def _obj_destroy(self, vm, name, args, obj):
        if self.rt2.gui is None:
            return _FALL_THROUGH
        self.rt2.gui.destroy(obj)
        return 0.0

    @_gs2_builtin(_GS2_OBJ_METHODS, "scheduleevent", "cancelevents")
    def _obj_events(self, vm, name, args, obj):
        if vm is None:
            return _FALL_THROUGH
        rt2 = self.rt2
        if name == "scheduleevent" and len(args) >= 2:
            rt2.schedule_event(vm, to_num(args[0]), to_str(args[1]),
                               list(args[2:]))
        elif name == "cancelevents":
            rt2.cancel_events(vm, to_str(args[0]) if args else "")
        return 0.0

    # -- _GS2_POPUP_METHODS: GuiPopUpEditCtrl row surface -------------------

    @_gs2_builtin(_GS2_POPUP_METHODS, "addrow", "add")
    def _popup_addrow(self, vm, name, args, obj):
        if len(args) < 2:
            return _FALL_THROUGH
        return obj.add_row(args[0], args[1])

    @_gs2_builtin(_GS2_POPUP_METHODS, "clear")
    def _popup_clear(self, vm, name, args, obj):
        if self.rt2.gui is not None and self.rt2.gui._open_popup is obj:
            self.rt2.gui._close_popup()
        return obj.clear_rows()

    @_gs2_builtin(_GS2_POPUP_METHODS, "getselectedrow", "getselected")
    def _popup_getselected(self, vm, name, args, obj):
        return obj.get_selected_row()

    @_gs2_builtin(_GS2_POPUP_METHODS, "getrowtext", "gettextbyid")
    def _popup_getrowtext(self, vm, name, args, obj):
        if not args:
            return _FALL_THROUGH
        return obj.get_row_text(args[0])

    # -- _GS2_PARTICLE_METHODS: the particle-emitter object surface ----------
    # findimg(i).emitter's eight funcDefs (TParticleEmitterProperties
    # .cpp:259-332) and the modifier object's addmod (TParticleModifier
    # Properties.cpp:11-20); the state model lives in pyreborn/particles.py.

    @_gs2_builtin(_GS2_PARTICLE_METHODS, *sorted(EMITTER_METHOD_NAMES))
    def _particle_emitter_method(self, vm, name, args, obj):
        if not isinstance(obj, ParticleEmitter):
            return _FALL_THROUGH
        result = obj.call_method(name, list(args))
        if result is NotImplemented:
            return _FALL_THROUGH
        if result is None:
            # rejected modtype: the reference returns the null OBJECT, which
            # scripts test with `== null` -- 0.0 would compare unequal
            return GS2_NULL
        return result

    @_gs2_builtin(_GS2_PARTICLE_METHODS, *sorted(MODIFIER_METHOD_NAMES))
    def _particle_modifier_addmod(self, vm, name, args, obj):
        if not isinstance(obj, ParticleModifier):
            return _FALL_THROUGH
        obj.add_var_modifier(args[0] if args else "",
                             args[1] if len(args) > 1 else "",
                             args[2] if len(args) > 2 else 0.0,
                             args[3] if len(args) > 3 else 0.0)
        return 0.0

    # -- _GS2_VARS_METHODS: the dynamic-member (VariableCollection) surface --
    # Login's Staff weapons manage their caches with it:
    # `this.spritecache.clearvars()` per rebuild, and
    # `for (v: this.gdefault.getdynamicvarnames())` to walk one. Private
    # bookkeeping keys (leading "_", e.g. the layer store's "_findimg") are
    # engine-internal and stay hidden.

    @_gs2_builtin(_GS2_VARS_METHODS, "clearvars")
    def _vars_clearvars(self, vm, name, args, obj):
        for key in [k for k in obj._members if not str(k).startswith("_")]:
            del obj._members[key]
        return 0.0

    @_gs2_builtin(_GS2_VARS_METHODS, "getvarnames", "getdynamicvarnames")
    def _vars_getvarnames(self, vm, name, args, obj):
        return [key for key in obj._members
                if not str(key).startswith("_")
                and not callable(obj._members[key])]

    # -- _GS2_BARE_GUI: bare GUI-construction builtins ----------------------
    # addcontrol()'s single argument is always "the object this new-statement
    # just constructed" (never a parent) -- GS2GuiManager infers nesting from
    # create/addcontrol call order. See gs2_gui.py's module docstring.

    @_gs2_builtin(_GS2_BARE_GUI, "addcontrol")
    def _bi_addcontrol(self, vm, name, args, obj):
        if self.rt2.gui is not None:
            self.rt2.gui.addcontrol(args[0] if args else None, owner_vm=vm)
        return 0.0

    @_gs2_builtin(_GS2_BARE_GUI, "addcontainer", "addguicontainer")
    def _bi_addcontainer(self, vm, name, args, obj):
        if self.rt2.gui is not None and len(args) >= 2:
            self.rt2.gui.add_to(args[0], args[1])
        return 0.0

    # -- _GS2_BARE: everything else ------------------------------------------

    @_gs2_builtin(_GS2_BARE, "requesturl", "requesturlasgamefile")
    def _bi_requesturl(self, vm, name, args, obj):
        # Inert BY POLICY: this client never fetches script-supplied
        # URLs (Login uses it for an events-news feed; the payload is
        # cosmetic). Returns a dead request object so the follow-up
        # catchevent(this.eventinforequest, "onReceiveData", ...) has a
        # real target -- onReceiveData simply never fires.
        rt2 = self.rt2
        if name not in rt2._policy_stub_logged:
            rt2._policy_stub_logged.add(name)
            logger.info("GS2 %s(): inert stub (no network fetch by "
                        "policy); url=%r",
                        name, to_str(args[0]) if args else "")
        return GS2Object(name="urlrequest")

    @_gs2_builtin(_GS2_BARE, "_")
    def _bi_localize(self, vm, name, args, obj):
        # `text = _(temp.text);` -- the mobile client's localization wrapper
        # (weapon-Mobile_Login.txt:176; a `translations/` dir ships with the
        # mobile server). Absent from FourPlay (Era/mobile-only name) and
        # not script-defined in any corpus, so the untranslated identity is
        # both the default-language behaviour and the only unguessed one.
        # Left unanswered, every wrapped label read back Number 0.0.
        return to_str(args[0]) if args else ""

    @_gs2_builtin(_GS2_BARE, "char")
    def _bi_char(self, vm, name, args, obj):
        # char(code) -> the 1-character string (weapon-LoginScreen.txt:341
        # builds a key suffix with char(33) = "!"). Absent from FourPlay
        # (mobile/Era name); the usage admits only the C chr() reading.
        # Out-of-range codes answer "" rather than raising.
        try:
            code = int(to_num(args[0])) if args else 0
            return chr(code) if 0 < code < 0x110000 else ""
        except (ValueError, OverflowError):
            return ""

    @_gs2_builtin(_GS2_BARE, "screenx", "screeny")
    def _bi_screenxy(self, vm, name, args, obj):
        rt2 = self.rt2
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

    @_gs2_builtin(_GS2_BARE, "worldx", "worldy")
    def _bi_worldxy(self, vm, name, args, obj):
        # The inverse of screenx/screeny above: floor each argument after
        # adding the engine's 1e-4 epsilon, then screenToWorldX/Y
        # (quattroplay/src/TInitStatics.cpp:3906-3921, table :4284/:4285).
        # worldx genuinely ignores its second argument -- the reference
        # leaves that parameter unnamed -- while worldy uses both.
        game = getattr(self.rt2, "game_shell", None)
        camera = getattr(game, "camera", None)
        sx = math.floor(to_num(args[0]) + 0.0001) if args else 0
        sy = math.floor(to_num(args[1]) + 0.0001) if len(args) > 1 else 0
        if camera is None:
            return float(sx if name == "worldx" else sy)
        point = camera.screen_to_world(sx, sy)
        return float(point[0 if name == "worldx" else 1])

    @_gs2_builtin(_GS2_BARE, "getmapx", "getmapy")
    def _bi_getmapxy(self, vm, name, args, obj):
        player = getattr(self.rt2.client, "player", None)
        pos = getattr(player, "x" if name == "getmapx" else "y", 0.0)
        return float(int(to_num(pos) // 64))

    @_gs2_builtin(_GS2_BARE, "getmusicfilename")
    def _bi_getmusicfilename(self, vm, name, args, obj):
        game = getattr(self.rt2, "game_shell", None)
        manager = getattr(game, "sound_mgr", None)
        return to_str(getattr(manager, "_current_music", "") or "")

    @_gs2_builtin(_GS2_BARE, "getnearestplayers")
    def _bi_getnearestplayers(self, vm, name, args, obj):
        # players[] INDICES, nearest first -- see nearest_player_indices
        # for why this is not findnearestplayers' payload.
        rt2 = self.rt2
        player = getattr(rt2.client, "player", None)
        x = to_num(args[0]) if args else to_num(getattr(player, "x", 0))
        y = to_num(args[1]) if len(args) > 1 else to_num(getattr(player, "y", 0))
        return rt2.nearest_player_indices(x, y)

    @_gs2_builtin(_GS2_BARE, "findnearestplayers", "findnearestplayer")
    def _bi_findnearestplayers(self, vm, name, args, obj):
        # Same sort as getnearestplayers above, different payload: the
        # player OBJECTS instead of their players[] indices (quattroplay
        # TInitStatics.cpp:2088 vs :2067). The SINGULAR form is the same
        # search returning only the winner, or null when the level is
        # empty (:2044, over the same list including ourselves --
        # Zelda's lift code checks `pl.account != player.account`).
        rt2 = self.rt2
        player = getattr(rt2.client, "player", None)
        x = to_num(args[0]) if args else to_num(getattr(player, "x", 0))
        y = to_num(args[1]) if len(args) > 1 else to_num(getattr(player, "y", 0))
        found = rt2.find_nearest_players(x, y)
        if name == "findnearestplayers":
            return found
        return found[0] if found else 0.0

    @_gs2_builtin(_GS2_BARE, "getstringkeys")
    def _bi_getstringkeys(self, vm, name, args, obj):
        return self.rt2.string_keys(to_str(args[0]) if args else "")

    @_gs2_builtin(_GS2_BARE, "getcallstack")
    def _bi_getcallstack(self, vm, name, args, obj):
        return self.rt2.call_stack(vm)

    @_gs2_builtin(_GS2_BARE, "isinclass")
    def _bi_isinclass(self, vm, name, args, obj):
        return 1.0 if (vm is not None and args
                       and self.rt2.is_in_class(vm, to_str(args[0]))) else 0.0

    @_gs2_builtin(_GS2_BARE, "leave")
    def _bi_leave(self, vm, name, args, obj):
        if vm is not None and args:
            self.rt2.leave_class(vm, to_str(args[0]))
        return 0.0

    @_gs2_builtin(_GS2_BARE, "findplayerbyid")
    def _bi_findplayerbyid(self, vm, name, args, obj):
        return self.rt2.player_by_id(int(to_num(args[0]))) if args else 0.0

    @_gs2_builtin(_GS2_BARE, "loadtranslation")
    def _bi_loadtranslation(self, vm, name, args, obj):
        # loadtranslation("loginserver"): selects the _()-domain. This
        # client ships no translation catalogs, so _() already answers its
        # argument verbatim and the load is an inert success.
        return 0.0

    @_gs2_builtin(_GS2_BARE, "getservername")
    def _bi_getservername(self, vm, name, args, obj):
        # Bare-call twin of the `servername` global (the -Playerlist weapon
        # only ever compares it against "Classic iPhone").
        return to_str(getattr(self.rt2.client, "server_name", "") or "")

    @_gs2_builtin(_GS2_BARE, "getplayerlisticons")
    def _bi_getplayerlisticons(self, vm, name, args, obj):
        # Engine builtin with NO surviving implementation in any oracle
        # (windows spec 8.2): only index 0 is behaviorally pinned -- the
        # default/no-icon row, since the weapon draws icons only for
        # playerlisticon > 0 (B/_Playerlist.gs2bc.gs2:1772). A single-entry
        # list is therefore the conservative stub; the full icon-name order
        # is unrecovered and deliberately not guessed.
        return ["Online"]

    @_gs2_builtin(_GS2_BARE, "checksum")
    def _bi_checksum(self, vm, name, args, obj):
        # checksum(lines): the buddy-group lists are checksummed and sent to
        # the lister for verifybuddies. The reference algorithm is
        # unrecovered; any deterministic digest satisfies the only live
        # consumer (our own lister leg ignores it), so this is CRC32 over
        # the flattened text -- flagged inference, do not treat the value as
        # wire-compatible with the official lister.
        import zlib
        arg = args[0] if args else ""
        if isinstance(arg, (list, tuple)):
            text = "\n".join(to_str(item) for item in arg)
        else:
            text = to_str(arg)
        return float(zlib.crc32(text.encode("latin-1", errors="replace")))

    @_gs2_builtin(_GS2_BARE, "findimg")
    def _bi_findimg(self, vm, name, args, obj):
        return self.rt2.find_image(vm, int(to_num(args[0]))) if args else 0.0

    @_gs2_builtin(_GS2_BARE, "enabledefaultcamera")
    def _bi_enabledefaultcamera(self, vm, name, args, obj):
        game = getattr(self.rt2, "game_shell", None)
        if game is not None:
            game._camera_enabled = True
        return 0.0

    @_gs2_builtin(_GS2_BARE, "setzoom")
    def _bi_setzoom(self, vm, name, args, obj):
        game = getattr(self.rt2, "game_shell", None)
        if game is not None and args and getattr(game, "camera", None) is not None:
            game.camera.zoom = to_num(args[0])
        return 0.0

    @_gs2_builtin(_GS2_BARE, "sendtext", "requesttext")
    def _bi_sendtext(self, vm, name, args, obj):
        # Script-facing signature is (type, option, params...) -- the
        # reference engine's binding is "ssX" (FourPlay TInitStatics
        # sendtext) with NO weapon argument: the engine prepends the
        # CALLING weapon's own name as the first wire field, giving
        # "-Serverlist,lister,list,all" / "GraalEngine,irc,login,-"
        # (GServer-v2 PlayerRequestText.cpp parses weapon\ntype\noption\n
        # params...; the C# client's hardcoded flows send the same shape).
        # A top-level {array} param contributes one wire
        # field per element; a NESTED array collapses to one gtokenized
        # field (server side does params[4].guntokenize(), e.g. the
        # IRCBot "!getserverinfo" bundle).
        rt2 = self.rt2
        if rt2.client is not None and args:
            fields = [rt2.wire_weapon_name(vm)] + rt2.wire_text_fields(args)
            rt2.client.send_server_text(name == "requesttext",
                                        "\n".join(fields))
        return 0.0

    @_gs2_builtin(_GS2_BARE, "showgui")
    def _bi_showgui(self, vm, name, args, obj):
        if self.rt2.gui is not None and args:
            self.rt2.gui.show(args[0])
        return 0.0

    @_gs2_builtin(_GS2_BARE, "hidegui")
    def _bi_hidegui(self, vm, name, args, obj):
        if self.rt2.gui is not None and args:
            self.rt2.gui.hide(args[0])
        return 0.0

    @_gs2_builtin(_GS2_BARE, "destroy")
    def _bi_destroy(self, vm, name, args, obj):
        if self.rt2.gui is not None and args:
            self.rt2.gui.destroy(args[0])
        return 0.0

    @_gs2_builtin(_GS2_BARE, "settimer")
    def _bi_settimer(self, vm, name, args, obj):
        # Floor at the reference client's 120Hz update tick; see
        # TIMER_RESOLUTION. settimer(0) CANCELS (same rule as
        # `this.timeout = 0` — see _ThisObject.set and the
        # TScriptSpace::setTimeout citation there).
        rt2 = self.rt2
        v = to_num(args[0]) if args else 0.0
        if v <= _TIMER_CANCEL:
            rt2._timeouts.pop(rt2._timeout_key(vm), None)
            return 0.0
        rt2._timeouts[rt2._timeout_key(vm)] = max(v, TIMER_RESOLUTION)
        return 0.0

    @_gs2_builtin(_GS2_BARE, "join")
    def _bi_join(self, vm, name, args, obj):
        if args:
            self.rt2.join_class(vm, to_str(args[0]))
        return 0.0

    @_gs2_builtin(_GS2_BARE, "echo")
    def _bi_echo(self, vm, name, args, obj):
        rt2 = self.rt2
        text = to_str(args[0]) if args else ""
        rt2.echo_log.append(text)
        if len(rt2.echo_log) > 1000:      # scripts can echo in loops
            del rt2.echo_log[:-500]
        logger.info("GS2 echo: %s", text)
        # echo() output IS an engine-log line -- the rescripted F2 shim maps
        # logtype "echo" into its "game" tab (weapon-Rescripted_-F2LogWindow
        # .txt:102-104) and the official handler dims the pure green.
        rt2.fire_log_message(text, 0.0, 1.0, 0.0, "echo")
        return 0.0

    @_gs2_builtin(_GS2_BARE, "triggeraction")
    def _bi_triggeraction(self, vm, name, args, obj):
        # triggeraction(x, y, action, params...) -> PLI_TRIGGERACTION
        rt2 = self.rt2
        if rt2.client is not None and len(args) >= 3:
            action = ",".join(_csv_flatten(args[2:]))
            rt2.client.triggeraction(action, x=to_num(args[0]), y=to_num(args[1]))
        return 0.0

    @_gs2_builtin(_GS2_BARE, "triggerserver")
    def _bi_triggerserver(self, vm, name, args, obj):
        # triggerserver("gui"/"npc", target, params...): the first arg
        # picks the serverside target class and is NOT sent verbatim.
        # Wire format (GServer-v2 TriggerCommandHandlers.cpp):
        #   triggeraction 0,0,serverside,<weaponname>,<params...>
        #   triggeraction 0,0,servernpc,<npcname>,<params...>
        rt2 = self.rt2
        if rt2.client is not None and len(args) >= 2:
            prefix = ("servernpc" if to_str(args[0]).lower() == "npc"
                      else "serverside")
            action = ",".join([prefix] + _csv_flatten(args[1:]))
            rt2.client.triggeraction(action, x=0.0, y=0.0)
        return 0.0

    @_gs2_builtin(_GS2_BARE, "isobject")
    def _bi_isobject(self, vm, name, args, obj):
        return 1.0 if (args and self.get_object(to_str(args[0])) is not None) else 0.0

    @_gs2_builtin(_GS2_BARE, "findweapon")
    def _bi_findweapon(self, vm, name, args, obj):
        rt2 = self.rt2
        wname = to_str(args[0]) if args else ""
        wvm = rt2.vms["weapon"].get(wname.lower()) if wname else None
        if wvm is None and wname:
            # Client-install weapons: see ClientGS2.fetch_weapon.
            wvm = rt2.fetch_weapon(wname)
        return wvm.this if wvm is not None else 0.0

    @_gs2_builtin(_GS2_BARE, "setani", "setcharani")
    def _bi_setani(self, vm, name, args, obj):
        # setcharani from an NPC script sets the NPC'S OWN animation —
        # piano/sign/furniture NPCs become visible exactly this way
        # (bomber v6 lobby: setcharani("sen_piano"), ("itsasign2")).
        # Route it through the GS1 host, which writes npc['gani'] for the
        # renderer; extra args are gani PARAM tokens, kept comma-joined
        # (render_entities._split_npc_gani splits them back off).
        # setani (v6 player builtin) and weapon-script setcharani keep
        # driving the local player below.
        rt2 = self.rt2
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

    @_gs2_builtin(_GS2_BARE, "timevar2")
    def _bi_timevar2(self, vm, name, args, obj):
        return time.time()

    @_gs2_builtin(_GS2_BARE, "getimgwidth", "getimgheight", "imgwidth",
                  "imgheight")
    def _bi_imgsize(self, vm, name, args, obj):
        # Answered from the downloaded file's header; preloader-style
        # scripts poll this in a wait loop until the download lands, so
        # a miss also (re-)requests the file.
        # imgwidth/imgheight are the LEGACY GS1 spellings (they are in
        # reborn_protocol.gs1's FUNCTIONS table; v6's binding table only
        # has the get* pair, TInitStatics.cpp:2297-2298) -- routed to the
        # same answer here so both engines share one implementation.
        fname = to_str(args[0]) if args else ""
        dims = self.rt2.image_size(fname) if fname else None
        if dims is None:
            return 0.0
        return float(dims[0] if name in ("getimgwidth", "imgwidth")
                     else dims[1])

    # -- v6 C# client platform builtins ---------------------------------
    # Call-site evidence is the v6 bytecode disasms (job a34dbef5 tmp/):
    # -System, -System_Preloader, -Zoom, -warn, npc 10371.

    @_gs2_builtin(_GS2_BARE, "base64encode", "base64decode")
    def _bi_base64(self, vm, name, args, obj):
        import base64
        raw = to_str(args[0]) if args else ""
        try:
            if name == "base64encode":
                return base64.b64encode(
                    raw.encode("latin-1", "replace")).decode("ascii")
            return base64.b64decode(
                raw.encode("ascii", "replace"), validate=False
            ).decode("latin-1", "replace")
        except Exception:
            return ""

    @_gs2_builtin(_GS2_BARE, "savevars")
    def _bi_savevars(self, vm, name, args, obj):
        # savevars(filename): persist the calling script's plain this.
        # members as name=value lines, path-confined under the same
        # server-scoped cache dir (and caps) save_lines enforces.
        if args and vm is not None:
            this = getattr(vm, "this", None)
            members = getattr(this, "_members", {}) or {}
            lines = [f"{key}={to_str(value)}"
                     for key, value in members.items()
                     if not str(key).startswith("_")
                     and not callable(value)
                     and isinstance(value, (str, int, float, bool))]
            self.rt2.save_lines(to_str(args[0]), lines)
        return 0.0

    @_gs2_builtin(_GS2_BARE, "lowercase", "uppercase")
    def _bi_case(self, vm, name, args, obj):
        # Bare engine string builtins (Login -Serverlist_Chat keys its
        # per-channel control names on lowercase(channel):
        # "GlobalChat_ChatList_" @ lowercase(channel)).
        # String unresolved-read rule: see the identity-property note.
        value = to_str(args[0]) if args else ""
        return value.lower() if name == "lowercase" else value.upper()

    @_gs2_builtin(_GS2_BARE, "strequals")
    def _bi_strequals(self, vm, name, args, obj):
        # npc 10371 onPlayerEnters:
        #   if (strequals("blank", player.ani)) setani("eye_bomber_idle0")
        # Result feeds OP_CONV_TO_FLOAT + OP_IF, so it must be 1/0.
        # Case-insensitive, matching the engine's string == convention
        # (VariableCollection lowercases; GS1 string compare ignores case).
        a = to_str(args[0]) if args else ""
        b = to_str(args[1]) if len(args) > 1 else ""
        return 1.0 if a.lower() == b.lower() else 0.0

    # Each name below was confirmed missing at RUNTIME (real compiler, real
    # server, GS2VM.builtins_missing) before being shaped from FourPlay's
    # binding tables.

    @_gs2_builtin(_GS2_BARE, "contains")
    def _bi_contains(self, vm, name, args, obj):
        # contains(source, needle) -- NOT a plain substring test: the
        # engine requires the match to be bounded by a WORD BORDER on
        # both sides (or by the ends of the string), case-insensitively
        # (TInitStatics.cpp:1962-1990, border set vars24 at :283;
        # binding :2287 `{'b', "ss"}`). era's weapongun.txt:236 uses the
        # GS1 strcontains(#s(this.weapon_opposite),Dual), so it is not
        # evidence for this GS2 rule. The live weapon%045Commands.txt:1185
        # calls contains(player.level.name, "mall"), where a substring
        # test would over-match "smallroom".
        source = to_str(args[0]).lower() if args else ""
        needle = to_str(args[1]).lower() if len(args) > 1 else ""
        if not needle:
            return False
        start = 0
        while True:
            found = source.find(needle, start)
            if found < 0:
                return False
            left_ok = found == 0 or source[found - 1] in _WORD_BORDER
            after = found + len(needle)
            right_ok = after >= len(source) or source[after] in _WORD_BORDER
            if left_ok and right_ok:
                return True
            start = after

    @_gs2_builtin(_GS2_BARE, "degtorad", "radtodeg")
    def _bi_angleconv(self, vm, name, args, obj):
        # TInitStatics.cpp:1999/2004, bindings :2289-2290 `{'d', "d"}`.
        # era's particle scripts pass modifier ranges as degtorad(0),
        # degtorad(15); bomber's weaponjoey_test1 spreads shots with
        # degtoRad(22.5).
        import math
        value = to_num(args[0]) if args else 0.0
        return (value * math.pi / 180.0 if name == "degtorad"
                else value * 180.0 / math.pi)

    @_gs2_builtin(_GS2_BARE, "findplayer")
    def _bi_findplayer(self, vm, name, args, obj):
        # findplayer(account) -> that player's object, else null.
        # Reference TInitStatics.cpp:2127 (binding :2301 `{'o', "s"}`)
        # checks the LOCAL player's account first, then the level's
        # other players. Zelda's carry code compares the result's
        # .account against player.account, so the local hit must be the
        # very object `player` resolves to, and a remote hit must be the
        # same per-id object findnearestplayers hands out.
        #
        # The binding coerces its argument to a string, but the live
        # call site feeds it a player OBJECT --
        # `findplayer(players[pls[i]])` in graal-lttp
        # weapon-Player_Movement.txt:91 -- so an object argument is
        # resolved through its `account` member rather than stringified
        # into a repr that could never match.
        rt2 = self.rt2
        wanted = args[0] if args else ""
        if isinstance(wanted, GS2Object):
            wanted = wanted.get("account")
        wanted = to_str(wanted)
        if not wanted:
            return 0.0
        client = rt2.client
        local = getattr(client, "player", None) if client else None
        if local is not None and to_str(
                getattr(local, "account", "")).lower() == wanted.lower():
            return rt2.player_object
        # in-level roster first, then the session-global one -- external
        # players and channel pseudo-players ("irc:#chan") only live in the
        # latter, and -Serverlist_Chat resolves both kinds by account
        seen = set()
        for source in (getattr(client, "players", {}) or {},
                       getattr(client, "all_players", {}) or {}):
            for pid, record in source.items():
                if pid in seen:
                    continue
                seen.add(pid)
                get = record.get if isinstance(record, dict) else (
                    lambda key, default=None: getattr(record, key, default))
                if to_str(get("account", "")).lower() == wanted.lower():
                    return rt2.script_player_object(pid, record)
        return 0.0

    @_gs2_builtin(_GS2_BARE, "cursoron", "cursoroff", "iscursoron")
    def _bi_cursor(self, vm, name, args, obj):
        # GuiCanvas cursor visibility (GuiCanvas.cpp:47-63, bindings
        # :86-88). Called BARE by Login's serverlist when it takes over
        # the screen. No corpus calls cursorOff/isCursorOn, so this can
        # only ever confirm the pointer visible in practice.
        gui = self.rt2.gui
        if gui is None:
            return 0.0
        if name == "iscursoron":
            return 1.0 if gui.cursor_on else 0.0
        gui.set_cursor_on(name == "cursoron")
        return 0.0

    @_gs2_builtin(_GS2_BARE, "keycode")
    def _bi_keycode(self, vm, name, args, obj):
        # keycode("f") -> that key's virtual-key code. NOT a v6 binding
        # (no entry anywhere in quattroplay/src): it is a legacy GS1
        # function that the 2006 era corpus still calls from GS2 blocks
        # (weaponKatana%032Blade.txt:106 etc.), so it resolves here
        # through the SAME implementation the GS1 engine uses rather
        # than a second copy of the keymap.
        #
        # Known limit, not worth working around: those call sites write
        # `keydown2(keycode(f), false)` with a BARE token, which the GS2
        # compiler emits as a read of an undefined variable `f`
        # (verified by compiling it with gs2test) -- the letter is gone
        # before the host is reached, so those particular calls answer
        # 0 here exactly as they do on the reference client.
        fn = _GS1_PURE.get("keycode")
        return fn(None, list(args)) if fn is not None else 0.0

    @_gs2_builtin(_GS2_BARE, "gettextwidth")
    def _bi_gettextwidth(self, vm, name, args, obj):
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
        game = getattr(self.rt2, "game_shell", None)
        if game is not None and hasattr(game, "_showtext_font"):
            try:
                font = game._showtext_font(fontname or "Arial", size,
                                           "b" in style)
                return float(font.size(text)[0])
            except Exception:
                pass
        # headless fallback: mean glyph advance ~0.55em
        return float(len(text)) * size * 0.55

    @_gs2_builtin(_GS2_BARE, "gettextheight")
    def _bi_gettextheight(self, vm, name, args, obj):
        # gettextheight(zoom, font, styles) -> line height in client px,
        # the sibling of gettextwidth above and BY FAR the most-called
        # gap in the live Login corpus (732 calls in one pass): the
        # serverlist screen sizes nearly every label's extent with
        # `extent = { w, gettextheight(scale, "friz", "b") }`.
        zoom = to_num(args[0]) if args else 1.0
        fontname = to_str(args[1]) if len(args) > 1 else ""
        style = to_str(args[2]) if len(args) > 2 else ""
        size = max(8, int(16 * (zoom or 1.0)))
        game = getattr(self.rt2, "game_shell", None)
        if game is not None and hasattr(game, "_showtext_font"):
            try:
                font = game._showtext_font(fontname or "Arial", size,
                                           "b" in style)
                return float(font.get_height())
            except Exception:
                pass
        # headless fallback: the same 1.2em leading pygame's default
        # font reports
        return float(int(size * 1.2))

    @_gs2_builtin(_GS2_BARE, "md5")
    def _bi_md5(self, vm, name, args, obj):
        import hashlib
        raw = to_str(args[0]) if args else ""
        return hashlib.md5(raw.encode("latin-1", "replace")).hexdigest()

    @_gs2_builtin(_GS2_BARE, "extractfilename", "extractfilebase",
                  "extractfileext")
    def _bi_extractfile(self, vm, name, args, obj):
        # Pure path helpers (the engine's own spelling of basename /
        # stem / suffix); both separators, since script-built paths mix
        # them. extractfileext keeps the dot, matching the call sites'
        # `if (extractfileext(f) == ".gani")` comparisons.
        leaf = to_str(args[0]).replace("\\", "/").rsplit("/", 1)[-1] \
            if args else ""
        if name == "extractfilename":
            return leaf
        base, dot, ext = leaf.rpartition(".")
        if not dot:
            return leaf if name == "extractfilebase" else ""
        return base if name == "extractfilebase" else dot + ext

    @_gs2_builtin(_GS2_BARE, "findfiles")
    def _bi_findfiles(self, vm, name, args, obj):
        # findfiles(pattern, recursive) -> array of matching client-install
        # files (TFileScripting.cpp:469 {'o', "si"} -> body :246). This
        # client has no install tree to enumerate (and scripts must not be
        # able to walk the user's disk), so the honest answer is the empty
        # array -- Login's Options lists *.wba window styles with it and
        # falls back to its hardcoded entries when the loop yields nothing.
        return []

    @_gs2_builtin(_GS2_BARE, "adventure_getcontrolbinding",
                  "adventure_setcontrolbinding")
    def _bi_control_binding(self, vm, name, args, obj):
        action = int(to_num(args[0])) if args else 0
        slot = int(to_num(args[1])) if len(args) > 1 else 0
        binding_key = (action, slot)
        if name == "adventure_setcontrolbinding":
            keycode = int(to_num(args[2])) if len(args) > 2 else -1
            self.rt2._control_bindings[binding_key] = keycode
            return 0.0
        keycode = self.rt2._control_bindings.get(binding_key, -1)
        result = GS2Object(name=f"binding:{action}:{slot}")
        result.set("key", float(keycode))
        result.set("keycode", float(keycode))
        if keycode < 0:
            keytext = ""
        else:
            keytext = {
                9: "TAB", 37: "LEFT", 38: "UP", 39: "RIGHT", 40: "DOWN",
            }.get(keycode)
            if keytext is None:
                keytext = (chr(keycode).upper()
                           if 32 <= keycode <= 126 else str(keycode))
        result.set("keytext", keytext)
        return result

    @_gs2_builtin(_GS2_BARE, "adventure_getapplicationfolder")
    def _bi_application_folder(self, vm, name, args, obj):
        return ""

    @_gs2_builtin(_GS2_BARE, "adventure_updatemidivolume",
                  "adventure_updatemp3volume",
                  "adventure_updateradiovolume")
    def _bi_update_volume(self, vm, name, args, obj):
        pref_name = {
            "adventure_updatemidivolume": "$pref::audio::midivolume",
            "adventure_updatemp3volume": "$pref::audio::mp3volume",
            "adventure_updateradiovolume": "$pref::audio::radiovolume",
        }[name]
        value = max(0.0, min(1.0, to_num(
            self.rt2.globals_store.get(pref_name, 1.0))))
        self.rt2._volume_settings[pref_name] = value
        sound_mgr = getattr(getattr(self.rt2, "game_shell", None),
                            "sound_mgr", None)
        if sound_mgr is not None:
            sound_mgr.set_volume(value)
        return 0.0

    @_gs2_builtin(_GS2_BARE, "getresolutionlist")
    def _bi_resolution_list(self, vm, name, args, obj):
        game = getattr(self.rt2, "game_shell", None)
        screen = getattr(game, "screen", None)
        current = screen.get_size() if screen is not None else (800, 600)
        sizes = [(640, 480), (800, 600), (1024, 768), (1280, 720),
                 (1280, 800), (1366, 768), (1920, 1080), current]
        unique = sorted(set((int(w), int(h)) for w, h in sizes))
        return [f"{w}x{h}" for w, h in unique]

    @_gs2_builtin(_GS2_BARE, "getbasepackage", "getupdatepackage")
    def _bi_update_package(self, vm, name, args, obj):
        if name == "getbasepackage":
            package_name = "basepackage.gupd"
        else:
            package_name = to_str(args[0]) if args else ""
        package = self.rt2._update_packages.get(package_name)
        if package is None:
            package = GS2Object(name=package_name)
            package.set("filename", package_name)
            package.set("name", package_name.removesuffix(".gupd"))
            package.set("platform", "any")
            package.set("accounts", "")
            package.set("version", 0.0)
            package.set("packages", [])
            server = GS2Object(name=f"{package_name}:server")
            server.set("filecount", 0.0)
            server.set("filesize", 0.0)
            package.set("server", server)
            package.set("update", lambda *unused: 0.0)
            self.rt2._update_packages[package_name] = package
        return package

    @_gs2_builtin(_GS2_BARE, "fileexists")
    def _bi_fileexists(self, vm, name, args, obj):
        # True only for content this client actually holds: a file the
        # server already sent us, or one in the sprite cache. Never a
        # local-filesystem probe -- a script must not be able to
        # enumerate the user's disk.
        rt2 = self.rt2
        fname = to_str(args[0]) if args else ""
        if not fname:
            return 0.0
        client = rt2.client
        received = getattr(client, "_received_files", {}) or {}
        if fname in received or fname.lower() in {
                str(key).lower() for key in received}:
            return 1.0
        game = getattr(rt2, "game_shell", None)
        sprites = getattr(game, "sprite_mgr", None)
        if sprites is not None and sprites.load_sheet(fname) is not None:
            return 1.0
        return 0.0

    @_gs2_builtin(_GS2_BARE, "pushdialog", "popdialog")
    def _bi_dialog(self, vm, name, args, obj):
        # Torque modal-dialog stack. Headlessly a dialog is just a
        # control raised to the top of the canvas (pushDialog) or
        # hidden again (popDialog) -- Login pushes its "connecting"
        # and error dialogs this way.
        if self.rt2.gui is not None and args:
            if name == "pushdialog":
                ctrl = self.rt2.gui._resolve(args[0])
                if ctrl is not None and ctrl.parent is None:
                    self.rt2.gui.addcontrol(ctrl)
                self.rt2.gui.show(args[0])
            else:
                self.rt2.gui.hide(args[0])
        return 0.0

    @_gs2_builtin(_GS2_BARE, "bringtofront")
    def _bi_bringtofront(self, vm, name, args, obj):
        if self.rt2.gui is not None and args:
            ctrl = self.rt2.gui._resolve(args[0])
            if ctrl is not None:
                self.rt2.gui.bring_to_front(ctrl)
        return 0.0

    @_gs2_builtin(_GS2_BARE, "isfullscreenmode")
    def _bi_isfullscreenmode(self, vm, name, args, obj):
        game = getattr(self.rt2, "game_shell", None)
        return 1.0 if getattr(game, "fullscreen", False) else 0.0

    @_gs2_builtin(_GS2_BARE, "scheduleevent")
    def _bi_scheduleevent(self, vm, name, args, obj):
        if vm is not None and len(args) >= 2:
            self.rt2.schedule_event(vm, to_num(args[0]), to_str(args[1]),
                                    list(args[2:]))
        return 0.0

    @_gs2_builtin(_GS2_BARE, "cancelevents")
    def _bi_cancelevents(self, vm, name, args, obj):
        # cancelevents(["EventName"]): drop this script's pending
        # scheduled events (all of them when no name is given).
        if vm is not None:
            self.rt2.cancel_events(vm, to_str(args[0]) if args else "")
        return 0.0

    @_gs2_builtin(_GS2_BARE, "findobject")
    def _bi_findobject(self, vm, name, args, obj):
        # findobject(name) -> the named engine object / GUI control, or
        # 0.0. Same registry every bare-name reference resolves through
        # (get_object); Login Mobile's gui_scaler and -LoginScreen look
        # their controls up this way instead of by bare name.
        found = self.get_object(to_str(args[0])) if args else None
        return found if found is not None else 0.0

    @_gs2_builtin(_GS2_BARE, "loadvars", "loadvarsfromarray")
    def _bi_loadvars(self, vm, name, args, obj):
        # The inverse of savevars(): repopulate the calling script's
        # this. members from `name=value` lines -- either from this
        # client's own server-scoped cache (loadvars, the only place
        # savevars is allowed to write) or straight from an array.
        this = getattr(vm, "this", None) if vm is not None else None
        if this is None:
            return 0.0
        if name == "loadvarsfromarray":
            lines = args[0] if args and isinstance(args[0], list) else []
        else:
            lines = self.rt2.load_lines(to_str(args[0]) if args else "")
        for line in lines:
            key, sep, value = to_str(line).partition("=")
            if sep and key.strip():
                this.set(key.strip(), value)
        return 0.0

    @_gs2_builtin(_GS2_BARE, "getscalefactor")
    def _bi_getscalefactor(self, vm, name, args, obj):
        # -Zoom onCreated: this.maxscale = getScaleFactor() + 1, and the
        # desktop default for client.mobile_smoothzoom_* -> 1 on PC
        # (maxscale 2 matches -System's own scalefactor = 2).
        return 1.0

    @_gs2_builtin(_GS2_BARE, "getplatform")
    def _bi_getplatform(self, vm, name, args, obj):
        # Same value player.platform reports -- the reference reads both
        # off TIdentification::platformname (TInitStatics.cpp:2796-2801
        # binding :4214 `{'s', ""}`, and TPlayer.cpp:663). It used to
        # share the 0.0 group below, which made `getplatform() ==
        # "android"` compare EQUAL (0 == strtofloat("android")) and sent
        # Login Mobile's -Adventure down the handset branch.
        return PLATFORM_NAME

    @_gs2_builtin(_GS2_BARE, "getgamesubversion", "getpremiumoption",
                  "fileupdate")
    def _bi_zero(self, vm, name, args, obj):
        # 0.0 is the TRUTHFUL answer (we hold no premium option). Deliberately NOT in
        # `stubbed`: game_tester/server_crawl.py KNOWN_UNSUPPORTED_CALLS is the single
        # source of truth for the boundary.
        return 0.0

    @_gs2_builtin(_GS2_BARE, "getdevicemodel")
    def _bi_getdevicemodel(self, vm, name, args, obj):
        # -Zoom uses it only as a client-flag name suffix
        # (client.mobile_smoothzoom_<model>): any stable, benign
        # desktop-ish token works.
        return "PC"

    @_gs2_builtin(_GS2_BARE, "getiphonemodel", "getandroiddevicemodel")
    def _bi_gethandsetmodel(self, vm, name, args, obj):
        # Login Mobile's gui_scaler picks its layout scale off the
        # handset model. We are not one -- the empty string is the
        # truthful answer and lands the class on its desktop branch.
        # It is also literally what the reference client returns off
        # the handset: scriptfun_android_getandroiddevicemodel
        # (FourPlay TInitStatics.cpp:5610, binding :5979 `{'s', ""}`)
        # constructs an empty TString and returns it, with no JNI call
        # at all -- unlike its neighbours in that file, which do go
        # through javaenvironment. Both live call sites take .lower()
        # or compare the result, never branch on emptiness
        # (graal-loginserver-mobile weapon-Adventure.txt getDeviceModel,
        # graal-bomber-gs2 scripts/utility_device.txt:19).
        return ""

    @_gs2_builtin(_GS2_BARE, "gameobject::find",
                  "object::findanyobjectbytype")
    def _bi_engine_find(self, vm, name, args, obj):
        # -System: cam = object::findanyobjectbytype(type::camera); then
        # cam.orthographic = true; cam.orthographicsize = 120; -- needs a
        # writable object with stable identity. -System_Preloader:
        # GameObject::Find("Logger") heads a discarded chain -- needs
        # non-null traversal. Never polled in a retry loop.
        key = to_str(args[0]) if args else ""
        return _engine_object(self.rt2, f"{name}:{key}".lower())

    @_gs2_builtin(_GS2_BARE, "quattro::transformextensions::getcomponents")
    def _bi_engine_components(self, vm, name, args, obj):
        # -System: cams = ...getcomponents(Type::Camera) -- assigned and
        # never read again; return a one-element list for shape-safety.
        key = to_str(args[0]) if args else ""
        return [_engine_object(self.rt2, f"component:{key}".lower())]

    @_gs2_builtin(_GS2_BARE, "setframetick", "adventure_setframetick",
                  "adventure_getframetick", "switchopengldevicescale",
                  "setretinadisplaynoantialias", "switchtodirectx",
                  "adventure_setcheatwindows")
    def _bi_platform_inert(self, vm, name, args, obj):
        # Frame pacing / GL-scale / retina / renderer-backend / staff
        # cheat-window toggles for the C# client's renderer (the staff
        # ones arrive as `quattro::debugtools::*`, matched by prefix in
        # _call_bare_builtin). Every observed call discards the result
        # (OP_INDEX_DEC at each site in -System, -System_Preloader,
        # -Zoom, npc 10371, and the live Login -Serverlist) -- inert by
        # design.
        return 0.0

    @_gs2_builtin(_GS2_BARE, "adventure_invokekeyevent")
    def _bi_invokekeyevent(self, vm, name, args, obj):
        # Synthesising key events on a server script's say-so is an
        # input-spoofing primitive, not a rendering feature: the script
        # could drive any bound action (including chat and movement) as
        # if the user had typed it. Inert BY POLICY. Live Login Mobile
        # uses it only to dismiss its own soft keyboard.
        rt2 = self.rt2
        if name not in rt2._policy_stub_logged:
            rt2._policy_stub_logged.add(name)
            logger.info("GS2 %s(): inert stub (no synthetic input by "
                        "policy)", name)
        return 0.0


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
        self.globals_store: Dict[str, Any] = _GlobalsStore(self)
        #: selectedsword's backing store: pyReborn has one sword, so the
        #: reference's separate weapon-array index has nowhere else to live.
        self._selected_sword = -1
        self.player_object = _PlayerObject(self)
        self.level_object = _LevelObject(self)
        self._flag_scopes: Dict[str, GS2Object] = {}
        # onPlayerEnters bookkeeping: which VMs got it for the current level
        self._entered_level: Optional[str] = None
        self._entered_vms: set = set()
        self._tiles_view_key = None   # (world_w, world_h) the view was built for
        self._tiles_view = None
        self._weapons_signature = None
        self._weapons_view = []
        # findnearestplayers() entries, kept per player id so the objects
        # scripts hold on to keep their identity (see script_player_object)
        self._script_players: Dict[Any, GS2Object] = {}
        # session-local PM log per player id (see log_pm_history)
        self.pm_history: Dict[Any, List[tuple]] = {}
        # reentrancy guard: an onLogMessage handler that itself errors/echoes
        # must not recurse into another onLogMessage
        self._in_log_message = False
        # GUI-controls tree (showgui/GuiControl); None when pygame isn't
        # installed (headless callers, e.g. game_tester's GameBot).
        self.gui = GS2GuiManager(rt2=self) if GS2GuiManager is not None else None
        if self.gui is not None:
            options_dialog = self.gui.register_native_control(
                "GuiWindowCtrl", "OptionsDlg2D")
            options_dialog.set_visible(False)
        self.game_shell = None
        self._control_bindings: Dict[tuple, int] = {
            (0, 0): 38, (1, 0): 37, (2, 0): 40, (3, 0): 39,
            (4, 0): 68, (5, 0): 83, (6, 0): 65, (7, 0): 77,
            (8, 0): 9, (9, 0): 81, (10, 0): 80,
        }
        self._volume_settings: Dict[str, float] = {}
        self._update_packages: Dict[str, GS2Object] = {}
        self.echo_log: List[str] = []
        self._timeouts: Dict[tuple, float] = {}   # (kind, key) -> seconds left
        # scheduleevent() arms: [{key, left, event, params}] -- see
        # schedule_event/_process_scheduled_events
        self._scheduled: List[dict] = []
        self._pending_joins: Dict[str, List[GS2VM]] = {}
        self._prev_bytecode_cb = None
        self._prev_server_text_cb = None
        # Bytecode that arrived inside the client's packet loop, waiting to
        # be loaded/run from the game loop (see _on_bytecode).
        self._pending_bytecode: List[tuple] = []
        # findweapon() names the server did not answer a PLI_UPDATESCRIPT
        # for (see fetch_weapon) -- never re-stall on them this session.
        self._findweapon_missing: set = set()
        # policy-inert builtins already logged once (requesturl etc.)
        self._policy_stub_logged: set = set()
        self._sleeping = False                    # a script sleep() is pumping update()
        self._coros: List[dict] = []
        self._active_coro_keys: set = set()
        self._pending_events: Dict[tuple, List[tuple]] = {}
        self._timer_accumulator = 0.0
        # Script definitions are shared; entries in vms["gani"] are the
        # independent hidden objects attached to individual wearers.
        self._gani_classes: Dict[str, GS2VM] = {}
        self._gani_worn: Dict[tuple, tuple] = {}
        self._gani_this: Dict[tuple, _GaniThisObject] = {}
        self._gani_created: set = set()
        self._gani_wearer_identity: Dict[tuple, str] = {}
        self._requested_ganis: set = set()
        self._executing_vm: Optional[GS2VM] = None
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

    def load_lines(self, filename: str) -> List[str]:
        """Read back lines this client's own save_lines/savevars wrote.

        Same server-scoped cache directory and same leaf-name confinement,
        so a script can only ever read what it stored here -- never an
        arbitrary path. Missing/unreadable file -> empty list."""
        from .prefs import config_dir
        import hashlib
        server = to_str(getattr(self.client, "server_name", "") or
                        getattr(self.client, "host", "") or "default")
        scope = hashlib.sha256(server.encode("utf-8")).hexdigest()[:16]
        leaf = Path(str(filename).replace("\\", "/")).name
        if not leaf or leaf in (".", "..") or "\x00" in leaf:
            return []
        target = config_dir() / "client-cache" / scope / leaf
        try:
            if target.stat().st_size > SAVE_LINES_CACHE_MAX_BYTES:
                return []
            return target.read_text(encoding="utf-8").splitlines()
        except (OSError, ValueError, UnicodeDecodeError):
            return []

    def wire_weapon_name(self, vm: Optional[GS2VM]) -> str:
        """The calling script's wire identity for sendtext/requesttext: the
        weapon's original-case name, or "GraalEngine" for engine-originated
        sends (the reference client's convention -- see call_builtin's
        sendtext comment). Joined-class instances resolve to their joiner."""
        key = self._timeout_key(vm) if vm is not None else None
        if key is not None and key[0] == "weapon":
            wvm = self.vms["weapon"].get(key[1])
            name = getattr(wvm, "name", "") if wvm is not None else ""
            if ":" in name:
                return name.split(":", 1)[1]
            if name:
                return name
            return to_str(key[1])
        return "GraalEngine"

    @staticmethod
    def wire_text_fields(args) -> List[str]:
        """Flatten sendtext/requesttext script args to wire fields: scalars
        one field each, a top-level array one field per element, an array
        nested inside that one gtokenized field (round-tripping the server's
        params[i].guntokenize())."""
        from .packets import _gtokenize

        def field(value) -> str:
            if isinstance(value, (list, tuple)):
                return _gtokenize("\n".join(field(item) for item in value))
            return to_str(value)

        fields: List[str] = []
        for arg in args:
            if isinstance(arg, (list, tuple)):
                fields.extend(field(item) for item in arg)
            else:
                fields.append(to_str(arg))
        return fields

    def player_positions(self) -> list:
        """(x, y) per entry of the `players[]` array, in ITS order.

        Shares one construction order with player_list_objects() so an index
        from nearest_player_indices() always addresses the same entry the
        script then reads out of players[]."""
        client = self.client
        if client is None:
            return []
        local = getattr(client, "player", None)
        found = [(to_num(getattr(client, "x", getattr(local, "x", 0)) or 0),
                  to_num(getattr(client, "y", getattr(local, "y", 0)) or 0))]
        for record in (getattr(client, "players", {}) or {}).values():
            get = record.get if isinstance(record, dict) else (
                lambda key, default=None: getattr(record, key, default))
            found.append((to_num(get("x", 0)), to_num(get("y", 0))))
        return found

    def nearest_player_indices(self, x: float, y: float) -> list:
        """getnearestplayers(x, y) -> `players[]` INDICES, nearest first.

        Deliberately NOT the same payload as findnearestplayers(), which
        returns the player OBJECTS: the reference sorts one copy of the
        player list by distance and then emits
        `players->indexOf(entry)` per entry as a float array
        (quattroplay TInitStatics.cpp:2067-2086 vs :2088-2098). The live
        call site only works that way round -- graal-lttp
        weapon-Player_Movement.txt:88-91 RenderNicks does
        `temp.pls = getnearestplayers(...); temp.pl = findplayer(players[
        pls[i]]);`, i.e. it INDEXES players[] with what it gets back.

        The LOCAL player is index 0 and is part of the ranking: RenderNicks
        draws one caption per returned entry and branches on
        `pl.account != player.account` to decide whether to show our own,
        which is unreachable if we are missing from the list.

        Distance is measured from each player's stand point (+1.5, +2), the
        pair the reference's comparator adds to every player before
        comparing (same offsets find_nearest_players uses)."""
        positions = self.player_positions()
        ranked = sorted(
            range(len(positions)),
            key=lambda i: ((positions[i][0] + 1.5 - x) ** 2
                           + (positions[i][1] + 2.0 - y) ** 2))
        return [float(i) for i in ranked]

    #: findnearestplayers() entry members -> (remote-player record key,
    #: default). The record keys are the ones packets.parse_other_player
    #: writes. Content reads the combat fields off these objects, not just
    #: the identity ones -- Zelda's CheckHurt uses .ani, .dir, .swordpower,
    #: .account, .x and .y.
    _SCRIPT_PLAYER_MEMBERS = (
        ("account", "account", ""), ("nick", "nickname", ""),
        ("nickname", "nickname", ""), ("chat", "chat", ""),
        ("level", "level", ""), ("swordimg", "sword_image", ""),
        ("shieldimg", "shield_image", ""), ("headimg", "head_image", ""),
        ("bodyimg", "body_image", ""),
        ("x", "x", 0.0), ("y", "y", 0.0), ("dir", "direction", 0.0),
        ("sprite", "sprite", 0.0), ("hearts", "hearts", 0.0),
        ("fullhearts", "max_hearts", 0.0), ("ap", "ap", 0.0),
        ("mp", "mp", 0.0), ("swordpower", "sword_power", 0.0),
        ("shieldpower", "shield_power", 0.0),
        ("glovepower", "glove_power", 0.0),
    )

    def script_player_object(self, player_id, record) -> GS2Object:
        """The script-facing object for ONE remote player, stable per id.

        Identity matters: content compares entries against each other and
        against `player` (Login's -Serverlist_Observer picks a follow target
        with `if (temp.pl != player)`), and gs2_compare's object/object rule
        is pointer identity -- so the same player must hand back the same
        object every call, refreshed in place. The -Playerlist weapon also
        WRITES onto these objects (isbuddy/isignored/playerlisticon) and the
        PM machinery stashes the waiting message here, so the refresh below
        only rewrites wire-sourced members and leaves the sticky ones alone.
        """
        cache = self._script_players
        item = cache.get(player_id)
        get = record.get if isinstance(record, dict) else (
            lambda key, default=None: getattr(record, key, default))
        if item is None:
            item = cache[player_id] = GS2Object(name=f"player:{player_id}")
            # Indexed views, bound to the id rather than to this particular
            # record dict: they resolve the live record on every access, so
            # they keep working after client.players[id] is re-created.
            # Zelda's lift code reads BOTH off a remote player object --
            # `pl.attr[3] == player.account` (weapon-Player_Movement.txt:858)
            # and `pl.colors[0..4]` (:204-208).
            item.set("attr", _PlayerAttrObject(self, player_id))
            item.set("colors", _PlayerColorsObject(self, player_id))
            item.set("color", item.get("colors"))
            self._seed_roster_surface(item, player_id)
        else:
            # Id REUSE detection: both servers hand a freed id to the next
            # login immediately, and the wrapper cache deliberately outlives
            # a logout (roster_player_removed keeps it around so waiting-PM
            # text survives, the deletedplayers analog). A refresh whose
            # account does not match the cached one -- or that follows a
            # logout on an id whose wrapper never learned an account -- is a
            # NEW person on an old wrapper: clear the prior occupant's
            # sticky state or Bob logs in wearing Alice's PM badge, buddy
            # flag and PM history. A same-account reconnect (and a
            # pm_received placeholder wrapper that later learns its account)
            # keeps its state in place.
            incoming = to_str(get("account", "") or "")
            if incoming:
                cached = to_str(item.get("account") or "")
                if incoming != cached and (
                        cached or to_num(item.get("isloggedin")) == 0.0):
                    self._forget_prior_occupant(item, player_id)
        item.set("id", player_id)
        for member, key, default in self._SCRIPT_PLAYER_MEMBERS:
            value = get(key, default)
            item.set(member, default if value is None else value)
        item.set("ani", _NameObject(to_str(get("ani", "") or get("gani", "") or "")))
        # Derived, never carried on the wire (see _guild_from_nick).
        # String unresolved-read rule: see the identity-property note.
        guild = _guild_from_nick(get("nickname", ""))
        item.set("guild", guild)
        # The OFFICIAL spelling of the level (TServerPlayerProperties.cpp:573);
        # `level` above is our own extension, kept for the same reason
        # _PlayerObject keeps it.
        item.set("levelname", to_str(get("level", "")))
        # PLAYERLISTCATEGORY (prop 81) bit-flags -> the four roster booleans
        # (FourPlay TServerPlayer.cpp:1940-1954). External additionally
        # forces isadmin false (:1949-1951); otherwise isadmin is the
        # staff-guild rule over the nick-derived guild (TServerPlayer.cpp:
        # 342-347).
        flags = int(to_num(get("playerlist_flags", 0) or 0))
        item.set("isexternal", 1.0 if flags & 1 else 0.0)
        item.set("ischannel", 1.0 if flags & 2 else 0.0)
        item.set("ischanneluser", 1.0 if flags & 4 else 0.0)
        item.set("ischannelopen", 1.0 if flags & 8 else 0.0)
        staff = getattr(self.client, "staff_guilds", None) if self.client else None
        item.set("isadmin",
                 0.0 if flags & 1 else
                 (1.0 if _is_admin_guild(guild, staff) else 0.0))
        item.set("isloggedin", 1.0)
        # Live sources for two members the seed loop used to blank: prop 82
        # and the OSTYPE prop.
        item.set("communityname", to_str(get("communityname", "") or ""))
        item.set("platform", to_str(get("os_type", "") or ""))
        for member in _REMOTE_PLAYER_EMPTY_STRINGS:
            if not item.has(member):
                # seeded once, not per refresh: there is no live source to
                # refresh these FROM, so re-setting would only clobber a
                # script's own write into the writable ones
                item.set(member, "")
        return item

    def _seed_roster_surface(self, item: GS2Object, player_id) -> None:
        """One-time members of a remote-player wrapper: the PM/profile
        method surface the -Playerlist / -Serverlist_Chat weapons call, and
        the script-writable slots a refresh must never clobber. Everything
        here is CLAIMED even when inert -- an unanswered name reads Number
        0.0 and equals every non-numeric string it is compared against."""
        for member in _REMOTE_PLAYER_STICKY_NUMBERS:
            item.set(member, 0.0)
        # `person.gmap.name` (tab-2 hint text) -- no per-player gmap source,
        # so an empty-named object keeps the read chain object-shaped.
        item.set("gmap", _NameObject(""))
        # pmswaiting() = message non-empty; ismasspm()/isguildpm() = prefix
        # tests (TServerPlayerProperties.cpp:241-254).
        item.set("pmswaiting",
                 lambda *a, _p=item: bool(to_str(_p.get("message"))))
        item.set("ismasspm",
                 lambda *a, _p=item:
                 to_str(_p.get("message")).startswith("Mass message:"))
        item.set("isguildpm",
                 lambda *a, _p=item:
                 to_str(_p.get("message")).startswith("Guild message:"))

        # showprofile() fires the universe event -Playerlist_Profile catches
        # (TServerPlayerProperties.cpp:259-263).
        def _showprofile(*a, _p=item):
            self.trigger_event("onOpenProfileWindow", _p)
            return 0.0
        item.set("showprofile", _showprofile)
        # "use the native PM window if this build has one": the mobile
        # reference answers false (:256-257) and every caller falls back to
        # the scripted windows -- exactly what we want.
        item.set("openexternalpm", lambda *a: False)
        item.set("openexternalhistory", lambda *a: False)

    def _forget_prior_occupant(self, item: GS2Object, player_id) -> None:
        """A reused player id's wrapper is about to represent a DIFFERENT
        person (see the reuse detection in script_player_object): reset the
        sticky script/PM state to its seeded defaults and drop the per-id PM
        history. The wire-sourced members are rewritten by the refresh that
        follows; the attr/colors views and the PM method surface are id-
        bound, not occupant-bound, so they stay."""
        for member in _REMOTE_PLAYER_STICKY_NUMBERS:
            item.set(member, 0.0)
        for member in _REMOTE_PLAYER_EMPTY_STRINGS:
            item.set(member, "")
        self.pm_history.pop(player_id, None)

    def find_nearest_players(self, x: float, y: float) -> list:
        """findnearestplayers(x, y) -> EVERY player object, nearest first.

        Deliberately NOT an alias of getnearestplayers(): the reference
        engine sorts the same list both ways but getnearestplayers returns
        players[] INDICES while findnearestplayers returns the player
        objects themselves (quattroplay TInitStatics.cpp:2067 vs :2088).

        The local player is part of the list -- both live call sites filter
        themselves back out (Zelda's CheckHurt skips `i.account !=
        player.account`, the Login observer skips `pl != player`), which
        only works if we hand back the very object those comparisons expect,
        so our entry IS self.player_object. Distance is measured from each
        player's stand point (+1.5, +2 -- the offsets the reference's
        comparator adds to every player before comparing, the same pair
        TClient::sendPlayerHurt uses)."""
        client = self.client
        if client is None:
            return []
        found = []
        local = getattr(client, "player", None)
        if local is not None:
            dx = to_num(getattr(client, "x", getattr(local, "x", 0))) + 1.5 - x
            dy = to_num(getattr(client, "y", getattr(local, "y", 0))) + 2.0 - y
            found.append(((dx * dx + dy * dy) ** 0.5, self.player_object))
        live = getattr(client, "players", {}) or {}
        # prune wrappers only when the id is gone from BOTH rosters: a
        # level-leaver stays in allplayers (and scripts keep state -- waiting
        # PM text, buddy flags -- on the wrapper)
        roster = getattr(client, "all_players", {}) or {}
        for stale in [key for key in self._script_players
                      if key not in live and key not in roster]:
            del self._script_players[stale]
        for player_id, record in live.items():
            item = self.script_player_object(player_id, record)
            dx = to_num(item.get("x")) + 1.5 - x
            dy = to_num(item.get("y")) + 2.0 - y
            found.append(((dx * dx + dy * dy) ** 0.5, item))
        return [item for _, item in sorted(found, key=lambda pair: pair[0])]

    def string_keys(self, prefix: str) -> List[str]:
        """getstringkeys(prefix) -> the matching flag names, prefix stripped.

        Reference (quattroplay TInitStatics.cpp:2218): walk the player's own
        var collection, keep the names starting with `prefix`, DROP the ones
        holding an empty string or 0, strip the prefix off what is left and
        sort it. The player's vars are the client./clientr. flag namespace,
        which is what an unprefixed prefix searches here; a leading scope
        token selects that scope's store instead. Our stores key flags
        WITHOUT the wire prefix (gs1_client's _PlayerFlagScope /
        _ServerFlagScope), so the token is stripped from the search prefix
        as well -- Zelda's addMinorFlag asks for "clientr.minorflags_" and
        means the clientr flags named minorflags_*."""
        shared = self.gs1._shared if self.gs1 is not None else {}
        text = to_str(prefix)
        lowered = text.lower()
        store, inner = shared.get("client", {}), text
        for token in ("clientr.", "client.", "serverr.", "server."):
            if lowered.startswith(token):
                store = shared.get("server" if token.startswith("server")
                                   else "client", {})
                # serverr flags live in the server store under their wire
                # prefix (see _FlagScopeObject), client/clientr share one
                # unprefixed player store.
                inner = (token if token == "serverr." else "") + text[len(token):]
                break
        keep = []
        for key, value in list(store.items()):
            name = str(key)
            if not name.lower().startswith(inner.lower()):
                continue
            if not (value if isinstance(value, str) else to_num(value)):
                continue
            keep.append(name[len(inner):])
        return sorted(keep, key=str.casefold)

    def call_stack(self, vm: Optional[GS2VM]) -> list:
        """getcallstack() -> the script call stack, outermost FIRST.

        Entry shape (quattroplay TCallStackEntryProperties.cpp plus g2k1's
        weaponParticleEditor dumpCallStack): `.name` is the frame's function
        name and `.scriptcallobject` is the object whose script declared it,
        which is why content indexes `stack[stack.size()-2].scriptcallobject
        .name` for its immediate CALLER (Zelda's destroy() guards).

        The shared VM keeps its frames on the Python stack and publishes no
        frame list, so there is nothing here to enumerate -- and neither has
        the reference binding this port targets, which returns an EMPTY
        array (TInitStatics.cpp:2242, makeArrayVar with nothing added to
        it). Both live call sites degrade to an empty caller name rather
        than misbehaving. If the VM grows a real stack (a `call_stack` list
        of (vm, function name) pairs), it lights up here with no change."""
        entries = []
        for frame in (getattr(vm, "call_stack", None) or []):
            try:
                frame_vm, function = frame
            except (TypeError, ValueError):
                continue
            entry = GS2Object(name=to_str(function))
            entry.set("name", to_str(function))
            entry.set("scriptcallobject", getattr(frame_vm, "this", None))
            entries.append(entry)
        return entries

    def owner_vm(self, vm: GS2VM) -> GS2VM:
        """The top-level weapon/npc VM a (possibly joined-class) VM acts for."""
        kind, key = self._timeout_key(vm)
        return self.vms.get(kind, {}).get(key, vm)

    def is_in_class(self, vm: GS2VM, classname: str) -> bool:
        """isinclass("name"): has the calling script joined that class?

        A property of the OBJECT, not of the running code: Zelda's
        class:gui_builder built() calls it right after this.leave(
        "gui_builder") -- from inside gui_builder itself -- and echoes the
        result to show the class is gone, so the answer comes from the
        joiner's class list alone."""
        cname = to_str(classname).lower()
        return any(getattr(joined, "_gs2_key", None) == cname
                   for joined in self.owner_vm(vm).joined)

    def leave_class(self, vm: GS2VM, classname: str) -> bool:
        """leave("classname"): the inverse of join(). Returns whether the
        class was attached. Safe to call from inside the class's own code
        (Zelda's gui_builder.built() does exactly that) -- the running
        instance stays alive for the rest of the call, it just stops being
        reachable from the joiner."""
        cname = to_str(classname).lower()
        owner = self.owner_vm(vm)
        remaining = [joined for joined in owner.joined
                     if getattr(joined, "_gs2_key", None) != cname]
        left = len(remaining) != len(owner.joined)
        owner.joined = remaining
        waiting = self._pending_joins.get(cname)
        if waiting:
            self._pending_joins[cname] = [joiner for joiner in waiting
                                          if joiner is not owner]
            if not self._pending_joins[cname]:
                del self._pending_joins[cname]
        return left

    def roster_record(self, player_id) -> Optional[dict]:
        """The freshest record for an id: the in-level record when the
        player shares our level, else the session-global allplayers one."""
        client = self.client
        if client is None:
            return None
        record = (getattr(client, "players", {}) or {}).get(player_id)
        if record is not None:
            return record
        return (getattr(client, "all_players", {}) or {}).get(player_id)

    def roster_wrapper(self, player_id) -> Optional[GS2Object]:
        """The persistent per-id wrapper for a KNOWN player, else None."""
        record = self.roster_record(player_id)
        if record is None:
            return None
        return self.script_player_object(player_id, record)

    def player_by_id(self, player_id: int):
        """Return the player object with this id (local or remote), else 0.0.

        Hands back the PERSISTENT wrappers -- the local player is the very
        object `player` resolves to and a remote id is the same per-id
        object findnearestplayers/players[] serve, because the -Playerlist
        weapon stamps state onto whatever findplayerbyid returns and expects
        to see it again."""
        client = self.client
        if client is None:
            return 0.0
        local = getattr(client, "player", None)
        if local is not None and getattr(local, "id", None) == player_id:
            return self.player_object
        item = self.roster_wrapper(player_id)
        return item if item is not None else 0.0

    def player_list_objects(self) -> list:
        """`players[]`: the local player first (the reference's own layout),
        then the in-level roster as persistent per-id wrappers. Order is
        shared with player_positions()."""
        client = self.client
        if client is None:
            return []
        result = [self.player_object]
        for player_id, record in (getattr(client, "players", {}) or {}).items():
            result.append(self.script_player_object(player_id, record))
        return result

    def all_player_objects(self) -> list:
        """`allplayers`: every player id seen this session (incl. externals
        and channel pseudo-players), as persistent wrappers -- the engine's
        global list distinct from the in-level `players`
        (TGameEnvironment::allplayers, fed by setotherplayerprops only, so
        the LOCAL player is not in it). Falls back to the in-level roster
        for embedders whose client has no all_players store."""
        client = self.client
        if client is None:
            return []
        roster = getattr(client, "all_players", None)
        if roster is None:
            roster = getattr(client, "players", {}) or {}
        seen = []
        for player_id in list(roster):
            record = self.roster_record(player_id)
            if record is not None:
                seen.append(self.script_player_object(player_id, record))
        return seen

    # -- roster/universe event feed (called from the packet handlers via
    # client.gs2_host; see handlers/entities.py and handlers/chat.py) -------

    def roster_player_added(self, player_id) -> None:
        """onPlayerLogin(other, id) -- FourPlay TClient.cpp:3107-3108."""
        try:
            item = self.roster_wrapper(player_id)
            if item is not None:
                self.trigger_event("onPlayerLogin", item, float(player_id))
        except Exception:
            logger.exception("GS2 roster onPlayerLogin failed")

    def roster_player_changed(self, player_id) -> None:
        """onPlayerChanges(other, id) -- fired when a roster-relevant prop
        updated (TServerPlayer.cpp:1981-1982 via playerListChanged)."""
        try:
            item = self.roster_wrapper(player_id)
            if item is not None:
                self.trigger_event("onPlayerChanges", item, float(player_id))
        except Exception:
            logger.exception("GS2 roster onPlayerChanges failed")

    def roster_player_removed(self, player_id, record) -> None:
        """onPlayerLogout(other, id) -- FourPlay TClient.cpp:3123-3124. The
        wrapper stays cached (the reference's deletedplayers analog) so any
        waiting-PM text survives until the id is pruned; id-100000
        resurrection of departed PM senders is deliberately NOT modelled."""
        try:
            item = self.script_player_object(player_id, record or {})
            item.set("isloggedin", 0.0)
            self.trigger_event("onPlayerLogout", item, float(player_id))
        except Exception:
            logger.exception("GS2 roster onPlayerLogout failed")

    def pm_received(self, from_id, msg_type: str, message: str) -> None:
        """PLO_PRIVATEMESSAGE -> stash the waiting text on the sender's
        wrapper, log it to the PM history, then fire universe.onPM(other).
        `message` keeps its "Private message:"/"Mass message:" type line as
        a prefix so ismasspm()/isguildpm() prefix-test truthfully (the fire
        site is absent from the mobile reference -- semantics reconstructed
        from pmswaiting() + the relog-preservation code, flagged inference).
        """
        try:
            item = self.roster_wrapper(from_id)
            if item is None:
                # PM from an id we never saw props for: serve a minimal
                # wrapper so the event still carries an object (no roster
                # entry -- it will not appear in allplayers).
                item = self.script_player_object(from_id, {})
            text = to_str(message)
            mtype = to_str(msg_type)
            full = f"{mtype}\n{text}" if mtype else text
            item.set("message", full)
            self.log_pm_history(from_id, "in", text)
            self.trigger_event("onPM", item)
        except Exception:
            logger.exception("GS2 onPM dispatch failed")

    def log_pm_history(self, player_id, direction: str, text: str) -> None:
        """Session-local PM log backing GuiPMHistoryCtrl.showHistory().
        In-memory only: the reference's on-disk log (gated by the weapon's
        options.dontsavepms) is deliberately not persisted."""
        log = self.pm_history.setdefault(player_id, [])
        log.append((direction, to_str(text)))
        if len(log) > 200:
            del log[:-100]

    def weapon_list_objects(self) -> list:
        weapons = getattr(self.client, "weapons", None) if self.client else None
        weapons = weapons if isinstance(weapons, dict) else {}
        signature = tuple(
            (name, record.get("image", "") if isinstance(record, dict) else "")
            for name, record in weapons.items()
        )
        if signature != self._weapons_signature:
            self._weapons_signature = signature
            result = []
            for name, image in signature:
                item = GS2Object(name="weapon")
                item.set("name", to_str(name))
                item.set("image", to_str(image))
                result.append(item)
            self._weapons_view = result
        # The client table exposes the active player's weapon array read-only.
        # FourPlay/quattroplay/src/TInitStatics.cpp:2700-2703,2784;
        # weapon-Player_Movement.txt:473.
        return self._weapons_view

    def level_object_positions(self, probe: str) -> list:
        """(x, y) per entry of the list `level.test<kind>` indexes, in the
        order the client stores it -- signs are per level, the other three
        are already scoped to the current one (client.py clears them on every
        level change)."""
        client = self.client
        if client is None:
            return []
        if probe == "testsign":
            level = getattr(client, "_current_level_name", "") or ""
            return list((getattr(client, "signs", {}) or {}).get(level, {}))
        if probe == "testitem":
            return list(getattr(client, "items", {}) or {})
        if probe == "testbomb":
            return list(getattr(client, "bombs", {}) or {})
        return [(to_num(e.get("x", 0)), to_num(e.get("y", 0)))
                for e in (getattr(client, "active_explosions", None) or [])]

    def tiles_view(self) -> list:
        """Live gmap-aware `tiles[]`: tiles[x][y] (and tiles[x,y]) in the
        SCRIPT frame -- world tiles while standing on a gmap segment (LTTP's
        -Player/Movement indexes 0..width*64), local 0..63 in a standalone
        level. Columns are _BoardTilesColumn views routing straight to the
        client board both ways; the old code here snapshotted one 64x64
        local board, so world coords indexed out to None and every write
        mutated a detached copy. Rebuilt only when the world's shape
        changes (gmap <-> house); reads/writes are live regardless."""
        w, h = board_world_dims(self.client)
        if self._tiles_view is None or self._tiles_view_key != (w, h):
            self._tiles_view_key = (w, h)
            self._tiles_view = [_BoardTilesColumn(self, x, h)
                                for x in range(w)]
        return self._tiles_view

    def find_image(self, vm, index: int):
        """findimg(index) -> a LIVE view of the layer record (see
        _LayerImage / layer_image_get, which creates the record on a miss).
        The prior detached-copy object silently dropped every
        `findimg(i).rotation += ...` / `.text = ...` write (the v6 bomber's
        CadavreTest cogs and debug readouts animate exclusively this way)."""
        if self.gs1 is None:
            return 0.0
        ctx = self._gs1_ctx(vm)
        table = self.gs1._host._layer_store(ctx)
        if table is None:
            return 0.0
        owner = ctx.this_obj if isinstance(ctx.this_obj, dict) else None
        return layer_image_get(table, index, owner)

    # -- wiring --------------------------------------------------------------

    def attach(self):
        """Hook into the client: bytecode arrivals load into VMs, and inbound
        PLO_TRIGGERACTION fires onAction<name> handlers."""
        if self.client is None:
            return self
        self.client.gs2_host = self
        self._prev_bytecode_cb = self.client.on_gs2_bytecode
        self.client.on_gs2_bytecode = self._on_bytecode
        # Bytecode that arrived BEFORE this hook existed still has to run.
        # Classes first so
        # a weapon's toplevel join() resolves immediately (a late class
        # still resolves via _pending_joins, this just avoids the detour).
        pending = getattr(self.client, "gs2_bytecode", None) or {}
        for kind in ("class", "weapon", "npc", "gani"):
            for key, blob in list(pending.get(kind, {}).items()):
                self._pending_bytecode.append((kind, key, blob))
        self.pump_pending()
        # PLO_SERVERTEXT -> onReceiveText engine event. NB the pygame shell's
        # _setup_callbacks() later replaces client.on_server_text with its own
        # chat-log handler, which forwards here explicitly (game/setup.py) --
        # this direct hook covers headless embedders that never run setup.
        self._prev_server_text_cb = getattr(self.client, "on_server_text", None)
        if hasattr(self.client, "on_server_text"):
            self.client.on_server_text = self._on_server_text
        return self

    def _on_server_text(self, text: str):
        if self._prev_server_text_cb is not None:
            try:
                self._prev_server_text_cb(text)
            except Exception:
                pass
        self.handle_server_text(text)

    def handle_server_text(self, text: str) -> None:
        """Inbound PLO_SERVERTEXT -> the v6 engine's onReceiveText(texttype,
        textoption, textlines) weapon event ("receivetext" in the reference
        client's engine-event list; FourPlay's tclient_receivetext binding
        takes FOUR strings). The wire payload's FIRST token is the target
        WEAPON's name -- e.g. a join confirm is "-Serverlist_Chat,irc,join,
        #channel" (GServer-v2 ServerList.cpp:925-961 rewrites the weapon
        field per receiver; its replies echo the weapon field from the
        request, PlayerRequestText.cpp; the C# client parses
        tokens[0]==weapon, [1]==type, [2]==option). The engine consumes the
        weapon token for routing and hands the script (texttype, textoption,
        textlines) -- which is why -Serverlist_Chat can gate texttype ==
        "irc". A prior revision bound texttype = tokens[0], so every real
        reply carried the weapon name as its texttype and no handler's gate
        ever matched. Replies addressed to a weapon we have route to it
        alone; anything else (e.g. "GraalEngine", or a client-install weapon
        the server never sent us) broadcasts."""
        from .packets import _guntokenize
        tokens = _guntokenize(to_str(text))
        # every live Login server sends one EMPTY PLO_SERVERTEXT in its
        # login burst (guntokenize("") == [""]) -- not an event
        if not tokens or not to_str(tokens[0]):
            return
        weapon = to_str(tokens[0])
        texttype = tokens[1] if len(tokens) > 1 else ""
        textoption = tokens[2] if len(tokens) > 2 else ""
        textlines = tokens[3:]
        vm = self.vms["weapon"].get(weapon.lower())
        if vm is not None:
            if vm.has_function("onReceiveText"):
                self._run(vm, "onReceiveText", texttype, textoption, textlines)
            return
        self.trigger_event("onReceiveText", texttype, textoption, textlines)

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

        if kind == "gani":
            self._gani_classes[norm_key] = vm
            for wearer_key, worn in list(self._gani_worn.items()):
                if worn[0] == norm_key:
                    self._attach_gani(wearer_key, norm_key, worn[1],
                                      reload=True)
            return vm

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
            # Toplevel runs on every load so its join() calls attach classes.
            # State carries over via vm.this; onCreated fires only on first load.
            vm.run_toplevel()
            if (old is None and vm.has_function("onCreated")
                    and (kind == "weapon" or self.client is None)):
                self._run(vm, "onCreated")
            if (old is None and kind == "weapon"
                    and getattr(self.client, "connected", False)):
                # "serverlisterconnect" engine event: fired on the UNIVERSE
                # object, no args (TClient.cpp:2231-2241 -> universe->
                # invokeEvent("onServerListerConnect")). The v6 client raises
                # it when its serverlist link comes up; server weapons load
                # over a connection whose lister link is ALREADY up, so the
                # notification replays at load. Login's corpus handler is a
                # dotted `function universe.onServerListerConnect()` that
                # just forwards to a bare global of the same name -- the
                # bare spelling stays the primary call (it is what the live
                # fingerprint pins), with the universe-dotted form covering
                # content that defines ONLY the forwarder. Login's
                # -Serverlist_Chat does its whole lister login (sendLogin ->
                # sendtext "irc","login") from exactly this handler.
                if vm.has_function("onServerListerConnect"):
                    self._run(vm, "onServerListerConnect")
                elif vm.has_function("universe.onServerListerConnect"):
                    self._run(vm, "universe.onServerListerConnect")
        return vm

    def fetch_weapon(self, wname: str, timeout: float = 3.0) -> Optional[GS2VM]:
        """findweapon() missed: pull the weapon from the server.

        On the official client the Login serverlist weapons
        (-Rescripted/Serverlist, -Serverlist, -ServerListScreen, ...) ship
        with the CLIENT INSTALL -- the server never pushes them, it only
        answers PLI_UPDATESCRIPT refresh requests, which is exactly how the
        installed copies stay current. We have no client install, so
        findweapon() on those names always missed and Login's bootstrap
        (-Rescripted/IRC/Login3 onCreated) silently did nothing = black
        screen. Requesting the script over the same PLI_UPDATESCRIPT channel
        works: the live Login server answers with full bytecode (verified
        2026-07-24 for all five client-install names).

        When we're outside the client's packet loop, pump the connection
        (bounded) until the script lands and load it inline, so findweapon()
        returns a live weapon object just as if it had been installed --
        Login3 then skips straight past its null-checks like the official
        client. From inside the packet loop (an event fired mid-update) we
        can't recurse into update(); the request still goes out and the
        weapon self-initializes when it loads via the normal deferred path.
        Names the server never answers are negative-cached for the session
        so a genuinely absent weapon stalls at most once."""
        client = self.client
        norm = wname.lower()
        if (client is None or norm in self._findweapon_missing
                or not client.request_weapon_bytecode(wname)):
            return None
        if getattr(client, "_in_update", False):
            return None      # async: load_bytecode will run it on arrival
        deadline = time.time() + timeout
        while time.time() < deadline:
            client.update(timeout=0.05)
            for i, (kind, key, blob) in enumerate(self._pending_bytecode):
                nk = key.lower() if isinstance(key, str) else key
                if kind == "weapon" and nk == norm:
                    del self._pending_bytecode[i]
                    return self.load_bytecode(kind, key, blob)
        self._findweapon_missing.add(norm)
        logger.info("GS2 findweapon(%r): server did not answer "
                    "PLI_UPDATESCRIPT within %.1fs", wname, timeout)
        return None

    # -- class joins ---------------------------------------------------------

    def join_class(self, vm: GS2VM, classname: str) -> bool:
        """join("classname"): merge the class's functions into the joining
        VM. If the class bytecode isn't here yet, request it (PLI_UPDATECLASS)
        and finish the join when it arrives."""
        cname = classname.lower()
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
        if getattr(vm, "_gs2_kind", "") == "gani":
            vm.this.mirror_wearer()
            vm._gs2_player = self._gani_player_object(vm._gs2_key)
            if not args and event.lower() != "oncreated":
                worn = self._gani_worn.get(vm._gs2_key)
                args = tuple(worn[1]) if worn is not None else ()
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
            if getattr(vm, "_gs2_kind", "") == "gani":
                vm.this.mirror_wearer()
                vm._gs2_player = self._gani_player_object(vm._gs2_key)
            previous, self._executing_vm = self._executing_vm, vm
            try:
                delay = next(gen)
            finally:
                self._executing_vm = previous
        except StopIteration:
            self._event_finished(key)
            return
        except Exception as e:
            self._event_finished(key)
            logger.warning("GS2 %s.%s aborted: %s", vm.name, event, e)
            self.fire_log_message(f"{vm.name}.{event} aborted: {e}",
                                  1.0, 0.0, 0.0, "scripterrors")
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
                if getattr(coro["vm"], "_gs2_kind", "") == "gani":
                    coro["vm"].this.mirror_wearer()
                    coro["vm"]._gs2_player = self._gani_player_object(
                        coro["vm"]._gs2_key)
                previous, self._executing_vm = (
                    self._executing_vm, coro["vm"])
                try:
                    coro["remaining"] = float(next(coro["gen"]))
                finally:
                    self._executing_vm = previous
                still.append(coro)
            except StopIteration:
                finished.append(coro["key"])
            except Exception as e:
                finished.append(coro["key"])
                logger.warning("GS2 %s.%s aborted: %s",
                               coro["vm"].name, coro["event"], e)
                self.fire_log_message(
                    f"{coro['vm'].name}.{coro['event']} aborted: {e}",
                    1.0, 0.0, 0.0, "scripterrors")
        self._coros = still
        for key in finished:
            self._event_finished(key)

    def fire_log_message(self, msg, red=1.0, green=1.0, blue=1.0,
                         logtype: str = "game") -> None:
        """universe.onLogMessage(msg, r, g, b, logtype) -- the engine-log
        line feed the official -F2LogWindow weapon renders (its handler at
        Preagonal/gbf/bytecode/login/_F2LogWindow.gs2bc.gs2:170-239; no C++
        fire site survives in the mobile reference, so the signature and the
        category vocabulary come from the two corpus handlers -- flagged
        inference). RGB are floats 0..1. Reentrancy-guarded: a handler that
        itself logs (or aborts, which would log "scripterrors") must not
        recurse."""
        if self._in_log_message:
            return
        self._in_log_message = True
        try:
            self.trigger_event("onLogMessage", to_str(msg), to_num(red),
                               to_num(green), to_num(blue), to_str(logtype))
        finally:
            self._in_log_message = False

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
            # `server` is the only one of the four that is NOT an alias of the
            # executing player (TScriptMachine.cpp:5123-5130 lists client,
            # clientr and serverr), so it gets no player fallback.
            player = None if name == "server" else self.player_object
            if name in ("client", "clientr"):
                scope = shared.setdefault("client", {})
                obj = _FlagScopeObject(name, scope,
                                       local_writes=(name == "clientr"),
                                       player=player)
            else:
                scope = shared.setdefault("server", {})
                prefix = "serverr." if name == "serverr" else ""
                obj = _FlagScopeObject(name, scope, prefix=prefix,
                                       local_writes=(name == "serverr"),
                                       player=player)
            self._flag_scopes[name] = obj
        return obj

    def handle_triggeraction(self, action_csv: str):
        """Inbound PLO_TRIGGERACTION: fire onAction<name>(params...) --
        the GS2 counterpart of the GS1 `action<name>` routing in client.py."""
        if not action_csv:
            return
        parts = _csv_unflatten(action_csv)
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
            self._scheduled = [item for item in self._scheduled
                               if item["key"] != tkey]
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
                if kind == "npc":
                    # Remember WHICH level this NPC last came alive in, so
                    # _npc_timer_suppressed can tell a script left behind by
                    # a warp from one whose props simply have not streamed
                    # in yet (see there).
                    vm._gs2_entered_level = level
                    if vm.has_function("onCreated"):
                        self._run(vm, "onCreated")
                if vm.has_function("onPlayerEnters"):
                    self._run(vm, "onPlayerEnters")

    def begin_level_visit(self):
        self._entered_level = None
        self._entered_vms.clear()

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
        self.sync_gani_wearers()
        self.pump_level_events()
        for kind in ("weapon", "npc", "gani"):
            for key, vm in list(self.vms[kind].items()):
                if (vm.has_function("onUpdate")
                        and not self._npc_timer_suppressed(kind, key, vm)):
                    self._run(vm, "onUpdate")
        self._timer_accumulator = min(
            self._timer_accumulator + max(0.0, dt), TIMER_BACKLOG_CAP)
        steps = int(self._timer_accumulator / TIMER_RESOLUTION)
        self._timer_accumulator -= steps * TIMER_RESOLUTION
        for _ in range(steps):
            self._process_timeout_step(TIMER_RESOLUTION)
        self._sync_script_position()

    def schedule_event(self, vm: GS2VM, delay: float, event: str,
                       params: List[Any]) -> None:
        """scheduleevent(delay, name, params...): arm a one-shot call of the
        script's own `name` function. Distinct from settimer/onTimeout --
        a script may have many in flight at once, each with its own
        arguments -- so they live in their own list, keyed by the same
        (kind, key) VM identity settimer uses (joined classes file under
        their joiner, see _timeout_key)."""
        if not event:
            return
        key = self._timeout_key(vm)
        if key is None:
            return
        if len(self._scheduled) >= SCHEDULED_EVENT_CAP:
            # a script looping scheduleevent() must not grow this without
            # bound; drop the newest rather than starve the armed ones
            return
        self._scheduled.append({"key": key, "left": max(0.0, to_num(delay)),
                                "event": event, "params": list(params)})

    def cancel_events(self, vm: GS2VM, event: str = "") -> None:
        """cancelevents([name]): drop this script's pending scheduled events
        (all of them when no name is given)."""
        key = self._timeout_key(vm)
        if key is None:
            return
        wanted = event.lower()
        self._scheduled = [
            item for item in self._scheduled
            if item["key"] != key or (wanted and item["event"].lower() != wanted)
        ]

    def _process_scheduled_events(self, dt: float) -> None:
        due = []
        for item in self._scheduled:
            item["left"] -= dt
            if item["left"] <= 0:
                due.append(item)
        if not due:
            return
        fired = {id(item) for item in due}
        self._scheduled = [item for item in self._scheduled
                           if id(item) not in fired]
        for item in due:
            kind, key = item["key"]
            vm = self.vms.get(kind, {}).get(key)
            if vm is not None and not self._npc_timer_suppressed(kind, key, vm):
                self._run(vm, item["event"], *item["params"])

    def _process_timeout_step(self, dt: float):
        """Advance script timers by one fixed update quantum."""
        self._process_scheduled_events(dt)
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
            # Don't fire the timer of an NPC that isn't in the level we're
            # standing in (ghost effects from a stale settimer). A truly
            # despawned NPC's VM is already gone via forget_npc
            # (PLO_NPCDEL).
            if self._npc_timer_suppressed(kind, key, vm):
                continue
            if vm.has_function("onTimeout"):
                self._run(vm, "onTimeout")

    # -- scripted animation lifecycle ---------------------------------------

    @staticmethod
    def _split_gani_text(value) -> tuple:
        parts = [part.strip() for part in to_str(value or "").split(",")]
        return ((parts[0] or "idle").lower(), parts[1:])

    def _gani_wearer_record(self, wearer_key: tuple):
        if self.client is None:
            return None
        kind, key = wearer_key
        if kind == "local":
            return getattr(self.client, "player", None)
        table = getattr(self.client, "players" if kind == "player" else "npcs",
                        {}) or {}
        return table.get(key)

    def _gani_player_object(self, wearer_key: tuple):
        kind, key = wearer_key
        if kind == "local":
            return self.player_object
        if kind == "player":
            record = self._gani_wearer_record(wearer_key) or {}
            return self.script_player_object(key, record)
        record = self._gani_wearer_record(wearer_key) or {}
        return self.script_player_object(key, record)

    def _request_gani(self, name: str) -> None:
        if name in self._requested_ganis:
            return
        request = getattr(self.client, "request_gani_bytecode", None)
        if request is not None:
            try:
                if request(name, 0):
                    self._requested_ganis.add(name)
            except Exception:
                pass

    def note_gani(self, wearer_key: tuple, value, force: bool = False) -> None:
        name, params = self._split_gani_text(value)
        old = self._gani_worn.get(wearer_key)
        current = (name, params)
        if old == current and not force:
            if name not in self._gani_classes:
                self._request_gani(name)
            return
        if old is not None:
            self._detach_gani(wearer_key)
        self._gani_worn[wearer_key] = current
        self._request_gani(name)
        if name in self._gani_classes:
            self._attach_gani(wearer_key, name, params)

    def _attach_gani(self, wearer_key: tuple, name: str, params: list,
                     reload: bool = False) -> None:
        class_vm = self._gani_classes.get(name)
        if class_vm is None:
            return
        old = self.vms["gani"].get(wearer_key)
        if old is not None:
            self._free_gani_vm(old)
        vm = GS2VM(class_vm.container, name=f"gani::{name}", host=self.host)
        vm_key = ("gani", wearer_key)
        vm.this = self._gani_this.get(wearer_key)
        if vm.this is None:
            vm.this = _GaniThisObject(self, vm_key, wearer_key,
                                      name=f"gani::{name}")
            self._gani_this[wearer_key] = vm.this
        vm.this._vm_key = vm_key
        vm.this._wearer_key = wearer_key
        vm.thiso = vm.this
        vm._gs2_kind = "gani"
        vm._gs2_key = wearer_key
        vm._gs2_owner = vm_key
        vm._gs2_player = self._gani_player_object(wearer_key)
        self.vms["gani"][wearer_key] = vm
        vm.this.mirror_wearer()
        previous, self._executing_vm = self._executing_vm, vm
        try:
            vm.run_toplevel()
        finally:
            self._executing_vm = previous
        created_key = (wearer_key, name)
        if created_key not in self._gani_created:
            self._gani_created.add(created_key)
            if vm.has_function("onCreated"):
                self._run(vm, "onCreated")
        if vm.has_function("onPlayerEnters"):
            self._run(vm, "onPlayerEnters", *params)

    def _free_gani_vm(self, vm: GS2VM) -> None:
        key = self._timeout_key(vm)
        self._timeouts.pop(key, None)
        self._scheduled = [item for item in self._scheduled
                           if item["key"] != key]
        self._cancel_vm_coroutines(vm)
        if self.gs1 is not None:
            self.gs1._weapon_imgs.pop(f"gs2_gani_{key[1]}", None)

    def _detach_gani(self, wearer_key: tuple) -> None:
        vm = self.vms["gani"].pop(wearer_key, None)
        if vm is not None:
            self._free_gani_vm(vm)
        self._gani_this.pop(wearer_key, None)
        self._gani_created = {
            key for key in self._gani_created if key[0] != wearer_key
        }

    def sync_gani_wearers(self) -> None:
        if self.client is None:
            return
        active = set()
        player = getattr(self.client, "player", None)
        if player is not None:
            key = ("local", getattr(player, "id", 0))
            active.add(key)
            identity = to_str(getattr(player, "account", "") or
                              getattr(player, "account_name", ""))
            if self._gani_wearer_identity.get(key, identity) != identity:
                self._detach_gani(key)
                self._gani_worn.pop(key, None)
            self._gani_wearer_identity[key] = identity
            self.note_gani(key, getattr(player, "animation", "idle"))
        for player_id, record in (getattr(self.client, "players", {}) or {}).items():
            key = ("player", player_id)
            active.add(key)
            identity = to_str(record.get("account", "") or
                              record.get("account_name", ""))
            if self._gani_wearer_identity.get(key, identity) != identity:
                self._detach_gani(key)
                self._gani_worn.pop(key, None)
            self._gani_wearer_identity[key] = identity
            self.note_gani(key, record.get("ani") or
                           record.get("animation") or "idle")
        for npc_id, record in (getattr(self.client, "npcs", {}) or {}).items():
            key = ("npc", npc_id)
            active.add(key)
            identity = to_str(record.get("name", "") or
                              record.get("account", "") or npc_id)
            if self._gani_wearer_identity.get(key, identity) != identity:
                self._detach_gani(key)
                self._gani_worn.pop(key, None)
            self._gani_wearer_identity[key] = identity
            self.note_gani(key, record.get("gani") or "idle")
        for key in set(self._gani_worn) - active:
            self._detach_gani(key)
            self._gani_worn.pop(key, None)
            self._gani_wearer_identity.pop(key, None)

    def _sync_script_position(self):
        """A script's player.x/player.y/player.dir writes only touch local
        state -- nothing walks the built-in Client.move() path that puts
        movement on the wire -- so broadcast them ourselves, at most every
        0.05s (one script tick).

        This is NOT limited to disabledefmovement levels. Classic content
        nudges the player from script while default movement is on all the
        time, and always along one axis: Bomber's piano seat does
        `playery-=.5` on sit and `playery = playery + 1` on stand
        (Preagonal/graal-bomber-gs1/world/levels/playerbase/room0.nw:757,798),
        its stairs do `playery+=.5`
        (same file:1130), and its lobby stair NPC does
        `playery += (this.y - playery)/2`
        (Preagonal/graal-bomber-gs1/world/bomblobby.nw:481). Gating this on
        disabledefmovement meant none of that ever reached the server: we
        drew ourselves on the piano bench while everybody else still saw us
        standing in front of it, one and a half tiles lower, with X spot on.
        The reference client has no such gate -- TPlayer::setlocalx/setlocaly
        flag the property dirty on ANY change
        (Preagonal/FourPlay/quattroplay/src/TPlayer.cpp:6290-6314).

        `client.position_matches_wire` (not just "did the value change since
        last tick") is what keeps this from doubling normal walking traffic:
        Client.move_to already transmitted those steps and recorded them.
        """
        client, gs1 = self.client, self.gs1
        if client is None or not getattr(client, "connected", False):
            return
        if getattr(client, "_local_level_transition", ""):
            # Mid-warp: x/y already name the destination but the server has
            # not acknowledged the level yet. Announcing here would report
            # the new coordinates against the old level.
            return
        p = getattr(client, "player", None)
        if p is None:
            return
        snap = (round(float(getattr(p, "x", 0.0)), 3),
                round(float(getattr(p, "y", 0.0)), 3),
                int(to_num(getattr(p, "direction", 0))))
        if snap == self._pos_sync_last:
            return
        if getattr(client, "position_matches_wire", False):
            # move_to/send_position/respond_to_hurt already put this exact
            # position on the wire -- nothing for us to announce.
            self._pos_sync_last = snap
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

    def _npc_timer_suppressed(self, kind: str, key, vm) -> bool:
        """True when this VM's timed events must NOT fire.

        NPC VMs deliberately OUTLIVE their level: gs2emu streams a level's
        static data (and its NPC bytecode) only once per session, so
        dropping the VM on exit would leave every script dead on re-entry.
        But client.npcs IS cleared on a level change (_reset_level_state),
        which left every departed NPC's settimer loop firing forever against
        a record that no longer exists -- measured against the local 2006
        Era world: 3596 orphan onTimeout calls vs 3912 live ones over a
        24-second, 4-level walk, each one running showimg/setcharani side
        effects for an NPC that is not in the level.

        The discriminator is the level the VM last came alive in
        (stamped by pump_level_events). A VM that has never entered a level
        keeps ticking exactly as before -- that is the not-yet-streamed
        case, plus weapons and the headless/test VMs with no NPC record at
        all. Re-entering the level re-fires onCreated (which re-arms the
        timer) and re-stamps the level, so this is a pause, not a kill."""
        if kind != "npc":
            return False
        entered = getattr(vm, "_gs2_entered_level", None)
        if entered is not None:
            level = getattr(self.client, "_current_level_name", "") or ""
            if level and entered != level:
                return True
        return self._npc_in_other_level(key)

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
        self.gs1._host.call_command(name, self._gs1_args(name, args),
                                    self._gs1_ctx(vm))

    @staticmethod
    def _gs1_args(name: str, args: List[Any]) -> List[Any]:
        """Hand the GS1 host this command's arguments, with the ones that
        end up as DISPLAY TEXT already stringified by GS2's rule.

        The two engines print numbers differently and deliberately stay that
        way: GS2 emits at most 9 decimals ("%.9f" trimmed, anything under
        1e-4 as "0") while GS1/GServer print the shortest round-tripping
        repr. Which rule applies is decided by where the VALUE came from, so
        a bare number a GS2 script passes as caption text (`showtext(0, x,
        y, "arial", "", 2/3)`) has to be converted HERE -- gs1_client's own
        to_str would print 0.6666666666666666 where the reference client
        draws 0.666666667. Text a script BUILDS with @ is already correct:
        OP_JOIN stringifies inside the VM.

        Only the caption positions are touched; coordinates and indices stay
        numeric so the GS1 host keeps full precision."""
        positions = _GS1_TEXT_ARGS.get(name)
        if not positions:
            return list(args)
        out = list(args)
        for index in positions:
            if index < len(out) and isinstance(out[index], (int, float)) \
                    and not isinstance(out[index], bool):
                out[index] = to_str(out[index])
        return out
