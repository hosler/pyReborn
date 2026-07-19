import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from pyreborn.game.render_effects import day_night_tint


def _minute_of_day(server_time):
    return ((server_time * 5) // 60) % 1440


def test_server_time_to_minute_of_day():
    assert _minute_of_day(0) == 0
    assert _minute_of_day(12 * 60 * 12) == 720
    assert _minute_of_day(24 * 60 * 12 + 75 * 12) == 75


def test_day_and_night_tints():
    assert day_night_tint(12 * 60) is None
    assert day_night_tint(0) == (10, 10, 45, 110)


def test_transition_midpoints():
    assert day_night_tint(6 * 60) == (10, 10, 45, 55)
    assert day_night_tint(20 * 60) == (10, 10, 45, 55)


def test_curve_boundaries():
    assert day_night_tint(5 * 60) == (10, 10, 45, 110)
    assert day_night_tint(7 * 60) is None
    assert day_night_tint(19 * 60) == (10, 10, 45, 0)
    assert day_night_tint(21 * 60) == (10, 10, 45, 110)
