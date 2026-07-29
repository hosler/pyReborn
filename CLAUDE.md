# CLAUDE.md - PyReborn Developer Guide

## Project Overview

**PyReborn** is a Python client library for Reborn game servers. Zero external dependencies for core functionality, optional pygame for the graphical client.

## Directory Structure

```
pyreborn/
├── __init__.py           # Exports: Client, Player, ListServerClient, RCClient, NCClient
├── client.py             # Client facade - session, state components, dispatch
├── client_state.py       # Client's state components (level/gmap/entities/...)
├── handlers/             # Packet handlers, one module per domain
│   ├── registry.py       # @handles(<PLO id>) table; grep it to find a handler
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
├── gs1_client.py         # GS1 script transport/state
├── gs2_client.py         # GS2 bytecode transport
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
    ├── camera.py         # Camera/viewport tracking
    ├── collision.py      # Tile/entity collision
    ├── constants.py      # Screen/tile size constants
    ├── frame_context.py  # FrameContext - per-frame state shared across passes
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
├── login.py              # login_client/login_session - the ONE connect+login
│                         #   path, with guaranteed teardown. Use it; don't
│                         #   hand-roll connect/login (leaked sockets before).
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
  a broken UI. A control that exists is not a control that has anything in it.
  Do NOT pin a control whose population depends on which row the listserver
  happens to return first: `serverlist_description0`, `serverlist_eventnews`
  and `serverlist_tablestab` were removed from Login/Login DEV on 2026-07-26
  for that reason. They belong to the Account Info pane, which
  `Rescripted_Serverlist`'s `showLoginInfo()` only builds when the first listed
  server is a `"P "`/`"3 "` entry. A `"U "` server first yields a blank-named
  root folder (`serverlistcats[4]` is unset) whose auto-select instead runs
  `showServerListEntry(serverlistentries[0])` — its unset `id` reads 0.0, so
  `node.id >= 0` HOLDS — and the faithful engine builds the MAP pane for that
  first row (`Serverlist_Map` with unfetchable `login_servermap_*` art, hence
  0×0, plus per-tick `updateServerMapIcons` host calls; Login was re-baselined
  for this on 2026-07-26). Under the pre-lattice `to_num` compare, the
  `this.selectedserver == entry` guard at weapon-Rescripted_Serverlist.txt:559
  was spuriously TRUE (`<unset> == "<row string>"`), which early-returned and
  built neither pane — the earlier claim that `node.id >= 0` fails was a
  mis-attribution of that masking. Either way pane choice is payload-order
  dependent; the pruned pins stay pruned. `serverlist_serverlist` is the real
  list-is-populated signal; keep that one;
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

### GS1 client-engine conformance (`--gs1-client`)

`python -m game_tester --gs1-client` pins the CLIENT-side GS1 engine
(`pyreborn/gs1_client.py` running in the real Client + GameClient + NPCHandler
stack, SDL dummy) against the decompiled reference client. Each of the 73
rows in `game_tester/gs1_client_conformance.py` is an executable transcription
of one FourPlay citation (`Preagonal/FourPlay/quattroplay/src/...` file:line
in the row), covering footprint blocking/dontblock, touchtestd touch,
timeout=0 cancel, setani-vs-setcharani, say/say2/message/sign ordering,
tiles[]/updateboard, hurt half-hearts, putbomb/putexplosion wire+local pairs,
hideimg(s), hidelocal/showlocal and selectedweapon — so a semantic change that
breaks a row contradicts a cited reference line, not a guess. It spawns its
own throwaway pygserver (never targets `--host`), skips wholesale if that
fails, and finishes in ~12s. Two delivery gotchas are baked in and documented
in the module docstring: weapon-channel scripts must be ONE line (pygserver's
weapon-text builder skips the newline→0xa7 GS1 wire mangling — pinned by the
`weapon_multiline_truncation` divergence row) and every fixture weapon ships
an empty `.gs2bc` cache, because a gs2test binary in the checkout otherwise
compiles GS1-style bodies as GS2 and the cases silently run in the GS2 VM
instead of the engine under test. Rows marked `[PINNED DIVERGENCE]` assert the
current known-divergent shipping state (stacked-sign collapse, weapon
truncation) and go red when the server side gets fixed.

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

Receiving: `raw < bias` is a bare power; `raw >= bias` means `power = raw - bias`
followed by the image. **Branching on `power > 4` instead reads an image string
that is not on the wire and desyncs every following property in the packet.**
Bare powers 1..4 get a synthesised default name (`sword{N}.png`, `.gif` on
classic servers).

Don't hand-roll any of this -- `reborn_protocol.props` owns the descriptor
tables (`PLAYER_PROPS`, `NPC_PROPS`, `BADDY_PROPS`) plus `decode_value`,
`encode_value` and `parse_prop_stream`. It replaced six independent parsers
across this client and pygserver, which is what let them drift apart.

Two more traps from the same fix:
- `PLPROP_COLORS` is 5 bytes on classic and 8 on v6 new-world, and the server
  picks the width from a server-wide mode, NOT from the client version -- so it
  cannot be derived from the handshake.
- Property streams are emitted in ASCENDING id order. A strict parser STOPS at
  the first descending id rather than erroring, so an out-of-order writer makes
  entities silently arrive half-populated.

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

**Do not re-derive this math inline.** `reborn_protocol.coords` owns it for both
this client and pygserver, because independently-written copies are what caused
the repeated coordinate-frame bugs (props frame, door frame, edge-warp frame,
gani anchor, cross-seam collision).

```python
from reborn_protocol.coords import (
    segment_index, segment_at, world_to_local, local_to_world,
    segment_origin, level_index, in_level_bounds,
    camera_origin, world_to_screen, screen_to_world, visible_tile_range,
)
```

Local coords are 0-63 within a segment; `world = local + grid * 64`.

**Segment selection must use `math.floor(world / 64)`.** `int(world / 64)`
truncates toward zero and disagrees for negative coordinates: world `-1.5` is
segment -1 / local 62 under floor, but segment 0 / local 63 under `int()`. That
exact mismatch made the debug tile-editor's hover readout name a different tile
than the one it edited (fixed 2026-07-25).

Known limitation, deliberately not "fixed": for a negative magnitude below one
ULP of 64 (e.g. `-1e-16`), `world % 64` returns exactly `64.0` rather than
staying in `[0, 64)`. Unreachable for real coordinates, which are all multiples
of 1/16 tile.

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

## Where assets live

**Game art is not committed to this repo.** `pyreborn/assets/` is gitignored, so
a fresh clone has almost nothing in it and the client must work with it empty.
`pyreborn/asset_paths.py` owns the three tiers — don't hand-roll paths or
lowercase names anywhere else:

| Tier | Location | What |
|---|---|---|
| bundled | `pyreborn/assets/` | whatever art happens to be installed locally |
| user content | `~/.local/share/pyreborn/content/` (`$PYREBORN_CONTENT_DIR`) | base art a server assumes you already have |
| download cache | `~/.cache/pyreborn/servers/{host}_{port}/` (`$PYREBORN_CACHE_DIR`) | everything the server sends, + `index.json` of modtimes |

The middle tier exists because the original client shipped base art **built in**,
so servers only publish their own custom content and are under no obligation to
serve `pics1.png`, player ganis, `sprites.png`, `body.png`, `head0.png` or the
`COMMON_SOUNDS`. If those are missing the client renders an invisible player and
nothing errors. Populate that directory from your own game install.

The download cache is **advisory**: any IO error degrades to memory-only. It is
revalidated with `PLI_UPDATEFILE`/`PLO_FILEUPTODATE` rather than trusting mtime,
and `PLO_UPDATEPACKAGEISUPDATED` (187) drops a stale entry mid-session.

Two traps this replaced, both of which cost a real outage:
- There used to be a `cache/` directory *inside the checkout* that nothing in
  the client ever wrote. It was populated out of band, so `rm -rf cache/` took
  the tileset with it and a fresh clone never had one at all.
- Asset names are keyed through `normalize_asset_name()` (basename +
  lowercase). Servers descend from a Windows client and send mixed casing; on
  Linux `Body.png` and `body.png` were two cache entries, two downloads and two
  surfaces, with the requested/failed bookkeeping split so neither deduped.

## Running the tests

Use **`/usr/bin/python3.13`**. The system `python3` is 3.14 and lacks
`hypothesis`, so `reborn-protocol`'s property suite silently fails to *collect*
under it and you get a false green.

Do **not** pass `-q`: `pyproject.toml`'s addopts already includes it, and a
second `-q` (`-qq`) suppresses the pass/fail summary line entirely.

```bash
/usr/bin/python3.13 -m pytest                          # unit + integration
/usr/bin/python3.13 -m game_tester                     # live bot QA (16/16)
SDL_VIDEODRIVER=dummy /usr/bin/python3.13 -m game_tester.render_smoke
```

**`pytest` does not cover the render loop.** On 2026-07-25 the pygame client
crashed on its first rendered frame while all 1295 unit tests and the 16/16 bot
QA passed — nothing in either drives `_render()`. After touching anything under
`pyreborn/game/`, run `render_smoke` or you have not tested your change.

## Common Pitfalls

1. **Props 75/76 are NOT position** - They're OSTYPE (string) and TEXTCODEPAGE (3 bytes)
2. **Missing prop handlers** - Causes 1-byte skip instead of correct size
3. **Centering sprites** - Reborn uses top-left positioning
4. **PLO_TOALL for movement** - Use PLO_OTHERPLPROPS instead
5. **Boundary check failures** - Must still advance pos or break to avoid infinite loops
6. **Not running QA tests** - Always run `python -m game_tester` after changes
7. **Green pytest != working client** - see "Running the tests" above
8. **Hand-rolling prop or coordinate math** - use `reborn_protocol.props` and
   `reborn_protocol.coords`; duplicating either is how they drifted before
