"""Client-side GS2 package component."""

from __future__ import annotations

from typing import Any
from typing import Dict
from ..gs1_client import PLAYER_ATTR
from reborn_protocol.gs2 import casefold as gs2_casefold
import logging
from reborn_protocol.gs2 import to_bool
from reborn_protocol.gs2 import to_num
from reborn_protocol.gs2 import to_str

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
    from ..game.gs2_gui import GS2GuiManager, GuiControl, GuiPopUpEditCtrl
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
    "play", "play2", "playlooped", "setmusic", "stopmusic", "stopmidi",
    "stopsong",
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
    "gravity": lambda rt2, key, value: setattr(rt2, "gravity", to_num(value)) is None,
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
