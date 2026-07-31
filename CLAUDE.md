# CLAUDE.md - PyReborn Developer Guide

## Project Overview

**PyReborn** is a Python client library for Reborn game servers. The core has no
external dependencies. The graphical client needs pygame.

## Directory Structure

```
pyreborn/
├── __init__.py           # Exports: Client, Player, ListServerClient, RCClient, NCClient
├── client.py             # Client facade - session, state components, dispatch
├── client_actions.py     # Outbound action mixin
├── client_appearance.py  # Chat and player-appearance mixin
├── client_combat.py      # Sword and arrow simulation mixin
├── client_files.py       # File-transfer and board-modification mixin
├── client_gmap.py        # Multi-level map loading and adjacency mixin
├── client_movement.py    # Movement and position synchronization mixin
├── client_warp.py        # Warp and level-link transition mixin
├── client_state.py       # Client's state components (level/gmap/entities/...)
├── handlers/             # Packet handlers, one module per domain
│   ├── registry.py       # @handles(<PLO id>) table. Grep it to find a handler
│   ├── level.py          # level/board/warp        session.py  # handshake/auth
│   ├── entities.py       # players/NPCs            combat.py   # combat relay
│   ├── chat.py           # chat/RC                 files.py    # downloads
│   └── scripts.py        # GS1/GS2 transport
├── protocol.py           # Socket connection + encryption
├── packets.py            # Packet parsing/building - CRITICAL for debugging
├── player.py             # Player dataclass
├── listserver.py         # Listserver authentication
├── rc_client.py          # Remote Control client
├── nc_client.py          # NPC Control client
├── npc_handler.py        # NPC state tracking
├── gani.py               # GANI animation parser
├── gs1_client/           # GS1 script transport/state package
│   ├── __init__.py       # Compatibility exports (see packets.py for the idiom)
│   ├── registry.py       # Handler tables + @_gs1_builtin/@_gs1_command
│   ├── board.py          # Board access helpers
│   ├── objects.py        # Object references and flag scopes
│   ├── host.py           # GS1ClientHost composition + core dispatch
│   ├── host_builtins.py  # get/set_builtin handlers
│   ├── host_commands_pre.py    # _GS1_PRE_COMMANDS stage
│   ├── host_commands_layer.py  # _GS1_LAYER_COMMANDS stage
│   ├── host_commands_npc.py    # _GS1_NPC_COMMANDS + _NPC_TAIL stages
│   ├── host_commands_main.py   # _GS1_MAIN_COMMANDS stage
│   ├── host_functions.py       # call_function + message_code
│   └── runtime.py        # ClientGS1
├── gs2_client/           # GS2 bytecode transport/state package
│   ├── __init__.py       # Compatibility exports. Re-exports BY VALUE, so
│   │                     #   monkeypatch the owning submodule, not this
│   ├── registry.py       # Builtin tables + @_gs2_builtin/@_gs2_object
│   ├── helpers.py        # CSV/image/admin-guild helpers
│   ├── objects.py        # Level/NPC/layer object wrappers
│   ├── objects_player.py # Engine/name/player object wrappers
│   ├── host.py           # GS2ClientHost composition + call_builtin/get_object
│   ├── host_objects.py   # @_gs2_object factories
│   ├── host_*.py         # One mixin per builtin table
│   └── runtime.py        # ClientGS2
├── tiletypes.py          # Tile collision data
├── sprites.py            # Sprite/tileset managers
├── sounds.py             # Sound manager
├── inventory_ui.py       # Inventory UI overlay
├── prefs.py              # ~/.config/pyreborn preferences (0600)
├── example_pygame.py     # Entry point
├── pygame_game.py        # GameClient - composes game/ mixins
├── pygame_screens.py     # Login/ServerSelect/browser screens
├── assets/
│   └── tile_corrections.json
└── game/                 # GameClient mixins (rendering, input, world logic)
    ├── actions.py        # Player actions (grab/sword/attack/etc.)
    ├── assets.py         # Asset loading
    ├── callbacks/        # on_* wiring pulled out of setup.py
    │   ├── client_callbacks.py  # Client (network) callbacks
    │   └── gs1_callbacks.py     # GS1 engine callbacks
    ├── camera.py         # Camera/viewport tracking
    ├── collision.py      # Tile/entity collision
    ├── constants.py      # Screen/tile size constants
    ├── frame_context.py  # FrameContext - per-frame state shared across passes
    ├── hud.py            # HUD rendering
    ├── input.py          # Keyboard/input handling
    ├── minimap.py        # GMAP minimap
    ├── render.py         # Core render loop
    ├── render_collect.py # Entity collection, sorting, and interpolation
    ├── render_effects.py # Particle/effect rendering
    ├── render_entities.py # Player/NPC/baddy rendering
    ├── render_gani.py    # Animated-entity rendering
    ├── render_layers.py  # Scripted-layer rendering
    ├── render_objects.py # Item/object rendering
    ├── render_shared.py  # Shared entity-rendering definitions
    ├── render_text.py    # Entity text and speech-bubble rendering
    ├── render_world.py   # Tile/level rendering
    ├── setup.py          # GameClient init/setup
    ├── theme.py          # UI palette + emblem/panel helpers (reskin here)
    ├── tile_editor.py    # In-client tile editor
    ├── ui.py             # Menus/dialogs
    └── viewport.py       # Viewport sizing/scaling

game_tester/              # Automated QA framework
├── __init__.py           # Exports all modules
├── login.py              # login_client/login_session - the ONE connect+login
│                         #   path, with guaranteed cleanup. Use it. Do not
│                         #   hand-roll connect/login (that leaked sockets).
├── game_bot.py           # Headless bot wrapper for Client (GameBot.ACTIONS)
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

The `game_tester` module runs headless automated tests against the game client
and server.

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

**Run this after ANY change to the GS2 VM or client host.** The other suites
cannot detect a *branch flip* in real server content. If a semantic change makes
a server's own scripts take the wrong path, you get no error, no warning and no
failing test. The client silently builds nothing. That is how a
`gs2_compare(<object>, null)` change broke the public Login server on 2026-07-24
while all 754 tests passed.

`--behaviour` logs into each known server with a real `GameClient`. It pumps a
fixed window of frames. It then asserts ~34 invariants against
`game_tester/behaviour_baselines.json`, in four families:

- **structure** — GUI root, named-control and control-class counts. Also which
  weapons load and which must *never* load, event and host-call volumes, no new
  missing builtins, and no new warning templates.
- **content** — `tree_nodes`, `list_rows`, `text_controls` and the
  `required_filled_controls` pin. **Structure alone is not enough.** On
  2026-07-25 the Login server list came up completely EMPTY. Every structural
  count stayed inside its band, so the harness reported 25/25 over a broken UI.
  A control that exists is not a control that has anything in it.

  Do NOT pin a control whose population depends on which row the listserver
  returns first. That is why `serverlist_description0`, `serverlist_eventnews`
  and `serverlist_tablestab` left Login and Login DEV on 2026-07-26. They belong
  to the Account Info pane. `Rescripted_Serverlist`'s `showLoginInfo()` builds
  that pane only when the first listed server is a `"P "` or `"3 "` entry. A
  `"U "` server first yields a blank-named root folder, because
  `serverlistcats[4]` is unset. Its auto-select instead runs
  `showServerListEntry(serverlistentries[0])`. The unset `id` reads 0.0, so
  `node.id >= 0` HOLDS, and the faithful engine builds the MAP pane for that
  first row. That pane is `Serverlist_Map`, with unfetchable
  `login_servermap_*` art and therefore a 0×0 size, plus per-tick
  `updateServerMapIcons` host calls. Login was re-baselined for this on
  2026-07-26.

  Under the pre-lattice `to_num` compare, the `this.selectedserver == entry`
  guard at weapon-Rescripted_Serverlist.txt:559 was spuriously TRUE
  (`<unset> == "<row string>"`). It returned early and built neither pane. The
  earlier claim that `node.id >= 0` fails was a mis-attribution of that masking.
  Either way, pane choice depends on payload order, so the pruned pins stay
  pruned. `serverlist_serverlist` is the real list-is-populated signal. Keep
  that one.
- **geometry** — `within_parent`, `nonzero_area`, `window_layout`. These catch a
  layout that collapses without changing any count. An unimplemented
  `GuiFrameSetCtrl` left Global Chat's cells at their constructor defaults, with
  *identical* roots, named controls, controls, tree_nodes and list_rows to the
  healthy capture.
- **assets** — `assets_refused`, a ceiling rather than a band. It counts the
  files the server declined to send. A refusal is a fact about the SERVER's
  content, not about our engine. The login serverlist asks for a per-server icon
  that most servers never published. Counting those as engine warnings pinned
  `no_new_warnings` red on four servers, for something no client change could
  fix. The harness counts them separately instead, and only a *jump* fails.
  Asking for art nobody has is a client bug even though each refusal is not.
  Fewer refusals always passes.

A server's most interesting UI often exists only after someone opens it. A
target may therefore list `open_ui` entries (`"<weapon vm>:<function>"`) that
the harness invokes after the observation window. Login opens
`-Serverlist_Chat.openChat`. **Only ever list openers that build UI locally.** A
function that sends is a live action on someone else's server.

Bands are loose enough to survive normal content churn and tight enough to catch
a branch flip. When a real content or engine change moves a metric legitimately,
re-baseline **that server** with `--rebaseline` and say why in the commit. That
flag keeps the curated pins, and it seeds pin kinds added since the baseline was
recorded. `--rebaseline-pins` resets them.

`tests/fixtures/fingerprint_login_{good,broken,emptylist,layout}.json` are real
captures of the healthy server and of three different outages.
`tests/unit/test_behaviour_fingerprint.py` replays them offline. "Does this
still catch THE outage?" therefore stays answerable with no network, even after
a re-baseline. The `emptylist` and `layout` fixtures also assert the *converse*.
The structural invariants alone would NOT have caught either one.

### GS1 client-engine conformance (`--gs1-client`)

`python -m game_tester --gs1-client` pins the CLIENT-side GS1 engine against the
decompiled reference client. It runs `pyreborn/gs1_client.py` inside the real
Client, GameClient and NPCHandler stack, with the SDL dummy driver.

Each of the 73 rows in `game_tester/gs1_client_conformance.py` is an executable
transcription of one FourPlay citation. The row carries that citation as a
`Preagonal/FourPlay/quattroplay/src/...` file:line reference. The rows cover
footprint blocking and dontblock, touchtestd touch, timeout=0 cancel,
setani-vs-setcharani, say/say2/message/sign ordering, tiles[]/updateboard, hurt
half-hearts, putbomb/putexplosion wire+local pairs, hideimg(s),
hidelocal/showlocal and selectedweapon. A semantic change that breaks a row
therefore contradicts a cited reference line, not a guess.

The suite starts its own throwaway pygserver and never targets `--host`. If that
server fails to start, the suite skips wholesale. A full run takes about 12
seconds.

Two delivery gotchas are baked in, and the module docstring records both.
Weapon-channel scripts must be ONE line, because pygserver's weapon-text builder
skips the newline→0xa7 GS1 wire mangling. The `weapon_multiline_truncation`
divergence row pins that. Every fixture weapon also ships an empty `.gs2bc`
cache. Without it, a gs2test binary in the checkout compiles GS1-style bodies as
GS2, and the cases silently run in the GS2 VM instead of the engine under test.

Rows marked `[PINNED DIVERGENCE]` assert the current known-divergent shipping
state: stacked-sign collapse and weapon truncation. They go red when someone
fixes the server side.

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

The framework detects:
- **Position desync** - Client and server positions do not match
- **Stuck detection** - The bot cannot move for an extended period
- **Out of bounds** - The player is outside the level boundaries
- **Position discontinuity** - A sudden teleport or jump
- **PvP damage not applied** - Attacks do not reduce hearts
- **Chat not relayed** - Messages do not reach other players
- **Level data missing** - Tiles did not load
- **Invalid tile values** - Corrupted tile data

---

## Critical: Player Property IDs

Each player prop has a specific byte size. A wrong size misaligns the parser.

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
PLPROP_SWORDPOWER    = 8   # 1 byte, or 1 + string if raw >= 30  (see below)
PLPROP_SHIELDPOWER   = 9   # 1 byte, or 1 + string if raw >= 10  (see below)
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

# GATTRIBs are strings -- but the block is NOT contiguous. Ids 42-45 and
# 50-53 sit inside the apparent range and are NOT gattribs (ATTACHNPC,
# GMAPLEVELX, GMAPLEVELY, Z, ...). A naive `GATTRIB1 <= id <= GATTRIB30`
# range test reads those as length-prefixed strings and corrupts the rest
# of the packet -- that was a live pygserver bug, fixed 2026-07-25. Derive
# the real ids from reborn_protocol.props.PLAYER_PROPS, never from a range.
PLPROP_GATTRIB1-30            # STRING: 1 byte len + chars
```

### Sword/shield power: the bias forms

Oracle: `GServer-v2/server/src/utilities/PropertySerializers.cpp`
(`PropertySwordPower::serialize` / `::deserialize`, and the shield pair).

```
sword:  power 0             -> single byte 0
        power 1..4, no image -> bare byte = power
        otherwise            -> byte = power + 30, then a length-prefixed image
shield: same, with bias 10 and bare range 1..3
```

When you receive a value, `raw < bias` is a bare power. `raw >= bias` means
`power = raw - bias`, followed by the image. **A branch on `power > 4` instead
reads an image string that is not on the wire, and desyncs every following
property in the packet.** Bare powers 1..4 get a synthesized default name
(`sword{N}.png`, or `.gif` on classic servers).

Do not hand-roll any of this. `reborn_protocol.props` owns the descriptor tables
(`PLAYER_PROPS`, `NPC_PROPS`, `BADDY_PROPS`) plus `decode_value`, `encode_value`
and `parse_prop_stream`. It replaced six independent parsers across this client
and pygserver, which is what let them drift apart.

Two more traps from the same fix:
- `PLPROP_COLORS` is 5 bytes on classic and 8 on v6 new-world. The server picks
  the width from a server-wide mode, NOT from the client version, so you cannot
  derive it from the handshake.
- Property streams arrive in ASCENDING id order. A strict parser STOPS at the
  first descending id instead of raising an error, so an out-of-order writer
  makes entities silently arrive half-populated.

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
**Every prop must consume the correct number of bytes.** If one prop consumes
the wrong count, every later prop is misaligned and you read garbage.

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

The `parse_other_player` function in packets.py needs a handler for EVERY prop
type that can appear. Watch these:
- Props 78, 79, 80 (X2, Y2, Z2) - 2 bytes each
- Props 75, 76 (OSTYPE, CODEPAGE) - string and 3-byte gInt
- All GATTRIB props (46-74) - strings

A prop that falls through to the default `else` clause skips only 1 byte. That
misaligns every multi-byte prop after it.

## Sprite Positioning Rules

**All sprites use top-left positioning with NO offsets.**

```python
# Correct - sprites render at entity position
self.screen.blit(sprite, (x, y))

# WRONG - do not center sprites
self.screen.blit(sprite, (x - w//2, y - h//2))  # NO!
```

## GMAP Coordinate System

**Do not re-derive this math inline.** `reborn_protocol.coords` owns it for both
this client and pygserver. Independently-written copies caused the repeated
coordinate-frame bugs: props frame, door frame, edge-warp frame, gani anchor,
and cross-seam collision.

```python
from reborn_protocol.coords import (
    segment_index, segment_at, world_to_local, local_to_world,
    segment_origin, level_index, in_level_bounds,
    camera_origin, world_to_screen, screen_to_world, visible_tile_range,
)
```

Local coords are 0-63 within a segment. The world coordinate is
`local + grid * 64`.

**Segment selection must use `math.floor(world / 64)`.** `int(world / 64)`
truncates toward zero and disagrees for negative coordinates. World `-1.5` is
segment -1 and local 62 under floor, but segment 0 and local 63 under `int()`.
That mismatch made the debug tile-editor's hover readout name a different tile
than the one it edited. It was fixed on 2026-07-25.

Known limitation, deliberately not "fixed": for a negative magnitude below one
ULP of 64 (for example `-1e-16`), `world % 64` returns exactly `64.0` instead of
a value in `[0, 64)`. Real coordinates never reach that case, because they are
all multiples of 1/16 tile.

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

Before you debug by hand, run game_tester to find the issue:

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

Unexpected prop IDs mean the parser is misaligned. Prop 0 more than once in a
single packet is the usual sign. Check that every preceding prop consumed the
correct byte count.

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

## Which server the tier suites need

The QA suites do NOT all run against the same server world. A suite run against
the wrong world gives misleading results instead of an error.

```bash
cd pygserver && python run_server.py                      # default world
python -m game_tester                 # 16/16   base bot QA
python -m game_tester --tier1         # 2/2     board modify + large file
python -m game_tester --tier2         # 4/4     bomb/arrow/horse/flag relay
python -m game_tester --tier3         # 4/4     freeze/say2/triggeraction
python -m game_tester --tier5         # 5/5     GS2 bytecode transport
python -m game_tester --gs2           # 6/6

cd pygserver && python run_server.py ../funtimes-pygserver  # gmap world
python -m game_tester --gmap          # needs `gmaps = chicken.gmap`
```

`--gmap` refuses to run when the server has no gmap loaded, because it used to
pass *vacuously*. With `gmaps =` unset, every warp onto a segment fails silently
and both bots stay on the start level. "Can they see each other" and "does chat
arrive" are then trivially true. Three of six tests passed while they tested
nothing, which hid two real cross-segment failures. If `gmap_world_loaded`
fails, you started the wrong world.

`--tier1` writes its own large-file fixture into whichever local server world
directory it finds, and it generates that fixture from a fixed seed. The suite
used to depend on an untracked 45000-byte blob that existed on exactly one
machine.

## Where assets live

**Game art is not committed to this repo.** `pyreborn/assets/` is gitignored, so
a fresh clone has almost nothing in it. The client must work with that directory
empty. `pyreborn/asset_paths.py` owns the three tiers. Do not hand-roll paths or
lowercase names anywhere else.

| Tier | Location | What |
|---|---|---|
| download cache | `~/.cache/pyreborn/servers/{host}_{port}/` (`$PYREBORN_CACHE_DIR`) | everything the server sends, + `index.json` of modtime/size/SHA-256 metadata |
| user content | any directory you point at (below), else `~/.local/share/pyreborn/content/` | base art a server assumes you already have |
| bundled | `pyreborn/assets/` | last resort, nearly empty in a clone |

The client searches the tiers in that order, so a server's own art wins over
your stock copy of the same filename.

The middle tier exists because the original client shipped base art **built
in**. Servers therefore publish only their own custom content. No server has to
serve `pics1.png`, the player ganis, `sprites.png`, `body.png`, `head0.png` or
the `COMMON_SOUNDS`. If those files are missing, the client renders an invisible
player and reports no error.

### Pointing at an existing client installation

The quickest way to fill that tier is to point pyReborn at an installed game
client. The client saves the path to prefs, so you give it once:

```bash
python -m pyreborn.example_pygame --content-dir /path/to/client-install
python -m pyreborn.example_pygame --content-dir /path/a --content-dir /path/b
python -m pyreborn.example_pygame --clear-content-dirs
```

`$PYREBORN_CONTENT_DIR` takes an `os.pathsep`-separated list for one-off runs.

`asset_paths.looks_like_client_install` detects an install from its layout,
never from its name, so any directory laid out like a client works. The install
root and its `levels/` subdirectory both resolve to the same pair of roots. Each
manager then probes its `subdirs` and finds `levels/ganis`, `levels/heads`,
`sounds/` and the rest. A real install supplies the entire tier-2 set: all 12
base player ganis, `sprites.png`, `pics1.png`, the body/head/sword/shield
defaults and about 110 sounds.

Every resolved root logs one INFO line with what it found
(`Content root /path: ganis=114, images=19, sounds=110`). A wrong directory
reports zeros. That is the whole point, because every other asset failure in
this client is silent.

The download cache is **advisory**. Any IO error degrades it to memory-only. The
client revalidates each entry with `PLI_UPDATEFILE` and `PLO_FILEUPTODATE`
instead of trusting the mtime. It also checks every disk read against the
recorded byte length and SHA-256 digest before it serves or revalidates that
entry. `PLO_UPDATEPACKAGEISUPDATED` (187) drops a stale entry mid-session.

Three traps this replaced, all of which cost a real outage:
- A `cache/` directory once sat *inside the checkout*, and nothing in the client
  ever wrote to it. Someone populated it out of band. `rm -rf cache/` therefore
  took the tileset with it, and a fresh clone never had one at all.
- `normalize_asset_name()` keys every asset name by basename and lowercase.
  Servers descend from a Windows client and send mixed casing. On Linux,
  `Body.png` and `body.png` became two cache entries, two downloads and two
  surfaces. The requested and failed bookkeeping split as well, so neither
  entry deduped.
- A truncated large-file transfer left a zero-byte `pics1.png` that kept its
  recorded modtime, so the server declared it current every time. The client
  searches the download tier first, so that poisoned entry also shadowed a good
  user copy. The whole world stayed placeholder-colored across restarts.

## Running the tests

Use **`/usr/bin/python3.13`**. The system `python3` is 3.14 and has no
`hypothesis`. Under it, `reborn-protocol`'s property suite silently fails to
*collect* and you get a false green.

Do **not** pass `-q`. The `addopts` in `pyproject.toml` already includes it. A
second `-q` gives `-qq`, which suppresses the pass/fail summary line entirely.

```bash
/usr/bin/python3.13 -m pytest                          # unit + integration
/usr/bin/python3.13 -m game_tester                     # live bot QA (16/16)
SDL_VIDEODRIVER=dummy /usr/bin/python3.13 -m game_tester.render_smoke
```

**`pytest` does not cover the render loop.** On 2026-07-25 the pygame client
crashed on its first rendered frame while all 1295 unit tests and the 16/16 bot
QA passed. Neither suite drives `_render()`. After you touch anything under
`pyreborn/game/`, run `render_smoke`. Without it you have not tested your
change.

## Common Pitfalls

1. **Props 75/76 are NOT position** - They are OSTYPE (string) and TEXTCODEPAGE (3 bytes)
2. **Missing prop handlers** - The parser skips 1 byte instead of the correct size
3. **Centering sprites** - Reborn uses top-left positioning
4. **PLO_TOALL for movement** - Use PLO_OTHERPLPROPS instead
5. **Boundary check failures** - Advance `pos` or break, or the loop never ends
6. **Not running QA tests** - Always run `python -m game_tester` after changes
7. **Green pytest != working client** - see "Running the tests" above
8. **Hand-rolling prop or coordinate math** - use `reborn_protocol.props` and
   `reborn_protocol.coords`. Duplicating either is how they drifted before
