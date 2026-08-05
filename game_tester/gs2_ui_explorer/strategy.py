from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable

from .actions import ActionKind, UIAction
from .interactables import control_map


_RETURN_WORDS = re.compile(r"(?:^|[_ .-])(exit|close|back|quit)(?:$|[_ .-])", re.I)
_NUMBER_RUN = re.compile(r"\d+")
_DIRECTION_WORDS = re.compile(r"(?:^|[_ .-])(left|right|prev|previous|next|arrow)(?:$|[_ .-])", re.I)
_GAME_BRANCHES = {
    "aztek": "aztek", "blackjack": "blackjack",
    "guessnumber": "guessnumber", "guessthenumber": "guessnumber",
    "memorymatch": "memorymatch", "splatman": "splatman",
    "tictactoe": "tictactoe",
}


@dataclass(frozen=True)
class SelectorGroup:
    """A launcher and the two controls which change its selected option."""

    launcher: UIAction
    previous: UIAction
    next: UIAction
    value_control: str | None = None


def sanitize_branch_name(value: str) -> str:
    """Turn a selector's displayed value into a stable report identity."""
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower()) or "option"


def enumerate_selector_values(read_value, advance, *, cap: int = 12) -> list[str]:
    """Enumerate values until the first repeats, bounded for non-cycling UIs."""
    values = []
    for _ in range(cap):
        value = str(read_value()).strip()
        if value in values:
            break
        values.append(value)
        advance()
    return values


def selector_seed(actions: Iterable[UIAction], gui: Any) -> SelectorGroup | None:
    """Find a conservative launcher/previous/next candidate for probing.

    Names merely make probing safe; a candidate becomes a selector only after
    its click is observed to make a lightweight sibling text/image change.
    """
    clicks = [action for action in sorted(set(actions), key=UIAction.sort_key)
              if action.kind == ActionKind.CLICK]
    previous = next_action = None
    for action in clicks:
        identity = action.control.lower()
        if re.search(r"(?:left|prev|previous)", identity):
            previous = previous or action
        if re.search(r"(?:right|next)", identity):
            next_action = next_action or action
    if previous is None or next_action is None:
        arrows = [action for action in clicks if "arrow" in action.control.lower()]
        if len(arrows) >= 2:
            previous, next_action = arrows[:2]
    if previous is None or next_action is None:
        return None

    controls = control_map(gui)
    excluded = {previous, next_action}
    launchers = [action for action in clicks if action not in excluded
                 and not _DIRECTION_WORDS.search(action.control)]
    if not launchers:
        return None

    def launcher_rank(action: UIAction) -> tuple[int, int, str]:
        control = controls.get(action.control)
        rect = control.rect() if control is not None else None
        area = rect.width * rect.height if rect is not None else 0
        name = action.control.lower()
        hint = any(word in name for word in
                   ("selection", "launch", "play", "start", "open"))
        return (int(hint), area, name)

    launcher = max(launchers, key=launcher_rank)
    return SelectorGroup(launcher, previous, next_action)


def lightweight_selector_change(before: dict[str, Any], after: dict[str, Any],
                                *, ignored_controls: Iterable[str] = ()) -> str | None:
    """Return the changed value-control name for a text/image-only delta."""
    left = {item["path"]: item for item in before.get("controls", [])}
    right = {item["path"]: item for item in after.get("controls", [])}
    if left.keys() != right.keys():
        return None
    ignored = {name.lower() for name in ignored_controls}
    candidates = []
    lightweight = {"text_hash", "image", "checked"}
    for path in left:
        old, new = left[path], right[path]
        if old == new:
            continue
        changed = {key for key in old.keys() | new.keys()
                   if old.get(key) != new.get(key)}
        if not changed <= lightweight:
            return None
        if new.get("name", "").lower() not in ignored:
            text_change = "text_hash" in changed
            text_control = "text" in str(new.get("class", "")).lower()
            candidates.append((text_change, text_control, new.get("name", "")))
    candidates.sort(reverse=True)
    return next((name for _text, _class, name in candidates if name), None)


def opener_branch_name(action: UIAction, gui: Any) -> str | None:
    """Return a stable branch name for a visible game-launch control."""
    if action.kind != ActionKind.CLICK:
        return None
    control = control_map(gui).get(action.control)
    text = str(getattr(control, "text", "") or "")
    identity = re.sub(r"[^a-z0-9]", "", action.control.lower())
    label = re.sub(r"[^a-z0-9]", "", text.lower())
    for marker, name in _GAME_BRANCHES.items():
        if (marker in identity and "game" in identity) or label == marker:
            return name
    return None


def detect_branch_openers(actions: Iterable[UIAction], gui: Any) -> list[tuple[str, UIAction]]:
    """Find distinct sibling launchers without confusing in-game controls."""
    found: dict[str, UIAction] = {}
    for action in sorted(set(actions), key=UIAction.sort_key):
        name = opener_branch_name(action, gui)
        if name is not None:
            found.setdefault(name, action)
    # A lone game-named control can be part of an already-open game.  Branch
    # mode begins only at a genuine selection surface with sibling choices.
    return sorted(found.items()) if len(found) >= 2 else []


def action_shape(action: UIAction, gui: Any) -> tuple[str, str, str]:
    """A stable structural identity which groups interchangeable siblings."""
    control = control_map(gui).get(action.control)
    class_name = type(control).__name__ if control is not None else "unknown"
    name = _NUMBER_RUN.sub("#", action.control.lower())
    # Common grids use trailing letters instead of digits (cell_a, cell_b).
    name = re.sub(r"(?<=[_.-])[a-z]$", "#", name)
    return class_name, action.kind.value, name


def rank_actions(actions: Iterable[UIAction], gui: Any,
                 visited_shapes: set[tuple[str, str, str]],
                 shape_counts: Counter | None = None,
                 *, sibling_sample: int = 3) -> list[UIAction]:
    """Put novel structural branches first and damp repeated grid siblings."""
    counts = shape_counts or Counter()
    ranked = []
    offered = Counter()
    for stable_index, action in enumerate(sorted(set(actions), key=UIAction.sort_key)):
        shape = action_shape(action, gui)
        repeated = counts[shape] + offered[shape]
        if shape in visited_shapes and repeated >= sibling_sample:
            continue
        offered[shape] += 1
        is_return = action.kind == ActionKind.ESCAPE
        ranked.append((is_return, shape in visited_shapes, repeated, stable_index, action))
    return [item[-1] for item in sorted(ranked, key=lambda item: item[:-1])]


def synthesize_backtrack_actions(gui: Any) -> list[UIAction]:
    """Return visible close-like controls followed by the universal Escape."""
    actions = []
    for key, control in sorted(control_map(gui).items()):
        if not getattr(control, "_awake", False) or not control.effectively_visible():
            continue
        text = str(getattr(control, "text", "") or "")
        class_name = type(control).__name__.lower()
        if _RETURN_WORDS.search(f"{key} {text}"):
            actions.append(UIAction(ActionKind.CLICK, key))
        elif "guiwindowctrl" in class_name:
            actions.append(UIAction(ActionKind.ESCAPE, key, text="window-close"))
    actions.append(UIAction(ActionKind.ESCAPE, "@escape"))
    return sorted(set(actions), key=UIAction.sort_key)


@dataclass
class BranchScheduler:
    per_branch_budget: int = 12
    spent: Counter = field(default_factory=Counter)
    rounds: Counter = field(default_factory=Counter)

    def allows(self, branch: str) -> bool:
        return self.spent[branch] < (self.rounds[branch] + 1) * self.per_branch_budget

    def record(self, branch: str) -> None:
        self.spent[branch] += 1

    def next_round(self, branches: Iterable[str]) -> None:
        for branch in branches:
            self.rounds[branch] += 1
