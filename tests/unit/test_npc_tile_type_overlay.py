"""A setshape2 array is a per-cell TILE TYPE table, not a blocking mask.

`TServerNPC::getTileType` indexes the array by the offset from the NPC's
origin and returns the cell verbatim
(Preagonal/FourPlay/quattroplay/src/TServerNPC.cpp:2016-2040);
`TServerLevel::getTileType` asks the level's NPCs BEFORE the board and lets any
answer above 1 override it (TServerLevel.cpp:688-708, searching via
getNPCTileType at :536-561).

We used to keep only the single value 22 (blocking), which is all the Bomber
arena's falling choc blocks needed. Everything else was dropped — including the
32 cells of type 3 (CHAIR) that classic Bomber's player-base room controller
paints over the whole 64x64 room with `setshape2 64,64,obj`. Live on
bomber.eevul.net that room's chair cells sit on board tiles of type 0, so the
board can never say "chair" and walking onto your own furniture did nothing.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

from pyreborn import Client
from pyreborn.game.actions import ActionsMixin
from pyreborn.game.collision import CollisionMixin
from pyreborn.gs1_client import ClientGS1
from pyreborn.tiletypes import TileType


class _SentRecorder:
    connected = True

    def __init__(self):
        self.sent = []

    def send_packet(self, packet_id, data=b""):
        self.sent.append((int(packet_id), bytes(data)))
        return True


def _engine(level="room0.nw", board_tile=0):
    c = Client("localhost", 14900)
    c._authenticated = True
    c._protocol = _SentRecorder()
    c._current_level_name = level
    c.tiles = [board_tile] * 4096
    c._tiles_level_name = level
    c.levels[level] = c.tiles
    return c, ClientGS1(c)


def _shape(gs1, client, npc_id, x, y, w, h, cells):
    """Run one NPC's `setshape2 w,h,{cells}` at (x, y)."""
    npc = client.npcs.setdefault(npc_id, {"x": float(x), "y": float(y),
                                          "script": ";"})
    npc["x"], npc["y"] = float(x), float(y)
    gs1.load_script("npc_%d" % npc_id, ";", npc_id=npc_id, x=x, y=y)
    gs1._update_shape_blocks(npc_id, npc, w, h, list(cells))


# -- the overlay itself ------------------------------------------------------

def test_a_chair_cell_is_published_as_a_tile_type():
    c, gs1 = _engine()
    _shape(gs1, c, 91, 10, 5, 2, 2, [0, 0, 3, 3])
    # Row-major from the NPC's origin: the 3s are the second row.
    assert gs1.npc_tile_type(10, 6) == TileType.CHAIR
    assert gs1.npc_tile_type(11, 6) == TileType.CHAIR
    assert gs1.npc_tile_type(10, 5) == 0
    # A fractional coordinate floors into its cell (the player's feet point
    # is never tile-aligned).
    assert gs1.npc_tile_type(10.75, 6.25) == TileType.CHAIR


def test_cells_at_or_below_one_do_not_override_the_board():
    # TServerLevel.cpp:694-696 takes the NPC answer only when it is > 1; the
    # room controller also parks private markers (-1..-9) in the same array.
    c, gs1 = _engine()
    _shape(gs1, c, 91, 0, 0, 3, 1, [0, 1, -7])
    assert [gs1.npc_tile_type(x, 0) for x in (0, 1, 2)] == [0, 0, 0]


def test_blocking_cells_still_reach_the_onwall_probe():
    # The pre-existing behaviour this generalises: 22 keeps blocking.
    c, gs1 = _engine()
    _shape(gs1, c, 91, 4, 4, 2, 1, [22, 0])
    assert (4, 4) in gs1._shape_blocks and (5, 4) not in gs1._shape_blocks
    assert gs1.is_wall(4, 4) is True
    assert gs1.npc_tile_type(4, 4) == TileType.BLOCKING


def test_rerunning_setshape2_replaces_the_npcs_own_cells():
    c, gs1 = _engine()
    _shape(gs1, c, 91, 10, 5, 2, 2, [0, 0, 3, 3])
    _shape(gs1, c, 91, 10, 5, 2, 2, [0, 0, 0, 0])
    assert gs1.npc_tile_type(10, 6) == 0
    assert gs1._shape_types == {}


def test_a_despawned_npc_leaves_another_npcs_overlapping_cell_intact():
    # Bomber's room0 has TWO 64x64 shape NPCs blanketing the same room.
    c, gs1 = _engine()
    _shape(gs1, c, 90, 0, 0, 1, 1, [22])
    _shape(gs1, c, 91, 0, 0, 1, 1, [3])
    gs1.forget_npc(91)
    assert gs1.npc_tile_type(0, 0) == TileType.BLOCKING
    gs1.forget_npc(90)
    assert gs1.npc_tile_type(0, 0) == 0


def test_clear_drops_the_overlay():
    c, gs1 = _engine()
    _shape(gs1, c, 91, 10, 5, 2, 2, [0, 0, 3, 3])
    gs1.clear()
    assert gs1.npc_tile_type(10, 6) == 0


# -- what the player actually feels ------------------------------------------

class _SitHarness(CollisionMixin, ActionsMixin):
    """Just enough GameClient for _update_sitting_state."""

    def __init__(self, client, gs1):
        self.client = client
        self.gs1 = gs1
        self.tile_corrections = {}
        self.is_swimming = False
        self.is_moving = False
        self.animations = {}

    # set_animation goes to the wire; the sit state is what we're asserting.
    def _noop(self, *a, **kw):
        return None


def _sitting_harness(chair_cells):
    c, gs1 = _engine()
    c.set_animation = lambda *a, **kw: None
    game = _SitHarness(c, gs1)
    if chair_cells:
        w = 2
        _shape(gs1, c, 91, chair_cells[0][0], chair_cells[0][1], w, 1,
               [TileType.CHAIR] * w)
    return c, gs1, game


def test_walking_onto_an_npc_chair_seats_the_player():
    # The live failure: the board says type 0 everywhere, only the NPC's
    # setshape2 array says chair.
    c, gs1, game = _sitting_harness([(20, 30)])
    assert game._get_corrected_tile_type(game._get_tile_at(20.5, 30.5)) == 0
    c.player.x = 20.5 - game.PLAYER_GROUND_DX
    c.player.y = 30.5 - game.PLAYER_GROUND_DY
    game._update_sitting_state()
    assert c.player.is_sitting is True


def test_leaving_the_npc_chair_stands_the_player_up():
    c, gs1, game = _sitting_harness([(20, 30)])
    c.player.x = 20.5 - game.PLAYER_GROUND_DX
    c.player.y = 30.5 - game.PLAYER_GROUND_DY
    game._update_sitting_state()
    assert c.player.is_sitting is True
    c.player.x += 4.0
    game._update_sitting_state()
    assert c.player.is_sitting is False


def test_the_sit_band_matches_the_official_ground_point():
    """A Bomber furniture chair is TWO tiles tall, and the sit test samples
    ONE point. Sampling it at PLAYER_STAND_Y (2.5) instead of the official
    (x+1.5, y+2.0) — `TPlayer::testSittingSleeping`,
    Preagonal/FourPlay/quattroplay/src/TPlayer.cpp:5925-5927 — shifted the
    seatable band half a tile up the screen: measured live on
    bomber.eevul.net 2026-07-26, a chair on rows 27-28 seated the player over
    y 24.50..26.375 instead of 25.00..26.875, so the bottom half-tile of every
    chair refused to seat him."""
    c, gs1 = _engine()
    c.set_animation = lambda *a, **kw: None
    game = _SitHarness(c, gs1)
    _shape(gs1, c, 91, 27, 27, 1, 2, [TileType.CHAIR, TileType.CHAIR])

    def sits(py):
        c.player.x = 27.5 - game.PLAYER_GROUND_DX
        c.player.y = py
        c.player.is_sitting = False
        game._update_sitting_state()
        return bool(c.player.is_sitting)

    # floor(y + 2.0) in {27, 28}  ->  y in [25.0, 27.0)
    assert sits(24.875) is False
    assert sits(25.0) is True
    assert sits(26.0) is True
    assert sits(26.875) is True          # the half-tile the old point lost
    assert sits(27.0) is False


def test_no_npc_overlay_means_the_board_still_decides():
    c, gs1, game = _sitting_harness([])
    c.player.x, c.player.y = 20.0, 30.0
    game._update_sitting_state()
    assert c.player.is_sitting is False


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
