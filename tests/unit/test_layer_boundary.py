"""The library layer must not depend on the game layer.

LIB is everything under pyreborn/ except the GAME files below. Rules:
  * importing LIB never loads pygame or pyreborn.game*;
  * no LIB module has a top-level import of GAME or pygame (function-level
    imports are lazy and allowed), except the pygame-backed modules listed in
    PYGAME_LIB_ALLOWLIST;
  * GS2 code reads its host only through the GameShell protocol;
  * GAME reaches the library only through public names.
"""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PKG = REPO / "pyreborn"
GAME_FILES = {"pygame_game.py", "pygame_screens.py", "inventory_ui.py",
              "example_pygame.py"}

#: LIB modules that are pygame-backed by nature. Only GAME may import them.
PYGAME_LIB_ALLOWLIST = {
    "sprites.py": "SpriteManager/TilesetManager decode surfaces",
    "sounds.py": "SoundManager drives pygame.mixer",
    "mng.py": "decodes MNG frames into pygame surfaces",
}

#: Deliberate private reaches from GAME into LIB: (file, attribute) -> reason.
PRIVATE_REACH_ALLOWLIST = {}


def _is_game(rel: Path) -> bool:
    return rel.parts[0] == "game" or str(rel) in GAME_FILES


def _py_files(game: bool):
    for path in sorted(PKG.rglob("*.py")):
        rel = path.relative_to(PKG)
        if "__pycache__" in rel.parts:
            continue
        if _is_game(rel) == game:
            yield rel, path


def _top_level_imports(tree):
    """Import nodes executed at import time (module body, through try/if/with,
    not inside def or class bodies)."""
    stack = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            continue
        else:
            for field in ("body", "orelse", "finalbody", "handlers"):
                stack.extend(getattr(node, field, []) or [])


def _targets(node, rel: Path):
    """Absolute dotted module names an import node pulls in."""
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    base = node.module or ""
    if node.level:
        pkg_parts = ["pyreborn"] + list(rel.parts[:-1])
        keep = len(pkg_parts) - (node.level - 1)
        prefix = ".".join(pkg_parts[:keep])
        base = prefix + ("." + base if base else "")
    names = [base]
    names += [base + "." + a.name for a in node.names]
    return names


def _is_game_module(name: str) -> bool:
    return (name == "pygame" or name.startswith("pygame.")
            or name == "pyreborn.game" or name.startswith("pyreborn.game.")
            or name in ("pyreborn.pygame_game", "pyreborn.pygame_screens",
                        "pyreborn.inventory_ui", "pyreborn.example_pygame"))


def test_importing_the_library_loads_neither_pygame_nor_game():
    modules = [
        "pyreborn", "pyreborn.client", "pyreborn.gs1_client",
        "pyreborn.gs2_client", "pyreborn.handlers", "pyreborn.packet_codec",
        "pyreborn.rc_client", "pyreborn.nc_client", "pyreborn.rc_link",
        "pyreborn.nc_link", "pyreborn.listserver", "pyreborn.gani",
        "pyreborn.particles", "pyreborn.asset_paths", "pyreborn.palette",
        "pyreborn.constants",
    ]
    code = (
        "import sys\n"
        + "".join("import %s\n" % m for m in modules)
        + "bad = sorted(m for m in sys.modules if m == 'pygame' or "
          "m.startswith('pygame.') or m == 'pyreborn.game' or "
          "m.startswith('pyreborn.game.'))\n"
          "print(','.join(bad))\n"
    )
    result = subprocess.run(
        [sys.executable, "-W", "ignore", "-c", code], cwd=str(REPO),
        capture_output=True, text=True, timeout=120,
        env=dict(os.environ, PYTHONPATH=str(REPO)))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "", "loaded: " + result.stdout


def test_creating_a_gs2_runtime_still_resolves_the_gui_layer():
    from pyreborn.gs2_client import ClientGS2, GuiControl, GS2GuiManager
    rt2 = ClientGS2()
    assert isinstance(rt2.gui, GS2GuiManager)
    assert GuiControl is not None


def test_no_lib_module_imports_game_or_pygame_at_top_level():
    offenders = []
    for rel, path in _py_files(game=False):
        if str(rel) in PYGAME_LIB_ALLOWLIST:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in _top_level_imports(tree):
            for name in _targets(node, rel):
                if _is_game_module(name):
                    offenders.append("%s:%d imports %s" % (rel, node.lineno, name))
                elif name in ("pyreborn." + a[:-3] for a in PYGAME_LIB_ALLOWLIST):
                    offenders.append("%s:%d imports pygame-backed %s"
                                     % (rel, node.lineno, name))
    assert not offenders, "\n".join(offenders)


def test_pygame_allowlist_is_not_stale():
    for name in PYGAME_LIB_ALLOWLIST:
        tree = ast.parse((PKG / name).read_text(encoding="utf-8"))
        assert any(_is_game_module(t) for n in _top_level_imports(tree)
                   for t in _targets(n, Path(name))), (
            "%s no longer imports pygame at top level; drop it from "
            "PYGAME_LIB_ALLOWLIST" % name)


# -- GameShell ---------------------------------------------------------------

def _is_game_expr(node):
    if isinstance(node, ast.Name):
        return node.id == "game"
    if isinstance(node, ast.Attribute):
        return node.attr == "game_shell"
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "getattr" and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)):
        return node.args[1].value == "game_shell"
    return False


def _game_shell_reads():
    """Every member name gs2_client reads off its host, with location."""
    reads = []
    for path in sorted((PKG / "gs2_client").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and _is_game_expr(node.value):
                reads.append((path.name, node.lineno, node.attr))
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and node.func.id in ("getattr", "hasattr", "setattr")
                  and len(node.args) >= 2 and _is_game_expr(node.args[0])
                  and isinstance(node.args[1], ast.Constant)):
                reads.append((path.name, node.lineno, node.args[1].value))
    return reads


def test_gs2_client_reads_game_shell_only_through_protocol_members():
    from pyreborn.gs2_client.game_shell import GameShell
    members = set(GameShell.__annotations__) | {
        n for n in vars(GameShell) if not n.startswith("_")}
    reads = _game_shell_reads()
    assert reads, "scan found no game_shell reads; the test is broken"
    private = [r for r in reads if r[2].startswith("_")]
    assert not private, private
    outside = [r for r in reads if r[2] not in members]
    assert not outside, outside
    # no speculative members: each is read somewhere
    unused = members - {r[2] for r in reads}
    assert not unused, unused


def test_game_client_satisfies_the_game_shell_protocol(monkeypatch, tmp_path):
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from pyreborn import Client
    from pyreborn.gs2_client.game_shell import GameShell
    from pyreborn.pygame_game import GameClient
    game = GameClient(Client("127.0.0.1", 14900, version="6.037"))
    try:
        assert isinstance(game, GameShell)
        assert game.gs2.game_shell is game
        game.day_night_enabled = True
        assert game._day_night_enabled is True
        game.camera_enabled = True
        assert game._camera_enabled is True
    finally:
        game.shutdown(remember_window=False)


# -- GAME -> LIB private reaches ----------------------------------------------

def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return list(reversed(parts))
    return None


def _private(name):
    return name.startswith("_") and not name.startswith("__")


def _lib_handles(chain):
    return bool(chain) and chain[-1] in ("client", "gs1", "gs2")


def test_game_layer_uses_no_private_library_members():
    offenders = []
    for rel, path in _py_files(game=True):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            attr = None
            if isinstance(node, ast.Attribute) and _private(node.attr):
                if _lib_handles(_dotted(node.value)):
                    attr = node.attr
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and node.func.id in ("getattr", "hasattr", "setattr")
                  and len(node.args) >= 2
                  and isinstance(node.args[1], ast.Constant)
                  and isinstance(node.args[1].value, str)
                  and _private(node.args[1].value)
                  and _lib_handles(_dotted(node.args[0]))):
                attr = node.args[1].value
            if attr and (str(rel), attr) not in PRIVATE_REACH_ALLOWLIST:
                offenders.append("%s:%d %s" % (rel, node.lineno, attr))
    assert not offenders, "\n".join(offenders)


def test_public_names_delegate_to_the_private_ones():
    from pyreborn import Client
    from pyreborn.gs1_client import ClientGS1
    client = Client("127.0.0.1", 14900, version="6.037")
    client._current_level_name = "a.nw"
    assert client.current_level_name == "a.nw"
    client.current_level_name = "b.nw"
    assert client._current_level_name == "b.nw"
    assert Client.ARROW_SPEED == Client._ARROW_SPEED
    assert Client.bomb_half_tile(1.0, 1.0) == Client._bomb_half_tile(1.0, 1.0)
    client._local_level_transition = "c.nw"
    client._local_level_transition_direction = 2
    client.clear_local_transition_direction()
    assert client.local_level_transition_direction is None
    client.release_local_transition()
    assert client.local_level_transition == ""
    gs1 = ClientGS1(None)
    assert gs1.shape1_npcs is gs1._shape1_npcs
    assert gs1.weapon_imgs is gs1._weapon_imgs
    assert gs1.has_program("weapon_x") is False
