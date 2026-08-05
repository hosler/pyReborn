"""Client-side GS2 package component."""

from __future__ import annotations

from typing import Any
from typing import Dict
from reborn_protocol.gs2 import GS2Host
from reborn_protocol.gs2 import GS2Object
from reborn_protocol.gs2 import GS2VM
from typing import List
from reborn_protocol.gs2 import NOT_HANDLED
from typing import Optional
from ..particles import ParticleEmitter
from ..particles import ParticleModifier
from reborn_protocol.gs1.runtime import UNSET
from .objects_player import _CanvasObject, _EngineObject
from .registry import GS2GuiManager, GuiControl, GuiPopUpEditCtrl, _FALL_THROUGH, _GS1_COMMANDS, _GS1_FUNCTIONS, _GS1_LEVEL_PROBES, _GS2_ANY, _GS2_BARE, _GS2_BARE_GUI, _GS2_ENGINE_METHODS, _GS2_GUI_METHODS, _GS2_LIST_METHODS, _GS2_OBJECTS, _GS2_OBJ_METHODS, _GS2_PARTICLE_METHODS, _GS2_POPUP_METHODS, _GS2_STR_METHODS, _GS2_TABLES, _GS2_VARS_METHODS
from .host_any import HostAnyMixin
from .host_collections import HostCollectionsMixin
from .host_engine import HostEngineMixin
from .host_gui import HostGuiMixin
from .host_objmethods import HostObjmethodsMixin
from .host_particles import HostParticlesMixin
from .host_vars import HostVarsMixin
from .host_bare import HostBareMixin
from .host_objects import HostObjectsMixin

class GS2ClientHost(HostAnyMixin, HostCollectionsMixin, HostEngineMixin, HostGuiMixin, HostObjmethodsMixin, HostParticlesMixin, HostVarsMixin, HostBareMixin, HostObjectsMixin, GS2Host):
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
        """Return built-ins that this host or the real GS1 host handles.

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
            from ..game.gs2_gui import control_method_names
            names |= control_method_names()
        GS2ClientHost._surface_cache = frozenset(names) | GS2ClientHost.stubbed
        return GS2ClientHost._surface_cache

    # -- infrastructure ----------------------------------------------------

    def get_globals(self) -> Dict[str, Any]:
        return self.rt2.globals_store

    def get_object(self, name: str) -> Optional[GS2Object]:
        """Resolve a bare name to an object (or plain value -- the VM pushes
        whatever comes back. See vm.py _lookup / _op_conv_to_object).

        Named engine objects/globals come from the _GS2_OBJECTS registry. A
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
        from ..outbound import script_origin
        if vm is not None:
            with script_origin(getattr(vm, "_gs2_kind", "gs2"),
                               getattr(vm, "_gs2_key",
                                       getattr(vm, "name", type(vm).__name__)),
                               name):
                return self._call_builtin_attributed(vm, name, args, obj)
        return self._call_builtin_attributed(vm, name, args, obj)

    def _call_builtin_attributed(self, vm: GS2VM, name: str, args: List[Any],
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
                return rt2.call_public_event(wvm, name, *args)
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
