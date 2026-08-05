from __future__ import annotations

import json
import os
import subprocess
from collections import Counter
from types import SimpleNamespace

import pygame

from game_tester.gs2_ui_explorer.capture import CaptureWriter
from game_tester.gs2_ui_explorer.actions import ActionKind, UIAction
from game_tester.gs2_ui_explorer.explorer import ExplorerBot, ExplorerBudget
from game_tester.gs2_ui_explorer.fingerprint import canonical_state, state_hash
from game_tester.gs2_ui_explorer.input_driver import InputDriver, InputResult
from game_tester.gs2_ui_explorer.interactables import enumerate_actions
from game_tester.gs2_ui_explorer.pump import GamePump, SettleResult
from game_tester.gs2_ui_explorer.send_policy import PassiveSendPolicy
from game_tester.gs2_ui_explorer.strategy import (
    BranchScheduler, action_shape, detect_branch_openers,
    enumerate_selector_values, lightweight_selector_change, rank_actions,
    sanitize_branch_name, selector_seed, synthesize_backtrack_actions,
)
from game_tester.gs2_ui_explorer.deep_drive import build_deep_report, write_deep_report
from pyreborn.game.gs2_gui import GS2GuiManager
from pyreborn.outbound import script_origin
from pyreborn.packets import PacketID
from pyreborn.protocol import Protocol
from pyreborn.gs2_client.runtime import ClientGS2


def _add(manager, classname, name, *, x, y, width, height, parent=None):
    control = manager.create_control(classname, name)
    control.x, control.y = x, y
    control.width, control.height = width, height
    manager.addcontrol(control)
    if parent is not None:
        parent.add_child(control)
        if control in manager.roots:
            manager.roots.remove(control)
    return control


def test_selector_detection_is_confirmed_by_lightweight_behavior():
    manager = GS2GuiManager()
    previous = _add(manager, "GuiButtonCtrl", "chooser_prev", x=0, y=0,
                    width=20, height=20)
    launcher = _add(manager, "GuiButtonCtrl", "chooser_launch", x=30, y=0,
                    width=100, height=40)
    next_button = _add(manager, "GuiButtonCtrl", "chooser_next", x=140, y=0,
                       width=20, height=20)
    label = _add(manager, "GuiTextCtrl", "chooser_label", x=30, y=50,
                 width=100, height=20)
    label.text = "First"
    actions = enumerate_actions(manager)
    seed = selector_seed(actions, manager)
    assert seed is not None and seed.launcher.control == launcher.ctrl_name.lower()
    before = canonical_state(manager)
    label.text = "Second"
    after = canonical_state(manager)
    assert lightweight_selector_change(
        before, after,
        ignored_controls=(previous.ctrl_name, next_button.ctrl_name)) == "chooser_label"


def test_selector_enumeration_stops_on_repeat_and_cap():
    cycling = {"index": 0}
    values = ("one", "two", "three")
    found = enumerate_selector_values(
        lambda: values[cycling["index"]],
        lambda: cycling.update(index=(cycling["index"] + 1) % len(values)))
    assert found == list(values)

    growing = {"index": 0}
    capped = enumerate_selector_values(
        lambda: f"option-{growing['index']}",
        lambda: growing.update(index=growing["index"] + 1), cap=12)
    assert len(capped) == 12


def test_selector_branch_name_comes_from_display_text():
    assert sanitize_branch_name("  Memory Match! ") == "memorymatch"


def test_input_driver_real_dispatch_occlusion_and_tab():
    manager = GS2GuiManager()
    first = _add(manager, "GuiTextEditCtrl", "first", x=0, y=0,
                 width=100, height=22)
    second = _add(manager, "GuiTextEditCtrl", "second", x=0, y=30,
                  width=100, height=22)
    button = _add(manager, "GuiButtonCtrl", "button", x=120, y=0,
                  width=60, height=22)
    called = []
    button.set("onaction", lambda: called.append(True))
    driver = InputDriver(manager)
    assert driver.click_control(button).success
    assert called == [True]
    assert driver.focus_control(first).success
    assert manager._first_responder is first
    assert driver.press_tab().success
    assert manager._first_responder is second
    assert driver.press_tab(reverse=True).success
    assert manager._first_responder is first

    cover = _add(manager, "GuiControl", "cover", x=120, y=0,
                 width=60, height=22)
    assert not driver.click_control(button).success
    assert driver.click_control(button).reason == "occluded/unhittable"
    assert cover is manager.hit_test((130, 10))


def test_passive_policy_origin_allowlist_and_jsonl(tmp_path):
    path = tmp_path / "blocked.jsonl"
    policy = PassiveSendPolicy(path)
    engine = {"engine": True, "kind": "engine", "name": "", "function": ""}
    script = {"engine": False, "kind": "weapon", "name": "shop",
              "function": "onaction"}
    assert policy(PacketID.PLI_TRIGGERACTION, b"same", engine).allowed
    assert not policy(PacketID.PLI_TRIGGERACTION, b"same", script).allowed
    assert policy(PacketID.PLI_UPDATESCRIPT, b"shop", script).allowed
    record = json.loads(path.read_text().splitlines()[0])
    assert record["decision"] == "blocked"
    assert record["origin"] == script
    assert record["packet_id"] == PacketID.PLI_TRIGGERACTION
    assert len(record["payload_sha256"]) == 64


def test_protocol_gate_precedes_recorder_and_codec():
    protocol = Protocol("invalid", 1)
    protocol.socket = SimpleNamespace(setblocking=lambda *_: None,
                                      sendall=lambda *_: None)
    protocol.connected = True
    protocol.sent_payloads = {}
    policy = PassiveSendPolicy()
    protocol.outbound_policy = policy
    with script_origin("weapon", "test", "onaction"):
        assert not protocol.send_packet(PacketID.PLI_TRIGGERACTION, b"x")
    assert protocol.sent_payloads == {}


def test_canonical_hash_excludes_pointer_and_animation_state():
    manager = GS2GuiManager()
    control = _add(manager, "GuiButtonCtrl", "stable", x=1, y=2,
                   width=30, height=20)
    before = state_hash(canonical_state(manager))
    manager.last_mouse = (999, 888)
    manager._hover = control
    manager._animation_ticks = 123456
    after = state_hash(canonical_state(manager))
    assert before == after


def test_canonical_hash_changes_when_control_image_changes():
    manager = GS2GuiManager()
    control = _add(manager, "GuiBitmapCtrl", "card", x=1, y=2,
                   width=30, height=20)
    control.set("image", "card-back.png")
    before = state_hash(canonical_state(manager))
    control.set("image", "card-face.png")
    after = state_hash(canonical_state(manager))
    assert before != after


def test_settle_requires_stable_state_idle_animations_and_runtime(monkeypatch):
    manager = GS2GuiManager()
    control = _add(manager, "GuiControl", "fade", x=0, y=0,
                   width=20, height=20)
    animation = control.create_animation()
    animation.set("transition", "fadein")
    animation.set("duration", .04)

    class Runtime:
        gui = manager

        def has_pending_explorer_work(self):
            return pump.steps < 2

    game = SimpleNamespace(gs2=Runtime())

    class ProbePump(GamePump):
        steps = 0

        def step(self):
            self.steps += 1
            manager.tick(.02)

    clock = iter(index / 100 for index in range(1000))
    monkeypatch.setattr("game_tester.gs2_ui_explorer.pump.time.monotonic",
                        lambda: next(clock))
    pump = ProbePump(game, stable_frames=3)
    settled = pump.settle(.5)
    assert settled.quiescent
    assert settled.frames >= 3
    assert not manager.has_active_animations()

    long_animation = control.create_animation()
    long_animation.set("transition", "fadein")
    long_animation.set("duration", 10)
    capped = pump.settle(.03)
    assert not capped.quiescent
    assert manager.has_active_animations()


def test_capture_writer_round_trip(tmp_path):
    writer = CaptureWriter(tmp_path / "capture", {"target": "fixture"})
    state = {"controls": [{"path": "0:root"}]}
    writer.write_state("sha256:" + "a" * 64, state)
    client = SimpleNamespace(gs2_bytecode={"weapon": {"Shop": b"bytecode"}})
    metadata = writer.capture_bytecodes(client, 7)
    writer.write_step({"step": 7, "delta": {"new_bytecodes": metadata}})
    assert json.loads((writer.out_dir / "manifest.json").read_text())["target"] == "fixture"
    assert json.loads(writer.steps_path.read_text())["step"] == 7
    blob = writer.bytecode_dir / f"{metadata[0]['sha256']}.gs2bc"
    assert blob.read_bytes() == b"bytecode"
    assert json.loads(writer.bytecodes_path.read_text())["first_seen_step"] == 7


def test_bfs_dedup_and_budgets(tmp_path):
    manager = GS2GuiManager()
    control = _add(manager, "GuiButtonCtrl", "state", x=0, y=0,
                   width=50, height=20)
    game = SimpleNamespace(
        gs2=SimpleNamespace(gui=manager,
                            vms={"weapon": {}, "class": {}, "npc": {}, "gani": {}}),
        client=SimpleNamespace(gs2_bytecode={}),
    )
    actions = [UIAction(ActionKind.CLICK, "state", text=value)
               for value in ("a", "b", "c")]

    def execute(action):
        control.text = action.text
        return InputResult(True)

    bot = ExplorerBot(
        game, writer=CaptureWriter(tmp_path / "bfs"),
        budget=ExplorerBudget(max_states=3, max_depth=5, actions_per_state=2,
                              settle_seconds=0),
        action_source=lambda _gui: actions, executor=execute)
    result = bot.explore(2)
    assert result.states == 3
    assert result.actions <= 3 * 2
    lines = bot.writer.steps_path.read_text().splitlines()
    assert len(lines) == result.actions


def test_branch_novelty_beats_explored_sibling_and_damps_repetition():
    manager = GS2GuiManager()
    for index in range(6):
        _add(manager, "GuiButtonCtrl", f"cell_{index}", x=index * 30, y=0,
             width=28, height=20)
    _add(manager, "GuiButtonCtrl", "open_memory", x=0, y=30,
         width=100, height=20)
    actions = enumerate_actions(manager)
    cell_shape = action_shape(next(a for a in actions if a.control == "cell_0"), manager)
    ranked = rank_actions(actions, manager, {cell_shape}, Counter({cell_shape: 2}),
                          sibling_sample=3)
    assert ranked[0].control == "open_memory"
    assert len([action for action in ranked if action.control.startswith("cell_")]) == 1


def test_backtrack_synthesis_and_per_branch_budget():
    manager = GS2GuiManager()
    _add(manager, "GuiButtonCtrl", "quit_game", x=0, y=0, width=80, height=20)
    actions = synthesize_backtrack_actions(manager)
    assert UIAction(ActionKind.CLICK, "quit_game") in actions
    assert any(action.kind == ActionKind.ESCAPE for action in actions)
    scheduler = BranchScheduler(per_branch_budget=2)
    scheduler.record("Aztek")
    scheduler.record("Aztek")
    assert not scheduler.allows("Aztek") and scheduler.allows("Splatman")
    scheduler.next_round(["Aztek", "Splatman"])
    assert scheduler.allows("Aztek")


def test_detects_distinct_game_branch_openers_only_on_selection_surface():
    manager = GS2GuiManager()
    for index, name in enumerate(("Aztek", "Black Jack", "Guess Number")):
        button = _add(manager, "GuiButtonCtrl", f"menu_games_{name}",
                      x=index * 100, y=0, width=95, height=20)
        button.text = name
    openers = detect_branch_openers(enumerate_actions(manager), manager)
    assert [name for name, _action in openers] == [
        "aztek", "blackjack", "guessnumber"]

    lone = GS2GuiManager()
    _add(lone, "GuiButtonCtrl", "tictactoe_board_1", x=0, y=0,
         width=20, height=20)
    assert detect_branch_openers(enumerate_actions(lone), lone) == []


def test_branch_budget_excludes_open_and_backtrack_and_verifies_hash(tmp_path):
    manager = GS2GuiManager()
    active = {"controls": []}
    for index, name in enumerate(("aztek", "blackjack")):
        opener = _add(manager, "GuiButtonCtrl", f"menu_games_{name}",
                      x=index * 110, y=0, width=100, height=20)

        def launch(branch=name):
            for control in manager.roots:
                control.visible = False
            active["controls"] = []
            for item in range(4):
                child = _add(manager, "GuiButtonCtrl", f"{branch}_play_{item}",
                             x=item * 30, y=40, width=25, height=20)
                child.set("onaction", lambda control=child:
                          setattr(control, "text", control.text + "x"))
                active["controls"].append(child)
            exit_button = _add(manager, "GuiButtonCtrl", f"{branch}_exit",
                               x=0, y=70, width=80, height=20)

            def close():
                for control in list(active["controls"]) + [exit_button]:
                    if control in manager.roots:
                        manager.roots.remove(control)
                    manager._named.pop(control.ctrl_name.lower(), None)
                for control in manager.roots:
                    control.visible = True

            exit_button.set("onaction", close)

        opener.set("onaction", launch)

    game = SimpleNamespace(
        gs2=SimpleNamespace(gui=manager,
                            vms={"weapon": {}, "class": {}, "npc": {}, "gani": {}}),
        client=SimpleNamespace(gs2_bytecode={}),
    )
    writer = CaptureWriter(tmp_path / "branches")
    bot = ExplorerBot(game, writer=writer,
                      budget=ExplorerBudget(per_branch_actions=2,
                                            settle_seconds=0))
    result = bot.explore(10)
    records = [json.loads(line) for line in writer.steps_path.read_text().splitlines()]
    for branch in ("aztek", "blackjack"):
        own = [record for record in records if record["branch"] == branch]
        assert sum(record.get("transition") is None for record in own) == 2
        assert any(record.get("transition") == "opener" for record in own)
        assert any(record.get("transition") == "backtrack"
                   and record.get("backtrack_verified") for record in own)
    assert not [record for record in records if record.get("branch") == "entry"
                and any(name in json.dumps(record.get("delta", {}))
                        for name in ("aztek_play", "blackjack_play"))]
    assert result.actions == len(records)


def test_deep_report_shape_and_brokenness_order(tmp_path):
    records = [
        {"branch": "Good", "before": "a", "after": "b", "success": True,
         "action": {"kind": "click", "control": "go"},
         "delta": {"new_controls": [{"name": "panel"}], "new_host_calls": {"showgui": 1}}},
        {"branch": "Broken", "before": "x", "after": "x", "success": True,
         "action": {"kind": "click", "control": "dead"},
         "delta": {"new_controls": [], "new_missing_builtins": {"copyfrom": 1}}},
    ]
    report = build_deep_report(records)
    assert report["branches"][0]["name"] == "Broken"
    assert report["branches"][0]["dead_buttons"] == ["dead"]
    assert report["branches"][1]["built_controls"] is True
    markdown, payload = write_deep_report(tmp_path, report)
    assert markdown.exists() and payload.exists()


def test_deep_report_records_failed_backtrack_verification():
    report = build_deep_report([{
        "branch": "memorymatch", "before": "game", "after": "still-game",
        "success": True, "transition": "backtrack", "backtrack_verified": False,
        "action": {"kind": "click", "control": "memorymatch_exit"},
        "delta": {"new_controls": [{"name": "memorymatch_panel"}]},
    }])
    branch = report["branches"][0]
    assert branch["backtrack_success"] is False
    assert branch["backtrack_failures"] == 1


def test_compiled_gs2_local_transition_with_send_gate(tmp_path):
    compiler = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "../../../reborn-protocol/tests/tools/gs2test"))
    if not os.path.isfile(compiler):
        import pytest
        pytest.skip("local GS2 compiler is unavailable")
    source = tmp_path / "explorer.gs2"
    bytecode = tmp_path / "explorer.gs2bc"
    source.write_text("""
function onCreated() {
  new GuiButtonCtrl(temp.button) {
    x = 5; y = 5; width = 100; height = 24; text = "Before";
    buttontype = "ToggleButton";
    onAction = function() {
      triggeraction(0, 0, "explorer", "clicked");
    };
  }
  showgui(temp.button);
}
""")
    subprocess.run([compiler, str(source), "-o", str(bytecode)], check=True,
                   capture_output=True, text=True)
    policy = PassiveSendPolicy(tmp_path / "blocked.jsonl")
    protocol = Protocol("fixture", 1)
    protocol.socket = SimpleNamespace(setblocking=lambda *_: None,
                                      sendall=lambda *_: None)
    protocol.connected = True
    protocol.outbound_policy = policy

    class Client:
        connected = True
        _authenticated = True

        def triggeraction(self, action, x=None, y=None, npc_id=0):
            return protocol.send_packet(PacketID.PLI_TRIGGERACTION,
                                        action.encode("utf-8"))

    runtime = ClientGS2(client=Client())
    assert runtime.load_bytecode("weapon", "explorer", bytecode.read_bytes())
    button = runtime.gui.roots[0]
    assert InputDriver(runtime.gui).click_control(button).success
    assert button.checked is True
    assert len(policy.blocked) == 1
    assert policy.blocked[0]["packet_name"] == "PLI_TRIGGERACTION"


def test_explorer_idles_through_compiled_loading_menu_and_clicks(tmp_path):
    compiler = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "../../../reborn-protocol/tests/tools/gs2test"))
    if not os.path.isfile(compiler):
        import pytest
        pytest.skip("local GS2 compiler is unavailable")
    source = tmp_path / "loading_menu.gs2"
    bytecode = tmp_path / "loading_menu.gs2bc"
    source.write_text("""
function onCreated() {
  new GuiControl("LoadingPanel") {
    x = 0; y = 0; width = 200; height = 100;
  }
  showgui(LoadingPanel);
  settimer(.05);
}
function onTimeout() {
  destroy(LoadingPanel);
  new GuiControl("MainMenu") {
    x = 0; y = 0; width = 200; height = 100;
    new GuiBitmapButtonCtrl("LaunchGame") {
      x = 10; y = 10; width = 100; height = 24; text = "Tic Tac Toe";
      onAction = function() {
        new GuiControl("LaunchedGame") {
          x = 0; y = 40; width = 180; height = 50;
        }
        showgui(LaunchedGame);
      };
    }
  }
  showgui(MainMenu);
}
""")
    subprocess.run([compiler, str(source), "-o", str(bytecode)], check=True,
                   capture_output=True, text=True)

    class Client:
        gs2_bytecode = {"weapon": {}, "class": {}, "npc": {}, "gani": {}}

    client = Client()
    runtime = ClientGS2(client=client)
    blob = bytecode.read_bytes()
    client.gs2_bytecode["weapon"]["loading-menu"] = blob
    assert runtime.load_bytecode("weapon", "loading-menu", blob)
    assert [control.ctrl_name for control in runtime.gui.roots] == ["LoadingPanel"]

    class RuntimePump:
        def settle(self, seconds=.2):
            for _ in range(4):
                runtime.process_coroutines(.02)
                runtime.process_timeouts(.02)
            return SettleResult(4, .08, False)

    game = SimpleNamespace(gs2=runtime, client=client)
    writer = CaptureWriter(tmp_path / "idle-explorer")
    bot = ExplorerBot(
        game, pump=RuntimePump(), writer=writer,
        budget=ExplorerBudget(max_states=3, max_depth=3,
                              actions_per_state=4, settle_seconds=.08))
    result = bot.explore(.05)

    records = [json.loads(line) for line in writer.steps_path.read_text().splitlines()]
    spontaneous = [record for record in records
                   if record.get("transition") == "spontaneous"]
    assert result.states == 3
    assert spontaneous and spontaneous[0]["action"] is None
    assert any(action.control == "launchgame"
               for action in enumerate_actions(runtime.gui))
    assert any(record.get("action", {}).get("control") == "launchgame"
               for record in records if record.get("action"))
    assert "launchedgame" in runtime.gui._named
    assert len(list(writer.bytecode_dir.glob("*.gs2bc"))) == 1
    assert json.loads(writer.bytecodes_path.read_text())["first_seen_step"] == 0
