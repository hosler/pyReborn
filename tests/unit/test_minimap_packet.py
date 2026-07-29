"""PLO_MINIMAP parser coverage."""

from pyreborn.packet_codec.level import parse_minimap


def test_parse_minimap_csv_configuration():
    parsed = parse_minimap(b"worldmap.png,worldlevels.txt,12.5,-3")

    assert parsed == {
        "image": "worldmap.png",
        "levels_file": "worldlevels.txt",
        "x": 12.5,
        "y": -3.0,
    }


def test_parse_minimap_non_csv_preserves_raw_payload():
    payload = b"\x20\x21\xffraw pixels"

    assert parse_minimap(payload) == {
        "data": payload,
        "type": 0,
    }
