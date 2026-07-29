"""Regression smoke test: scripted-movement touch + link-warp probes against
CLASSIC Bomber Arena (bomber.eevul.net:14916, protocol v2.22).

Login -> reach lobby -> sit 60s (log any level/warp/exception) -> walk around
the lobby incl. into walls/NPCs for 60s -> park the account there.

Run with PYREBORN_DEBUG=1 to see [touch]/[trigger] breadcrumbs.
"""
import os
import sys
import time
import traceback

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, "/home/hosler/Projects/opengraal2/pyReborn")

import pygame
from pyreborn.client import Client
from pyreborn.pygame_game import GameClient
from pygame.locals import K_UP, K_DOWN, K_LEFT, K_RIGHT

ACCOUNT = sys.argv[1] if len(sys.argv) > 1 else "hosler1"
PASSWORD = os.environ.get("BOMBER_PW") or sys.argv[2]
HOST, PORT = "bomber.eevul.net", 14916

t0 = time.time()
def log(msg):
    print(f"[{ACCOUNT} {time.time()-t0:7.2f}] {msg}", flush=True)


class FakeKeys:
    """Stand-in for pygame.key.get_pressed(), controlled by the bot below.
    _feed_gs1_input does `for i in range(len(keys))` to scan the whole
    keycode range for keydown2's VK translation, so this needs a real
    __len__ matching pygame's key array size (512)."""
    def __init__(self):
        self._held = set()
    def set(self, *keys):
        self._held = set(keys)
    def __getitem__(self, key):
        return key in self._held
    def __len__(self):
        return 512


fake_keys = FakeKeys()
pygame.key.get_pressed = lambda: fake_keys

client = Client(HOST, PORT)  # default version "2.22"
orig_handle = client._handle_packet
def spy(pid, data):
    if pid in (6, 14):  # PLO_LEVELNAME, PLO_LEVELWARP-ish signature packets
        log(f"PLO {pid}: {data[:60]!r}")
    return orig_handle(pid, data)
client._handle_packet = spy

log(f"connecting to {HOST}:{PORT} (v{client.version}) as {ACCOUNT}...")
assert client.connect(), "connect failed"
assert client.login(ACCOUNT, PASSWORD, timeout=20), f"login failed: {client.disconnect_reason!r}"
log("logged in")

for _ in range(60):
    client.update(timeout=0.05)
    if client._current_level_name and client.tiles:
        break
log(f"initial level={client._current_level_name!r} pos=({client.x},{client.y})")

game = GameClient(client)
dt = 0.05
errors = []
warps = []
last_level = [client._current_level_name]
last_pos = [(client.x, client.y)]
last_default_movement = [None]


def frame(current_time):
    """One iteration of pygame_game.GameClient.run()'s loop body, minus the
    real pygame event pump / display flip (headless).

    _frame_dt must be set BEFORE _handle_input runs (matches run()'s real
    ordering) — normal movement accumulates distance via
    self._move_accum += self.walk_speed * self._frame_dt in input.py, so a
    stale/zero _frame_dt silently drops all movement (harness-only bug,
    found live: player never moved a single frame across 60s of held
    arrow keys on the first run of this script)."""
    game._frame_dt = dt
    game._handle_events()
    game._handle_input(current_time)
    client.update(timeout=0)
    game._load_new_npcs()
    game._process_pending_warp()
    game._process_self_shoots()
    game.gs1.process_coroutines(dt)
    game.gs1.process_timeouts(dt)
    game.gs2.process_coroutines(dt)
    game.gs2.process_timeouts(dt)
    game._check_scripted_link_warp()
    game.gs1.advance_input_frame()
    game._check_level_change()
    game._update_swimming_state()
    game._update_visual_position(dt)
    game._update_animations(dt)
    game._last_dt = dt
    game._render()


def pump(seconds, label=""):
    end = time.time() + seconds
    n = 0
    while time.time() < end:
        n += 1
        try:
            frame(time.time())
        except Exception:
            tb = traceback.format_exc()
            errors.append(tb)
            log(f"EXCEPTION during frame ({label}): {tb[-500:]}")
        dm = game.gs1.default_movement
        if dm != last_default_movement[0]:
            log(f"default_movement -> {dm}")
            last_default_movement[0] = dm
        if client._current_level_name != last_level[0]:
            msg = (f"LEVEL CHANGE ({label}): {last_level[0]!r} -> "
                   f"{client._current_level_name!r} pos=({client.x:.2f},{client.y:.2f})")
            warps.append(msg)
            log(msg)
            last_level[0] = client._current_level_name
        pos = (round(client.x, 2), round(client.y, 2))
        dx = abs(pos[0] - last_pos[0][0])
        dy = abs(pos[1] - last_pos[0][1])
        if dx > 3 or dy > 3:
            msg = f"POSITION JUMP ({label}): {last_pos[0]} -> {pos}"
            warps.append(msg)
            log(msg)
        last_pos[0] = pos
        time.sleep(0.01)
    return n


# --- reach lobby ---
deadline = time.time() + 60
fake_keys.set()
while client._current_level_name != "bomblobby.nw" and time.time() < deadline:
    pump(1, "wait-for-lobby")
log(f"in level {client._current_level_name!r} at ({client.x:.2f},{client.y:.2f}) "
    f"default_movement={game.gs1.default_movement}")

if not client.connected:
    log("FAIL: disconnected before reaching lobby")
    sys.exit(1)

# --- phase 1: sit 60s, log everything ---
log("=== PHASE 1: sit 60s, watch for spurious warps/exceptions ===")
pump(60, "sit")
log(f"phase1 end: level={client._current_level_name!r} pos=({client.x:.2f},{client.y:.2f}) "
    f"connected={client.connected}")

# --- phase 2: walk around lobby incl. into walls/NPCs for 60s ---
log("=== PHASE 2: walk around lobby (walls + NPCs) 60s ===")


def walk_toward(gx, gy, seconds, label):
    end = time.time() + seconds
    while time.time() < end and client.connected:
        dx = gx - client.x
        dy = gy - client.y
        keys = []
        if abs(dy) > 0.3:
            keys.append(K_DOWN if dy > 0 else K_UP)
        if abs(dx) > 0.3:
            keys.append(K_RIGHT if dx > 0 else K_LEFT)
        fake_keys.set(*keys)
        pump(0.2, label)


# Known lobby landmark: queue-counter NPC around (25,18) (bomber_arena_bot.py
# JOIN_NPC_X/Y). Walk to it and push up against it (this is the pre-existing
# default-movement touch path, not the new probe -- exercised here mainly to
# see whether reaching/joining the queue is what flips default_movement, per
# the memory note that classic weapons get granted via login triggeractions).
log("walking toward queue-counter NPC (~25,18)...")
walk_toward(25.0, 19.0, 15, "approach-counter")
log(f"near counter at ({client.x:.2f},{client.y:.2f}); pushing up 8s...")
fake_keys.set(K_UP)
pump(8, "push-counter")
fake_keys.set()
pump(1, "pause-after-counter")
log(f"post-counter-push: pos=({client.x:.2f},{client.y:.2f}) "
    f"default_movement={game.gs1.default_movement}")

# Cycle cardinal directions, holding each long enough to hit something
# (walls, other NPCs) for the remainder of phase 2's budget.
directions = [
    (K_UP, "up"), (K_DOWN, "down"), (K_LEFT, "left"), (K_RIGHT, "right"),
]
phase2_deadline = time.time() + 60
i = 0
while time.time() < phase2_deadline and client.connected:
    key, name = directions[i % len(directions)]
    fake_keys.set(key)
    pump(2.5, f"walk-{name}")
    fake_keys.set()
    pump(0.3, f"pause-after-{name}")
    i += 1

fake_keys.set()
log(f"phase2 end: level={client._current_level_name!r} pos=({client.x:.2f},{client.y:.2f}) "
    f"connected={client.connected}")

log("=== SUMMARY ===")
log(f"warps/jumps observed: {len(warps)}")
for w in warps:
    log(f"  - {w}")
log(f"exceptions observed: {len(errors)}")
log(f"final level={client._current_level_name!r} pos=({client.x:.2f},{client.y:.2f}) "
    f"connected={client.connected} default_movement={game.gs1.default_movement}")

if not client.connected:
    log("FAIL: disconnected during test")
    sys.exit(1)
if errors:
    log(f"FAIL: {len(errors)} exception(s) during test")
    sys.exit(1)
if warps:
    log(f"FAIL: {len(warps)} unexpected warp/jump event(s)")
    sys.exit(1)

log("PASS: stable lobby session, no unexpected warps, no exceptions")

# --- park the account: keep the connection alive, idle ---
log("parking in lobby, idling indefinitely (heartbeat only)...")
fake_keys.set()
while client.connected:
    pump(5, "park")
    log(f"parked heartbeat: level={client._current_level_name!r} "
        f"pos=({client.x:.2f},{client.y:.2f})")
