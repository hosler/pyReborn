"""
Pytest wrappers around the game_tester QA scenarios.

Covers the same ground as `python -m game_tester` (single-bot
TestScenarios + multi-bot visibility/pvp/chat), but against the throwaway
pygserver started by the `pygserver`/`bots` fixtures in conftest.py instead
of a hand-started, shared server - no account-state drift between runs.

Marked `integration` (see pyproject.toml); deselected by default addopts
only excludes `live`, so a bare `pytest` run *does* start the fixture
server and run these.
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


# Mirrors TestScenarios.run_all_single_bot_tests() (game_tester/test_scenarios.py),
# i.e. the "[SINGLE BOT TESTS]" section of `python -m game_tester`.
SINGLE_BOT_SCENARIOS = [
    test_scenarios.TestScenarios.test_connection,
    test_scenarios.TestScenarios.test_level_data,
    test_scenarios.TestScenarios.test_movement_all_directions,
    test_scenarios.TestScenarios.test_collision_detection,
    test_scenarios.TestScenarios.test_swimming_detection,
    test_scenarios.TestScenarios.test_walk_to_target,
    test_scenarios.TestScenarios.test_chat_roundtrip,
    test_scenarios.TestScenarios.test_sword_attack,
    test_scenarios.TestScenarios.test_item_detection,
    test_scenarios.TestScenarios.test_npc_visibility,
    test_scenarios.TestScenarios.test_file_download,
    test_scenarios.TestScenarios.test_chest_interaction,
    test_scenarios.TestScenarios.test_level_parsing,
]


@pytest.mark.parametrize("scenario", SINGLE_BOT_SCENARIOS,
                         ids=lambda f: f.__name__)
def test_single_bot_scenario(bots, scenario):
    bot = bots(1)[0]
    result = scenario(bot)
    assert result.passed, (
        f"{result.name} failed: {result.details}\nissues={result.issues}")


@pytest.fixture
def multi_bots(pygserver):
    """A connected 2-bot MultiBotTest (visibility/pvp/chat need two players)."""
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
