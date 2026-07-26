"""Dispatch table behind Client._handle_packet.

Every inbound PLO packet id is handled by exactly one module-level function
in this package, registered with `@handles(<PacketID>)`. The set of ids the
client understands is therefore exactly the set in those decorators:

    grep -rn '@handles' pyreborn/handlers/

which is also what Client.HANDLED_PLO_IDS / the packet-coverage harness read.
"""

from typing import Callable, Dict

# packet id (int) -> handler(client, data). Filled at import time by @handles;
# see handlers/__init__.py for the module list that must be imported for the
# table to be complete.
PACKET_HANDLERS: Dict[int, Callable] = {}


class _Stop:
    """Type of the STOP sentinel."""

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
