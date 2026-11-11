"""The PLPROP_COLORS (13) / NPCPROP_COLORS (19) width in force for a session.

One rule serves both directions, so what the client reads and what it writes
cannot disagree:

1. ``PLO_NEWWORLDMODE`` (177) received -> 8 bytes, and the width is *known*:
   the reference sends it before the first props packet when
   ``servermode = newworld`` (GServer-v2 Player.cpp:751-752), and that mode
   is what widens the prop (PropertySerializers.h:793-796).
2. ``PLO_KINGDOMSMODE`` (176) received -> 5 bytes (kingdoms is not new-world).
   Not "known": 176 was FULLSTOP in the older enum, so the parser may still
   correct it.
3. Otherwise the session's own parse evidence decides. Every props packet whose
   COLORS parsed cleanly at exactly one width counts as ``colors_seen_5`` or
   ``colors_seen_8`` (packet_codec.common._parse_with_colors_retry). The width
   with more sightings wins, so a server that writes 8 bytes without ever
   sending 177 is still followed.
4. With no evidence and no announcement the width is 5, the reference default
   (new-world off). ``SessionState.colors_len`` holds that prior.

The announcement is the only thing that makes a width "known"; its absence
proves nothing on its own.
"""

from reborn_protocol.props import COLORS_CLASSIC, COLORS_NEWWORLD


def colors_width_policy(client):
    """-> (colors_len, colors_len_known) for the session's COLORS props."""
    mode = getattr(client, 'server_mode', '')
    if mode == 'newworld':
        return COLORS_NEWWORLD, True
    if mode == 'kingdoms':
        return COLORS_CLASSIC, False
    diagnostics = getattr(client, 'prop_parse_diagnostics', None) or {}
    seen_8 = diagnostics.get(f'colors_seen_{COLORS_NEWWORLD}', 0)
    seen_5 = diagnostics.get(f'colors_seen_{COLORS_CLASSIC}', 0)
    if seen_8 > seen_5:
        return COLORS_NEWWORLD, False
    if seen_5 > seen_8:
        return COLORS_CLASSIC, False
    return client._colors_len, False


def colors_len_in_force(client) -> int:
    """Width to use when WRITING a COLORS prop on this connection."""
    return colors_width_policy(client)[0]
