"""The one-byte tile coordinate on the client's wire: PLO_PLAYERWARP /
PLAYERWARP2 X/Y in, classic PLPROP_X/Y (15/16) out.

Oracles:
* Server writes the warp X/Y with PropertyTileCoordinate::serialize and reads
  PLPROP_X/Y with ::deserialize (GServer-v2 origin/beta4 512b8918,
  server/src/player/PlayerClient.cpp:1262,1273;
  server/src/utilities/PropertySerializers.cpp:484-509): byte - 32 half-tiles,
  so 0x00..0x1F are -16..-0.5 tiles. read_gchar's clamp to 0 lost those.
* The reference client sends ``(char)(floorToInt(tiles * 2.0 + 0.5) + 0x20)``
  (Preagonal/FourPlay/quattroplay/src/TPlayer.cpp:279-282, 3213-3216): no
  0..223 clamp, so a negative position reaches the server.
"""

import pytest

from pyreborn.packets import (
    build_hurt_response,
    build_movement,
    build_player_props,
    parse_playerwarp,
    parse_playerwarp2,
)


@pytest.mark.parametrize("byte,tiles", [
    (0x00, -16.0), (0x0B, -10.5), (0x1F, -0.5), (0x20, 0.0), (0x5E, 31.0),
    (0xF8, 108.0), (0xFF, 111.5),
])
def test_playerwarp_reads_the_full_tile_range(byte, tiles):
    warp = parse_playerwarp(bytes((byte, byte)) + b"level.nw")
    assert (warp['x'], warp['y'], warp['level']) == (tiles, tiles, "level.nw")


def test_playerwarp2_reads_negative_tiles_and_keeps_the_rest():
    data = bytes((0x1F, 0x00, 50 + 32, 3 + 32, 4 + 32)) + b"world.gmap"
    warp = parse_playerwarp2(data)
    assert warp == {'x': -0.5, 'y': -16.0, 'z': 50, 'gmap_x': 3,
                    'gmap_y': 4, 'level': "world.gmap"}


@pytest.mark.parametrize("tiles,byte", [
    (-16.0, 0x00), (-0.5, 0x1F), (-0.26, 0x1F), (-0.25, 0x20), (0.0, 0x20),
    (111.5, 0xFF), (-11.0, 0x0B),   # 0x0A would end the packet
])
def test_classic_position_bytes_follow_the_reference_client(tiles, byte):
    movement = build_movement(tiles, tiles, direction=2, use_new_format=False)
    assert movement[2:] == bytes((15 + 32, byte, 16 + 32, byte))
    assert build_player_props(tiles, tiles) == bytes((15 + 32, byte, 16 + 32, byte))
    hurt = build_hurt_response(3.0, tiles, tiles, 2, use_new_format=False)
    assert hurt[-4:] == bytes((15 + 32, byte, 16 + 32, byte))
