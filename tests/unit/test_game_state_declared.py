"""Every attribute a GameClient has is declared once, in game/host.py.

``GameHost`` annotates the whole catalogue. This file enforces it, strictly:

1. Static. An AST walk over the game layer (``pyreborn/game/**``,
   ``pygame_game.py`` and the four library modules that take the game as an
   argument). Every store to a game attribute (``self.x = ...`` inside a class
   of the GameClient MRO; ``game.x`` / ``g.x`` / ``self.game.x`` elsewhere)
   must name an annotation or a method/property. There is no
   ``getattr(<game>, 'x', default)`` / ``hasattr(<game>, 'x')`` on a declared
   name anywhere: read it directly.
2. Dynamic. A real offline game is built, then driven through start, frames,
   chat, overlay keys, a push and two warps. It gains no attribute after
   ``__init__`` (``CLASS_LEVEL`` names, which exist on the class from the
   start, are the only exception).
3. Catalogue equality. The annotations equal ``vars(game)`` after ``__init__``
   plus ``CLASS_LEVEL``.

There is no allowlist for guards or lazy attributes. A test double that lacks
an attribute is fixed by building the real game with ``make_game``
(tests/offline_game.py), not by adding a guard to the game layer. A cache that
fills on first use is assigned empty in ``__init__``.
"""

import ast
import inspect
from collections import Counter
from pathlib import Path

import pygame
import pytest

from offline_game import key_event
from pyreborn.game.host import GameHost
from pyreborn.pygame_game import GameClient

PKG = Path(__file__).resolve().parents[2] / "pyreborn"

#: What the offline fixture adds to a game; not part of GameClient.
FIXTURE_EXTRAS = {"_fixture_clock", "_fixture_rng", "server", "feed",
                  "last_frame", "frames", "ticks"}

#: Library modules that take the game as ``game`` (the rest of pyreborn/ is
#: the library layer and reads its host through the GameShell protocol).
LIB_GAME_USERS = ("sword.py", "throwing.py", "carrying.py", "pausing.py")

#: Declared names that exist only as a class-level default on the mixins. An
#: entry that is no longer a class attribute, or that ``__init__`` now sets,
#: fails.
CLASS_LEVEL = frozenset({
    "_vk_cache",
    "fullscreen",
})


# -- the static walk ---------------------------------------------------------------

def _mro_classes():
    """{module file: set of class names} for the GameClient MRO."""
    classes = {}
    for cls in GameClient.__mro__:
        if cls in (object, GameHost):
            continue
        classes.setdefault(Path(inspect.getsourcefile(cls)), set()).add(
            cls.__name__)
    return classes


def _scanned_files():
    files = sorted((PKG / "game").rglob("*.py"))
    files.append(PKG / "pygame_game.py")
    files.extend(PKG / name for name in LIB_GAME_USERS)
    return files


class _Walker(ast.NodeVisitor):
    def __init__(self, rel, mro_names):
        self.rel = rel
        self.mro_names = mro_names
        self.in_mro = [False]
        self.stores = []        # (name, receiver, lineno)
        self.guards = []        # (name, receiver, lineno)

    def _receiver(self, node):
        if isinstance(node, ast.Name):
            if node.id in ("game", "g"):
                return node.id
            if node.id == "self" and self.in_mro[-1]:
                return "self"
        elif (isinstance(node, ast.Attribute) and node.attr == "game"
              and isinstance(node.value, ast.Name)
              and node.value.id == "self" and not self.in_mro[-1]):
            return "self.game"
        return None

    def visit_ClassDef(self, node):
        self.in_mro.append(node.name in self.mro_names)
        self.generic_visit(node)
        self.in_mro.pop()

    def _target(self, target, lineno):
        if isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._target(elt, lineno)
        elif isinstance(target, ast.Starred):
            self._target(target.value, lineno)
        elif isinstance(target, ast.Attribute):
            receiver = self._receiver(target.value)
            if receiver:
                self.stores.append((target.attr, receiver, lineno))

    def visit_Assign(self, node):
        for target in node.targets:
            self._target(target, node.lineno)
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        self._target(node.target, node.lineno)
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        self._target(node.target, node.lineno)
        self.generic_visit(node)

    def visit_For(self, node):
        self._target(node.target, node.lineno)
        self.generic_visit(node)

    def visit_Call(self, node):
        func = node.func
        if (isinstance(func, ast.Name) and func.id in ("getattr", "hasattr")
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
                and (func.id == "hasattr" or len(node.args) >= 3)):
            receiver = self._receiver(node.args[0])
            if receiver:
                self.guards.append((node.args[1].value, receiver, node.lineno))
        self.generic_visit(node)


def _walk_tree():
    mro = _mro_classes()
    stores, guards = [], []
    for path in _scanned_files():
        rel = path.relative_to(PKG).as_posix()
        walker = _Walker(rel, mro.get(path, set()))
        walker.visit(ast.parse(path.read_text()))
        stores += [(rel,) + s for s in walker.stores]
        guards += [(rel,) + g for g in walker.guards]
    return stores, guards


def declared():
    """Every annotated name over the MRO."""
    names = set()
    for cls in GameClient.__mro__:
        names |= set(inspect.get_annotations(cls))
    return names


def _is_method_or_property(name):
    attr = inspect.getattr_static(GameClient, name, None)
    return attr is not None and (
        isinstance(attr, (property, staticmethod, classmethod))
        or inspect.isfunction(attr))


def measured_guards(names=None):
    names = declared() if names is None else names
    _, guards = _walk_tree()
    return Counter((rel, name) for rel, name, _, _ in guards if name in names)


# -- part 1: static ------------------------------------------------------------------

def test_every_store_names_a_declared_attribute():
    names = declared()
    stores, _ = _walk_tree()
    undeclared = sorted({(name, rel, line) for rel, name, _, line in stores
                         if name not in names
                         and not _is_method_or_property(name)})
    assert not undeclared, (
        "attribute stored on the game but not annotated in game/host.py "
        "GameHost (add it there, and to GameClient.__init__): "
        + "; ".join("%s at %s:%d" % u for u in undeclared))


def test_no_getattr_or_hasattr_guard_on_a_declared_attribute():
    measured = measured_guards()
    assert not measured, (
        "getattr/hasattr guard on a declared game attribute: read it "
        "directly. If a test double lacks it, build the real game with "
        "make_game (tests/offline_game.py) instead of guarding in the game "
        "layer; if it may be absent, assign it (None, empty) in "
        "GameClient.__init__. Found: "
        + "; ".join("%s %r x%d" % (k[0], k[1], n)
                    for k, n in sorted(measured.items())))


# -- part 3 first: it needs only an unstarted game ------------------------------------

@pytest.fixture
def unstarted(make_game):
    return make_game(start=False)


def _init_names(game):
    return set(vars(game)) - FIXTURE_EXTRAS


def test_annotations_equal_init_attributes_plus_class_level(unstarted):
    init = _init_names(unstarted)
    names = declared()
    assert names == init | CLASS_LEVEL, (
        "undeclared (set in __init__, not annotated in game/host.py): %s; "
        "declared but absent after __init__ (assign it in "
        "GameClient.__init__, None or empty if it fills later): %s"
        % (sorted(init - names), sorted(names - init - CLASS_LEVEL)))


def test_class_level_allowlist_has_no_stale_entries(unstarted):
    init = _init_names(unstarted)
    assert not CLASS_LEVEL & init, (
        "now assigned in __init__, delete from CLASS_LEVEL: %s"
        % sorted(CLASS_LEVEL & init))
    gone = {n for n in CLASS_LEVEL if not hasattr(GameClient, n)}
    assert not gone, "no longer a class attribute: %s" % sorted(gone)
    assert not CLASS_LEVEL - declared()


def test_annotations_are_data_not_methods():
    clash = sorted(n for n in declared() if _is_method_or_property(n))
    assert not clash, "annotated names that are methods/properties: %s" % clash


# -- part 2: dynamic ------------------------------------------------------------------

def _flat(tile):
    return lambda tx, ty: tile


def test_a_driven_game_gains_no_attribute(make_game):
    from pyreborn.tiletypes import is_blocking
    wall = next(t for t in range(4096) if is_blocking(t))

    def tiles(tx, ty):
        return wall if ty == 20 and 20 <= tx < 45 else 0

    game = make_game(start=False, player_xy=(30.0, 19.5), tiles=tiles,
                     extra_levels={"other.nw": _flat(3)})
    declared_at_init = set(vars(game))
    game.start()
    game.frames(30)

    # chat: open, type, send
    game.frames(1, events=[key_event(pygame.K_RETURN, "\r")])
    for ch in "hi":
        game.frames(1, events=[key_event(ord(ch), ch)])
    game.frames(1, events=[key_event(pygame.K_RETURN, "\r")])
    # F7 and F8 overlays, the map, and back out
    for key in (pygame.K_F7, pygame.K_ESCAPE, pygame.K_F8, pygame.K_ESCAPE,
                pygame.K_m, pygame.K_m):
        game.frames(1, events=[key_event(key)])
    # a push into the wall
    game.client.player.direction = 0
    game._update_push_hold(0, -1)
    game.frames(5)

    async def warp(world, level, x, y):
        await world.me.warp(level, x, y)
    game.server.run(lambda w: warp(w, "other.nw", 20.0, 20.0))
    game.frames(5)
    game.server.run(lambda w: warp(w, "fixture.nw", 30.0, 30.0))
    game.frames(5)

    gained = set(vars(game)) - declared_at_init - FIXTURE_EXTRAS
    stray = gained - CLASS_LEVEL
    assert not stray, (
        "attributes first assigned after __init__ (a lazily created "
        "attribute): assign them in GameClient.__init__, None or empty "
        "until used: %s" % sorted(stray))
    assert gained <= declared(), (
        "created but not annotated: %s" % sorted(gained - declared()))
    assert game.frame_errors == {}


# -- the base class itself --------------------------------------------------------------

def test_game_host_sits_just_before_object_and_changes_no_order():
    names = [c.__name__ for c in GameClient.__mro__]
    assert names == [
        "GameClient", "SetupMixin", "MinimapMixin", "CollisionMixin",
        "InputMixin", "ActionsMixin", "RenderMixin", "WorldRenderMixin",
        "EntityRenderMixin", "EntityCollectMixin", "EffectsRenderMixin",
        "LevelObjectsRenderMixin", "ClockedMixin", "RenderTextMixin",
        "LayerRenderMixin", "GaniRenderMixin", "FlyingObjectsMixin",
        "FrameContextMixin", "GameHost", "object"]


def test_game_host_declares_no_runtime_attribute():
    """Annotations only: a bare annotation must not create a class attribute,
    or hasattr/getattr on the game would change behaviour."""
    own = {k for k in vars(GameHost) if not k.startswith("__")}
    assert own == set(), sorted(own)
