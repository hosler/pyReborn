"""The one supported way to build a pygame GameClient with no server socket.

``build_game(**knobs)`` returns a real ``GameClient`` over a real ``Client``.
The world is NOT hand-built: the knobs become a pygserver world (level files,
NPCs, items, other players) held in-process, and a real pygserver ``Player``
logs in through ``LoginService.complete_login`` and is warped by
``Player.warp``. The bytes that player would have written to its socket are
split by the client's own framing code and handed to ``Client._handle_packet``.
Everything the client sends back during the build (the gmap file request,
adjacent-segment requests, ...) is dispatched to that server player, so the
packet stream is whatever pygserver really sends. It cannot drift from the
server, because it IS the server.

Three more things make a frame repeatable on every machine:

* a fixture clock: the game's own ``client.clock`` reads it (an injected time
  source, no module patching), and ``frames()`` advances it by ``dt``. Only
  ``pygame.time.get_ticks`` is still patched (``install_determinism``), for
  the few UI widgets (caret blink, row flicker) that read pygame's counter;
* a per-game ``random`` state, seeded at build and swapped in for each step;
* synthetic art (tileset, body, head, sword, shield, sprites, NPC image,
  player ganis) generated at runtime into the content tier, and the bundled
  tier pinned to the git-tracked files only (``pin_assets``).

``region_differs`` / ``frame_differs`` are the content probes: they compare
two games built with the same clock, one with the thing under test and one
without. See pyReborn/CLAUDE.md, "Offline game fixture".
"""

import asyncio
import atexit
import contextlib
import gc
import os
import random
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

from pyreborn import Client  # noqa: E402
from pyreborn.packets import PacketID  # noqa: E402
from pyreborn.protocol import WebSocketProtocol  # noqa: E402
from pyreborn.pygame_game import GameClient  # noqa: E402
from reborn_protocol.props import NPC_PROPS, PLAYER_PROPS, encode_value  # noqa: E402

# -- NPC specs for the ``npcs`` knob ---------------------------------------
# Keys are NPC_PROPS names, case-insensitive (IMAGE, GANI, NICKNAME, ...),
# applied through pygserver's own NPC prop rules; ``id``, ``x`` and ``y`` are
# required. ``script`` is the CLIENTSIDE half of the NPC's script, ``level``
# puts the NPC on another level or gmap segment than the start one.
IMAGE_NPC = {"id": 101, "x": 24.0, "y": 24.0, "image": "pics1.png",
             "imagepart": (0, 0, 32, 32)}
GANI_NPC = {"id": 102, "x": 34.0, "y": 24.0, "gani": "idle",
            "bodyimage": "body3.png", "headimage": "head2.png",
            "colors": [2, 3, 4, 5, 1]}
NAMED_NPC = {"id": 103, "x": 28.0, "y": 34.0, "gani": "idle",
             "nickname": "Offline Guard", "bodyimage": "body3.png",
             "headimage": "head2.png", "message": "hello there"}
# -- weapon specs for the ``weapons`` knob ------------------------------------
# ``{"name": "-w", "script": "...", "engine": "gs1" | "gs2", "image": ""}``.
# Each becomes a GRAWP001 file in the world's weapons/ directory, loaded by
# pygserver's own GS2ScriptManager and granted to our account, so login
# streams it exactly as a live server does: a GS2 weapon as PLO_NPCWEAPONADD
# plus the PLO_LOADSCRIPT header whose bytecode the client then pulls with
# PLI_UPDATESCRIPT, a GS1 weapon as PLO_NPCWEAPONADD text. A GS1 script must
# be ONE line (pygserver's build_npc_weapon_add sends the text unmangled, so
# the client cuts it at the first newline) and gets an empty .gs2bc cache
# beside it, so a GS2 compiler never turns it into bytecode (see
# game_tester/gs1_client_conformance.py generate_fixtures). A GS2 script is
# the clientside half; the knob adds the //#CLIENTSIDE marker. Compiling it
# needs the gs2test binary (tests/unit/gs2_compiler.py require_compiler).

#: A look for another player that no other character shares, so its colours
#: say whose pixels they are (own player: body.png/head0.png, NPC characters:
#: body3.png/head2.png). ``players`` specs take these as PLAYER_PROPS names.
OTHER_LOOK = {"bodyimg": "body2.png", "headgif": "head1.png"}

#: LevelItemType ids; the wire carries the numeric id.
ITEM_GREENRUPEE = 0

ACCOUNT = "offline-tester"
BOARD_SIZE = 64
GMAP_NAME = "fixture.gmap"
GMAP_SEGMENTS = ("fixture_a.nw", "fixture_b.nw",
                 "fixture_c.nw", "fixture_d.nw")  # row-major, 2x2
SEED = 20261111

#: Our own appearance at login, as the account file would hold it. The
#: ``me`` knob overrides any pygserver Character attribute.
DEFAULT_ME = {"nickname": ACCOUNT, "head_image": "head0.png",
              "body_image": "body.png", "sword_image": "sword1.png",
              "shield_image": "shield1.png", "colors": [2, 3, 4, 5, 1],
              "max_hearts": 3.0}

# == determinism: clock and random ===========================================

WALL_ORIGIN = 1_000_000.0
#: Far from Clock.SIM_ORIGIN (1_000_000) on purpose: frame time and
#: simulation time must never be close in a test, or a stamp taken on one
#: clock and compared on the other could not fail. The water shimmer index
#: is int(now / period) % 4, so its phase depends on this value: frame
#: baselines recorded before 2026-11-12 (origin 1_000_000) differ there.
MONO_ORIGIN = 40_000_000.0
TICKS_ORIGIN_MS = 10_000


class FixtureClock:
    """Seconds since the game was built. Only ``advance`` moves it."""

    def __init__(self) -> None:
        self.t = 0.0

    def advance(self, seconds: float) -> None:
        if seconds > 0:
            self.t += seconds


_REAL = {"ticks": pygame.time.get_ticks}
_ACTIVE: Dict[str, Optional[FixtureClock]] = {"clock": None}


def _fake_ticks() -> int:
    clock = _ACTIVE["clock"]
    return (_REAL["ticks"]() if clock is None
            else TICKS_ORIGIN_MS + int(clock.t * 1000))


def install_determinism(monkeypatch) -> None:
    """Route ``pygame.time.get_ticks`` through the active fixture clock.

    The game's time does NOT go through this: ``client.clock`` is handed the
    fixture clock as its time source (``attach_clock``), so ``time.time`` and
    ``time.monotonic`` are left alone. ``get_ticks`` is the one counter still
    read directly (the allowlisted caret-blink and row-flicker widgets in
    tests/unit/test_clock_discipline.py). Outside a build or step no clock is
    active and the real function answers."""
    monkeypatch.setattr(pygame.time, "get_ticks", _fake_ticks)
    monkeypatch.setitem(_ACTIVE, "clock", None)


def _clock_is_installed() -> bool:
    return pygame.time.get_ticks is _fake_ticks


def attach_clock(client: Client, fixture: FixtureClock) -> None:
    """Make ``client.clock`` read ``fixture``: monotonic ``MONO_ORIGIN + t``,
    wall ``WALL_ORIGIN + t``, and a sleep that advances it."""
    client.clock.set_sources(
        source=lambda: MONO_ORIGIN + fixture.t,
        wall_source=lambda: WALL_ORIGIN + fixture.t,
        sleep_source=fixture.advance)


@contextlib.contextmanager
def _running(owner) -> Iterable[None]:
    """Make ``owner``'s clock and random state the live ones."""
    previous = _ACTIVE["clock"]
    saved = random.getstate()
    _ACTIVE["clock"] = owner._fixture_clock
    random.setstate(owner._fixture_rng)
    try:
        yield
    finally:
        owner._fixture_rng = random.getstate()
        random.setstate(saved)
        _ACTIVE["clock"] = previous


@contextlib.contextmanager
def _wall_clock() -> Iterable[None]:
    """Real ``get_ticks`` for the in-process server's event loop."""
    previous = _ACTIVE["clock"]
    _ACTIVE["clock"] = None
    try:
        yield
    finally:
        _ACTIVE["clock"] = previous


# == synthetic assets ==========================================================

#: Git-tracked files in pyreborn/assets/. The fixture's bundled tier holds
#: only these, so a developer's gitignored art never reaches a test frame.
TRACKED_BUNDLED = ("baddies", "emblem.png", "rebornfont.ttf")

#: Player ganis the synthetic content tier carries.
SYNTHETIC_GANIS = ("idle", "walk", "sword", "hurt", "dead", "grab", "pull",
                   "push", "lift", "carry", "sit", "carrystill")


#: Every synthetic sheet: file name -> (pixel size, cell size). Each CELL of a
#: sheet has a colour of its own (``cell_color``), unique across all sheets, so
#: a pixel on screen says which sheet and which cell of it was blitted there.
SHEETS: Dict[str, Tuple[Tuple[int, int], int]] = {
    "dustynewpics1.png": ((2048, 512), 16),    # the tileset: one cell per tile
    "pics1.png": ((2048, 512), 16),
    "body.png": ((128, 128), 16),              # own player
    "body2.png": ((128, 128), 16),             # other players (OTHER_LOOK)
    "body3.png": ((128, 128), 16),             # NPC characters
    "head0.png": ((32, 256), 8),
    "head1.png": ((32, 256), 8),
    "head2.png": ((32, 256), 8),
    "sword1.png": ((16, 32), 8),
    "shield1.png": ((16, 16), 8),
    "sprites.png": ((512, 512), 16),
}


def cell_color(sheet: str, col: int, row: int) -> Tuple[int, int, int]:
    """The colour of cell (col, row) of ``sheet``. Three 6-bit digits of the
    cell's serial number become R, G and B (16 + 3 * digit), so no two cells
    of any sheet share a colour and none is black."""
    serial = list(SHEETS).index(sheet) * 16384 + row * 128 + col
    return (16 + 3 * (serial & 63), 16 + 3 * ((serial >> 6) & 63),
            16 + 3 * ((serial >> 12) & 63))


def cell_outline(color: Tuple[int, int, int]) -> Tuple[int, int, int]:
    """The colour of the one-pixel outline a cell of ``color`` is drawn with."""
    return (color[0] // 3, color[1] // 3, color[2] // 3)


def sheet_color_at(sheet: str, px: int, py: int) -> Tuple[int, int, int]:
    """The colour of sheet pixel (px, py), which must not lie on a cell's
    one-pixel outline."""
    cell = SHEETS[sheet][1]
    return cell_color(sheet, px // cell, py // cell)


def tile_cell(tile_id: int) -> Tuple[int, int]:
    """Column and row of a tile's cell in the tileset sheet: 16-column blocks
    of 32 rows (the layout palette.py documents)."""
    return (tile_id // 512) * 16 + tile_id % 16, (tile_id // 16) % 32


def tile_color(tile_id: int) -> Tuple[int, int, int]:
    """The colour tile ``tile_id`` has on screen."""
    return cell_color("dustynewpics1.png", *tile_cell(tile_id))


def _sheet_surface(name: str) -> "pygame.Surface":
    (width, height), cell = SHEETS[name]
    surf = pygame.Surface((width, height))
    for row in range(height // cell):
        for col in range(width // cell):
            color = cell_color(name, col, row)
            rect = (col * cell, row * cell, cell, cell)
            surf.fill(color, rect)
            pygame.draw.rect(surf, cell_outline(color), rect, 1)
    return surf


#: Where the player gani places each layer inside the 48x48 canvas that
#: anchors at the entity's top-left (x, y offsets in pixels), and the layer
#: draw order. gani frame lines and tests both read these.
BODY_AT = (8, 16)
HEAD_AT = (8, 2)
SHIELD_AT = (26, 20)
SHIELD_FRAME_STEP = 4      # the shield moves this many px right per frame
SWORD_AT = (28, 6)         # only the "sword" gani places the sword
CELL_PX = 32               # body and head sprites are 32x32 on their sheets


def _gani_text(name: str) -> str:
    lines = [
        "SPRITE    0  SPRITES   0   0  24  12 shadow",
        "SPRITE   10   SHIELD   0   0  16  16 shield",
        "SPRITE   20    SWORD   0   0  16  32 sword",
    ]
    for d in range(4):
        lines.append("SPRITE  %d     HEAD   0 %3d  32  32 head" % (100 + d, d * 32))
        lines.append("SPRITE  %d     BODY %3d   0  32  32 body" % (200 + d, d * 32))
    lines += ["DEFAULTBODY body.png", "DEFAULTHEAD head0.png",
              "DEFAULTSWORD sword1.png", "DEFAULTSHIELD shield1.png", ""]
    if name in ("walk", "sword", "carry", "push", "pull"):
        lines.append("LOOP")
    if name == "dead":
        lines.append("SETBACKTO dead")
    lines.append("ANI")
    for frame in range(2 if name in ("walk", "sword") else 1):
        for d in range(4):
            parts = ["0 12 34", "%d %d %d" % ((200 + d,) + BODY_AT),
                     "%d %d %d" % ((100 + d,) + HEAD_AT),
                     "10 %d %d" % (SHIELD_AT[0] + SHIELD_FRAME_STEP * frame,
                                   SHIELD_AT[1])]
            if name == "sword":
                parts.append("20 %d %d" % SWORD_AT)
            lines.append("   " + ",  ".join(parts))
        lines.append("")
    lines.append("ANIEND")
    return "\n".join(lines) + "\n"


def write_synthetic_assets(root: Path) -> Path:
    """Generate the art a scene needs into ``root`` (idempotent) and return it.

    Nothing is copied from the repo or the developer's machine: every file is
    drawn here, so the scene is the same everywhere."""
    marker = root / ".complete"
    if marker.exists():
        return root
    root.mkdir(parents=True, exist_ok=True)
    for name in SHEETS:
        pygame.image.save(_sheet_surface(name), str(root / name))
    ganis = root / "ganis"
    ganis.mkdir(exist_ok=True)
    for name in SYNTHETIC_GANIS:
        (ganis / f"{name}.gani").write_text(_gani_text(name))
    marker.write_text("ok\n")
    return root


def pin_assets(monkeypatch, root: Path) -> Path:
    """Point the content tier at synthetic art and the bundled tier at the
    git-tracked files only. Returns the content directory."""
    content = write_synthetic_assets(root / "content")
    monkeypatch.setenv("PYREBORN_CONTENT_DIR", str(content))
    package = root / "package"
    assets = package / "assets"
    if not assets.exists():
        assets.mkdir(parents=True)
        real = Path(__file__).resolve().parents[1] / "pyreborn" / "assets"
        for name in TRACKED_BUNDLED:
            if (real / name).exists():
                (assets / name).symlink_to(real / name)
    import pyreborn.game.setup as setup_module
    monkeypatch.setattr(setup_module, "PACKAGE_DIR", package)
    # The GS2 GUI font index lists pyreborn/assets/ itself (profiles.py
    # prime_font_roots), not the bundled tier above. Seed it with what a
    # clean checkout plus this content tier would index, so a gitignored
    # .ttf on a developer's machine cannot change a frame.
    from pyreborn.game.gs2_gui import profiles
    monkeypatch.setattr(profiles, "_font_index",
                        {"rebornfont": str(assets / "rebornfont.ttf")})
    monkeypatch.setattr(profiles, "_font_index_key", str(content))
    return content


# == wire helpers (for tests that push one more packet) ======================

def _gbyte(value: int, count: int) -> bytes:
    out = []
    for i in range(count):
        shift = 7 * (count - 1 - i)
        out.append(((int(value) >> shift) & 0x7F) + 32)
    return bytes(out)


def _gchar(value: int) -> bytes:
    return _gbyte(value, 1)


def _props(table, props: Dict[str, Any]) -> bytes:
    """``[gchar prop id][payload]`` pairs in ASCENDING id order (a descending
    id stops the parser, so the order is part of the wire contract)."""
    by_name = {d.name.lower(): d for d in table.values()}
    pairs = []
    for key, value in props.items():
        desc = by_name[key.lower()]
        pairs.append((desc.id, encode_value(desc, value)))
    return b"".join(bytes([32 + pid]) + payload
                    for pid, payload in sorted(pairs))


def sent_player_props(sent) -> List[List[Tuple[int, Any]]]:
    """Every PLI_PLAYERPROPS the client sent (``client._protocol.sent``) as a
    list of ``(prop id, decoded value)`` pairs in wire order, one list per
    packet. For tests that pin which props went out and in what order."""
    from reborn_protocol.props import decode_value
    out = []
    for packet_id, data in sent:
        if packet_id != PacketID.PLI_PLAYERPROPS:
            continue
        pairs, pos = [], 0
        while pos < len(data):
            prop_id = data[pos] - 32
            value, pos = decode_value(PLAYER_PROPS[prop_id], data, pos + 1)
            pairs.append((prop_id, value))
        out.append(pairs)
    return out


def _default_tiles(tx: int, ty: int) -> int:
    if tx in (0, 63) or ty in (0, 63):
        return 2
    return 0 if (tx // 4 + ty // 4) % 2 == 0 else 1


_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


def _nw_text(tiles, *, signs=(), links=(), chests=(), baddies=()) -> str:
    """A GLEVNW01 level file, the format pygserver loads from disk."""
    from pygserver.level import BADDY_TYPE_TO_NAME
    tiles = tiles or _default_tiles
    lines = ["GLEVNW01"]
    for y in range(BOARD_SIZE):
        row = "".join(_B64[t // 64] + _B64[t % 64]
                      for t in (int(tiles(x, y)) for x in range(BOARD_SIZE)))
        lines.append(f"BOARD 0 {y} 64 0 {row}")
    for line in links:
        lines.append("LINK " + line)
    for x, y, text in signs:
        lines += [f"SIGN {x} {y}", text, "SIGNEND"]
    for x, y, _opened in chests:
        lines.append(f"CHEST {x} {y} greenrupee 0")
    for spec in baddies:
        name = BADDY_TYPE_TO_NAME.get(int(spec.get("type", 0)), "graysoldier")
        lines += [f"BADDY {spec['x']} {spec['y']} {name}", "", "", "",
                  "BADDYEND"]
    return "\n".join(lines) + "\n"


def tiles_from_board(board: Sequence[int]):
    """A ``tiles`` knob answering from a flat 64x64 row-major list (the shape
    ``Client.tiles`` has), for tests that were written against one."""
    return lambda tx, ty: board[ty * BOARD_SIZE + tx]


def gmap_text(names: Sequence[str] = GMAP_SEGMENTS, width: int = 2) -> str:
    rows = [names[i:i + width] for i in range(0, len(names), width)]
    body = ",\n".join(",".join('"%s"' % n for n in row) for row in rows)
    return ("GRMAP001\nWIDTH %d\nHEIGHT %d\nLEVELNAMES\n%s\nLEVELNAMESEND\n"
            % (width, len(rows), body))


# == the in-process server and the loopback ==================================

class _Loopback:
    """Stands in for the Protocol. Outbound packets are recorded (``sent``)
    and, while the server is attached, dispatched to the server player.
    Inbound server bytes are split by the client's own framing code
    (WebSocketProtocol._parse_packets, the socket-free twin of
    Protocol.recv_packets)."""

    connected = True

    def __init__(self) -> None:
        self.sent: List[Tuple[int, bytes]] = []
        #: Every packet the server delivered, in order (fixture tests read
        #: it to pin the stream's shape).
        self.received: List[Tuple[int, bytes]] = []
        self.raw_data_expected = 0
        self.raw_data_buffer = b""
        self.pending_packets: List[Tuple[int, bytes]] = []
        #: The game's FixtureClock (set by build_client); a wait advances it.
        self.clock: Optional[FixtureClock] = None

    def send_packet(self, packet_id, data=b"", *args, **kwargs):
        self.sent.append((int(packet_id), bytes(data)))
        return True

    def split(self, raw: bytes) -> List[Tuple[int, bytes]]:
        WebSocketProtocol._parse_packets(self, raw)
        out, self.pending_packets = self.pending_packets, []
        self.received.extend(out)
        return out

    def recv_packets(self, timeout=0.0):
        # A wait for packets is a wait: the fixture clock moves by it, so a
        # "pump update() until clock.now() passes X" loop ends.
        if self.clock is not None:
            self.clock.advance(timeout)
        return []

    def disconnect(self):
        self.connected = False


class _CaptureSession:
    """pygserver PlayerSession without a socket: what would have been
    encrypted and written is kept, in order, as the decoded packet bytes."""

    def __init__(self) -> None:
        self.out: List[bytes] = []
        self.connected = True
        self.codec = object()
        self.last_data_time = 0.0

    async def send(self, data: bytes):
        self.out.append(bytes(data))

    async def send_login_response(self, data: bytes):
        self.out.append(bytes(data))

    async def close(self):
        self.connected = False


#: Event loops of closed worlds, cleaned and ready for the next one. Creating a
#: loop opens a socketpair (~8 ms); a world owns its loop exclusively while it
#: lives, so a loop that was cleaned at close can be handed to the next world.
_LOOP_POOL: List["asyncio.AbstractEventLoop"] = []


@atexit.register
def _close_pooled_loops() -> None:
    while _LOOP_POOL:
        _LOOP_POOL.pop().close()


class ServerWorld:
    """A pygserver world held in-process for one offline client.

    ``run(fn)`` awaits ``fn(world)`` on the world's event loop (with real
    time, which the server's loop needs) and then delivers everything our
    server player sent to the client, pumping the client's replies back until
    both sides are quiet."""

    def __init__(self, root: Path, client: Client) -> None:
        from pygserver.protocol import colors
        self.root = root
        self.client = client
        self.loop = _LOOP_POOL.pop() if _LOOP_POOL else asyncio.new_event_loop()
        self._colors_server = colors._server
        self.server = None
        self.me = None
        self.peers: Dict[int, Any] = {}

    def close(self) -> None:
        from pygserver.protocol import colors
        colors._server = self._colors_server
        loop, self.loop = self.loop, None
        if loop is None:
            return
        with _wall_clock():
            pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True))
            _LOOP_POOL.append(loop)

    # -- server-side helpers usable inside run() ------------------------------

    def level(self, name: str):
        return self.server.world.get_level(name)

    def run(self, fn: Callable[["ServerWorld"], Any]) -> None:
        """Run ``fn(world)`` (a coroutine function) server-side, then deliver
        and pump."""
        with _wall_clock():
            self.loop.run_until_complete(fn(self))
            self.loop.run_until_complete(asyncio.sleep(0))
        self.pump()

    def send(self, raw: bytes) -> None:
        """Have the server send ``raw`` (pygserver builder output) to us."""
        async def _send(world):
            await world.me.send_raw(raw)
        self.run(_send)

    def pump(self, rounds: int = 20) -> None:
        loopback = self.client._protocol
        cursor = len(loopback.sent)
        for _ in range(rounds):
            out, self.me.session.out = self.me.session.out, []
            for raw in out:
                for packet_id, data in loopback.split(raw):
                    self.client._handle_packet(packet_id, data)
            replies = loopback.sent[cursor:]
            cursor = len(loopback.sent)
            if not replies:
                if not out:
                    return
                continue

            async def _dispatch(world, replies=replies):
                for packet_id, data in replies:
                    await world.me._dispatch_packet(packet_id, data)
            with _wall_clock():
                self.loop.run_until_complete(_dispatch(self))
                self.loop.run_until_complete(asyncio.sleep(0))
        raise AssertionError("client and server never went quiet")


def _new_player(server, player_id: int, account: str):
    from pygserver.player import Player
    player = Player(server, player_id, AsyncMock(), MagicMock())
    player.session = _CaptureSession()
    player.account_name = account
    server.players[player_id] = player
    return player


async def _build_server(world: ServerWorld, *, levels: Dict[str, Any],
                        gmap: bool, start: str, player_xy, hearts: float,
                        me: Dict[str, Any], npcs, chests, preplaced_items, players,
                        baddies, signs, links, options, weapons=()) -> None:
    from pygserver.baddy import BaddyManager
    from pygserver.combat import CombatManager
    from pygserver.config import ServerConfig
    from pygserver.filesystem import FileSystem
    from pygserver.horse import HorseManager
    from pygserver.items import ItemManager
    from pygserver.level import Level
    from pygserver.server import GameServer
    from pygserver.world import GMap

    root = world.root
    world_dir = root / "world"
    world_dir.mkdir(parents=True)
    for name, tiles in levels.items():
        here = name == start
        (world_dir / name).write_text(_nw_text(
            tiles, signs=signs if here else (), links=links if here else (),
            chests=chests if here else (), baddies=baddies if here else ()),
            encoding="latin-1")
    if gmap:
        (world_dir / GMAP_NAME).write_text(gmap_text())

    config = ServerConfig.from_server_dir(str(root))
    config.start_level = start
    config.start_x, config.start_y = player_xy
    config.gmaps = [GMAP_NAME] if gmap else []
    for key, value in options.items():
        if not hasattr(config, key):
            raise ValueError(f"pygserver has no server option {key!r}")
        setattr(config, key, value)
    server = GameServer(config)
    world.server = server
    # The subsystems GameServer.start() would create, minus their tick loops
    # and the list-server link: nothing here may outlive the build.
    server.combat_manager = CombatManager(server)
    server.item_manager = ItemManager(server)
    server.baddy_manager = BaddyManager(server)
    server.horse_manager = HorseManager(server)
    server.filesystem = FileSystem(server, str(root))
    for name in levels:
        level = Level.load(str(world_dir / name))
        server.world.add_level(level)
        await server._register_level_features(level)
    if gmap:
        server.world.add_gmap(GMap.load(str(world_dir / GMAP_NAME)))

    for x, y, opened in chests:
        if opened:
            for chest in server.item_manager.get_chests_on_level(start):
                if (chest.x, chest.y) == (x, y):
                    chest.opened_by.add(ACCOUNT)
    # Items that exist BEFORE we log in. The reference server sends no level
    # item to a player who enters, so none may reach the client's stream
    # (a revert would restore ItemManager.send_level_items in
    # pygserver/items.py, the loop that sent build_item_add per level item on
    # entry; test_an_item_present_before_login_is_not_sent_on_entry catches it).
    from pygserver.protocol.constants import LevelItemType
    for x, y, item in preplaced_items:
        await server.item_manager.spawn_item(
            server.world.get_level(start), x, y, LevelItemType(item))
    by_name = {d.name.lower(): d for d in NPC_PROPS.values()}
    for spec in npcs:
        spec = dict(spec)
        npc_id = spec.pop("id")
        level = server.world.get_level(spec.pop("level", start))
        npc = server.npc_manager.create_npc(
            name="fixturenpc", level=level, x=spec.pop("x"), y=spec.pop("y"),
            npc_id=npc_id)
        script = spec.pop("script", None)
        if script:
            server.npc_manager.attach_gs1(npc, "//#CLIENTSIDE\n" + script)
        for key, value in spec.items():
            # pygserver's own NPC prop rules (a GANI makes the NPC a
            # character, image "#c#", exactly as on the server).
            if not npc.apply_client_prop(by_name[key.lower()].id, value):
                raise ValueError(f"pygserver refused NPC prop {key}={value!r}")
    for spec in players:
        spec = dict(spec)
        pid = spec.pop("id")
        peer = _new_player(server, pid, spec.get("nickname", f"peer{pid}"))
        peer.logged_in = True
        world.peers[pid] = peer
        x, y = spec.pop("x"), spec.pop("y")
        chat = spec.pop("curchat", None)
        await peer.warp(spec.pop("level", start), x, y)
        if spec:
            # Their client announces its look, through the real handler.
            await peer._dispatch_packet(PacketID.PLI_PLAYERPROPS,
                                        _props(PLAYER_PROPS, spec))
        peer._fixture_chat = chat

    me_player = _new_player(server, max(server.next_player_id, 2), ACCOUNT)
    server.next_player_id = me_player.id + 1
    world.me = me_player
    for attr, value in {**DEFAULT_ME, **me}.items():
        setattr(me_player, attr, value)
    me_player.hearts = hearts
    if weapons:
        _install_weapons(server, root, me_player, weapons)
    await me_player.login_service.complete_login()


def _install_weapons(server, root: Path, me_player, weapons) -> None:
    """Write the ``weapons`` knob's specs as weapon files, load them through
    pygserver's GS2ScriptManager (GameServer.start() builds it; the fixture
    does not run start()) and grant them to our account."""
    from pygserver.gs2 import GS2ScriptManager
    weapons_dir = Path(server.config.weapons_dir)
    weapons_dir.mkdir(parents=True, exist_ok=True)
    for spec in weapons:
        name = spec["name"]
        engine = spec.get("engine", "gs1")
        script = spec["script"]
        stem = name.lstrip("-*") or "weapon"
        if engine == "gs2":
            script = "//#CLIENTSIDE\n" + script
        elif engine == "gs1":
            if "\n" in script.strip():
                raise ValueError(f"GS1 weapon {name}: one line only "
                                 "(pygserver sends weapon text unmangled)")
        else:
            raise ValueError(f"weapon {name}: engine must be gs1 or gs2")
        source = weapons_dir / f"{stem}.txt"
        source.write_text(f"GRAWP001\nREALNAME {name}\nIMAGE "
                          f"{spec.get('image', '')}\nSCRIPT\n{script}\n"
                          "SCRIPTEND\n", encoding="latin-1")
        if engine == "gs1":
            cache = source.with_suffix(".gs2bc")
            cache.write_bytes(b"")
            stamp = source.stat().st_mtime + 60
            os.utime(cache, (stamp, stamp))
    server.gs2_manager = GS2ScriptManager(server, str(root))
    server.gs2_manager.load()
    for spec in weapons:
        me_player.add_weapon(spec["name"])
        script = server.gs2_manager.get_weapon(spec["name"])
        if script is None:
            raise ValueError(f"pygserver did not load weapon {spec['name']}")
        if spec.get("engine") == "gs2" and not script.bytecode:
            raise ValueError(f"GS2 weapon {spec['name']} did not compile: "
                             f"{server.gs2_manager.compiler.last_error!r}")


async def _peers_chat(world: "ServerWorld") -> None:
    """Each peer with a ``curchat`` says it, through the server's own
    PLI_PLAYERPROPS handler, which relays it to us."""
    for peer in world.peers.values():
        if peer._fixture_chat:
            await peer._dispatch_packet(PacketID.PLI_PLAYERPROPS,
                                        _props(PLAYER_PROPS,
                                               {"curchat": peer._fixture_chat}))


def _spawn_items(world, items, level_name: str) -> None:
    """Create the ground items while we are in the level, so the server sends
    the item-add packet then. The reference server never sends a level's items
    to a player who enters (GServer-v2 Level.cpp addItem is the only item-add
    sender besides a player's own drop), so an item that exists before we
    arrive would never reach the client."""
    from pygserver.protocol.constants import LevelItemType

    async def _spawn(w):
        level = w.server.world.get_level(level_name)
        for x, y, item in items:
            await w.server.item_manager.spawn_item(level, x, y,
                                                   LevelItemType(item))
    if items:
        world.run(_spawn)


def _send_events(client, bombs, arrows, items=(), level_name="") -> None:
    """What happens after we arrive: other players talk, ground items are
    created, bombs drop and arrows fly. Sent once the game exists, because the
    game learns of a relayed bomb or arrow (or a new item) through the client
    callbacks it wires at construction."""
    from pygserver.protocol.packets import build_arrow_add, build_bomb_add
    world = client.server
    world.run(_peers_chat)
    _spawn_items(world, list(items), level_name)
    for x, y in bombs:
        # Owner 77, power 1 from a player (bit 3), 20 ticks of fuse.
        world.send(build_bomb_add(77, x, y, 1 | 8, 20))
    for x, y, direction in arrows:
        world.send(build_arrow_add(77, x, y, (direction & 3) | 8, 0, 1))


# == the factory =============================================================

def build_client(*,
                 level: str = "fixture.nw",
                 player_xy: Tuple[float, float] = (30.0, 30.0),
                 hearts: float = 3.0,
                 me: Optional[Dict[str, Any]] = None,
                 version: str = "6.037",
                 tiles=None,
                 extra_levels: Optional[Dict[str, Any]] = None,
                 npcs: Iterable[Dict[str, Any]] = (),
                 chests: Iterable[Tuple[int, int, bool]] = (),
                 items: Iterable[Tuple[float, float, int]] = (),
                 preplaced_items: Iterable[Tuple[float, float, int]] = (),
                 players: Iterable[Dict[str, Any]] = (),
                 baddies: Iterable[Dict[str, Any]] = (),
                 bombs: Iterable[Tuple[float, float]] = (),
                 arrows: Iterable[Tuple[float, float, int]] = (),
                 signs: Iterable[Tuple[int, int, str]] = (),
                 links: Iterable[str] = (),
                 gmap: bool = False,
                 gmap_segment: Tuple[int, int] = (0, 0),
                 server_options: Optional[Dict[str, Any]] = None,
                 weapons: Iterable[Dict[str, Any]] = (),
                 root: Optional[Path] = None,
                 defer_events: bool = False) -> "Client":
    """A populated ``Client`` with no game: the world half of build_game.

    Knobs (positions are level-local tiles):

    level / player_xy   start level and position (the server's startlevel).
    hearts              our hearts at login (0 -> dead).
    me                  pygserver Character attributes for our account
                        (``{"body_image": "body2.png", "rupees": 120}``).
    tiles               ``fn(tx, ty) -> tile id`` for every level file.
    extra_levels        ``{name: tiles fn or None}`` more levels to warp to.
    npcs                specs (see IMAGE_NPC / GANI_NPC / NAMED_NPC).
    chests              ``(x, y, opened)``; opened = already opened by us.
    items               ``(x, y, item id)`` ground items, created after we
                        arrive (the server sends no item on entry).
    preplaced_items     same shape, created BEFORE we log in: a test that the
                        server sends none of them on entry.
    players             other players ``{"id", "x", "y", ...}``; the rest are
                        PLAYER_PROPS names their client sends (``curchat``
                        is said after we arrive).
    baddies             ``{"x", "y", "type"}``.
    bombs / arrows      ``(x, y)`` / ``(x, y, direction)`` relayed from player
                        77 after login (pygserver's builders).
    signs / links       ``(x, y, text)`` / ``"dest x y w h newx newy"``.
    gmap                2x2 gmap (GMAP_SEGMENTS); the player starts in
                        ``gmap_segment`` (grid x, y) at ``player_xy``.
    server_options      ServerConfig attributes (``{"bigmap": "..."}``).
    weapons             weapon specs granted to us and streamed at login,
                        before any GameClient exists (see the comment above
                        DEFAULT_ME); a GS2 one runs its top level and
                        onCreated when the game attaches its GS2 runtime.

    ``client.feed(packet_id, data)`` pushes one hand-built packet through the
    handler table; ``client.server`` is the ServerWorld (``.send(raw)``,
    ``.run(coro_fn)``) for anything pygserver can produce itself.
    ``client._protocol.sent`` lists what the client sent.
    """
    if not _clock_is_installed():
        raise RuntimeError("use the make_game / make_client fixtures; they "
                           "install the fixture clock first")

    root = Path(root or tempfile.mkdtemp(prefix="offline-world-"))
    client = Client("127.0.0.1", 14900, version=version)
    client._protocol = _Loopback()
    client.player.account = ACCOUNT
    client._fixture_clock = FixtureClock()
    client._protocol.clock = client._fixture_clock
    attach_clock(client, client._fixture_clock)
    client._fixture_rng = random.Random(SEED).getstate()

    if gmap:
        names = list(GMAP_SEGMENTS)
        start = names[gmap_segment[1] * 2 + gmap_segment[0]]
    else:
        names = [level]
        start = level
    levels = {name: tiles for name in names}
    levels.update(extra_levels or {})

    world = ServerWorld(root, client)
    client.server = world
    with _running(client):
        try:
            world.run(lambda w: _build_server(
                w, levels=levels, gmap=gmap, start=start,
                player_xy=player_xy, hearts=hearts, me=me or {},
                npcs=npcs, chests=chests, preplaced_items=list(preplaced_items),
                players=players,
                baddies=baddies, signs=signs, links=links,
                options=server_options or {}, weapons=list(weapons)))
            if defer_events:
                client._fixture_events = (list(bombs), list(arrows),
                                          list(items), start)
            else:
                _send_events(client, bombs, arrows, list(items), start)
        except BaseException:
            world.close()
            raise

    def feed(packet_id, data=b""):
        with _running(client):
            client._handle_packet(int(packet_id), data)

    client.feed = feed
    return client


def build_game(*, flying: Iterable[Tuple[float, float, int, int]] = (),
               start: bool = True,
               register: Optional[Callable[["GameClient"], None]] = None,
               **client_knobs) -> "GameClient":
    """Build a GameClient, offline, in dummy SDL, over build_client's world.

    Takes every build_client knob plus:

    flying              ``(x, y, direction, power)`` script-fired flying
                        objects (power 2 fireblast, 3 nuke), queued through the
                        GS1 engine's own hook.
    start               call ``game.start()`` (default).
    register            called with the game as soon as it exists, before
                        ``start()``, so a fixture can always shut it down.

    ``game.frames(n)`` runs n strict steps on the game's fixture clock and
    keeps a copy of the finished frame in ``game.last_frame``;
    ``game.ticks(n)`` runs exactly n simulation ticks the same way;
    ``game.feed(id, data)`` and ``game.server`` are the client's.
    """
    client = build_client(defer_events=True, **client_knobs)
    try:
        with _running(client):
            game = GameClient(client)
    except BaseException:
        client.server.close()
        raise
    game._fixture_clock = client._fixture_clock
    game._fixture_rng = client._fixture_rng
    game.server = client.server
    game.feed = client.feed
    game.last_frame = None
    if register is not None:
        register(game)
    with _running(game):
        for x, y, direction, power in flying:
            game.gs1.on_flying(x, y, direction, power)

    def frames(n: int = 1, dt: float = 1 / 60, events=None) -> None:
        """Run ``n`` strict steps (frames). The fixture clock advances by
        ``dt`` per step, so a run is repeatable. ``events`` go in the first.
        The simulation advances in 50 ms ticks (pyreborn/clock.py): at the
        default 1/60 s a tick runs on every third frame."""
        with _running(game):
            for i in range(n):
                game._fixture_clock.advance(dt)
                game.step(dt, strict=True,
                          events=events if i == 0 else None)
        game.last_frame = game.screen.copy()

    def ticks(n: int = 1, events=None) -> None:
        """Run exactly ``n`` simulation ticks: ``n`` frames of one tick
        length each (whatever part of a tick the clock already held stays
        held). ``events`` go in the first. At a frame tick of 0 (one tick
        per frame) the frames are 1/60 s."""
        frames(n, dt=game.clock.tick_length or 1 / 60, events=events)

    game.frames = frames
    game.ticks = ticks
    if start:
        with _running(game):
            game.start()
    with _running(game):
        bombs, arrows, items, start_level = client._fixture_events
        _send_events(client, bombs, arrows, items, start_level)
    return game


# == content probes ===============================================================

def surface_is_flat(surface: "pygame.Surface") -> bool:
    """True when every pixel equals the top-left one."""
    first = surface.get_at((0, 0))
    same = pygame.mask.from_threshold(surface, first, (1, 1, 1, 255))
    return same.count() == surface.get_width() * surface.get_height()


def _frame(game) -> "pygame.Surface":
    if game.last_frame is None:
        raise AssertionError("run game.frames() before probing")
    return game.last_frame


def world_rect(game, x: float, y: float, w: float = 1.0, h: float = 1.0,
               pad: float = 0.0) -> "pygame.Rect":
    """The screen rect of world tiles (x, y, w, h), clipped to the frame."""
    (sx0, sy0) = game.camera.world_to_screen(x - pad, y - pad)
    (sx1, sy1) = game.camera.world_to_screen(x + w + pad, y + h + pad)
    rect = pygame.Rect(int(sx0), int(sy0), int(sx1 - sx0), int(sy1 - sy0))
    return rect.clip(_frame(game).get_rect())


def changed_pixels(subject, baseline, rect: Optional["pygame.Rect"] = None) -> int:
    """How many pixels of ``rect`` (default: whole frame) differ between the
    two games' last frames."""
    a, b = _frame(subject), _frame(baseline)
    if a.get_size() != b.get_size():
        raise AssertionError(f"frame sizes differ: {a.get_size()} {b.get_size()}")
    rect = (rect or a.get_rect()).clip(a.get_rect())
    if rect.width <= 0 or rect.height <= 0:
        raise AssertionError(f"probe rect {rect} is off screen")
    sa, sb = a.subsurface(rect), b.subsurface(rect)
    diff = sa.copy()
    diff.blit(sb, (0, 0), special_flags=pygame.BLEND_RGB_SUB)
    back = sb.copy()
    back.blit(sa, (0, 0), special_flags=pygame.BLEND_RGB_SUB)
    diff.blit(back, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
    same = pygame.mask.from_threshold(diff, (0, 0, 0), (1, 1, 1, 255)).count()
    return rect.width * rect.height - same


def changed_outside(subject, baseline, rects: Sequence["pygame.Rect"]) -> int:
    """How many pixels differ between the two games' last frames once every
    rect in ``rects`` is blanked on both: the change that happened where the
    thing under test is NOT supposed to draw."""
    a, b = _frame(subject).copy(), _frame(baseline).copy()
    for rect in rects:
        a.fill((0, 0, 0), rect)
        b.fill((0, 0, 0), rect)
    holder_a = type("Frame", (), {"last_frame": a})
    holder_b = type("Frame", (), {"last_frame": b})
    return changed_pixels(holder_a, holder_b)


def region_differs(subject, baseline, *, world=None, screen=None,
                   pad: float = 0.0, minimum: int = 1) -> bool:
    """True when the two frames differ inside the probe region.

    ``world=(x, y, w, h)`` is a rect in world tiles (converted with the
    subject's camera, which must match the baseline's); ``screen`` is a
    ``pygame.Rect``; neither = the whole frame. The two games must have run
    the same number of frames at the same dt, so the only difference left is
    the thing under test."""
    if subject.camera.center != baseline.camera.center:
        raise AssertionError("the probe games' cameras differ: "
                             f"{subject.camera.center} vs {baseline.camera.center}")
    rect = screen
    if world is not None:
        rect = world_rect(subject, *world, pad=pad)
    return changed_pixels(subject, baseline, rect) >= minimum


def frame_differs(subject, baseline, minimum: int = 1) -> bool:
    return region_differs(subject, baseline, minimum=minimum)


def pass_contributes(game, target, name: str, minimum: int = 1) -> bool:
    """Re-render the current state twice at the same clock reading, once
    with ``target.name`` replaced by a no-op, and report whether the frames
    differ. For a pass no with/without game pair can isolate (one that draws
    over a full-screen effect it shares a trigger with)."""
    had_own = name in vars(target)
    own = vars(target).get(name)
    with _running(game):
        game._render()
        drawn = game.screen.copy()
        setattr(target, name, lambda *args, **kwargs: None)
        try:
            game._render()
            suppressed = game.screen.copy()
        finally:
            if had_own:
                setattr(target, name, own)
            else:
                delattr(target, name)
    holder_a = type("Frame", (), {"last_frame": drawn})
    holder_b = type("Frame", (), {"last_frame": suppressed})
    return changed_pixels(holder_a, holder_b) >= minimum


def shutdown_games(games: Sequence["GameClient"]) -> None:
    """Shut down every game and close every game's server, whatever one of
    them raises: a ``shutdown`` that fails must not leave the others' servers
    (event loops, temp worlds) open. The first failure is re-raised once all
    are done. ``pygame.quit`` is neutralised for the duration: a test session
    shares one SDL, and shutdown() ends with that call."""
    real_quit = pygame.quit
    real_collect = gc.collect
    pygame.quit = lambda: None
    # shutdown() ends with a full collection (it frees font file handles for
    # a session that really quits); a test session has no handles to free and
    # pays ~18 ms for it per game.
    gc.collect = lambda *args, **kwargs: 0
    errors: List[BaseException] = []
    try:
        for game in games:
            try:
                game.shutdown(remember_window=False)
            except Exception as exc:
                errors.append(exc)
            finally:
                try:
                    game.server.close()
                except Exception as exc:
                    errors.append(exc)
    finally:
        pygame.quit = real_quit
        gc.collect = real_collect
    if errors:
        raise errors[0]


def key_event(key: int, unicode: str = "", mod: int = 0):
    return pygame.event.Event(pygame.KEYDOWN, key=key, unicode=unicode,
                              mod=mod, scancode=0)


def spy(monkeypatch, obj, name: str) -> List[Tuple[tuple, dict]]:
    """Wrap ``obj.name`` so every call is recorded as ``(args, kwargs)`` and
    still runs the real method. For tests on a real game that assert "the
    client was asked to send X" without replacing the client."""
    real = getattr(obj, name)
    calls: List[Tuple[tuple, dict]] = []

    def wrapper(*args, **kwargs):
        calls.append((args, kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(obj, name, wrapper)
    return calls


def stub_art(monkeypatch, game, sheets) -> None:
    """Make the game's art lookup answer ``sheets`` (``{name: Surface}``, or
    one Surface for every name), blank its screen, and record asset requests
    in ``game.requested`` instead of sending them. The renderer, camera and
    screen stay the game's own: only the pixels a test inspects are chosen by
    the test, so one pixel says which layer drew it."""
    def lookup(name, *part):
        return sheets if isinstance(sheets, pygame.Surface) else sheets.get(name)

    game.requested = []
    monkeypatch.setattr(game, "_request_asset", game.requested.append)
    monkeypatch.setattr(game.sprite_mgr, "load_sheet", lookup)
    monkeypatch.setattr(game.sprite_mgr, "get_sprite", lookup)
    game.screen.fill((0, 0, 0))


class BlitRecorder:
    """Stands in for a game's ``screen`` when a test asserts what was blitted
    where: ``blits`` lists ``(source, dest)`` and nothing is drawn, so the
    source may be any marker (a tile id) instead of a Surface. Every other
    attribute is the real surface's. Install with
    ``monkeypatch.setattr(game, "screen", BlitRecorder(game.screen))``."""

    def __init__(self, surface: "pygame.Surface") -> None:
        self._surface = surface
        self.blits: List[Tuple[Any, Any]] = []

    def blit(self, source, dest, *args, **kwargs):
        self.blits.append((source, dest))

    def __getattr__(self, name):
        return getattr(self._surface, name)
