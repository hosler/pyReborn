"""RenderCache group B (effects and layers): each cache that has a key or an
invalidating event must miss when the key changes and draw the new content.

Every test names one mutation of the production code that fails a named
assertion; the mutation was applied, the test failed, and it was reverted.
A stale entry, or an invalidation that targets a dead attribute instead of
``game.render_cache``, fails here.
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import math
from types import SimpleNamespace

import pygame
import pytest

from offline_game import stub_art
from pyreborn.game.render_cache import PARTICLE_CACHE_CAP, RenderCache
from pyreborn.game.render_effects import EffectsRenderMixin
from pyreborn.particles import ParticleEmitter

BLACK = (0, 0, 0, 255)


def _solid(size, color):
    surf = pygame.Surface(size, pygame.SRCALPHA)
    surf.fill(color)
    return surf


def test_particle_capacity_has_one_source():
    assert RenderCache().particle_surf.max_entries == PARTICLE_CACHE_CAP == 400
    assert not hasattr(EffectsRenderMixin, "_PARTICLE_CACHE_CAP")


def test_combat_surface_is_keyed_by_screen_size(make_game):
    # Mutation: key = (name,) in _combat_surface -> fails "new size".
    game = make_game()
    first = game._combat_surface("probe")
    assert game._combat_surface("probe") is first
    game.screen = pygame.Surface((first.get_width() + 8, first.get_height() + 4))
    second = game._combat_surface("probe")
    assert second is not first
    assert second.get_size() == game.screen.get_size(), "new size"
    assert len(game.render_cache.combat_surface) == 2


def _particle_rec():
    rec = {'x': 50.0, 'y': 50.0, 'vis': 4, 'vis_set': True}
    emitter = ParticleEmitter(rec)
    emitter.set('emitautomatically', 0)
    emitter.set('nrofparticles', 1)
    emitter.get('particle').set('lifetime', 10)
    emitter.get('particle').set('image', 'dot.png')
    rec['emitter'] = emitter
    emitter.emit_now()
    return rec, emitter


def test_particle_surface_misses_when_alpha_changes(make_game, monkeypatch):
    # Mutation: drop `aq` from the key in _render_layer_emitter -> fails
    # "faded particle drawn at full alpha".
    game = make_game()
    stub_art(monkeypatch, game, _solid((8, 8), (255, 255, 255, 255)))
    rec, emitter = _particle_rec()
    game._render_layer_emitter(rec, emitter)
    full = game.screen.get_at((53, 53))
    assert full[:3] == (255, 255, 255)
    game.screen.fill((0, 0, 0))
    emitter.particles[0].alpha = 0.5
    game._render_layer_emitter(rec, emitter)
    faded = game.screen.get_at((53, 53))
    assert faded[0] < full[0], "faded particle drawn at full alpha"
    assert len(game.render_cache.particle_surf) == 2


def test_ripple_surface_is_keyed_by_radius(make_game):
    # Mutation: cache[radius] -> cache[0] in _ripple_surface -> fails "side".
    game = make_game()
    small = game._ripple_surface(3)
    assert game._ripple_surface(3) is small
    large = game._ripple_surface(9)
    assert large is not small
    assert large.get_size() == (20, 20), "side"
    assert set(game.render_cache.ripple_surface) == {3, 9}


def _night_game(make_game, minute):
    game = make_game()
    game._day_night_enabled = True
    game.screen_tint = None
    game.client.server_time = minute * 12   # (t * 5) // 60 == minute
    return game


def test_day_night_overlay_refills_when_the_ambient_colour_changes(make_game):
    # Mutation: in _render_screen_tint compare `size` only (cache_key = size)
    # -> fails "overlay not refilled for the new colour".
    game = _night_game(make_game, 100)
    game.screen.fill(BLACK)
    game._render_screen_tint()
    first_key = game.render_cache.day_night_overlay_key
    first_pixel = game.screen.get_at((5, 5))
    game.client.server_time = 1250 * 12
    game.screen.fill(BLACK)
    game._render_screen_tint()
    assert game.render_cache.day_night_overlay_key != first_key
    assert game.screen.get_at((5, 5)) != first_pixel, \
        "overlay not refilled for the new colour"


def test_day_night_overlay_is_rebuilt_at_the_new_screen_size(make_game):
    # Mutation: drop the `overlay.get_size() != size` test -> fails "size".
    game = _night_game(make_game, 100)
    game._render_screen_tint()
    old = game.render_cache.day_night_overlay_surface
    game.screen = pygame.Surface((old.get_width() + 16, old.get_height() + 16))
    game._render_screen_tint()
    new = game.render_cache.day_night_overlay_surface
    assert new is not old
    assert new.get_size() == game.screen.get_size(), "size"


def test_scripted_tint_overlay_refills_when_the_tint_changes(make_game):
    # Mutation: key the overlay by size only -> fails "tint colour change".
    game = make_game()
    game._day_night_enabled = False
    game.screen_tint = {'r': 255, 'g': 0, 'b': 0, 'a': 200}
    game.screen.fill(BLACK)
    game._render_screen_tint()
    red = game.screen.get_at((5, 5))
    assert red[0] > red[2]
    game.screen_tint = {'r': 0, 'g': 0, 'b': 255, 'a': 200}
    game.screen.fill(BLACK)
    game._render_screen_tint()
    blue = game.screen.get_at((5, 5))
    assert blue[2] > blue[0], "tint colour change"
    assert game.render_cache.tint_overlay_key[1] == (0, 0, 255, 200)


def test_tint_hole_scratch_is_rebuilt_at_the_new_screen_size(make_game):
    # Mutation: drop the `scratch.get_size() != size` test -> fails "size".
    game = make_game()
    lights = [(_solid((4, 4), (255, 255, 255, 255)), 2, 2)]
    frame = SimpleNamespace(light_sources=lights)
    size = game.screen.get_size()
    game._blit_tint_overlay(_solid(size, (0, 0, 0, 100)), size, frame)
    old = game.render_cache.tint_hole_scratch
    assert old.get_size() == size
    game.screen = pygame.Surface((size[0] + 8, size[1] + 8))
    size = game.screen.get_size()
    game._blit_tint_overlay(_solid(size, (0, 0, 0, 100)), size, frame)
    new = game.render_cache.tint_hole_scratch
    assert new is not old
    assert new.get_size() == size, "size"


def test_light_sprite_misses_when_the_alpha_changes(make_game):
    # Mutation: key = (id(sprite), None, False) in the non-light branch of
    # _render_light_sprite -> fails "alpha change served a stale sprite".
    game = make_game()
    sprite = _solid((4, 4), (255, 255, 255, 255))
    frame = SimpleNamespace(defer_light=lambda *_a: False)
    game.screen.fill(BLACK)
    game._render_light_sprite(sprite, 0, 0, False, (1.0, 1.0, 1.0, 1.0), frame)
    opaque = game.screen.get_at((1, 1))
    game.screen.fill(BLACK)
    game._render_light_sprite(sprite, 0, 0, False, (1.0, 1.0, 1.0, 0.25), frame)
    dim = game.screen.get_at((1, 1))
    assert dim[0] < opaque[0], "alpha change served a stale sprite"
    assert len(game.render_cache.light_sprite) == 2


def test_showimg_misses_when_the_layer_colours_change(make_game, monkeypatch):
    # Mutation: colors_key = None in _render_showimg_rec -> fails "recoloured
    # layer drawn from the stale entry".
    game = make_game()
    stub_art(monkeypatch, game, _solid((8, 8), (255, 255, 255, 255)))
    rec = {'image': 'dot.png', 'x': 50.0, 'y': 50.0, 'vis': 4,
           'vis_set': True, 'colors': (1.0, 1.0, 1.0, 1.0)}
    game._render_showimg_rec(rec)
    white = game.screen.get_at((53, 53))
    assert white[:3] == (255, 255, 255)
    game.screen.fill(BLACK)
    rec['colors'] = (1.0, 0.0, 0.0, 1.0)
    game._render_showimg_rec(rec)
    red = game.screen.get_at((53, 53))
    assert red[1] == 0, "recoloured layer drawn from the stale entry"
    assert len(game.render_cache.showimg) == 2


def test_showtext_font_is_keyed_by_name_size_and_bold(make_game):
    # Mutation: key = (name.lower(),) in _showtext_font -> fails "size".
    game = make_game()
    small = game._showtext_font("Arial", 10, False)
    assert game._showtext_font("ARIAL", 10, False) is small
    big = game._showtext_font("Arial", 24, False)
    assert big is not small
    assert big.get_height() > small.get_height(), "size"
    assert len(game.render_cache.showtext_fonts) == 2


def test_release_fonts_empties_the_showtext_font_cache(make_game):
    # Mutation: drop the clear() call in GameClient._release_fonts -> fails
    # "fonts survived release".
    game = make_game()
    game._showtext_font("Arial", 10, False)
    assert game.render_cache.showtext_fonts
    game._release_fonts()
    assert not game.render_cache.showtext_fonts, "fonts survived release"
