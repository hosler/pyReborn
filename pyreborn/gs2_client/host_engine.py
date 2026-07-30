"""Client-side GS2 package component."""

from __future__ import annotations

from reborn_protocol.gs2 import to_num
from reborn_protocol.gs2 import to_str
from .registry import _GS2_ENGINE_METHODS, _gs2_builtin

class HostEngineMixin:

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
