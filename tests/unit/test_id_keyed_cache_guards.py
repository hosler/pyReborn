"""Identity-guard regressions for caches keyed with object addresses."""

import os
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

from pyreborn.gani import Gani, GaniFrame, GaniSprite
from pyreborn.game.render_entities import EntityRenderMixin


def setup_module():
    pygame.init()


@pytest.mark.parametrize("is_light, coloreffect, variant", [
    (False, None, None),
    (True, (1.0, 1.0, 1.0, 1.0), 140),
])
def test_light_sprite_cache_rejects_a_different_source_surface(
        is_light, coloreffect, variant):
    source = pygame.Surface((2, 2))
    source.fill((20, 40, 60))
    stale_source = pygame.Surface((2, 2))
    stale_result = pygame.Surface((2, 2))
    stale_result.fill((200, 100, 50))
    key = (id(source), variant, is_light)
    harness = SimpleNamespace(
        screen=pygame.Surface((2, 2)),
        _light_sprite_cache={key: (stale_source, stale_result)},
        _LIGHT_ADDITIVE_ALPHA_CAP=140,
    )
    frame = SimpleNamespace(defer_light=lambda *_args: False)

    EntityRenderMixin._render_light_sprite(
        harness, source, 0, 0, is_light, coloreffect, frame,
    )

    cached_source, cached_result = harness._light_sprite_cache[key]
    assert cached_source is source
    assert cached_result is not stale_result
    assert harness.screen.get_at((0, 0))[:3] != (200, 100, 50)


def test_gani_layer_cache_rejects_a_different_source_gani():
    sprite = GaniSprite(1, "BODY", 0, 0, 16, 16)
    source = Gani("current", sprites={1: sprite})
    stale_source = Gani("stale")
    frame = GaniFrame([(1, 3, 4)])
    anim = SimpleNamespace(gani=source, direction=0, frame=0)
    key = (id(source), 0, 0, ())
    stale_result = [("shadow", 99, 99)]
    harness = SimpleNamespace(
        _gani_layer_cache={key: (stale_source, stale_result)},
    )

    resolved = EntityRenderMixin._resolve_gani_layers(
        harness, anim, frame, {},
    )

    cached_source, cached_result = harness._gani_layer_cache[key]
    assert cached_source is source
    assert cached_result is resolved
    assert resolved == [("sprite", "body.png", sprite, 3, 4, False)]
