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
    assert day_night_tint(0) == (5, 5, 35, 155)


def test_dusk_is_warm_and_subtle():
    tint = day_night_tint(19 * 60 + 30)
    assert tint[:3] == (255, 120, 55)
    assert 25 <= tint[3] <= 45


def test_curve_boundaries():
    assert day_night_tint(18 * 60) is None
    assert day_night_tint(7 * 60) is None
    assert day_night_tint(22 * 60) == (10, 10, 45, 110)


def test_deep_night_is_darker_than_late_evening():
    assert day_night_tint(2 * 60 + 30)[3] > day_night_tint(22 * 60)[3]


def test_dawn_is_pinkish():
    red, green, blue, alpha = day_night_tint(5 * 60)
    assert red > blue > green
    assert 0 < alpha < 100


def test_evening_alpha_rises_monotonically_to_midnight():
    alphas = [day_night_tint(minute)[3] for minute in range(20 * 60, 24 * 60, 15)]
    alphas.append(day_night_tint(0)[3])
    assert alphas == sorted(alphas)
    assert max(alphas) <= 160
