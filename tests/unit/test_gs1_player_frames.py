"""GS1 player arrays must share playerx/playery's coordinate frame."""

from types import SimpleNamespace

import pytest

from pyreborn import Client
from pyreborn.gs1_client import ClientGS1


def _gmap_client():
    client = Client("localhost", 14900)
    client.gmap_width = client.gmap_height = 3
    client.gmap_grid.update({(1, 1): "chicken1.nw", (0, 1): "chicken2.nw"})
    client._current_level_name = "chicken1.nw"
    client.player.x, client.player.y = 89.0, 74.0
    return client


@pytest.mark.parametrize("position", [
    {},
    {"level": "chicken1.nw"},
    {"world_x": 93.0, "world_y": 74.0},
])
def test_gmap_players_share_player_position_frame(position):
    client = _gmap_client()
    client.players[2] = {"x": 29.0, "y": 10.0, "account": "other", **position}
    host = ClientGS1(client)._host
    ctx = SimpleNamespace(this_obj=None)

    players = host._player_list()
    assert (players[0]["x"], players[0]["y"]) == (89.0, 74.0)
    assert (players[1]["x"], players[1]["y"]) == (93.0, 74.0)
    assert (players[1]["x"] - players[0]["x"],
            players[1]["y"] - players[0]["y"]) == (4.0, 0.0)
    for axis, builtin in (("x", "playerx"), ("y", "playery")):
        assert host.get_builtin("players." + axis, [0], ctx) == host.get_builtin(
            builtin, [], ctx)
        assert host.get_builtin("players." + axis, [1], ctx) == players[1][axis]
    assert client.players[2] == {"x": 29.0, "y": 10.0, "account": "other", **position}


@pytest.mark.parametrize("position,expected", [
    ({"level": "chicken2.nw"}, (29.0, 74.0)),
    ({"level": "chicken1.nw", "world_x": 0.0, "world_y": 10.0}, (0.0, 10.0)),
    ({"world_x": 157.0}, (157.0, 74.0)),
])
def test_gmap_players_prefer_known_world_position_or_own_segment(position, expected):
    client = _gmap_client()
    client.players[2] = {"x": 29.0, "y": 10.0, **position}
    player = ClientGS1(client)._host._player_list()[1]
    assert (player["x"], player["y"]) == expected


def test_non_gmap_player_positions_are_unchanged():
    client = Client("localhost", 14900)
    client._current_level_name = "standalone.nw"
    client.player.x, client.player.y = 25.0, 10.0
    client.players[2] = {"x": 29.0, "y": 10.0}
    players = ClientGS1(client)._host._player_list()
    assert [(p["x"], p["y"]) for p in players] == [(25.0, 10.0), (29.0, 10.0)]
