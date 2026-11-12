"""Frames of everything that moves under the simulation: a flying arrow, a
script-fired flying object, thrown objects, a bomb through its fuse into its
blast, a server explosion, and a level change with those in flight.

Each scene captures frames several ticks apart (``capture``), so the frame
baseline tool pins the exact pixels where an object is at each moment: a
refactor that moves the simulation out of the draw, or changes the clock it
reads, must leave every one identical. The asserts are independent of the
baseline: an object really moves, lands, or explodes between the frames.
"""
import offline_game
from frame_baseline import capture
from offline_game import _running
from pygserver.protocol.packets import build_explosion
from pyreborn.throwing import make_throw

DT = 0.05            # one 20 Hz tick per frame
BUSH = (4, 5, 6, 7)  # tile ids of a thrown 2x2 pattern


def _flat(tile):
    return lambda tx, ty: tile


def _positions(game, key):
    return [(round(p["x"], 3), round(p["y"], 3)) for p in getattr(game, key)]


def test_arrow_in_flight(make_game):
    game = make_game(arrows=[(26.0, 40.0, 1)])
    game.frames(2, DT)
    capture(game, "a2")
    first = _positions(game, "active_projectiles")
    game.frames(4, DT)
    capture(game, "a6")
    assert _positions(game, "active_projectiles") != first
    game.frames(6, DT)
    capture(game, "a12")
    game.frames(40, DT)
    capture(game, "gone")
    assert game.frame_errors == {}


def test_flying_object(make_game):
    game = make_game(flying=[(40.0, 34.0, 1, 2)])
    game.frames(2, DT)
    capture(game, "f2")
    first = _positions(game, "active_projectiles")
    assert first
    game.frames(5, DT)
    capture(game, "f7")
    assert _positions(game, "active_projectiles") != first
    game.frames(10, DT)
    capture(game, "f17")
    game.frames(30, DT)
    capture(game, "f47")
    assert game.frame_errors == {}


def test_thrown_objects_fly_and_land(make_game):
    game = make_game()
    game.frames(1, DT)
    mine = make_throw(game.client.x, game.client.y, 3, "bush", BUSH)
    theirs = make_throw(game.client.x - 6.0, game.client.y + 4.0, 3, "rock",
                        BUSH, owner_id=77)
    game.thrown_objects.append(mine)
    game.other_thrown_objects.append(theirs)
    game.frames(2, DT)
    capture(game, "t2")
    x0 = mine["x"]
    game.frames(3, DT)
    capture(game, "t5")
    assert mine["x"] > x0
    game.frames(4, DT)
    capture(game, "t9")
    game.frames(12, DT)
    capture(game, "landed")
    assert not game.thrown_objects and not game.other_thrown_objects
    assert game.frame_errors == {}


def test_bomb_fuse_and_blast(make_game):
    # pygserver relays the bomb with a 20-tick (one second) fuse.
    game = make_game(bombs=[(36.0, 36.0)])
    game.frames(3, DT)
    capture(game, "b3")
    assert game.active_bombs and not game.active_bombs[0].get("exploded")
    for tick in (8, 14, 18):
        game.frames(tick - (3 if tick == 8 else 8 if tick == 14 else 14), DT)
        capture(game, f"b{tick}")
    game.frames(6, DT)
    capture(game, "b24")
    assert any(b.get("exploded") for b in game.active_bombs) or not game.active_bombs
    game.frames(6, DT)
    capture(game, "b30")
    game.frames(20, DT)
    capture(game, "b50")
    assert game.frame_errors == {}


def test_server_explosion(make_game):
    game = make_game()
    game.frames(2, DT)
    game.server.send(build_explosion(0, 44, 18, 2, 1))
    game.frames(1, DT)
    capture(game, "e1")
    game.frames(4, DT)
    capture(game, "e5")
    game.frames(6, DT)
    capture(game, "e11")
    game.frames(20, DT)
    capture(game, "e31")
    assert game.frame_errors == {}


def test_level_change_with_objects_in_flight(make_game):
    game = make_game(arrows=[(26.0, 40.0, 1)], bombs=[(36.0, 36.0)],
                     flying=[(40.0, 34.0, 1, 2)],
                     extra_levels={"other.nw": _flat(3)})
    game.frames(1, DT)
    game.thrown_objects.append(
        make_throw(game.client.x, game.client.y, 3, "bush", BUSH))
    game.frames(3, DT)
    capture(game, "before")

    async def warp(world, level, x, y):
        await world.me.warp(level, x, y)
    game.server.run(lambda w: warp(w, "other.nw", 20.0, 20.0))
    game.frames(1, DT)
    capture(game, "warp1")
    game.frames(4, DT)
    capture(game, "warp5")
    game.frames(10, DT)
    capture(game, "warp15")
    assert game.client._current_level_name == "other.nw"
    game.server.run(lambda w: warp(w, "fixture.nw", 30.0, 30.0))
    game.frames(6, DT)
    capture(game, "back")
    assert game.frame_errors == {}


def test_objects_keep_moving_while_a_transition_holds_the_frame(make_game):
    """The reference keeps Adventure->timer() running while the loading
    screen is up (GuiCanvas.cpp:1540-1545): a held level transition freezes
    the picture, not the simulation."""
    game = make_game(arrows=[(26.0, 40.0, 1)], flying=[(40.0, 34.0, 1, 2)])
    game.frames(3, DT)
    capture(game, "free")
    client = game.client
    thrown = make_throw(client.x, client.y, 3, "bush", BUSH)
    game.thrown_objects.append(thrown)
    with _running(game):
        client._local_level_transition = "held.nw"
        client._local_level_transition_started = game.clock.frame_now()
    before = (_positions(game, "active_projectiles"), thrown["x"], thrown["y"])
    held_frame = game.last_frame.copy()
    game.frames(5, DT)
    capture(game, "held")
    assert (_positions(game, "active_projectiles"), thrown["x"],
            thrown["y"]) != before
    # ...while the screen shows the held picture.
    assert game.last_frame.get_view("2").raw == held_frame.get_view("2").raw
    client.release_local_transition()
    game.frames(4, DT)
    capture(game, "released")
    assert game.frame_errors == {}
