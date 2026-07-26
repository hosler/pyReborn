"""The single-bot scenario registry and the account-fixture path guards.

Registry: the suite membership used to be written out twice - once in
run_all_single_bot_tests() and once in tests/test_qa_pytest.py - so a scenario
added to one and forgotten in the other silently lost its coverage.
"""

import importlib.util
import inspect
from pathlib import Path

import pytest

# NB: import the modules, not the `TestScenarios`/`TestResult` names - binding
# either into this module's globals makes pytest's default `Test*` collection
# pick them up as test classes (see tests/test_qa_pytest.py's note).
from game_tester import reporter, test_scenarios
from game_tester.test_scenarios import (
    _DEFAULT_ACCOUNTS_DIR,
    _DEFAULT_PYGSERVER_ACCOUNTS_DIR,
    _resolve_accounts_dir,
    reset_account_chests,
    reset_account_position,
    single_bot_scenario,
    single_bot_scenarios,
)

QA_PYTEST_MODULE = Path(__file__).resolve().parents[1] / "test_qa_pytest.py"


def _load_qa_pytest_module():
    spec = importlib.util.spec_from_file_location("qa_pytest_registry_probe",
                                                  QA_PYTEST_MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

def test_registry_is_ordered_and_unambiguous():
    orders = [order for order, _ in test_scenarios._SINGLE_BOT_REGISTRY]
    assert len(orders) == len(set(orders))
    assert [fn for _, fn in sorted(test_scenarios._SINGLE_BOT_REGISTRY,
                                   key=lambda entry: entry[0])] == \
        single_bot_scenarios()


def test_registered_scenarios_are_the_TestScenarios_staticmethods():
    """Registry entries must be the same objects attribute access yields, or
    pytest's `ids=f.__name__` test ids would stop matching the CLI names."""
    for fn in single_bot_scenarios():
        assert getattr(test_scenarios.TestScenarios, fn.__name__) is fn
        assert list(inspect.signature(fn).parameters)[0] == "bot"


def test_duplicate_order_is_rejected_at_import_time():
    taken = test_scenarios._SINGLE_BOT_REGISTRY[0][0]
    with pytest.raises(ValueError, match="already used by"):
        single_bot_scenario(taken)(lambda bot: None)


def test_a_new_scenario_reaches_the_registry():
    free = max(order for order, _ in test_scenarios._SINGLE_BOT_REGISTRY) + 1000
    marker = single_bot_scenario(free)(lambda bot: None)
    try:
        assert single_bot_scenarios()[-1] is marker
    finally:
        test_scenarios._SINGLE_BOT_REGISTRY.remove((free, marker))


def test_cli_runner_runs_exactly_the_registry_in_order(monkeypatch):
    ran = []

    def fake(name):
        def scenario(bot):
            ran.append(name)
            return reporter.TestResult(name=name, passed=True, duration=0.0,
                                       details="", issues=[])
        return scenario

    scenarios = [fake("first"), fake("second")]
    monkeypatch.setattr(test_scenarios, "single_bot_scenarios",
                        lambda: scenarios)
    results = test_scenarios.TestScenarios.run_all_single_bot_tests(bot=None)
    assert ran == ["first", "second"]
    assert [result.name for result in results] == ["first", "second"]


def test_pytest_wrapper_reads_the_same_registry():
    assert _load_qa_pytest_module().SINGLE_BOT_SCENARIOS == \
        single_bot_scenarios()


# --------------------------------------------------------------------------
# Account-fixture paths
# --------------------------------------------------------------------------

def test_defaults_are_derived_from_this_checkout():
    checkout = Path(__file__).resolve().parents[2].parent
    assert _DEFAULT_PYGSERVER_ACCOUNTS_DIR == checkout / "pygserver" / "accounts"
    assert _DEFAULT_ACCOUNTS_DIR == (checkout / "GServer-v2" / "bin" /
                                     "servers" / "default" / "accounts")


def test_override_wins_when_it_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("QA_TEST_ACCOUNTS_DIR", str(tmp_path))
    assert _resolve_accounts_dir("QA_TEST_ACCOUNTS_DIR",
                                 Path("/nonexistent")) == str(tmp_path)


def test_override_that_points_nowhere_is_reported_not_replaced(monkeypatch,
                                                               capsys):
    monkeypatch.setenv("QA_TEST_ACCOUNTS_DIR", "/nonexistent/accounts")
    assert _resolve_accounts_dir("QA_TEST_ACCOUNTS_DIR", Path(".")) is None
    assert "QA_TEST_ACCOUNTS_DIR" in capsys.readouterr().err


def test_missing_default_disables_the_fixture(monkeypatch):
    monkeypatch.delenv("QA_TEST_ACCOUNTS_DIR", raising=False)
    assert _resolve_accounts_dir("QA_TEST_ACCOUNTS_DIR",
                                 Path("/nonexistent")) is None


def _isolate_account_dirs(monkeypatch, path):
    """Point BOTH account stores at a throwaway dir.

    Not optional: these helpers rewrite persisted account files, and the
    derived defaults are the real sibling checkouts on a dev machine.
    """
    monkeypatch.setenv("GSERVER_ACCOUNTS_DIR", str(path))
    monkeypatch.setenv("PYGSERVER_ACCOUNTS_DIR", str(path))


def test_reset_helpers_no_op_when_the_store_is_missing(tmp_path, monkeypatch):
    _isolate_account_dirs(monkeypatch, tmp_path / "gone")
    assert reset_account_chests("testbot1") is False
    assert reset_account_position("testbot1") is False


def test_reset_account_position_rewrites_an_existing_account(tmp_path,
                                                            monkeypatch):
    _isolate_account_dirs(monkeypatch, tmp_path)
    account = tmp_path / "testbot1.txt"
    account.write_text("GRACC001\r\nLEVEL chicken1.nw\r\nX 5\r\nY 6\r\n",
                       newline="")

    assert reset_account_position("testbot1", "onlinestartlocal.nw", 30, 30.5,
                                  mp=7) is True
    written = account.read_text(newline="")
    assert "LEVEL onlinestartlocal.nw" in written
    assert "X 30\r\n" in written and "Y 30.5\r\n" in written
    assert "MP 7" in written and "NICK testbot1" in written
    # pygserver's JSON twin lands in the same isolated dir.
    assert (tmp_path / "testbot1.json").exists()


def test_reset_account_chests_strips_only_loot_lines(tmp_path, monkeypatch):
    _isolate_account_dirs(monkeypatch, tmp_path)
    account = tmp_path / "testbot2.txt"
    account.write_text("GRACC001\nCHEST 1 2 lvl.nw\nX 5\n")

    assert reset_account_chests("testbot2") is True
    assert account.read_text() == "GRACC001\nX 5\n"
