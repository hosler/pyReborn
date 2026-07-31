"""The registry provides the dispatch table for Client._handle_packet.

Exactly one module-level function in this package handles each inbound PLO
packet ID. The `@handles(<PacketID>)` decorator registers the function. Thus,
the decorators contain the set of IDs that the client understands:

    grep -rn '@handles' pyreborn/handlers/

Client.HANDLED_PLO_IDS and the packet-coverage harness also read this set.
"""

from typing import Callable, Dict

# packet id (int) -> handler(client, data). Filled at import time by @handles;
# see handlers/__init__.py for the module list that must be imported for the
# table to be complete.
PACKET_HANDLERS: Dict[int, Callable] = {}


class _Stop:
    """Define the type of the STOP sentinel."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "STOP"


# A handler returns STOP to say it has fully consumed the packet, which makes
# Client._handle_packet skip the client.on_packet[id] custom handler. This
# reproduces the bare `return`s the old if/elif chain used mid-branch (only
# entities.handle_other_player_props does this - a player leaving our level, or
# a cross-level props update, never reached the custom-handler call at the
# bottom of _handle_packet).
STOP = _Stop()


def handles(*packet_ids) -> Callable:
    """Register the decorated function as the handler for `packet_ids`."""

    def decorate(fn: Callable) -> Callable:
        for packet_id in packet_ids:
            key = int(packet_id)
            existing = PACKET_HANDLERS.get(key)
            if existing is not None and existing is not fn:
                raise RuntimeError(
                    "packet id %d is already handled by %s.%s"
                    % (key, existing.__module__, existing.__qualname__))
            PACKET_HANDLERS[key] = fn
        return fn

    return decorate
