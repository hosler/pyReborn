"""Client-side GS2 package component."""

from __future__ import annotations

from typing import Any
from typing import Dict
from reborn_protocol.gs2 import GS2Object
from reborn_protocol.gs2 import GS2VM
from reborn_protocol.gs2 import VMCoroutineWait
from typing import List
from typing import Optional
from pathlib import Path
from types import SimpleNamespace
from ..gs1_client import board_world_dims
import time
from reborn_protocol.gs2 import to_num
from reborn_protocol.gs2 import to_str
from .helpers import _csv_unflatten, _image_size, _is_admin_guild
from .host import GS2ClientHost
from .objects import _BoardTilesColumn, _GaniThisObject, _LevelObject, _NpcThisObject, layer_image_get
from .objects_player import _FlagScopeObject, _NameObject, _PlayerAttrObject, _PlayerColorsObject, _PlayerObject, _ThisObject, _guild_from_nick
from .registry import GS2GuiManager, GuiControl, PENDING_EVENT_CAP, SAVE_LINES_CACHE_MAX_BYTES, SAVE_LINES_MAX_CHARS_PER_LINE, SAVE_LINES_MAX_LINES, SCHEDULED_EVENT_CAP, TIMER_BACKLOG_CAP, TIMER_RESOLUTION, _GS1_TEXT_ARGS, _GlobalsStore, _REMOTE_PLAYER_EMPTY_STRINGS, _REMOTE_PLAYER_STICKY_NUMBERS, logger

CLASS_JOIN_WAIT_SECONDS = 5.0
CLASS_JOIN_WAIT_PUMPS = 300


class _ClassJoinWait(VMCoroutineWait):
    def __init__(self, runtime, vm, classname):
        self.runtime = runtime
        self.vm = vm
        self.classname = classname
        self.deadline = time.monotonic() + CLASS_JOIN_WAIT_SECONDS
        self.pumps = 0
        self.timed_out = False

    def ready(self):
        # The packet handler stores bytecode before its deferred runtime-load
        # callback can run.  Promote that cache hit now: attachment happens
        # synchronously, while coroutine resumption remains protected by the
        # runtime's non-reentrant wake loop.
        self.runtime._attach_cached_class(self.classname)
        if any(getattr(joined, "_gs2_key", None) == self.classname
               for joined in self.vm.joined):
            return True
        if (self.pumps >= CLASS_JOIN_WAIT_PUMPS
                or time.monotonic() >= self.deadline):
            self.timed_out = True
            return True
        return False

    def pump(self):
        self.pumps += 1

    def result(self):
        if self.timed_out:
            warning_key = (id(self.vm), self.classname)
            if warning_key not in self.runtime._join_timeout_warned:
                self.runtime._join_timeout_warned.add(warning_key)
                logger.warning("GS2 %s: class %r did not arrive; join timed out",
                               self.vm.name, self.classname)
            self.runtime._expire_join(self.vm, self.classname)
            return 0.0
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
        # Global projectile gravity (TInitStatics.cpp:1281, 2414-2416).
        self.gravity = 2.0
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
            # The Login rescripted log weapon customizes this client-owned
            # window with a `with` block rather than constructing it.  Keep
            # the native object on the canvas so showtop() can both reveal it
            # and raise it through the ordinary GUI-control method surface.
            log_window = self.gui.register_native_control(
                "GuiWindowCtrl", "F2LogWindow_Window")
            log_window.width = 500.0
            log_window.height = 200.0
            log_window.set_visible(False)
            log_window._native_canvas_control = True
            # The client predeclares the F3 player-list window before Login's
            # scripts install their full control tree.  The log weapon can
            # address it first, so preserve that native identity and attach
            # it to the canvas only when showtop() reveals it.
            player_list_window = self.gui.register_native_control(
                "GuiWindowCtrl", "PlayerList_Window")
            player_list_window.width = 188.0
            player_list_window.height = 503.0
            player_list_window.set_visible(False)
            player_list_window._native_canvas_control = True
            download_window = self.gui.register_native_control(
                "GuiWindowCtrl", "DownloadProgress_Window")
            download_window.width = 400.0
            download_window.height = 170.0
            download_window.set_visible(False)
            download_window._native_canvas_control = True
            installer_window = self.gui.register_native_control(
                "GuiWindowCtrl", "IRC_Test_UpdateWindow")
            installer_window.width = 590.0
            installer_window.height = 370.0
            installer_window.set_visible(False)
            installer_window._native_canvas_control = True
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
        self._join_timeout_warned: set = set()
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
        self._processing_coroutines = False
        self._coroutine_wake_pending = False
        self._active_coro_keys: set = set()
        self._pending_events: Dict[tuple, List[tuple]] = {}
        # New event entries wait here while this object's class downloads
        # are outstanding.  This is separate from _pending_events, which
        # serializes entries behind an event coroutine that is already
        # running (and may itself be parked in join()).
        self._join_gated_events: Dict[tuple, List[tuple]] = {}
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
        # Set only while an NPC's wasshot callback executes. The reference
        # getters inspect activeEvent + the executing NPC's projectile-origin
        # bit, so attribution must never leak beyond that callback.
        self._shot_attribution: Optional[str] = None
        # script-driven movement wire sync (see _sync_script_position)
        self._pos_sync_last: Optional[tuple] = None
        self._pos_sync_next: float = 0.0

    def has_pending_explorer_work(self) -> bool:
        """Whether deferred script work can still change an explorer snapshot.

        Scheduled timers are deliberately excluded: they are ordinary idle-time
        activity and may repeat forever.  This query covers work already in
        flight or held behind class loading/event serialization.
        """
        return bool(
            self._pending_bytecode
            or self._pending_joins
            or self._join_gated_events
            or self._pending_events
            or self._coros
            or self._active_coro_keys
            or self._coroutine_wake_pending
        )

    def save_lines(self, filename: str, lines: list) -> bool:
        """Persist script lines beneath a server-scoped client cache directory."""
        from ..prefs import config_dir
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
        from ..prefs import config_dir
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
        from ..packets import _gtokenize

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
        ("rating", "rating", 0.0),
        ("ratingd", "rating_deviation", 0.0),
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
        follows. The attr/colors views and the PM method surface are id-
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
        sort it. The player's vars are the client./clientr. Flag namespace,
        which is what an unprefixed prefix searches here. A leading scope
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
        """`allplayers`: every player id seen this session (incl. Externals
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
        waiting-PM text survives until the id is pruned. Id-100000
        resurrection of departed PM senders is deliberately NOT modeled."""
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
            level = getattr(client, "_current_level_name", "") or ""
            items_in_level = getattr(client, "items_in_level", None)
            if items_in_level is not None:
                return list(items_in_level(level))
            return list(getattr(client, "items", {}) or {})
        if probe == "testbomb":
            level = getattr(client, "_current_level_name", "") or ""
            return list((getattr(client, "bombs", {}).get(level, {}) or {}))
        return [(to_num(e.get("x", 0)), to_num(e.get("y", 0)))
                for e in (getattr(client, "active_explosions", None) or [])]

    def tiles_view(self) -> list:
        """Live gmap-aware `tiles[]`: tiles[x][y] (and tiles[x,y]) in the
        SCRIPT frame -- world tiles while standing on a gmap segment (LTTP's
        -Player/Movement indexes 0..width*64), local 0..63 in a standalone
        level. Columns are _BoardTilesColumn views routing straight to the
        client board both ways. The old code here snapshotted one 64x64
        local board, so world coords indexed out to None and every write
        mutated a detached copy. Rebuilt only when the world's shape
        changes (gmap <-> house). Reads/writes are live regardless."""
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
        client's engine-event list. FourPlay's tclient_receivetext binding
        takes FOUR strings). The wire payload's FIRST token is the target
        WEAPON's name -- e.g. A join confirm is "-Serverlist_Chat,irc,join,
        #channel" (GServer-v2 ServerList.cpp:925-961 rewrites the weapon
        field per receiver. Its replies echo the weapon field from the
        request, PlayerRequestText.cpp. The C# client parses
        tokens[0]==weapon, [1]==type, [2]==option). The engine consumes the
        weapon token for routing and hands the script (texttype, textoption,
        textlines) -- which is why -Serverlist_Chat can gate texttype ==
        "irc". A prior revision bound texttype = tokens[0], so every real
        reply carried the weapon name as its texttype and no handler's gate
        ever matched. Replies addressed to a weapon we have route to it
        alone. Anything else (e.g. "GraalEngine", or a client-install weapon
        the server never sent us) broadcasts."""
        from ..packets import _guntokenize
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
            for joiner in waiting:
                self._flush_join_gated_events(joiner)
            # A class response is itself a coroutine wake-up source. Resume
            # here so a following join is requested before the next packet or
            # offline bytecode feed arrives.
            if waiting:
                self.process_coroutines(0.0)

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

        When we are outside the client's packet loop, pump the connection
        (bounded) until the script lands and load it inline, so findweapon()
        returns a live weapon object just as if it had been installed --
        Login3 then skips straight past its null-checks like the official
        client. From inside the packet loop (an event fired mid-update) we
        cannot recurse into update(). The request still goes out and the
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

    def is_class_loaded(self, classname: str) -> bool:
        cname = classname.lower()
        if cname in self.vms["class"]:
            return True
        stores = getattr(self.client, "gs2_bytecode", {}) if self.client else {}
        classes = stores.get("class", {}) if isinstance(stores, dict) else {}
        return cname in {to_str(key).lower() for key in classes}

    def load_class(self, classname: str) -> bool:
        """Request/store class bytecode without joining it to a caller."""
        if not classname or self.is_class_loaded(classname):
            return bool(classname)
        if self.client is None:
            return False
        try:
            return bool(self.client.request_class_bytecode(classname))
        except Exception:
            return False

    def join_class(self, vm: GS2VM, classname: str):
        """join("classname"): merge the class's functions into the joining
        VM. If the class bytecode is not here yet, request it (PLI_UPDATECLASS)
        and finish the join when it arrives."""
        cname = classname.lower()
        vm = self.owner_vm(vm)
        for j in vm.joined:
            if getattr(j, "_gs2_key", None) == cname:
                return True

        cvm = self.vms["class"].get(cname)
        if cvm is None:
            cvm = self._attach_cached_class(cname)
        if cvm is not None:
            self._attach_class(vm, cname, cvm)
            return True

        waiting = self._pending_joins.setdefault(cname, [])
        if vm not in waiting:
            waiting.append(vm)
        if self.client is not None:
            try:
                self.client.request_class_bytecode(classname)
            except Exception:
                pass
        if vm.call_is_suspendable:
            return _ClassJoinWait(self, vm, cname)
        return False

    def _attach_cached_class(self, classname: str) -> Optional[GS2VM]:
        """Load one class already present in the client's bytecode store.

        Packet receipt and VM loading are deliberately separate.  A join is
        the exception where the executing frame needs an available class
        immediately, so cache promotion and pending-join attachment are
        synchronous; only resuming parked generators may be deferred.
        """
        cname = to_str(classname).lower()
        cvm = self.vms["class"].get(cname)
        if cvm is not None or self.client is None:
            return cvm
        stores = getattr(self.client, "gs2_bytecode", {}) or {}
        classes = stores.get("class", {}) if isinstance(stores, dict) else {}
        blob = next((value for key, value in classes.items()
                     if to_str(key).lower() == cname and value), None)
        if blob is None:
            return None
        return self.load_bytecode("class", cname, blob)

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

    def _has_pending_joins(self, vm: GS2VM) -> bool:
        """Whether the script object owning *vm* still awaits any class."""
        if not isinstance(vm, GS2VM):
            return False
        key = self._timeout_key(self.owner_vm(vm))
        return any(any(self._timeout_key(self.owner_vm(joiner)) == key
                       for joiner in waiting)
                   for waiting in self._pending_joins.values())

    def _expire_join(self, vm: GS2VM, classname: str) -> None:
        """Resolve one failed download so queued entries may proceed."""
        owner = self.owner_vm(vm)
        waiting = self._pending_joins.get(classname)
        if waiting:
            self._pending_joins[classname] = [
                joiner for joiner in waiting if joiner is not owner]
            if not self._pending_joins[classname]:
                del self._pending_joins[classname]
        self._flush_join_gated_events(owner)

    def _flush_join_gated_events(self, vm: GS2VM) -> None:
        """Admit queued events, in arrival order, after the final join."""
        owner = self.owner_vm(vm)
        if self._has_pending_joins(owner):
            return
        key = self._timeout_key(owner)
        queued = self._join_gated_events.pop(key, [])
        for event, args in queued:
            current = self.vms.get(key[0], {}).get(key[1])
            if current is not None and current.has_function(event):
                self._run(current, event, *args)

    def _timeout_key(self, vm: GS2VM) -> tuple:
        """The (kind, key) identity a VM's settimer()/onTimeout state files
        under. A joined-class instance resolves to its joiner's own key
        (multiple joiners share one class's bytecode but never its timeout
        slot). A top-level weapon/npc/gani VM resolves to its own key."""
        return getattr(vm, "_gs2_owner",
                       (getattr(vm, "_gs2_kind", "weapon"),
                        getattr(vm, "_gs2_key", vm.name)))

    # -- events --------------------------------------------------------------

    def _run(self, vm: GS2VM, event: str, *args) -> None:
        from ..outbound import script_origin
        if getattr(vm, "_gs2_kind", "") == "gani":
            vm.this.mirror_wearer()
            vm._gs2_player = self._gani_player_object(vm._gs2_key)
            if not args and event.lower() != "oncreated":
                worn = self._gani_worn.get(vm._gs2_key)
                args = tuple(worn[1]) if worn is not None else ()
        key = self._timeout_key(vm)
        if self._has_pending_joins(vm):
            pending = self._join_gated_events.setdefault(key, [])
            if len(pending) >= PENDING_EVENT_CAP:
                dropped = pending.pop(0)
                logger.debug("GS2 %s join-gated queue full; dropped %s",
                             vm.name, dropped[0])
            pending.append((event, args))
            return
        if key in self._active_coro_keys:
            pending = self._pending_events.setdefault(key, [])
            if len(pending) >= PENDING_EVENT_CAP:
                dropped = pending.pop(0)
                logger.debug("GS2 %s pending-event queue full; dropped %s",
                             vm.name, dropped[0])
            pending.append((event, args))
            return
        with script_origin(getattr(vm, "_gs2_kind", "gs2"),
                           getattr(vm, "_gs2_key", vm.name), event):
            gen = vm.iter_call(event, *args)
            self._drive(gen, vm, key, event)

    def call_public_event(self, vm: GS2VM, event: str, *args) -> Any:
        """Enter a public cross-VM call through the event admission gate.

        Calls within the target VM's current event remain ordinary function
        calls; only a new entry from another script object is gated.
        """
        # Test doubles and host-owned callable objects have no runtime VM
        # identity and cannot own class joins.
        if not isinstance(vm, GS2VM):
            return vm.call(event, *args)
        source = self._executing_vm
        if (source is not None
                and self._timeout_key(source) == self._timeout_key(vm)):
            return vm.call(event, *args)
        if self._has_pending_joins(vm):
            self._run(vm, event, *args)
            return 0.0
        return vm.call(event, *args)

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

    def reset_session(self) -> None:
        """Discard execution frames and class waits owned by the session."""
        self._coros.clear()
        self._active_coro_keys.clear()
        self._pending_events.clear()
        self._join_gated_events.clear()
        self._pending_joins.clear()
        self._pending_bytecode.clear()
        self._join_timeout_warned.clear()
        self._processing_coroutines = False
        self._coroutine_wake_pending = False

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
                            "event": event, "wait": delay,
                            "remaining": (float(delay)
                                          if not isinstance(delay, VMCoroutineWait)
                                          else 0.0)})

    def process_coroutines(self, dt: float) -> None:
        """Resume scripts whose cooperative sleep has elapsed."""
        if self._processing_coroutines:
            self._coroutine_wake_pending = True
            return
        if not self._coros:
            return
        self._processing_coroutines = True
        try:
            self._process_coroutines(dt)
            while self._coroutine_wake_pending:
                self._coroutine_wake_pending = False
                self._process_coroutines(0.0)
        finally:
            self._processing_coroutines = False

    def _process_coroutines(self, dt: float) -> None:
        """Run one non-reentrant coroutine pass."""
        still = []
        finished = []
        for coro in self._coros:
            wait = coro.get("wait")
            if isinstance(wait, VMCoroutineWait):
                wait.pump()
                if not wait.ready():
                    still.append(coro)
                    continue
            else:
                coro["remaining"] -= dt
            if not isinstance(wait, VMCoroutineWait) and coro["remaining"] > 0:
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
                    delay = next(coro["gen"])
                    coro["wait"] = delay
                    coro["remaining"] = (float(delay)
                                         if not isinstance(delay, VMCoroutineWait)
                                         else 0.0)
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
        Preagonal/gbf/bytecode/login/_F2LogWindow.gs2bc.gs2:170-239. No C++
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
                # A not-yet-attached class may be the code that defines the
                # event, so pending joins take precedence over lookup.
                if self._has_pending_joins(vm) or vm.has_function(event):
                    self._run(vm, event, *args)
                    n += 1
        return n

    def trigger_weapon_event(self, weapon: str, event: str, *args) -> bool:
        vm = self.vms["weapon"].get(weapon.lower())
        if vm is not None and (self._has_pending_joins(vm)
                               or vm.has_function(event)):
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
        if vm is not None and (self._has_pending_joins(vm)
                               or vm.has_function(event)):
            self._run(vm, event, *args)
            return True
        return False

    def trigger_npc_wasshot(self, npc_id, by_player: bool, *args) -> bool:
        """Run one NPC ``wasshot`` event with reference-scoped attribution."""
        previous = self._shot_attribution
        self._shot_attribution = "player" if by_player else "baddy"
        try:
            return self.trigger_npc_event(npc_id, "wasshot", *args)
        finally:
            self._shot_attribution = previous

    def npc_has_event(self, npc_id, event: str) -> bool:
        """Return True if this NPC's VM defines the event.

        The touch handler uses this result as its gate.
        """
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
        definition. OnTimeout may still be defined on a joined class. Call()
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
        """Return True only if client.npcs contains this NPC.

        The NPC must also have a tag for a level other than the player's current
        level.
        """
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

        Only the caption positions are touched. Coordinates and indices stay
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
