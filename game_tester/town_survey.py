"""town_survey - visual survey of a world's levels for aesthetic review.

Logs one real rendering client (Client + GameClient, SDL dummy driver - the
feel_probe.py pattern) into a live server, warps it through a list of levels,
and writes two images per level:

- ``<level>_view.png``   - the actual rendered viewport (what a player sees:
  tiles, NPC ganis, lights, showimgs), captured after the level's scripts
  have had time to fire.
- ``<level>_board.png``  - a full 64x64-tile composite of the level board
  built from the real tileset, with NPC positions marked. This is the
  layout/aesthetics view a viewport crop can't give.

An ``index.json`` records per-level NPC counts and positions so a reviewer
(human or LLM) can cross-reference the markers.

Run:
    SDL_VIDEODRIVER=dummy ../.venv/bin/python -m game_tester.town_survey \
        --host 127.0.0.1 --port 14900 --account surveybot --password pw \
        --out-dir /tmp/town_survey
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from reborn_protocol.coords import segment_at
from pyreborn import Client
from pyreborn import tiletypes
from pyreborn.pygame_game import GameClient
from game_tester.login import login_client
import logging
from pyreborn.logutil import log_swallowed
logger = logging.getLogger(__name__)

FPS = 60
TILE_PX = 16
# Close-up window around an NPC's anchor, in tiles. A character NPC draws
# about 3x3 tiles right/below its anchor, so the window leans that way.
CLOSEUP_LEFT, CLOSEUP_TOP, CLOSEUP_W, CLOSEUP_H = 3, 3, 9, 9
CLOSEUP_SCALE = 3

DEFAULT_LEVELS = [
    "chicken1.nw", "chicken2.nw", "chicken3.nw", "chicken4.nw",
    "chicken5.nw", "chicken6.nw", "chicken7.nw", "chicken8.nw",
    "chicken9.nw", "chicken_house1.nw", "chicken_cave_entrance.nw",
    "chicken_cave_1.nw", "chicken_cave_2.nw", "chicken_pk.nw",
    "chicken_ko_lobby.nw", "ball_lobby.nw",
]


class Survey:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.out = Path(args.out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.client: Optional[Client] = None
        self.game: Optional[GameClient] = None
        self.index: Dict[str, Any] = {"levels": {}, "notes": []}

    # -- frame loop -------------------------------------------------------
    def pump(self, frames: int = 1) -> None:
        game = self.game
        for _ in range(frames):
            game.step(1.0 / FPS, strict=True)
            game.frame_limiter.tick(FPS)

    def settle(self) -> None:
        self.game.start()
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            self.pump()
            if (getattr(self.client, "_current_level_name", "") and
                    len(getattr(self.client, "tiles", []) or []) >= 4096 and
                    math.isfinite(float(self.client.x))):
                return
        raise RuntimeError("level board never arrived")

    # -- captures ---------------------------------------------------------
    def level_npcs(self, level_name: str) -> List[Dict[str, Any]]:
        # On a gmap, NPC coords are world coords and the npc dict's level
        # field is unreliable; attribute each NPC to the segment its
        # position falls in, exactly as the client does for the player.
        grid = getattr(self.client, "gmap_grid", {}) or {}
        on_gmap = level_name in grid.values()
        rows = []
        for npc_id, npc in (getattr(self.client, "npcs", {}) or {}).items():
            if not isinstance(npc, dict):
                continue
            try:
                nx = float(npc.get("world_x", npc.get("x")))
                ny = float(npc.get("world_y", npc.get("y")))
            except (TypeError, ValueError):
                continue
            if on_gmap:
                if grid.get(segment_at(nx, ny)) != level_name:
                    continue
            elif (npc.get("level") or "") not in ("", level_name):
                continue
            rows.append({
                "id": npc_id,
                "x": nx, "y": ny,
                "local_x": nx % 64, "local_y": ny % 64,
                "image": npc.get("image") or "",
                "nickname": npc.get("nickname") or "",
                "gani": npc.get("gani") or npc.get("animation") or "",
                "character": bool(npc.get("is_character")),
                "body": npc.get("bodyimage") or "",
                "head": npc.get("headimage") or "",
                "visible": npc.get("visible", True) is not False,
            })
        return rows

    def capture_board(self, level_name: str, stem: str) -> Optional[str]:
        board = list(getattr(self.client, "tiles", []) or [])
        if len(board) < 4096:
            return None
        surface = pygame.Surface((64 * TILE_PX, 64 * TILE_PX))
        get_tile = self.game.tileset_mgr.get_tile_or_color
        for y in range(64):
            for x in range(64):
                tile = get_tile(board[y * 64 + x])
                if tile is not None:
                    surface.blit(tile, (x * TILE_PX, y * TILE_PX))
        # NPC markers: layout evidence, deliberately loud.
        for npc in self.level_npcs(level_name):
            nx = int(npc["local_x"]) * TILE_PX
            ny = int(npc["local_y"]) * TILE_PX
            pygame.draw.rect(surface, (255, 0, 0),
                             pygame.Rect(nx, ny, TILE_PX * 2, TILE_PX * 2), 2)
        path = self.out / f"{stem}_board.png"
        pygame.image.save(surface, path)
        return path.name

    def capture_view(self, stem: str) -> str:
        path = self.out / f"{stem}_view.png"
        pygame.image.save(pygame.display.get_surface() or self.game.screen, path)
        return path.name

    def ground_types(self, local_x: float, local_y: float) -> List[List[str]]:
        """Tile-type names for the 4x4 tiles from the NPC anchor, row-major.
        A character's feet sit around (x+1, y+2.5), so this covers the
        ground a placement check needs (chair, road, water, wall...)."""
        board = list(getattr(self.client, "tiles", []) or [])
        rows = []
        for ty in range(int(local_y), int(local_y) + 4):
            row = []
            for tx in range(int(local_x), int(local_x) + 4):
                if not (0 <= tx < 64 and 0 <= ty < 64) or len(board) < 4096:
                    row.append("-")
                    continue
                tid = board[ty * 64 + tx]
                try:
                    name = tiletypes.TileType(tiletypes.get_tile_type(tid, client=self.client)).name
                except ValueError:
                    name = str(tiletypes.get_tile_type(tid, client=self.client))
                row.append(f"{tid}:{name}")
            rows.append(row)
        return rows

    def closeup(self, level_name: str, npc: Dict[str, Any]) -> Optional[str]:
        """Stand the player well left (or right) of the NPC, render, and crop
        an unannotated zoomed window around the NPC from the live frame."""
        lx, ly = npc["local_x"], npc["local_y"]
        px = lx - 9 if lx >= 12 else lx + 10
        self.client.warp_to_level(level_name, min(max(px, 1.0), 61.0),
                                  min(max(ly, 1.0), 61.0))
        self.pump(int(self.args.closeup_frames))
        self.game.visual_x, self.game.visual_y = self.client.x, self.client.y
        self.pump(10)
        # Re-read: scripts may have moved the NPC after it arrived.
        live = next((n for n in self.level_npcs(level_name)
                     if n["id"] == npc["id"]), npc)
        sx, sy = self.game.camera.world_to_screen(live["x"], live["y"])
        rect = pygame.Rect(int(sx) - CLOSEUP_LEFT * TILE_PX,
                           int(sy) - CLOSEUP_TOP * TILE_PX,
                           CLOSEUP_W * TILE_PX, CLOSEUP_H * TILE_PX)
        frame = self.game.screen
        clip = rect.clip(frame.get_rect())
        if clip.width <= 0 or clip.height <= 0:
            return None
        crop = pygame.Surface(rect.size)
        crop.fill((255, 0, 255))  # off-screen padding, never a real tile
        crop.blit(frame, (clip.x - rect.x, clip.y - rect.y), clip)
        crop = pygame.transform.scale(
            crop, (rect.width * CLOSEUP_SCALE, rect.height * CLOSEUP_SCALE))
        stem = level_name.replace(".nw", "")
        name = f"{stem}_npc{npc['id']}_closeup.png"
        pygame.image.save(crop, self.out / name)
        npc["closeup"] = name
        npc["ground"] = self.ground_types(live["local_x"], live["local_y"])
        npc["gani"] = live.get("gani", npc.get("gani", ""))
        return name

    def visit(self, level_name: str, x: float, y: float) -> None:
        stem = level_name.replace(".nw", "")
        entry: Dict[str, Any] = {"warp_target": [x, y]}
        self.client.warp_to_level(level_name, x, y)
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            self.pump()
            if self.client.get_current_level_from_position() == level_name:
                break
        else:
            entry["error"] = "warp timeout"
            self.index["levels"][level_name] = entry
            return
        # Snap the camera and give scripts/assets time to land.
        self.game.visual_x, self.game.visual_y = self.client.x, self.client.y
        self.pump(int(self.args.settle_frames))
        entry["player"] = [self.client.x, self.client.y]
        entry["npcs"] = self.level_npcs(level_name)
        entry["view"] = self.capture_view(stem)
        entry["board"] = self.capture_board(level_name, stem)
        self.index["levels"][level_name] = entry
        if self.args.npc_closeups:
            for npc in entry["npcs"]:
                # Nothing to look at: a script-only NPC (trigger, spawner).
                drawn = npc["visible"] and (npc["character"] or npc["image"])
                if drawn:
                    self.closeup(level_name, npc)

    # -- driver -----------------------------------------------------------
    def run(self) -> int:
        try:
            self.client = Client(self.args.host, self.args.port, version="6.037")
            outcome = login_client(self.client, self.args.account,
                                   self.args.password, timeout=10.0,
                                   settle=False)
            if not outcome.ok:
                print(f"login failed: {outcome.rejection}")
                return 1
            self.game = GameClient(self.client, password=self.args.password)
            self.game.visual_x, self.game.visual_y = self.client.x, self.client.y
            self.settle()
            self.pump(90)
            for spec in self.args.levels:
                name, _, pos = spec.partition("@")
                if pos:
                    px, py = (float(v) for v in pos.split(","))
                else:
                    px, py = 30.0, 30.0
                self.visit(name, px, py)
                done = self.index["levels"].get(name, {})
                status = "ok" if "view" in done else done.get("error", "?")
                print(f"  {name}: {status} ({len(done.get('npcs', []))} npcs)")
        finally:
            if self.client is not None:
                try:
                    self.client.disconnect()
                except Exception:
                    log_swallowed(logger, level=logging.DEBUG)
            (self.out / "index.json").write_text(
                json.dumps(self.index, indent=2, default=str, sort_keys=True))
            pygame.quit()
        return 0


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Visual level survey")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=14900)
    parser.add_argument("--account", default="surveybot")
    parser.add_argument("--password", default="surveybot")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--settle-frames", type=int, default=90,
                        help="frames to pump before capturing each level")
    parser.add_argument("--npc-closeups", action="store_true",
                        help="also crop a zoomed render around every NPC and "
                             "record the tile types under it")
    parser.add_argument("--closeup-frames", type=int, default=45,
                        help="frames to pump after each close-up warp")
    parser.add_argument("--levels", nargs="*", default=DEFAULT_LEVELS,
                        help="level names, optionally name.nw@x,y")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    return Survey(parse_args(argv)).run()


if __name__ == "__main__":
    raise SystemExit(main())
