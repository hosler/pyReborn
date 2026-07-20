"""Lifecycle tests for the client-side chest item reveal."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from pyreborn.game.render_objects import LevelObjectsRenderMixin


class _Client:
    _current_level_name = "test.nw"
    in_gmap_segment = False
    gmap_grid = {}

    def __init__(self):
        self.chests = {"test.nw": {(8, 10): False}}
        self.chest_items = {"test.nw": {(8, 10): "heart"}}

    def chests_in_level(self, level_name):
        return self.chests.get(level_name, {})


class _Harness(LevelObjectsRenderMixin):
    def __init__(self):
        self.client = _Client()
        self.screen = pygame.Surface((320, 240), pygame.SRCALPHA)
        self.positions = []

    def _world_to_screen(self, x, y):
        self.positions.append((x, y))
        return x * 16, y * 16


def test_reveal_spawns_only_on_closed_to_open_transition():
    harness = _Harness()
    harness._sync_chest_reveals(100)
    assert not getattr(harness, "_chest_reveals", [])

    harness.client.chests["test.nw"][(8, 10)] = True
    harness._sync_chest_reveals(200)

    assert len(harness._chest_reveals) == 1
    assert harness._chest_reveals[0]["item_type"] == "heart"
    assert harness._chest_reveals[0]["started_ms"] == 200


def test_reveal_rises_fades_and_expires():
    reveal = {"started_ms": 100}

    assert _Harness._chest_reveal_visual(reveal, 100) == (0.0, 255)
    halfway_rise, halfway_alpha = _Harness._chest_reveal_visual(reveal, 850)
    assert halfway_rise == 0.25
    assert halfway_alpha == 255

    late_rise, late_alpha = _Harness._chest_reveal_visual(reveal, 1400)
    assert 0.4 < late_rise < 0.5
    assert 0 < late_alpha < 255
    assert _Harness._chest_reveal_visual(reveal, 1600) is None


def test_reveal_draw_position_is_centered_above_chest():
    harness = _Harness()
    harness._sync_chest_reveals(0)
    harness.client.chests["test.nw"][(8, 10)] = True
    harness._render_chest_reveals(100)

    assert harness.positions == [(8.5, 9.0)]
