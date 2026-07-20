"""Regression tests for position-based level attribution."""

from pyreborn import Client


def _client_with_configured_grid() -> Client:
    client = Client("localhost", 14900)
    client.gmap_name = "world.gmap"
    client.gmap_width = 2
    client.gmap_height = 1
    client.gmap_grid = {(0, 0): "west.nw", (1, 0): "east.nw"}
    return client


def test_configured_grid_does_not_override_standalone_current_level():
    client = _client_with_configured_grid()
    client._current_level_name = "standalone.nw"
    client._pending_level_name = "east.nw"
    client.active_level = "east.nw"
    client.player.x = 70.0
    client.player.y = 5.0

    assert client.get_current_level_from_position() == "standalone.nw"


def test_current_gmap_segment_still_resolves_from_world_position():
    client = _client_with_configured_grid()
    client._current_level_name = "west.nw"
    client.player.x = 70.0
    client.player.y = 5.0

    assert client.get_current_level_from_position() == "east.nw"
