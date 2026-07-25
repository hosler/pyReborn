# CLAUDE.md - PyReborn Developer Guide

## Project Overview

**PyReborn** is a Python client library for Reborn game servers. Zero external dependencies for core functionality, optional pygame for the graphical client.

## Directory Structure

```
pyreborn/
├── __init__.py           # Exports: Client, Player, ListServerClient, RCClient, NCClient
├── client.py             # Main Client class - game state, packet handling
├── protocol.py           # Socket connection + encryption
├── packets.py            # Packet parsing/building - CRITICAL for debugging
├── player.py             # Player dataclass
├── listserver.py         # Listserver authentication
├── rc_client.py          # Remote Control client
├── nc_client.py          # NPC Control client
├── npc_handler.py        # NPC state tracking
├── gani.py               # GANI animation parser
├── gs1_client.py         # GS1 script transport/state
├── gs2_client.py         # GS2 bytecode transport
├── tiletypes.py          # Tile collision data
├── sprites.py            # Sprite/tileset managers
├── sounds.py             # Sound manager
├── inventory_ui.py       # Inventory UI overlay
├── prefs.py              # ~/.config/pyreborn preferences (0600)
├── debug_packets.py      # Packet trace/debug helper
├── example_pygame.py     # Entry point
├── pygame_game.py        # GameClient - composes game/ mixins
├── pygame_screens.py     # Login/ServerSelect/browser screens
├── assets/
│   └── tile_corrections.json
└── game/                 # GameClient mixins (rendering, input, world logic)
    ├── actions.py        # Player actions (grab/sword/attack/etc.)
    ├── assets.py         # Asset loading
    ├── camera.py         # Camera/viewport tracking
    ├── collision.py      # Tile/entity collision
    ├── constants.py      # Screen/tile size constants
    ├── hud.py            # HUD rendering
    ├── input.py          # Keyboard/input handling
    ├── minimap.py        # GMAP minimap
    ├── render.py         # Core render loop
    ├── render_effects.py # Particle/effect rendering
    ├── render_entities.py # Player/NPC/baddy rendering
    ├── render_objects.py # Item/object rendering
    ├── render_world.py   # Tile/level rendering
    ├── setup.py          # GameClient init/setup
    ├── theme.py          # UI palette + emblem/panel helpers (reskin here)
    ├── tile_editor.py    # In-client tile editor
    ├── ui.py             # Menus/dialogs
    └── viewport.py       # Viewport sizing/scaling

game_tester/              # Automated QA framework
├── __init__.py           # Exports all modules
├── game_bot.py           # Headless bot wrapper for Client
├── bug_detector.py       # Anomaly detection utilities
├── multi_bot.py          # Multi-bot coordination (PvP, visibility)
├── test_scenarios.py     # Scripted test cases
├── explorer.py           # Autonomous AI exploration
├── reporter.py           # JSON/HTML report generation
├── screenshots.py        # Level capture (PNG/ASCII)
├── packet_coverage.py    # RC/NC packet coverage harness
├── version_probe.py      # Live login probe across client versions
├── gmap_tests.py         # GMAP coordinate-crossing suite
├── gs2_tests.py          # GS2 bytecode transport suite
├── tier1_tests.py        # Board modify / large files
├── tier2_tests.py        # Bomb/arrow/horse/flagdel relay
├── tier3_tests.py        # Freeze/say2/triggeraction/serverwarp
├── tier5_tests.py        # GS2 bytecode transport integrity
├── render_smoke.py       # Render smoke test
├── exercise.py           # Ad-hoc exercise script
├── exercise_nc.py        # NC exercise script
├── exercise_rc.py        # RC exercise script
└── __main__.py           # CLI entry point
```

## Quick Start

```bash
# Run pygame client
python -m pyreborn.example_pygame <username> <password> localhost 14900

# Run automated QA tests
python -m game_tester --host localhost --port 14900
```

**Controls:** Arrows=Move, A=Grab, S/Space=Sword, D=Weapon, Q=Inventory, Enter=Chat, F1=Debug, F2=Warp

---

## Automated QA Testing (game_tester)

The `game_tester` module provides headless automated testing for the game client and server.

### Running Tests

```bash
# Run all tests (single-bot + multi-bot)
python -m game_tester

# Run with specific server
python -m game_tester --host localhost --port 14900

# Multi-bot tests with 3 bots
python -m game_tester --bots 3

# Single-bot tests only
python -m game_tester --single

# Explorer AI mode (autonomous wandering for N seconds)
python -m game_tester --explore 60

# Save reports (JSON + HTML)
python -m game_tester --report my_report

# Behavioural fingerprints against live servers (see below)
python -m game_tester --behaviour
python -m game_tester --behaviour --behaviour-server "Login"
python -m game_tester --behaviour --behaviour-server "Login" --rebaseline
```

### Behavioural fingerprints (`--behaviour`)

**Run this after ANY change to the GS2 VM or client host.** The rest of the
suite cannot detect a *branch flip* in real server content: if a semantic
change makes a server's own scripts take the wrong path, there is no error,
no warning and no failing test — the client just silently builds nothing.
That is exactly how a `gs2_compare(<object>, null)` change broke the public
Login server on 2026-07-24 with all 754 tests passing.

`--behaviour` logs into each known server with a real `GameClient`, pumps a
fixed window of frames, and asserts ~33 invariants against
`game_tester/behaviour_baselines.json`, in three families:

- **structure** — GUI root / named-control / control-class counts, which
  weapons load and which must *never* load, event and host-call volumes, no
  new missing builtins, no new warning templates;
- **content** — `tree_nodes`, `list_rows`, `text_controls` and the
  `required_filled_controls` pin. **Structure alone is not enough**: on
  2026-07-25 the Login server list came up completely EMPTY and every
  structural count stayed inside its band, so the harness reported 25/25 over
  a broken UI. A control that exists is not a control that has anything in it;
- **geometry** — `within_parent`, `nonzero_area`, `window_layout`. These catch
  a layout that collapses without changing any count: an unimplemented
  `GuiFrameSetCtrl` left Global Chat's cells at their constructor defaults
  with *identical* roots/named/controls/tree_nodes/list_rows to the healthy
  capture.

A server's most interesting UI often only exists once someone opens it, so a
target may list `open_ui` entries (`"<weapon vm>:<function>"`) that are
invoked after the observation window — Login opens `-Serverlist_Chat.openChat`.
**Only ever list openers that build UI locally**; a function that sends is a
live action on someone else's server.

Bands are deliberately loose enough to survive normal content churn and tight
enough to catch a branch flip. When a real content or engine change moves a
metric legitimately, re-baseline **that server** with `--rebaseline` (curated
pins are preserved, and pin kinds added since the baseline was recorded get
seeded; `--rebaseline-pins` resets them) and say why in the commit.

`tests/fixtures/fingerprint_login_{good,broken,emptylist,layout}.json` are real
captures of the healthy server and of three different outages, replayed offline
by `tests/unit/test_behaviour_fingerprint.py` — so "does this still catch THE
outage?" stays answerable with no network, even after a re-baseline. The
`emptylist` and `layout` fixtures also assert the *converse*: that the
structural invariants alone would NOT have caught them.

### Test Categories

| Category | Tests | What It Checks |
|----------|-------|----------------|
| **Connection** | `connection_stability` | 5s stable connection, no disconnects |
| **Level Data** | `level_data` | Tiles loaded, valid tile values |
| **Movement** | `movement_all_directions`, `collision_detection`, `walk_to_target` | 4-direction movement, wall collision, pathfinding |
| **Combat** | `sword_attack`, `multi_pvp_combat` | Sword in 4 directions, PvP damage application |
| **Chat** | `chat_roundtrip`, `multi_chat` | Own message echo, message relay between players |
| **Visibility** | `multi_visibility` | Players can see each other |
| **Items/NPCs** | `item_detection`, `npc_visibility` | Ground items detected, NPCs received |

### Using GameBot Programmatically

```python
from game_tester import GameBot, BugDetector

bot = GameBot("testbot", "localhost", 14900)
bot.connect()

# High-level actions
bot.walk_to(35, 35, timeout=10.0)
bot.sword_attack(direction=2)  # 0=up, 1=left, 2=down, 3=right
bot.say("Hello world")
bot.pickup_item(x, y)
bot.warp_to("othermap.nw", 30, 30)

# Check for bugs
result = BugDetector.check_position_sync(bot.client, expected_x, expected_y)
if not result.passed:
    print(f"Bug: {result.message}")

# Get detected issues
for issue in bot.get_issues():
    print(f"[{issue.severity}] {issue.description}")

bot.disconnect()
```

### Multi-Bot Testing

```python
from game_tester import MultiBotTest

test = MultiBotTest(num_bots=2, host="localhost", port=14900)
test.connect_all()

# Test player visibility
result = test.run_visibility_test()
print(f"Visibility: {'PASS' if result.passed else 'FAIL'}")

# Test PvP combat
result = test.run_pvp_test()
print(f"PvP: {'PASS' if result.passed else 'FAIL'}")

# Test chat between players
result = test.run_chat_test()
print(f"Chat: {'PASS' if result.passed else 'FAIL'}")

test.disconnect_all()
```

### Explorer AI Mode

```python
from game_tester import GameBot, ExplorerBot

bot = GameBot("explorer", "localhost", 14900)
bot.connect()

explorer = ExplorerBot(bot)
result = explorer.explore(duration=60.0, verbose=True)

print(f"Tiles visited: {result.tiles_visited}/4096")
print(f"Actions: {result.actions_performed}")
print(f"Anomalies: {result.anomalies_detected}")

explorer.print_coverage_map()  # ASCII coverage visualization
bot.disconnect()
```

### Screenshots

```python
from game_tester import GameBot, ScreenshotCapture

bot = GameBot("screenshot", "localhost", 14900)
bot.connect()

capture = ScreenshotCapture()

# PNG screenshot (requires PIL)
png_data = capture.capture_level(bot.client, scale=8)
with open("level.png", "wb") as f:
    f.write(png_data)

# ASCII fallback (no dependencies)
ascii_map = capture.get_ascii_level(bot.client)
print(ascii_map)

bot.disconnect()
```

### Known Detectable Bugs

The framework can detect:
- **Position desync** - Client/server position mismatch
- **Stuck detection** - Bot unable to move for extended period
- **Out of bounds** - Player outside level boundaries
- **Position discontinuity** - Sudden teleportation/jumps
- **PvP damage not applied** - Attacks don't reduce hearts
- **Chat not relayed** - Messages not reaching other players
- **Level data missing** - Tiles not loaded
- **Invalid tile values** - Corrupted tile data

---

## Critical: Player Property IDs

When parsing player props, each prop has a specific byte size. Getting this wrong causes parser misalignment.

```python
# Single byte props (value = byte - 32)
PLPROP_NICKNAME      = 0   # STRING: 1 byte len + chars
PLPROP_MAXPOWER      = 1   # 1 byte
PLPROP_CURPOWER      = 2   # 1 byte
PLPROP_RUPEESCOUNT   = 3   # 3 bytes (gInt)
PLPROP_ARROWSCOUNT   = 4   # 1 byte
PLPROP_BOMBSCOUNT    = 5   # 1 byte
PLPROP_GLOVEPOWER    = 6   # 1 byte
PLPROP_BOMBPOWER     = 7   # 1 byte
PLPROP_SWORDPOWER    = 8   # 1 byte, or 1 + string if > 4
PLPROP_SHIELDPOWER   = 9   # 1 byte, or 1 + string if > 3
PLPROP_GANI          = 10  # STRING: 1 byte len + chars
PLPROP_HEADIMAGE     = 11  # STRING: 1 byte len + chars
PLPROP_BODYIMAGE     = 13  # STRING: 1 byte len + chars
PLPROP_X             = 15  # 1 byte (tiles * 2, half-tile precision)
PLPROP_Y             = 16  # 1 byte (tiles * 2, half-tile precision)
PLPROP_SPRITE        = 17  # 1 byte (direction in lower 2 bits)
PLPROP_STATUS        = 18  # 1 byte
PLPROP_CURLEVEL      = 20  # STRING: 1 byte len + chars
PLPROP_ACCOUNTNAME   = 34  # STRING: 1 byte len + chars

# CRITICAL: These are NOT position props!
PLPROP_OSTYPE        = 75  # STRING: 1 byte len + chars (NOT X2!)
PLPROP_TEXTCODEPAGE  = 76  # 3 bytes gInt (NOT Y2!)

# High-precision position (2 bytes each)
PLPROP_X2            = 78  # 2 bytes (gShort, pixels/16 = tiles)
PLPROP_Y2            = 79  # 2 bytes (gShort, pixels/16 = tiles)
PLPROP_Z2            = 80  # 2 bytes (gShort)

# GATTRIBs (46-74) are all strings
PLPROP_GATTRIB1-30   = 36-74  # STRING: 1 byte len + chars
```

### X2/Y2 Decoding (High Precision Position)

```python
def decode_position(b1, b2):
    """Decode 2-byte high-precision position."""
    b1 = b1 - 32
    b2 = b2 - 32
    value = (b1 << 7) | b2
    pixels = value >> 1
    if value & 0x0001:  # Sign bit
        pixels = -pixels
    return pixels / 16.0  # Convert to tiles
```

## Critical: Packet Parsing Rules

### Parser Alignment
**Every prop must consume the correct number of bytes.** If a prop consumes wrong bytes, all subsequent props are misaligned and you'll read garbage.

Common symptoms of misalignment:
- Y position jumps randomly (e.g., smooth movement then sudden jump to 39.5)
- Properties appearing with wrong values
- Parser reading string data as prop IDs

### Other Player Movement

Other player positions come via **PLO_OTHERPLPROPS (packet 8)**, NOT PLO_TOALL (packet 13).

```python
# In client.py _handle_packet:
elif packet_id == PacketID.PLO_OTHERPLPROPS:
    props = parse_other_player(data)
    # props contains: id, x, y, ani, sprite, level, etc.
```

### parse_other_player Must Handle All Props

The `parse_other_player` function in packets.py must have handlers for ALL prop types that could appear, especially:
- Props 78, 79, 80 (X2, Y2, Z2) - 2 bytes each
- Props 75, 76 (OSTYPE, CODEPAGE) - string and 3-byte gInt
- All GATTRIB props (46-74) - strings

If a prop falls through to the default `else` clause, it only skips 1 byte, causing misalignment for multi-byte props.

## Sprite Positioning Rules

**All sprites use top-left positioning with NO offsets.**

```python
# Correct - sprites render at entity position
self.screen.blit(sprite, (x, y))

# WRONG - don't center sprites
self.screen.blit(sprite, (x - w//2, y - h//2))  # NO!
```

## GMAP Coordinate System

```python
# Local coords: 0-63 within a level segment
# World coords: local + (grid_position * 64)

# Convert local to world (for GMAP)
world_x = local_x + grid_x * 64
world_y = local_y + grid_y * 64

# Find grid position
grid_x = math.floor(world_x / 64)
grid_y = math.floor(world_y / 64)

# Get local from world
local_x = world_x % 64
local_y = world_y % 64
```

## Key Packet IDs

```python
# Server -> Client
PLO_LEVELBOARD = 0       # Level metadata
PLO_LEVELLINK = 1        # Door/warp definitions
PLO_NPCPROPS = 3         # NPC properties
PLO_PLAYERLEFT = 4       # Player left level
PLO_LEVELNAME = 6        # Level name
PLO_OTHERPLPROPS = 8     # Other player properties/movement
PLO_PLAYERPROPS = 9      # Our player properties
PLO_TOALL = 13           # Chat messages
PLO_BOARDPACKET = 101    # Tile data

# Client -> Server
PLI_PLAYERPROPS = 2      # Send movement/props (constants.py PacketID.PLAYERPROPS)
PLI_TOALL = 24           # Send chat
PLI_LEVELWARP = 29       # Warp request
```

## Debugging Tips

### Run Automated Tests First

Before manual debugging, run the game_tester to identify issues:

```bash
python -m game_tester --report debug_report
# Check debug_report.html for detailed results
```

### Add Prop Debug Output

```python
# In parse_other_player, add after reading prop_id:
print(f"prop={prop_id} pos={pos} remaining={len(data)-pos}")
```

### Check for Parser Misalignment

If you see unexpected prop IDs (like prop 0 appearing multiple times in one packet), the parser is misaligned. Check that all preceding props consumed the correct bytes.

### Use BugDetector for Specific Checks

```python
from game_tester import BugDetector

# Check position sync
result = BugDetector.check_position_sync(client, expected_x, expected_y)

# Check if stuck
result = BugDetector.check_stuck_detection(position_history)

# Check level loaded
result = BugDetector.check_level_loaded(client)

# Check tiles valid
result = BugDetector.check_tiles_valid(client)
```

## Test Credentials

- **Server:** localhost:14900
- **Account:** Use your server account credentials
- **Version:** 6.037 (or 2.22 for older protocol)

## Common Pitfalls

1. **Props 75/76 are NOT position** - They're OSTYPE (string) and TEXTCODEPAGE (3 bytes)
2. **Missing prop handlers** - Causes 1-byte skip instead of correct size
3. **Centering sprites** - Reborn uses top-left positioning
4. **PLO_TOALL for movement** - Use PLO_OTHERPLPROPS instead
5. **Boundary check failures** - Must still advance pos or break to avoid infinite loops
6. **Not running QA tests** - Always run `python -m game_tester` after changes
