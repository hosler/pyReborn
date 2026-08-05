from __future__ import annotations

import time
from collections import deque
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable

import pygame

from game_tester.behaviour_fingerprint import (
    delta_counters, snapshot_bytecodes, snapshot_host_counters, snapshot_logs,
    snapshot_vms,
)

from .actions import ActionKind, UIAction
from .capture import CaptureWriter
from .fingerprint import snapshot_and_hash, state_delta
from .input_driver import InputDriver, InputResult
from .interactables import control_map, enumerate_actions
from .report import ExplorerReport
from .strategy import (
    action_shape, detect_branch_openers, opener_branch_name, rank_actions,
    sanitize_branch_name, selector_seed, lightweight_selector_change,
    synthesize_backtrack_actions,
)


@dataclass(frozen=True)
class ExplorerBudget:
    max_states: int = 200
    max_depth: int = 8
    actions_per_state: int = 40
    settle_seconds: float = 3.0
    repeated_self_loops: int = 2
    per_branch_actions: int = 5
    sibling_sample: int = 3


@dataclass(frozen=True)
class ExplorerResult:
    duration: float
    states: int
    actions: int
    blocked_sends: int
    out_dir: str


class ExplorerBot:
    def __init__(self, game: Any, *, pump: Any = None,
                 writer: CaptureWriter | None = None, policy: Any = None,
                 budget: ExplorerBudget | None = None,
                 action_source: Callable[[Any], list[UIAction]] = enumerate_actions,
                 executor: Callable[[UIAction], InputResult] | None = None):
        self.game = game
        self.gui = game.gs2.gui
        self.pump = pump
        self.writer = writer or CaptureWriter()
        self.policy = policy
        self.budget = budget or ExplorerBudget()
        self.action_source = action_source
        self.driver = InputDriver(self.gui)
        self.executor = executor
        self.visited_shapes: set[tuple[str, str, str]] = set()
        self.shape_counts: Counter = Counter()

    def _settle(self, started: float, duration: float):
        if self.pump is None:
            return None
        remaining = max(0.0, duration - (time.monotonic() - started))
        return self.pump.settle(min(self.budget.settle_seconds, remaining))

    def _execute(self, action: UIAction) -> InputResult:
        if self.executor is not None:
            return self.executor(action)
        control = control_map(self.gui).get(action.control)
        if control is None:
            return InputResult(False, "control disappeared")
        if action.kind == ActionKind.CLICK:
            return self.driver.click_control(control)
        if action.kind == ActionKind.SELECT_ROW:
            return self.driver.select_row(control, action.row or 0, action.double)
        if action.kind == ActionKind.SELECT_TAB:
            return self.driver.select_tab(control, action.row or 0)
        if action.kind == ActionKind.SELECT_TREE:
            rect = control.rect()
            point = (int(rect.left + 6),
                     int(rect.top + (action.row or 0) * control.ROW_H + control.ROW_H / 2))
            return self.driver.click_point(point)
        if action.kind == ActionKind.OPEN_POPUP:
            return self.driver.click_control(control)
        if action.kind == ActionKind.SELECT_POPUP:
            return self.driver.select_popup_row(control, action.row or 0)
        if action.kind == ActionKind.FOCUS:
            return self.driver.focus_control(control)
        if action.kind == ActionKind.TYPE_TEXT:
            return self.driver.type_text(control, action.text)
        if action.kind == ActionKind.BACKSPACE:
            focused = self.driver.focus_control(control)
            return self.driver.press_key(pygame.K_BACKSPACE) if focused.success else focused
        if action.kind == ActionKind.SUBMIT:
            focused = self.driver.focus_control(control)
            return self.driver.press_key(pygame.K_RETURN) if focused.success else focused
        if action.kind == ActionKind.ESCAPE:
            return self.driver.press_key(pygame.K_ESCAPE)
        return InputResult(False, "unsupported action")

    def _record_action(self, action: UIAction, *, branch: str, step: int,
                       parent_hash: str, start: float, duration: float,
                       transition: str | None = None,
                       expected_hash: str | None = None,
                       backtrack_verifier: Callable[[], bool] | None = None,
                       metadata: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
        before, before_hash = snapshot_and_hash(self.gui)
        host_before = snapshot_host_counters()
        vm_before = snapshot_vms(self.game.gs2)
        log_before = snapshot_logs(getattr(self.game, "_explorer_log_capture", None))
        blocked_before = len(self.policy.blocked) if self.policy else 0
        result = self._execute(action)
        shape = action_shape(action, self.gui)
        self.visited_shapes.add(shape)
        self.shape_counts[shape] += 1
        settle = self._settle(start, duration)
        after, after_hash = snapshot_and_hash(self.gui)
        blocked = self.policy.since(blocked_before) if self.policy else []
        delta = state_delta(before, after)
        delta.update({
            "new_bytecodes": self.writer.capture_bytecodes(self.game.client, step),
            "new_vms": delta_counters(vm_before, snapshot_vms(self.game.gs2)),
            "new_missing_builtins": delta_counters(
                host_before.get("missing", {}),
                snapshot_host_counters().get("missing", {})),
            "new_host_calls": delta_counters(
                host_before.get("called", {}),
                snapshot_host_counters().get("called", {})),
            "new_warning_kinds": delta_counters(
                log_before.get("kinds", {}),
                snapshot_logs(getattr(self.game, "_explorer_log_capture", None)).get("kinds", {})),
            "blocked_sends": blocked,
        })
        record = {
            "step": step, "parent_state": parent_hash, "branch": branch,
            "action": action.to_dict(), "before": before_hash, "after": after_hash,
            "success": result.success, "reason": result.reason,
            "settle": settle.to_dict() if settle else {
                "frames": 0, "seconds": 0, "quiescent": True},
            "delta": delta,
        }
        if transition:
            record["transition"] = transition
        if metadata:
            record.update(metadata)
        if expected_hash is not None or backtrack_verifier is not None:
            verified = (backtrack_verifier() if backtrack_verifier is not None
                        else after_hash == expected_hash)
            record["backtrack_verified"] = verified
            if not verified:
                record["finding"] = "backtrack did not restore the branch-selection state"
        self.writer.write_state(after_hash, after)
        self.writer.write_step(record)
        return after_hash, record

    def _selector_value(self, control_name: str | None) -> str:
        control = control_map(self.gui).get(control_name or "")
        return str(getattr(control, "text", "") or "").strip()

    def _selector_menu_visible(self, group) -> bool:
        """Recognize a selector menu independently of its selected value."""
        controls = control_map(self.gui)
        required = (group.launcher.control, group.previous.control,
                    group.next.control, group.value_control)
        if any(not name or name not in controls for name in required):
            return False
        for name in required:
            control = controls[name]
            if (not getattr(control, "visible", False)
                    or not getattr(control, "is_active", lambda: True)()
                    or control.rect().width <= 0 or control.rect().height <= 0):
                return False
        available = set(self.action_source(self.gui))
        return all(action in available for action in
                   (group.launcher, group.previous, group.next))

    def _align_selector(self, group, option: str, *, start: float,
                        duration: float, step: int,
                        parent_hash: str) -> tuple[bool, int, str, set[str]]:
        """Move a visible selector to an exact option in entry scope."""
        states: set[str] = set()
        for _ in range(13):
            if (time.monotonic() - start >= duration
                    or not self._selector_menu_visible(group)):
                return False, step, parent_hash, states
            if self._selector_value(group.value_control) == option:
                return True, step, parent_hash, states
            parent_hash, _ = self._record_action(
                group.next, branch="entry", step=step,
                parent_hash=parent_hash, start=start, duration=duration,
                transition="selector_advance",
                metadata={"selector_target": option})
            states.add(parent_hash)
            step += 1
        return False, step, parent_hash, states

    def _enumerate_selector(self, actions: list[UIAction], *, start: float,
                            duration: float, step: int):
        """Behaviorally confirm and enumerate a name-seeded selector."""
        seed = selector_seed(actions, self.gui)
        if seed is None:
            return None, [], step, set()
        initial_state, initial_hash = snapshot_and_hash(self.gui)
        states = {initial_hash}
        value_control = None
        options: list[str] = []
        first_value = ""
        for index in range(12):
            if time.monotonic() - start >= duration:
                break
            before, _before_hash = snapshot_and_hash(self.gui)
            after_hash, record = self._record_action(
                seed.next, branch="entry", step=step,
                parent_hash=initial_hash if index == 0 else record["after"],
                start=start, duration=duration, transition="selector_enumeration")
            step += 1
            states.add(after_hash)
            changed = lightweight_selector_change(
                before, record_delta_state := snapshot_and_hash(self.gui)[0],
                ignored_controls=(seed.previous.control, seed.next.control))
            if index == 0:
                value_control = changed
                if value_control is None:
                    # The observed transition was structural, so this is not a
                    # selector.  Undo the safe directional probe when possible.
                    self._record_action(seed.previous, branch="entry", step=step,
                                        parent_hash=after_hash, start=start,
                                        duration=duration)
                    return None, [], step + 1, states
                # Recover the value before the first next click directly from
                # the canonical snapshot's matching live control.
                live = control_map(self.gui).get(value_control)
                current = str(getattr(live, "text", "") or "").strip()
                self._execute(seed.previous)
                self._settle(start, duration)
                first_value = self._selector_value(value_control)
                self._execute(seed.next)
                self._settle(start, duration)
                options.append(first_value)
            current = self._selector_value(value_control)
            record["selector_value"] = current
            if current in options:
                break
            options.append(current)
        if not options:
            return None, [], step, states
        # Enumeration normally ends when the first option repeats.  With a cap,
        # walk back to the initial selection so branch order stays breadth-first.
        for _ in range(12):
            if self._selector_value(value_control) == options[0]:
                break
            self._execute(seed.next)
            self._settle(start, duration)
        group = type(seed)(seed.launcher, seed.previous, seed.next, value_control)
        # Persist the complete list on a compact summary record.  This record
        # has no action and does not affect branch action findings.
        self.writer.write_step({
            "step": step, "branch": "entry", "transition": "selector_options",
            "before": initial_hash, "after": snapshot_and_hash(self.gui)[1],
            "success": True, "selector_options": options,
            "delta": {"new_controls": [], "removed_controls": [],
                      "changed_controls": []},
        })
        return group, options, step + 1, states

    def _drive_selector(self, group, options: list[str], *, start: float,
                        duration: float, step: int) -> tuple[int, set[str]]:
        states = set()
        for index, option in enumerate(options):
            current_hash = snapshot_and_hash(self.gui)[1]
            aligned, step, selection_hash, alignment_states = self._align_selector(
                group, option, start=start, duration=duration, step=step,
                parent_hash=current_hash)
            states.update(alignment_states)
            if not aligned:
                self.writer.write_step({
                    "step": step, "branch": sanitize_branch_name(option),
                    "transition": "branch_unreachable", "before": selection_hash,
                    "after": selection_hash, "success": False,
                    "finding": "selector menu could not be recovered for planned option",
                    "selector_value": option,
                    "delta": {"new_controls": [], "removed_controls": [],
                              "changed_controls": []},
                })
                step += 1
                continue
            branch = sanitize_branch_name(option)
            after_hash, _ = self._record_action(
                group.launcher, branch=branch, step=step,
                parent_hash=selection_hash, start=start, duration=duration,
                transition="opener", metadata={"selector_value": option})
            step += 1
            states.add(after_hash)
            for _ in range(self.budget.per_branch_actions):
                available = self.action_source(self.gui)
                returns = set(synthesize_backtrack_actions(self.gui))
                internal = [action for action in rank_actions(
                    available, self.gui, self.visited_shapes, self.shape_counts,
                    sibling_sample=self.budget.sibling_sample)
                    if action not in returns and action != group.launcher]
                if not internal or time.monotonic() - start >= duration:
                    break
                after_hash, _ = self._record_action(
                    internal[0], branch=branch, step=step, parent_hash=after_hash,
                    start=start, duration=duration)
                step += 1
                states.add(after_hash)
            returned = False
            candidates = synthesize_backtrack_actions(self.gui)
            candidates.sort(key=lambda action: action.kind == ActionKind.ESCAPE)
            for action in candidates[:3] + [UIAction(ActionKind.ESCAPE, "@escape")] * 3:
                after_hash, record = self._record_action(
                    action, branch=branch, step=step, parent_hash=after_hash,
                    start=start, duration=duration, transition="backtrack",
                    backtrack_verifier=lambda: self._selector_menu_visible(group))
                step += 1
                states.add(after_hash)
                if record["backtrack_verified"]:
                    returned = True
                    break
            if not returned and time.monotonic() - start < duration:
                # Re-observe on the next planned option.  Its alignment step
                # either recovers the known menu or records that option as an
                # explicit failed finding; one failed return cannot end the run.
                continue
        return step, states

    def _drive_sibling_openers(self, openers: list[tuple[str, UIAction]], *,
                               selection_hash: str, start: float,
                               duration: float, step: int) -> tuple[int, set[str]]:
        """Cover every opener once before spending time on deeper sampling."""
        states = {selection_hash}
        settle_cost = max(.05, self.budget.settle_seconds)
        for index, (branch, opener) in enumerate(openers):
            if time.monotonic() - start >= duration:
                break
            after_hash, _record = self._record_action(
                opener, branch=branch, step=step, parent_hash=selection_hash,
                start=start, duration=duration, transition="opener")
            step += 1
            states.add(after_hash)

            remaining_branches = len(openers) - index
            remaining_seconds = max(0., duration - (time.monotonic() - start))
            # Reserve an opener and return transition for every sibling still
            # owed coverage.  Only the surplus can buy in-branch depth.
            reserved = remaining_branches * 2 * settle_cost
            fair_share = max(0., remaining_seconds - reserved) / remaining_branches
            quota = min(self.budget.per_branch_actions, int(fair_share / settle_cost))
            for _ in range(quota):
                available = self.action_source(self.gui)
                returns = set(synthesize_backtrack_actions(self.gui))
                internal = [action for action in rank_actions(
                    available, self.gui, self.visited_shapes, self.shape_counts,
                    sibling_sample=self.budget.sibling_sample)
                    if action not in returns and opener_branch_name(action, self.gui) is None]
                if not internal or time.monotonic() - start >= duration:
                    break
                after_hash, _record = self._record_action(
                    internal[0], branch=branch, step=step, parent_hash=after_hash,
                    start=start, duration=duration)
                step += 1
                states.add(after_hash)

            returned = False
            candidates = synthesize_backtrack_actions(self.gui)
            candidates.sort(key=lambda action: action.kind == ActionKind.ESCAPE)
            for backtrack in candidates[:3]:
                after_hash, record = self._record_action(
                    backtrack, branch=branch, step=step, parent_hash=after_hash,
                    start=start, duration=duration, transition="backtrack",
                    expected_hash=selection_hash)
                step += 1
                states.add(after_hash)
                if record["backtrack_verified"]:
                    returned = True
                    break
            if not returned:
                # Escape is also the safe menu-root recovery path.  Keep
                # trying it and verify every transition against the known
                # selection state rather than assuming a close succeeded.
                for _ in range(3):
                    after_hash, record = self._record_action(
                        UIAction(ActionKind.ESCAPE, "@escape"), branch=branch,
                        step=step, parent_hash=after_hash, start=start,
                        duration=duration, transition="backtrack",
                        expected_hash=selection_hash)
                    step += 1
                    states.add(after_hash)
                    if record["backtrack_verified"]:
                        returned = True
                        break
            if not returned:
                break
        return step, states

    def explore(self, duration: float) -> ExplorerResult:
        start = time.monotonic()
        initial, initial_hash = snapshot_and_hash(self.gui)
        self.writer.write_state(initial_hash, initial)
        # Login bytecode normally predates the explorer.  Capture that initial
        # inventory before the first input or idle pump can add more blobs.
        self.writer.capture_bytecodes(self.game.client, 0)
        queue = deque([(initial_hash, 0)])
        seen = {initial_hash}
        step = actions_done = 0
        self_loops: dict[tuple[str, UIAction], int] = {}
        current_depth = 0
        current_branch = "entry"
        branch_spent: Counter = Counter()
        while len(seen) <= self.budget.max_states:
            if time.monotonic() - start >= duration:
                break
            if not queue:
                if self.pump is None:
                    break
                before, before_hash = snapshot_and_hash(self.gui)
                settle = self._settle(start, duration)
                after, after_hash = snapshot_and_hash(self.gui)
                new_bytecodes = self.writer.capture_bytecodes(self.game.client, step)
                if after_hash == before_hash:
                    continue
                self.writer.write_state(after_hash, after)
                self.writer.write_step({
                    "step": step, "parent_state": before_hash,
                    "action": None, "transition": "spontaneous",
                    "before": before_hash, "after": after_hash,
                    "success": True, "reason": "time-driven UI transition",
                    "settle": settle.to_dict(),
                    "delta": {**state_delta(before, after),
                              "new_bytecodes": new_bytecodes,
                              "new_vms": {}, "new_missing_builtins": {},
                              "new_warning_kinds": {}, "blocked_sends": []},
                })
                step += 1
                if after_hash not in seen and len(seen) < self.budget.max_states:
                    seen.add(after_hash)
                    queue.append((after_hash, min(current_depth + 1,
                                                  self.budget.max_depth)))
                continue
            parent_hash, depth = queue.popleft()
            current_depth = depth
            if depth > self.budget.max_depth:
                continue
            available = self.action_source(self.gui)
            # Return actions are learned from every reached state, so an opened
            # panel cannot strand the walk away from its siblings.
            if available and current_branch != "entry":
                available.extend(synthesize_backtrack_actions(self.gui))
            openers = detect_branch_openers(available, self.gui)
            if current_branch == "entry":
                selector, options, step, selector_states = self._enumerate_selector(
                    available, start=start, duration=duration, step=step)
                if selector is not None:
                    step, branch_states = self._drive_selector(
                        selector, options, start=start, duration=duration, step=step)
                    seen.update(selector_states)
                    seen.update(branch_states)
                    actions_done = step
                    break
            if current_branch == "entry" and openers:
                _selection, selection_hash = snapshot_and_hash(self.gui)
                step, branch_states = self._drive_sibling_openers(
                    openers, selection_hash=selection_hash, start=start,
                    duration=duration, step=step)
                seen.update(branch_states)
                actions_done = step
                break
            if (current_branch != "entry"
                    and branch_spent[current_branch] >= self.budget.per_branch_actions):
                available = [action for action in available
                             if action.kind == ActionKind.ESCAPE or any(
                                 word in action.control.lower()
                                 for word in ("exit", "close", "back", "quit"))]
            actions = rank_actions(
                available, self.gui, self.visited_shapes,
                self.shape_counts, sibling_sample=self.budget.sibling_sample,
            )[:(self.budget.actions_per_state if current_branch == "entry" else
                min(self.budget.actions_per_state, self.budget.per_branch_actions))]
            for action in actions:
                if time.monotonic() - start >= duration:
                    break
                before, before_hash = snapshot_and_hash(self.gui)
                host_before = snapshot_host_counters()
                vm_before = snapshot_vms(self.game.gs2)
                log_before = snapshot_logs(getattr(self.game, "_explorer_log_capture", None))
                blocked_before = len(self.policy.blocked) if self.policy else 0
                result = self._execute(action)
                shape = action_shape(action, self.gui)
                self.visited_shapes.add(shape)
                self.shape_counts[shape] += 1
                settle = self._settle(start, duration)
                after, after_hash = snapshot_and_hash(self.gui)
                blocked = self.policy.since(blocked_before) if self.policy else []
                delta = state_delta(before, after)
                delta.update({
                    "new_bytecodes": self.writer.capture_bytecodes(self.game.client, step),
                    "new_vms": delta_counters(vm_before, snapshot_vms(self.game.gs2)),
                    "new_missing_builtins": delta_counters(
                        host_before.get("missing", {}),
                        snapshot_host_counters().get("missing", {})),
                    "new_host_calls": delta_counters(
                        host_before.get("called", {}),
                        snapshot_host_counters().get("called", {})),
                    "new_warning_kinds": delta_counters(
                        log_before.get("kinds", {}),
                        snapshot_logs(getattr(self.game, "_explorer_log_capture", None)).get("kinds", {})),
                    "blocked_sends": blocked,
                })
                for created in delta.get("new_controls", []):
                    name = str(created.get("name", ""))
                    marker = name.lower().find("games_")
                    if marker >= 0:
                        current_branch = name[marker + len("games_"):] or name
                        break
                if action.kind == ActionKind.ESCAPE or any(
                        word in action.control.lower()
                        for word in ("exit", "close", "back", "quit")):
                    record_branch, current_branch = current_branch, "entry"
                else:
                    record_branch = current_branch
                    branch_spent[current_branch] += 1
                self.writer.write_state(after_hash, after)
                self.writer.write_step({
                    "step": step, "parent_state": parent_hash,
                    "branch": record_branch,
                    "action": action.to_dict(), "before": before_hash,
                    "after": after_hash,
                    "success": result.success, "reason": result.reason,
                    "settle": settle.to_dict() if settle else {
                        "frames": 0, "seconds": 0, "quiescent": True},
                    "delta": delta,
                })
                step += 1
                actions_done += 1
                loop_key = (before_hash, action)
                if after_hash == before_hash:
                    self_loops[loop_key] = self_loops.get(loop_key, 0) + 1
                elif (after_hash not in seen and depth < self.budget.max_depth
                      and len(seen) < self.budget.max_states):
                    seen.add(after_hash)
                    queue.append((after_hash, depth + 1))
                if self_loops.get(loop_key, 0) >= self.budget.repeated_self_loops:
                    continue
                if len(seen) >= self.budget.max_states:
                    break
        report = ExplorerReport(len(seen), actions_done,
                                len(self.policy.blocked) if self.policy else 0)
        manifest_path = self.writer.out_dir / "manifest.json"
        # The initial manifest is durable even if exploration is interrupted;
        # the detailed final counts remain represented by steps.jsonl.
        return ExplorerResult(time.monotonic() - start, report.states,
                              report.actions, report.blocked_sends,
                              str(self.writer.out_dir))
