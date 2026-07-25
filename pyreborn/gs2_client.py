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
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from reborn_protocol.gs1.runtime import UNSET
from reborn_protocol.gs2 import (
    GS2VM, GS2Host, GS2Object, NOT_HANDLED, to_bool, to_num, to_str,
)
from .gs1_client import PLAYER_ATTR

logger = logging.getLogger(__name__)

# Limits for untrusted script writes to each server-scoped cache directory.
SAVE_LINES_MAX_LINES = 4096
SAVE_LINES_MAX_CHARS_PER_LINE = 4096
SAVE_LINES_CACHE_MAX_BYTES = 5 * 1024 * 1024

# Floor for settimer()/this.timeout. The v6 reference (C# client) has NO
# 0.05s script-timer clamp — that tradition is the legacy GS1 path
# (OpenGraal.Common ScriptObj.cs:100, `timeout -= 0.05` per tick). Its GS2
# path fires onTimeout two racing ways, neither floored at 0.05:
#   * GS2Engine 1.8.3 Script.cs SetTimer(): a ThreadPool sleeper at
#     `Thread.Sleep(value * 1500)` (1.5x the requested delay, ~ms floor);
#   * GameEngine.cs:755 polls due timers every fixed-timestep Update
#     (TargetElapsedTime = 1/120 s — GameEngine.cs:85/171).
# So a self-rearming setTimer(0.01) loop ticks at roughly the frame rate
# (~60-120 Hz) — that cadence is what sizes the bomber lobby's CadavreTest
# cog spin (0.03 rad/tick) AND -Test_Movement's walk (0.3 tiles/tick). The
# old 0.05 floor here ran both at 1/3 speed. Floor at the reference's
# 120 Hz update tick; effective cadence stays bounded by how often the game
# loop pumps process_timeouts. A fixed-step accumulator catches up at 120 Hz
# when a rendered frame spans multiple update quanta.
TIMER_RESOLUTION = 1.0 / 120.0
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

#: GS1 function names answered by GS1ClientHost.call_function.
#: onwater/onwater2 are v6 bindings too (FourPlay TInitStatics.cpp:4240-4241,
#: `{'b',"dd"}` / `{'b',"dddd"}` -> TServerLevel::isOnWater), and the GS1 host
#: already implements exactly that against the same tile store -- routing them
#: here keeps one water test for both engines. Zelda's movement weapon gates
#: its whole swim branch on onwater(player.x+1.5, player.y+2.25).
#: tiletype(x, y) is the same family: one tile store, one answer for both
#: engines. Zelda's -Player/Movement calls it bare AND as `level.tiletype(...)`
#: (the level object has no such member, so the member form lands here too)
#: to detect chairs, beds and jumpable ledges.
_GS1_FUNCTIONS = frozenset({"onwall", "onwall2", "onwater", "onwater2",
                            "keydown", "keydown2", "hasweapon", "tiletype"})

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
    "ani": "gani",
    # v6 HUD scripts read these members directly (the bomber's scripted HUD
    # draws counters from player.mp/ap/darts and player.swordimg); none has
    # a GS1 "player<name>" builtin, so the derived map missed them and every
    # read came back 0/"" (MP/AP meters empty, dart count zero, no sword
    # icon). "darts" is the classic name for arrows on the wire.
    "mp": "mp", "magicpoints": "mp", "ap": "ap", "darts": "arrows",
    "swordimg": "sword_image", "shieldimg": "shield_image",
    "headimg": "head_image", "bodyimg": "body_image",
})


def _csv_flatten(args) -> List[str]:
    """Trigger params as wire CSV fields: a GS2 {array} argument contributes
    one field per element (the client flattens arrays into the action string)."""
    out: List[str] = []
    for a in args:
        if isinstance(a, (list, tuple)):
            out.extend(to_str(x) for x in a)
        else:
            out.append(to_str(a))
    return out


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


def _engine_object(rt2: "ClientGS2", key: str) -> _EngineObject:
    """Session-persistent stand-in registry: repeated Find()/findanyobjectbytype
    calls for the same name/type must return the SAME object so member writes
    persist across scripts (the -System camera setup relies on identity)."""
    objs = getattr(rt2, "_engine_objects", None)
    if objs is None:
        objs = rt2._engine_objects = {}
    obj = objs.get(key)
    if obj is None:
        obj = objs[key] = _EngineObject(name=key)
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
    """

    __slots__ = ("_scope", "_prefix", "_local_writes")

    def __init__(self, name: str, scope: dict, prefix: str = "",
                 local_writes: bool = False):
        super().__init__(name=name)
        self._scope = scope
        self._prefix = prefix
        self._local_writes = local_writes

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
            return self._scope.get(key.lower(), "")
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
        # bare local inside `with(server){...}` to a networked flag.
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
        # -- STRING-VALUED identity properties -----------------------------
        # These must answer a STRING even when we have nothing to say. An
        # unanswered member reads as None, and comparing None against a
        # non-numeric string literal is EQUAL (both sides coerce to 0), so
        # every `player.<prop> == "<anything>"` in real content fires. Live
        # measurement on the Login server: 48 comparisons per 25s session of
        # `player.platform` against "linuxstream", which made
        # weapon-Rescripted_Serverlist.txt:336 and :2247 hide their controls
        # and :441 take the mobile branch. Anything else content
        # string-compares belongs in this group -- a corpus sweep of
        # `player.<name> ==/!=/in "..."` across Preagonal/graal-* found
        # exactly platform (46), account (18), chat (8), level (7),
        # communityname (7), guild (534 across era/GTA) and ani (1); all but
        # platform/communityname/guild were already answered below.
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
                return _NameObject(to_str(getattr(p, "gani", "") or ""))
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
            # so this.timeout = 0.01 loops tick at frame rate too
            v = to_num(value)
            if 0.0 < v < TIMER_RESOLUTION:
                v = TIMER_RESOLUTION
            self._rt2._timeouts[self._vm_key] = max(0.0, v)
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
            # public-function lookup has to happen here. Verified live: with
            # this gone, Login Mobile logs 14 "unknown method replaceall()"
            # per session. GS2VM.script_function recurses into joined
            # classes, so a class's public function resolves too.
            kind, key_ = self._vm_key
            vm = self._rt2.vms.get(kind, {}).get(key_)
            if vm is not None:
                return vm.script_function(key)
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
}


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
        return super().get(key)

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
                else:
                    npc[attr] = value if isinstance(value, str) else to_num(value)
                return
        super().set(key, value)


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

    __slots__ = ("_rec",)

    _NUM_KEYS = frozenset(("x", "y", "zoom", "rotation", "mode"))
    _STR_KEYS = frozenset(("image", "font", "style"))

    def __init__(self, index: int, rec: dict):
        super().__init__(name=f"image:{index}")
        self._rec = rec

    def get(self, key: str) -> Any:
        k = key.lower()
        if k == "visible":
            return 1.0 if self._rec.get("visible", True) else 0.0
        if k == "layer":
            return float(self._rec.get("vis", 4))
        v = self._rec.get(k)
        return super().get(k) if v is None else v

    def set(self, key: str, value: Any) -> None:
        k = key.lower()
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
        # More of the same credential surface as the des_encrypt group
        # above: a stored-account editor and password appliers. Inert BY
        # POLICY -- pyReborn's accounts come from prefs.py and nothing a
        # server script says may read, write or apply them.
        "setpasswordofaccount",
        "applypassword",
        "clearpassword",
        "adventure_geteditnickname",
        "adventure_geteditaccountnames",
        # External-application surface: opening a browser/native window on a
        # server script's say-so is an attack primitive, never a rendering
        # feature. Inert BY POLICY (the same reasoning as requesturl below,
        # which is a documented no-fetch stub).
        "opengraalurl",
        "gotowebpage",
        "adventure_openexternaloptions",
        "showupdatewindow",
        "startgraalstreaming",
        "showfriendinvitationwindow",
        "showgiftinvitationwindow",
        # Native platform toggles with no headless analog (offline mode,
        # socket policy, fullscreen switch, smartphone UI build, chat
        # widget hand-off, pointer grab). Every observed call site discards
        # the result.
        "adventure_startofflinemode",
        "adventure_setallowedsocketsconnect",
        "adventure_setfullscreen",
        "adventure_setchat",
        "createsmartphoneui",
        "mouselock",
        # Serverlist CONNECT-THROUGH surface. pyReborn joins servers from
        # its own browser (pygame_screens.py) after the user picks one; a
        # script-initiated connect/RC session would hand control of who we
        # talk to to remote content, so these stay inert here even though
        # the reference client wires them to real actions.
        "connecttoselectedserver",
        "serverdirectconnect",
        "startscriptedrc",
        "initserverlist",
        "requestserverinfo",
        "selectservercategory",
        # Store/profile/chat windows served by the platform account system,
        # which this client has no session with.
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

    #: host_surface() cache -- computed once per process. The introspection
    #: below re-reads THIS FILE from disk (inspect.getsource -> linecache):
    #: recomputing per call meant an on-disk edit made after import (routine
    #: during parallel-agent dev) desynced the line numbers and blew up
    #: ast.parse with a bogus SyntaxError -- which silently failed EVERY
    #: run_gs2_bounded() crawl classification on 07-22 ("SyntaxError:
    #: invalid syntax (<unknown>, line 1)" against live-server bytecode).
    #: The surface is static per process anyway.
    _surface_cache: Optional[frozenset] = None

    @staticmethod
    def host_surface():
        """Return builtins handled directly or delegated to the real GS1 host."""
        if GS2ClientHost._surface_cache is not None:
            return GS2ClientHost._surface_cache
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
        name = name.lower()
        if name in ("player", "playero"):
            return self.rt2.player_object
        if name == "level":
            return self.rt2.level_object
        if name in ("server", "serverr", "client", "clientr"):
            return self.rt2.flag_scope_object(name)
        if name == "guicontainer":
            # The engine's root GUI canvas. Scripts wrap whole construction
            # runs in `with (GUIContainer) { Win = new ("GuiWindowCtrl")
            # {...} }` (Login -Serverlist_Chat addChatWindowControls); the
            # VM SKIPS a with-block whose target isn't an object, so leaving
            # this unresolved silently discarded the entire window build.
            # A persistent engine-object stand-in is sufficient: parenting
            # comes from the compiler's auto-emitted addcontrol calls, not
            # from the container. It must answer canvas GEOMETRY reads
            # though: Login's -Rescripted/Serverlist sizes its taskbar and
            # trial bar off GUIContainer.clientwidth/clientheight (the
            # taskbar docks at clientheight - 30) -- auto-vivified members
            # read back as objects (numeric 0) and everything landed above
            # the canvas at y=-30.
            obj = _engine_object(self.rt2, "guicontainer")
            gs1 = self.rt2.gs1
            w = float(getattr(gs1, "screen_w", 800) or 800)
            h = float(getattr(gs1, "screen_h", 600) or 600)
            obj._members.update({
                "width": w, "height": h, "clientwidth": w, "clientheight": h,
                "extent": [w, h], "clientextent": [w, h],
            })
            return obj
        if name in ("graalcontrol", "graalcontrol3d"):
            # The engine's game-viewport control. Login's
            # initGraalControlSize resizes it (height = parent.clientheight
            # - taskbar) and then anchors its ChatBar/toggle button off its
            # clientwidth/clientheight, so it must answer geometry reads;
            # the script's own `height` write (with-scope, existence-gated
            # -- hence the setdefault) takes precedence over the live
            # canvas height on later clientheight reads.
            obj = _engine_object(self.rt2, name)
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
        if name == "servername":
            # Bare global: the CURRENT server's serverlist name ("Login").
            # The Login scripts gate their whole taskbar layout on it
            # (isLoginServer(): Serverlist_TaskButton_Server visible = the
            # non-login case); unresolved it read "" and the empty-labeled
            # server button covered the Servers button.
            return to_str(getattr(self.rt2.client, "server_name", "") or "")
        if name in ("serverstartconnect", "serverstartparams", "serveraddr"):
            # The other three TServerList globals. They MUST answer as
            # STRINGS, not as "unresolved" -- the reference allocates all
            # four as TStrings up front (`TServerList::serverstartconnect =
            # new TString()`, FourPlay quattroplay/src/TInitStatics.cpp:
            # 4928-4937, alongside the servername = "Offline" above), so an
            # untouched one is the empty STRING and compares by strcasecmp.
            #
            # Left unanswered they resolved to None -> lattice cell NUMBER
            # 0.0 (TScriptStackEntry::resolve), and the official number/string
            # rule is compareNumberValues(0.0, strtofloat(s))
            # (TScriptMachine::compare, src/TScriptMachine.cpp:1458-1461):
            # strtofloat of any non-numeric string is 0.0, so an unset global
            # tested EQUAL TO EVERY WORD. -Rescripted/Serverlist's
            # initServerlist then took `serverstartconnect == "skills"`
            # (weapon-Rescripted_Serverlist.txt:85), rewrote it to "login3",
            # fell into the `!= ""` arm at :106 and did
            # `Serverlist_Panel.visible = false; serverwarp("login3");` with
            # temp.donormallogin = false -- so sendServerListRequest() at
            # :121 never ran and the server tree stayed EMPTY, silently.
            #
            # `serverstartconnect` carries the server the client was launched
            # to auto-join (a graal:// URL / command line); pyReborn is always
            # launched at a server directly, so it is always empty here.
            return ""
        if name == "worldsf":
            # v6 C# client world handle: scripts call WorldsF.setFrameTick(ms)
            # (v6 preloader init + npc 10371). Method calls on an object the
            # host can't resolve never reach call_builtin (the VM only
            # consults the host when obj is not None), so hand back a
            # persistent engine-object stand-in.
            return _engine_object(self.rt2, "worldsf")
        if name in ("screenwidth", "screenheight"):
            # Bare screen-size reads: -arenaSYS centers its "Joining..."
            # showtext at (screenwidth/2, screenheight/2), the preloader's
            # DrawBar anchors likewise. The VM resolves unknown bare names
            # through host.get_object, which returned None here -> the
            # values read as 0 and every GS2 screen-anchored layer landed
            # at (0,0) (a 'c'-centered caption then hangs off the top-left
            # corner with only its tail on screen). Same source the GS1
            # host's screenwidth/screenheight builtins use; get_object may
            # return a plain value - the VM pushes whatever comes back
            # (vm.py _lookup / _op_conv_to_object).
            gs1 = self.rt2.gs1
            attr = "screen_w" if name == "screenwidth" else "screen_h"
            return float(getattr(gs1, attr, 0) or 0)
        if name == "isleader":
            gs1 = self.rt2.gs1
            if gs1 is None:
                return False
            return gs1._host.get_builtin(
                "isleader", [], self.rt2._gs1_ctx(None))
        if name == "allstats":
            # Sum of every showstats bit (GServer-v2 docs, "showstats"):
            # 1 ASD + 2 icons + 4 gralats + 8 bombs + 16 arrows + 32 hearts
            # + 64 AP + 128 MP + 256 minimap + 512 inventory + 1024 players.
            # The v6 bomber's HUD weapon computes `showstats(allstats - 1 -
            # 2 - ... - 128)` to swap the client's default HUD for its own
            # scripted one; unresolved this read 0 and the mask went
            # negative.
            return 2047.0
        if name in ("timevar", "timevar2"):
            # bare-name clock reads (v6 -Test_Movement stamps player.notpush
            # = timevar2 for its push-mode timing); same source the GS1
            # engine's builtin uses so both engines share one clock.
            gs1 = self.rt2.gs1
            if gs1 is None:
                return 0.0
            return gs1._host.get_builtin(name, [], self.rt2._gs1_ctx(None))
        if name == "players":
            return self.rt2.player_list_objects()
        if name == "tiles":
            return self.rt2.tiles_view()
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

    def create_object(self, classname: str, arg: Any) -> GS2Object:
        # host.create_object() is already the VM's constructor hook for
        # every `new` (see _op_new_object in reborn_protocol/gs2/vm.py) --
        # no vm.py change was needed to wire this up. Any Gui*Ctrl classname
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

    def call_builtin(self, vm: GS2VM, name: str, args: List[Any],
                     obj: Optional[GS2Object] = None) -> Any:
        rt2 = self.rt2

        if name == "catchevent":
            # catchevent(target, eventname, handlername): route a GUI
            # control's event to a function in the calling script.
            # -Serverlist_Chat wires its smilie buttons this way from inside
            # each button's construction block:
            #   thiso.catchevent(this.name, "onAction", "onSmilieButton")
            # `this.name` reads back empty there (the VM's `this` is the
            # weapon, not the control under construction), so an empty or
            # unresolvable target falls back to the control currently being
            # constructed. The handler receives the control's name (the
            # callbacks parse a trailing index off it).
            if rt2.gui is not None and len(args) >= 3 and vm is not None:
                target = args[0]
                ctrl = (rt2.gui._named.get(target.lower())
                        if isinstance(target, str)
                        else rt2.gui._resolve(target))
                if ctrl is None and rt2.gui._construction_stack:
                    ctrl = rt2.gui._construction_stack[-1]
                event = to_str(args[1]).lower()
                handler = to_str(args[2]).lower()
                if ctrl is not None and event and handler:
                    # the handler receives the CONTROL (onSmilieButton reads
                    # obj.smiliecode off it)
                    ctrl.set(event,
                             lambda *a, _c=ctrl, _vm=vm, _h=handler:
                                 _vm.call(_h, _c))
            return 0.0

        if name == "objecttype":
            # obj.objecttype() -> the object's class name (TGraalVar method,
            # TGraalVarProperties.cpp:475-483 `{'s', ""}`). Login's
            # serverlist filters its taskbar with
            # `temp.button.objecttype() != "GuiButtonCtrl"`
            # (weapon-Rescripted_Serverlist.txt:351) and -Staff/GUIExplorer
            # labels every node with it. GuiControl subclasses carry the
            # authoritative spelling on CTRL_CLASS; everything the host
            # builds through create_object() is named after its `new`
            # classname. Answered ABOVE the obj-method block below, which
            # ends in NOT_HANDLED for anything it doesn't recognize.
            target = obj if obj is not None else getattr(vm, "this", None)
            return to_str(getattr(target, "CTRL_CLASS", None)
                          or getattr(target, "name", "") or "")

        if obj is not None:
            if name == "sort" and isinstance(obj, list):
                obj.sort(key=lambda value: (to_str(value).casefold(), to_num(value)))
                return obj
            if name in ("sortascending", "sortdescending") and isinstance(obj, list):
                # The shared VM implements sortbyvalue but not these two
                # (Login's staff file-explorer weapon sorts its listing with
                # `files.sortascending()`); the host gets first refusal, so
                # this is the only place they can live.
                obj.sort(key=lambda value: (to_str(value).casefold(), to_num(value)),
                         reverse=name == "sortdescending")
                return obj
            if name == "savelines" and isinstance(obj, list):
                if args:
                    rt2.save_lines(to_str(args[0]), obj)
                return 0.0
            if isinstance(obj, str):
                # String METHODS the compiler does not lower to an opcode.
                # `.lower()`/`.upper()` are the two the live corpus uses
                # (Login's staff sprite-editor weapon keys its per-gani
                # default map on `this.gdefault.(@def.lower())`).
                if name in ("lower", "lowercase"):
                    return obj.lower()
                if name in ("upper", "uppercase"):
                    return obj.upper()
                # ("-Serverlist_Options").showOptions() -- a method call on a
                # string that NAMES a weapon script dispatches to that
                # weapon's public function (the reference engine's
                # weapon-as-object form; Login uses it for -ScriptedRC,
                # -Serverlist_Options and -ShopGlobal). Only already-loaded
                # weapons are considered: resolving one would mean a
                # findweapon-style server fetch on every unknown string
                # method, which is neither free nor obviously wanted.
                wvm = rt2.vms["weapon"].get(obj.lower())
                if wvm is not None and wvm.has_function(name):
                    return wvm.call(name, *args)
            # Other list methods (add/addarray/size/clear/index/sortbyvalue)
            # deliberately fall through as NOT_HANDLED: the shared VM
            # implements them natively and gives the host first refusal
            # (obj= may be a plain Python list here, not a GS2Object).
            if name in self.stubbed:
                return 0.0
            if name == "addcontrol" and rt2.gui is not None:
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
                child = args[0] if args else None
                if isinstance(child, str):
                    child = rt2.gui._named.get(child.lower(), child)
                rt2.gui.addcontrol(child, owner_vm=vm)
                rt2.gui.add_to(obj, child)
                return 0.0
            if isinstance(obj, _EngineObject):
                # v6 C# client engine-object methods. Observed call sites
                # (v6 -System/-System_Preloader/npc 10371 disasm):
                #  * WorldsF.setFrameTick(ms): frame pacing hint, result
                #    discarded (OP_INDEX_DEC) -> inert.
                #  * Find("Logger").transform.GetChild(0).gameObject
                #      .SetActive(true): whole-chain result discarded; only
                #    non-null traversal matters. GetChild returns a stable
                #    auto-vivified child; SetActive records the flag.
                if name == "getchild":
                    return obj.get(f"child{int(to_num(args[0])) if args else 0}")
                if name == "setactive":
                    obj.set("active", 1.0 if not args or to_num(args[0]) else 0.0)
                    return 0.0
                # Any other engine-object method is part of the same C#-client
                # surface we don't emulate: inert, result never consumed.
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
                if name in ("showtop", "show") and ctrl is not None:
                    # ctrl.showTop(): make visible and raise to the top of
                    # the sibling z-order (Login's -Serverlist_Chat openChat
                    # ends with GlobalChat_Window.showtop()). Same semantics
                    # as the global showgui() form.
                    rt2.gui.show(ctrl)
                    return 0.0
                if name == "hide" and ctrl is not None:
                    rt2.gui.hide(ctrl)
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

            if name in ("leave", "isinclass", "getcallstack") and vm is not None:
                # The object-method spelling of the three bare forms below.
                # Every live call site uses THIS one: Zelda's
                # class:gui_builder built() ends with
                # `this.leave("gui_builder"); echo(... this.isinclass(
                # "gui_builder"))`, and g2k1's weaponParticleEditor dumps
                # `this.getCallStack()`.
                if name == "getcallstack":
                    return rt2.call_stack(vm)
                if name == "isinclass":
                    return 1.0 if (args and rt2.is_in_class(
                        vm, to_str(args[0]))) else 0.0
                if args:
                    rt2.leave_class(vm, to_str(args[0]))
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
            if name in ("scheduleevent", "cancelevents") and vm is not None:
                # `this.scheduleevent(1, "TurnOffBorder", obj)` -- the same
                # engine call as the bare form below, reached as a method of
                # the script's own `this` (every live call site spells it
                # that way).
                if name == "scheduleevent" and len(args) >= 2:
                    rt2.schedule_event(vm, to_num(args[0]), to_str(args[1]),
                                       list(args[2:]))
                elif name == "cancelevents":
                    rt2.cancel_events(vm, to_str(args[0]) if args else "")
                return 0.0
            if isinstance(obj, GS2Object):
                # Dynamic-member (VariableCollection) surface. Login's
                # Staff weapons manage their caches with it:
                # `this.spritecache.clearvars()` per rebuild, and
                # `for (v: this.gdefault.getdynamicvarnames())` to walk one.
                # Private bookkeeping keys (leading "_", e.g. the layer
                # store's "_findimg") are engine-internal and stay hidden.
                names = [key for key in obj._members
                         if not str(key).startswith("_")]
                if name == "clearvars":
                    for key in names:
                        del obj._members[key]
                    return 0.0
                if name in ("getvarnames", "getdynamicvarnames"):
                    return [key for key in names
                            if not callable(obj._members[key])]
            # other object methods with no member function bound: no GS1
            # equivalent
            return NOT_HANDLED

        # GS2 GUI-controls builtins (showgui/GuiControl -- see gs2_gui.py's
        # module docstring). addcontrol()'s single argument is always "the
        # object this new-statement just constructed" (never a parent) --
        # GS2GuiManager infers nesting from create/addcontrol call order.
        if name == "addcontrol":
            if rt2.gui is not None:
                rt2.gui.addcontrol(args[0] if args else None, owner_vm=vm)
            return 0.0

        if name in ("addcontainer", "addguicontainer"):
            if rt2.gui is not None and len(args) >= 2:
                rt2.gui.add_to(args[0], args[1])
            return 0.0

        if name in self.stubbed:
            return self._PATCHER_STUB_VALUES.get(name, 0.0)

        if name in ("requesturl", "requesturlasgamefile"):
            # Inert BY POLICY: this client never fetches script-supplied
            # URLs (Login uses it for an events-news feed; the payload is
            # cosmetic). Returns a dead request object so the follow-up
            # catchevent(this.eventinforequest, "onReceiveData", ...) has a
            # real target -- onReceiveData simply never fires.
            if name not in rt2._policy_stub_logged:
                rt2._policy_stub_logged.add(name)
                logger.info("GS2 %s(): inert stub (no network fetch by "
                            "policy); url=%r",
                            name, to_str(args[0]) if args else "")
            return GS2Object(name="urlrequest")

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
            # players[] INDICES, nearest first -- see nearest_player_indices
            # for why this is not findnearestplayers' payload.
            player = getattr(rt2.client, "player", None)
            x = to_num(args[0]) if args else to_num(getattr(player, "x", 0))
            y = to_num(args[1]) if len(args) > 1 else to_num(getattr(player, "y", 0))
            return rt2.nearest_player_indices(x, y)

        if name in ("findnearestplayers", "findnearestplayer"):
            # Same sort as getnearestplayers above, different payload: the
            # player OBJECTS instead of their players[] indices (quattroplay
            # TInitStatics.cpp:2088 vs :2067). The SINGULAR form is the same
            # search returning only the winner, or null when the level is
            # empty (:2044, over the same list including ourselves --
            # Zelda's lift code checks `pl.account != player.account`).
            player = getattr(rt2.client, "player", None)
            x = to_num(args[0]) if args else to_num(getattr(player, "x", 0))
            y = to_num(args[1]) if len(args) > 1 else to_num(getattr(player, "y", 0))
            found = rt2.find_nearest_players(x, y)
            if name == "findnearestplayers":
                return found
            return found[0] if found else 0.0

        if name == "getstringkeys":
            return rt2.string_keys(to_str(args[0]) if args else "")

        if name == "getcallstack":
            return rt2.call_stack(vm)

        if name == "isinclass":
            return 1.0 if (vm is not None and args
                           and rt2.is_in_class(vm, to_str(args[0]))) else 0.0

        if name == "leave":
            # leave("classname"): the inverse of join() -- drop the class
            # from the calling script again.
            if vm is not None and args:
                rt2.leave_class(vm, to_str(args[0]))
            return 0.0

        if name == "findplayerbyid":
            return rt2.player_by_id(int(to_num(args[0]))) if args else 0.0

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
            # Script-facing signature is (type, option, params...) -- the
            # reference engine's binding is "ssX" (FourPlay TInitStatics
            # sendtext) with NO weapon argument: the engine prepends the
            # CALLING weapon's own name as the first wire field, giving
            # "-Serverlist,lister,list,all" / "GraalEngine,irc,login,-"
            # (GServer-v2 PlayerRequestText.cpp parses weapon\ntype\noption\n
            # params...; the C# client's hardcoded flows send the same shape).
            # Without that field the server read our type as the weapon and
            # matched nothing -- the live Login lister never answered a
            # single request. A top-level {array} param contributes one wire
            # field per element; a NESTED array collapses to one gtokenized
            # field (server side does params[4].guntokenize(), e.g. the
            # IRCBot "!getserverinfo" bundle).
            if rt2.client is not None and args:
                fields = [rt2.wire_weapon_name(vm)] + rt2.wire_text_fields(args)
                rt2.client.send_server_text(name == "requesttext",
                                            "\n".join(fields))
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
            # Floor at the reference client's 120Hz update tick, NOT the
            # legacy 0.05s: see TIMER_RESOLUTION. A prior wave clamped this
            # to 0.05 assuming -Test_Movement's setTimer(0.01) loop was
            # meant to tick at 20Hz (0.3 tiles/tick = the classic 6 tiles/s
            # walk) — but GS2Engine 1.8.3 (the exact package the C# client
            # pins) has no such floor, so per-frame ticking IS the reference
            # behavior, for movement speed included.
            v = to_num(args[0]) if args else 0.0
            if 0.0 < v < TIMER_RESOLUTION:
                v = TIMER_RESOLUTION
            rt2._timeouts[rt2._timeout_key(vm)] = max(0.0, v)
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
                action = ",".join(_csv_flatten(args[2:]))
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
                action = ",".join([prefix] + _csv_flatten(args[1:]))
                rt2.client.triggeraction(action, x=0.0, y=0.0)
            return 0.0

        if name == "isobject":
            return 1.0 if (args and self.get_object(to_str(args[0])) is not None) else 0.0

        if name == "findweapon":
            wname = to_str(args[0]) if args else ""
            wvm = rt2.vms["weapon"].get(wname.lower()) if wname else None
            if wvm is None and wname:
                # Client-install weapons: see ClientGS2.fetch_weapon.
                wvm = rt2.fetch_weapon(wname)
            return wvm.this if wvm is not None else 0.0

        if name in ("setani", "setcharani"):
            # setcharani from an NPC script sets the NPC'S OWN animation —
            # piano/sign/furniture NPCs become visible exactly this way
            # (bomber v6 lobby: setcharani("sen_piano"), ("itsasign2")).
            # Route it through the GS1 host, which writes npc['gani'] for the
            # renderer; extra args are gani PARAM tokens, kept comma-joined
            # (render_entities._split_npc_gani splits them back off).
            # setani (v6 player builtin) and weapon-script setcharani keep
            # driving the local player below.
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

        if name == "timevar2":
            return time.time()

        if name in ("getimgwidth", "getimgheight", "imgwidth", "imgheight"):
            # Answered from the downloaded file's header; preloader-style
            # scripts poll this in a wait loop until the download lands, so
            # a miss also (re-)requests the file.
            # imgwidth/imgheight are the LEGACY GS1 spellings (they are in
            # reborn_protocol.gs1's FUNCTIONS table; v6's binding table only
            # has the get* pair, TInitStatics.cpp:2287-2288) -- routed to the
            # same answer here so both engines share one implementation.
            fname = to_str(args[0]) if args else ""
            dims = rt2.image_size(fname) if fname else None
            if dims is None:
                return 0.0
            return float(dims[0] if name in ("getimgwidth", "imgwidth")
                         else dims[1])

        if name == "tiletype":
            if rt2.client is not None and len(args) >= 2:
                from .tiletypes import get_tile_type
                x, y = int(to_num(args[0])), int(to_num(args[1]))
                tiles = getattr(rt2.client, "tiles", None)
                if tiles and 0 <= x < 64 and 0 <= y < 64:
                    return float(get_tile_type(tiles[y * 64 + x]))
            return 0.0

        # -- v6 C# client platform builtins ---------------------------------
        # Call-site evidence is the v6 bytecode disasms (job a34dbef5 tmp/):
        # -System, -System_Preloader, -Zoom, -warn, npc 10371.

        if name in ("base64encode", "base64decode"):
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

        if name == "savevars":
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
                rt2.save_lines(to_str(args[0]), lines)
            return 0.0

        if name in ("lowercase", "uppercase"):
            # Bare engine string builtins (Login -Serverlist_Chat keys its
            # per-channel control names on lowercase(channel):
            # "GlobalChat_ChatList_" @ lowercase(channel) -- unanswered,
            # every channel control lookup missed).
            value = to_str(args[0]) if args else ""
            return value.lower() if name == "lowercase" else value.upper()

        if name == "strequals":
            # npc 10371 onPlayerEnters:
            #   if (strequals("blank", player.ani)) setani("eye_bomber_idle0")
            # Result feeds OP_CONV_TO_FLOAT + OP_IF, so it must be 1/0.
            # Case-insensitive, matching the engine's string == convention
            # (VariableCollection lowercases; GS1 string compare ignores case).
            a = to_str(args[0]) if args else ""
            b = to_str(args[1]) if len(args) > 1 else ""
            return 1.0 if a.lower() == b.lower() else 0.0

        # -- 2026-07-24 static-census gaps ----------------------------------
        # Each name below was confirmed missing at RUNTIME first (compiled
        # with the real gs2 compiler, run on this host, seen in
        # GS2VM.builtins_missing) and only then shaped from the reference
        # client's binding tables in Preagonal/FourPlay/quattroplay/src.

        if name == "contains":
            # contains(source, needle) -- NOT a plain substring test: the
            # engine requires the match to be bounded by a WORD BORDER on
            # both sides (or by the ends of the string), case-insensitively
            # (TInitStatics.cpp:1962-1990, border set vars24 at :283;
            # binding :2287 `{'b', "ss"}`). era's weapongun.txt:270 gates on
            # contains(this.weapon_opposite, "Dual") and -Commands.txt:1159
            # on contains(player.level.name, "mall") -- both of which a
            # substring test would over-match ("Dualist", "smallroom").
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

        if name in ("degtorad", "radtodeg"):
            # TInitStatics.cpp:1999/2004, bindings :2289-2290 `{'d', "d"}`.
            # era's particle scripts pass modifier ranges as degtorad(0),
            # degtorad(15); bomber's weaponjoey_test1 spreads shots with
            # degtoRad(22.5).
            import math
            value = to_num(args[0]) if args else 0.0
            return (value * math.pi / 180.0 if name == "degtorad"
                    else value * 180.0 / math.pi)

        if name == "findplayer":
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
            for pid, record in (getattr(client, "players", {}) or {}).items():
                get = record.get if isinstance(record, dict) else (
                    lambda key, default=None: getattr(record, key, default))
                if to_str(get("account", "")).lower() == wanted.lower():
                    return rt2.script_player_object(pid, record)
            return 0.0

        if name in ("cursoron", "cursoroff", "iscursoron"):
            # GuiCanvas cursor visibility (GuiCanvas.cpp:47-63, bindings
            # :83-85). Called BARE by Login's serverlist when it takes over
            # the screen. No corpus calls cursorOff/isCursorOn, so this can
            # only ever confirm the pointer visible in practice.
            gui = rt2.gui
            if gui is None:
                return 0.0
            if name == "iscursoron":
                return 1.0 if gui.cursor_on else 0.0
            gui.set_cursor_on(name == "cursoron")
            return 0.0

        if name == "keycode":
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

        if name == "gettextwidth":
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
            game = getattr(rt2, "game_shell", None)
            if game is not None and hasattr(game, "_showtext_font"):
                try:
                    font = game._showtext_font(fontname or "Arial", size,
                                               "b" in style)
                    return float(font.size(text)[0])
                except Exception:
                    pass
            # headless fallback: mean glyph advance ~0.55em
            return float(len(text)) * size * 0.55

        if name == "gettextheight":
            # gettextheight(zoom, font, styles) -> line height in client px,
            # the sibling of gettextwidth above and BY FAR the most-called
            # gap in the live Login corpus (732 calls in one pass): the
            # serverlist screen sizes nearly every label's extent with
            # `extent = { w, gettextheight(scale, "friz", "b") }`, so an
            # unanswered 0 collapsed those controls to zero height.
            zoom = to_num(args[0]) if args else 1.0
            fontname = to_str(args[1]) if len(args) > 1 else ""
            style = to_str(args[2]) if len(args) > 2 else ""
            size = max(8, int(16 * (zoom or 1.0)))
            game = getattr(rt2, "game_shell", None)
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

        if name == "md5":
            import hashlib
            raw = to_str(args[0]) if args else ""
            return hashlib.md5(raw.encode("latin-1", "replace")).hexdigest()

        if name in ("extractfilename", "extractfilebase", "extractfileext"):
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

        if name == "fileexists":
            # True only for content this client actually holds: a file the
            # server already sent us, or one in the sprite cache. Never a
            # local-filesystem probe -- a script must not be able to
            # enumerate the user's disk.
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

        if name in ("pushdialog", "popdialog"):
            # Torque modal-dialog stack. Headlessly a dialog is just a
            # control raised to the top of the canvas (pushDialog) or
            # hidden again (popDialog) -- Login pushes its "connecting"
            # and error dialogs this way.
            if rt2.gui is not None and args:
                if name == "pushdialog":
                    rt2.gui.show(args[0])
                else:
                    rt2.gui.hide(args[0])
            return 0.0

        if name == "bringtofront":
            # global form; the with-scope/method form is a control method
            if rt2.gui is not None and args:
                ctrl = rt2.gui._resolve(args[0])
                if ctrl is not None:
                    rt2.gui.bring_to_front(ctrl)
            return 0.0

        if name == "isfullscreenmode":
            game = getattr(rt2, "game_shell", None)
            return 1.0 if getattr(game, "fullscreen", False) else 0.0

        if name == "scheduleevent":
            # scheduleevent(delay, "EventName", params...): call the calling
            # script's own EventName after `delay` seconds. Driven by the
            # same per-frame pump as settimer (see process_timeouts).
            if vm is not None and len(args) >= 2:
                rt2.schedule_event(vm, to_num(args[0]), to_str(args[1]),
                                   list(args[2:]))
            return 0.0

        if name == "cancelevents":
            # cancelevents(["EventName"]): drop this script's pending
            # scheduled events (all of them when no name is given).
            if vm is not None:
                rt2.cancel_events(vm, to_str(args[0]) if args else "")
            return 0.0

        if name == "findobject":
            # findobject(name) -> the named engine object / GUI control, or
            # 0.0. Same registry every bare-name reference resolves through
            # (get_object); Login Mobile's gui_scaler and -LoginScreen look
            # their controls up this way instead of by bare name.
            found = self.get_object(to_str(args[0])) if args else None
            return found if found is not None else 0.0

        if name in ("loadvars", "loadvarsfromarray"):
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
                lines = rt2.load_lines(to_str(args[0]) if args else "")
            for line in lines:
                key, sep, value = to_str(line).partition("=")
                if sep and key.strip():
                    this.set(key.strip(), value)
            return 0.0

        if name == "getscalefactor":
            # -Zoom onCreated: this.maxscale = getScaleFactor() + 1, and the
            # desktop default for client.mobile_smoothzoom_* -> 1 on PC
            # (maxscale 2 matches -System's own scalefactor = 2).
            return 1.0

        if name == "getplatform":
            # Same value player.platform reports -- the reference reads both
            # off TIdentification::platformname (TInitStatics.cpp:2796-2801
            # binding :4214 `{'s', ""}`, and TPlayer.cpp:663). It used to
            # share the 0.0 group below, which made `getplatform() ==
            # "android"` compare EQUAL (0 == strtofloat("android")) and sent
            # Login Mobile's -Adventure down the handset branch.
            return PLATFORM_NAME

        if name in ("getgamesubversion", "getpremiumoption", "fileupdate"):
            # Native build/entitlement/patcher queries the live Login MOBILE
            # server's -Adventure and -Mobile/Serverlist make every session.
            # No honest answer exists for a portable Python client -- and
            # 0.0 is the TRUTHFUL one for the entitlement query, since we
            # hold no premium option. Deliberately NOT in
            # `stubbed`: game_tester/server_crawl.py's
            # KNOWN_UNSUPPORTED_CALLS is the registry that classifies these,
            # and it must stay the single source of truth for the boundary.
            # Answering them here only stops the per-session unknown-call
            # warning; the crawler still reports them known_unsupported.
            return 0.0

        if name == "getdevicemodel":
            # -Zoom uses it only as a client-flag name suffix
            # (client.mobile_smoothzoom_<model>): any stable, benign
            # desktop-ish token works.
            return "PC"

        if name in ("getiphonemodel", "getandroiddevicemodel"):
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

        if name in ("gameobject::find", "object::findanyobjectbytype"):
            # -System: cam = object::findanyobjectbytype(type::camera); then
            # cam.orthographic = true; cam.orthographicsize = 120; -- needs a
            # writable object with stable identity. -System_Preloader:
            # GameObject::Find("Logger") heads a discarded chain -- needs
            # non-null traversal. Never polled in a retry loop.
            key = to_str(args[0]) if args else ""
            return _engine_object(rt2, f"{name}:{key}".lower())

        if name == "quattro::transformextensions::getcomponents":
            # -System: cams = ...getcomponents(Type::Camera) -- assigned and
            # never read again; return a one-element list for shape-safety.
            key = to_str(args[0]) if args else ""
            return [_engine_object(rt2, f"component:{key}".lower())]

        if (name in ("setframetick", "adventure_setframetick",
                     "adventure_getframetick", "switchopengldevicescale",
                     "setretinadisplaynoantialias", "switchtodirectx",
                     "adventure_setcheatwindows")
                or name.startswith("quattro::debugtools::")):
            # Frame pacing / GL-scale / retina / renderer-backend / staff
            # cheat-window toggles for the C# client's renderer. Every
            # observed call discards the result (OP_INDEX_DEC at each site in
            # -System, -System_Preloader, -Zoom, npc 10371, and the live
            # Login -Serverlist) -- inert by design.
            return 0.0

        if name == "adventure_invokekeyevent":
            # Synthesising key events on a server script's say-so is an
            # input-spoofing primitive, not a rendering feature: the script
            # could drive any bound action (including chat and movement) as
            # if the user had typed it. Inert BY POLICY. Live Login Mobile
            # uses it only to dismiss its own soft keyboard.
            if name not in rt2._policy_stub_logged:
                rt2._policy_stub_logged.add(name)
                logger.info("GS2 %s(): inert stub (no synthetic input by "
                            "policy)", name)
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
        self._flag_scopes: Dict[str, GS2Object] = {}
        # onPlayerEnters bookkeeping: which VMs got it for the current level
        self._entered_level: Optional[str] = None
        self._entered_vms: set = set()
        self._tiles_source = None
        self._tiles_view = None
        # findnearestplayers() entries, kept per player id so the objects
        # scripts hold on to keep their identity (see script_player_object)
        self._script_players: Dict[Any, GS2Object] = {}
        # GUI-controls tree (showgui/GuiControl); None when pygame isn't
        # installed (headless callers, e.g. game_tester's GameBot).
        self.gui = GS2GuiManager(rt2=self) if GS2GuiManager is not None else None
        self.game_shell = None
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
        object every call, refreshed in place."""
        cache = self._script_players
        item = cache.get(player_id)
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
        get = record.get if isinstance(record, dict) else (
            lambda key, default=None: getattr(record, key, default))
        item.set("id", player_id)
        for member, key, default in self._SCRIPT_PLAYER_MEMBERS:
            value = get(key, default)
            item.set(member, default if value is None else value)
        item.set("ani", _NameObject(to_str(get("ani", "") or get("gani", "") or "")))
        # Derived, never carried on the wire (see _guild_from_nick). era and
        # GTA content string-compares player/other-player guilds ~534 times;
        # an unanswered member would compare EQUAL to every guild name.
        item.set("guild", _guild_from_nick(get("nickname", "")))
        return item

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
        for stale in [key for key in self._script_players if key not in live]:
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

    def player_by_id(self, player_id: int):
        """Return the player object with this id (local or remote), else 0.0."""
        client = self.client
        if client is None:
            return 0.0
        local = getattr(client, "player", None)
        if local is not None and getattr(local, "id", None) == player_id:
            get = lambda key, default=None: getattr(local, key, default)
        else:
            player = (getattr(client, "players", {}) or {}).get(player_id)
            if player is None:
                return 0.0
            get = player.get if isinstance(player, dict) else (
                lambda key, default=None: getattr(player, key, default))
        item = GS2Object(name=f"player:{player_id}")
        for key, value in (
                ("id", player_id), ("account", get("account", "")),
                ("nick", get("nickname", "")),
                ("nickname", get("nickname", "")),
                ("chat", get("chat", "")),
                ("x", get("x", 0)), ("y", get("y", 0))):
            item.set(key, value)
        return item

    def player_list_objects(self) -> list:
        client = self.client
        if client is None:
            return []
        local = getattr(client, "player", None)
        records = [{
            "id": getattr(local, "id", 0),
            "account": getattr(local, "account", ""),
            "nick": getattr(local, "nickname", ""),
            "nickname": getattr(local, "nickname", ""),
            "chat": getattr(local, "chat", ""),
            "x": getattr(client, "x", getattr(local, "x", 0)),
            "y": getattr(client, "y", getattr(local, "y", 0)),
        }]
        for player_id, player in (getattr(client, "players", {}) or {}).items():
            records.append({
                "id": player_id, "account": player.get("account", ""),
                "nick": player.get("nickname", ""),
                "nickname": player.get("nickname", ""),
                "chat": player.get("chat", ""), "x": player.get("x", 0),
                "y": player.get("y", 0),
            })
        result = []
        for index, record in enumerate(records):
            obj = GS2Object(name=f"player:{index}")
            for key, value in record.items():
                obj.set(key, value)
            result.append(obj)
        return result

    def tiles_view(self) -> list:
        tiles = getattr(self.client, "tiles", None) if self.client else None
        if tiles is not self._tiles_source:
            self._tiles_source = tiles
            self._tiles_view = [
                [float(tiles[y * 64 + x])
                 if tiles is not None and y * 64 + x < len(tiles) else 0.0
                 for y in range(64)]
                for x in range(64)
            ]
        return self._tiles_view

    def find_image(self, vm, index: int):
        """findimg(index) -> a LIVE view of the layer record (see
        _LayerImage). The prior detached-copy object silently dropped every
        `findimg(i).rotation += ...` / `.text = ...` write (the v6 bomber's
        CadavreTest cogs and debug readouts animate exclusively this way)."""
        if self.gs1 is None:
            return 0.0
        table = self.gs1._host._layer_store(self._gs1_ctx(vm))
        record = table.get(index) if table is not None else None
        if record is None:
            return 0.0
        obj = record.get("_findimg")
        # identity check: showtext REPLACES the rec dict for an index, so a
        # cached wrapper can point at a dead dict
        if not isinstance(obj, _LayerImage) or obj._rec is not record:
            obj = record["_findimg"] = _LayerImage(index, record)
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
        # Bytecode that arrived BEFORE this hook existed still has to run.
        # The embedding app logs in first and builds GameClient (and with it
        # this runtime) only afterwards -- pygame_game.py:191 -- so every
        # PLO_NPCBYTECODE/PLO_NPCWEAPONSCRIPT/PLO_LOADSCRIPT/PLO_GANISCRIPT
        # in the login burst landed in client.gs2_bytecode with nobody
        # listening and was silently dropped. Measured against the local
        # 2006 Era world (GServer-v2 bin/servers/era, :14901): the start
        # level's only bytecode NPC arrived during login and NEVER got a VM,
        # while an identical NPC entered after a warp did. Classes first so
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
        WEAPON's name -- live Login traffic is "-Serverlist_Chat,irc,
        addchanneluser,#graal,..." and GServer-v2's replies echo the weapon
        field from the request (PlayerRequestText.cpp; the C# client parses
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
            if (old is None and vm.has_function("onCreated")
                    and (kind == "weapon" or self.client is None)):
                self._run(vm, "onCreated")
            if (old is None and kind == "weapon"
                    and vm.has_function("onServerListerConnect")
                    and getattr(self.client, "connected", False)):
                # "serverlisterconnect" engine event (reference client event
                # list, FourPlay TInitStatics.cpp). The v6 client raises it
                # when its serverlist link comes up; server weapons load over
                # a connection whose lister link is ALREADY up, so the
                # notification replays at load. Login's -Serverlist_Chat
                # does its whole lister login (sendLogin -> sendtext
                # "irc","login") from exactly this handler.
                self._run(vm, "onServerListerConnect")
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
        # already joined?
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
            delay = next(gen)
        except StopIteration:
            self._event_finished(key)
            return
        except Exception as e:
            self._event_finished(key)
            logger.warning("GS2 %s.%s aborted: %s", vm.name, event, e)
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
                coro["remaining"] = float(next(coro["gen"]))
                still.append(coro)
            except StopIteration:
                finished.append(coro["key"])
            except Exception as e:
                finished.append(coro["key"])
                logger.warning("GS2 %s.%s aborted: %s",
                               coro["vm"].name, coro["event"], e)
        self._coros = still
        for key in finished:
            self._event_finished(key)

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

    def trigger_weapon_fired(self, weapon: str) -> bool:
        """The player used this weapon (D key): onWeaponFired, falling back
        to the legacy onFired name."""
        for ev in ("onWeaponFired", "onFired"):
            if self.trigger_weapon_event(weapon, ev):
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
            if name in ("client", "clientr"):
                scope = shared.setdefault("client", {})
                obj = _FlagScopeObject(name, scope,
                                       local_writes=(name == "clientr"))
            else:
                scope = shared.setdefault("server", {})
                prefix = "serverr." if name == "serverr" else ""
                obj = _FlagScopeObject(name, scope, prefix=prefix,
                                       local_writes=(name == "serverr"))
            self._flag_scopes[name] = obj
        return obj

    def handle_triggeraction(self, action_csv: str):
        """Inbound PLO_TRIGGERACTION: fire onAction<name>(params...) --
        the GS2 counterpart of the GS1 `action<name>` routing in client.py."""
        if not action_csv:
            return
        parts = action_csv.split(",")
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
        self.pump_level_events()
        for kind in ("weapon", "npc"):
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

    def _sync_script_position(self):
        """While a script drives movement (disabledefmovement), its player.x/
        player.y/player.dir writes only touch local state -- nothing walks
        the built-in Client.move() path that puts movement on the wire, so
        other players saw us frozen at the spawn point. Broadcast position/
        direction changes ourselves, at most every 0.05s (one script tick)."""
        client, gs1 = self.client, self.gs1
        if (client is None or gs1 is None or gs1.default_movement
                or not getattr(client, "connected", False)):
            return
        p = getattr(client, "player", None)
        if p is None:
            return
        snap = (round(float(getattr(p, "x", 0.0)), 3),
                round(float(getattr(p, "y", 0.0)), 3),
                int(to_num(getattr(p, "direction", 0))))
        if snap == self._pos_sync_last:
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
