from __future__ import annotations

import hashlib
from typing import Any

from reborn_protocol.gs2 import to_num, to_str
from pyreborn.game.gs2_gui import (
    GuiButtonBaseCtrl, GuiPopUpEditCtrl, GuiTabCtrl, GuiTextEditCtrl,
    GuiTextListCtrl, GuiTreeViewCtrl,
)

from .actions import ActionKind, UIAction


def _label_hash(value: Any) -> str:
    return hashlib.sha256(to_str(value).encode("utf-8")).hexdigest()


def control_key(control: Any) -> str:
    return str(getattr(control, "ctrl_name", "") or
               getattr(control, "name", "") or f"@{id(control)}").lower()


def control_map(gui: Any) -> dict[str, Any]:
    found = {}
    stack = list(reversed(list(getattr(gui, "roots", ()) or ())))
    while stack:
        control = stack.pop()
        found[control_key(control)] = control
        stack.extend(reversed(list(getattr(control, "children", ()) or ())))
    return found


def enumerate_actions(gui: Any) -> list[UIAction]:
    actions = []
    for key, control in control_map(gui).items():
        if (not getattr(control, "_awake", False)
                or not control.effectively_visible()):
            continue
        rect = control.rect()
        if rect.width <= 0 or rect.height <= 0:
            continue
        if isinstance(control, GuiButtonBaseCtrl) and control.is_active():
            actions.append(UIAction(ActionKind.CLICK, key))
        elif isinstance(control, GuiTabCtrl):
            for index, row in enumerate(control.list_rows):
                if index != control.selected_index:
                    actions.append(UIAction(ActionKind.SELECT_TAB, key, index,
                                            label_hash=_label_hash(row.get("text"))))
        elif isinstance(control, GuiTextListCtrl):
            for index, row in enumerate(control.list_rows):
                text = to_str(row.get("text"))
                active = row.get("active")
                if text != "-" and (active is None or to_num(active)):
                    actions.append(UIAction(ActionKind.SELECT_ROW, key, index,
                                            label_hash=_label_hash(text)))
        elif isinstance(control, GuiTreeViewCtrl):
            for index, node in enumerate(control.flat_nodes()):
                actions.append(UIAction(ActionKind.SELECT_TREE, key, index,
                                        label_hash=_label_hash(getattr(node, "text", ""))))
        elif isinstance(control, GuiPopUpEditCtrl):
            actions.append(UIAction(ActionKind.OPEN_POPUP, key))
            for index, (_row_id, text) in enumerate(control.rows):
                actions.append(UIAction(ActionKind.SELECT_POPUP, key, index,
                                        label_hash=_label_hash(text)))
        elif isinstance(control, GuiTextEditCtrl):
            actions.append(UIAction(ActionKind.FOCUS, key))
            if not control.is_password():
                actions.append(UIAction(ActionKind.TYPE_TEXT, key, text="qa"))
                actions.append(UIAction(ActionKind.BACKSPACE, key))
                actions.append(UIAction(ActionKind.SUBMIT, key))
    return sorted(set(actions), key=UIAction.sort_key)
