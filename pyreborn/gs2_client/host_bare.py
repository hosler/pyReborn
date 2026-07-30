"""Client-side GS2 package component."""

from __future__ import annotations

from reborn_protocol.gs2 import GS2Object
import math
import time
from reborn_protocol.gs2 import to_num
from reborn_protocol.gs2 import to_str
from .helpers import _csv_flatten
from .objects_player import PLATFORM_NAME, _engine_object
from .registry import GS2GuiManager, TIMER_RESOLUTION, _GS1_PURE, _GS2_BARE, _GS2_BARE_GUI, _TIMER_CANCEL, _WORD_BORDER, _gs2_builtin, logger

class HostBareMixin:

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
