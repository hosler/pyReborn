"""`_place_nameplate` against the flat O(n^2) scan it replaced.

REFERENCE is the placement as it was: every new plate is `colliderect`-tested
against every plate already placed and nudged down one box height + 2 until it
clears. The grid-backed version must return the same position for every plate
and leave the same rects in `nameplate_rects`, for any input order."""

import random
from types import SimpleNamespace

import pygame
import pytest
from hypothesis import given, settings, strategies as st

from pyreborn.game.render_text import RenderTextMixin

SCREEN_W, SCREEN_H = 1920, 1080
GUARD = 20000        # a reference that spins longer than this never terminates


def reference_place(rects, name_x, name_y, size):
    w, h = size
    rect = pygame.Rect(int(name_x), int(name_y), int(w), int(h))
    spins = 0
    while any(rect.colliderect(r) for r in rects):
        rect.y += h + 2
        spins += 1
        if spins > GUARD:
            raise RecursionError("reference does not terminate")
    rects.append(rect)
    return rect.x, rect.y


class Placer(RenderTextMixin):
    def __init__(self):
        self.frame = SimpleNamespace(nameplate_rects=[])

    def _frame_context(self):
        return self.frame

    def place(self, x, y, size):
        return self._place_nameplate(x, y, size, self.frame)


def both(plates):
    """Run one plate list through both; None when the reference never ends."""
    ref_rects, ref_out = [], []
    try:
        for x, y, size in plates:
            ref_out.append(reference_place(ref_rects, x, y, size))
    except RecursionError:
        return None
    placer = Placer()
    new_out = [placer.place(x, y, size) for x, y, size in plates]
    return ref_out, new_out, ref_rects, placer.frame.nameplate_rects


def assert_same(plates):
    got = both(plates)
    if got is None:
        return
    ref_out, new_out, ref_rects, new_rects = got
    assert new_out == ref_out
    assert [tuple(r) for r in new_rects] == [tuple(r) for r in ref_rects]


def plate_lists(rng, n, mode):
    plates = []
    for _ in range(n):
        size = (rng.randint(8, 140), rng.randint(8, 18))
        if mode == "cluster":
            x, y = rng.randint(900, 960), rng.randint(500, 520)
        elif mode == "same":
            x, y = 400.5, 300.25
        elif mode == "edges":
            x = rng.choice((-200, -1, 0, 1, SCREEN_W - 1, SCREEN_W, SCREEN_W + 80))
            y = rng.choice((-50, 0, 1, SCREEN_H - 14, SCREEN_H, SCREEN_H + 60))
        elif mode == "tall":
            x, y = rng.randint(0, 3000), rng.randint(0, 40)
        else:
            x, y = rng.uniform(-100, SCREEN_W + 100), rng.uniform(-100, SCREEN_H + 100)
        plates.append((x, y, size))
    return plates


@pytest.mark.parametrize("n", [0, 1, 2, 500])
@pytest.mark.parametrize("mode", ["cluster", "same", "edges", "tall", "spread"])
def test_sizes_and_modes(n, mode):
    for seed in range(12 if n < 500 else 2):
        assert_same(plate_lists(random.Random(f"{mode}{n}{seed}"), n, mode))


def test_many_random_sets():
    rng = random.Random(1234)
    for i in range(400):
        mode = rng.choice(["cluster", "same", "edges", "tall", "spread"])
        assert_same(plate_lists(rng, rng.randint(0, 80), mode))


def test_degenerate_sizes_match():
    """Zero and negative boxes, a box wider than the screen, mixed with
    normal ones in both orders."""
    sizes = [(0, 0), (0, 12), (30, 0), (-20, 12), (30, -4), (-5, -5),
             (1, 1), (4000, 12), (60, 1100), (60, 14)]
    rng = random.Random(77)
    for _ in range(300):
        plates = [(rng.randint(-30, 300), rng.randint(-30, 120),
                   rng.choice(sizes)) for _ in range(rng.randint(1, 25))]
        assert_same(plates)


@settings(max_examples=400, deadline=None)
@given(st.lists(st.tuples(
    st.floats(-3000, 5000, allow_nan=False, allow_infinity=False),
    st.floats(-3000, 5000, allow_nan=False, allow_infinity=False),
    st.tuples(st.integers(-10, 300), st.integers(-3, 40))), max_size=60))
def test_hypothesis_arbitrary_plates(plates):
    assert_same(plates)


@settings(max_examples=300, deadline=None)
@given(st.lists(st.tuples(
    st.integers(0, 80), st.integers(0, 40),
    st.tuples(st.integers(1, 90), st.integers(1, 16))), min_size=0, max_size=120))
def test_hypothesis_dense_small_area(plates):
    """Everything inside a few cells, the worst case for stagger chains and
    for cell-boundary mistakes."""
    assert_same(plates)


def test_plate_appended_behind_the_index_is_seen():
    placer = Placer()
    placer.place(10, 10, (50, 14))
    placer.frame.nameplate_rects.append(pygame.Rect(200, 200, 50, 14))
    assert placer.place(205, 205, (50, 14)) == (205, 221)


def test_new_frame_starts_empty():
    placer = Placer()
    first = placer.place(10, 10, (50, 14))
    placer.frame = SimpleNamespace(nameplate_rects=[])
    assert placer.place(10, 10, (50, 14)) == first
