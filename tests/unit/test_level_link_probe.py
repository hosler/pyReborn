"""Regression tests for reference-compatible directional link probes."""

import pytest

from pyreborn import Client


def _client_with_link(link):
    client = Client("localhost", 14900)
    client._current_level_name = "room.nw"
    client.links = {"room.nw": [link]}
    return client


# TPlayer.cpp:6122 uses offsets (1.5,1), (.5,2), (1.5,3), (2.5,2).
@pytest.mark.parametrize("direction, position", [
    (0, (8.5, 9.0)),   # up
    (1, (9.5, 8.0)),  # left
    (2, (8.5, 7.0)),   # down
    (3, (7.5, 8.0)),   # right
])
def test_flush_contact_with_wall_door_triggers_in_each_direction(
        direction, position):
    link = {"x": 10, "y": 10, "width": 0, "height": 0,
            "dest_level": "inside.nw"}
    client = _client_with_link(link)
    client.player.x, client.player.y = position
    client.player.direction = direction

    assert client.check_link_collision() is link


def test_probe_does_not_wrap_onto_the_opposite_side_of_the_board():
    link = {"x": 1, "y": 12, "width": 0, "height": 0,
            "dest_level": "inside.nw"}
    client = _client_with_link(link)
    client.player.x, client.player.y = 62.8, 10.0
    client.player.direction = 3

    assert client.check_link_collision() is None


def test_near_door_facing_away_does_not_trigger():
    link = {"x": 10, "y": 10, "width": 0, "height": 0,
            "dest_level": "inside.nw"}
    client = _client_with_link(link)
    client.player.x, client.player.y = 8.5, 9.0
    client.player.direction = 2

    assert client.check_link_collision() is None
