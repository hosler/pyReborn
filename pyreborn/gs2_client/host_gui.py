"""Client-side GS2 package component."""

from __future__ import annotations

from reborn_protocol.gs2 import GS2Object
from reborn_protocol.gs2 import to_num
from reborn_protocol.gs2 import to_str
from .registry import GuiPopUpEditCtrl, _FALL_THROUGH, _GS2_GUI_METHODS, _GS2_POPUP_METHODS, _gs2_builtin

class HostGuiMixin:

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
