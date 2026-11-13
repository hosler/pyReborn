"""Scripts that run while GameClient.__init__ is still building the game.

Every launcher builds the GameClient AFTER login (example_pygame, the
game_tester harnesses, the offline fixture), so on a v6 server the GS2
bytecode of every granted weapon is already waiting in
``client.gs2_bytecode`` when the game is built. ``ClientGS2.attach()`` loads
it and runs each weapon's top level and ``onCreated`` at once, through the
GS1 host callbacks, the GameShell members and anything a script's sleep()
or findweapon() pumps off the network. A script reaching a game attribute
that ``__init__`` has not assigned yet raises AttributeError (swallowed by
the engines: the script simply stops), and a value it sets can be reset by
a later line of ``__init__``.

The reference client never runs a weapon against a half-built client: a
delivered script is set only when the active player and the weapon object
exist (FourPlay quattroplay/src/TClient.cpp:2266), and it then runs at
once (TServerWeapon.cpp:20-31), so what it sets persists. So the runtime
attaches as the LAST step of ``__init__``.

Two tests pin it:

* ``test_no_script_runs_before_every_attribute_exists``: records ``vars(game)``
  at the first point during ``__init__`` where a script, a client callback or
  a listener can run, and requires every declared data attribute to exist
  there. Mutation: move ``self.gs2.attach()`` above any assignment in
  ``__init__`` (or move one assignment below it) and this test names the
  missing attributes.
* ``test_weapons_streamed_at_login_run_against_a_complete_game``: the
  offline fixture streams a GS1 and several GS2 weapons at login, before the
  GameClient exists (the ``weapons`` knob), and their load-time code uses
  the callback surface. Every assertion names the state a script asked for.
  On the tree before this fix it failed on: setani (game_shell unset during
  attach) and the #m that reads it back, the shot (neither sent nor handed
  back), the music request, putleaps, setlevel2, setfocus, freezeplayer,
  seteffect, the #c chat bubble and say2. Mutation: move
  ``self._current_music_name = None`` below ``self.gs2.attach()``; "play
  music" fails.
"""

import logging

import pytest

import pyreborn.gs1_client.registry as gs1_registry
from pyreborn.gs2_client import runtime as gs2_runtime
from pyreborn.pygame_game import GameClient

from .gs2_compiler import require_compiler
from .test_game_state_declared import CLASS_LEVEL, FIXTURE_EXTRAS, declared

#: Declared names that may still be missing when the first script-capable
#: hook runs, each with the reason no load-time path can read it. Empty: the
#: runtime attaches after every assignment. An entry here is a promise that
#: nothing a script can reach reads the name; do not add one to make the
#: test pass.
BUILT_AFTER_FIRST_HOOK = frozenset()


def _hooks(monkeypatch, seen):
    """Record vars(game) the first time anything that can run a script or a
    callback is entered while a GameClient is being built."""
    building = []

    real_init = GameClient.__init__

    def init(self, *args, **kwargs):
        building.append(self)
        try:
            real_init(self, *args, **kwargs)
        finally:
            building.pop()
    monkeypatch.setattr(GameClient, "__init__", init)

    def wrap(owner, name):
        real = getattr(owner, name)

        def recorder(*args, **kwargs):
            if building and not seen:
                seen.append((f"{owner.__name__}.{name}",
                             set(vars(building[-1]))))
            return real(*args, **kwargs)
        monkeypatch.setattr(owner, name, recorder)

    from pyreborn import Client
    from pyreborn.gs1_client import runtime as gs1_runtime
    # Script entry points (both engines), and the client's packet path a
    # script's sleep()/findweapon() pumps. Each is patched on the module
    # that owns the class (the package re-exports it by value).
    for name in ("attach", "pump_pending", "load_bytecode", "trigger_event"):
        wrap(gs2_runtime.ClientGS2, name)
    for name in ("load_weapon", "load_script", "trigger_event",
                 "trigger_npc_event"):
        wrap(gs1_runtime.ClientGS1, name)
    for name in ("update", "_handle_packet"):
        wrap(Client, name)


def test_no_script_runs_before_every_attribute_exists(make_game, monkeypatch):
    seen = []
    _hooks(monkeypatch, seen)
    game = make_game(start=False)
    assert seen, "no script-capable hook ran during GameClient.__init__"
    hook, present = seen[0]
    data = declared() - CLASS_LEVEL
    missing = data - present - BUILT_AFTER_FIRST_HOOK
    assert not missing, (
        f"{hook} ran inside GameClient.__init__ before these attributes "
        f"were assigned, so a load-time script that reaches them raises "
        f"AttributeError or has its state reset: {sorted(missing)}")
    stale = BUILT_AFTER_FIRST_HOOK & present
    assert not stale, ("exist when the first hook runs; delete them from "
                       f"BUILT_AFTER_FIRST_HOOK: {sorted(stale)}")
    assert not (set(vars(game)) - FIXTURE_EXTRAS) - declared()


def test_the_runtime_attaches_last():
    """The ordering the structural test measures, stated where it is read:
    ``self.gs2.attach()`` is the last statement of ``__init__``."""
    import ast
    import inspect
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(GameClient.__init__)))
    body = tree.body[0].body
    last = body[-1]
    assert (isinstance(last, ast.Expr) and isinstance(last.value, ast.Call)
            and ast.unparse(last.value.func) == "self.gs2.attach"), (
        "GameClient.__init__ must end with self.gs2.attach()")


# -- end to end -------------------------------------------------------------

# One action per GS2 weapon, so a script that stops on an error cannot hide
# the next one.
GS2_WEAPONS = {
    "-init_ani": 'function onCreated() { disabledefmovement(); '
                 'setani("sit", ""); }',
    "-init_shoot": 'function onCreated() { '
                   'shoot(player.x, player.y, 0, 0, 0, 0, "blank", "q"); }\n'
                   'function onActionProjectile2() { this.selfshot = 1; }',
    "-init_chat": 'function onCreated() { player.chat = "loaded"; }',
    "-init_say2": 'function onCreated() { say2("a sign at load"); }',
    "-init_music": 'function onCreated() { play("loadtrack.mid"); }',
    "-init_showimg": 'function onCreated() { '
                     'showimg(201, "pics1.png", 30, 30); }',
    "-init_leaps": 'function onCreated() { putleaps(1, 30, 30); }',
    "-init_focus": 'function onCreated() { setfocus(12, 14); }',
    "-init_freeze": 'function onCreated() { freezeplayer(30); }',
    "-init_tint": 'function onCreated() { seteffect(1, 0, 0, 0.5); }',
    "-init_timer": 'function onCreated() { setTimer(0.1); }\n'
                   'function onTimeout() { this.fired = 1; }',
}

# Runs at start() (GS1 weapons load there), after the GS2 ones: it reads the
# gani the GS2 weapon set while the game was being built.
GS1_WEAPON = ("-init_gs1", "if (created) { setstring client.loadani,#m; "
                           "timeout = 0.1; } "
                           "if (timeout) { setstring client.loadtimeout,yes; }")


def _build(make_game, *, warp):
    require_compiler()
    weapons = [{"name": n, "engine": "gs2", "script": s}
               for n, s in GS2_WEAPONS.items()]
    if warp:
        weapons.append({"name": "-init_warp", "engine": "gs2",
                        "script": 'function onCreated() { '
                                  'setlevel2("other.nw", 20, 21); }'})
    weapons.append({"name": GS1_WEAPON[0], "engine": "gs1",
                    "script": GS1_WEAPON[1]})
    return make_game(start=False, weapons=weapons,
                     extra_levels={"other.nw": None})


@pytest.fixture
def engine_errors(monkeypatch, caplog):
    """GS1 host errors are deduplicated process-wide; start this test with
    a fresh set so its own errors are reported."""
    monkeypatch.setattr(gs1_registry, "_GS1_ERR_SEEN", set())
    caplog.set_level(logging.WARNING)
    return lambda: [r.getMessage() for r in caplog.records
                    if "Error" in r.getMessage()]


def test_weapons_streamed_at_login_run_against_a_complete_game(
        make_game, engine_errors):
    from pyreborn.packets import PacketID
    game = _build(make_game, warp=False)
    vms = game.gs2.vms["weapon"]
    assert set(vms) >= {n.lower() for n in GS2_WEAPONS}, (
        "the GS2 weapons did not arrive at login")
    leaps_at_init = list(game.particles.leaps)
    ani_at_init = game.current_anim_name

    game.start()
    game.frames(12)

    client_scope = game.gs1._shared["client"]
    sent = {pid for pid, _ in game.client._protocol.sent}
    layers = [t for k, t in game.gs1._weapon_imgs.items()
              if "init_showimg" in k]
    # Every expectation is checked, so one run names every script that lost
    # its effect. Label: the script call whose result is missing.
    expected = {
        # setani after disabledefmovement drives the drawn player (read
        # before the frames: the synthetic sit gani is not looped, and a
        # GS2 setani does not hold a finished gani the way GS1's does)
        "setani": ani_at_init == "sit",
        # GS1 #m, read at start(), sees the gani set at load
        "#m after setani": client_scope.get("loadani") == "sit",
        "GS1 timeout": client_scope.get("loadtimeout") == "yes",
        # shoot: sent to the server and handed back to the shooter
        "shoot sent": bool(sent & {int(PacketID.PLI_SHOOT),
                                   int(PacketID.PLI_SHOOT2)}),
        "own shot -> onActionProjectile2":
            vms["-init_shoot"].this.get("selfshot") == 1,
        # player.chat -> setplayerprop #c -> the local bubble
        "player.chat": (game.local_chat_text == "loaded"
                        and game.local_chat_time is not None),
        "say2": "sign at load" in str(game.dialogue_text or ""),
        # play of a track we do not have: remembered for its download
        "play music": game._current_music_name == "loadtrack.mid",
        "showimg": bool(layers) and 201 in layers[0],
        "putleaps": bool(leaps_at_init),
        "setfocus": game._camera_focus == (12.0, 14.0),
        "freezeplayer": game._frozen_until - game.clock.sim_now() > 20,
        "seteffect": game.screen_tint == {"r": 255, "g": 0, "b": 0, "a": 127},
        "setTimer": vms["-init_timer"].this.get("fired") == 1,
    }
    lost = sorted(label for label, ok in expected.items() if not ok)
    assert not lost, f"load-time script effects missing: {lost}"
    assert game.frame_errors == {}
    assert engine_errors() == []


def test_a_warp_requested_at_load_is_performed(make_game, engine_errors):
    game = _build(make_game, warp=True)
    game.start()
    game.frames(30)
    assert game.client.current_level_name == "other.nw", "setlevel2 at load"
    assert (game.client.x, game.client.y) == (20.0, 21.0)
    assert game.frame_errors == {}
    assert engine_errors() == []
