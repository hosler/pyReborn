"""Regression tests for reference-compatible directional link probes."""

import pytest

from pyreborn import Client


def _client_with_link(link):
    client = Client("localhost", 14900)
    client._current_level_name = "room.nw"
    client.links = {"room.nw": [link]}
    return client


@pytest.mark.parametrize("direction, position", [
    (0, (8.5, 9.0)),   # up
    (1, (10.0, 8.0)),  # left
    (2, (8.5, 6.5)),   # down
    (3, (7.0, 8.0)),   # right
])
def test_flush_contact_with_wall_door_triggers_in_each_direction(
        direction, position):
    link = {"x": 10, "y": 10, "width": 0, "height": 0,
            "dest_level": "inside.nw"}
    client = _client_with_link(link)
    client.player.x, client.player.y = position
    client.player.direction = direction

    assert client.check_link_collision() is link


def test_probe_wraps_coherently_across_gmap_segment_seam():
    link = {"x": 1, "y": 12, "width": 0, "height": 0,
            "dest_level": "inside.nw"}
    client = _client_with_link(link)
    client.player.x, client.player.y = 62.8, 10.0
    client.player.direction = 3

    assert client.check_link_collision() is link


def test_near_door_facing_away_does_not_trigger():
    link = {"x": 10, "y": 10, "width": 0, "height": 0,
            "dest_level": "inside.nw"}
    client = _client_with_link(link)
    client.player.x, client.player.y = 8.5, 9.0
    client.player.direction = 2

    assert client.check_link_collision() is None
