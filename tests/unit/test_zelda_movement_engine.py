"""Client support for a fully script-driven movement engine (Zelda LTTP).

The live "Zelda: A Link to the Past" server (hastur.eevul.net:14912) hands the
client three weapons that ARE the game: `*System` draws the HUD,
`-Player/Functions` is a library published as a bare global, and
`-Player/Movement` calls `disabledefmovement()` and then drives walking,
collision, swimming, sitting and jumping itself from a 10 ms timer.

Three client gaps kept that from working; all three are covered here with no
server needed. Source references are to Preagonal/graal-lttp, the world's own
repository.

1. **Scripted layer colours.** GS2 assigns `findimg(i).red/.green/.blue/.alpha`, not GS1's packed `changeimgcolors` (-Player/Movement:155-160).
2. **Tile probes on a gmap.** Zelda passes world tile coordinates (0..640), while the GS1 host only knew a single 64x64 board.
3. **`tiletype()` itself** was not implemented (-Player/Movement:369-370, 451).
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pygame
import pytest

from pyreborn.game.render_entities import EntityRenderMixin, _layer_colors
from pyreborn.gs1_client import ClientGS1
from pyreborn.tiletypes import TileType


def test_changeimgcolors_still_wins():
    rec = {'colors': (0.5, 0.5, 0.5, 1.0), 'red': 1.0}
    assert _layer_colors(rec) == (0.5, 0.5, 0.5, 1.0)


def test_untouched_layer_has_no_colours():
    assert _layer_colors({'image': 'x.png'}) is None


def test_per_channel_writes_default_the_rest_to_one():
    """`findimg(2000).red = 1; .blue = .green = 0; .alpha = 0` — exactly what
    -Player/Movement:156-159 does."""
    rec = {'red': 1.0, 'green': 0.0, 'blue': 0.0, 'alpha': 0.0}
    assert _layer_colors(rec) == (1.0, 0.0, 0.0, 0.0)


def test_alpha_alone_keeps_full_rgb():
    assert _layer_colors({'alpha': 0.25}) == (1.0, 1.0, 1.0, 0.25)


def test_non_numeric_channel_falls_back_to_one():
    assert _layer_colors({'alpha': 'x'}) == (1.0, 1.0, 1.0, 1.0)


class _PolyHarness(EntityRenderMixin):
    """Just enough of GameClient for _render_showpoly_rec."""

    def __init__(self, surf):
        self.screen = surf

    @staticmethod
    def _layer_is_gui(rec):
        return True          # screen-pixel vertices, no camera needed


@pytest.fixture
def canvas():
    pygame.init()
    return pygame.Surface((64, 48))


def _fullscreen_quad(**extra):
    return {'poly': [0, 0, 64, 0, 64, 48, 0, 48],
            'vis': 15, 'vis_set': True, **extra}


def test_alpha_zero_fullscreen_quad_draws_nothing(canvas):
    """THE live bug: the world went white behind an invisible quad."""
    canvas.fill((10, 20, 30))
    _PolyHarness(canvas)._render_showpoly_rec(
        _fullscreen_quad(red=1.0, green=0.0, blue=0.0, alpha=0.0))
    assert canvas.get_at((32, 24))[:3] == (10, 20, 30)


def test_uncoloured_quad_still_fills_white(canvas):
    """Unchanged behaviour for a layer the script never coloured."""
    canvas.fill((10, 20, 30))
    _PolyHarness(canvas)._render_showpoly_rec(_fullscreen_quad())
    assert canvas.get_at((32, 24))[:3] == (255, 255, 255)


def test_faded_in_quad_tints_red(canvas):
    """As the player takes damage the script ramps `.alpha` up
    (-Player/Movement:128-129) — the flash must actually appear, in red."""
    canvas.fill((0, 0, 0))
    _PolyHarness(canvas)._render_showpoly_rec(
        _fullscreen_quad(red=1.0, green=0.0, blue=0.0, alpha=1.0))
    assert canvas.get_at((32, 24))[:3] == (255, 0, 0)


WALL_TILE = 511          # in the blocking range of tiletypes.py
WATER_TILE = 0x400       # deep water
CHAIR_TILE = None        # resolved below from the real table


def _first_tile_of_type(kind):
    from pyreborn.tiletypes import get_tile_type
    for tid in range(4096):
        if get_tile_type(tid) == kind:
            return tid
    raise AssertionError(f"no tile of type {kind}")


class _FakeClient:
    tiles = None
    npcs = {}
    players = {}
    level_links = {}


def _host(tile_source=None):
    rt = ClientGS1(_FakeClient())
    rt.tile_source = tile_source
    return rt


def test_without_a_tile_source_the_single_level_fallback_is_unchanged():
    client = _FakeClient()
    client.tiles = [0] * (64 * 64)
    client.tiles[10 * 64 + 5] = _first_tile_of_type(TileType.BLOCKING)
    rt = ClientGS1(client)
    assert rt.is_wall(5, 10) is True
    assert rt.is_wall(6, 10) is False
    # ...and a world coordinate off that board reads as open, the old
    # behaviour this fallback exists to preserve for standalone levels.
    assert rt.is_wall(319, 320) is False


def test_gmap_world_coordinates_reach_the_owning_segment():
    """With the game shell's resolver wired, a probe at a Zelda-scale world
    coordinate finds the real tile instead of falling off the board."""
    wall = _first_tile_of_type(TileType.BLOCKING)
    board = {(319, 320): wall}
    rt = _host(lambda x, y: board.get((int(x), int(y)), 0))
    assert rt.is_wall(319, 320) is True
    assert rt.is_wall(318, 320) is False


def test_unresolvable_gmap_cell_blocks():
    """A resolver returning -1 means "outside the world" (CollisionMixin's
    own convention) — the script must be told it is a wall, not open air."""
    rt = _host(lambda x, y: -1)
    assert rt.is_wall(999, 999) is True
    assert rt.is_water_at(999, 999) is False


def test_water_probe_uses_the_resolver():
    water = _first_tile_of_type(TileType.WATER)
    rt = _host(lambda x, y: water if (int(x), int(y)) == (300, 300) else 0)
    assert rt.is_water_at(300, 300) is True
    assert rt.is_water_at(301, 300) is False


def test_tiletype_returns_the_type_code():
    chair = _first_tile_of_type(TileType.CHAIR)
    rt = _host(lambda x, y: chair if (int(x), int(y)) == (12, 34) else 0)
    assert rt.tile_type_at(12, 34) == float(int(TileType.CHAIR))
    assert rt.tile_type_at(0, 0) == float(int(TileType.NONBLOCK))


def test_tiletype_builtin_is_callable_from_a_script():
    chair = _first_tile_of_type(TileType.CHAIR)
    rt = _host(lambda x, y: chair)
    val = rt._host.call_function("tiletype", [12.5, 34.5], None)
    assert val == float(int(TileType.CHAIR))
