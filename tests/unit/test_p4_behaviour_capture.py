"""Phase 4: the behaviour fingerprint's log capture after the swallow logging.

Mutations (each fails the named assertion):
  * make a DEBUG site (packet_codec/level.py parse_level_link) log at WARNING
    -> test_an_expected_failure_site_adds_no_kind
  * make log_swallowed's message a constant (no site name)
    -> test_a_real_swallow_adds_a_kind_naming_its_site
  * delete ``reset_swallowed()`` in _LogCapture.__init__
    -> test_kinds_do_not_depend_on_which_target_ran_first
  * delete the ``_SCRIPT_ERROR_PREFIX`` branch in _LogCapture.emit
    -> test_gs1_script_errors_stay_out_of_the_warning_kinds
"""
import logging

import pytest

from game_tester.behaviour_fingerprint import _LogCapture
from pyreborn import logutil


@pytest.fixture
def capture():
    made = []

    def _make():
        cap = _LogCapture()
        logging.getLogger().addHandler(cap)
        made.append(cap)
        return cap

    yield _make
    for cap in made:
        logging.getLogger().removeHandler(cap)
    logutil.reset_swallowed()


def _expected_failure():
    from pyreborn.packet_codec.level import parse_level_link
    parse_level_link(b"dest abc 1 2 3 4 5")


def _real_swallow():
    from pyreborn.gani import AnimationState, GaniParser

    def resolver(name):
        raise RuntimeError("bad resolver")

    anim = AnimationState(GaniParser())
    anim.name_resolver = resolver
    anim.set_animation("idle")


def test_an_expected_failure_site_adds_no_kind(capture):
    cap = capture()
    _expected_failure()
    assert cap.kinds == {} and cap.warnings == 0


def test_a_real_swallow_adds_a_kind_naming_its_site(capture):
    cap = capture()
    _real_swallow()
    kinds = list(cap.kinds)
    assert len(kinds) == 1
    assert kinds[0].startswith("pyreborn.gani|WARNING|")
    assert "AnimationState.set_animation" in kinds[0] or "set_animation" in kinds[0]


def test_kinds_do_not_depend_on_which_target_ran_first(capture):
    first = capture()
    _real_swallow()
    second = capture()  # the next target: a fresh capture
    _real_swallow()
    assert set(second.kinds) == set(first.kinds) != set()


def test_gs1_script_errors_stay_out_of_the_warning_kinds(capture):
    from pyreborn.gs1_client import registry
    registry._GS1_ERR_SEEN.clear()
    cap = capture()
    registry._report_gs1_error("command x", ValueError("boom"))
    registry._GS1_ERR_SEEN.clear()
    assert cap.kinds == {} and cap.warnings == 0
    assert cap.script_errors == 1
