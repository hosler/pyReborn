"""Fixture-driven tests for movie gani parsing and timeline resolution."""

from pathlib import Path

import pytest

from pyreborn.game.render_entities import EntityRenderMixin
from pyreborn.gani import AnimationState, GaniParser, MoviePlaybackState


FIXTURE = Path(__file__).parents[1] / "fixtures" / "intromovie.gani"


@pytest.fixture
def movie():
    parser = GaniParser()
    gani = parser.parse_file(FIXTURE)
    assert gani is not None
    return gani, MoviePlaybackState(gani, parser)


def test_parse_movie_fixture(movie):
    gani, _playback = movie

    assert gani.is_movie
    assert gani.movie_length == 800
    assert len(gani.actors) == 48
    assert gani.defaults == {
        "ATTR1": "hat0.png",
        "HEAD": "head19.png",
        "BODY": "body.png",
    }
    assert gani.get_frame(2, 0) is None


def test_athenea_timeline(movie):
    _gani, playback = movie

    state = playback.actor_state("Athenea", 0)
    assert state is not None
    assert state.ani == "cn_walkslow"
    assert (state.dx, state.dy, state.direction) == (86, -64, 1)

    state = playback.actor_state("Athenea", 23)
    assert state is not None
    assert state.ani == "cn_idle"
    assert (state.dx, state.dy, state.direction) == (23, -55, 1)

    state = playback.actor_state("Athenea", 24)
    assert state is not None
    assert (state.dx, state.dy, state.direction) == (23, -55, 2)


def test_actor15_visibility_and_interpolation(movie):
    _gani, playback = movie

    assert playback.actor_state("Actor15", 200.99) is None

    state = playback.actor_state("Actor15", 203)
    assert state is not None
    assert state.dx == pytest.approx(-41.4)
    assert state.dy == 79

    assert playback.actor_state("Actor15", 207) is None


def test_movie_render_branch_tolerates_missing_actor_assets(movie):
    gani, _playback = movie
    parser = GaniParser()
    parser.put_cache(gani.name, gani)
    animation = AnimationState(parser)
    animation.set_animation(gani.name)

    class Harness(EntityRenderMixin):
        def __init__(self):
            self.requested = []

        def _request_asset(self, filename):
            self.requested.append(filename)

    harness = Harness()
    harness._render_movie(100, 200, animation)

    assert "cn_walkslow.gani" in harness.requested
