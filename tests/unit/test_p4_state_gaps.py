"""State the P4 review found unpinned: each test fails under the one-line
mutation named in its docstring (the code is correct; these only guard it).

  link-arrival suppression      -> a warp that leaves link_arrival unset
  ChatInput / PrivateMessage    -> a close() that leaves its state behind
  first-ripple timestamp        -> last_ripple_time starting at 0.0
"""
import pygame
import pytest
from pyreborn.game import overlays
from offline_game import spy

BIG_LINK = "fixture.nw 32 28 8 8 34 30"   # lands inside its own rectangle


class _Keys(dict):
    def __missing__(self, key):
        return False


@pytest.fixture
def held(monkeypatch):
    keys = _Keys()
    monkeypatch.setattr(pygame.key, "get_pressed", lambda: keys)
    return keys


def _warps(game):
    """Link warps the game has fired so far."""
    return len(game._link_spy)


def _link_game(make_game, monkeypatch):
    game = make_game(player_xy=(30.0, 30.0), tiles=lambda tx, ty: 0,
                     links=[BIG_LINK])
    game.frames(3)
    game._link_spy = spy(monkeypatch, game, "_use_door_link")
    return game


def _walk(game, held, key, until, limit=40):
    """Hold `key` for ticks until `until()` is true."""
    held.clear()
    held[key] = True
    for _ in range(limit):
        if until():
            break
        game.ticks(1)
    held.clear()
    assert until(), "the walk never got there"


def test_link_warp_does_not_bounce_back_and_rearms_after_leaving(
        make_game, held, monkeypatch):
    game = _link_game(make_game, monkeypatch)
    arrival = game.arrival
    assert _warps(game) == 0 and not arrival.on_link

    # Step onto the link: one warp, landing inside the link's rectangle.
    _walk(game, held, pygame.K_RIGHT, lambda: _warps(game) == 1)
    assert arrival.on_link is True
    assert arrival.link_arrival == (game.client.x, game.client.y)
    assert (game.client.x, game.client.y) == (34.0, 30.0)

    # Still standing on the link we landed on: probing again must not warp.
    assert game._try_link_warp() is False
    assert _warps(game) == 1

    # The destination's links stream in late: for a moment none is under us.
    # Standing at the arrival spot the suppression must outlive that gap.
    saved = game.client.links
    game.client.links = {}
    assert game._try_link_warp() is False
    game.client.links = saved
    assert game._try_link_warp() is False
    assert _warps(game) == 1, "warped straight back onto the return link"

    # Walk off the link (>= 1.5 tiles from the arrival spot), then back on.
    _walk(game, held, pygame.K_RIGHT, lambda: game.client.check_link_collision() is None)
    assert arrival.link_arrival is None
    assert _warps(game) == 1
    _walk(game, held, pygame.K_LEFT, lambda: _warps(game) == 2)
    assert arrival.link_arrival == (game.client.x, game.client.y)


def test_chat_input_close_clears_typing_and_text(make_game):
    game = make_game()
    chat = game.chat
    chat.typing = True
    chat.input = "half a sentence"
    panel = overlays.find(game.overlays, "chat")
    assert panel.visible
    panel.close()
    assert chat.typing is False
    assert chat.input == ""
    assert not panel.visible


def test_private_message_close_clears_target(make_game):
    game = make_game()
    chat = game.chat
    chat.pm_target_id = 7
    chat.pm_input = "psst"
    panel = overlays.find(game.overlays, "pm")
    assert panel.visible
    panel.close()
    assert chat.pm_target_id is None
    assert not panel.visible


@pytest.mark.parametrize("clock_reads", [0.1, 3.0, 4.0e7])
def test_first_water_step_ripples_at_once_whatever_the_clock_reads(
        make_game, monkeypatch, clock_reads):
    from pyreborn.clock import Clock
    game = make_game()
    assert game.particles.ripples == []
    game.is_swimming = True
    monkeypatch.setattr(Clock, "frame_now", lambda self: clock_reads)
    game._render_water_ripples()
    assert len(game.particles.ripples) == 1
    assert game.particles.ripples[0]["time"] == clock_reads
    # ... and not again within half a second.
    game._render_water_ripples()
    assert len(game.particles.ripples) == 1
