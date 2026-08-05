"""Live, bounded gameplay-feel probe for the rendering client.

This module is deliberately inert on import.  Running it logs in to the named
public server, drives the normal pygame input path under SDL's dummy drivers,
and writes a frame-by-frame JSONL/PNG record for later inspection.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import time
import traceback
from pathlib import Path
from typing import Any, Iterable

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from reborn_protocol.coords import level_index, local_to_world, segment_at
from pyreborn import Client
from pyreborn.liftobjects import (
    BUSH_OBJECTS, BUSH_REPLACE, LIFT_OBJECTS, LIFT_PROBE, LIFT_REPLACE,
)
from pyreborn.prefs import Prefs
from pyreborn.pygame_game import GameClient
from pyreborn.game.gs2_gui.basic_controls import GuiWindowCtrl
from game_tester.login import login_client


FPS = 60
KEYS = {
    "up": pygame.K_UP, "left": pygame.K_LEFT,
    "down": pygame.K_DOWN, "right": pygame.K_RIGHT,
    "sword": pygame.K_s, "grab": pygame.K_a,
}
DIR_NUM = {"up": 0, "left": 1, "down": 2, "right": 3}
QUADS = ((0, 0), (0, 1), (1, 0), (1, 1))


class PressedKeys:
    """Sequence-shaped replacement for pygame's held-key snapshot."""

    def __init__(self) -> None:
        self.held: set[int] = set()
        # pygame's ScancodeWrapper reports 512 entries even though named key
        # constants (notably arrows) are large SDL keycodes.  Direct indexing
        # still accepts those constants; iteration is intentionally bounded.
        self.size = 512

    def __len__(self) -> int:
        return self.size

    def __getitem__(self, key: int) -> bool:
        return key in self.held

    def press(self, *keys: int) -> None:
        for key in keys:
            if key not in self.held:
                self.held.add(key)
                pygame.event.post(pygame.event.Event(
                    pygame.KEYDOWN, key=key, unicode=""))

    def release(self, *keys: int) -> None:
        for key in keys:
            if key in self.held:
                self.held.remove(key)
                pygame.event.post(pygame.event.Event(pygame.KEYUP, key=key))

    def clear(self) -> None:
        self.release(*tuple(self.held))


class Probe:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.out = Path(args.out_dir)
        self.frames_dir = self.out / "frames"
        self.out.mkdir(parents=True, exist_ok=True)
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.timeline = (self.out / "timeline.jsonl").open("w", encoding="utf-8")
        self.started = time.monotonic()
        self.deadline = self.started + args.seconds
        self.frame = 0
        self.phase = "LOGIN"
        self.summary: dict[str, Any] = {
            "host": args.host, "port": args.port, "complete": False,
            "phases": {}, "cuts": [], "lift_throw": None, "notes": [],
        }
        self.client: Client | None = None
        self.game: GameClient | None = None
        self.keys = PressedKeys()
        self.original_get_pressed = pygame.key.get_pressed
        self.sounds: list[dict[str, Any]] = []
        self.triggers: list[dict[str, Any]] = []
        self._last_capture = -9999

    def emit(self, kind: str, **data: Any) -> None:
        row = {"frame": self.frame, "t": round(time.monotonic() - self.started, 6),
               "phase": self.phase, "event": kind, **data}
        self.timeline.write(json.dumps(row, default=str, sort_keys=True) + "\n")
        self.timeline.flush()

    def capture(self, label: str) -> None:
        if not self.game:
            return
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)
        path = self.frames_dir / f"{self.frame:06d}_{safe}.png"
        pygame.image.save(pygame.display.get_surface() or self.game.screen, path)
        self.emit("screenshot", path=str(path.relative_to(self.out)))
        self._last_capture = self.frame

    def timed_out(self) -> bool:
        return time.monotonic() >= self.deadline

    def anim(self) -> tuple[str, int]:
        # AnimationState (pyreborn/gani.py) names its playback-position field
        # `frame`, not `current_frame` -- the old attribute name here always
        # missed and silently fell back to the `0` default, so gani_frame
        # never moved and every cadence metric read as an empty/zero series.
        anim = getattr(self.game, "player_anim", None)
        return (str(getattr(self.game, "current_anim_name", "") or
                    getattr(anim, "current_name", "")),
                int(getattr(anim, "frame", 0) or 0))

    def effect_rows(self) -> dict[str, int]:
        gs1 = getattr(self.game, "gs1", None)
        weapon = getattr(gs1, "_weapon_imgs", {}) or {}
        npc_rows = sum(len(n.get("imgs", {}) or {})
                       for n in (getattr(self.client, "npcs", {}) or {}).values())
        return {
            "weapon_showimgs": sum(len(v or {}) for v in weapon.values()),
            "npc_showimgs": npc_rows,
            "break_effects": len(getattr(self.game, "break_effects", []) or []),
        }

    def board4(self, x: int, y: int) -> list[int | None]:
        board = getattr(self.client, "tiles", None) or []
        return [board[level_index(x + dx, y + dy)]
                if 0 <= x + dx < 64 and 0 <= y + dy < 64 and len(board) >= 4096
                else None for dx, dy in QUADS]

    def items(self) -> list[dict[str, Any]]:
        name = self.client.get_current_level_from_position()
        reader = getattr(self.client, "items_in_level", None)
        rows = reader(name) if reader else getattr(self.client, "items", {})
        return [{"x": p[0], "y": p[1], "type": value}
                for p, value in (rows or {}).items()]

    def pump(self, *, capture: str | None = None, record: bool = True) -> None:
        if self.timed_out():
            raise TimeoutError("overall --seconds deadline reached")
        game = self.game
        self.frame += 1
        now = time.monotonic()
        game._frame_dt = min(1.0 / FPS, 0.1)
        game._handle_events()
        game._handle_input(now)
        self.client.update(timeout=0)
        game._load_new_npcs()
        game._process_pending_warp()
        game._process_self_shoots()
        game.gs1.process_coroutines(game._frame_dt)
        game.gs1.process_timeouts(game._frame_dt)
        game.gs2.process_coroutines(game._frame_dt)
        game.gs2.process_timeouts(game._frame_dt)
        game._check_scripted_link_warp()
        game.gs1.advance_input_frame()
        game._check_level_change()
        game._update_swimming_state()
        game._update_visual_position(game._frame_dt)
        game._update_animations(game._frame_dt)
        game._last_dt = game._frame_dt
        game._render()
        game.viewport.present()
        gani, gani_frame = self.anim()
        if record:
            self.emit("frame", x=self.client.x, y=self.client.y,
                      visual_x=getattr(game, "visual_x", None),
                      visual_y=getattr(game, "visual_y", None),
                      direction=self.client.player.direction,
                      gani=gani, gani_frame=gani_frame,
                      effects=self.effect_rows())
        if capture or self.frame - self._last_capture >= FPS:
            self.capture(capture or "periodic")
        game.clock.tick(FPS)

    def phase_call(self, name: str, fn) -> Any:
        self.phase = name
        self.emit("phase_start")
        try:
            value = fn()
            self.summary["phases"].setdefault(name.lower(), {})["ok"] = True
            self.emit("phase_end", ok=True)
            return value
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            self.summary["phases"].setdefault(name.lower(), {}).update(
                ok=False, error=detail)
            self.summary["notes"].append(f"{name}: {detail}")
            self.emit("phase_end", ok=False, error=detail,
                      traceback=traceback.format_exc())
            self.keys.clear()
            return None

    def settle(self) -> None:
        # These are the one-time prologue steps from GameClient.run(), kept
        # here so failures are attributed to SETTLE and still make a summary.
        self.game._load_npc_scripts()
        self.game._trigger_playerenters()
        self.game.npc_handler.update_npcs()
        self.game._gs1_level = self.client._current_level_name
        self.game._gs1_visual_level_epoch = self.client._plain_level_change_epoch
        limit = min(self.deadline, time.monotonic() + 25)
        while time.monotonic() < limit:
            self.pump(record=False)
            if (getattr(self.client, "_current_level_name", "") and
                    len(getattr(self.client, "tiles", []) or []) >= 4096 and
                    math.isfinite(float(self.client.x)) and
                    math.isfinite(float(self.client.y))):
                break
        else:
            self.summary["notes"].append("Server never sent a complete board; probe aborted.")
            raise RuntimeError("level board did not arrive")
        missing = sorted(getattr(self.game.sprite_mgr, "_missing_sheets", set()))
        assets = {
            "search_paths": [str(p) for p in self.game.asset_paths],
            "tileset": getattr(self.game.tileset_mgr, "current_tileset", None),
            "missing_sheets": missing,
            "missing_ganis": sorted(str(k) for k, v in self.game.gani_parser.cache.items()
                                    if v is None),
        }
        data = {"level": self.client._current_level_name,
                "x": self.client.x, "y": self.client.y, "assets": assets}
        self.summary["phases"]["settle"] = data
        self.emit("settled", **data)
        self.capture("settled")

    def sprite_report(self) -> dict[str, Any]:
        """Definitive per-frame answer to "is this a real LTTP Link sprite
        or a placeholder": replays the exact equip dict/resolve call
        `_render_player` (game/render_entities.py) uses for the LOCAL player,
        against the CURRENT gani/frame, and checks every image it names
        against the sprite manager -- not just the generic settle()-time
        `_missing_sheets` snapshot, which only proves SOME sheet failed
        somewhere, never which one the player is actually wearing."""
        game, client = self.game, self.client
        anim = game.player_anim
        player = client.player
        equip = {
            "body_image": player.body_image or "body.png",
            "head_image": player.head_image or "head0.png",
            "sword_image": player.sword_image or "sword1.png",
            "shield_image": player.shield_image or "shield1.png",
            "colors": player.colors,
        }
        equip.update(game._attr_equipment(player.gattribs))
        frame = anim.get_frame()
        layers = game._resolve_gani_layers(anim, frame, equip) if frame else []
        images_used = sorted({entry[1] for entry in layers if entry[0] == "sprite"})
        sprite_mgr = game.sprite_mgr
        checked = sorted(set(images_used) | {v for k, v in equip.items()
                                             if k.endswith("_image")})
        resolution = {}
        for img in checked:
            path = sprite_mgr.find_file(img)
            tier = None
            if path is not None:
                for root in game.asset_paths:
                    try:
                        Path(path).relative_to(root)
                        tier = str(root)
                        break
                    except ValueError:
                        continue
            resolution[img] = {
                "resolved_path": str(path) if path else None,
                "resolved_tier": tier,
                "loaded": sprite_mgr.has_sheet(img),
                "in_missing_sheets": img in getattr(sprite_mgr, "_missing_sheets", ()),
            }
        report = {
            "gani_name": anim.gani.name if anim.gani else None,
            "direction": anim.direction,
            "frame_index": anim.frame,
            "gani_defaults": dict(anim.gani.defaults) if anim.gani else {},
            "equip_images": {k: v for k, v in equip.items() if k.endswith("_image")},
            "images_drawn_this_frame": images_used,
            "resolution": resolution,
            "is_placeholder": bool(images_used) and not all(
                resolution[img]["loaded"] for img in images_used),
        }
        self.emit("sprite_report", **report)
        return report

    def close_topmost_window(self) -> dict[str, Any]:
        """Close the topmost visible GS2 GUI window through the real UI
        dispatch: a synthetic click on its titlebar close button
        (GS2GuiManager.click_point feeds the same handle_event() a physical
        click would). Falls back to a titlebar drag to a corner if the
        window refuses to close (canclose false, or a closequery handler
        intercepts it)."""
        result: dict[str, Any] = {"found": False}
        mgr = getattr(self.game.gs2, "gui", None)
        if mgr is None:
            self.emit("close_window_attempt", **result)
            return result
        window = next((w for w in reversed(mgr.roots)
                       if isinstance(w, GuiWindowCtrl) and w.visible), None)
        if window is None:
            self.emit("close_window_attempt", **result)
            return result
        result.update(found=True, title=getattr(window, "text", ""),
                      canclose=bool(window.canclose), canmove=bool(window.canmove))
        trig_before = len(self.triggers)
        close_rect = window._screen_button_rects()[0]
        result["close_rect"] = [close_rect.x, close_rect.y, close_rect.w, close_rect.h]
        result["click_consumed"] = bool(mgr.click_point(close_rect.center))
        self.pump(capture="after_close_click")
        result["closed_after_click"] = not window.visible
        if not result["closed_after_click"] and window.canmove:
            titlebar = window.titlebar_rect()
            start = titlebar.center
            target = (20, 20)
            mgr.handle_event(pygame.event.Event(
                pygame.MOUSEBUTTONDOWN, pos=start, button=1))
            steps = 6
            for i in range(1, steps + 1):
                pos = (start[0] + (target[0] - start[0]) * i // steps,
                       start[1] + (target[1] - start[1]) * i // steps)
                mgr.handle_event(pygame.event.Event(
                    pygame.MOUSEMOTION, pos=pos, rel=(0, 0), buttons=(1, 0, 0)))
            mgr.handle_event(pygame.event.Event(
                pygame.MOUSEBUTTONUP, pos=target, button=1))
            self.pump(capture="after_drag")
            result["dragged"] = True
            result["window_pos_after_drag"] = [window.x, window.y]
        result["triggers_fired"] = [t["action"] for t in self.triggers[trig_before:]]
        self.summary["window_close"] = result
        self.emit("close_window_attempt",
                  **{k: v for k, v in result.items() if k != "close_rect"})
        return result

    def hold(self, names: Iterable[str], frames: int) -> list[dict[str, Any]]:
        keys = [KEYS[n] for n in names]
        self.keys.press(*keys)
        rows = []
        try:
            for _ in range(frames):
                before = (float(self.client.x), float(self.client.y))
                self.pump()
                gani, gani_frame = self.anim()
                rows.append({"frame": self.frame, "x": self.client.x,
                             "y": self.client.y, "dx": self.client.x - before[0],
                             "dy": self.client.y - before[1], "gani": gani,
                             "gani_frame": gani_frame})
        finally:
            self.keys.release(*keys)
            self.pump()
        return rows

    def movement(self) -> None:
        all_rows = []
        for direction in ("up", "left", "down", "right"):
            rows = self.hold((direction,), 2 * FPS)
            for row in rows:
                row["direction"] = direction
            all_rows.extend(rows)
        magnitudes = [math.hypot(r["dx"], r["dy"]) for r in all_rows
                      if r["dx"] or r["dy"]]
        discontinuities = [r for r in all_rows
                           if math.hypot(r["dx"], r["dy"]) > 1.0]
        # "walk" as a substring, not a prefix: a server replaces the built-in
        # gani names with its own (replaceani/setspritesimage), and this
        # server's walk cycle is "zlttp_walk" -- a startswith("walk") check
        # matched zero of them and always reported an empty cadence.
        changes = [b["frame"] for a, b in zip(all_rows, all_rows[1:])
                   if b["gani_frame"] != a["gani_frame"] and
                   "walk" in b["gani"].lower()]
        cadence = [b - a for a, b in zip(changes, changes[1:])]
        metrics = {
            "moving_frames": len(magnitudes),
            "mean_delta": statistics.fmean(magnitudes) if magnitudes else 0,
            "delta_stddev": statistics.pstdev(magnitudes) if len(magnitudes) > 1 else 0,
            "discontinuities": discontinuities,
            "walk_frame_cadence": cadence,
            "cadence_stddev": statistics.pstdev(cadence) if len(cadence) > 1 else 0,
        }
        self.summary["phases"]["movement_feel"] = metrics
        self.emit("movement_metrics", **metrics)
        if metrics["delta_stddev"] > 0.08:
            self.summary["notes"].append("Movement per-frame delta is jittery (stddev above 0.08 tile).")
        if discontinuities:
            self.summary["notes"].append("Movement contained position discontinuities above one tile.")

    @staticmethod
    def scan_patterns(board: list[int], patterns) -> list[tuple[int, int, int]]:
        found = []
        if len(board) < 4096:
            return found
        for y in range(63):
            for x in range(63):
                values = tuple(board[level_index(x + dx, y + dy)] for dx, dy in QUADS)
                for row, pattern in enumerate(patterns):
                    if values == pattern:
                        found.append((row, x, y))
        return found

    def _walk_to(self, target_x: float, target_y: float, direction: int,
                 end: float) -> bool:
        """One candidate pose: walk toward it until arrival, stall, or `end`."""
        stalled = 0
        while time.monotonic() < end:
            ex, ey = target_x - self.client.x, target_y - self.client.y
            if abs(ex) < .3 and abs(ey) < .3:
                self.client.player.direction = direction
                self.game.player_anim.set_direction(direction)
                self.emit("target_reached", target=[target_x, target_y], direction=direction)
                return True
            # Steer along whichever axis is currently farthest off, not
            # always X first. A fixed X-then-Y priority stalls whenever X
            # sits just outside its own .25 tolerance while Y is still tiles
            # away: every step nudges X back and forth across that tolerance
            # line and Y never gets its turn, so the walk oscillates in place
            # forever (observed live approaching a bush 12 tiles north with
            # X only fractionally off -- 400 frames, zero net Y progress).
            if abs(ex) >= abs(ey):
                name = "right" if ex > .25 else "left" if ex < -.25 else (
                    "down" if ey > .25 else "up")
            else:
                name = "down" if ey > .25 else "up" if ey < -.25 else (
                    "right" if ex > .25 else "left")
            before = (self.client.x, self.client.y)
            self.hold((name,), min(8, max(2, int((abs(ex) + abs(ey)) * 2))))
            stalled = stalled + 1 if before == (self.client.x, self.client.y) else 0
            if stalled >= 3:
                return False
        return False

    def approach(self, origin_x: int, origin_y: int, timeout: float = 9) -> bool:
        """Walk toward one of four exact action-probe poses, then face it.

        Tries candidate poses closest-first, but does not commit to only the
        single closest one: LTTP overworld terrain routinely blocks one or
        two sides of an object (water, cliffs, a fence), and a naive client
        with no real pathfinding gives up on a perfectly cuttable bush just
        because its nearest-by-Euclidean-distance side happens to be the
        blocked one. Each candidate gets its own stall detector and a slice
        of the overall timeout; the first one that's reachable wins.
        """
        candidates = []
        for direction, (px, py) in enumerate(LIFT_PROBE):
            for dx, dy in QUADS:
                candidates.append((origin_x + dx - px, origin_y + dy - py, direction))
        candidates.sort(key=lambda p: abs(p[0] - self.client.x) + abs(p[1] - self.client.y))
        overall_end = min(self.deadline, time.monotonic() + timeout)
        tried = 0
        # No early cap on how many of the 16 poses get tried: the OUTER loop
        # bound is still `overall_end`, so worst-case wall time is unchanged
        # from a 4-candidate cap -- this just spends that same budget on
        # smaller slices across more poses, which matters on terrain where
        # 3+ sides of an object are blocked (observed live: two full runs
        # against LTTP overworld bushes where every one of the first 4
        # closest poses was water/fence-blocked, and none of the other 12
        # ever got a turn).
        for target_x, target_y, direction in candidates:
            if time.monotonic() >= overall_end:
                break
            tried += 1
            per_candidate_end = min(overall_end, time.monotonic() + max(1.2, timeout / 6))
            if self._walk_to(target_x, target_y, direction, per_candidate_end):
                return True
        self.emit("target_unreachable", origin=[origin_x, origin_y], candidates_tried=tried)
        return False

    def cut_one(self, bush: tuple[int, int, int], number: int,
                grid: tuple[int, int]) -> None:
        row, x, y = bush
        # `board4`/`approach` deliberately use two different frames: the board
        # scan is level-LOCAL (0..63, what client.tiles holds), but approach()
        # steers by client.x/y, which is gmap WORLD coords -- local + segment
        # * 64 (CLAUDE.md "GMAP Coordinate System"). Comparing a local bush
        # coordinate straight against a world player coordinate is exactly the
        # bug this project's own coords module exists to prevent: on this
        # server (a gmap, level "*-h4.nw") it made the probe steer toward a
        # target dozens of tiles away in the wrong frame and walk in place
        # against a wall instead of ever reaching the bush.
        world_x, world_y = local_to_world(x, y, *grid)
        if not self.approach(world_x, world_y):
            raise RuntimeError(f"bush {number} was unreachable")
        for _ in range(10):
            self.pump(capture=f"cut{number}_pre")
        before_items = self.items()
        sound_start = len(self.sounds)
        trigger_start = len(self.triggers)
        key_frame = self.frame + 1
        # LTTP's own slash-anchor formula (CheckTiles, movement-weapon
        # bytecode instrs #6765-6810): px = int(x + (dir==3 ? 3.5 : -1.5)),
        # py = int(y + (dir==0 ? 0 : dir==2 ? 4 : 2)), evaluated 0.12s after
        # the keypress -- with freezeplayer honored the position is this
        # one, frozen at the swing.
        direction = int(self.client.player.direction) & 3
        px = int(self.client.x + (3.5 if direction == 3 else -1.5))
        py = int(self.client.y + (0 if direction == 0 else
                                  4 if direction == 2 else 2))
        self.keys.press(KEYS["sword"])
        sword_start = sword_end = swap_frame = None
        samples = []
        try:
            for offset in range(41):
                self.pump(capture=f"cut{number}_{offset:+03d}")
                gani, gani_frame = self.anim()
                tiles = self.board4(x, y)
                samples.append({"frame": self.frame, "gani": gani,
                                "gani_frame": gani_frame, "tiles": tiles,
                                "items": self.items(), "effects": self.effect_rows(),
                                "sounds": self.sounds[sound_start:],
                                "triggers": self.triggers[trigger_start:]})
                # "sword" as a substring, same rationale as the walk-cadence
                # check above: a server-replaced attack gani need not be
                # named exactly "sword...".
                if "sword" in gani.lower() and sword_start is None:
                    sword_start = self.frame
                if sword_start is not None and "sword" not in gani.lower() and sword_end is None:
                    sword_end = self.frame
                if tiles == list(BUSH_REPLACE[row]) and swap_frame is None:
                    swap_frame = self.frame
        finally:
            self.keys.release(KEYS["sword"])
        world_bush = local_to_world(x, y, *grid)
        result = {
            "bush": {"row": row, "x": x, "y": y}, "keypress_frame": key_frame,
            "direction": direction,
            "predicted_target_world": [px, py],
            "predicted_offset_from_bush": [px - world_bush[0],
                                           py - world_bush[1]],
            "frames_to_sword": None if sword_start is None else sword_start - key_frame,
            "sword_duration_frames": None if sword_start is None else
                (sword_end or self.frame) - sword_start,
            "frames_to_tile_swap": None if swap_frame is None else swap_frame - key_frame,
            "item_dropped": self.items() != before_items,
            "sounds": [s["name"] for s in self.sounds[sound_start:]],
            "triggers": [t["action"] for t in self.triggers[trigger_start:]],
            "samples": samples,
        }
        self.summary["cuts"].append(result)
        self.emit("cut_metrics", **result)
        if sword_start is None:
            self.summary["notes"].append(f"Bush {number}: no sword gani appeared.")
        if swap_frame is None or swap_frame - key_frame > 30:
            self.summary["notes"].append(f"Bush {number}: tile swap was absent or slower than 30 frames.")
        if not result["sounds"]:
            self.summary["notes"].append(f"Bush {number}: no sound was triggered.")
        if not any("objslashed" in t for t in result["triggers"]):
            self.summary["notes"].append(
                f"Bush {number}: no objslashed- trigger observed (server hit "
                f"detection may not have registered this swing).")

    def swing_sword_in_place(self) -> None:
        """Swing without a target in range: pure animation/latency evidence
        (gani + sound + trigger, if any), no tile-swap expected."""
        self.keys.press(KEYS["sword"])
        try:
            for offset in range(20):
                self.pump(capture=f"swing_notarget_{offset:+03d}")
        finally:
            self.keys.release(KEYS["sword"])
        self.pump(capture="swing_notarget_end")

    def engine_reads(self) -> dict[str, Any]:
        """Script-visible freeze state, read exactly the way server bytecode
        reads it: LTTP's DoMovement gates on `clientr.freezetime == -1` and
        DoSword on `player.freezetime == -1` (see the movement weapon's
        disassembly). Both must track the live freezeplayer counter."""
        try:
            from reborn_protocol.gs2 import to_num
            rt2 = self.game.gs2
            scope = rt2.flag_scope_object("clientr")
            return {
                "clientr_freezetime": to_num(scope.get("freezetime")),
                "player_freezetime": to_num(
                    rt2.player_object.get("freezetime")),
            }
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}

    def flag_audit(self) -> dict[str, Any]:
        """What the client-flag store actually holds for the names the LTTP
        movement weapon gates on, plus the live engine reads. The 2026-08-05
        walk-through-freezeplayer bug was a literal `freezetime` flag (the
        server's own modifyclientr write) shadowing the engine counter."""
        shared = getattr(self.game.gs1, "_shared", {}) or {}
        client_flags = shared.get("client", {}) or {}
        watched = ("freezetime", "sworddisabled", "ganidisabled", "strafe",
                   "qon")
        data = {
            "watched_flags": {k: client_flags.get(k) for k in watched
                              if k in client_flags},
            "engine": self.engine_reads(),
        }
        self.summary["phases"]["flag_audit"] = data
        self.emit("flag_audit", **data)
        return data

    def sword_freeze(self, hold: str = "right", frames: int = 110) -> None:
        """Hold a direction, tap S mid-walk, and measure the freeze.

        Reference expectation: DoSword runs setAni("zlttp_sword") +
        freezeplayer(0.6), so the position must hold still ~0.6s (36 frames
        at 60fps) while the swing plays, then walking resumes; the swing
        gani itself is 5 steps of WAIT 2 (0.75s) ending in SETBACKTO
        ce_idle. Records per-frame x/y/gani plus the script-visible
        freezetime reads."""
        rows: list[dict[str, Any]] = []
        self.keys.press(KEYS[hold])
        try:
            for i in range(frames):
                if i == 20:
                    self.keys.press(KEYS["sword"])
                if i == 26:
                    self.keys.release(KEYS["sword"])
                before = (float(self.client.x), float(self.client.y))
                self.pump()
                gani, gani_frame = self.anim()
                rows.append({"frame": self.frame, "x": self.client.x,
                             "y": self.client.y,
                             "moved": (float(self.client.x),
                                       float(self.client.y)) != before,
                             "gani": gani, "gani_frame": gani_frame,
                             **self.engine_reads()})
        finally:
            self.keys.release(KEYS[hold], KEYS["sword"])
            self.pump()
        sword_rows = [r for r in rows if "sword" in r["gani"].lower()]
        frozen = [r for r in rows if r.get("player_freezetime", -1) >= 0]
        frozen_still = [r for r in frozen if not r["moved"]]
        after = [r for r in rows
                 if frozen and r["frame"] > frozen[-1]["frame"]]
        metrics = {
            "hold": hold,
            "sword_frames": len(sword_rows),
            "frozen_frames": len(frozen),
            "frozen_frames_still": len(frozen_still),
            "moved_while_frozen": len(frozen) - len(frozen_still),
            "resumed_after_freeze": any(r["moved"] for r in after),
            "ganis_seen": sorted({r["gani"] for r in rows}),
            "rows": rows,
        }
        self.summary["phases"]["sword_freeze"] = {
            k: v for k, v in metrics.items() if k != "rows"}
        self.emit("sword_freeze_metrics",
                  **{k: v for k, v in metrics.items() if k != "rows"})

    def setback_watch(self, seconds: float = 6.0) -> dict[str, Any]:
        """Swing standing still and watch the swing END: the renderer must
        request the SETBACKTO gani (ce_idle on LTTP) and switch to it when
        the server serves the file, instead of holding the last sword frame
        forever."""
        self.swing_sword_in_place()
        end = min(self.deadline, time.monotonic() + seconds)
        while time.monotonic() < end:
            self.pump()
            gani, _ = self.anim()
            if "sword" not in gani.lower():
                break
        gani, frame = self.anim()
        anim = self.game.player_anim
        parsed = {name: (entry is not None)
                  for name, entry in self.game.gani_parser.cache.items()
                  if "idle" in str(name) or "sword" in str(name)}
        data = {"final_gani": gani,
                "renderer_gani": getattr(getattr(anim, "gani", None),
                                         "name", None),
                "requested": getattr(anim, "requested_name", None),
                "ganis_parsed": parsed}
        self.summary["phases"]["setback_watch"] = data
        self.emit("setback_watch", **data)
        return data

    def bush_hunt_and_cut(self) -> None:
        board = list(getattr(self.client, "tiles", []) or [])
        # The board just read is the segment the player is standing in RIGHT
        # NOW; fix the local<->world offset to that segment before it can
        # change under a later warp/segment-crossing.
        grid = segment_at(self.client.x, self.client.y)
        def world_dist(b: tuple[int, int, int]) -> float:
            wx, wy = local_to_world(b[1], b[2], *grid)
            return abs(wx - self.client.x) + abs(wy - self.client.y)
        bushes = self.scan_patterns(board, BUSH_OBJECTS)
        lifts = self.scan_patterns(board, LIFT_OBJECTS)
        bushes.sort(key=world_dist)
        lifts.sort(key=world_dist)
        counts = {"bushes": len(bushes), "liftables": len(lifts)}
        self.summary["phases"]["bush_hunt"] = counts
        self.emit("board_scan", **counts)
        cut_ok = 0
        for number, bush in enumerate(bushes[:6], 1):
            try:
                self.cut_one(bush, number, grid)
                cut_ok += 1
            except Exception as exc:
                self.summary["cuts"].append({"bush": bush, "error": str(exc)})
                self.emit("cut_error", bush=bush, error=str(exc))
            # LTTP overworld bushes often sit against terrain our greedy
            # approach() can't route around (see the class docstring above
            # `_walk_to`/`approach`) -- two confirmed cuts is enough evidence
            # of the swing/hit/tile-swap chain without burning the whole
            # session's connect-time budget on unreachable ones.
            if cut_ok >= 2:
                break
        if cut_ok == 0 and bushes:
            # Every scanned bush was out of reach of a greedy walk (this
            # server's overworld hedges bushes with water/fences on most
            # sides, per the notes above). A miss on the OBJECT is not a
            # miss on the SWING: capture the swing gani in isolation so
            # there is still visual evidence the sword animation plays and
            # completes, even with nothing in range to cut.
            self.swing_sword_in_place()
        available_lifts = [v for v in lifts if v not in bushes[:3]]
        if available_lifts:
            row, x, y = available_lifts[0]
            world_x, world_y = local_to_world(x, y, *grid)
            if self.approach(world_x, world_y):
                start = len(self.sounds)
                before = self.board4(x, y)
                direction = self.client.player.direction
                direction_name = ("up", "left", "down", "right")[direction]
                self.keys.press(KEYS["grab"], KEYS[direction_name])
                for i in range(35):
                    self.pump(capture=f"lift_{i:02d}")
                self.keys.release(KEYS["grab"], KEYS[direction_name])
                carried = self.client.player.is_carrying()
                self.keys.press(KEYS["sword"])
                for i in range(35):
                    self.pump(capture=f"throw_{i:02d}")
                self.keys.release(KEYS["sword"])
                result = {"object": {"row": row, "x": x, "y": y},
                          "tiles_before": before, "tiles_after": self.board4(x, y),
                          "replacement_seen": self.board4(x, y) == list(LIFT_REPLACE[row]),
                          "carried_before_throw": carried,
                          "sounds": [s["name"] for s in self.sounds[start:]]}
                self.summary["lift_throw"] = result
                self.emit("lift_throw_metrics", **result)
        else:
            self.summary["notes"].append("No additional liftable was available for grab/lift/throw.")

    def install_trigger_hook(self) -> None:
        """Log every outbound PLI_TRIGGERACTION (Client.triggeraction).

        This server's scripted hit detection is client-side (its sword weapon
        tracks cuttable objects itself and calls `triggeraction`), so the
        `objslashed-<id>`/`objlifted-<id>` string on the wire is the only
        first-party evidence that OUR key press was recognised as a hit on
        the object, as distinct from the server's own board response.
        """
        client = self.client
        original = getattr(client, "triggeraction", None)
        if original is None:
            return
        def wrapped(action, *args, _original=original, **kwargs):
            rec = {"frame": self.frame, "action": str(action)}
            self.triggers.append(rec)
            self.emit("triggeraction", **rec)
            return _original(action, *args, **kwargs)
        client.triggeraction = wrapped

    def install_sound_hook(self) -> None:
        manager = self.game.sound_mgr
        for method_name in ("play", "play_from_gani", "play_positional"):
            original = getattr(manager, method_name, None)
            if original is None:
                continue
            def wrapped(name, *args, _original=original, _method=method_name, **kwargs):
                rec = {"frame": self.frame, "name": str(name), "method": _method}
                self.sounds.append(rec)
                self.emit("sound", **rec)
                return _original(name, *args, **kwargs)
            setattr(manager, method_name, wrapped)

    def run(self) -> int:
        login_failed = False
        try:
            self.client = Client(self.args.host, self.args.port, version="6.037")
            outcome = login_client(self.client, self.args.account, self.args.password,
                                   timeout=min(10.0, self.args.seconds), settle=False)
            if not outcome.ok:
                login_failed = True
                reason = outcome.rejection or "connect/login failed"
                self.summary["notes"].append(f"Login failed: {reason}")
                self.summary["login"] = {"ok": False, "reason": reason}
                self.emit("login_failed", reason=reason)
                return 1
            self.summary["login"] = {"ok": True, "version": outcome.version}
            self.game = GameClient(self.client, password=self.args.password)
            pygame.key.get_pressed = lambda: self.keys
            self.install_sound_hook()
            self.install_trigger_hook()
            self.game.visual_x, self.game.visual_y = self.client.x, self.client.y
            self.phase_call("SETTLE", self.settle)
            if len(getattr(self.client, "tiles", []) or []) >= 4096:
                # settle() returns the instant the board arrives, which is
                # BEFORE this server's own scripted intro (the freezetime/
                # ganidisabled clientr toggle + warp into the overworld +
                # its "FPS Demo" debug window all land a few frames later --
                # observed live at frame ~4 for the warp/clientr and by
                # frame 61 for the window). Snapshotting sprite/window state
                # immediately after settle() catches the pre-intro throwaway
                # "idle"/default-head appearance, not what the player
                # actually looks like in the overworld.
                for _ in range(90):
                    self.pump(record=False)
                self.summary["sprite_report_idle"] = self.phase_call(
                    "SPRITE_CHECK", self.sprite_report)
                self.phase_call("CLOSE_DEBUG_WINDOW", self.close_topmost_window)
                self.capture("post_settle_clear")
                self.phase_call("MOVEMENT_FEEL", self.movement)
                self.summary["sprite_report_walk"] = self.phase_call(
                    "SPRITE_CHECK_WALK", self.sprite_report)
                self.phase_call("BUSH_HUNT_CUT", self.bush_hunt_and_cut)
            self.summary["complete"] = not self.timed_out()
        except TimeoutError as exc:
            self.summary["notes"].append(str(exc))
            self.emit("deadline", error=str(exc))
        except Exception as exc:
            self.summary["notes"].append(f"Probe failure: {type(exc).__name__}: {exc}")
            self.emit("probe_error", error=str(exc), traceback=traceback.format_exc())
        finally:
            pygame.key.get_pressed = self.original_get_pressed
            self.keys.clear()
            if self.client is not None:
                try:
                    self.client.disconnect()
                except Exception:
                    pass
            if self.game is not None:
                try:
                    self.game.sound_mgr.stop_all()
                    self.game.sound_mgr.stop_music()
                except Exception:
                    pass
            self.summary["runtime_seconds"] = round(time.monotonic() - self.started, 3)
            self.summary["frames"] = self.frame
            (self.out / "summary.json").write_text(
                json.dumps(self.summary, indent=2, default=str, sort_keys=True) + "\n",
                encoding="utf-8")
            self.timeline.close()
            pygame.quit()
        return 1 if login_failed else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    prefs = Prefs.load()
    parser = argparse.ArgumentParser(description="Probe live movement and object-cut feel")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--account", default=prefs.username)
    parser.add_argument("--password", default=prefs.password)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--seconds", type=float, default=120.0)
    args = parser.parse_args(argv)
    if not args.account or not args.password:
        parser.error("account/password are required (arguments or saved preferences)")
    if args.seconds <= 0:
        parser.error("--seconds must be positive")
    return args


def main(argv: list[str] | None = None) -> int:
    return Probe(parse_args(argv)).run()


if __name__ == "__main__":
    raise SystemExit(main())
