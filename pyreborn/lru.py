"""A size-bounded least-recently-used cache.

One class serves ``client.levels`` / the file caches and the render and script
caches. Several of the latter used to empty themselves wholesale once they
passed a size, so a working set just over the cap rebuilt every entry every
cycle. ``LruCache`` keeps the bound but drops only the entry unused longest.
It is a dict, so call sites keep their ``get`` / ``[]`` / ``in`` / ``len`` /
``clear`` idiom.

Recency: a hit through ``[]`` or ``get`` always marks the entry recent, and a
store marks it recent. Whether ``in`` also does is explicit:
``refresh_on_contains`` (default True, the behaviour the client caches have
always had, so ``if name in levels: levels[name]`` keeps one touch either way)."""

from collections import OrderedDict
from typing import Any, Hashable


class LruCache(OrderedDict):
    """OrderedDict holding at most ``capacity`` entries (``capacity >= 1``)."""

    def __init__(self, capacity: int, *, refresh_on_contains: bool = True):
        super().__init__()
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self.capacity = capacity
        self.refresh_on_contains = refresh_on_contains

    @property
    def max_entries(self) -> int:
        """The old BoundedLRU name for ``capacity``."""
        return self.capacity

    def __getitem__(self, key: Hashable) -> Any:
        value = super().__getitem__(key)
        self.move_to_end(key)
        return value

    def get(self, key: Hashable, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key: Hashable) -> bool:
        present = super().__contains__(key)
        if present and self.refresh_on_contains:
            self.move_to_end(key)
        return present

    def __setitem__(self, key: Hashable, value: Any) -> None:
        super().__setitem__(key, value)
        self.move_to_end(key)
        while len(self) > self.capacity:
            self.popitem(last=False)
