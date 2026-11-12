"""The real pygame client with dummy SDL output and controllable keyboard input.

Constructing connects/logs in. Use a context manager (or close()) for cleanup.
SDL's display/event queue is process-global: drive one graphical client at a time.
"""
from __future__ import annotations

import logging
import os
import time
import traceback


class FakeKeys:
    """pygame key-array stand-in, including the 512-entry GS1 scan surface."""

    def __init__(self):
        self._held = set()

    def set(self, *keys):
        self._held = set(keys)

    def __getitem__(self, key):
        return key in self._held

    def __len__(self):
        return 512


class _WarningLog(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.lines = []

    def emit(self, record):
        self.lines.append(self.format(record))


class HeadlessGameClient:
    """Networked GameClient driven at 20 FPS by pump/hold/press."""

    frame_dt = 0.05

    def __init__(self, host, port, account, password, version="6.037"):
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"
        import pygame
        from pyreborn.client import Client
        from pyreborn.pygame_game import GameClient
        from .login import login_client
        from .local_world import local_world_for

        self.pygame = pygame
        self.name = account
        self.keys = FakeKeys()
        self.frame_exceptions = []
        self._warnings = _WarningLog()
        self._closed = False
        self.game = None
        self.client = Client(host, port, version=version)
        logging.getLogger().addHandler(self._warnings)
        try:
            world = local_world_for(host, port)
            if world is not None:
                world.register_bot(self)
            outcome = login_client(self.client, account, password, timeout=20)
            if not outcome.ok or not outcome.settled:
                raise RuntimeError(f"headless login/level failed: {outcome.rejection}")
            self.game = GameClient(self.client, password=password)
            self.game.start()
        except BaseException:
            self.close()
            raise

    @property
    def connected(self):
        return self.client.connected

    def frame(self):
        """Run a frame, recording exceptions in report() for QA inspection."""
        if self._closed:
            raise RuntimeError("headless client is closed")
        original = self.pygame.key.get_pressed
        self.pygame.key.get_pressed = lambda: self.keys
        try:
            self.game.step(self.frame_dt, strict=True)
        except Exception:
            self.frame_exceptions.append(traceback.format_exc())
        finally:
            self.pygame.key.get_pressed = original

    def pump(self, seconds):
        deadline = time.monotonic() + max(0, seconds)
        frames = 0
        while time.monotonic() < deadline:
            start = time.monotonic()
            self.frame()
            frames += 1
            delay = min(deadline - time.monotonic(),
                        self.frame_dt - (time.monotonic() - start))
            if delay > 0:
                time.sleep(delay)
        return frames

    def _key_codes(self, keys):
        if isinstance(keys, (str, int)):
            keys = [keys]
        return [self.pygame.key.key_code(k) if isinstance(k, str) else k for k in keys]

    def _set_keys(self, keys):
        previous = self.keys._held
        current = set(keys)
        self.keys.set(*current)
        for code in previous ^ current:
            event_type = self.pygame.KEYDOWN if code in current else self.pygame.KEYUP
            self.pygame.event.post(self.pygame.event.Event(
                event_type, key=code, unicode=chr(code) if 32 <= code < 127 else "", mod=0))

    def hold(self, keys, seconds):
        """Hold pygame key codes or names for the given wall-clock duration."""
        self._set_keys(self._key_codes(keys))
        try:
            return self.pump(seconds)
        finally:
            self._set_keys([])

    def press(self, key):
        self.hold(key, self.frame_dt)
        self.pump(self.frame_dt)

    def report(self):
        game = self.game
        counts = {"client": len(self.client.weapons), "gs1": 0, "gs2": 0}
        if game is not None:
            counts["gs1"] = sum(bool(p.get("is_weapon")) for p in game.gs1._progs.values())
            counts["gs2"] = len(game.gs2.vms["weapon"])
        return {"level": self.client._current_level_name,
                "pos": [self.client.x, self.client.y],
                "weapon_counts": counts,
                "frame_exceptions": list(self.frame_exceptions),
                "warning_log_lines": list(self._warnings.lines)}

    def close(self):
        if self._closed:
            return
        self._closed = True
        logging.getLogger().removeHandler(self._warnings)
        try:
            if self.game is not None:
                # The game's own shutdown: disconnect, RC/NC links, sound,
                # pygame. A harness never rewrites the player's prefs.
                self.game.shutdown(remember_window=False)
            else:
                self.client.disconnect()
        finally:
            self.pygame.quit()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
