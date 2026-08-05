"""Client-side GS2 package component."""

from __future__ import annotations

from typing import Any
from reborn_protocol.gs2 import GS2Object
from reborn_protocol.gs2 import GS2VM
import time
from reborn_protocol.gs2 import to_num
from reborn_protocol.gs2 import to_str
from .objects_player import _CanvasObject, _engine_object
from .registry import GS2GuiManager, _gs2_object
from ..liftobjects import LIFT_SPRITES

class HostObjectsMixin:

    @_gs2_object("carriesnpc", "carriesbush", "carriessign", "carriesvase",
                 "carriesstone", "carriesblackstone")
    def _obj_carry_kind(self, name):
        player = getattr(self.rt2.client, "player", None)
        if player is None:
            return False
        if name == "carriesnpc":
            return bool(getattr(player, "carry_npc", 0))
        index = {"carriesbush": 0, "carriessign": 1, "carriesvase": 2,
                 "carriesstone": 3, "carriesblackstone": 4}[name]
        return getattr(player, "carry_sprite", 0) == LIFT_SPRITES[index]

    @_gs2_object("weaponsenabled")
    def _obj_weapons_enabled(self, name):
        gs1 = self.rt2.gs1
        return bool(getattr(gs1, "weapons_enabled", True))

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

    @_gs2_object("mousex", "mousey", "mousescreenx", "mousescreeny")
    def _obj_mouse_position(self, name):
        game = getattr(self.rt2, "game_shell", None)
        if game is None:
            return 0.0
        try:
            sx, sy = game.viewport.mouse_pos()
        except Exception:
            sx = sy = 0
        if name == "mousescreenx":
            return float(sx)
        if name == "mousescreeny":
            return float(sy)
        try:
            wx, wy = game.camera.screen_to_world(sx, sy)
        except Exception:
            wx = wy = 0.0
        return float(wx if name == "mousex" else wy)

    @_gs2_object("leftmousebutton")
    def _obj_left_mouse(self, name):
        try:
            import pygame
            return bool(pygame.mouse.get_pressed()[0])
        except Exception:
            return False

    @_gs2_object("focusx", "focusy", "isfocused")
    def _obj_focus(self, name):
        game = getattr(self.rt2, "game_shell", None)
        camera = getattr(game, "camera", None)
        if camera is None:
            player = getattr(self.rt2.client, "player", None)
            if name == "isfocused":
                return False
            return float(getattr(player, "x" if name == "focusx" else "y", 0.0) or 0.0)
        if name == "isfocused":
            return True
        return float(camera.center[0 if name == "focusx" else 1])

    @_gs2_object("isapplicationactive", "isopengl", "screenpixelscale",
                 "scriptedcontrols", "gravity", "canspin")
    def _obj_window_state(self, name):
        if name == "isopengl":
            # This client uses pygame's software/2D surface renderer.
            return False
        if name == "gravity":
            return float(self.rt2.gravity)
        if name == "scriptedcontrols":
            return True
        if name == "screenpixelscale":
            viewport = getattr(getattr(self.rt2, "game_shell", None), "viewport", None)
            return float(getattr(viewport, "_scale_x", 1.0) or 1.0)
        if name == "isapplicationactive":
            try:
                import pygame
                return bool(pygame.display.get_surface() is not None and pygame.display.get_active())
            except Exception:
                return False
        player = getattr(self.rt2.client, "player", None)
        if name == "canspin":
            return bool(getattr(player, "carry_sprite", None))
        return False

    @_gs2_object("shotbyplayer", "shotbybaddy", "wasshooted")
    def _obj_shot_event(self, name):
        attribution = getattr(self.rt2, "_shot_attribution", None)
        active = bool(attribution and getattr(self.rt2, "_executing_vm", None) is not None)
        if name == "wasshooted":
            return active
        return active and attribution == ("player" if name == "shotbyplayer" else "baddy")

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
