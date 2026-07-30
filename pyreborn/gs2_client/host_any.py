"""Client-side GS2 package component."""

from __future__ import annotations

from reborn_protocol.gs2 import GS2Object
import math
from reborn_protocol.gs2 import to_num
from reborn_protocol.gs2 import to_str
from .registry import GuiControl, _GS2_ANY, _gs2_builtin

class HostAnyMixin:

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
