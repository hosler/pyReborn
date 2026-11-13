"""Regression tests: level-link warps under scripted movement.

Bomber v6 runs disabledefmovement — the -Test/Movement GS2 weapon writes
player x/y from the VM every tick. That broke door links: _try_link_warp was
only called from _move() in the input path, which input.py skips entirely
while a script drives movement, so walking onto a level link no longer
warped. The -Test/Movement bytecode itself only does wall checks (onwall2/
hitwall) and gani updates, never link warps. The reference client warps
whenever the player's position enters a link rect regardless of what moved
them.

Fix under test: the frame loop calls ActionsMixin._check_scripted_link_warp()
after the script engines tick. On any position change while default_movement
is off it runs the same _try_link_warp path (rising-edge latch, arrival
suppression, _use_door_link invariants) as input-driven movement.
"""

import pytest


@pytest.fixture
def link_game(make_game):
    """``link_game(default_movement=False)``: (client, real offline game) in
    lobby.nw with an interior door link, rect (30,32)-(34,34), well away from
    level edges so it is never classified as a GMAP edge link, to house1.nw
    at (30, 30). The player faces down: the link probe is at (x+1.5, y+3.0)."""
    def build(default_movement=False):
        game = make_game(level="lobby.nw", extra_levels={"house1.nw": None},
                         links=["house1.nw 30 32 4 2 30 30"])
        game.gs1.default_movement = default_movement
        game.client.player.direction = 2
        return game.client, game
    return build


class TestScriptedMovementLinkWarp:
    def test_vm_position_write_onto_link_warps(self, link_game):
        c, h = link_game()

        # Off the link: probe runs (position changed from None) but no warp.
        c.player.x, c.player.y = 30.0, 20.0
        assert h._check_scripted_link_warp() is False
        assert c._current_level_name == "lobby.nw"

        # Script tick writes the player onto the link rect: must warp through
        # the normal door path.
        c.player.x, c.player.y = 30.0, 30.0
        assert h._check_scripted_link_warp() is True
        assert c._current_level_name == "house1.nw"
        assert (c.x, c.y) == (30.0, 30.0)

    def test_no_refire_at_warp_arrival(self, link_game):
        c, h = link_game()
        c.player.x, c.player.y = 30.0, 30.0
        assert h._check_scripted_link_warp() is True
        assert c._current_level_name == "house1.nw"

        # Same frame-loop probe again at the arrival point: no bounce-back
        # (position stamp + rising-edge latch/arrival suppression).
        assert h._check_scripted_link_warp() is False
        assert c._current_level_name == "house1.nw"

    def test_unchanged_position_short_circuits(self, link_game):
        c, h = link_game()
        c.player.x, c.player.y = 30.0, 20.0
        assert h._check_scripted_link_warp() is False

        calls = []
        original = c.check_link_collision
        c.check_link_collision = lambda: calls.append(1) or original()
        assert h._check_scripted_link_warp() is False  # position unchanged
        assert calls == []

    def test_default_movement_leaves_probe_inert(self, link_game):
        c, h = link_game(default_movement=True)
        c.player.x, c.player.y = 30.0, 30.0
        assert h._check_scripted_link_warp() is False
        assert c._current_level_name == "lobby.nw"

    def test_transition_in_flight_defers_probe(self, link_game):
        c, h = link_game()
        c._local_level_transition = "scroll"
        c.player.x, c.player.y = 30.0, 30.0
        assert h._check_scripted_link_warp() is False
        assert c._current_level_name == "lobby.nw"
