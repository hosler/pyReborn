"""Inbound (PLO) packet handlers, grouped by domain.

| module      | packets                                                    |
|-------------|------------------------------------------------------------|
| level       | level naming/transitions, boards + deltas, links, signs,   |
|             | chests, gmap metadata                                      |
| entities    | our player props, other players, NPCs, baddies, items      |
| files       | file downloads (incl. the large-file chunk protocol)       |
| scripts     | weapons, GS1/GS2 script + bytecode transport, triggeractions |
| combat      | hurt/projectiles/explosions and the bomb/arrow/horse relay |
| chat        | chat, PMs and server-pushed text windows                   |
| session     | handshake/session flags and server-control packets         |

Each handler is `handle_x(client, data)`; it mutates `client` state and fires
the matching `client.on_*` callback. Returning `registry.STOP` suppresses
`client.on_packet` for that packet (see registry.STOP).
"""

from .registry import PACKET_HANDLERS, STOP, handles

# Imported for the @handles registration side effect. Registration order is
# irrelevant (ids are unique and the registry rejects a collision), but a
# module that is not imported here has its packets silently unhandled.
from . import chat, combat, entities, files, level, scripts, session  # noqa: E402,F401

__all__ = ["PACKET_HANDLERS", "STOP", "handles"]
