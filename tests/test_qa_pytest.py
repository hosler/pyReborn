"""
Pytest wraps the game_tester QA scenarios.

The tests cover the same items as `python -m game_tester`. These items include
single-bot TestScenarios and multi-bot visibility/pvp/chat. The tests use the
temporary pygserver that the `pygserver`/`bots` fixtures in conftest.py start.
They do not use a manually started, shared server. Thus, account-state drift
does not occur between runs.

The tests have the `integration` mark (see pyproject.toml). The default addopts
deselect only `live`. Thus, a bare `pytest` run starts the fixture server and
runs these tests.
"""

import pytest

from game_tester.multi_bot import MultiBotTest
# NB: import the module, not the `TestScenarios` name directly - binding the
# class itself into this module's globals would make pytest's default
# `Test*` class collection pick it up a second time (its staticmethods take
# a positional `bot` arg, not a fixture, so that fails when pytest tries to
# collect it as a test class).
from game_tester import test_scenarios

pytestmark = pytest.mark.integration


# The suite registry itself (game_tester/test_scenarios.py's
# @single_bot_scenario), so this covers exactly the "[SINGLE BOT TESTS]"
# section of `python -m game_tester` - in the same order - instead of a
# hand-maintained copy of that list that could silently fall behind it.
SINGLE_BOT_SCENARIOS = test_scenarios.single_bot_scenarios()


@pytest.mark.parametrize("scenario", SINGLE_BOT_SCENARIOS,
                         ids=lambda f: f.__name__)
def test_single_bot_scenario(bots, scenario):
    bot = bots(1)[0]
    result = scenario(bot)
    assert result.passed, (
        f"{result.name} failed: {result.details}\nissues={result.issues}")


@pytest.fixture
def multi_bots(pygserver):
    """Create a connected two-bot MultiBotTest. Visibility/pvp/chat need two players."""
    test = MultiBotTest(2, pygserver.host, pygserver.port)
    if not test.connect_all(timeout=15.0):
        pytest.fail(f"multi-bot connect_all() failed: {pygserver.log_tail()}")
    yield test
    test.disconnect_all()


# Mirrors MultiBotTest.run_all_multi_tests(), i.e. the "[MULTI-BOT TESTS]"
# section of `python -m game_tester`.
def test_multi_bot_visibility(multi_bots):
    result = multi_bots.run_visibility_test()
    assert result.passed, (
        f"{result.name} failed: {result.details}\nissues={result.issues}")


def test_multi_bot_pvp_combat(multi_bots):
    result = multi_bots.run_pvp_test()
    assert result.passed, (
        f"{result.name} failed: {result.details}\nissues={result.issues}")


def test_multi_bot_chat(multi_bots):
    result = multi_bots.run_chat_test()
    assert result.passed, (
        f"{result.name} failed: {result.details}\nissues={result.issues}")
