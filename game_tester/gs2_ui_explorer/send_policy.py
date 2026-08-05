from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pyreborn.packets import PacketID


PASSIVE_ALLOWLIST = frozenset({
    PacketID.PLI_UPDATESCRIPT, PacketID.PLI_UPDATECLASS,
    PacketID.PLI_UPDATEGANI, PacketID.PLI_UPDATEFILE, PacketID.PLI_WANTFILE,
})


def _packet_name(packet_id: int) -> str:
    for name, value in vars(PacketID).items():
        if name.startswith("PLI_") and value == packet_id:
            return name
    return f"PLI_{packet_id}"


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    record: dict[str, Any] | None = None


class PassiveSendPolicy:
    """Allow engine/session traffic; default-deny other script traffic."""

    def __init__(self, record_path: str | Path | None = None,
                 allow_sends: bool = False):
        self.mode = "full" if allow_sends else "passive"
        self.record_path = Path(record_path) if record_path else None
        self.blocked: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def __call__(self, packet_id: int, data: bytes, origin: dict[str, Any],
                 metadata: dict[str, Any] | None = None) -> PolicyDecision:
        script = not bool(origin.get("engine", True))
        allowed = (self.mode == "full" or not script
                   or packet_id in PASSIVE_ALLOWLIST)
        if allowed:
            return PolicyDecision(True)
        payload = bytes(data)
        record = {
            "decision": "blocked", "mode": self.mode,
            "origin": {
                "engine": False,
                "kind": str(origin.get("kind", "script")),
                "name": str(origin.get("name", "")),
                "function": str(origin.get("function", "")),
            },
            "packet_id": int(packet_id), "packet_name": _packet_name(packet_id),
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "payload_preview": payload[:64].hex(),
        }
        with self._lock:
            self.blocked.append(record)
            if self.record_path is not None:
                self.record_path.parent.mkdir(parents=True, exist_ok=True)
                with self.record_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record, sort_keys=True) + "\n")
        return PolicyDecision(False, record)

    def since(self, index: int) -> list[dict[str, Any]]:
        return list(self.blocked[index:])
