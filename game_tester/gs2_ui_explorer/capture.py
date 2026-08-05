from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def default_output_dir() -> Path:
    root = os.environ.get("PYREBORN_DATA")
    base = Path(root) if root else Path.home() / ".local" / "share" / "pyreborn"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return base / "gs2_ui_explorer" / stamp


class CaptureWriter:
    def __init__(self, out_dir: str | Path | None = None,
                 manifest: dict[str, Any] | None = None):
        self.out_dir = Path(out_dir) if out_dir else default_output_dir()
        self.states_dir = self.out_dir / "artifacts" / "states"
        self.bytecode_dir = self.out_dir / "artifacts" / "bytecode"
        self.bytecodes_path = self.out_dir / "bytecodes.jsonl"
        self.states_dir.mkdir(parents=True, exist_ok=True)
        self.bytecode_dir.mkdir(parents=True, exist_ok=True)
        self.steps_path = self.out_dir / "steps.jsonl"
        self.blocked_path = self.out_dir / "blocked_sends.jsonl"
        self.warning_samples_path = self.out_dir / "warning_samples.json"
        self._bytecodes: set[str] = set()
        self._warning_samples: dict[str, list[dict[str, str]]] = {}
        data = {"schema_version": 1,
                "created_at": datetime.now(timezone.utc).isoformat(),
                **(manifest or {})}
        (self.out_dir / "manifest.json").write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def write_state(self, state_hash: str, state: dict[str, Any]) -> Path:
        digest = state_hash.removeprefix("sha256:")
        path = self.states_dir / f"{digest}.json"
        if not path.exists():
            path.write_text(json.dumps(state, sort_keys=True) + "\n",
                            encoding="utf-8")
        return path

    def capture_bytecodes(self, client: Any, step: int) -> list[dict[str, Any]]:
        found = []
        for kind, blobs in sorted((getattr(client, "gs2_bytecode", {}) or {}).items()):
            for name, raw in sorted(blobs.items(), key=lambda item: str(item[0])):
                blob = bytes(raw)
                digest = hashlib.sha256(blob).hexdigest()
                if digest in self._bytecodes:
                    continue
                self._bytecodes.add(digest)
                path = self.bytecode_dir / f"{digest}.gs2bc"
                if not path.exists():
                    path.write_bytes(blob)
                found.append({"kind": str(kind), "name": str(name),
                              "size": len(blob), "sha256": digest,
                              "first_seen_step": step})
        if found:
            with self.bytecodes_path.open("a", encoding="utf-8") as stream:
                for record in found:
                    stream.write(json.dumps(record, sort_keys=True) + "\n")
        return found

    def write_step(self, record: dict[str, Any]) -> None:
        with self.steps_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")

    def record_warning(self, template: str, formatted: str, vm: str = "",
                       *, limit: int = 5) -> None:
        """Keep bounded formatted examples alongside a stable log template."""
        samples = self._warning_samples.setdefault(template, [])
        sample = {"vm": vm or "unknown", "message": formatted[:500]}
        if sample not in samples and len(samples) < limit:
            samples.append(sample)
            self.warning_samples_path.write_text(
                json.dumps(self._warning_samples, indent=2, sort_keys=True) + "\n",
                encoding="utf-8")

    def warning_handler(self, *, limit: int = 5) -> logging.Handler:
        writer = self

        class Handler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                if not record.name.startswith(("pyreborn.gs2_client", "reborn_protocol.gs2")):
                    return
                template = f"{record.name}|{record.levelname}|{str(record.msg)[:160]}"
                try:
                    message = record.getMessage()
                except Exception:
                    message = str(record.msg)
                # Engine warnings conventionally start "GS2 <vm>...". Keep
                # that token separately so samples remain attributable.
                words = message.split()
                vm = words[1].rstrip(".:()") if len(words) > 1 and words[0] == "GS2" else record.name
                writer.record_warning(template, message, vm, limit=limit)

        return Handler(level=logging.WARNING)
