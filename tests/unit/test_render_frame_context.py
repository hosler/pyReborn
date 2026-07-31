"""The render pass tree, driven for real.

Nothing in pytest used to call a renderer through _render_entities: the whole
suite stayed green while the live client died on
``TypeError: _render_npc() takes 5 positional arguments but 6 were given``
after the FrameContext refactor split the entity pass into collectors and
draw adapters. These tests close that gap from both ends -- one drives a real
GameClient's entity pass with one of every entity kind on screen (so every
adapter->renderer edge is actually called), the rest pin the cross-pass state
FrameContext now owns (nameplate rects, deferred additive lights).

Kept honest by construction: the renderers are wrapped, not replaced, so the
real method still receives the real arguments.
"""

import os
import sys
import time
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

import pygame
import pytest

from pyreborn import Client
from pyreborn.game.frame_context import FrameContext
from pyreborn.game.render_entities import EntityRenderMixin
from pyreborn.pygame_game import GameClient

pygame.init()
# _render_showimg_rec's additive path calls convert_alpha(), which needs a
# video mode; the dummy driver above keeps it headless.
pygame.display.set_mode((64, 64))

RED = (255, 0, 0, 255)
BLACK = (0, 0, 0, 255)

# The character renderers reached by the populated fixture below.
ENTITY_RENDERER_NAMES = ('_render_player', '_render_other_player',
                         '_render_npc', '_render_baddy', '_render_horse')


@pytest.fixture(scope="module")
def game():
    """A real, fully composed GameClient, offline. The Client is never
    connected -- the entity pass only reads its state dicts.

    Not torn down with pygame.display.quit(): pygame.init() leaves the video
    system up for the whole session and other modules rely on that."""
    client = Client('127.0.0.1', 14900, version='6.037')
    return GameClient(client)


def _populate(game):
    """One of every entity kind, clustered around the camera so none is
    culled by _entity_on_screen."""
    client = game.client
    client.players.clear()
    client.npcs.clear()
    client.baddies.clear()
    client.horses.clear()
    client.chests.clear()
    client.items.clear()
    game.camera.set_center(32.0, 32.0)
    game.visual_x = game.visual_y = 32.0
    game._player_render_pos = (32.0, 32.0)
    client.players[7] = {'x': 31.0, 'y': 31.0, 'nick': 'bob', 'level': ''}
    client.npcs[3] = {'x': 32.0, 'y': 32.0, 'image': 'sign.png',
                      'nickname': 'sign'}
    client.baddies[1] = {'x': 33.0, 'y': 33.0, 'type': 0, 'mode': 2}
    client.horses['h1'] = {'x': 34.0, 'y': 34.0}


class TestEntityPass:
    def test_every_entity_kind_reaches_its_renderer(self, game):
        """Wraps each renderer so the call is recorded AND forwarded verbatim:
        an arity mismatch between a draw adapter and its renderer raises here
        exactly as it did in the live client."""
        _populate(game)
        seen = []
        for name in ENTITY_RENDERER_NAMES:
            real = getattr(game, name)

            def spy(*args, _name=name, _real=real, **kwargs):
                seen.append(_name)
                return _real(*args, **kwargs)

            setattr(game, name, spy)
        try:
            game._render_entities()
        finally:
            for name in ENTITY_RENDERER_NAMES:
                delattr(game, name)
        assert sorted(set(seen)) == sorted(ENTITY_RENDERER_NAMES)

    def test_pass_table_and_renderer_table_agree(self):
        kinds = [kind for kind, _collect, _render in
                 EntityRenderMixin._ENTITY_PASSES]
        assert list(EntityRenderMixin._ENTITY_RENDERERS) == kinds
        assert len(set(kinds)) == len(kinds)

    def test_entities_are_dispatched_in_depth_order(self, game):
        _populate(game)
        order = []
        wrapped = {}
        for kind, render in EntityRenderMixin._ENTITY_RENDERERS.items():
            def draw(self, ent, frame, _kind=kind, _render=render):
                order.append((_kind, ent.depth))
                return _render(self, ent, frame)
            wrapped[kind] = draw
        game._ENTITY_RENDERERS = wrapped
        try:
            game._render_entities()
        finally:
            del game._ENTITY_RENDERERS
        depths = [depth for _kind, depth in order]
        assert len(depths) == 5
        assert depths == sorted(depths)

    def test_npc_bands_override_bottom_edge_depth(self, game):
        _populate(game)
        game.client.players.clear()
        game.client.baddies.clear()
        game.client.horses.clear()
        game.npc_visual.clear()
        game.client.npcs.clear()
        game.client.npcs[1] = {
            'x': 32.0, 'y': 40.0, 'imagepart': (0, 0, 16, 16),
            'draw_layer': 'under',
        }
        game.client.npcs[2] = {
            'x': 32.0, 'y': 20.0, 'imagepart': (0, 0, 16, 16),
            'draw_layer': 'over',
        }
        order = []
        game._ENTITY_RENDERERS = {
            kind: (lambda self, ent, frame: order.append(
                (ent.kind, ent.data.get('draw_layer')
                 if isinstance(ent.data, dict) else None)))
            for kind in EntityRenderMixin._ENTITY_RENDERERS
        }
        try:
            game._render_entities()
        finally:
            del game._ENTITY_RENDERERS
        assert order == [('npc', 'under'), ('player', None), ('npc', 'over')]

    @pytest.mark.parametrize(
        ('kind', 'position', 'expected'),
        [
            ('chest', (32.0, 30.0), ['chest', 'player']),
            ('chest', (32.0, 34.0), ['player', 'chest']),
            ('item', (32.0, 33.0), ['item', 'player']),
            ('item', (32.0, 35.0), ['player', 'item']),
        ],
    )
    def test_ground_objects_compete_with_player_depth(self, game, kind,
                                                       position, expected):
        _populate(game)
        game.client.players.clear()
        game.client.npcs.clear()
        game.client.baddies.clear()
        game.client.horses.clear()
        sprite_size = (32, 32) if kind == 'chest' else (16, 16)
        sprite = pygame.Surface(sprite_size, pygame.SRCALPHA)
        game._get_chest_sprite = lambda opened: sprite
        game._get_item_sprite = lambda item_type: sprite
        if kind == 'chest':
            game.client.chests = {position: False}
        else:
            level_name = game.client.get_current_level_from_position()
            game.client.items.setdefault(level_name, {})[position] = 'greenrupee'
        order = []
        game._ENTITY_RENDERERS = {
            entity_kind: (lambda self, ent, frame: order.append(ent.kind))
            for entity_kind in EntityRenderMixin._ENTITY_RENDERERS
        }
        try:
            game._render_entities()
        finally:
            del game._ENTITY_RENDERERS
            del game._get_chest_sprite
            del game._get_item_sprite
        assert order == expected

    @pytest.mark.parametrize(
        ('bomb_y', 'expected'),
        [(31.0, ['deferred_world', 'player']),
         (35.0, ['player', 'deferred_world'])],
    )
    def test_bombs_compete_with_player_depth(self, game, bomb_y, expected):
        _populate(game)
        game.client.players.clear()
        game.client.npcs.clear()
        game.client.baddies.clear()
        game.client.horses.clear()
        game.client.chests.clear()
        game.client.items.clear()
        bomb_sprite = pygame.Surface((16, 16), pygame.SRCALPHA)
        bomb_sprite.fill(RED)
        game._get_effect_sprite = lambda filename: bomb_sprite
        game.active_bombs = [{
            'x': 32.0, 'y': bomb_y, 'time': time.time(),
            'fuse_time': 10.0, 'power': 1, 'exploded': False,
        }]
        frame = game._begin_frame()
        game._render_bombs(frame)
        order = []
        game._ENTITY_RENDERERS = {
            kind: (lambda self, ent, ctx: order.append(ent.kind))
            for kind in EntityRenderMixin._ENTITY_RENDERERS
        }
        try:
            game._render_entities(frame)
        finally:
            del game._ENTITY_RENDERERS
            del game._get_effect_sprite
        assert order == expected

    def test_frame_state_does_not_leak_back_onto_the_client(self, game):
        """The cross-pass lists live on FrameContext only. The old
        attribute mechanism (and its _in_gui_pass flag) must stay gone."""
        _populate(game)
        game._render_entities()
        for attr in ('_frame_nameplate_rects', '_frame_light_sources',
                     '_frame_light_draws', '_in_gui_pass'):
            assert not hasattr(game, attr), attr


class _BareHarness(EntityRenderMixin):
    """Just enough for _place_nameplate / the frame lifecycle."""


class TestNameplateStaggering:
    def test_overlapping_plates_stagger_within_one_frame(self):
        h = _BareHarness()
        frame = h._begin_frame()
        first = h._place_nameplate(100, 200, (40, 12), frame)
        second = h._place_nameplate(100, 200, (40, 12), frame)
        third = h._place_nameplate(100, 200, (40, 12), frame)
        assert first == (100, 200)
        assert second == (100, 214)   # nudged down by height + 2
        assert third == (100, 228)
        assert len(frame.nameplate_rects) == 3

    def test_a_new_frame_starts_with_no_placed_plates(self):
        h = _BareHarness()
        h._place_nameplate(100, 200, (40, 12), h._begin_frame())
        assert h._place_nameplate(100, 200, (40, 12),
                                  h._begin_frame()) == (100, 200)

    def test_idle_callers_share_one_accumulating_context(self):
        """Harnesses outside the render loop still stagger, the way the
        lazily-created list used to (see FrameContextMixin._frame_context)."""
        h = _BareHarness()
        assert h._place_nameplate(100, 200, (40, 12)) == (100, 200)
        assert h._place_nameplate(100, 200, (40, 12)) == (100, 214)


class _LightHarness(EntityRenderMixin):
    """The showimg slice of EntityRenderMixin, with a unit camera."""

    def __init__(self):
        self.screen = pygame.Surface((64, 64))
        self.screen.fill((0, 0, 0))
        self.camera = SimpleNamespace(
            scale=16.0,
            world_to_screen=lambda x, y: (x * 16.0, y * 16.0),
        )
        sheet = pygame.Surface((8, 8), pygame.SRCALPHA)
        sheet.fill(RED)
        self.sprite_mgr = SimpleNamespace(
            load_sheet=lambda name: sheet,
            get_sprite=lambda name, *part: sheet,
        )

    def _request_asset(self, name):
        pass


def _additive_rec():
    # mode 0 == additive (GServer-v2 object/ShowImg.h prop 8); world band, so
    # world_to_screen puts the 8x8 red square at (16, 16).
    return {'image': 'glow.png', 'x': 1.0, 'y': 1.0, 'vis': 1, 'mode': 0}


class TestDeferredLights:
    def test_additive_layer_waits_for_the_tint(self):
        h = _LightHarness()
        frame = h._begin_frame()
        h._render_showimg_rec(_additive_rec())
        assert h.screen.get_at((20, 20)) == BLACK
        assert len(frame.light_draws) == 1
        h._render_deferred_lights(frame)
        assert h.screen.get_at((20, 20)) == RED
        assert frame.light_draws == []

    def test_gui_band_blits_immediately(self):
        """The GUI band runs after the deferred flush, so a draw queued there
        would never be picked back up."""
        h = _LightHarness()
        frame = h._begin_frame()
        frame.gui_pass = True
        h._render_showimg_rec(_additive_rec())
        assert h.screen.get_at((20, 20)) == RED
        assert frame.light_draws == []

    def test_idle_callers_blit_immediately(self):
        h = _LightHarness()
        h._render_showimg_rec(_additive_rec())
        assert h.screen.get_at((20, 20)) == RED
        assert h._frame_context().light_draws == []

    def test_gui_pass_flag_is_cleared_even_if_a_layer_raises(self):
        h = _LightHarness()
        frame = h._begin_frame()

        def boom():
            raise RuntimeError("layer walk blew up")

        h._render_gui_layers_inner = boom
        with pytest.raises(RuntimeError):
            h._render_gui_layers(frame)
        assert frame.gui_pass is False


class TestFrameLifecycle:
    def test_begin_frame_replaces_the_previous_frame(self):
        h = _BareHarness()
        first = h._begin_frame()
        first.light_draws.append(('unflushed', 0, 0))
        second = h._begin_frame()
        assert second is not first
        assert second.light_draws == []
        assert h._frame_context() is second

    def test_idle_context_is_not_in_a_frame(self):
        h = _BareHarness()
        ctx = h._frame_context()
        assert isinstance(ctx, FrameContext)
        assert ctx.in_frame is False
        assert ctx.defer_light(object(), 0, 0) is False
        assert ctx.light_draws == []


class TestDeferredWorldObjects:
    def test_idle_bomb_renderer_blits_immediately(self, game):
        _populate(game)
        game._frame_ctx = FrameContext()
        game.screen.fill(BLACK)
        bomb_sprite = pygame.Surface((16, 16), pygame.SRCALPHA)
        bomb_sprite.fill(RED)
        game._get_effect_sprite = lambda filename: bomb_sprite
        game.active_bombs = [{
            'x': 32.0, 'y': 32.0, 'time': time.time(),
            'fuse_time': 10.0, 'power': 1, 'exploded': False,
        }]
        try:
            game._render_bombs()
        finally:
            del game._get_effect_sprite
        assert game.screen.get_bounding_rect().width > 0
        assert game._frame_context().world_draws == []

    def test_thrown_object_depth_uses_ground_at_top_of_arc(self, game):
        _populate(game)
        game.thrown_objects = [{
            'x': 32.0, 'y': 30.0, 'dx': 0.0, 'dy': 1.0,
            'speed': 1.0, 'dist': 0.0, 'range': 10.0,
            'z': 8.0, 'z0': 8.0, 'tiles': [0, 0, 0, 0],
        }]
        game.other_thrown_objects = []
        game._get_tile_at = lambda x, y: 0
        game._is_tile_blocking = lambda tile: False
        frame = game._begin_frame()
        try:
            game._update_and_render_thrown(0.0, frame)
        finally:
            del game._get_tile_at
            del game._is_tile_blocking
        assert len(frame.world_draws) == 1
        _draw, depth = frame.world_draws[0]
        # Ground y (30.0) plus the fixed 2-tile graphic. Sorting by the lifted
        # sprite instead would put the object 8 tiles higher in the order and
        # make it duck behind characters at the top of every arc.
        assert depth == 32.0
        assert depth != (30.0 - 8.0) + 2.0
