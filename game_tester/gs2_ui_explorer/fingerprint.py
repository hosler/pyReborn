from __future__ import annotations

import hashlib
import json
from typing import Any

from reborn_protocol.gs2 import to_str


def _hash_text(value: Any) -> str:
    return hashlib.sha256(to_str(value).encode("utf-8")).hexdigest()


def _surface_hash(surface: Any) -> str:
    """Stable pixel identity for an unnamed pygame-compatible surface."""
    try:
        import pygame
        size = surface.get_size()
        pixels = pygame.image.tobytes(surface, "RGBA")
    except (AttributeError, TypeError, ValueError):
        return ""
    digest = hashlib.sha256()
    digest.update(f"{size[0]}x{size[1]}:".encode("ascii"))
    digest.update(pixels)
    return "sha256:" + digest.hexdigest()


def _image_identity(control: Any) -> dict[str, Any] | None:
    identity: dict[str, Any] = {}
    bitmap = getattr(control, "bitmap", "")
    if bitmap:
        identity["bitmap"] = to_str(bitmap)
    bitmaps = getattr(control, "bitmaps", None)
    if bitmaps is not None:
        identity["frames"] = [to_str(value) for value in bitmaps]
        identity["checked"] = bool(getattr(control, "checked", False))
    icon = getattr(control, "icon_image", "")
    if icon:
        identity["icon"] = to_str(icon)
    if not identity:
        for attr in ("surface", "_surface", "_scaled_surf"):
            content_hash = _surface_hash(getattr(control, attr, None))
            if content_hash:
                identity["content_hash"] = content_hash
                break
    if hasattr(control, "ani"):
        identity["ani"] = to_str(getattr(control, "ani", ""))
        identity["dir"] = int(getattr(control, "direction", 0))
    return identity or None


def _event_names(gui: Any, control: Any) -> list[str]:
    names = set(getattr(control, "_event_catchers", {}) or {})
    for name in getattr(control, "_EVENT_MEMBERS", ()):
        try:
            if callable(control.get(name)):
                names.add(name.lower())
        except Exception:
            pass
    ctrl_name = str(getattr(control, "ctrl_name", "") or "").lower()
    names.update((getattr(gui, "_pending_catchers", {}).get(ctrl_name, {}) or {}))
    rt2 = getattr(gui, "rt2", None)
    dotted_prefix = f"{ctrl_name}."
    for group in getattr(rt2, "vms", {}).values() if rt2 is not None else ():
        for vm in group.values():
            functions = getattr(vm, "functions", {})
            names.update(key[len(dotted_prefix):] for key in functions
                         if str(key).lower().startswith(dotted_prefix))
    return sorted(str(name).lower() for name in names)


def canonical_state(gui: Any) -> dict[str, Any]:
    controls = []

    def visit(control: Any, path: str, shown: bool) -> None:
        shown = shown and bool(getattr(control, "visible", False))
        rect = control.rect()
        name = str(getattr(control, "ctrl_name", "") or "")
        record: dict[str, Any] = {
            "path": path, "name": name.lower(), "class": type(control).__name__,
            "visible": bool(getattr(control, "visible", False)),
            "effective_visible": shown,
            "active": bool(getattr(control, "is_active", lambda: True)()),
            "rect": [rect.x, rect.y, rect.width, rect.height],
            "text_hash": _hash_text(getattr(control, "text", "")),
            "events": _event_names(gui, control),
        }
        image = _image_identity(control)
        if image is not None:
            record["image"] = image
        for attr in ("checked", "button_type", "selected_index", "selected_row",
                     "popup_open"):
            if hasattr(control, attr):
                record[attr] = getattr(control, attr)
        rows = getattr(control, "list_rows", None)
        if rows is not None:
            record["rows"] = [_hash_text(row.get("text")) for row in rows]
        popup_rows = getattr(control, "rows", None)
        if popup_rows is not None:
            record["rows"] = [_hash_text(row[1]) for row in popup_rows]
        flat = getattr(control, "flat_nodes", None)
        if callable(flat):
            record["nodes"] = [_hash_text(getattr(node, "text", ""))
                               for node in flat()]
        controls.append(record)
        for index, child in enumerate(list(getattr(control, "children", ()) or ())):
            child_name = str(getattr(child, "ctrl_name", "") or type(child).__name__)
            visit(child, f"{path}/{index}:{child_name.lower()}", shown)

    for index, root in enumerate(list(getattr(gui, "roots", ()) or ())):
        name = str(getattr(root, "ctrl_name", "") or type(root).__name__)
        visit(root, f"{index}:{name.lower()}", True)
    return {"controls": controls,
            "popup": str(getattr(getattr(gui, "_open_popup", None),
                                 "ctrl_name", "") or "").lower()}


def state_hash(state: dict[str, Any]) -> str:
    raw = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def snapshot_and_hash(gui: Any) -> tuple[dict[str, Any], str]:
    state = canonical_state(gui)
    return state, state_hash(state)


def state_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    left = {item["path"]: item for item in before.get("controls", [])}
    right = {item["path"]: item for item in after.get("controls", [])}
    return {
        "new_controls": [right[key] for key in sorted(right.keys() - left.keys())],
        "removed_controls": [left[key] for key in sorted(left.keys() - right.keys())],
        "changed_controls": [right[key] for key in sorted(left.keys() & right.keys())
                             if left[key] != right[key]],
    }
