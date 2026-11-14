"""Board lookups for a gmap segment ignore the case of the segment's name.

`level_at` returns the spelling the .gmap file gave, while `client.levels` is
keyed by the spelling the server sent, so every lookup that starts from the
grid goes through `gmap_coords.get_ci`.
"""

from reborn_protocol.coords import LEVEL_SIZE

from pyreborn import Client
from pyreborn.client_combat import CombatMixin
from pyreborn.game.collision import CollisionMixin
from pyreborn.game.render_world import WorldRenderMixin
from pyreborn.gs1_client.board import _board_list


class _Stub:
    def __getattr__(self, name):
        return lambda *a, **k: None


class _Harness(CollisionMixin):
    def __init__(self, client):
        self.client = client
        self.noclip = False
        self.active_bombs = []
        self.gs1 = None


def _client(*, grid_name="Foo.nw", server_name="foo.nw", tile=0):
    c = Client("localhost", 14900)
    c._authenticated = True
    c._protocol = _Stub()
    c.gmap_width, c.gmap_height = 1, 1
    c.gmap_grid[(0, 0)] = grid_name
    c._current_level_name = grid_name
    c.levels[server_name] = [tile] * 4096
    return c


def test_collision_reads_the_board_held_under_another_case():
    """Mutation: use `self.client.levels.get(seg)` in `_level_tiles_at`
    (exact lookup) -> no tiles, no collision."""
    c = _client(tile=1)
    h = _Harness(c)
    seg, tiles = h._level_tiles_at(5.5, 5.5)
    assert seg == "Foo.nw" and tiles is c.levels["foo.nw"]
    assert h._get_tile_at(5.5, 5.5) == 1


def test_standalone_collision_reads_the_board_under_another_case():
    """Mutation: exact `levels.get(name)` in the standalone branch."""
    c = _client(tile=1)
    c.gmap_grid.clear()
    c._current_level_name = "FOO.nw"
    assert _Harness(c)._level_tiles_at(5.5, 5.5)[1] is c.levels["foo.nw"]


def test_a_drawn_segment_finds_its_tiles_under_another_case():
    """Mutation: use `c.levels.get(level_name)` in `_segment_tiles`."""
    c = _client(tile=3)
    host = _Stub()
    host.client = c
    assert WorldRenderMixin._segment_tiles(host, "Foo.nw") is c.levels["foo.nw"]
    c.tiles = [9] * 4096
    c._tiles_level_name = "FOO.NW"
    del c.levels["foo.nw"]
    assert WorldRenderMixin._segment_tiles(host, "foo.nw") is c.tiles


def test_a_board_patch_lands_when_the_name_differs_in_case():
    """Mutation: use `self.levels.get(level_name)` in `_apply_board_modify`
    -> the cached board is not patched."""
    c = _client()
    c._tiles_level_name = "other.nw"    # the patched board is not the active one
    c._apply_board_modify("FOO.nw", {
        'layer': 0, 'x': 2, 'y': 3, 'width': 1, 'height': 1, 'tiles': [11]})
    assert c.levels["foo.nw"][3 * LEVEL_SIZE + 2] == 11


def test_the_bush_board_is_found_under_another_case():
    """Mutation: use `self.levels.get(level)` in `_bush_board`."""
    c = _client()
    c.player.x, c.player.y = 5.0, 5.0
    ox, oy = 0, 0
    level, board, got_ox, got_oy = CombatMixin._bush_board(c)
    assert board is c.levels["foo.nw"] and (got_ox, got_oy) == (ox, oy)


def test_the_script_board_list_is_found_under_another_case():
    """Mutation: use `levels.get(level_name)` in `_board_list`."""
    c = _client()
    assert _board_list(c, "Foo.nw") is c.levels["foo.nw"]
