"""Client-side GS2 package component."""

from __future__ import annotations

from .registry import _GS2_VARS_METHODS, _gs2_builtin

class HostVarsMixin:

    # -- _GS2_VARS_METHODS: the dynamic-member (VariableCollection) surface --
    # Login's Staff weapons manage their caches with it:
    # `this.spritecache.clearvars()` per rebuild, and
    # `for (v: this.gdefault.getdynamicvarnames())` to walk one. Private
    # bookkeeping keys (leading "_", e.g. the layer store's "_findimg") are
    # engine-internal and stay hidden.

    @_gs2_builtin(_GS2_VARS_METHODS, "clearvars")
    def _vars_clearvars(self, vm, name, args, obj):
        for key in [k for k in obj._members if not str(k).startswith("_")]:
            del obj._members[key]
        return 0.0

    @_gs2_builtin(_GS2_VARS_METHODS, "copyfrom")
    def _vars_copyfrom(self, vm, name, args, obj):
        """Copy a script object through its reference-defined copy gate.

        Splatman's three uses have GuiTextProfile receivers.  Their
        ``copy_from`` override opts in and copies profile state; ordinary GUI
        controls override the same hook with the reference's silent no-op.
        """
        obj.copy_from(args[0] if args else None)
        return 0.0

    @_gs2_builtin(_GS2_VARS_METHODS, "getvarnames", "getdynamicvarnames")
    def _vars_getvarnames(self, vm, name, args, obj):
        return [key for key in obj._members
                if not str(key).startswith("_")
                and not callable(obj._members[key])]
