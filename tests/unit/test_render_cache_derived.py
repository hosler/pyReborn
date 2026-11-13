"""Dropping the RenderCache changes no pixel.

Two games run the same scripted scene. One is untouched; the other gets a
fresh ``RenderCache()`` swapped in before every frame. This proves that
discarding the cache is safe: a cache whose loss changed a frame (state the
frame depended on) would make the two runs differ. It does not prove that a
cache invalidates correctly or that a live entry is never stale; the
per-field tests do that.
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from offline_game import NAMED_NPC
from pyreborn.game.render_cache import PARTICLE_CACHE_CAP, RenderCache
from pyreborn.lru import LruCache


def _digest(game):
    surf = game.screen
    return (surf.get_size(), pygame.image.tobytes(surf, "RGB"))


def _crowd(n):
    """Nickname-bearing NPCs with seven distinct names, so the plates need
    several different outlined-text surfaces in one frame."""
    npcs = []
    for i in range(n):
        spec = dict(NAMED_NPC)
        spec.update(id=200 + i, nickname=f"Guard {i % 7}",
                    x=24.0 + (i % 5) * 0.5, y=26.0 + (i % 3) * 0.25)
        npcs.append(spec)
    return npcs


def _scene(game, swap):
    """Walk, chat and let animations run, collecting one frame per step."""
    out = []
    game.client.player.chat = "hello there"
    for i in range(24):
        if swap:
            game.render_cache = RenderCache()
        game.client.player.x = 10.0 + (i % 12) * 0.25
        game.frames(1)
        out.append(_digest(game))
    return out


def test_swapping_in_a_fresh_render_cache_every_frame_changes_no_pixel(make_game):
    plain = _scene(make_game(npcs=_crowd(21)), swap=False)
    swapped = _scene(make_game(npcs=_crowd(21)), swap=True)
    assert len(plain) == len(swapped) == 24
    for i, (a, b) in enumerate(zip(plain, swapped)):
        assert a == b, "frame %d differs when the RenderCache is dropped" % i


def test_default_factories_build_the_call_site_types():
    cache = RenderCache()
    for name, cap in (("text_surf", 500), ("text_outline", 500), ("wrap", 300),
                      ("gani_layer", 2000), ("entity_alpha", 600),
                      ("npc_gani_split", 300), ("other_anim_split", 300),
                      ("npc_zoom", 100), ("particle_surf", PARTICLE_CACHE_CAP),
                      ("light_sprite", 300), ("showimg", 300)):
        held = getattr(cache, name)
        assert isinstance(held, LruCache), name
        assert held.max_entries == cap, name
    assert PARTICLE_CACHE_CAP == 400
    assert cache.prefetched_gani_names == set()
    assert cache.baddy_sheets == {}
    assert cache.nameplate_grid is None
    # Two instances never share a container.
    assert RenderCache().baddy_sheets is not cache.baddy_sheets
