"""Client-side GS2 package component."""

from __future__ import annotations

from typing import Any
from reborn_protocol.gs2 import GS2Object
from typing import Optional
from reborn_protocol.gs1.runtime import UNSET
import sys
import time
from reborn_protocol.gs2 import to_num
from reborn_protocol.gs2 import to_str
from .helpers import FREEZE_MAX_TICKS, FREEZE_TICKS_PER_SECOND, ZOOM_FACTOR_MAX, ZOOM_FACTOR_MIN, _GANI_TRANSFORM_DEFAULTS
from .registry import TIMER_RESOLUTION, _PLAYER_EMPTY_STRINGS, _PLAYER_MEMBER_ATTR, _PLAYER_READONLY, _TIMER_CANCEL

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
    view prefixes its keys. Serverr is the read-only replica -- writes stay
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
    two engines cannot disagree about what we are carrying."""

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
    """`player.colors[i]` / `pl.colors[i]`: the five body-color slots
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
        """player.freezetime = N, with the reference's quantization.

        propfun_player_freezetime_w (quattroplay/src/TPlayerProperties.cpp:
        18-37): a negative value freezes for 0 ticks, anything past 30 s
        saturates at the 600-tick ceiling, and everything else is
        `int(seconds * 20 + 1e-4)` ticks -- so 0.03 s rounds DOWN to nothing
        while 0.05 s is exactly one tick. It then clears the action mode. The
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
