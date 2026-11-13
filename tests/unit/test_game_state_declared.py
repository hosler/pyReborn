"""Every attribute a GameClient has is declared once, in game/host.py.

``GameHost`` annotates the whole catalogue. This file enforces it in three
parts, and two allowlists that may only shrink:

1. Static. An AST walk over the game layer (``pyreborn/game/**``,
   ``pygame_game.py`` and the four library modules that take the game as an
   argument). Every store to a game attribute (``self.x = ...`` inside a class
   of the GameClient MRO; ``game.x`` / ``g.x`` / ``self.game.x`` elsewhere)
   must name an annotation or a method/property. Every
   ``getattr(<game>, 'x', default)`` / ``hasattr(<game>, 'x')`` on a declared
   name must be listed in ``ALLOWED_GUARDS``; the list must match the tree
   exactly, so removing a guard forces the entry out too.
2. Dynamic. A real offline game is built, then driven through start, frames,
   chat, overlay keys, a push and two warps. Every attribute it gains after
   ``__init__`` must be in ``LAZY_ALLOWED`` (or ``CLASS_LEVEL``).
3. Catalogue equality. The annotations equal ``vars(game)`` after ``__init__``
   plus ``LAZY_ALLOWED`` and ``CLASS_LEVEL``.

Allowlists. They start as the measured lists and only shrink:

* a cluster step that makes ``__init__`` assign a lazy attribute deletes its
  name from ``LAZY_ALLOWED`` (the test fails on a name that is already in
  ``vars(game)``), and lowers ``LAZY_CEILING`` to the new length;
* a step that removes a guard lowers its ``ALLOWED_GUARDS`` count (or deletes
  the entry), and lowers ``GUARD_CEILING`` to the new sum;
* raising a ceiling to bless a new lazy attribute or a new guard is the thing
  this test exists to make visible: do not.
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

# -- allowlists (only shrink) ----------------------------------------------------

#: Declared names ``__init__`` does not assign. Each is created later by a
#: store (a lazy cache, a lazy UI, a ``start()``-time value, a ``__dict__``
#: write). An entry whose name is in ``vars(game)`` after ``__init__`` fails.
LAZY_ALLOWED = frozenset()

#: Declared names that exist only as a class-level default on the mixins. An
#: entry that is no longer a class attribute, or that ``__init__`` now sets,
#: fails.
CLASS_LEVEL = frozenset({
    "_vk_cache",
    "fullscreen",
})

#: (file relative to pyreborn/, name) -> number of guard sites. A guard is
#: ``getattr(<game>, 'name', default)`` or ``hasattr(<game>, 'name')`` on a
#: declared attribute.
ALLOWED_GUARDS = {
    ("game/actions.py", "_footstep_tick"): 1,
    ("game/actions.py", "_frozen_until"): 2,
    ("game/actions.py", "_giveaway_item"): 2,
    ("game/actions.py", "_ground_ticks"): 1,
    ("game/actions.py", "_ledge_jump"): 4,
    ("game/actions.py", "_sign_contact_key"): 1,
    ("game/actions.py", "_sleep_level"): 1,
    ("game/actions.py", "_sleep_was_moving"): 1,
    ("game/actions.py", "_step_parity"): 1,
    ("game/actions.py", "_swim_in_lava"): 1,
    ("game/actions.py", "active_bombs"): 1,
    ("game/actions.py", "gs1"): 6,
    ("game/actions.py", "is_swimming"): 1,
    ("game/actions.py", "npc_handler"): 1,
    ("game/actions.py", "sprite_mgr"): 1,
    ("game/callbacks/client_callbacks.py", "_ledge_jump"): 1,
    ("game/callbacks/client_callbacks.py", "_pending_music"): 1,
    ("game/callbacks/client_callbacks.py", "gs1"): 7,
    ("game/callbacks/client_callbacks.py", "gs2"): 3,
    ("game/callbacks/client_callbacks.py", "player_anim"): 1,
    ("game/callbacks/gs1_callbacks.py", "_pending_self_shoots"): 1,
    ("game/callbacks/gs1_callbacks.py", "current_anim_name"): 1,
    ("game/callbacks/gs1_callbacks.py", "gs1"): 1,
    ("game/callbacks/gs1_callbacks.py", "gs2"): 1,
    ("game/callbacks/gs1_callbacks.py", "npc_handler"): 1,
    ("game/callbacks/gs1_callbacks.py", "sprite_mgr"): 1,
    ("game/collision.py", "active_bombs"): 1,
    ("game/collision.py", "gs1"): 2,
    ("game/collision.py", "noclip"): 1,
    ("game/dev_ui.py", "rc_password"): 1,
    ("game/dev_ui.py", "rc_ui"): 1,
    ("game/editor/editor.py", "dev_ui"): 1,
    ("game/editor/editor.py", "rc_ui"): 1,
    ("game/flying.py", "gs1"): 1,
    ("game/flying.py", "gs2"): 1,
    ("game/flying.py", "npc_handler"): 1,
    ("game/frame_context.py", "_frame_ctx"): 1,
    ("game/frame_context.py", "_frame_dt"): 2,
    ("game/hud.py", "combat_presentation"): 1,
    ("game/hud.py", "dialogue_classic_font"): 2,
    ("game/hud.py", "gs1"): 1,
    ("game/hud.py", "noclip"): 1,
    ("game/hud.py", "sprite_mgr"): 1,
    ("game/input.py", "_death_started"): 1,
    ("game/input.py", "_frozen_until"): 1,
    ("game/input.py", "_giveaway_item"): 1,
    ("game/input.py", "_latch_context"): 2,
    ("game/input.py", "_ledge_jump"): 1,
    ("game/input.py", "_mouse_left_latched"): 1,
    ("game/input.py", "current_anim_name"): 1,
    ("game/input.py", "dev_ui"): 1,
    ("game/input.py", "gs1"): 3,
    ("game/input.py", "gs2"): 1,
    ("game/input.py", "key_just_pressed"): 2,
    ("game/input.py", "level_editor"): 1,
    ("game/input.py", "rc_ui"): 1,
    ("game/input.py", "servers"): 1,
    ("game/input.py", "settings_ui"): 1,
    ("game/overlays.py", "big_map_visible"): 1,
    ("game/overlays.py", "debug_mode"): 1,
    ("game/overlays.py", "dialogue_text"): 1,
    ("game/overlays.py", "editor_overlay"): 1,
    ("game/overlays.py", "gs2"): 1,
    ("game/overlays.py", "hud"): 1,
    ("game/overlays.py", "hud_notice"): 2,
    ("game/overlays.py", "inventory_ui"): 1,
    ("game/overlays.py", "level_editor"): 1,
    ("game/overlays.py", "server_warp_prompt"): 1,
    ("game/overlays.py", "show_help"): 1,
    ("game/overlays.py", "show_player_list"): 1,
    ("game/overlays.py", "show_server_list"): 1,
    ("game/rc_ui.py", "rc_password"): 1,
    ("game/render.py", "_camera_focus"): 1,
    ("game/render.py", "_camera_shake_started"): 1,
    ("game/render.py", "_ledge_jump"): 4,
    ("game/render.py", "_scripted_player_ani"): 1,
    ("game/render.py", "_swim_in_lava"): 1,
    ("game/render.py", "combat_presentation"): 1,
    ("game/render.py", "gs1"): 2,
    ("game/render.py", "interpolator"): 1,
    ("game/render_collect.py", "_npc_visual_epoch"): 1,
    ("game/render_collect.py", "gs1"): 2,
    ("game/render_collect.py", "interpolator"): 1,
    ("game/render_effects.py", "_camera_shake_started"): 1,
    ("game/render_effects.py", "_day_night_enabled"): 1,
    ("game/render_effects.py", "interpolator"): 1,
    ("game/render_effects.py", "thrown_objects"): 1,
    ("game/render_entities.py", "_giveaway_item"): 1,
    ("game/render_entities.py", "_step_parity"): 1,
    ("game/render_entities.py", "_swamp_pos"): 1,
    ("game/render_entities.py", "camera"): 3,
    ("game/render_entities.py", "local_chat_time"): 1,
    ("game/render_entities.py", "player_anim"): 1,
    ("game/render_layers.py", "_frame_dt"): 2,
    ("game/render_layers.py", "client"): 1,
    ("game/render_layers.py", "gs1"): 1,
    ("game/render_objects.py", "_chest_reveal_snapshots"): 1,
    ("game/render_objects.py", "_chest_reveals"): 2,
    ("game/render_objects.py", "dialogue_text"): 1,
    ("game/render_objects.py", "sprite_mgr"): 1,
    ("game/settings_ui.py", "_day_night_enabled"): 2,
    ("game/settings_ui.py", "_low_hearts_warning_enabled"): 2,
    ("game/setup.py", "_current_music_name"): 1,
    ("game/setup.py", "_gs2_shape1_npcs"): 1,
    ("game/setup.py", "_low_hearts_next_beep"): 1,
    ("game/setup.py", "_low_hearts_warning_enabled"): 1,
    ("game/setup.py", "_pending_self_shoots"): 1,
    ("game/setup.py", "gs2"): 2,
    ("game/setup.py", "interpolator"): 2,
    ("game/setup.py", "npc_handler"): 1,
    ("pygame_game.py", "_camera_enabled"): 1,
    ("pygame_game.py", "_day_night_enabled"): 1,
    ("pygame_game.py", "_dbg"): 1,
    ("pygame_game.py", "_was_dead"): 1,
    ("pygame_game.py", "gs1"): 1,
    ("pygame_game.py", "hud"): 1,
    ("pygame_game.py", "inventory_ui"): 2,
    ("pygame_game.py", "is_moving"): 1,
    ("pygame_game.py", "npc_handler"): 1,
    ("pygame_game.py", "sound_mgr"): 1,
    ("throwing.py", "gs1"): 1,
    ("throwing.py", "gs2"): 1,
}

LAZY_CEILING = 0
GUARD_CEILING = 162


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


def test_guards_on_declared_names_are_allowlisted():
    measured = measured_guards()
    new = {k: n for k, n in measured.items() if n > ALLOWED_GUARDS.get(k, 0)}
    assert not new, (
        "new getattr/hasattr guard on a declared attribute (assign it in "
        "__init__ and read it directly instead): "
        + "; ".join("%s %r x%d" % (k[0], k[1], n) for k, n in sorted(new.items())))


def test_guard_allowlist_has_no_stale_entries():
    measured = measured_guards()
    stale = {k: n for k, n in ALLOWED_GUARDS.items()
             if measured.get(k, 0) < n}
    assert not stale, (
        "ALLOWED_GUARDS lists guards that no longer exist: lower the count "
        "or delete the entry, then lower GUARD_CEILING: "
        + "; ".join("%s %r allows %d, tree has %d"
                    % (k[0], k[1], n, measured.get(k, 0))
                    for k, n in sorted(stale.items())))


def test_guard_allowlist_only_shrinks():
    assert sum(ALLOWED_GUARDS.values()) == GUARD_CEILING, (
        "GUARD_CEILING must equal the sum of ALLOWED_GUARDS, and a step only "
        "ever lowers both")


def test_allowlisted_guard_names_are_declared():
    unknown = {name for _, name in ALLOWED_GUARDS} - declared()
    assert not unknown, "ALLOWED_GUARDS names not in GameHost: %s" % sorted(unknown)


# -- part 3 first: it needs only an unstarted game ------------------------------------

@pytest.fixture
def unstarted(make_game):
    return make_game(start=False)


def _init_names(game):
    return set(vars(game)) - FIXTURE_EXTRAS


def test_annotations_equal_init_attributes_plus_allowlists(unstarted):
    init = _init_names(unstarted)
    names = declared()
    assert names == init | LAZY_ALLOWED | CLASS_LEVEL, (
        "undeclared (set in __init__, not annotated): %s; "
        "declared but absent after __init__ (annotated, not assigned, not "
        "in LAZY_ALLOWED/CLASS_LEVEL): %s"
        % (sorted(init - names),
           sorted(names - init - LAZY_ALLOWED - CLASS_LEVEL)))


def test_lazy_allowlist_has_no_stale_entries(unstarted):
    init = _init_names(unstarted)
    assert not LAZY_ALLOWED & init, (
        "now assigned in __init__, delete from LAZY_ALLOWED (and lower "
        "LAZY_CEILING): %s" % sorted(LAZY_ALLOWED & init))
    assert not LAZY_ALLOWED - declared(), (
        "LAZY_ALLOWED names not annotated: %s"
        % sorted(LAZY_ALLOWED - declared()))
    assert len(LAZY_ALLOWED) <= LAZY_CEILING
    assert len(LAZY_ALLOWED) == LAZY_CEILING, (
        "lower LAZY_CEILING to len(LAZY_ALLOWED)")


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


def test_a_driven_game_gains_only_allowlisted_attributes(make_game):
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
    stray = gained - LAZY_ALLOWED - CLASS_LEVEL
    assert not stray, (
        "attributes created after __init__ that are neither assigned in "
        "__init__ nor in LAZY_ALLOWED: %s" % sorted(stray))
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
