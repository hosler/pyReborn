"""Lifecycle tests for the client-side chest item reveal (real offline game)."""

import pytest

from pyreborn.game.render_objects import LevelObjectsRenderMixin

CHEST = (8, 10)


@pytest.fixture
def harness(make_game, monkeypatch):
    game = make_game(chests=[(CHEST[0], CHEST[1], False)])
    level = game.client.current_level_name
    game.client.chest_items[level][CHEST] = "heart"
    played = []
    monkeypatch.setattr(game.sound_mgr, "play", played.append)
    game.played = played
    game.positions = []
    real = game._world_to_screen

    def spy(x, y):
        game.positions.append((x, y))
        return real(x, y)
    monkeypatch.setattr(game, "_world_to_screen", spy)
    game.level = level
    return game


def test_reveal_spawns_only_on_closed_to_open_transition(harness):
    harness._sync_chest_reveals(100)
    assert not getattr(harness, "_chest_reveals", [])

    harness.client.chests[harness.level][CHEST] = True
    harness._sync_chest_reveals(200)

    assert len(harness._chest_reveals) == 1
    assert harness._chest_reveals[0]["item_type"] == "heart"
    assert harness._chest_reveals[0]["started_ms"] == 200
    assert harness.played == ["chest.wav"]


def test_reveal_is_static_and_expires_after_24_ticks():
    reveal = {"started_ms": 100}

    assert LevelObjectsRenderMixin._chest_reveal_visual(reveal, 100) == (0.0, 255)
    assert LevelObjectsRenderMixin._chest_reveal_visual(reveal, 1250) == (0.0, 255)
    assert LevelObjectsRenderMixin._chest_reveal_visual(reveal, 1300) is None


def test_reveal_draw_position_is_centered_above_chest(harness):
    harness._sync_chest_reveals(0)
    harness.client.chests[harness.level][CHEST] = True
    harness.positions.clear()
    harness._render_chest_reveals(100)

    assert harness.positions == [(8.5, 9.0)]
