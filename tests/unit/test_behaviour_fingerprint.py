"""Offline tests for the behavioural-fingerprint comparison.

The two fixtures are REAL captures of the public Login server taken with
game_tester/behaviour_fingerprint.py:

  fingerprint_login_good.json    the fixed tree (9 GUI roots, 90 named
                                 controls, 3 weapon VMs), re-captured
                                 2026-07-25 once player.platform was
                                 implemented -- while unset it took the
                                 iPhone setTimer(1) branch
                                 (weapon-Rescripted_Serverlist.txt:403-425),
                                 so the counts were 1 Hz, not 20 Hz.
  fingerprint_login_broken.json  the same server observed with the
                                 object-vs-null `gs2_compare` regression
                                 re-introduced -- 4 roots, 3 named controls,
                                 and the legacy -Serverlist/-ServerListScreen/
                                 -IRC_Login3 fallback path loaded instead
  fingerprint_login_emptylist.json
                                 the 2026-07-25 outage: the server list is
                                 EMPTY. `serverstartconnect` was unanswered,
                                 so it resolved to Number 0.0 and compared
                                 equal to every word. InitServerlist() took
                                 `serverstartconnect == "skills"` and
                                 auto-connected instead of requesting the
                                 list. Structurally almost identical to the
                                 good capture -- which is why the harness
                                 passed 25/25 over it before `tree_nodes` /
                                 `controls_filled` existed.
  fingerprint_login_layout.json  the Global Chat window with GuiFrameSetCtrl
                                 unimplemented: EVERY count matches the good
                                 capture exactly, and only the geometry
                                 invariants move.

so "does the harness still catch THE outage?" is answerable without a
network, and stays answerable after someone re-baselines. (If a rebaseline is
ever taken from a broken client, the broken fixture starts passing and this
file fails -- which is the point.)
"""

import json
from pathlib import Path

import pytest

from game_tester.behaviour_fingerprint import (
    METRIC_BANDS, METRIC_LABELS, band_for, compare, default_pins, load_baselines,
    make_entry, target_for, Target, _event_views, _metric)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _fixture(name):
    return json.loads((FIXTURES / f"fingerprint_{name}.json").read_text())


@pytest.fixture(scope="module")
def login_baseline():
    baselines = load_baselines()
    entry = baselines["servers"].get("Login")
    assert entry is not None, "the checked-in Login behaviour baseline vanished"
    return entry


def _failed(results):
    return {result.name for result in results if not result.passed}


# --- the regression this suite exists for ----------------------------------


def test_broken_login_capture_fails_the_baseline(login_baseline):
    results = compare(_fixture("login_broken"), login_baseline)
    failed = _failed(results)
    # The whole GUI was never built...
    assert {"gui_roots", "gui_named", "gui_controls", "gui_depth",
            "controls_present", "control_classes"} <= failed
    # ...because the script took the legacy branch, which loads weapons the
    # modern path never does.
    assert "weapons_forbidden" in failed
    assert "weapon_vms" in failed


def test_broken_login_failures_say_what_moved(login_baseline):
    results = {result.name: result for result in
               compare(_fixture("login_broken"), login_baseline)}
    roots = results["gui_roots"]
    assert not roots.passed
    assert roots.actual == "4"
    # 11 on 2026-07-25 when the capture started opening the menu-driven Global
    # Chat window (Target.open_ui), 9 since the 2026-07-31 rebaseline: the
    # nine NAMED roots are identical either way (globalchat_window and its
    # channel menu included, so the opener still runs) -- what moved is two
    # anonymous transient roots, which is ordinary churn and not a lost window.
    assert roots.baseline == "9"
    assert ".." in roots.expected              # a band, not a magic number
    forbidden = results["weapons_forbidden"]
    assert "-serverlist" in forbidden.actual
    assert "-serverlistscreen" in forbidden.actual


def test_good_login_capture_passes_the_baseline(login_baseline):
    assert _failed(compare(_fixture("login_good"), login_baseline)) == set()


# --- the 2026-07-25 outage: an EMPTY server list ---------------------------


def test_empty_server_list_is_caught(login_baseline):
    failed = _failed(compare(_fixture("login_emptylist"), login_baseline))
    assert "tree_nodes" in failed
    assert "controls_filled" in failed


def test_empty_server_list_was_invisible_to_the_structural_invariants(
        login_baseline):
    """The reason this fixture exists.

    Every count the harness had BEFORE content metrics -- roots, named,
    controls, depth, weapon VMs, events, host calls, warnings -- is inside
    its band for a Login screen that lists no servers at all. If this ever
    starts failing on a structural invariant, great. But it must never stop
    failing on the content ones.
    """
    results = {r.name: r for r in
               compare(_fixture("login_emptylist"), login_baseline)}
    structural = ("gui_roots", "gui_named", "gui_controls", "gui_depth",
                  "weapon_vms", "controls_present", "control_classes",
                  "no_new_warnings", "no_new_gaps", "weapons_forbidden",
                  "event_kinds", "stayed_connected")
    assert all(results[name].passed for name in structural), \
        [name for name in structural if not results[name].passed]
    assert results["tree_nodes"].actual == "0"
    assert results["tree_nodes"].baseline != "0"


def test_collapsed_frame_set_layout_is_caught(login_baseline):
    """Global Chat with GuiFrameSetCtrl unimplemented.

    Counts alone cannot see this at all: the fixture has the same roots,
    named controls, control total, tree nodes and list rows as the healthy
    capture. Only geometry moves.
    """
    results = {r.name: r for r in
               compare(_fixture("login_layout"), login_baseline)}
    assert not results["nonzero_area"].passed
    assert "globalchat_chatfield" in results["nonzero_area"].actual
    assert not results["within_parent"].passed
    assert "globalchat_chatlabel" in results["within_parent"].actual
    for name in ("gui_roots", "gui_named", "gui_controls", "tree_nodes",
                 "list_rows", "text_controls", "controls_filled"):
        assert results[name].passed, name


def test_window_layout_invariant_flags_an_unexpected_overlap(login_baseline):
    """Two tiled windows that start intersecting is a layout arithmetic bug.

    The pin carries the overlaps that are legitimate (Global Chat floats over
    the serverlist), so anything else is new.
    """
    observed = json.loads(json.dumps(_fixture("login_good")))
    observed["gui"]["window_overlaps"] = observed["gui"]["window_overlaps"] + [
        "serverlist_descriptionwindow|serverlist_tableswindow"]
    results = {r.name: r for r in compare(observed, login_baseline)}
    assert not results["window_layout"].passed
    assert "serverlist_tableswindow" in results["window_layout"].actual


def test_a_broken_ui_opener_is_an_invariant(login_baseline):
    observed = json.loads(json.dumps(_fixture("login_good")))
    observed["ui_opened"] = {"-serverlist_chat:openchat": "no such weapon vm"}
    assert "ui_openers" in _failed(compare(observed, login_baseline))


# --- comparison mechanics ---------------------------------------------------


def test_identical_fingerprint_passes_every_invariant():
    observed = _fixture("login_good")
    entry = make_entry(Target("x", "h", 1), observed)
    assert _failed(compare(observed, entry)) == set()


def test_band_is_inclusive_and_never_negative():
    assert band_for(100, 0.25, 3) == (72, 128)
    assert band_for(0, 0.5, 2) == (0, 2)
    assert band_for(3, 0.0, 1) == (2, 4)


def test_every_banded_metric_has_a_label():
    assert set(METRIC_BANDS) <= set(METRIC_LABELS)


def test_metric_reads_nested_paths_and_lengths():
    fingerprint = {"gui": {"roots": 7}, "vms": {"weapon": ["a", "b"]}}
    assert _metric(fingerprint, "gui.roots") == 7
    assert _metric(fingerprint, "vms.weapon") == 2
    assert _metric(fingerprint, "gui.nope") == 0
    assert _metric(fingerprint, "nope.nope") == 0


def test_npc_events_are_aggregated_but_weapon_events_are_not():
    # NPC VM keys are server-assigned ids that move whenever level content is
    # edited, so pinning them by id would fail on every content change.
    views = _event_views({"npc:10003.ontimeout": 4,
                          "weapon:-serverlist.oncreated": 1})
    assert views["kinds"] == ["npc.ontimeout", "weapon.oncreated"]
    assert views["weapon_events"] == ["weapon:-serverlist.oncreated"]
    assert views["calls"] == 5
    assert views["distinct"] == 2


def test_dropped_connection_is_an_invariant():
    observed = _fixture("login_good")
    entry = make_entry(Target("x", "h", 1), observed)
    dropped = dict(observed, connected_at_end=False)
    assert "stayed_connected" in _failed(compare(dropped, entry))


def test_new_warning_kind_fails_even_when_counts_hold():
    observed = _fixture("login_good")
    entry = make_entry(Target("x", "h", 1), observed)
    noisy = json.loads(json.dumps(observed))
    noisy["logs"]["kinds"] = ["pyreborn.gs2_client|WARNING|GS2 %s: brand new"]
    noisy["logs"]["warnings"] = 1
    assert "no_new_warnings" in _failed(compare(noisy, entry))


def test_new_missing_builtin_fails():
    observed = _fixture("login_good")
    entry = make_entry(Target("x", "h", 1), observed)
    gapped = json.loads(json.dumps(observed))
    gapped["host_calls"]["missing"] = ["somenewbuiltin"]
    assert "no_new_gaps" in _failed(compare(gapped, entry))


def test_ignore_list_drops_named_invariants():
    observed = _fixture("login_good")
    entry = make_entry(Target("x", "h", 1), observed)
    entry["ignore"] = ["gui_roots", "level_npcs"]
    names = {result.name for result in compare(observed, entry)}
    assert "gui_roots" not in names and "level_npcs" not in names
    assert "gui_named" in names


def test_per_entry_tolerance_widens_a_band():
    observed = _fixture("login_good")
    entry = make_entry(Target("x", "h", 1), observed)
    halved = json.loads(json.dumps(observed))
    halved["host_calls"]["total"] = observed["host_calls"]["total"] // 4
    assert "host_calls" in _failed(compare(halved, entry))
    entry["tolerance"] = {"host_calls": 0.95}
    assert "host_calls" not in _failed(compare(halved, entry))


# --- baseline bookkeeping ---------------------------------------------------


def test_default_pins_use_root_controls_not_every_named_control():
    observed = _fixture("login_good")
    pins = default_pins(observed)
    assert pins["required_controls"] == observed["gui"]["root_names"]
    assert len(pins["required_controls"]) < observed["gui"]["named"]
    assert pins["required_weapons"] == observed["vms"]["weapon"]
    assert pins["forbidden_weapons"] == []


def test_rebaseline_seeds_pin_kinds_the_previous_entry_never_had():
    """A rebaseline used to restore the previous pins WHOLESALE, so any pin
    kind added after a baseline was recorded stayed absent for ever and
    checked nothing. Curated keys still win. New keys get seeded."""
    observed = _fixture("login_good")
    previous = make_entry(Target("Login", "h", 1), observed)
    del previous["pins"]["required_filled_controls"]
    previous["pins"]["forbidden_weapons"] = ["-serverlist"]

    refreshed = make_entry(Target("Login", "h", 1), observed, previous)
    assert refreshed["pins"]["required_filled_controls"] == \
        observed["gui"]["filled_controls"]
    assert refreshed["pins"]["forbidden_weapons"] == ["-serverlist"]


def test_rebaseline_preserves_curated_pins_by_default():
    observed = _fixture("login_good")
    previous = make_entry(Target("Login", "h", 1), observed)
    previous["pins"]["forbidden_weapons"] = ["-serverlist"]
    previous["ignore"] = ["level_npcs"]
    previous["tolerance"] = {"host_calls": 0.9}

    kept = make_entry(Target("Login", "h", 1), observed, previous)
    assert kept["pins"]["forbidden_weapons"] == ["-serverlist"]
    assert kept["ignore"] == ["level_npcs"]
    assert kept["tolerance"] == {"host_calls": 0.9}

    reset = make_entry(Target("Login", "h", 1), observed, previous, reset_pins=True)
    assert reset["pins"]["forbidden_weapons"] == []


def test_target_resolution_prefers_explicit_then_baseline_then_default():
    entry = {"address": {"host": "baseline.host", "port": 1},
             "version": "2.22", "seconds": 9.0}
    assert target_for("Login", entry).host == "baseline.host"
    assert target_for("Login", entry, host="cli.host").host == "cli.host"
    assert target_for("Login", entry).seconds == 9.0
    assert target_for("Login", None).port == 14911      # DEFAULT_TARGETS
    with pytest.raises(ValueError):
        target_for("Never Heard Of It", None)


def test_checked_in_baselines_are_loadable_and_pinned():
    baselines = load_baselines()
    assert baselines["servers"], "no behaviour baselines checked in"
    for name, entry in baselines["servers"].items():
        assert entry["address"]["host"] and entry["address"]["port"]
        assert entry["observed"]["connected_at_end"] is True, name
        assert "required_weapons" in entry["pins"], name
