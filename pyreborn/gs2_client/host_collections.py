"""Client-side GS2 package component."""

from __future__ import annotations

from .registry import _GS2_LIST_METHODS, _GS2_STR_METHODS, _gs2_builtin, _gs2_sort_key

class HostCollectionsMixin:

    # -- _GS2_LIST_METHODS: methods on a plain Python list -------------------

    @_gs2_builtin(_GS2_LIST_METHODS, "sort")
    def _list_sort(self, vm, name, args, obj):
        obj.sort(key=_gs2_sort_key)
        return obj

    # -- _GS2_STR_METHODS: string methods the compiler leaves as calls -------

    @_gs2_builtin(_GS2_STR_METHODS, "lower", "lowercase", "upper", "uppercase")
    def _str_case(self, vm, name, args, obj):
        # `.lower()`/`.upper()` are the two the live corpus uses (Login's
        # staff sprite-editor weapon keys its per-gani default map on
        # `this.gdefault.(@def.lower())`).
        return obj.lower() if name in ("lower", "lowercase") else obj.upper()
