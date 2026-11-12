"""Frame baselines: a hash of every captured frame, to guard a refactor that
must not change a single pixel.

Off by default; nothing is committed to the repo. Two pytest options, on the
offline render suite:

    --frame-baseline-record=DIR   write DIR/manifest.json (one sha256 per
                                  captured frame, plus the environment it was
                                  taken in) and DIR/<key>.png for each frame
    --frame-baseline-check=DIR    recompute and compare; a frame that differs
                                  fails its test, naming the key and the
                                  bounding box of the differing pixels, and
                                  writes <key>.actual.png, <key>.expected.png
                                  and <key>.diff.png into DIR

The hashes are only valid on the machine, SDL and pygame that recorded them
(font rasterisation and blending are library behaviour), which is why the
manifest holds the environment and a check from a different one refuses to
run. Record, refactor, check: ``record`` replaces the manifest, so run it on
the unrefactored tree.

A capture point is ``capture(game, label)``: the frame ``game.frames()`` last
finished, filed under ``<test id>/<label>``. Several labels per scene (first
frame and last) are what cover animation timing.
"""

import hashlib
import json
import platform
import re
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

import pygame

MANIFEST = "manifest.json"


def environment() -> Dict[str, str]:
    return {"pygame": pygame.version.ver,
            "sdl": ".".join(map(str, pygame.get_sdl_version())),
            "python": sys.version.split()[0],
            "machine": platform.machine(),
            "system": platform.system()}


def frame_hash(surface: "pygame.Surface") -> str:
    digest = hashlib.sha256()
    digest.update(b"%dx%d:" % surface.get_size())
    digest.update(pygame.image.tobytes(surface, "RGB"))
    return digest.hexdigest()


def file_name(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.\[\]-]+", "_", key)


def diff_box(actual: "pygame.Surface", expected: "pygame.Surface"
             ) -> Tuple[Optional[Tuple[int, int, int, int]], int,
                        "pygame.Surface"]:
    """(bounding box x0, y0, x1, y1 inclusive, differing pixel count, an image
    of the actual frame with every differing pixel painted red)."""
    width, height = actual.get_size()
    marked = actual.copy()
    if expected.get_size() != actual.get_size():
        return None, width * height, marked
    a = pygame.image.tobytes(actual, "RGB")
    b = pygame.image.tobytes(expected, "RGB")
    row = width * 3
    x0 = y0 = None
    x1 = y1 = -1
    count = 0
    for y in range(height):
        ra, rb = a[y * row:(y + 1) * row], b[y * row:(y + 1) * row]
        if ra == rb:
            continue
        for x in range(width):
            if ra[x * 3:x * 3 + 3] != rb[x * 3:x * 3 + 3]:
                count += 1
                marked.set_at((x, y), (255, 0, 0))
                x0 = x if x0 is None else min(x0, x)
                x1 = max(x1, x)
                y0 = y if y0 is None else min(y0, y)
                y1 = max(y1, y)
    return ((x0, y0, x1, y1) if count else None), count, marked


class FrameBaseline:
    def __init__(self) -> None:
        self.mode: Optional[str] = None
        self.dir: Optional[Path] = None
        self.current_test = ""
        self.manifest: Dict[str, str] = {}
        self.seen: Dict[str, str] = {}
        self.checked = 0

    # -- configuration -------------------------------------------------------

    def configure(self, record: Optional[str], check: Optional[str]) -> None:
        if record and check:
            raise ValueError("give --frame-baseline-record or "
                             "--frame-baseline-check, not both")
        if record:
            self.mode, self.dir = "record", Path(record)
            self.dir.mkdir(parents=True, exist_ok=True)
        elif check:
            self.mode, self.dir = "check", Path(check)
            path = self.dir / MANIFEST
            if not path.exists():
                raise ValueError(f"no {MANIFEST} in {self.dir}: record one "
                                 f"first with --frame-baseline-record")
            data = json.loads(path.read_text())
            if data["environment"] != environment():
                raise ValueError(
                    "the baseline was recorded under "
                    f"{data['environment']}, this run is {environment()}: "
                    "hashes are only valid on the machine and library "
                    "versions that recorded them; record again here")
            self.manifest = data["frames"]

    @property
    def active(self) -> bool:
        return self.mode is not None

    # -- capture ---------------------------------------------------------------

    def capture(self, key: str, surface: "pygame.Surface") -> None:
        digest = frame_hash(surface)
        if key in self.seen:
            assert self.seen[key] == digest, (
                f"frame baseline key {key!r} was captured twice with "
                "different pixels: two capture points share a label")
            return
        self.seen[key] = digest
        stem = self.dir / file_name(key)
        if self.mode == "record":
            stem.parent.mkdir(parents=True, exist_ok=True)
            pygame.image.save(surface, str(stem) + ".png")
            return
        self.checked += 1
        assert key in self.manifest, (
            f"frame baseline: no recorded frame for {key!r}; the suite "
            "captures a point that was not captured when recording")
        if self.manifest[key] == digest:
            return
        expected_path = Path(str(stem) + ".png")
        box, count, marked = None, -1, surface
        if expected_path.exists():
            expected = pygame.image.load(str(expected_path))
            box, count, marked = diff_box(surface, expected)
            pygame.image.save(expected, str(stem) + ".expected.png")
        pygame.image.save(surface, str(stem) + ".actual.png")
        pygame.image.save(marked, str(stem) + ".diff.png")
        raise AssertionError(
            f"frame baseline mismatch in {key!r}: {count} pixels differ, "
            f"bounding box (x0, y0, x1, y1) = {box}; "
            f"actual/expected/diff PNGs are in {self.dir}")

    # -- end of session --------------------------------------------------------

    def finish(self) -> str:
        if self.mode == "record":
            (self.dir / MANIFEST).write_text(json.dumps(
                {"environment": environment(),
                 "frames": dict(sorted(self.seen.items()))}, indent=1) + "\n")
            return f"frame baseline: recorded {len(self.seen)} frames in {self.dir}"
        if self.mode == "check":
            unvisited = len(set(self.manifest) - set(self.seen))
            return (f"frame baseline: checked {self.checked} frames against "
                    f"{self.dir} ({unvisited} recorded frames not captured "
                    "this run)")
        return ""


BASELINE = FrameBaseline()


def capture(game, label: str) -> None:
    """File ``game``'s last finished frame under ``<test id>/<label>``. A
    no-op unless a baseline option is on."""
    if not BASELINE.active:
        return
    if game.last_frame is None:
        raise AssertionError("capture needs a frame: run game.frames() first")
    BASELINE.capture(f"{BASELINE.current_test}/{label}", game.last_frame)
