"""Unit tests for pyreborn Client class."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

from pyreborn import Client, Player


class TestClientCreation:
    """These tests cover Client instantiation."""

    def test_create_client(self):
        """The test creates a Client instance."""
        client = Client("localhost", 14900)
        assert client is not None
        assert client.host == "localhost"
        assert client.port == 14900

    def test_create_client_with_version(self):
        """The test creates a Client with a specific version."""
        client = Client("localhost", 14900, version="6.037")
        assert client.version == "6.037"

    def test_client_initial_state(self):
        """The test checks the initial Client state."""
        client = Client("localhost", 14900)
        assert client.connected is False
        assert client.authenticated is False

    def test_client_context_manager(self):
        """The test checks that a Client works as a context manager."""
        # Should not raise even if not connected
        with Client("localhost", 14900) as client:
            assert client is not None


class TestPlayerClass:
    """These tests cover the Player dataclass."""

    def test_player_creation(self):
        """The test creates a Player instance."""
        player = Player()
        assert player is not None

    def test_player_default_values(self):
        """The test checks the default Player attribute values."""
        player = Player()
        assert player.x == 0
        assert player.y == 0
        assert hasattr(player, 'nickname')

    def test_player_position(self):
        """The test sets the player position."""
        player = Player()
        player.x = 10.5
        player.y = 20.5
        assert player.x == 10.5
        assert player.y == 20.5


class TestClientPacketHandling:
    """These unit tests cover Client packet handling."""

    def test_client_has_handlers(self):
        """The test checks that Client has packet handlers."""
        client = Client("localhost", 14900)
        # Client should have handler methods
        assert hasattr(client, '_handle_packet') or hasattr(client, 'handle_packet')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
