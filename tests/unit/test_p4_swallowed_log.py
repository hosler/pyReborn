"""Phase 4: swallowed exceptions are logged once per site, not dropped.

Mutations (each fails the named assertion):
  * delete ``log_swallowed(logger)`` in gani.py AnimationState.set_animation
    (the name_resolver handler)
    -> test_a_real_swallow_site_logs_through_its_module_logger
  * make log_swallowed skip the ``_SEEN`` test (log every call)
    -> test_a_repeat_from_the_same_site_is_silent
  * key ``_SEEN`` on the raising frame (``tb`` innermost line) instead of the
    handler frame -> test_two_handlers_failing_through_one_callee_both_log
  * call ``traceback.extract_tb(tb)`` before the ``_SEEN`` test
    -> test_the_seen_path_extracts_no_traceback
  * change ``level=logging.DEBUG`` back to the default at
    packet_codec/level.py parse_level_link
    -> test_expected_failure_sites_do_not_reach_warning
  * put the old ``print(..., file=sys.stderr)`` back in _report_gs1_error
    -> test_gs1_script_errors_go_to_logging
"""
import linecache
import logging
import traceback

import pytest

from pyreborn import logutil
from pyreborn.gs1_client import registry
from pyreborn.logutil import log_swallowed

LOG = logging.getLogger("test_p4_swallowed_log")


@pytest.fixture(autouse=True)
def _fresh_sites():
    logutil.reset_swallowed()
    yield
    logutil.reset_swallowed()


def _fail():
    try:
        {}["missing"]
    except Exception:
        return log_swallowed(LOG)


def _callee():
    raise ValueError("shared callee")


def _site_one():
    try:
        _callee()
    except Exception:
        return log_swallowed(LOG)


def _site_two():
    try:
        _callee()
    except Exception:
        return log_swallowed(LOG)


def test_a_repeat_from_the_same_site_is_silent(caplog):
    with caplog.at_level(logging.WARNING, logger=LOG.name):
        results = [_fail() for _ in range(50)]
    assert results[0] is True
    assert results[1:] == [False] * 49
    assert len(caplog.records) == 1
    assert "KeyError" in caplog.records[0].getMessage()
    assert caplog.records[0].exc_info is not None


def test_two_handlers_failing_through_one_callee_both_log(caplog):
    with caplog.at_level(logging.WARNING, logger=LOG.name):
        assert _site_one() is True
        assert _site_two() is True
        assert _site_one() is False
    names = [r.getMessage() for r in caplog.records]
    assert len(names) == 2
    assert any("_site_one" in m for m in names)
    assert any("_site_two" in m for m in names)


def test_the_seen_path_extracts_no_traceback(monkeypatch):
    _fail()  # first call logs and marks the site seen

    touched = []

    def spy(*args, **kwargs):
        touched.append(1)
        return []

    monkeypatch.setattr(traceback, "extract_tb", spy)
    monkeypatch.setattr(traceback, "format_exception", spy)
    monkeypatch.setattr(linecache, "getlines", spy)
    monkeypatch.setattr(linecache, "updatecache", spy)
    monkeypatch.setattr(linecache, "checkcache", spy)
    assert _fail() is False
    assert touched == []


def test_no_active_exception_logs_nothing(caplog):
    with caplog.at_level(logging.WARNING, logger=LOG.name):
        assert log_swallowed(LOG) is False
    assert caplog.records == []


def test_a_real_swallow_site_logs_through_its_module_logger(caplog):
    from pyreborn.gani import AnimationState, GaniParser

    def resolver(name):
        raise RuntimeError("bad resolver")

    anim = AnimationState(GaniParser())
    anim.name_resolver = resolver
    with caplog.at_level(logging.WARNING, logger="pyreborn.gani"):
        anim.set_animation("idle")
    assert [r.name for r in caplog.records] == ["pyreborn.gani"]
    assert caplog.records[0].levelno == logging.WARNING
    assert "set_animation" in caplog.records[0].getMessage()


def test_expected_failure_sites_do_not_reach_warning(caplog):
    from pyreborn.packet_codec.level import parse_level_link
    bad = b"dest abc 1 2 3 4 5"  # seven fields, the second not a number
    with caplog.at_level(logging.WARNING, logger="pyreborn.packet_codec.level"):
        assert parse_level_link(bad) == {}
    assert caplog.records == []
    logutil.reset_swallowed()
    with caplog.at_level(logging.DEBUG, logger="pyreborn.packet_codec.level"):
        assert parse_level_link(bad) == {}
    assert [r.levelno for r in caplog.records] == [logging.DEBUG]


def test_gs1_script_errors_go_to_logging(caplog, capsys):
    registry._GS1_ERR_SEEN.clear()
    with caplog.at_level(logging.WARNING, logger=registry.logger.name):
        registry._report_gs1_error("command x", ValueError("boom"))
        registry._report_gs1_error("command x", ValueError("boom"))
    assert len(caplog.records) == 1
    assert "[GS1] command x: ValueError: boom" in caplog.records[0].getMessage()
    assert "[GS1]" not in capsys.readouterr().err
    registry._GS1_ERR_SEEN.clear()
