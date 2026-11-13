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

import pytest

from offline_game import GMAP_SEGMENTS, IMAGE_NPC
from pyreborn.packets import PacketID

SPAWN = GMAP_SEGMENTS[3]       # grid (1, 1) = world origin (64, 64)
WEST = GMAP_SEGMENTS[2]        # grid (0, 1)


@pytest.fixture
def seam_game(make_game):
    """``seam_game(**knobs)``: (client, game) on the fixture's 2x2 gmap,
    spawned in segment (1, 1) with the movement engine OFF (scripted)."""
    def build(**knobs):
        knobs.setdefault("gmap", True)
        knobs.setdefault("gmap_segment", (1, 1))
        game = make_game(**knobs)
        game.gs1.default_movement = False
        return game.client, game
    return build


def sent_ids(c):
    return [pid for pid, _ in c._protocol.sent]


#: A seam crossing announces itself with the PLAIN level warp, even though the
#: preloaded neighbour is held: the reference sends no warp for a hop inside
#: its map, and a mod-time warp would make the server resend the board.
WARPS = (PacketID.PLI_LEVELWARP,)


def warped(c):
    return any(pid in WARPS for pid in sent_ids(c))


def test_staying_in_the_same_cell_announces_nothing(seam_game):
    c, h = seam_game()
    c.player.x, c.player.y = 70.0, 70.0
    h._check_scripted_link_warp()
    c._protocol.sent.clear()
    c.player.x, c.player.y = 80.0, 90.0        # still cell (1, 1)
    h._check_scripted_link_warp()
    assert not warped(c)
    assert c._current_level_name == SPAWN


def test_crossing_west_re_homes_us_in_the_new_segment(seam_game):
    c, h = seam_game()
    c.player.x, c.player.y = 70.0, 70.0
    h._check_scripted_link_warp()
    c._protocol.sent.clear()
    c.player.x, c.player.y = 60.0, 70.0        # cell (0, 1)
    h._check_scripted_link_warp()
    assert warped(c)
    assert c._current_level_name == WEST


def test_unknown_cell_says_nothing_and_does_not_re_probe(seam_game):
    """Straight off the grid's edge: nothing to announce, and the cell is
    still latched so the next frame does not retry."""
    c, h = seam_game()
    c.player.x, c.player.y = 70.0, 70.0
    h._check_scripted_link_warp()
    c._protocol.sent.clear()
    c.player.x, c.player.y = 700.0, 70.0       # cell (10, 1): no segment
    h._check_scripted_link_warp()
    assert not warped(c)
    assert c._current_level_name == SPAWN
    assert h._scripted_gmap_cell == (10, 1)


def test_default_movement_worlds_are_untouched(seam_game):
    """With the built-in movement engine, move_to() already does this. The
    probe must not fire a second announce."""
    c, h = seam_game()
    h.gs1.default_movement = True
    c._protocol.sent.clear()
    c.player.x, c.player.y = 60.0, 70.0
    h._check_scripted_link_warp()
    assert not warped(c)


def test_inside_a_house_local_coords_announce_nothing(seam_game):
    """is_gmap stays True inside a standalone interior (house/cave) of a gmap
    world, but player coords there are LOCAL — the probe must not read them
    as world. Live regression (LTTP 2026-07-26): moving inside
    zlttp-linkshouse.nw announced grid cell (0,0) and the server warped the
    player to the gmap's top-left segment."""
    c, h = seam_game(extra_levels={"linkshouse.nw": None})

    async def enter_house(world):
        await world.me.warp("linkshouse.nw", 30.5, 38.0)    # not a grid member
    h.server.run(enter_house)
    assert c._current_level_name == "linkshouse.nw"
    c._protocol.sent.clear()
    c.player.x, c.player.y = 30.5, 38.0
    h._check_scripted_link_warp()
    c.player.x, c.player.y = 30.5, 37.5        # local step != segment (0,0)
    h._check_scripted_link_warp()
    assert not warped(c)
    assert c._current_level_name == "linkshouse.nw"


def test_non_gmap_worlds_are_untouched(make_game):
    h = make_game()
    h.gs1.default_movement = False
    c = h.client
    assert not c.gmap_width
    c._protocol.sent.clear()
    c.player.x, c.player.y = 60.0, 70.0
    h._check_scripted_link_warp()
    assert not warped(c)


def test_enter_gmap_segment_is_not_a_level_reset(seam_game):
    """A seam hop keeps level state (unlike warp_to_level): the server just
    re-homes us and streams the newly-adjacent segments."""
    c, _ = seam_game(npcs=[IMAGE_NPC])
    before = dict(c.npcs)
    assert before
    assert c.enter_gmap_segment(WEST, 60.0 % 64, 70.0 % 64) is True
    assert c._current_level_name == WEST
    assert c.npcs == before


def test_enter_gmap_segment_needs_a_live_session(seam_game):
    c, _ = seam_game()
    c._authenticated = False
    assert c.enter_gmap_segment(WEST, 1.0, 1.0) is False
