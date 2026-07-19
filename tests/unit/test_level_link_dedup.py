"""Regression test for PLO_LEVELLINK duplicate accumulation.

Re-entering a level the server has already streamed us (e.g. crossing a
GMAP segment boundary out and back, or any level preload/revisit) makes
the server re-send that level's full PLO_LEVELLINK set. The handler in
client.py used to append every parsed link unconditionally, so
client.links[level] grew a duplicate entry per revisit - confirmed live
via the playtest daemon crossing chicken1.nw -> chicken7.nw -> chicken1.nw
and chicken1's own links list gaining a second copy of one of its doors
(see game_tester/playtest_daemon.py's _current_links docstring, which used
to dedupe this on the read side as a workaround).

client.py now dedupes at insertion; identity is the parsed link's own
fields (dest_level/x/y/width/height/dest_x/dest_y).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

from pyreborn import Client
from pyreborn.packets import PacketID


def _fake_connected_client():
    c = Client("localhost", 14900)
    c._authenticated = True
    return c


def _link_packet(dest_level, x, y, w, h, dest_x, dest_y):
    """Raw PLO_LEVELLINK body: "destLevel x y width height newX newY"."""
    text = f"{dest_level} {x} {y} {w} {h} {dest_x} {dest_y}"
    return text.encode('latin-1')


class TestLevelLinkDedup:
    def test_single_link_stored(self):
        c = _fake_connected_client()
        c._current_level_name = "chicken1.nw"
        c._handle_packet(PacketID.PLO_LEVELLINK,
                          _link_packet("chicken7.nw", 62, 30, 2, 2, 1, 30))
        assert len(c.links["chicken1.nw"]) == 1

    def test_revisit_does_not_duplicate_identical_link(self):
        """Streaming the exact same link twice (level revisit) must not
        grow the list - this is the live repro."""
        c = _fake_connected_client()
        c._current_level_name = "chicken1.nw"
        link_bytes = _link_packet("chicken7.nw", 62, 30, 2, 2, 1, 30)

        c._handle_packet(PacketID.PLO_LEVELLINK, link_bytes)
        c._handle_packet(PacketID.PLO_LEVELLINK, link_bytes)
        c._handle_packet(PacketID.PLO_LEVELLINK, link_bytes)

        assert len(c.links["chicken1.nw"]) == 1

    def test_distinct_links_are_all_kept(self):
        """Different doors in the same level must not be collapsed into
        one another just because they share e.g. a dest_level."""
        c = _fake_connected_client()
        c._current_level_name = "chicken1.nw"

        c._handle_packet(PacketID.PLO_LEVELLINK,
                          _link_packet("chicken7.nw", 62, 30, 2, 2, 1, 30))
        c._handle_packet(PacketID.PLO_LEVELLINK,
                          _link_packet("chicken2.nw", 0, 30, 2, 2, 62, 30))
        # Same dest_level as the first, but a different rect - a distinct door.
        c._handle_packet(PacketID.PLO_LEVELLINK,
                          _link_packet("chicken7.nw", 0, 0, 2, 2, 1, 1))

        assert len(c.links["chicken1.nw"]) == 3

    def test_revisit_across_pending_and_current_level_name(self):
        """Full re-stream on entry uses _pending_level_name; a subsequent
        revisit that resolves through _current_level_name instead must
        still be recognized as the same level's link list."""
        c = _fake_connected_client()
        link_bytes = _link_packet("chicken7.nw", 62, 30, 2, 2, 1, 30)

        c._pending_level_name = "chicken1.nw"
        c._current_level_name = None
        c._handle_packet(PacketID.PLO_LEVELLINK, link_bytes)

        c._pending_level_name = None
        c._current_level_name = "chicken1.nw"
        c._handle_packet(PacketID.PLO_LEVELLINK, link_bytes)

        assert len(c.links["chicken1.nw"]) == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
