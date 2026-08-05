from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class ActionKind(str, Enum):
    CLICK = "click"
    SELECT_ROW = "select_row"
    SELECT_TAB = "select_tab"
    SELECT_TREE = "select_tree"
    OPEN_POPUP = "open_popup"
    SELECT_POPUP = "select_popup"
    FOCUS = "focus"
    TYPE_TEXT = "type_text"
    BACKSPACE = "backspace"
    SUBMIT = "submit"
    TAB = "tab"
    ESCAPE = "escape"


@dataclass(frozen=True)
class UIAction:
    kind: ActionKind
    control: str
    row: int | None = None
    text: str = ""
    label_hash: str = ""
    double: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["kind"] = self.kind.value
        return {key: item for key, item in value.items()
                if item not in (None, "", False)}

    def sort_key(self) -> tuple:
        return (self.control.lower(), self.kind.value,
                -1 if self.row is None else self.row, self.label_hash,
                self.text, self.double)
