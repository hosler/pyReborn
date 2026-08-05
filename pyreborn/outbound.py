"""Scoped attribution for outbound traffic initiated by client scripts."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Mapping


ENGINE_ORIGIN = {"engine": True, "kind": "engine", "name": "", "function": ""}
_outbound_origin: ContextVar[Mapping[str, Any]] = ContextVar(
    "pyreborn_outbound_origin", default=ENGINE_ORIGIN)


def current_outbound_origin() -> dict[str, Any]:
    """Return a detached copy of the current packet-origin description."""
    return dict(_outbound_origin.get())


@contextmanager
def script_origin(kind: str, name: Any, function: str) -> Iterator[None]:
    """Attribute sends made in this scope to one script VM invocation."""
    token = _outbound_origin.set({
        "engine": False,
        "kind": str(kind or "script"),
        "name": str(name or ""),
        "function": str(function or ""),
    })
    try:
        yield
    finally:
        _outbound_origin.reset(token)
