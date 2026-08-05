"""Offline regression coverage for the captured Games UI script chain."""

from __future__ import annotations

import logging
import json
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from game_tester.gs2_ui_explorer.input_driver import InputDriver
from game_tester.gs2_ui_explorer.interactables import enumerate_actions, control_map
from game_tester.gs2_ui_explorer.fingerprint import snapshot_and_hash
from game_tester.gs2_ui_explorer.capture import CaptureWriter
from game_tester.gs2_ui_explorer.explorer import ExplorerBot, ExplorerBudget
from game_tester.gs2_ui_explorer.pump import GamePump
from game_tester.gs2_ui_explorer.pump import SettleResult
from game_tester.gs2_ui_explorer.deep_drive import build_deep_report
from game_tester.behaviour_fingerprint import snapshot_host_counters
from pyreborn.game.gs2_gui import GuiControl
from pyreborn.gs1_client import ClientGS1
from pyreborn.gs2_client import ClientGS2


CAPTURE = Path(__file__).parents[1] / "fixtures" / "gs2_games_capture"


class _OfflineClient(SimpleNamespace):
    def __init__(self):
        super().__init__(
            connected=False,
            version="6.037",
            _in_update=False,
            gs2_bytecode={"class": {}, "weapon": {}, "npc": {}, "gani": {}},
            player=SimpleNamespace(id=1, x=0, y=0),
            players={},
            all_players={},
            weapons=[],
            screen_w=800,
            screen_h=600,
            _pending_files=set(),
            _failed_files=set(),
        )

    def request_class_bytecode(self, _name):
        return True

    def request_weapon_bytecode(self, _name):
        return True

    def get_file(self, _name):
        return None

    def request_file(self, _name):
        return False

    def update(self, timeout=0):
        return None


def _blob(kind: str, name: str) -> bytes:
    return (CAPTURE / f"{kind}__{name.replace('/', '_')}.gs2bc").read_bytes()


def _control_count(runtime) -> int:
    def walk(control):
        return 1 + sum(walk(child) for child in control.children)
    return sum(walk(root) for root in runtime.gui.roots)


def _loaded_runtime(*, start_menu=True):
    client = _OfflineClient()
    runtime = ClientGS2(client, gs1=ClientGS1(client))
    for name in (
        "-Utils", "-GUI/Games", "-Games/Aztek", "-Games/BlackJack",
        "-Games/GuessNumber", "-Games/MemoryMatch", "-Games/Splatman",
        "-Games/TicTacToe", "-GUI/LoadingScreen", "-GUI/MainMenu",
    ):
        blob = _blob("weapon", name)
        client.gs2_bytecode["weapon"][name] = blob
        runtime.load_bytecode("weapon", name, blob)
    for name in ("gui_helpers", "gui_scale"):
        client.gs2_bytecode["class"][name] = _blob("class", name)
    for _ in range(300):
        runtime.process_coroutines(1 / 60)
        runtime.process_timeouts(1 / 60)
    if start_menu:
        runtime.vms["weapon"]["-gui/mainmenu"].call("startMenu")
    return client, runtime


def _delay_selection_with_fade(runtime, duration=1.0):
    """Model the live menu's deferred fade-complete launch offline."""
    selection = runtime.gui._named["skills_mainmenu_gameselection"]
    delayed = runtime.gui.create_control(
        "GuiButtonCtrl", "skills_mainmenu_gameselection_delayed")
    selection_rect = selection.rect()
    delayed.x, delayed.y = selection_rect.x, selection_rect.y
    delayed.width, delayed.height = selection.width, selection.height
    delayed.text = selection.text
    runtime.gui.addcontrol(delayed)
    selection.visible = False

    def begin_fade():
        animation = delayed.create_animation()
        animation.set("transition", "fadeout")
        animation.set("duration", duration)
        delayed.set("onanimationfinished",
                    lambda *_args: selection.fire_event("onaction"))

    delayed.set("onaction", begin_fade)
    return delayed


class _RuntimePump(GamePump):
    def step(self):
        runtime = self.game.gs2
        runtime.process_coroutines(self.frame_dt)
        runtime.process_timeouts(self.frame_dt)
        runtime.gui.tick(self.frame_dt)


def test_offline_games_menu_and_launcher_have_no_dispatch_warnings(caplog,
                                                                    monkeypatch):
    animation_receivers = []
    original_createanimation = GuiControl._m_createanimation

    def track_createanimation(control, *args):
        animation_receivers.append(control)
        return original_createanimation(control, *args)

    monkeypatch.setattr(GuiControl, "_m_createanimation", track_createanimation)
    client = _OfflineClient()
    runtime = ClientGS2(client, gs1=ClientGS1(client))
    for name in (
        "-Utils", "-GUI/Games", "-Games/Aztek", "-Games/BlackJack",
        "-Games/GuessNumber", "-Games/MemoryMatch", "-Games/Splatman",
        "-Games/TicTacToe", "-GUI/LoadingScreen", "-GUI/MainMenu",
    ):
        blob = _blob("weapon", name)
        client.gs2_bytecode["weapon"][name] = blob
        runtime.load_bytecode("weapon", name, blob)

    for name in ("gui_helpers", "gui_scale"):
        client.gs2_bytecode["class"][name] = _blob("class", name)

    for _ in range(300):
        runtime.process_coroutines(1 / 60)
        runtime.process_timeouts(1 / 60)

    runtime.vms["weapon"]["-gui/mainmenu"].call("startMenu")

    driver = InputDriver(runtime.gui)
    assert runtime.vms["weapon"]["-gui/mainmenu"].this.get("game_index") == 0
    selection = runtime.gui._named["skills_mainmenu_gameselection"]
    controls_before = _control_count(runtime)
    caplog.clear()
    animation_receivers.clear()
    with caplog.at_level(logging.WARNING):
        assert driver.click_control(selection).success
        for _ in range(60):
            runtime.process_coroutines(1 / 60)
            runtime.process_timeouts(1 / 60)

    # The broken join built the game's 13 native controls but missed the
    # helper class's exit button.  A complete launch adds all fourteen.
    assert _control_count(runtime) - controls_before == 14
    assert [control.ctrl_name for control in animation_receivers] == [
        "Skills_MainMenu", "Skills_Games_TicTacToe",
    ]
    assert all(isinstance(control, GuiControl) for control in animation_receivers)

    warnings = [record.getMessage() for record in caplog.records
                if "unknown function" in record.getMessage().lower()
                or "unknown method" in record.getMessage().lower()]
    assert warnings == []


def test_offline_all_six_games_open_and_print_findings(caplog):
    expected = {"Aztek", "BlackJack", "GuessNumber", "MemoryMatch",
                "Splatman", "TicTacToe"}
    findings = []
    for game_name in sorted(expected):
        _client, runtime = _loaded_runtime()
        before = _control_count(runtime)
        missing_before = snapshot_host_counters()["missing"]
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            vm = runtime.vms["weapon"][f"-games/{game_name.lower()}"]
            vm.call("startgame")
            for _ in range(60):
                runtime.process_coroutines(1 / 60)
                runtime.process_timeouts(1 / 60)
            built = _control_count(runtime) - before
            dead = []
            # Sample at most three same-shape buttons, matching explorer damping.
            for action in enumerate_actions(runtime.gui)[:12]:
                if action.kind.value != "click" or "exit" in action.control.lower():
                    continue
                control = control_map(runtime.gui).get(action.control)
                _state, state_before = snapshot_and_hash(runtime.gui)
                result = InputDriver(runtime.gui).click_control(control)
                for _ in range(3):
                    runtime.process_coroutines(1 / 60)
                    runtime.process_timeouts(1 / 60)
                _state, state_after = snapshot_and_hash(runtime.gui)
                if result.success and state_before == state_after:
                    dead.append(action.control)
                if len(dead) >= 3:
                    break
        warnings = [record.getMessage() for record in caplog.records]
        missing_after = snapshot_host_counters()["missing"]
        missing = {key: value - missing_before.get(key, 0)
                   for key, value in missing_after.items()
                   if value > missing_before.get(key, 0)}
        findings.append({"game": game_name, "opens": built > 0, "controls": built,
                         "dead": dead, "warnings": warnings, "missing": missing})
    print("\nOffline Games deep drive:")
    for item in sorted(findings, key=lambda row: row["game"]):
        print(f"  {item['game']}: opens={item['opens']} controls={item['controls']} "
              f"dead={item['dead'] or '-'} warnings={len(item['warnings'])} "
              f"missing={item['missing'] or '-'}")
    assert {item["game"] for item in findings} == expected
    assert all(item["opens"] and item["controls"] > 0 for item in findings)


def test_offline_deep_drive_covers_six_branches_breadth_first(tmp_path,
                                                               monkeypatch):
    """Exercise the scheduler with animation-scale transition accounting."""
    names = ("aztek", "blackjack", "guessnumber", "memorymatch",
             "splatman", "tictactoe")
    _client, runtime = _loaded_runtime(start_menu=False)
    runtime.gui.roots.clear()
    runtime.gui._named.clear()
    active = []
    menu_controls = []
    selected = {"index": 0}
    enter = runtime.gui.create_control("GuiButtonCtrl", "open_games")
    enter.x, enter.y, enter.width, enter.height = 0, 0, 140, 24
    runtime.gui.addcontrol(enter)
    controls = []
    for class_name, name, x, y, width in (
            ("GuiButtonCtrl", "menu_left_selection", 0, 30, 30),
            ("GuiButtonCtrl", "menu_game_selection", 50, 30, 140),
            ("GuiButtonCtrl", "menu_right_selection", 220, 30, 30),
            ("GuiTextCtrl", "menu_selection_text", 50, 70, 140)):
        control = runtime.gui.create_control(class_name, name)
        control.x, control.y, control.width, control.height = x, y, width, 24
        control.visible = False
        runtime.gui.addcontrol(control)
        menu_controls.append(control)
        controls.append(control)
    previous, launcher, next_button, label = controls
    label.text = names[0]

    def rotate(offset):
        selected["index"] = (selected["index"] + offset) % len(names)
        label.text = names[selected["index"]]

    previous.set("onaction", lambda: rotate(-1))
    next_button.set("onaction", lambda: rotate(1))

    def launch():
        branch = names[selected["index"]]
        for root in runtime.gui.roots:
            root.visible = False
        active.clear()
        # Exercise the captured implementation selected by the carousel.  The
        # small controls below are a deterministic harness around its native
        # UI because the already-loaded VM retains references to its original
        # menu canvas after this test replaces the roots.
        runtime.vms["weapon"][f"-games/{branch}"].call("startgame")
        for item in range(5):
            control = runtime.gui.create_control(
                "GuiButtonCtrl", f"{branch}_subtree_{item}")
            control.x, control.y = item * 45, 110
            control.width, control.height = 40, 22
            control.set("onaction", lambda target=control:
                        setattr(target, "text", target.text + "x"))
            runtime.gui.addcontrol(control)
            active.append(control)
        exit_button = runtime.gui.create_control(
            "GuiButtonCtrl", f"{branch}_exit")
        exit_button.x, exit_button.y = 0, 145
        exit_button.width, exit_button.height = 80, 22
        runtime.gui.addcontrol(exit_button)
        active.append(exit_button)

        def close():
            for control in list(active):
                if control in runtime.gui.roots:
                    runtime.gui.roots.remove(control)
                runtime.gui._named.pop(control.ctrl_name.lower(), None)
            enter.visible = False
            # The live menu can return at a different carousel position.  This
            # deliberately makes its canonical hash differ from the state that
            # launched the branch while preserving the selector menu itself.
            rotate(2)
            for menu_control in menu_controls:
                menu_control.visible = True

        exit_button.set("onaction", close)

    launcher.set("onaction", launch)

    def reveal_launchers():
        enter.visible = False
        for menu_control in menu_controls:
            menu_control.visible = True

    enter.set("onaction", reveal_launchers)

    clock = {"now": 0.0}
    monkeypatch.setattr("game_tester.gs2_ui_explorer.explorer.time.monotonic",
                        lambda: clock["now"])

    class HonestPump:
        def settle(self, cap):
            elapsed = min(1.0, cap)
            clock["now"] += elapsed
            return SettleResult(60, elapsed, True)

    game = SimpleNamespace(gs2=runtime, client=_client)
    writer = CaptureWriter(tmp_path / "six-branch-drive")
    result = ExplorerBot(
        game, pump=HonestPump(), writer=writer,
        budget=ExplorerBudget(per_branch_actions=5, sibling_sample=5,
                              settle_seconds=3),
    ).explore(240)
    records = [json.loads(line) for line in writer.steps_path.read_text().splitlines()]
    report = build_deep_report(records)
    branches = {branch["name"]: branch for branch in report["branches"]
                if branch["name"] != "entry"}
    entry = [record for record in records if record.get("branch") == "entry"]

    print("\nOffline six-branch report:")
    for name in names:
        branch = branches[name]
        print(f"  {name}: actions={branch['actions_explored']} "
              f"new_controls={branch['new_controls_built']} "
              f"backtrack={branch['backtrack_success']}")

    assert set(branches) == set(names)
    assert all(branch["new_controls_built"] > 0 for branch in branches.values())
    assert all(branch["backtrack_success"] for branch in branches.values())
    assert entry[0]["action"]["control"] == "open_games"
    assert report["selector_options"] == list(names)
    assert all(not any("_subtree_" in str(control.get("name", ""))
                       for control in record.get("delta", {}).get("new_controls", []))
               for record in entry)
    assert [record["branch"] for record in records
            if record.get("transition") == "opener"] == list(names)
    open_hashes = {record["branch"]: record["before"] for record in records
                   if record.get("transition") == "opener"}
    verified_returns = [record for record in records
                        if record.get("transition") == "backtrack"
                        and record.get("backtrack_verified")]
    assert all(record["after"] != open_hashes[record["branch"]]
               for record in verified_returns)
    assert all(record["branch"] == "entry" for record in records
               if record.get("transition") == "selector_advance")
    assert result.duration > 0


def test_animation_delayed_games_launch_stays_attributed_to_click(tmp_path):
    # First pin the old short-window shape: three frames see no launch, while
    # completing the one-second fade creates the game controls afterwards.
    _client, legacy_runtime = _loaded_runtime()
    selection = _delay_selection_with_fade(legacy_runtime)
    controls_before = _control_count(legacy_runtime)
    assert InputDriver(legacy_runtime.gui).click_control(selection).success
    for _ in range(3):
        legacy_runtime.process_coroutines(1 / 60)
        legacy_runtime.process_timeouts(1 / 60)
        legacy_runtime.gui.tick(1 / 60)
    assert _control_count(legacy_runtime) == controls_before
    for _ in range(60):
        legacy_runtime.process_coroutines(1 / 60)
        legacy_runtime.process_timeouts(1 / 60)
        legacy_runtime.gui.tick(1 / 60)
    assert _control_count(legacy_runtime) > controls_before

    client, runtime = _loaded_runtime()
    _delay_selection_with_fade(runtime)
    game = SimpleNamespace(gs2=runtime, client=client)
    writer = CaptureWriter(tmp_path / "delayed-games")
    bot = ExplorerBot(
        game, pump=_RuntimePump(game), writer=writer,
        budget=ExplorerBudget(max_states=2, max_depth=1,
                              actions_per_state=1, settle_seconds=3),
        action_source=lambda gui: [action for action in enumerate_actions(gui)
                                   if action.control == "skills_mainmenu_gameselection_delayed"],
    )
    bot.explore(2)
    records = [json.loads(line) for line in writer.steps_path.read_text().splitlines()]
    launch = next(record for record in records if record.get("action"))
    assert launch["action"]["control"] == "skills_mainmenu_gameselection_delayed"
    assert launch["before"] != launch["after"]
    assert launch["delta"]["new_controls"]
    assert launch["settle"]["quiescent"] is True
    assert not any(record.get("transition") == "spontaneous"
                   and record.get("delta", {}).get("new_controls")
                   for record in records)
