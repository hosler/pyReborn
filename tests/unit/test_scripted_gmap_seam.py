"""Scripted movement must announce GMAP seam crossings.

Client.move_to() notices when a step carries the player into a different gmap
cell and tells the server. A world whose movement is entirely script-driven
(`disabledefmovement()` + `player.x = ...` from the VM — Zelda LTTP's
-Player/Movement weapon) never calls move_to, so nothing announced the
crossing: the server kept us homed in the spawn segment, never streamed the
segments we walked into, and `_current_level_name` stayed pinned there while
the camera scrolled across the map.

Live evidence (hastur.eevul.net:14912, one 10x10 gmap): a 58-tile walk west
from `zlttp-e5.nw` ended at world x=251.5 — grid column 3, i.e. `zlttp-f5.nw`
— with the level name unchanged and `levels` still holding only the 9
segments from login. With the probe wired in, the same walk reports
`zlttp-e5.nw -> zlttp-f5.nw`, NPCs 4 -> 13 and 12 segments cached.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pytest

from pyreborn import Client
from pyreborn.packets import PacketID
from pyreborn.game.actions import ActionsMixin
from pyreborn.game.collision import CollisionMixin


class _Gs1Stub:
    default_movement = False


class _Harness(ActionsMixin, CollisionMixin):
    def __init__(self, client):
        self.client = client
        self.gs1 = _Gs1Stub()
        self.warped = []

    def _try_link_warp(self):
        self.warped.append((self.client.x, self.client.y))
        return False


def _client():
    c = Client("localhost", 14900)
    c._authenticated = True
    sent = []

    class _Stub:
        connected = True

        def send_packet(self, pid, data=b"", *a, **k):
            sent.append(pid)
            return True

    c._protocol = _Stub()
    c.sent_packets = sent
    # 3x3 grid, spawn segment at (1, 1) = world origin (64, 64).
    names = ["a.nw", "b.nw", "c.nw",
             "d.nw", "spawn.nw", "e.nw",
             "f.nw", "g.nw", "h.nw"]
    c.gmap_width, c.gmap_height = 3, 3
    for i, name in enumerate(names):
        c.gmap_grid[(i % 3, i // 3)] = name
    c._current_level_name = "spawn.nw"
    c.levels["spawn.nw"] = [0] * 4096
    c.tiles = c.levels["spawn.nw"]
    return c


def test_staying_in_the_same_cell_announces_nothing():
    c = _client()
    h = _Harness(c)
    c.player.x, c.player.y = 70.0, 70.0
    h._check_scripted_link_warp()
    c.sent_packets.clear()
    c.player.x, c.player.y = 80.0, 90.0        # still cell (1, 1)
    h._check_scripted_link_warp()
    assert PacketID.PLI_LEVELWARP not in c.sent_packets
    assert c._current_level_name == "spawn.nw"


def test_crossing_west_re_homes_us_in_the_new_segment():
    c = _client()
    h = _Harness(c)
    c.player.x, c.player.y = 70.0, 70.0
    h._check_scripted_link_warp()
    c.sent_packets.clear()
    c.player.x, c.player.y = 60.0, 70.0        # cell (0, 1) = "d.nw"
    h._check_scripted_link_warp()
    assert PacketID.PLI_LEVELWARP in c.sent_packets
    assert c._current_level_name == "d.nw"


def test_unknown_cell_says_nothing_and_does_not_re_probe():
    """Straight off the grid's edge: nothing to announce, and the cell is
    still latched so the next frame does not retry."""
    c = _client()
    h = _Harness(c)
    c.player.x, c.player.y = 70.0, 70.0
    h._check_scripted_link_warp()
    c.sent_packets.clear()
    c.player.x, c.player.y = 700.0, 70.0       # cell (10, 1): no segment
    h._check_scripted_link_warp()
    assert PacketID.PLI_LEVELWARP not in c.sent_packets
    assert c._current_level_name == "spawn.nw"
    assert h._scripted_gmap_cell == (10, 1)


def test_default_movement_worlds_are_untouched():
    """With the built-in movement engine, move_to() already does this. The
    probe must not fire a second announce."""
    c = _client()
    h = _Harness(c)
    h.gs1.default_movement = True
    c.player.x, c.player.y = 60.0, 70.0
    h._check_scripted_link_warp()
    assert PacketID.PLI_LEVELWARP not in c.sent_packets


def test_inside_a_house_local_coords_announce_nothing():
    """is_gmap stays True inside a standalone interior (house/cave) of a gmap
    world, but player coords there are LOCAL — the probe must not read them
    as world. Live regression (LTTP 2026-07-26): moving inside
    zlttp-linkshouse.nw announced grid cell (0,0) and the server warped the
    player to the gmap's top-left segment."""
    c = _client()
    h = _Harness(c)
    c._current_level_name = "linkshouse.nw"    # interior: not a grid member
    c.tiles = c.levels.setdefault("linkshouse.nw", [0] * 4096)
    c.player.x, c.player.y = 30.5, 38.0
    h._check_scripted_link_warp()
    c.player.x, c.player.y = 30.5, 37.5        # local step ≠ segment (0,0)
    h._check_scripted_link_warp()
    assert PacketID.PLI_LEVELWARP not in c.sent_packets
    assert c._current_level_name == "linkshouse.nw"


def test_non_gmap_worlds_are_untouched():
    c = _client()
    c.gmap_width = c.gmap_height = 0
    c.gmap_grid.clear()
    h = _Harness(c)
    c.player.x, c.player.y = 60.0, 70.0
    h._check_scripted_link_warp()
    assert PacketID.PLI_LEVELWARP not in c.sent_packets


def test_enter_gmap_segment_is_not_a_level_reset():
    """A seam hop keeps level state (unlike warp_to_level): the server just
    re-homes us and streams the newly-adjacent segments."""
    c = _client()
    c.npcs = {1: {"id": 1}}
    assert c.enter_gmap_segment("d.nw", 60.0 % 64, 70.0 % 64) is True
    assert c._current_level_name == "d.nw"
    assert c.npcs == {1: {"id": 1}}


def test_enter_gmap_segment_needs_a_live_session():
    c = _client()
    c._authenticated = False
    assert c.enter_gmap_segment("d.nw", 1.0, 1.0) is False
