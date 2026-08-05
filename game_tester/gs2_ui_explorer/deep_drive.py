from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


@dataclass
class BranchFinding:
    name: str
    states_explored: int = 0
    actions_explored: int = 0
    new_controls_built: int = 0
    missing_builtins: dict[str, int] = field(default_factory=dict)
    warning_samples: list[str] = field(default_factory=list)
    host_calls: list[str] = field(default_factory=list)
    blocked_sends: int = 0
    dead_buttons: list[str] = field(default_factory=list)
    built_controls: bool = False
    timer_driven_changes: int = 0
    backtrack_success: bool = False
    backtrack_failures: int = 0

    @property
    def brokenness(self) -> int:
        return (len(self.dead_buttons) * 4 + sum(self.missing_builtins.values()) * 3
                + len(self.warning_samples) * 2 + (0 if self.built_controls else 8))


def build_deep_report(records: Iterable[dict[str, Any]],
                      warning_samples: dict[str, Any] | None = None) -> dict[str, Any]:
    records = list(records)
    selector_options = next((list(record.get("selector_options", []))
                             for record in records
                             if record.get("transition") == "selector_options"), [])
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        branch = str(record.get("branch") or "unattributed")
        grouped[branch].append(record)
    findings = []
    for name, steps in grouped.items():
        states = set()
        missing, calls = Counter(), Counter()
        warnings, dead = [], []
        new_controls = blocked = timers = 0
        backtrack_success = False
        backtrack_failures = 0
        for step in steps:
            states.update(filter(None, (step.get("before"), step.get("after"))))
            delta = step.get("delta", {}) or {}
            created = delta.get("new_controls", []) or []
            new_controls += len(created)
            missing.update(delta.get("new_missing_builtins", {}) or {})
            calls.update(delta.get("new_host_calls", {}) or {})
            blocked += len(delta.get("blocked_sends", []) or [])
            warning_kinds = delta.get("new_warning_kinds", {}) or {}
            warnings.extend(sorted(warning_kinds))
            if step.get("transition") == "spontaneous" and step.get("before") != step.get("after"):
                timers += 1
            if step.get("transition") == "backtrack":
                backtrack_success = backtrack_success or bool(step.get("backtrack_verified"))
                backtrack_failures += not bool(step.get("backtrack_verified"))
            action = step.get("action") or {}
            if (action.get("kind") == "click" and step.get("success")
                    and step.get("before") == step.get("after")
                    and not warning_kinds and not delta.get("blocked_sends")):
                dead.append(str(action.get("control", "unknown")))
        for template, samples in (warning_samples or {}).items():
            if name.lower() in json.dumps(samples).lower():
                warnings.extend(sample.get("message", template) for sample in samples[:3])
        finding = BranchFinding(
            name=name, states_explored=len(states), actions_explored=len(steps),
            new_controls_built=new_controls, missing_builtins=dict(sorted(missing.items())),
            warning_samples=list(dict.fromkeys(warnings))[:5],
            host_calls=sorted(calls), blocked_sends=blocked,
            dead_buttons=list(dict.fromkeys(dead)), built_controls=new_controls > 0,
            timer_driven_changes=timers,
            backtrack_success=backtrack_success,
            backtrack_failures=backtrack_failures,
        )
        findings.append(finding)
    findings.sort(key=lambda item: (-item.brokenness, item.name.lower()))
    return {"schema_version": 1, "selector_options": selector_options, "branches": [
        {**asdict(item), "brokenness": item.brokenness} for item in findings
    ]}


def write_deep_report(out_dir: str | Path, report: dict[str, Any]) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "deep_report.json"
    md_path = out / "deep_report.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    lines = ["# GS2 UI deep-drive report", ""]
    options = report.get("selector_options", [])
    if options:
        lines.extend([f"Selector options: {', '.join(options)}", ""])
    for branch in report.get("branches", []):
        lines.extend([
            f"## {branch['name']}", "",
            f"Brokenness: {branch['brokenness']}; states/actions: "
            f"{branch['states_explored']}/{branch['actions_explored']}; "
            f"new controls: {branch['new_controls_built']}; blocked sends: "
            f"{branch['blocked_sends']}; timer changes: {branch['timer_driven_changes']}.", "",
            f"Dead buttons: {', '.join(branch['dead_buttons']) or 'none'}", "",
            f"Missing builtins: {json.dumps(branch['missing_builtins'], sort_keys=True)}", "",
            f"Host calls: {', '.join(branch['host_calls']) or 'none'}", "",
            f"Warnings: {'; '.join(branch['warning_samples']) or 'none'}", "",
            f"Backtrack verified: {branch['backtrack_success']}", "",
            f"Backtrack failures: {branch['backtrack_failures']}", "",
        ])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path, json_path


def report_capture(out_dir: str | Path) -> dict[str, Any]:
    out = Path(out_dir)
    records = [json.loads(line) for line in (out / "steps.jsonl").read_text().splitlines()]
    samples_path = out / "warning_samples.json"
    samples = json.loads(samples_path.read_text()) if samples_path.exists() else {}
    report = build_deep_report(records, samples)
    write_deep_report(out, report)
    return report
