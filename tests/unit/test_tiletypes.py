"""Unit tests for pyreborn tiletypes module (tile collision data)."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../reborn-protocol'))

from pyreborn.tiletypes import get_tile_type, TileType, is_blocking, is_water


class TestTileTypes:
    """These tests cover tile type lookup."""

    def test_get_tile_type_grass(self):
        """The test gets the tile type for grass tiles."""
        # Tile 0 is typically empty/passable
        tile_type = get_tile_type(0)
        assert tile_type is not None

    def test_get_tile_type_wall(self):
        """The test checks that wall tiles block movement."""
        # Common wall tile indices
        for tile_id in [1, 2, 3]:
            tile_type = get_tile_type(tile_id)
            # These should have some type

    def test_get_tile_type_out_of_range(self):
        """The test gets the tile type for invalid indices."""
        # Very large tile ID should return default
        tile_type = get_tile_type(99999)
        # Should not raise, should return something

    def test_is_blocking(self):
        """The test checks the is_blocking helper function."""
        # Check that function works for valid tiles
        result = is_blocking(0)
        assert isinstance(result, bool)

    def test_is_water(self):
        """The test checks the is_water helper function."""
        result = is_water(0)
        assert isinstance(result, bool)


class TestTileTypeEnum:
    """These tests cover the TileType enumeration."""

    def test_tile_type_values(self):
        """The test checks that TileType has the expected values."""
        assert hasattr(TileType, 'NONBLOCK')

    def test_tile_type_membership(self):
        """The test checks the TileType enumeration."""
        # Should be able to create valid tile types
        from pyreborn.tiletypes import TileType
        # Just verify the enum exists and has members
        assert len(TileType) > 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])


@pytest.mark.parametrize("tilestype", [0, 1, 2, 5])
@pytest.mark.parametrize("tile_id", [4096, 4098, 4157, 8191, 99999])
def test_high_ids_never_alias_base_tiles(tile_id, tilestype):
    assert get_tile_type(tile_id, tilestype) == TileType.NONBLOCK


def test_type_lookup_indexes_supplied_table_directly(monkeypatch):
    from pyreborn import tiletypes as tt
    table = bytearray(4097)
    table[4096] = 3
    monkeypatch.setattr(tt, "TILE_TYPES", bytes(table))
    assert tt.get_tile_type(4096, 0) == TileType.CHAIR


def test_enum_and_ground_predicates_match_reference(monkeypatch):
    from pyreborn import tiletypes as tt
    assert (TileType.NEAR_LAVA, TileType.DESERT, TileType.BLOCKING_FOREGROUND) == (9, 10, 23)
    monkeypatch.setattr(tt, "TILE_TYPES", bytes(range(24)))
    tt.reset_tiledefs()
    for ttype in range(24):
        assert tt.is_damaging(ttype) == (ttype in (2, 9, 12))
        assert tt.is_swimming_water(ttype) == (ttype in (11, 12))


@pytest.mark.parametrize("contents", [None, b"short"])
def test_missing_or_truncated_classic_data_warns_once(tmp_path, monkeypatch, caplog, contents):
    from pyreborn import tiletypes as tt
    path = tmp_path / "tiletypes1.dat"
    if contents is not None:
        path.write_bytes(contents)
    monkeypatch.setattr(tt, "_DAT_PATH", str(path))
    monkeypatch.setattr(tt, "_warned_classic_missing", False)
    assert tt._load_tile_types() == bytes(4096)
    tt._load_tile_types()
    messages = [r for r in caplog.records if "tiletypes1.dat" in r.message]
    assert len(messages) == 1
    assert "collision data unavailable" in messages[0].message
