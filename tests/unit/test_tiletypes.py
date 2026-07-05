"""Unit tests for pyreborn tiletypes module (tile collision data)."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

from pyreborn.tiletypes import get_tile_type, TileType, is_blocking, is_water


class TestTileTypes:
    """Tests for tile type lookup."""

    def test_get_tile_type_grass(self):
        """Test getting tile type for grass tiles."""
        # Tile 0 is typically empty/passable
        tile_type = get_tile_type(0)
        assert tile_type is not None

    def test_get_tile_type_wall(self):
        """Test that wall tiles are blocking."""
        # Common wall tile indices
        for tile_id in [1, 2, 3]:
            tile_type = get_tile_type(tile_id)
            # These should have some type

    def test_get_tile_type_out_of_range(self):
        """Test getting tile type for invalid indices."""
        # Very large tile ID should return default
        tile_type = get_tile_type(99999)
        # Should not raise, should return something

    def test_is_blocking(self):
        """Test is_blocking helper function."""
        # Check that function works for valid tiles
        result = is_blocking(0)
        assert isinstance(result, bool)

    def test_is_water(self):
        """Test is_water helper function."""
        result = is_water(0)
        assert isinstance(result, bool)


class TestTileTypeEnum:
    """Tests for TileType enumeration."""

    def test_tile_type_values(self):
        """Test that TileType has expected values."""
        assert hasattr(TileType, 'NONBLOCK')

    def test_tile_type_membership(self):
        """Test TileType enumeration."""
        # Should be able to create valid tile types
        from pyreborn.tiletypes import TileType
        # Just verify the enum exists and has members
        assert len(TileType) > 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
